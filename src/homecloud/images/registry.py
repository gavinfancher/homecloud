from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ImageKind(StrEnum):
    BUILTIN = "builtin"
    CUSTOM = "custom"


@dataclass
class ImageSpec:
    id: str
    name: str
    description: str
    kind: ImageKind
    template_id: int | None = None
    default_cores: int = 2
    default_memory_mb: int = 4096
    default_disk_gb: int = 20
    packages: list[str] = field(default_factory=list)


BUILTIN_IMAGES: dict[str, ImageSpec] = {
    "homecloud-base": ImageSpec(
        id="homecloud-base",
        name="Homecloud Base",
        description="Ubuntu with docker, uv, tailscale, and dev basics",
        kind=ImageKind.BUILTIN,
        packages=["docker", "uv", "tailscale", "curl", "tmux", "neovim"],
        default_cores=2,
        default_memory_mb=2048,
        default_disk_gb=10,
    ),
}


def list_images() -> list[ImageSpec]:
    return list(BUILTIN_IMAGES.values())


def get_image(image_id: str) -> ImageSpec | None:
    return BUILTIN_IMAGES.get(image_id)
