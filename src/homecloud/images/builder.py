from __future__ import annotations

import logging
import time
from collections.abc import Callable

from homecloud.config import settings
from homecloud.images.cloud_init import render_cloud_init
from homecloud.images.registry import get_image
from homecloud.proxmox.client import ProxmoxClient
from homecloud.state import (
    get_built_template,
    get_ssh_public_keys,
    hydrate_registry,
    set_built_template,
)

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]


def _noop_log(_level: str, _message: str) -> None:
    pass


class ImageBuilder:
    """Build Proxmox templates from cloud-init specs."""

    def __init__(self, proxmox: ProxmoxClient | None = None) -> None:
        self.proxmox = proxmox or ProxmoxClient()

    def build_builtin(self, image_id: str = "homecloud-base", *, log: LogFn | None = None) -> dict:
        emit = log or _noop_log
        spec = get_image(image_id)
        if spec is None:
            raise ValueError(f"Unknown image: {image_id}")

        ssh_keys = get_ssh_public_keys()
        if not ssh_keys:
            raise ValueError(
                "Complete setup and upload your SSH public key before building the base image"
            )

        vmid = self.proxmox.next_vmid(start=8000)
        name = f"tpl-{spec.id}"
        base_id = settings.proxmox_base_template_id

        emit("info", f"Cloning Ubuntu template {base_id} → build VM {vmid}")
        task = self.proxmox.clone_template(base_id, vmid, name)
        self.proxmox.wait_for_task(task)

        emit("info", "Applying cloud-init (docker, uv, tailscale)…")
        user_data = render_cloud_init(
            "base-image.yaml.j2",
            hostname=name,
            ssh_user=settings.vm_ssh_user,
            ssh_public_keys=ssh_keys,
        )
        self._apply_cloudinit(vmid, user_data, sshkeys=ssh_keys)

        self.proxmox.set_resources(
            vmid,
            cores=spec.default_cores,
            memory_mb=spec.default_memory_mb,
        )
        self.proxmox.resize_disk(vmid, "scsi0", spec.default_disk_gb)

        emit("info", f"Starting build VM {vmid}")
        start_task = self.proxmox.start(vmid)
        self.proxmox.wait_for_task(start_task, timeout=120)

        emit("info", "Waiting for cloud-init bootstrap (~2 min)…")
        time.sleep(120)

        emit("info", "Preparing VM for templating (cloud-init clean)")
        self.proxmox.prepare_for_template(vmid)

        emit("info", "Stopping VM and converting to template")
        stop_task = self.proxmox.stop(vmid)
        self.proxmox.wait_for_task(stop_task, timeout=120)

        self.proxmox.convert_to_template(vmid)
        set_built_template(image_id, vmid)
        emit("info", f"Base image ready — template ID {vmid}")

        return {
            "image_id": image_id,
            "template_id": vmid,
            "name": name,
            "status": "ready",
        }

    def build_custom(
        self,
        *,
        name: str,
        base_image_id: str = "homecloud-base",
        extra_packages: list[str] | None = None,
    ) -> dict:
        """Clone a built base template and layer custom config (future: user scripts)."""
        hydrate_registry()
        base = get_image(base_image_id)
        template_id = base.template_id if base else None
        if template_id is None and base:
            template_id = get_built_template(base_image_id)
        if base is None or template_id is None:
            raise ValueError(
                f"Base image {base_image_id} must be built first "
                "(POST /api/images/homecloud-base/build)"
            )

        vmid = self.proxmox.next_vmid(start=8000)
        tpl_name = f"tpl-{name}"

        task = self.proxmox.clone_template(template_id, vmid, tpl_name)
        self.proxmox.wait_for_task(task)

        if extra_packages:
            pkg_script = "\n".join(f"apt-get install -y {p}" for p in extra_packages)
            user_data = f"#cloud-config\nruncmd:\n  - apt-get update\n  - {pkg_script}\n"
            self._apply_cloudinit(vmid, user_data)

        start_task = self.proxmox.start(vmid)
        self.proxmox.wait_for_task(start_task, timeout=120)

        import time

        time.sleep(60)

        self.proxmox.prepare_for_template(vmid)

        stop_task = self.proxmox.stop(vmid)
        self.proxmox.wait_for_task(stop_task, timeout=120)

        self.proxmox.convert_to_template(vmid)

        return {
            "name": name,
            "template_id": vmid,
            "base_image_id": base_image_id,
            "status": "ready",
        }

    def _apply_cloudinit(
        self,
        vmid: int,
        user_data: str,
        *,
        sshkeys: list[str] | str | None = None,
    ) -> None:
        self.proxmox.set_cloudinit(
            vmid,
            user_data=user_data,
            ciuser=settings.vm_ssh_user,
            ipconfig0="ip=dhcp",
            sshkeys=sshkeys,
        )
