from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CloudImage(Base):
    """An upstream distro cloud image — a *source* instances are cloned from.

    ``template_id`` caches the source template produced by importing ``url``
    on the node and baking in the guest agent (see ``images/sources.py``).
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
