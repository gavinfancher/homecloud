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


_IMAGE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_PACKAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")


def _check_image_id(v: str) -> str:
    if not _IMAGE_ID_RE.match(v):
        raise ValueError(
            "id must match ^[a-z][a-z0-9-]{1,30}$ "
            "(lowercase letters, digits, hyphens; start with a letter)"
        )
    return v


def _check_packages(v: list[str]) -> list[str]:
    cleaned = [p.strip() for p in v if p.strip()]
    for pkg in cleaned:
        if not _PACKAGE_RE.fullmatch(pkg):
            raise ValueError(f"Invalid package name: {pkg!r}")
    return cleaned


class ConfigFileSpec(BaseModel):
    """A file baked into the image via cloud-init ``write_files``."""

    path: str = Field(..., description="Absolute path in the guest, e.g. /etc/myapp/config.toml")
    content: str = ""
    permissions: str | None = Field(None, description="Octal mode string, e.g. '0644'")
    owner: str | None = Field(None, description="owner:group, e.g. 'root:root'")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("/"):
            raise ValueError("Config file path must be absolute (start with '/')")
        return v

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not re.fullmatch(r"0?[0-7]{3}", v):
            raise ValueError("permissions must be an octal mode like '0644'")
        return v


class CustomImageRequest(BaseModel):
    """Body for ``POST /api/images``."""

    id: str = Field(..., description="Slug, e.g. 'web-node'")
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    cloud_image_id: str = Field(..., description="Base cloud image, e.g. 'ubuntu-24.04'")
    packages: list[str] = Field(default_factory=list)
    config_files: list[ConfigFileSpec] = Field(default_factory=list)
    run_commands: list[str] = Field(default_factory=list)
    default_cores: int = Field(2, ge=1, le=32)
    default_memory_mb: int = Field(2048, ge=512, le=65536)
    default_disk_gb: int = Field(10, ge=5, le=2000)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _check_image_id(v)

    @field_validator("packages")
    @classmethod
    def validate_packages(cls, v: list[str]) -> list[str]:
        return _check_packages(v)


class CustomImageUpdate(BaseModel):
    """Body for ``PATCH /api/images/{id}`` — every field optional."""

    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    cloud_image_id: str | None = None
    packages: list[str] | None = None
    config_files: list[ConfigFileSpec] | None = None
    run_commands: list[str] | None = None
    default_cores: int | None = Field(None, ge=1, le=32)
    default_memory_mb: int | None = Field(None, ge=512, le=65536)
    default_disk_gb: int | None = Field(None, ge=5, le=2000)

    @field_validator("packages")
    @classmethod
    def validate_packages(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _check_packages(v)


class CloudImageRequest(BaseModel):
    """Body for ``POST /api/cloud-images`` — register your own base image."""

    id: str = Field(..., description="Slug, e.g. 'alpine-3.21'")
    name: str = Field(..., min_length=1, max_length=128)
    distro: str = Field(..., min_length=1, max_length=32)
    version: str = Field(..., min_length=1, max_length=32)
    url: str = Field(..., description="Direct URL to a .img/.qcow2 cloud image")
    sha256: str | None = Field(None, pattern=r"^[A-Fa-f0-9]{64}$")
    ssh_user: str = "ubuntu"
    arch: str = "amd64"

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return _check_image_id(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must be an http(s) URL")
        return v


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
