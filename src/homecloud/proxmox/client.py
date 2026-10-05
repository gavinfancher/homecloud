from __future__ import annotations

import base64
import io
import ipaddress
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from urllib.parse import quote

from proxmoxer import ProxmoxAPI

from homecloud.config import settings
from homecloud.proxmox import seed

logger = logging.getLogger(__name__)

_VM_LIST_CACHE_TTL = 4.0
_LAN_IP_CACHE_TTL = 60.0

# Interfaces that never carry the VM's LAN address: the Tailscale tunnel and
# the bridges container runtimes hang off.  Loopback is matched exactly, so a
# real NIC whose name merely starts with "lo" is not skipped.
_NON_LAN_IFACES = ("tailscale", "docker", "br-", "veth", "virbr", "cni", "flannel")
# Tailscale hands out CGNAT addresses; those are the tailnet IP, not the LAN one.
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")
# Proxmox's limit on agent/file-write content.
_AGENT_WRITE_LIMIT = 61440
_MAC_FORMAT = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")
_MAC_RE = re.compile(r"=([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")


# Proxmox's own OUI; the rest is random. 2^24 addresses per node.
_MAC_PREFIX = "BC:24:11"


def _random_mac(used: set[str]) -> str:
    """A Proxmox-prefixed MAC that is not in *used* (lower-case MACs)."""
    while True:
        tail = ":".join(f"{secrets.randbelow(256):02X}" for _ in range(3))
        mac = f"{_MAC_PREFIX}:{tail}"
        if mac.lower() not in used:
            return mac


def _with_mac(net: str, mac: str) -> str:
    """``net0`` value with its MAC replaced, e.g. ``virtio=<mac>,bridge=vmbr0``."""
    if _MAC_RE.search(net) is None:
        raise ValueError(f"No MAC address in network config {net!r}")
    return _MAC_RE.sub(f"={mac}", net, count=1)


def _agent_text(data: str | None) -> str:
    """Guest output from ``exec-status``.

    Proxmox hands the guest's UTF-8 bytes through one byte per character, so
    non-ASCII output arrives as mojibake unless it is reassembled.
    """
    if not data:
        return ""
    try:
        return data.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return data


def _nic_mac(net: str) -> str | None:
    """MAC address out of a ``net0`` value like ``virtio=BC:24:11:..,bridge=vmbr0``."""
    match = _MAC_RE.search(net)
    return match.group(1) if match else None


