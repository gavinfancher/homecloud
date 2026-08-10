"""Built-in catalog of upstream distro cloud images.

These are seeded into the ``cloud_images`` table on startup.  Users can add
their own rows through the API; only ``builtin`` entries are refreshed from
this list (and only for fields the user cannot edit).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    name: str
    distro: str
    version: str
    url: str
    ssh_user: str
    arch: str = "amd64"


BUILTIN_CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        id="ubuntu-24.04",
        name="Ubuntu 24.04 LTS (Noble)",
        distro="ubuntu",
        version="24.04",
        url="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        ssh_user="ubuntu",
    ),
    CatalogEntry(
        id="ubuntu-22.04",
        name="Ubuntu 22.04 LTS (Jammy)",
        distro="ubuntu",
        version="22.04",
        url="https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        ssh_user="ubuntu",
    ),
    CatalogEntry(
        id="debian-12",
        name="Debian 12 (Bookworm)",
        distro="debian",
        version="12",
        url=(
            "https://cloud.debian.org/images/cloud/bookworm/latest/"
            "debian-12-genericcloud-amd64.qcow2"
        ),
        ssh_user="debian",
    ),
    CatalogEntry(
        id="fedora-41",
        name="Fedora Cloud 41",
        distro="fedora",
        version="41",
        url=(
            "https://download.fedoraproject.org/pub/fedora/linux/releases/41/Cloud/x86_64/"
            "images/Fedora-Cloud-Base-Generic-41-1.4.x86_64.qcow2"
        ),
        ssh_user="fedora",
    ),
    CatalogEntry(
        id="rocky-9",
        name="Rocky Linux 9",
        distro="rocky",
        version="9",
        url=(
            "https://download.rockylinux.org/pub/rocky/9/images/x86_64/"
            "Rocky-9-GenericCloud.latest.x86_64.qcow2"
        ),
        ssh_user="rocky",
    ),
]


def seed_catalog(session: Session) -> int:
    """Insert any missing built-in catalog entries. Returns the number added."""
    from homecloud.db.models import CloudImage

    existing = set(session.scalars(select(CloudImage.id)).all())
    added = 0
    for entry in BUILTIN_CATALOG:
        if entry.id in existing:
            continue
        session.add(
            CloudImage(
                id=entry.id,
                name=entry.name,
                distro=entry.distro,
                version=entry.version,
                arch=entry.arch,
                url=entry.url,
                ssh_user=entry.ssh_user,
                builtin=True,
            )
        )
        added += 1
    return added
