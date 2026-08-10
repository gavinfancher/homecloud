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

from homecloud.config import settings
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


def remote_image_path(cloud_image: CloudImage) -> str:
    """Where this cloud image is cached on the Proxmox node."""
    filename = Path(urlparse(cloud_image.url).path).name
    if not filename:
        filename = f"{cloud_image.id}.img"
    return f"{settings.cloud_image_cache_dir.rstrip('/')}/{filename}"


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
        path = remote_image_path(cloud_image)
    if pve.cloud_image_exists(path):
        emit("info", f"Cloud image already on the node: {path}")
    else:
        emit("info", f"Downloading {name} — this can take a few minutes…")
        pve.download_cloud_image(url, path, sha256=sha256)
        emit("info", f"Downloaded to {path}")

    vmid = pve.next_vmid(start=CLOUD_IMAGE_VMID_START)

    emit("info", f"Creating VM {vmid} for the imported disk")
    pve.create_vm(vmid, f"cloudimg-{cloud_image_id}")

    emit("info", "Importing disk (qm set --import-from)…")
    pve.import_cloud_image_disk(vmid, path)
    pve.attach_cloudinit_drive(vmid)

    emit("info", f"Converting VM {vmid} to template")
    pve.convert_to_template(vmid)

    with session_scope() as session:
        row = session.get(CloudImage, cloud_image_id)
        if row is not None:
            row.template_id = vmid
            row.imported_at = datetime.now(UTC)

    emit("info", f"{name} ready — template #{vmid}")
    return vmid
