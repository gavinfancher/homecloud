from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from homecloud.access import ssh_config_block
from homecloud.config import settings
from homecloud.dns.names import connection_info
from homecloud.dns.zone import write_zone
from homecloud.images.sources import source_template
from homecloud.jobs import JobCancelled
from homecloud.provision.catalog import resolve_roles
from homecloud.provision.keys import controller_public_key
from homecloud.provision.runner import run_roles
from homecloud.proxmox.client import ProxmoxClient
from homecloud.state import (
    get_instance,
    get_ssh_public_keys,
    register_vm,
    unregister_vm,
)
from homecloud.tailscale.client import TailscaleClient

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]


def _noop_log(_level: str, _message: str) -> None:
    pass


class VMDeployer:
    """Deploy VMs: clone a source, run the selected Ansible roles, join Tailscale."""

    def __init__(self, proxmox: ProxmoxClient | None = None) -> None:
        self.proxmox = proxmox or ProxmoxClient()
        self.tailscale = TailscaleClient()

    def deploy(
        self,
        *,
        name: str,
        cores: int,
        memory_gb: float,
        disk_gb: int,
        source_id: str,
        roles: list[dict],
        size_id: str = "custom",
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        emit = log or _noop_log

        def check_cancel() -> None:
            if cancel_check and cancel_check():
                raise JobCancelled("Deployment cancelled by user")

        check_cancel()
        emit("info", "Validating configuration…")
        if not settings.tailscale_auth_key:
            raise ValueError("TAILSCALE_AUTH_KEY required — VMs must join your tailnet")
        if not settings.tailscale_api_key:
            raise ValueError("TAILSCALE_API_KEY required — to resolve Tailscale IPs")

        roles = resolve_roles(roles)
        template_id = source_template(source_id, proxmox=self.proxmox)

        ssh_keys = get_ssh_public_keys()
        if not ssh_keys:
            raise ValueError("No SSH public key — complete setup first")

        check_cancel()
        vmid = self.proxmox.next_vmid()
        emit("info", f"Allocated VM ID {vmid} for {name}")

        emit("info", f"Cloning source template {template_id}…")
        self.proxmox.wait_for_task(self.proxmox.clone_template(template_id, vmid, name))
        emit("info", "Clone complete")
        check_cancel()

        # The controller's key sits next to yours so Ansible can get in.
        self.proxmox.set_native_cloudinit(
            vmid,
            ciuser=settings.vm_ssh_user,
            sshkeys=[*ssh_keys, controller_public_key()],
        )

        memory_mb = int(memory_gb * 1024)
        emit(
            "info",
            f"Setting resources: {cores} vCPU, {memory_gb} GB RAM, {disk_gb} GB disk",
        )
        self.proxmox.set_resources(vmid, cores=cores, memory_mb=memory_mb)
        self._resize_disk_to_target(vmid, disk_gb)

        emit("info", "Starting VM…")
        self.proxmox.wait_for_task(self.proxmox.start(vmid), timeout=120)

        emit("info", "Waiting for the guest agent to report an address…")
        local_ip = self.proxmox.wait_for_vm_ip(vmid, timeout=300, check_cancel=check_cancel)
        emit("info", f"Local IP: {local_ip} — waiting for SSH")
        self.proxmox.wait_for_ssh(local_ip, timeout=300, check_cancel=check_cancel)

        emit("info", f"Running Ansible: {', '.join(r['id'] for r in roles)}")
        run_roles(local_ip, roles, hostname=name, log=emit, cancel_check=cancel_check)

        tailscale_ip = self._wait_for_tailscale_ip(name, log=emit, cancel_check=cancel_check)
        emit("info", f"Tailscale IP assigned: {tailscale_ip}")

        dns = connection_info(name, tailscale_ip, local_ip)
        emit("info", f"Hostname: {dns['hostname']}")
        ssh_block = ssh_config_block(host_alias=name, hostname=name)

        record = {
            "vmid": vmid,
            "name": name,
            "ip": tailscale_ip,
            "tailscale_ip": tailscale_ip,
            "local_ip": local_ip,
            "hostname": dns["hostname"],
            "size_id": size_id,
            "cores": cores,
            "memory_gb": memory_gb,
            "memory_mb": memory_mb,
            "disk_gb": disk_gb,
            "source_id": source_id,
            "roles": roles,
        }
        register_vm(name, record)
        try:
            write_zone()
        except Exception:
            logger.warning("write_zone failed after VM create — non-fatal", exc_info=True)
        ProxmoxClient.invalidate_vm_list_cache()
        emit("info", f"Deployment complete — SSH: {dns['ssh']}")

        return {
            **record,
            "status": "running",
            "ssh_command": dns["ssh"],
            "ssh_config": ssh_block,
        }

    def provision(
        self,
        name: str,
        roles: list[dict],
        *,
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        """Re-apply *roles* to an existing instance and remember them."""
        emit = log or _noop_log
        instance = get_instance(name)
        if instance is None or not instance.get("vmid"):
            raise ValueError(f"Unknown instance: {name}")
        roles = resolve_roles(roles)

        vmid = instance["vmid"]
        host = self.proxmox.get_lan_ip(vmid, use_cache=False) or instance.get("local_ip")
        if not host:
            raise ValueError(f"No LAN address for {name} — is it running?")

        emit("info", f"Running Ansible on {name} ({host}): {', '.join(r['id'] for r in roles)}")
        run_roles(host, roles, hostname=name, log=emit, cancel_check=cancel_check)

        # Only the fields this run changed — the rest may have moved meanwhile.
        register_vm(name, {"roles": roles, "local_ip": host})
        emit("info", f"{name} reconfigured")
        return {"name": name, "roles": roles}

    def _resize_disk_to_target(self, vmid: int, target_gb: int) -> None:
        config = self.proxmox.get_vm_config(vmid)
        scsi0 = config.get("scsi0", "")
        match = re.search(r"size=(\d+)G", scsi0)
        current_gb = int(match.group(1)) if match else 10
        if target_gb > current_gb:
            self.proxmox.resize_disk(vmid, "scsi0", target_gb - current_gb)

    def _wait_for_tailscale_ip(
        self,
        hostname: str,
        *,
        timeout: int = 180,
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str:
        emit = log or _noop_log
        deadline = time.time() + timeout
        last_log = 0.0
        while time.time() < deadline:
            if cancel_check and cancel_check():
                raise JobCancelled("Deployment cancelled by user")
            ip = self.tailscale.get_device_ip(hostname)
            if ip:
                return ip
            if time.time() - last_log >= 15:
                remaining = int(deadline - time.time())
                emit("info", f"Still waiting for {hostname} on tailnet… ({remaining}s left)")
                last_log = time.time()
            time.sleep(5)
        raise TimeoutError(
            f"VM {hostname} did not join tailnet within {timeout}s — "
            f"check VM {hostname} is running and Tailscale API is reachable"
        )


class VMManager:
    """Start, stop, and delete VMs."""

    def __init__(
        self,
        proxmox: ProxmoxClient | None = None,
        tailscale: TailscaleClient | None = None,
    ) -> None:
        self.proxmox = proxmox or ProxmoxClient()
        self.tailscale = tailscale or TailscaleClient()

    def start(self, vmid: int) -> dict:
        task = self.proxmox.start(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        # A restarted VM can come back on a different DHCP lease.
        ProxmoxClient.invalidate_lan_ip_cache(vmid)
        return {"vmid": vmid, "status": "running"}

    def stop(self, vmid: int) -> dict:
        task = self.proxmox.stop(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        return {"vmid": vmid, "status": "stopped"}

    def suspend(self, vmid: int) -> dict:
        task = self.proxmox.suspend(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        return {"vmid": vmid, "status": "paused"}

    def resume(self, vmid: int) -> dict:
        task = self.proxmox.resume(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        # A restarted VM can come back on a different DHCP lease.
        ProxmoxClient.invalidate_lan_ip_cache(vmid)
        return {"vmid": vmid, "status": "running"}

    def delete(self, vmid: int, *, name: str | None = None, log: LogFn | None = None) -> dict:
        log = log or _noop_log
        tailscale_removed = False
        if name:
            unregister_vm(name)
            try:
                write_zone()
            except Exception:
                logger.warning("write_zone failed after VM delete — non-fatal", exc_info=True)
        try:
            stop_task = self.proxmox.stop(vmid)
            self.proxmox.wait_for_task(stop_task, timeout=120)
        except Exception:
            pass
        if name and settings.tailscale_api_key:
            try:
                if self.tailscale.delete_device_by_hostname(name):
                    tailscale_removed = True
                    log("info", f"Removed {name} from Tailnet")
                else:
                    log("info", f"No Tailscale device for {name} — tailnet cleanup skipped")
            except Exception as exc:
                logger.warning("Tailscale device delete failed for %s", name, exc_info=True)
                log("warning", f"Could not remove {name} from Tailnet: {exc}")
        task = self.proxmox.delete_vm(vmid)
        if task:
            self.proxmox.wait_for_task(task, timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        # next_vmid reuses ids — a stale entry would label the next VM wrongly.
        ProxmoxClient.invalidate_lan_ip_cache(vmid)
        return {"vmid": vmid, "status": "deleted", "tailscale_removed": tailscale_removed}
