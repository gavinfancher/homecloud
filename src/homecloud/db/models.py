from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BuildStatus(StrEnum):
    DRAFT = "draft"
    BUILDING = "building"
    BUILT = "built"
    FAILED = "failed"


class CloudImage(Base):
    """An upstream distro cloud image (the base layer a custom image builds on).

    ``template_id`` caches the Proxmox template produced by downloading and
    importing ``url`` on the node, so repeat builds skip the download.
    """

    __tablename__ = "cloud_images"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    distro: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(32))
    arch: Mapped[str] = mapped_column(String(16), default="amd64")
    url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Login the distro bakes into its cloud image (ubuntu, debian, fedora…).
    ssh_user: Mapped[str] = mapped_column(String(32), default="ubuntu")
    builtin: Mapped[bool] = mapped_column(default=False)

    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    custom_images: Mapped[list[CustomImage]] = relationship(back_populates="cloud_image")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "distro": self.distro,
            "version": self.version,
            "arch": self.arch,
            "url": self.url,
            "sha256": self.sha256,
            "ssh_user": self.ssh_user,
            "builtin": self.builtin,
            "template_id": self.template_id,
            "imported": self.template_id is not None,
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }


class CustomImage(Base):
    """A user-defined image: a cloud image plus packages, files, and commands."""

    __tablename__ = "custom_images"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    cloud_image_id: Mapped[str] = mapped_column(ForeignKey("cloud_images.id"))
    cloud_image: Mapped[CloudImage] = relationship(back_populates="custom_images")

    # list[str] — apt/dnf package names installed via cloud-init `packages`.
    packages: Mapped[list] = mapped_column(JSONB, default=list)
    # list[{path, content, permissions, owner}] — cloud-init `write_files`.
    config_files: Mapped[list] = mapped_column(JSONB, default=list)
    # list[str] — shell lines appended to cloud-init `runcmd`.
    run_commands: Mapped[list] = mapped_column(JSONB, default=list)

    default_cores: Mapped[int] = mapped_column(default=2)
    default_memory_mb: Mapped[int] = mapped_column(default=2048)
    default_disk_gb: Mapped[int] = mapped_column(default=10)

    status: Mapped[str] = mapped_column(String(16), default=BuildStatus.DRAFT)
    template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    build_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    built_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "kind": "custom",
            "cloud_image_id": self.cloud_image_id,
            "packages": list(self.packages or []),
            "config_files": list(self.config_files or []),
            "run_commands": list(self.run_commands or []),
            "default_cores": self.default_cores,
            "default_memory_mb": self.default_memory_mb,
            "default_disk_gb": self.default_disk_gb,
            "status": self.status,
            "built": self.status == BuildStatus.BUILT and self.template_id is not None,
            "template_id": self.template_id,
            "build_error": self.build_error,
            "built_at": self.built_at.isoformat() if self.built_at else None,
        }
