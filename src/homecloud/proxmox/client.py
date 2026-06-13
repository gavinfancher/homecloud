from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import quote

import requests
from proxmoxer import ProxmoxAPI

from homecloud.config import settings


class ProxmoxClient:
    """Thin wrapper around the Proxmox VE API."""

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

    def list_vms(self) -> list[dict]:
        vms = []
        for vm in self._api.nodes(self.node).qemu.get():
            config = self._api.nodes(self.node).qemu(vm["vmid"]).config.get()
            if config.get("template") != 1:
                vms.append(self.enrich_vm(vm, config))
        return vms

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

    def get_vm_config(self, vmid: int) -> dict:
        return self._api.nodes(self.node).qemu(vmid).config.get()

    def delete_vm(self, vmid: int) -> str:
        return self._api.nodes(self.node).qemu(vmid).delete()

    def guest_exec(self, vmid: int, command: list[str]) -> str:
        result = self._api.nodes(self.node).qemu(vmid).agent("exec").post(command=command)
        if isinstance(result, dict):
            return result.get("out-data", "") or str(result)
        return str(result)

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
