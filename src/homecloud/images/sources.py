"""Turn an upstream distro cloud image into a source template.

A source is a stock cloud image with exactly one addition: the QEMU guest
agent, so clones report their LAN address over the Proxmox API and the
controller can SSH in to run Ansible. Everything else is Ansible's job.

Importing is expensive (download, disk import, one boot), so the template id
is cached on the ``cloud_images`` row and every deploy clones it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml
from sqlalchemy import select

from homecloud.db.models import CloudImage
from homecloud.db.session import session_scope
from homecloud.jobs import JobCancelled
from homecloud.proxmox.client import ProxmoxClient

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]

# Source templates live above the instance range so they are easy to spot on
# the node and never collide with instance vmids.
SOURCE_VMID_START = 9100

# The guest agent is the one thing a source bakes in. Installed from runcmd
# rather than `packages:` so it works on apt and dnf distros alike.
_AGENT_BOOTSTRAP = """\
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y qemu-guest-agent
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y qemu-guest-agent
elif command -v yum >/dev/null 2>&1; then
  yum install -y qemu-guest-agent
fi
systemctl enable --now qemu-guest-agent
"""

# Key the DHCP client identifier off the MAC rather than /etc/machine-id, so
# clones can never collide on a lease even if a machine-id slips through.
_DHCP_IDENTIFIER = """\
network:
  version: 2
  ethernets:
    eth0:
      dhcp-identifier: mac
"""

# Proxmox only imports disks from these formats, and infers the format from
# the extension.  Distro ".img" cloud images (Ubuntu's) are qcow2 inside.
_IMPORT_EXTENSIONS = {".qcow2": ".qcow2", ".raw": ".raw", ".vmdk": ".vmdk", ".img": ".qcow2"}


def _noop_log(_level: str, _message: str) -> None:
    pass


def template_name(source_id: str) -> str:
    return f"source-{source_id}"


def import_filename(cloud_image: CloudImage) -> str:
    """File name the cloud image is cached under in the node's ``import`` storage."""
    upstream = Path(urlparse(cloud_image.url).path).name
    suffix = Path(upstream).suffix.lower()
    if suffix not in _IMPORT_EXTENSIONS:
        raise ValueError(
            f"Cannot import {upstream or cloud_image.url!r}: Proxmox imports "
            "qcow2, raw, vmdk or img cloud images"
        )
    return f"{cloud_image.id}{_IMPORT_EXTENSIONS[suffix]}"


def bake_user_data() -> str:
    doc = {
        "write_files": [
            {
                "path": "/etc/netplan/99-homecloud-dhcp-identifier.yaml",
                "permissions": "0600",
                "content": _DHCP_IDENTIFIER,
            }
        ],
        "runcmd": [["bash", "-c", _AGENT_BOOTSTRAP]],
    }
    return "#cloud-config\n" + yaml.safe_dump(doc, sort_keys=False, width=4096)


def _template_names(pve: ProxmoxClient) -> dict[int, str]:
    return {
        vm["vmid"]: vm.get("name", "")
        for vm in pve.api.nodes(pve.node).qemu.get()
        if vm.get("template") == 1
    }


def is_source_template(
    pve: ProxmoxClient,
    source_id: str,
    template_id: int | None,
    *,
    templates: dict[int, str] | None = None,
) -> bool:
    """True when *template_id* is a baked source template for *source_id*.

    Rows imported before sources existed point at templates without the guest
    agent; their names differ, so they count as not imported.
    """
    if template_id is None:
        return False
    templates = _template_names(pve) if templates is None else templates
    return templates.get(template_id) == template_name(source_id)


def list_sources(proxmox: ProxmoxClient | None = None) -> list[dict]:
    """Every catalog source, with ``imported`` reflecting the node's templates."""
    pve = proxmox or ProxmoxClient()
    templates = _template_names(pve)
    with session_scope() as session:
        rows = session.scalars(select(CloudImage).order_by(CloudImage.name)).all()
        sources = [row.to_dict() for row in rows]
    for source in sources:
        imported = is_source_template(
            pve, source["id"], source["template_id"], templates=templates
        )
        source["imported"] = imported
        if not imported:
            source["template_id"] = None
    return sources


