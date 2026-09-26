"""The role catalog: Ansible roles shipped in ``provision/roles`` plus their UI metadata.

Each role directory holds an ordinary Ansible role and a ``homecloud.yml``
describing it to the console — label, description, whether it is required
or pre-selected, where it runs in the play, and the variables the create flow renders a form
for. Requests are validated against that metadata here, so the playbook the
runner generates only ever contains known roles with well-typed variables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROLES_DIR = Path(__file__).parent / "roles"

VAR_TYPES = ("string", "text", "list", "bool", "files")
_OCTAL_MODE = re.compile(r"0?[0-7]{3,4}")


class RoleError(ValueError):
    """A role selection that does not match the catalog."""


@dataclass(frozen=True)
class RoleVar:
    name: str
    label: str
    type: str
    default: Any = None
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "description": self.description,
        }


@dataclass(frozen=True)
class RoleSpec:
    id: str
    label: str
    description: str
    required: bool = False
    # Pre-selected in the create flow (required roles always are).
    default_enabled: bool = False
    order: int = 100
    vars: list[RoleVar] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "required": self.required,
            "default_enabled": self.required or self.default_enabled,
            "order": self.order,
            "vars": [v.to_dict() for v in self.vars],
        }


def _load_role(path: Path) -> RoleSpec:
    meta = yaml.safe_load((path / "homecloud.yml").read_text()) or {}
    role_vars = []
    for raw in meta.get("vars") or []:
        if raw.get("type") not in VAR_TYPES:
            raise RuntimeError(f"Role {path.name}: var {raw.get('name')!r} has unknown type")
        role_vars.append(
            RoleVar(
                name=raw["name"],
                label=raw.get("label", raw["name"]),
                type=raw["type"],
                default=raw.get("default"),
                description=raw.get("description", ""),
            )
        )
    return RoleSpec(
        id=path.name,
        label=meta.get("label", path.name),
        description=meta.get("description", ""),
        required=bool(meta.get("required", False)),
        default_enabled=bool(meta.get("default_enabled", False)),
        order=int(meta.get("order", 100)),
        vars=role_vars,
    )


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, RoleSpec]:
    roles = [
        _load_role(p)
        for p in ROLES_DIR.iterdir()
        if p.is_dir() and (p / "homecloud.yml").exists()
    ]
    return {r.id: r for r in sorted(roles, key=lambda r: (r.order, r.id))}


def list_roles() -> list[dict]:
    return [r.to_dict() for r in load_catalog().values()]


def _coerce(role_id: str, var: RoleVar, value: Any) -> Any:
    where = f"{role_id}.{var.name}"
    if var.type in ("string", "text"):
        if not isinstance(value, str):
            raise RoleError(f"{where} must be a string")
        return value
    if var.type == "bool":
        if not isinstance(value, bool):
            raise RoleError(f"{where} must be true or false")
        return value
    if var.type == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise RoleError(f"{where} must be a list of strings")
        return [v.strip() for v in value if v.strip()]
    # files
    if not isinstance(value, list):
        raise RoleError(f"{where} must be a list of files")
    files = []
    for entry in value:
        if not isinstance(entry, dict):
            raise RoleError(f"{where} entries must be objects")
        path = str(entry.get("path", "")).strip()
        if not path.startswith("/"):
            raise RoleError(f"{where}: file path must be absolute, got {path!r}")
        mode = str(entry.get("mode") or "").strip()
        if mode and not _OCTAL_MODE.fullmatch(mode):
            raise RoleError(f"{where}: mode must be octal like 0644, got {mode!r}")
        files.append(
            {
                "path": path,
                "content": str(entry.get("content", "")),
                "mode": mode or None,
                "owner": str(entry.get("owner") or "").strip() or None,
            }
        )
    return files


def resolve_roles(selection: list[dict]) -> list[dict]:
    """Validate a ``[{id, vars}]`` selection and return it complete and in play order.

    Required roles are added when missing, every variable is filled from its
    default when not given, and unknown roles or variables are rejected.
    """
    catalog = load_catalog()
    chosen: dict[str, dict] = {}
    for item in selection:
        role_id = item.get("id")
        spec = catalog.get(role_id)  # type: ignore[arg-type]
        if spec is None:
            raise RoleError(f"Unknown role: {role_id}")
        if role_id in chosen:
            raise RoleError(f"Role listed twice: {role_id}")
        given = dict(item.get("vars") or {})
        known = {v.name: v for v in spec.vars}
        unknown = set(given) - set(known)
        if unknown:
            raise RoleError(f"Unknown variables for {role_id}: {', '.join(sorted(unknown))}")
        chosen[role_id] = {
            name: _coerce(role_id, var, given[name]) if name in given else var.default
            for name, var in known.items()
        }

    for spec in catalog.values():
        if spec.required and spec.id not in chosen:
            chosen[spec.id] = {v.name: v.default for v in spec.vars}

    return [{"id": rid, "vars": chosen[rid]} for rid in catalog if rid in chosen]
