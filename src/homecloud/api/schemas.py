from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

_SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class SetupRequest(BaseModel):
    """Accept one SSH public key (legacy) or many (new multi-key path).

    Exactly one of ``ssh_public_key`` or ``ssh_public_keys`` must be supplied.
    Both can be supplied; duplicates are removed, preserving order.  After
    validation, ``ssh_public_keys`` is always a non-empty list and
    ``ssh_public_key`` is always set to the first key (back-compat).
    """

    ssh_public_key: str | None = Field(None, min_length=20)
    ssh_public_keys: list[str] | None = None

    @model_validator(mode="after")
    def normalize_keys(self) -> SetupRequest:
        has_single = self.ssh_public_key is not None
        has_list = bool(self.ssh_public_keys)

        if not has_single and not has_list:
            raise ValueError(
                "Provide ssh_public_key (single key) or ssh_public_keys (list); "
                "at least one key is required."
            )

        raw: list[str] = []
        if has_list:
            raw.extend(self.ssh_public_keys)  # type: ignore[arg-type]
        if has_single and self.ssh_public_key not in raw:
            raw.append(self.ssh_public_key)  # type: ignore[arg-type]

        # Dedupe preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for k in raw:
            if k not in seen:
                seen.add(k)
                deduped.append(k)

        self.ssh_public_keys = deduped
        self.ssh_public_key = deduped[0]
        return self


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


class PublishServiceRequest(BaseModel):
    """Body for ``POST /api/vms/{name}/services``."""

    service: str = Field(..., description="Service label, e.g. 'grafana'")
    port: int = Field(..., ge=1, le=65535)
    public: bool = True
    force: bool = Field(
        False,
        description="Bypass the 'port was seen in last scan' check.",
    )

    @field_validator("service")
    @classmethod
    def validate_service_name(cls, v: str) -> str:
        if not _SERVICE_RE.match(v):
            raise ValueError(
                "service must match ^[a-z][a-z0-9-]{1,30}$ "
                "(lowercase letters, digits, hyphens; start with a letter)"
            )
        return v