def source_template(source_id: str, *, proxmox: ProxmoxClient | None = None) -> int:
    """Template id to clone for *source_id*; raises when it is not imported yet."""
    pve = proxmox or ProxmoxClient()
    with session_scope() as session:
        row = session.get(CloudImage, source_id)
        if row is None:
            raise ValueError(f"Unknown source image: {source_id}")
        template_id = row.template_id
    if not is_source_template(pve, source_id, template_id):
        raise ValueError(f"Source {source_id} is not imported yet — import it from Sources first")
    return template_id  # type: ignore[return-value]


def ensure_source_template(
    source_id: str,
    *,
    proxmox: ProxmoxClient | None = None,
    log: LogFn | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    """Return the template id for a source, importing and baking it if needed.

    The download, import and bake boot take minutes, so they run outside any
    transaction: the row is read in one short session and updated in another.
    """
    emit = log or _noop_log
    pve = proxmox or ProxmoxClient()

    def check_cancel() -> None:
        if cancel_check is not None and cancel_check():
            raise JobCancelled("Source import cancelled by user")

    with session_scope() as session:
        cloud_image = session.get(CloudImage, source_id)
        if cloud_image is None:
            raise ValueError(f"Unknown source image: {source_id}")
        cached = cloud_image.template_id
        name, url, sha256 = cloud_image.name, cloud_image.url, cloud_image.sha256
        filename = import_filename(cloud_image)

    if is_source_template(pve, source_id, cached):
        emit("info", f"Using {name} template #{cached}")
        return cached  # type: ignore[return-value]

    volid = f"{pve.image_storage}:import/{filename}"
    if pve.volume_exists(volid):
        emit("info", f"Cloud image already on the node: {volid}")
    else:
        emit("info", f"Downloading {name} — this can take a few minutes…")
        volid = pve.download_cloud_image(url, filename, sha256=sha256)
        emit("info", f"Downloaded to {volid}")
    check_cancel()

    vmid = pve.next_vmid(start=SOURCE_VMID_START)
    try:
        emit("info", f"Creating VM {vmid} and importing the disk")
        pve.wait_for_task(pve.create_vm(vmid, template_name(source_id)))
        pve.import_cloud_image_disk(vmid, volid)
        check_cancel()

        emit("info", "Booting once to install the QEMU guest agent…")
        pve.attach_seed(vmid, hostname=template_name(source_id), user_data=bake_user_data())
        pve.wait_for_task(pve.start(vmid), timeout=120)
        pve.wait_for_guest_agent(vmid, timeout=900, check_cancel=check_cancel)
        # The agent comes up from runcmd, near the end; let cloud-init finish
        # before wiping its state for the template.
        pve.guest_run(vmid, ["cloud-init", "status", "--wait"], timeout=600)
        emit("info", "Guest agent is up")

        emit("info", "Preparing VM for templating")
        pve.prepare_for_template(vmid)
        pve.wait_for_task(pve.stop(vmid), timeout=120)

        # Swap the bake seed for Proxmox's own cloud-init drive: clones get
        # their user, SSH keys and DHCP config from it through the API.
        pve.detach_seed(vmid)
        pve.attach_native_cloudinit_drive(vmid)
        pve.convert_to_template(vmid)
    except Exception:
        emit("warning", f"Import failed — removing VM {vmid}")
        try:
            pve.stop(vmid)
        except Exception:
            logger.debug("Could not stop VM %s", vmid, exc_info=True)
        try:
            pve.wait_for_task(pve.delete_vm(vmid), timeout=120)
        except Exception:
            logger.warning("Leftover source VM %s needs manual cleanup", vmid)
        try:
            pve.delete_seed(vmid)
        except Exception:
            logger.warning("Leftover seed ISO for VM %s", vmid, exc_info=True)
        raise

    with session_scope() as session:
        row = session.get(CloudImage, source_id)
        if row is not None:
            row.template_id = vmid
            row.imported_at = datetime.now(UTC)

    emit("info", f"{name} ready — template #{vmid}")
    return vmid
