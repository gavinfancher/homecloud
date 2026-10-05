"""ORM mappings. The schema itself is owned by ``migrations/*.sql``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


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
            "imported_at": _iso(self.imported_at),
        }


class SshKey(Base):
    """A public key authorized on every instance deployed after it is added."""

    __tablename__ = "ssh_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_key: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Instance(Base):
    __tablename__ = "instances"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    vmid: Mapped[int] = mapped_column(unique=True)
    source_id: Mapped[str | None] = mapped_column(Text)
    size_id: Mapped[str] = mapped_column(Text, default="custom")
    cores: Mapped[int | None]
    memory_mb: Mapped[int | None]
    disk_gb: Mapped[int | None]
    local_ip: Mapped[str | None] = mapped_column(Text)
    tailscale_ip: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    web: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    ports_seen: Mapped[list[Any] | None] = mapped_column(JSONB)
    ports_scanned_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "vmid": self.vmid,
            "name": self.name,
            "ip": self.tailscale_ip,
            "tailscale_ip": self.tailscale_ip,
            "local_ip": self.local_ip,
            "source_id": self.source_id,
            "size_id": self.size_id,
            "cores": self.cores,
            "memory_mb": self.memory_mb,
            "memory_gb": round(self.memory_mb / 1024, 2) if self.memory_mb else None,
            "disk_gb": self.disk_gb,
            "roles": self.roles,
            "web": self.web,
            "ports_seen": self.ports_seen,
            "ports_scanned_at": _iso(self.ports_scanned_at),
            "created_at": _iso(self.created_at),
        }


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[Any | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]

    def to_dict(self, logs: list[dict]) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "status": self.status,
            "meta": self.meta,
            "result": self.result,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "logs": logs,
        }


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(server_default=func.now())
    level: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)

    def to_dict(self) -> dict:
        return {"ts": _iso(self.ts), "level": self.level, "message": self.message}
