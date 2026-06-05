from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SetupRequest(BaseModel):
    ssh_public_key: str = Field(..., min_length=20)


_VALID_SIZE_IDS = ("micro", "small", "medium", "large", "xlarge")
_VALID_SIZE_IDS_STR = ", ".join(_valid for _valid in _VALID_SIZE_IDS)


class DeployVMRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9-]{1,30}$")
    size_id: str | None = None
    cores: int | None = Field(None, ge=1, le=32)
    memory_gb: float | None = Field(None, ge=0.5, le=64)
    disk_gb: int | None = Field(None, ge=10, le=2000)
    image_id: str = "homecloud-base"

    @model_validator(mode="after")
    def resolve_size_or_resources(self) -> DeployVMRequest:
        from homecloud.sizes import get_size

        using_preset = self.size_id is not None and self.size_id != "custom"
        has_any_custom = any(
            v is not None for v in (self.cores, self.memory_gb, self.disk_gb)
        )

        if using_preset and has_any_custom:
            raise ValueError(
                "Conflicting request: provide either size_id (preset) "
                "or explicit cores/memory_gb/disk_gb, not both"
            )

        if using_preset:
            size = get_size(self.size_id)  # type: ignore[arg-type]
            if size is None:
                raise ValueError(
                    f"Unknown size_id '{self.size_id}'. "
                    f"Valid presets: {_VALID_SIZE_IDS_STR}"
                )
            self.cores = size.cores
            self.memory_gb = size.memory_gb
            self.disk_gb = size.disk_gb
        else:
            # Custom or explicit-resource path — all three fields required.
            missing = [
                field
                for field, val in (
                    ("cores", self.cores),
                    ("memory_gb", self.memory_gb),
                    ("disk_gb", self.disk_gb),
                )
                if val is None
            ]
            if missing:
                raise ValueError(
                    "Either size_id (preset) or all of cores, memory_gb, disk_gb "
                    f"must be provided. Missing: {', '.join(missing)}"
                )
            # Normalise: treat an explicit size_id="custom" the same as omitting it.
            if self.size_id is None:
                self.size_id = "custom"

        return self
