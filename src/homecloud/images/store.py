"""CRUD helpers over the image tables.

Every function here is a no-op-safe wrapper the API can call: when no
DATABASE_URL is configured the listers return empty results rather than
raising, so the console still renders the built-in registry.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from homecloud.db.models import BuildStatus, CloudImage, CustomImage
from homecloud.db.session import db_enabled, session_scope


class ImageNotFound(Exception):
    pass


class ImageConflict(Exception):
    pass


def list_cloud_images() -> list[dict]:
    if not db_enabled():
        return []
    with session_scope() as session:
        rows = session.scalars(select(CloudImage).order_by(CloudImage.name)).all()
        return [row.to_dict() for row in rows]


def list_custom_images() -> list[dict]:
    if not db_enabled():
        return []
    with session_scope() as session:
        rows = session.scalars(select(CustomImage).order_by(CustomImage.created_at)).all()
        return [row.to_dict() for row in rows]


def get_custom_image(image_id: str) -> dict | None:
    if not db_enabled():
        return None
    with session_scope() as session:
        row = session.get(CustomImage, image_id)
        return row.to_dict() if row else None


def _require_cloud_image(session: Session, cloud_image_id: str) -> CloudImage:
    cloud = session.get(CloudImage, cloud_image_id)
    if cloud is None:
        raise ImageNotFound(f"Unknown cloud image: {cloud_image_id}")
    return cloud


def create_custom_image(payload: dict) -> dict:
    with session_scope() as session:
        if session.get(CustomImage, payload["id"]) is not None:
            raise ImageConflict(f"Image {payload['id']} already exists")
        _require_cloud_image(session, payload["cloud_image_id"])

        image = CustomImage(
            id=payload["id"],
            name=payload["name"],
            description=payload.get("description", ""),
            cloud_image_id=payload["cloud_image_id"],
            packages=payload.get("packages", []),
            config_files=payload.get("config_files", []),
            run_commands=payload.get("run_commands", []),
            default_cores=payload.get("default_cores", 2),
            default_memory_mb=payload.get("default_memory_mb", 2048),
            default_disk_gb=payload.get("default_disk_gb", 10),
            status=BuildStatus.DRAFT,
        )
        session.add(image)
        session.flush()
        return image.to_dict()


# Editing any of these invalidates an existing build — the template on the node
# no longer matches the definition, so the image drops back to draft.
_BUILD_AFFECTING = {"cloud_image_id", "packages", "config_files", "run_commands"}


def update_custom_image(image_id: str, changes: dict) -> dict:
    with session_scope() as session:
        image = session.get(CustomImage, image_id)
        if image is None:
            raise ImageNotFound(f"Unknown image: {image_id}")
        if image.status == BuildStatus.BUILDING:
            raise ImageConflict("Image is currently building — wait for the job to finish")

        if "cloud_image_id" in changes:
            _require_cloud_image(session, changes["cloud_image_id"])

        for field, value in changes.items():
            setattr(image, field, value)

        if _BUILD_AFFECTING & set(changes) and image.status == BuildStatus.BUILT:
            image.status = BuildStatus.DRAFT

        session.flush()
        return image.to_dict()


def delete_custom_image(image_id: str) -> dict:
    """Remove the definition. The Proxmox template, if any, is left in place."""
    with session_scope() as session:
        image = session.get(CustomImage, image_id)
        if image is None:
            raise ImageNotFound(f"Unknown image: {image_id}")
        if image.status == BuildStatus.BUILDING:
            raise ImageConflict("Image is currently building — wait for the job to finish")
        template_id = image.template_id
        session.delete(image)
        return {"deleted": image_id, "template_id": template_id}


def create_cloud_image(payload: dict) -> dict:
    with session_scope() as session:
        if session.get(CloudImage, payload["id"]) is not None:
            raise ImageConflict(f"Cloud image {payload['id']} already exists")
        cloud = CloudImage(**payload, builtin=False)
        session.add(cloud)
        session.flush()
        return cloud.to_dict()


def delete_cloud_image(cloud_image_id: str) -> dict:
    with session_scope() as session:
        cloud = session.get(CloudImage, cloud_image_id)
        if cloud is None:
            raise ImageNotFound(f"Unknown cloud image: {cloud_image_id}")
        if cloud.builtin:
            raise ImageConflict("Built-in cloud images cannot be deleted")
        if cloud.custom_images:
            used_by = ", ".join(img.id for img in cloud.custom_images)
            raise ImageConflict(f"Cloud image is still used by: {used_by}")
        session.delete(cloud)
        return {"deleted": cloud_image_id}
