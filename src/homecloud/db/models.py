"""ORM mappings. The schema itself is owned by ``migrations/*.sql``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class BaseImageConfig(Base):
    """The single editable base image definition (row id 1)."""

    __tablename__ = "base_image_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    image_url: Mapped[str] = mapped_column(Text)
    packages: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extra_user_data: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "image_url": self.image_url,
            "packages": self.packages,
            "extra_user_data": self.extra_user_data,
            "updated_at": _iso(self.updated_at),
        }


class BaseImage(Base):
    """One build of the base image: a config snapshot and the template it made."""

    __tablename__ = "base_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(Text, default="building")
    image_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(Text)
    ssh_keys: Mapped[list[str]] = mapped_column(JSONB, default=list)
    packages: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extra_user_data: Mapped[str] = mapped_column(Text, default="")
    template_vmid: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    built_at: Mapped[datetime | None]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "image_url": self.image_url,
            "sha256": self.sha256,
            "ssh_keys": self.ssh_keys,
            "packages": self.packages,
            "extra_user_data": self.extra_user_data,
            "template_vmid": self.template_vmid,
            "error": self.error,
            "created_at": _iso(self.created_at),
            "built_at": _iso(self.built_at),
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
    # NULL for instances cloned from a template that predates base images.
    base_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("base_images.id", ondelete="SET NULL")
    )
    size_id: Mapped[str] = mapped_column(Text, default="custom")
    cores: Mapped[int | None]
    memory_mb: Mapped[int | None]
    disk_gb: Mapped[int | None]
    local_ip: Mapped[str | None] = mapped_column(Text)
    tailscale_ip: Mapped[str | None] = mapped_column(Text)
    tailscale_device_id: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list[Any]] = mapped_column(JSONB, default=list)
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
            "base_image_id": self.base_image_id,
            "tailscale_device_id": self.tailscale_device_id,
            "size_id": self.size_id,
            "cores": self.cores,
            "memory_mb": self.memory_mb,
            "memory_gb": round(self.memory_mb / 1024, 2) if self.memory_mb else None,
            "disk_gb": self.disk_gb,
            "roles": self.roles,
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
