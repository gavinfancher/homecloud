"""Everything homecloud asks of Proxmox, all through its API with one API token. No SSH.

Every VM homecloud creates goes in the Proxmox pool `homecloud` and is tagged `homecloud`. The
API token only has rights on that pool (see the README), and homecloud only touches VMs it has
a row for, so the rest of the node (the k8s nodes, the DC, ...) is out of its reach.
"""

import io
import ipaddress
import time
from functools import cache
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

import requests
from proxmoxer import ProxmoxAPI

from app import config

TAG = "homecloud"
# Tailscale and container bridges carry addresses that aren't the VM's LAN IP.
_SKIP_IFACES = ("lo", "tailscale", "docker", "br-", "veth", "cni", "flannel", "loopback")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class PveError(Exception):
    pass


@cache
def api() -> ProxmoxAPI:
    user, _, token_name = config.PROXMOX_TOKEN_ID.partition("!")
    return ProxmoxAPI(config.PROXMOX_HOST, user=user, token_name=token_name,
                      token_value=config.PROXMOX_TOKEN_SECRET, verify_ssl=config.PROXMOX_VERIFY_TLS,
                      timeout=60)


def node():
    return api().nodes(config.PROXMOX_NODE)


def qemu(vmid: int):
    return node().qemu(vmid)


