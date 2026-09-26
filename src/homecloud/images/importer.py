"""Turn an upstream distro cloud image into a Proxmox base template.

Downloading and importing a cloud image is expensive, so the resulting
template id is cached on the ``cloud_images`` row: the first custom image that
needs Ubuntu 24.04 pays the cost, every later one clones the cached template.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from homecloud.db.models import CloudImage
from homecloud.db.session import session_scope
from homecloud.proxmox.client import ProxmoxClient

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]

# Imported cloud images live above the build/instance range so they are easy
# to spot on the node and never collide with `next_vmid(start=8000)` builds.
CLOUD_IMAGE_VMID_START = 9100


def _noop_log(_level: str, _message: str) -> None:
    pass


# Proxmox only imports disks from these formats, and infers the format from
# the extension.  Distro ".img" cloud images (Ubuntu's) are qcow2 inside.
_IMPORT_EXTENSIONS = {".qcow2": ".qcow2", ".raw": ".raw", ".vmdk": ".vmdk", ".img": ".qcow2"}


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


def ensure_cloud_image_template(
    cloud_image_id: str,
    *,
    proxmox: ProxmoxClient | None = None,
    log: LogFn | None = None,
) -> int:
    """Return the Proxmox template id for a cloud image, importing it if needed.

    The download and import can take many minutes, so they run outside any
    transaction: the row is read in one short session and updated in another.
    """
    emit = log or _noop_log
    pve = proxmox or ProxmoxClient()

    with session_scope() as session:
        cloud_image = session.get(CloudImage, cloud_image_id)
        if cloud_image is None:
            raise ValueError(f"Unknown cloud image: {cloud_image_id}")
        if cloud_image.template_id is not None:
            emit("info", f"Using cached {cloud_image.name} template #{cloud_image.template_id}")
            return cloud_image.template_id
        name, url, sha256 = cloud_image.name, cloud_image.url, cloud_image.sha256
        filename = import_filename(cloud_image)
    volid = f"{pve.image_storage}:import/{filename}"
    if pve.volume_exists(volid):
        emit("info", f"Cloud image already on the node: {volid}")
    else:
        emit("info", f"Downloading {name} — this can take a few minutes…")
        volid = pve.download_cloud_image(url, filename, sha256=sha256)
        emit("info", f"Downloaded to {volid}")

    vmid = pve.next_vmid(start=CLOUD_IMAGE_VMID_START)

    emit("info", f"Creating VM {vmid} for the imported disk")
    pve.create_vm(vmid, f"cloudimg-{cloud_image_id}")

    emit("info", "Importing disk…")
    pve.import_cloud_image_disk(vmid, volid)

    emit("info", f"Converting VM {vmid} to template")
    pve.convert_to_template(vmid)

    with session_scope() as session:
        row = session.get(CloudImage, cloud_image_id)
        if row is not None:
            row.template_id = vmid
            row.imported_at = datetime.now(UTC)

    emit("info", f"{name} ready — template #{vmid}")
    return vmid
