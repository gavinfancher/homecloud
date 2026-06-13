from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from homecloud.access import ssh_config_block
from homecloud.config import settings
from homecloud.dns.names import connection_info
from homecloud.dns.zone import write_zone
from homecloud.images.cloud_init import render_cloud_init
from homecloud.images.registry import get_image
from homecloud.jobs import JobCancelled
from homecloud.proxmox.client import ProxmoxClient
from homecloud.state import (
    get_built_template,
    get_ssh_public_keys,
    hydrate_registry,
    register_vm,
    unregister_vm,
)
from homecloud.tailscale.client import TailscaleClient

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]


def _noop_log(_level: str, _message: str) -> None:
    pass


class VMDeployer:
    """Deploy VMs: join Tailscale, expose MagicDNS hostname."""

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
        size_id: str = "custom",
        image_id: str = "homecloud-base",
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        emit = log or _noop_log

        def check_cancel() -> None:
            if cancel_check and cancel_check():
                raise JobCancelled("Deployment cancelled by user")

        hydrate_registry()

        check_cancel()
        emit("info", "Validating configuration…")
        if not settings.tailscale_auth_key:
            raise ValueError("TAILSCALE_AUTH_KEY required — VMs must join your tailnet")
        if not settings.tailscale_api_key:
            raise ValueError("TAILSCALE_API_KEY required — to resolve Tailscale IPs")

        spec = get_image(image_id)
        if spec is None:
            raise ValueError(f"Unknown image: {image_id}")
        template_id = spec.template_id or get_built_template(image_id)
        if template_id is None:
            raise ValueError(
                "Base image not built yet — complete setup and build the base image first"
            )

        ssh_keys = get_ssh_public_keys()
        if not ssh_keys:
            raise ValueError("No SSH public key — complete setup first")

        check_cancel()
        vmid = self.proxmox.next_vmid()
        emit("info", f"Allocated VM ID {vmid} for {name}")

        emit("info", f"Cloning template {template_id}…")
        task = self.proxmox.clone_template(template_id, vmid, name)
        self.proxmox.wait_for_task(task)
        emit("info", "Clone complete")
        check_cancel()

        emit("info", "Configuring cloud-init (Tailscale join + SSH keys)…")
        deploy_cloud_init = render_cloud_init(
            "deploy.yaml.j2",
            hostname=name,
            tailscale_auth_key=settings.tailscale_auth_key,
            ssh_public_keys=ssh_keys,
        )
        self.proxmox.set_cloudinit(
            vmid,
            user_data=deploy_cloud_init,
            ciuser=settings.vm_ssh_user,
            ipconfig0="ip=dhcp",
            sshkeys=ssh_keys,
        )

        memory_mb = int(memory_gb * 1024)
        emit(
            "info",
            f"Setting resources: {cores} vCPU, {memory_gb} GB RAM, {disk_gb} GB disk",
        )
        self.proxmox.set_resources(vmid, cores=cores, memory_mb=memory_mb)
        self._resize_disk_to_target(vmid, disk_gb)
        self.proxmox.regenerate_cloudinit(vmid)

        emit("info", "Starting VM…")
        start_task = self.proxmox.start(vmid)
        self.proxmox.wait_for_task(start_task, timeout=120)
        emit("info", f"VM {vmid} is running — waiting for Tailscale join")

        tailscale_ip = self._wait_for_tailscale_ip(name, log=emit, cancel_check=cancel_check)
        emit("info", f"Tailscale IP assigned: {tailscale_ip}")

        dns = connection_info(name, tailscale_ip)
        emit("info", f"MagicDNS: {dns['hostname']}")
        ssh_block = ssh_config_block(host_alias=name, hostname=name)

        record = {
            "vmid": vmid,
            "name": name,
            "ip": tailscale_ip,
            "tailscale_ip": tailscale_ip,
            "hostname": dns["hostname"],
            "size_id": size_id,
            "cores": cores,
            "memory_gb": memory_gb,
            "memory_mb": memory_mb,
            "disk_gb": disk_gb,
            "image_id": image_id,
        }
        register_vm(name, record)
        try:
            write_zone()
        except Exception:
            logger.warning("write_zone failed after VM create — non-fatal", exc_info=True)
        emit("info", f"Deployment complete — SSH: {dns['ssh']}")

        return {
            "vmid": vmid,
            "name": name,
            "status": "running",
            "size_id": size_id,
            "cores": cores,
            "memory_gb": memory_gb,
            "memory_mb": memory_mb,
            "disk_gb": disk_gb,
            "image_id": image_id,
            "tailscale_ip": tailscale_ip,
            "hostname": dns["hostname"],
            "ssh_command": dns["ssh"],
            "ssh_config": ssh_block,
            "magic_dns": dns["magic_dns"],
        }

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

    def __init__(self, proxmox: ProxmoxClient | None = None) -> None:
        self.proxmox = proxmox or ProxmoxClient()

    def start(self, vmid: int) -> dict:
        task = self.proxmox.start(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        return {"vmid": vmid, "status": "running"}

    def stop(self, vmid: int) -> dict:
        task = self.proxmox.stop(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        return {"vmid": vmid, "status": "stopped"}

    def suspend(self, vmid: int) -> dict:
        task = self.proxmox.suspend(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        return {"vmid": vmid, "status": "paused"}

    def resume(self, vmid: int) -> dict:
        task = self.proxmox.resume(vmid)
        self.proxmox.wait_for_task(task, timeout=120)
        return {"vmid": vmid, "status": "running"}

    def delete(self, vmid: int, *, name: str | None = None) -> dict:
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
        task = self.proxmox.delete_vm(vmid)
        if task:
            self.proxmox.wait_for_task(task, timeout=120)
        return {"vmid": vmid, "status": "deleted"}
