from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

from homecloud.config import settings
from homecloud.images.cloud_init import render_cloud_init
from homecloud.images.registry import get_image
from homecloud.jobs import JobCancelled
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


def _cloud_init_error_detail(status_output: str) -> str:
    """Turn `cloud-init status --long` output into one actionable sentence."""
    detail = status_output.split("detail:", 1)[-1].strip()

    if "package-update-upgrade-install" in status_output:
        # cloud-init installs the whole `packages:` list in a single call, so
        # one name that does not exist on this distro fails all of them.
        names = re.findall(r"'install',\s*(.+?)\]", status_output)
        listed = names[0].replace("'", "") if names else "the requested packages"
        return (
            f"Installing packages failed ({listed}). cloud-init installs them in one "
            "command, so a single name that does not exist on this distribution "
            "fails all of them — check the names against the base image "
            "(Debian and Ubuntu use 'neovim', not 'nvim')."
        )

    return detail[:400] if detail else status_output[:400]


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

    def build_custom_image(
        self,
        image_id: str,
        *,
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        """Build a user-defined image: cloud image + packages + config files.

        Imports (or reuses) the base cloud image template, clones it, bakes the
        definition in via cloud-init, then converts the result to a template.
        """
        from homecloud.db.models import BuildStatus, CustomImage  # noqa: PLC0415
        from homecloud.db.session import session_scope  # noqa: PLC0415
        from homecloud.images.composer import (  # noqa: PLC0415, E501
            BOOTSTRAP_DONE_MARKER,
            compose_cloud_init,
        )
        from homecloud.images.importer import ensure_cloud_image_template  # noqa: PLC0415

        emit = log or _noop_log

        def check_cancel() -> None:
            if cancel_check is not None and cancel_check():
                raise JobCancelled("Image build cancelled by user")

        ssh_keys = get_ssh_public_keys()
        if not ssh_keys:
            raise ValueError("Complete setup and upload your SSH public key before building images")

        with session_scope() as session:
            image = session.get(CustomImage, image_id)
            if image is None:
                raise ValueError(f"Unknown image: {image_id}")

            image.status = BuildStatus.BUILDING
            image.build_error = None
            # Snapshot what the build needs so the work below — minutes of
            # downloading and booting — does not hold the transaction open.
            cloud_image_id = image.cloud_image_id
            plan = {
                "packages": list(image.packages or []),
                "config_files": list(image.config_files or []),
                "run_commands": list(image.run_commands or []),
                "cores": image.default_cores,
                "memory_mb": image.default_memory_mb,
                "disk_gb": image.default_disk_gb,
            }

        # The image bakes in VM_SSH_USER (not the distro's default login) so
        # every image deploys and is reachable the same way, whatever the base.
        ssh_user = settings.vm_ssh_user
        vmid: int | None = None
        tpl_name = f"tpl-{image_id}"

        try:
            check_cancel()
            base_template = ensure_cloud_image_template(
                cloud_image_id, proxmox=self.proxmox, log=emit
            )
            check_cancel()
            vmid = self.proxmox.next_vmid(start=8000)

            emit("info", f"Cloning base template {base_template} → build VM {vmid}")
            self.proxmox.wait_for_task(
                self.proxmox.clone_template(base_template, vmid, tpl_name)
            )

            emit("info", "Applying cloud-init (packages, config files, commands)…")
            user_data = compose_cloud_init(
                hostname=tpl_name,
                ssh_user=ssh_user,
                ssh_public_keys=ssh_keys,
                packages=plan["packages"],
                config_files=plan["config_files"],
                run_commands=plan["run_commands"],
            )
            self.proxmox.set_cloudinit(
                vmid,
                user_data=user_data,
                ciuser=ssh_user,
                ipconfig0="ip=dhcp",
                sshkeys=ssh_keys,
            )

            self.proxmox.set_resources(
                vmid, cores=plan["cores"], memory_mb=plan["memory_mb"]
            )
            self.proxmox.resize_disk(vmid, "scsi0", plan["disk_gb"])

            emit("info", f"Starting build VM {vmid}")
            self.proxmox.wait_for_task(self.proxmox.start(vmid), timeout=120)

            emit("info", "Waiting for cloud-init to finish provisioning…")
            self.proxmox.wait_for_guest_file(
                vmid, BOOTSTRAP_DONE_MARKER, timeout=1800, check_cancel=check_cancel
            )

            # The marker only proves cloud-init reached the end. A failed module
            # (a package that does not exist on this distro is the common one)
            # leaves the image missing what was asked for, so fail loudly here
            # rather than shipping a template that silently lacks the packages.
            self._assert_cloud_init_succeeded(vmid, emit)

            emit("info", "Preparing VM for templating (cloud-init clean)")
            self.proxmox.prepare_for_template(vmid)

            emit("info", "Stopping VM and converting to template")
            self.proxmox.wait_for_task(self.proxmox.stop(vmid), timeout=120)
            self.proxmox.convert_to_template(vmid)
        except Exception as exc:
            # Best-effort cleanup: a half-built VM left on the node just eats
            # disk and confuses the instance list.
            if vmid is not None:
                emit("warn", f"Build failed — removing build VM {vmid}")
                try:
                    self.proxmox.stop(vmid)
                except Exception:
                    logger.debug("Could not stop build VM %s", vmid, exc_info=True)
                try:
                    self.proxmox.delete_vm(vmid)
                except Exception:
                    logger.warning("Leftover build VM %s needs manual cleanup", vmid)

            cancelled = isinstance(exc, JobCancelled)
            with session_scope() as session:
                failed = session.get(CustomImage, image_id)
                if failed is not None:
                    # A cancelled build is not a broken definition — put it back
                    # in draft so it can simply be built again.
                    failed.status = BuildStatus.DRAFT if cancelled else BuildStatus.FAILED
                    failed.build_error = None if cancelled else str(exc)
            raise

        with session_scope() as session:
            built = session.get(CustomImage, image_id)
            if built is not None:
                built.status = BuildStatus.BUILT
                built.template_id = vmid
                built.build_error = None
                built.built_at = datetime.now(UTC)

        emit("info", f"Image {image_id} ready — template #{vmid}")
        return {"image_id": image_id, "template_id": vmid, "name": tpl_name, "status": "built"}

    def _assert_cloud_init_succeeded(self, vmid: int, emit: LogFn) -> None:
        """Raise with cloud-init's own reason when provisioning reported an error."""
        try:
            result = self.proxmox.guest_run(
                vmid, ["cloud-init", "status", "--long"], timeout=120
            )
        except Exception:
            # Can't ask the guest — don't fail a build on a diagnostic hiccup.
            logger.warning("Could not read cloud-init status on VM %s", vmid, exc_info=True)
            return

        output = f"{result.get('out', '')}\n{result.get('err', '')}".strip()
        if "status: error" not in output:
            emit("info", "cloud-init reported success")
            return

        detail = _cloud_init_error_detail(output)
        raise RuntimeError(
            f"cloud-init failed inside the build VM — the image would be missing "
            f"what you asked for. {detail}"
        )

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
