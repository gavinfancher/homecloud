from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Size:
    id: str
    label: str
    cores: int
    memory_gb: float
    disk_gb: int


SIZES: dict[str, Size] = {
    "micro": Size(id="micro", label="Micro", cores=1, memory_gb=1.0, disk_gb=10),
    "small": Size(id="small", label="Small", cores=1, memory_gb=2.0, disk_gb=20),
    "medium": Size(id="medium", label="Medium", cores=2, memory_gb=4.0, disk_gb=40),
    "large": Size(id="large", label="Large", cores=4, memory_gb=8.0, disk_gb=80),
    "xlarge": Size(id="xlarge", label="X-Large", cores=8, memory_gb=16.0, disk_gb=160),
}


def list_sizes() -> list[Size]:
    """Return all preset sizes in definition order."""
    return list(SIZES.values())


def get_size(size_id: str) -> Size | None:
    """Return the Size for *size_id*, or None if not found (including 'custom')."""
    return SIZES.get(size_id)