def wait_task(upid: str, timeout: int = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = node().tasks(upid).status.get()
        if status.get("status") == "stopped":
            if status.get("exitstatus") != "OK":
                raise PveError(f"Proxmox task failed: {status.get('exitstatus')}")
            return
        time.sleep(2)
    raise PveError(f"Proxmox task still running after {timeout}s: {upid}")


# ---------- reading ----------

def status_by_vmid() -> dict[int, dict]:
    """Every VM on the cluster, in one call: {vmid: {status, uptime, name, ...}}."""
    return {r["vmid"]: r for r in api().cluster.resources.get(type="vm")}


def exists(vmid: int) -> bool:
    return vmid in status_by_vmid()


def free_vmid(start: int, also_taken: set[int]) -> int:
    """The lowest id at or above *start* that no VM on the cluster uses.

    Asked of /cluster/nextid, which checks every VM, including ones this token can't see (it
    only has rights on the homecloud pool, so cluster/resources hides the rest).
    """
    vmid = start
    for _ in range(1000):
        if vmid not in also_taken:
            try:
                return int(api().cluster.nextid.get(vmid=vmid))
            except Exception as e:
                if "already exists" not in str(e):
                    raise
        vmid += 1
    raise PveError(f"No free VM id from {start}")


def lan_ip(vmid: int) -> str | None:
    """The VM's LAN IPv4, from the guest agent. None if the agent isn't answering yet."""
    try:
        result = qemu(vmid).agent("network-get-interfaces").get()
    except Exception:
        return None
    for iface in result.get("result", []) if isinstance(result, dict) else result or []:
        name = (iface.get("name") or "").lower()
        if name.startswith(_SKIP_IFACES):
            continue
        for addr in iface.get("ip-addresses", []):
            if addr.get("ip-address-type") != "ipv4":
                continue
            try:
                ip = ipaddress.ip_address(addr.get("ip-address", ""))
            except ValueError:
                continue
            if not (ip.is_loopback or ip.is_link_local or ip in _CGNAT):
                return str(ip)
    return None


# ---------- files on the node ----------

def _storage():
    return node().storage(config.PROXMOX_FILE_STORAGE)


def volume_exists(volid: str) -> bool:
    content = volid.split(":", 1)[1].split("/", 1)[0]
    return any(e.get("volid") == volid for e in _storage().content.get(content=content))


def delete_volume(volid: str) -> None:
    if volume_exists(volid):
        task = _storage().content(quote(volid, safe="")).delete()
        if isinstance(task, str) and task.startswith("UPID:"):
            wait_task(task, timeout=120)


def upload_iso(filename: str, data: bytes) -> str:
    volid = f"{config.PROXMOX_FILE_STORAGE}:iso/{filename}"
    delete_volume(volid)  # a leftover from an earlier try
    buf = io.BytesIO(data)
    buf.name = filename  # proxmoxer names the multipart file after this
    task = _storage().upload.post(content="iso", filename=buf)
    if task:
        wait_task(task, timeout=120)
    return volid


def download(url: str, content: str, filename: str, sha256: str | None = None) -> str:
    """Have the node fetch *url* into its file storage, once. Returns the volume id.

    Proxmox checks the checksum itself and throws the file away if it doesn't match.
    """
    volid = f"{config.PROXMOX_FILE_STORAGE}:{content}/{filename}"
    if volume_exists(volid):
        return volid
    params = {"content": content, "filename": filename, "url": url}
    if sha256:
        params |= {"checksum": sha256, "checksum-algorithm": "sha256"}
    wait_task(_storage()("download-url").post(**params), timeout=3600)
    return volid


def ubuntu_image() -> str:
    """The pinned Ubuntu cloud image, downloaded on first use. Returns its volume id."""
    url = config.UBUNTU_IMAGE_URL
    path = PurePosixPath(urlparse(url).path)
    # The release folder (release-20261016) keeps builds apart. Proxmox wants .qcow2 for
    # imports, and Ubuntu's .img cloud images are qcow2 inside.
    filename = f"{path.parent.name}-{path.stem}.qcow2"
    if volume_exists(f"{config.PROXMOX_FILE_STORAGE}:import/{filename}"):
        return f"{config.PROXMOX_FILE_STORAGE}:import/{filename}"
    sums = requests.get(url.rsplit("/", 1)[0] + "/SHA256SUMS", timeout=30)
    sums.raise_for_status()
    for line in sums.text.splitlines():
        digest, _, name = line.partition(" ")
        if name.lstrip(" *") == path.name:
            return download(url, "import", filename, digest.lower())
    raise PveError(f"{path.name} isn't listed in its SHA256SUMS")


def virtio_iso() -> str:
    return download(config.VIRTIO_ISO_URL, "iso", PurePosixPath(urlparse(config.VIRTIO_ISO_URL).path).name)


# ---------- creating ----------

def create_ubuntu(vmid: int, name: str, cores: int, memory_mb: int, disk_gb: int, seed: str) -> None:
    """A VM whose disk is the cloud image, with the seed ISO in its CD drive."""
    image = ubuntu_image()
    disk = config.PROXMOX_DISK_STORAGE
    wait_task(node().qemu.post(
        vmid=vmid, name=name, pool=config.PROXMOX_POOL, tags=TAG, ostype="l26", machine="q35", cpu="host",
        cores=cores, memory=memory_mb, agent="enabled=1",
        scsihw="virtio-scsi-single", scsi0=f"{disk}:0,import-from={image},discard=on,iothread=1",
        ide2=f"{seed},media=cdrom", boot="order=scsi0",
        net0=f"virtio,bridge={config.PROXMOX_BRIDGE}",
        serial0="socket", vga="serial0",  # cloud images talk on the serial console
    ), timeout=900)
    # The cloud image is a few GB; grow it to the size asked for. Ubuntu grows its filesystem
    # to fit on first boot.
    wait_task(qemu(vmid).resize.put(disk="scsi0", size=f"{disk_gb}G"), timeout=300)


def create_windows(vmid: int, name: str, cores: int, memory_mb: int, disk_gb: int, answer: str) -> None:
    """Windows 11 wants UEFI with Secure Boot, a TPM 2.0 and q35. SATA disk and an Intel NIC,
    so Setup has drivers for both without any extra disc. The answer file and the VirtIO tools
    go in the other CD drives."""
    disk = config.PROXMOX_DISK_STORAGE
    virtio = virtio_iso()
    wait_task(node().qemu.post(
        vmid=vmid, name=name, pool=config.PROXMOX_POOL, tags=TAG, ostype="win11", machine="q35", bios="ovmf", cpu="host",
        cores=cores, memory=memory_mb, agent="enabled=1",
        efidisk0=f"{disk}:1,efitype=4m,pre-enrolled-keys=1",
        tpmstate0=f"{disk}:1,version=v2.0",
        sata0=f"{disk}:{disk_gb},discard=on",
        net0=f"e1000e,bridge={config.PROXMOX_BRIDGE}",
        ide2=f"{config.WINDOWS_ISO},media=cdrom",
        ide0=f"{answer},media=cdrom",
        ide1=f"{virtio},media=cdrom",
        boot="order=sata0;ide2",
    ), timeout=900)


# ---------- power ----------

def status(vmid: int) -> str:
    return qemu(vmid).status.current.get().get("status", "unknown")


def start(vmid: int) -> None:
    if status(vmid) != "running":
        wait_task(qemu(vmid).status.start.post(), timeout=120)


def press_enter(vmid: int, times: int = 15) -> None:
    """The Windows DVD says "Press any key to boot from CD or DVD" for a few seconds and then
    gives up. Press Enter for it a few times; extra presses land before Setup listens."""
    for _ in range(times):
        try:
            qemu(vmid).sendkey.put(key="ret")
        except Exception:
            pass
        time.sleep(1)


def shutdown(vmid: int) -> None:
    """Ask the guest to shut down (ACPI, or the agent). Returns once Proxmox has asked."""
    if status(vmid) == "running":
        qemu(vmid).status.shutdown.post(timeout=120, forceStop=1)


def stop(vmid: int) -> None:
    if status(vmid) == "running":
        wait_task(qemu(vmid).status.stop.post(), timeout=120)


def eject(vmid: int, *drives: str) -> None:
    """Empty CD drives. Works on a running VM, unlike removing the drive."""
    qemu(vmid).config.put(**{d: "none,media=cdrom" for d in drives})


def destroy(vmid: int) -> None:
    """Delete the VM and its disks. It must be stopped."""
    wait_task(qemu(vmid).delete(purge=1, **{"destroy-unreferenced-disks": 1}), timeout=600)