class ProxmoxClient:
    """Thin wrapper around the Proxmox VE API."""

    _vm_list_cache: tuple[float, list[dict]] | None = None
    _vm_list_cache_lock = threading.Lock()
    # vmid -> (fetched_at, ip or None).  Negative results are cached too, so a
    # VM without a responding guest agent is not re-probed on every dashboard poll.
    _lan_ip_cache: dict[int, tuple[float, str | None]] = {}
    _lan_ip_cache_lock = threading.Lock()

    def __init__(self) -> None:
        self._api = ProxmoxAPI(
            settings.proxmox_host,
            user=settings.proxmox_user,
            token_name=settings.proxmox_token_name,
            token_value=settings.proxmox_token_value,
            verify_ssl=settings.proxmox_verify_ssl,
        )
        self.node = settings.proxmox_node
        self.storage = settings.proxmox_storage
        # Directory storage for seed ISOs and downloaded cloud images.
        self.image_storage = settings.proxmox_image_storage

    @property
    def api(self) -> ProxmoxAPI:
        return self._api

    def list_templates(self) -> list[dict]:
        templates = []
        for vm in self._api.nodes(self.node).qemu.get():
            vmid = vm["vmid"]
            config = self._api.nodes(self.node).qemu(vmid).config.get()
            if config.get("template") == 1:
                templates.append(
                    {
                        "vmid": vmid,
                        "name": vm.get("name", f"vm-{vmid}"),
                        "status": vm.get("status"),
                    }
                )
        return templates

    @staticmethod
    def invalidate_vm_list_cache() -> None:
        with ProxmoxClient._vm_list_cache_lock:
            ProxmoxClient._vm_list_cache = None

    @staticmethod
    def invalidate_lan_ip_cache(vmid: int | None = None) -> None:
        with ProxmoxClient._lan_ip_cache_lock:
            if vmid is None:
                ProxmoxClient._lan_ip_cache.clear()
            else:
                ProxmoxClient._lan_ip_cache.pop(vmid, None)

    def list_vms(self, *, use_cache: bool = True) -> list[dict]:
        now = time.time()
        if use_cache:
            with ProxmoxClient._vm_list_cache_lock:
                cached = ProxmoxClient._vm_list_cache
                if cached and now - cached[0] < _VM_LIST_CACHE_TTL:
                    return [dict(v) for v in cached[1]]

        vms = []
        for vm in self._api.nodes(self.node).qemu.get():
            if vm.get("template") == 1:
                continue
            vms.append(self._vm_from_list_entry(vm))

        with ProxmoxClient._vm_list_cache_lock:
            ProxmoxClient._vm_list_cache = (now, vms)
        return [dict(v) for v in vms]

    def _vm_from_list_entry(self, vm: dict) -> dict:
        """Build a VM summary from the cluster list response (no per-VM config call)."""
        memory_mb = vm.get("maxmem")
        if memory_mb:
            memory_mb = memory_mb // (1024 * 1024)
        disk_gb = None
        if vm.get("maxdisk"):
            disk_gb = max(1, round(vm["maxdisk"] / (1024 ** 3)))
        return {
            "vmid": vm["vmid"],
            "name": vm.get("name", f"vm-{vm['vmid']}"),
            "status": vm.get("status"),
            "cpus": vm.get("cpus"),
            "cores": vm.get("cpus"),
            "maxmem": vm.get("maxmem"),
            "memory_mb": memory_mb,
            "disk_gb": disk_gb,
            "uptime": vm.get("uptime", 0),
            "node": self.node,
            "pid": vm.get("pid"),
        }

    def get_vm(self, vmid: int) -> dict | None:
        for vm in self._api.nodes(self.node).qemu.get():
            if vm["vmid"] != vmid:
                continue
            config = self._api.nodes(self.node).qemu(vmid).config.get()
            if config.get("template") == 1:
                return None
            return self.enrich_vm(vm, config)
        return None

    def enrich_vm(self, vm: dict, config: dict | None = None) -> dict:
        if config is None:
            config = self._api.nodes(self.node).qemu(vm["vmid"]).config.get()
        disk_gb = self._disk_gb_from_config(config)
        return {
            "vmid": vm["vmid"],
            "name": vm.get("name", f"vm-{vm['vmid']}"),
            "status": vm.get("status"),
            "cpus": vm.get("cpus") or config.get("cores"),
            "cores": vm.get("cpus") or config.get("cores"),
            "maxmem": vm.get("maxmem"),
            "memory_mb": config.get("memory") or vm.get("maxmem"),
            "disk_gb": disk_gb,
            "uptime": vm.get("uptime", 0),
            "node": self.node,
            "pid": vm.get("pid"),
        }

    @staticmethod
    def _disk_gb_from_config(config: dict) -> int | None:
        scsi0 = config.get("scsi0", "")
        match = re.search(r"size=(\d+)G", scsi0)
        return int(match.group(1)) if match else None

    def next_vmid(self, start: int = 500) -> int:
        existing = {vm["vmid"] for vm in self._api.cluster.resources.get(type="vm")}
        vmid = start
        while vmid in existing:
            vmid += 1
        return vmid

    def clone_template(
        self,
        template_id: int,
        vmid: int,
        name: str,
        *,
        full: bool = True,
    ) -> str:
        task = self._api.nodes(self.node).qemu(template_id).clone.post(
            newid=vmid,
            name=name,
            full=1 if full else 0,
            storage=self.storage,
        )
        return task

    # ------------------------------------------------------------------
    # Cloud-init seed ISOs (NoCloud) — see homecloud.proxmox.seed
    # ------------------------------------------------------------------

    def _require_content(self, content: str) -> None:
        """Fail early, with the fix, when the image storage can't hold *content*."""
        for entry in self._api.storage.get():
            if entry.get("storage") != self.image_storage:
                continue
            allowed = (entry.get("content") or "").split(",")
            if content in allowed:
                return
            raise RuntimeError(
                f"Proxmox storage '{self.image_storage}' does not allow '{content}' content. "
                f"Enable it under Datacenter → Storage → {self.image_storage} → Content "
                f"(or `pvesm set {self.image_storage} --content "
                f"{','.join([*filter(None, allowed), content])}` on the node)."
            )
        raise RuntimeError(f"Proxmox storage '{self.image_storage}' does not exist")

    def _storage_content(self):
        return self._api.nodes(self.node).storage(self.image_storage).content

    def volume_exists(self, volid: str) -> bool:
        content = volid.split(":", 1)[1].split("/", 1)[0] if ":" in volid else None
        entries = self._storage_content().get(**({"content": content} if content else {}))
        return any(e.get("volid") == volid for e in entries)

    def delete_volume(self, volid: str) -> None:
        # The volid contains ":" and "/"; encode it so it stays one path segment.
        task = self._storage_content()(quote(volid, safe="")).delete()
        if isinstance(task, str) and task.startswith("UPID:"):
            self.wait_for_task(task, timeout=120)

    def upload_iso(self, filename: str, data: bytes) -> str:
        """Upload *data* as ``iso`` content and return its volume id."""
        self._require_content("iso")
        buf = io.BytesIO(data)
        # proxmoxer names the multipart part after the file object's .name.
        buf.name = filename
        task = self._api.nodes(self.node).storage(self.image_storage).upload.post(
            content="iso", filename=buf
        )
        if task:
            self.wait_for_task(task, timeout=120)
        return f"{self.image_storage}:iso/{filename}"

    def attach_seed(self, vmid: int, *, hostname: str, user_data: str) -> str:
        """Give *vmid* its cloud-init data as a NoCloud seed ISO on ``ide2``.

        Clones inherit the template's Proxmox cloud-init drive on ``ide2``
        (and, on older templates, a ``cicustom`` snippet reference).  Both are
        removed first: two NoCloud sources would race, and the seed ISO carries
        the complete user-data, meta-data and network config on its own.
        """
        config = self.get_vm_config(vmid)
        mac = _nic_mac(config.get("net0", ""))
        if mac is None:
            raise RuntimeError(f"VM {vmid} has no net0 MAC address to write network config for")

        iso = seed.build_seed_iso(
            user_data=user_data,
            meta_data=seed.render_meta_data(hostname=hostname),
            network_config=seed.render_network_config(mac),
        )
        volid = self.upload_iso(seed.seed_iso_filename(vmid), iso)

        stale = [key for key in ("cicustom", "ciuser", "sshkeys", "ipconfig0") if key in config]
        if "cloudinit" in config.get("ide2", ""):
            stale.insert(0, "ide2")
        if stale:
            self._api.nodes(self.node).qemu(vmid).config.put(delete=",".join(stale))
        self._api.nodes(self.node).qemu(vmid).config.put(ide2=f"{volid},media=cdrom")
        return volid

    def detach_seed(self, vmid: int) -> None:
        """Eject the seed ISO and delete it from storage.

        Once cloud-init has run the seed is dead weight — and the deploy seed
        holds the Tailscale auth key, so it should not linger on the node.
        Ejecting (rather than removing the drive) works on a running VM.  Only
        the eject is required — a template must not reference the ISO — so a
        failed delete is logged rather than raised.
        """
        config = self.get_vm_config(vmid)
        filename = seed.seed_iso_filename(vmid)
        if filename in config.get("ide2", ""):
            self._api.nodes(self.node).qemu(vmid).config.put(ide2="none,media=cdrom")
        try:
            self.delete_seed(vmid)
        except Exception:  # noqa: BLE001
            logger.warning("Could not delete seed ISO for VM %s", vmid, exc_info=True)

    def delete_seed(self, vmid: int) -> None:
        """Delete *vmid*'s seed ISO from storage if it is still there."""
        volid = f"{self.image_storage}:iso/{seed.seed_iso_filename(vmid)}"
        if self.volume_exists(volid):
            self.delete_volume(volid)

    def used_macs(self) -> set[str]:
        """Every NIC MAC on the node's VMs and templates, lower-cased."""
        macs: set[str] = set()
        for vm in self._api.nodes(self.node).qemu.get():
            config = self._api.nodes(self.node).qemu(vm["vmid"]).config.get()
            for key, value in config.items():
                if key.startswith("net") and isinstance(value, str):
                    mac = _nic_mac(value)
                    if mac:
                        macs.add(mac.lower())
        return macs

    def assign_unique_mac(self, vmid: int, mac: str | None = None) -> str:
        """Give *vmid*'s ``net0`` a MAC no other VM on the node uses.

        Two VMs sharing a MAC get the same DHCP lease — the same IP — so every
        clone is re-addressed explicitly rather than trusting the clone to.
        *mac* keeps a known address (a rebuild that must keep its DHCP
        reservation); it is refused if any VM on the node still has it.
        """
        net0 = self.get_vm_config(vmid).get("net0", "")
        # The clone's current MAC counts as used too: it may be a copy of
        # another VM's, and the new one must differ from both.
        used = self.used_macs()
        if mac is not None:
            if not _MAC_FORMAT.fullmatch(mac):
                raise ValueError(f"Not a MAC address: {mac!r}")
            if mac.lower() in used:
                raise ValueError(f"MAC {mac} is still in use by a VM on the node")
            mac = mac.upper()
        else:
            mac = _random_mac(used)
        self._api.nodes(self.node).qemu(vmid).config.put(net0=_with_mac(net0, mac))
        return mac

    def resize_disk(self, vmid: int, disk: str, size_gb: int) -> None:
        self._api.nodes(self.node).qemu(vmid).resize.put(disk=disk, size=f"+{size_gb}G")

    def grow_disk(self, vmid: int, disk: str, target_gb: int) -> None:
        """Grow *disk* to *target_gb*; never shrinks (Proxmox can't)."""
        self._api.nodes(self.node).qemu(vmid).resize.put(disk=disk, size=f"{target_gb}G")

    def set_resources(self, vmid: int, *, cores: int, memory_mb: int) -> None:
        self._api.nodes(self.node).qemu(vmid).config.put(cores=cores, memory=memory_mb)

    def start(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).status.start.post()

    def stop(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).status.stop.post()

    def suspend(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).status.suspend.post()

    def resume(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).status.resume.post()

    def convert_to_template(self, vmid: int) -> None:
        self._api.nodes(self.node).qemu(vmid).template.post()

    def wait_for_task(self, upid: str, *, timeout: int = 600, poll: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._api.nodes(self.node).tasks(upid).status.get()
            if status.get("status") == "stopped":
                if status.get("exitstatus") != "OK":
                    raise RuntimeError(f"Proxmox task {upid} failed: {status}")
                return
            time.sleep(poll)
        raise TimeoutError(f"Proxmox task {upid} timed out after {timeout}s")

    # ------------------------------------------------------------------
    # Cloud image import
    # ------------------------------------------------------------------

    def download_cloud_image(
        self,
        url: str,
        filename: str,
        *,
        sha256: str | None = None,
        timeout: int = 1800,
    ) -> str:
        """Have the node fetch a distro cloud image as ``import`` content.

        Proxmox verifies the checksum itself and discards the download when it
        does not match, so a bad transfer never lands in the cache.  Returns
        the volume id.
        """
        self._require_content("import")
        params: dict = {"content": "import", "filename": filename, "url": url}
        if sha256:
            params["checksum"] = sha256.lower()
            params["checksum-algorithm"] = "sha256"
        task = self._api.nodes(self.node).storage(self.image_storage)("download-url").post(
            **params
        )
        self.wait_for_task(task, timeout=timeout)
        return f"{self.image_storage}:import/{filename}"

    def create_vm(
        self,
        vmid: int,
        name: str,
        *,
        cores: int = 2,
        memory_mb: int = 2048,
    ) -> str:
        """Create an empty VM shell suitable for a cloud image disk."""
        return self._api.nodes(self.node).qemu.post(
            vmid=vmid,
            name=name,
            cores=cores,
            memory=memory_mb,
            net0=f"virtio,bridge={settings.proxmox_bridge}",
            scsihw="virtio-scsi-pci",
            ostype="l26",
            agent=1,
            serial0="socket",
            vga="serial0",
        )

    def import_cloud_image_disk(self, vmid: int, volid: str, *, timeout: int = 1800) -> None:
        """Import a downloaded cloud image as the VM's scsi0 boot disk."""
        task = self._api.nodes(self.node).qemu(vmid).config.post(
            scsi0=f"{self.storage}:0,import-from={volid}",
            boot="order=scsi0",
        )
        if task:
            self.wait_for_task(task, timeout=timeout)

    def get_vm_config(self, vmid: int) -> dict:
        return self._api.nodes(self.node).qemu(vmid).config.get()

    def delete_vm(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).delete()

    def guest_run(
        self,
        vmid: int,
        command: list[str],
        *,
        timeout: int = 300,
        check_cancel: Callable[[], None] | None = None,
    ) -> dict:
        """Run a command in the guest and wait for it to exit.

        ``agent exec`` only returns a pid; the result has to be collected from
        ``agent exec-status``.  Returns ``{"exitcode", "out", "err"}``.
        *check_cancel* is called on every poll and may raise to stop waiting
        (the command itself keeps running in the guest).
        """
        started = self._api.nodes(self.node).qemu(vmid).agent("exec").post(command=command)
        pid = started.get("pid") if isinstance(started, dict) else None
        if pid is None:
            return {"exitcode": 0, "out": "", "err": ""}

        deadline = time.time() + timeout
        while time.time() < deadline:
            if check_cancel is not None:
                check_cancel()
            status = self._api.nodes(self.node).qemu(vmid).agent("exec-status").get(pid=pid)
            if status.get("exited"):
                return {
                    "exitcode": status.get("exitcode", 0),
                    "out": _agent_text(status.get("out-data")),
                    "err": _agent_text(status.get("err-data")),
                }
            time.sleep(2)
        raise TimeoutError(f"Guest command on VM {vmid} timed out after {timeout}s")

    def guest_write_file(self, vmid: int, path: str, content: str) -> None:
        """Write *content* to *path* in the guest through the agent.

        The content is base64-encoded here (``encode=0``): Proxmox's own
        encoding chokes on non-ASCII text.  A single write is capped at 60 KiB
        of base64; larger content has to go through cloud-init instead.
        """
        encoded = base64.b64encode(content.encode()).decode()
        if len(encoded) > _AGENT_WRITE_LIMIT:
            raise ValueError(
                f"{path} is too large for one guest agent write "
                f"({len(encoded)} bytes encoded, limit {_AGENT_WRITE_LIMIT})"
            )
        self._api.nodes(self.node).qemu(vmid).agent("file-write").post(
            file=path, content=encoded, encode=0
        )

    def wait_for_guest_file(
        self,
        vmid: int,
        path: str,
        *,
        timeout: int = 900,
        check_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Block until *path* exists in the guest (used for build-done markers).

        *check_cancel* is called on every poll and may raise to abort the wait —
        without it a build ignores the console's Cancel button until it times out.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check_cancel is not None:
                check_cancel()
            try:
                result = self.guest_run(vmid, ["test", "-f", path], timeout=30)
                if result["exitcode"] == 0:
                    return
            except Exception:  # agent not up yet, or command raced with boot
                pass
            time.sleep(5)
        raise TimeoutError(
            f"Timed out waiting for {path} on VM {vmid}. The guest agent never "
            "answered, so cloud-init either failed early or never finished — "
            f"check the serial console with `qm terminal {vmid}` on the node."
        )

    def wait_for_guest_agent(
        self,
        vmid: int,
        *,
        timeout: int = 180,
        check_cancel: Callable[[], None] | None = None,
    ) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check_cancel is not None:
                check_cancel()
            try:
                self._api.nodes(self.node).qemu(vmid).agent("ping").post()
                return
            except Exception:
                time.sleep(3)
        raise TimeoutError(f"Guest agent not ready on VM {vmid}")

    def prepare_for_template(self, vmid: int) -> None:
        """Strip per-machine identity so clones boot as distinct hosts.

        Every file cleared here is an identity a clone must not inherit:

        - ``/etc/machine-id`` is the big one.  systemd-networkd derives both the
          DHCPv4 IAID and the DUID from it, so clones that share a machine-id
          send a byte-identical DHCP client identifier and the DHCP server
          hands them all the *same lease* — several VMs on one IP.
        - ``/etc/hostname`` because cloud-init brings the network up (and fires
          the clone's first DHCP request) before its hostname module runs.
        - SSH host keys and Tailscale node state are cleared defensively;
          cloud-init already regenerates host keys per instance, but a template
          should not ship identity a clone might reuse.

        The command is run to completion and followed by ``sync``: the caller
        hard-stops the VM immediately afterwards, and without an explicit
        flush the truncations would still be in the page cache when the power
        is cut, leaving the template with its identity intact.
        """
        self.wait_for_guest_agent(vmid)
        result = self.guest_run(
            vmid,
            [
                "bash",
                "-c",
                "cloud-init clean --logs --seed && "
                "truncate -s 0 /etc/machine-id && "
                "rm -f /var/lib/dbus/machine-id && "
                "truncate -s 0 /etc/hostname && "
                "sed -i '/127\\.0\\.1\\.1/d' /etc/hosts && "
                "rm -rf /var/lib/cloud/instances/* && "
                "rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && "
                "rm -rf /var/lib/tailscale/* && "
                "rm -rf /var/lib/systemd/network/ /run/systemd/netif/leases/* && "
                "sync",
            ],
        )
        if result["exitcode"] != 0:
            raise RuntimeError(
                f"Template sysprep failed on VM {vmid} (exit {result['exitcode']}): "
                f"{result['err'].strip() or result['out'].strip()}. Refusing to convert "
                f"a VM that still carries its machine-id to a template."
            )

    @staticmethod
    def _is_lan_ipv4(ip: str) -> bool:
        """True for an address on the home LAN — not loopback, tailnet, or link-local."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if addr.version != 4:
            return False
        if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            return False
        return addr not in _TAILSCALE_CGNAT

    @staticmethod
    def _lan_ip_from_interfaces(interfaces) -> str | None:
        """Pick the LAN IPv4 out of a guest-agent ``network-get-interfaces`` payload."""
        if isinstance(interfaces, dict) and "result" in interfaces:
            interfaces = interfaces["result"]
        for iface in interfaces or []:
            name = (iface.get("name") or "").lower()
            if name == "lo" or name.startswith(_NON_LAN_IFACES):
                continue
            for addr in iface.get("ip-addresses", []):
                if addr.get("ip-address-type") != "ipv4":
                    continue
                ip = addr.get("ip-address", "")
                if ProxmoxClient._is_lan_ipv4(ip):
                    return ip
        return None

    def _query_lan_ip(self, vmid: int) -> str | None:
        interfaces = self._api.nodes(self.node).qemu(vmid).agent("network-get-interfaces").get()
        return self._lan_ip_from_interfaces(interfaces)

    def get_lan_ip(self, vmid: int, *, use_cache: bool = True) -> str | None:
        """LAN address of a running VM, or None when the guest agent can't answer.

        Cached (including misses) for ``_LAN_IP_CACHE_TTL`` so listing instances
        does not hit the guest agent of every VM on each poll.
        """
        now = time.time()
        if use_cache:
            with ProxmoxClient._lan_ip_cache_lock:
                cached = ProxmoxClient._lan_ip_cache.get(vmid)
                if cached and now - cached[0] < _LAN_IP_CACHE_TTL:
                    return cached[1]
        try:
            ip = self._query_lan_ip(vmid)
        except Exception:  # noqa: BLE001 — agent down or VM stopped; not an error here
            logger.debug("LAN IP lookup failed for VM %s", vmid, exc_info=True)
            ip = None
        with ProxmoxClient._lan_ip_cache_lock:
            ProxmoxClient._lan_ip_cache[vmid] = (now, ip)
        return ip

    def wait_for_vm_ip(
        self,
        vmid: int,
        *,
        timeout: int = 180,
        check_cancel: Callable[[], None] | None = None,
    ) -> str:
        """Wait for the DHCP-assigned LAN IP via the QEMU guest agent."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check_cancel is not None:
                check_cancel()
            try:
                self.wait_for_guest_agent(vmid, timeout=10)
                ip = self._query_lan_ip(vmid)
                if ip:
                    with ProxmoxClient._lan_ip_cache_lock:
                        ProxmoxClient._lan_ip_cache[vmid] = (time.time(), ip)
                    return ip
            except Exception:
                pass
            time.sleep(5)
        raise TimeoutError(f"Could not get IP for VM {vmid} within {timeout}s")
