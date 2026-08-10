from __future__ import annotations

import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import requests
from proxmoxer import ProxmoxAPI

from homecloud.config import settings

_VM_LIST_CACHE_TTL = 4.0


class ProxmoxClient:
    """Thin wrapper around the Proxmox VE API."""

    _vm_list_cache: tuple[float, list[dict]] | None = None
    _vm_list_cache_lock = threading.Lock()

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
        import re

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

    def upload_snippet(self, filename: str, content: str, *, storage: str = "local") -> str:
        """Write cloud-init user-data to Proxmox snippets storage."""
        snippets_dir = Path(settings.proxmox_snippets_dir)
        if snippets_dir.is_dir():
            (snippets_dir / filename).write_text(content)
            return f"local:snippets/{filename}"

        if settings.proxmox_ssh_host:
            path = f"{settings.proxmox_snippets_dir}/{filename}"
            subprocess.run(
                ["ssh", settings.proxmox_ssh_host, f"cat > {path}"],
                input=content,
                text=True,
                check=True,
            )
            return f"local:snippets/{filename}"

        # Fallback: Proxmox upload API
        url = (
            f"https://{settings.proxmox_host}:8006/api2/json/"
            f"nodes/{self.node}/storage/{storage}/upload"
        )
        auth = (
            f"PVEAPIToken={settings.proxmox_user}!"
            f"{settings.proxmox_token_name}={settings.proxmox_token_value}"
        )
        files = {"data": (filename, content.encode())}
        data = {"content": "snippets", "filename": filename}
        resp = requests.post(
            url,
            headers={"Authorization": auth},
            files=files,
            data=data,
            verify=settings.proxmox_verify_ssl,
            timeout=60,
        )
        resp.raise_for_status()
        return f"local:snippets/{filename}"

    def set_cloudinit(
        self,
        vmid: int,
        *,
        user_data: str | None = None,
        ipconfig0: str | None = "ip=dhcp",
        sshkeys: list[str] | str | None = None,
        ciuser: str | None = None,
        snippet_storage: str = "local",
    ) -> None:
        params: dict = {}
        if user_data is not None:
            snippet_name = f"homecloud-{vmid}-user.yaml"
            snippet_ref = self.upload_snippet(snippet_name, user_data, storage=snippet_storage)
            params["cicustom"] = f"user={snippet_ref}"
        if ipconfig0 is not None:
            params["ipconfig0"] = ipconfig0
        if sshkeys is not None:
            # Proxmox accepts newline-separated keys, all URL-encoded together.
            if isinstance(sshkeys, list):
                key_str = "\n".join(k.strip().splitlines()[0] for k in sshkeys if k.strip())
            else:
                key_str = sshkeys.strip().splitlines()[0]
            params["sshkeys"] = quote(key_str, safe="")
        if ciuser is not None:
            params["ciuser"] = ciuser
        if params:
            self._api.nodes(self.node).qemu(vmid).config.put(**params)

    def resize_disk(self, vmid: int, disk: str, size_gb: int) -> None:
        self._api.nodes(self.node).qemu(vmid).resize.put(disk=disk, size=f"+{size_gb}G")

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
        import time

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
    # Cloud image import (requires PROXMOX_SSH_HOST — `qm` runs on the node)
    # ------------------------------------------------------------------

    def ssh_exec(self, command: str, *, timeout: int = 600) -> str:
        """Run a shell command on the Proxmox node over SSH.

        Raises RuntimeError when PROXMOX_SSH_HOST is unset, since disk import
        has no API equivalent.
        """
        if not settings.proxmox_ssh_host:
            raise RuntimeError(
                "PROXMOX_SSH_HOST is not configured — importing cloud images "
                "requires SSH access to the Proxmox node"
            )
        result = subprocess.run(
            ["ssh", settings.proxmox_ssh_host, command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Proxmox node command failed ({result.returncode}): "
                f"{result.stderr.strip() or command}"
            )
        return result.stdout

    def cloud_image_exists(self, remote_path: str) -> bool:
        try:
            self.ssh_exec(f"test -s {shlex.quote(remote_path)}", timeout=30)
        except RuntimeError:
            return False
        return True

    def download_cloud_image(
        self,
        url: str,
        remote_path: str,
        *,
        sha256: str | None = None,
        timeout: int = 1800,
    ) -> None:
        """Fetch a distro cloud image onto the node, then verify it.

        Downloads to a temporary path and moves it into place only after the
        checksum passes, so an interrupted transfer never poisons the cache.
        """
        quoted = shlex.quote(remote_path)
        tmp = shlex.quote(f"{remote_path}.part")
        self.ssh_exec(f"mkdir -p {shlex.quote(str(Path(remote_path).parent))}", timeout=30)
        self.ssh_exec(f"curl -fL --retry 3 -o {tmp} {shlex.quote(url)}", timeout=timeout)
        if sha256:
            out = self.ssh_exec(f"sha256sum {tmp}", timeout=300)
            actual = out.split()[0] if out.split() else ""
            if actual.lower() != sha256.lower():
                self.ssh_exec(f"rm -f {tmp}", timeout=30)
                raise RuntimeError(
                    f"Checksum mismatch for {url}: expected {sha256}, got {actual}"
                )
        self.ssh_exec(f"mv {tmp} {quoted}", timeout=60)

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

    def import_cloud_image_disk(self, vmid: int, remote_path: str) -> None:
        """Import a downloaded cloud image as the VM's scsi0 boot disk."""
        self.ssh_exec(
            f"qm set {vmid} --scsi0 "
            f"{shlex.quote(self.storage)}:0,import-from={shlex.quote(remote_path)}",
            timeout=1800,
        )

    def attach_cloudinit_drive(self, vmid: int) -> None:
        """Add the cloud-init drive and make the imported disk bootable."""
        self._api.nodes(self.node).qemu(vmid).config.put(
            ide2=f"{self.storage}:cloudinit",
            boot="order=scsi0",
        )

    def get_vm_config(self, vmid: int) -> dict:
        return self._api.nodes(self.node).qemu(vmid).config.get()

    def delete_vm(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).delete()

    def guest_exec(self, vmid: int, command: list[str]) -> str:
        result = self._api.nodes(self.node).qemu(vmid).agent("exec").post(command=command)
        if isinstance(result, dict):
            return result.get("out-data", "") or str(result)
        return str(result)

    def guest_run(self, vmid: int, command: list[str], *, timeout: int = 300) -> dict:
        """Run a command in the guest and wait for it to exit.

        ``agent exec`` only returns a pid; the result has to be collected from
        ``agent exec-status``.  Returns ``{"exitcode", "out", "err"}``.
        """
        started = self._api.nodes(self.node).qemu(vmid).agent("exec").post(command=command)
        pid = started.get("pid") if isinstance(started, dict) else None
        if pid is None:
            return {"exitcode": 0, "out": "", "err": ""}

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._api.nodes(self.node).qemu(vmid).agent("exec-status").get(pid=pid)
            if status.get("exited"):
                return {
                    "exitcode": status.get("exitcode", 0),
                    "out": status.get("out-data", "") or "",
                    "err": status.get("err-data", "") or "",
                }
            time.sleep(2)
        raise TimeoutError(f"Guest command on VM {vmid} timed out after {timeout}s")

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

    def wait_for_guest_agent(self, vmid: int, *, timeout: int = 180) -> None:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._api.nodes(self.node).qemu(vmid).agent("ping").post()
                return
            except Exception:
                time.sleep(3)
        raise TimeoutError(f"Guest agent not ready on VM {vmid}")

    def regenerate_cloudinit(self, vmid: int) -> None:
        self._api.nodes(self.node).qemu(vmid).cloudinit.put()

    def prepare_for_template(self, vmid: int) -> None:
        """Reset cloud-init so clones get fresh first-boot config."""
        self.wait_for_guest_agent(vmid)
        self.guest_exec(
            vmid,
            [
                "bash",
                "-c",
                "cloud-init clean --logs --seed && "
                "truncate -s 0 /etc/machine-id && "
                "rm -rf /var/lib/cloud/instances/*",
            ],
        )

    def wait_for_vm_ip(self, vmid: int, *, timeout: int = 180) -> str:
        """Wait for DHCP IP via QEMU guest agent."""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.wait_for_guest_agent(vmid, timeout=10)
                interfaces = (
                    self._api.nodes(self.node).qemu(vmid).agent("network-get-interfaces").get()
                )
                if isinstance(interfaces, dict) and "result" in interfaces:
                    interfaces = interfaces["result"]
                for iface in interfaces or []:
                    for addr in iface.get("ip-addresses", []):
                        if addr.get("ip-address-type") != "ipv4":
                            continue
                        ip = addr.get("ip-address", "")
                        if ip and not ip.startswith("127."):
                            return ip
            except Exception:
                pass
            time.sleep(5)
        raise TimeoutError(f"Could not get IP for VM {vmid} within {timeout}s")
