from __future__ import annotations

import json
from pathlib import Path

STATE_FILE = Path(".homecloud/state.json")

_VALID_KEY_PREFIXES = ("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {
            "setup_complete": False,
            "ssh_public_key": None,
            "ssh_public_keys": [],
            "built_templates": {},
            "custom_templates": {},
            "vms": {},
        }
    state = json.loads(STATE_FILE.read_text())
    state.setdefault("setup_complete", False)
    state.setdefault("ssh_public_key", None)
    state.setdefault("ssh_public_keys", [])
    state.setdefault("vms", {})
    # Backfill: if legacy single-key state exists but list is empty, migrate it.
    if state["ssh_public_key"] and not state["ssh_public_keys"]:
        state["ssh_public_keys"] = [state["ssh_public_key"]]
    return state


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _validate_key(raw: str) -> str:
    """Normalize and validate a single SSH public key; raise ValueError if invalid."""
    key = raw.strip().splitlines()[0]
    if not key.startswith(_VALID_KEY_PREFIXES):
        short = key[:60]
        raise ValueError(f"Invalid SSH public key format: {short!r}")
    return key


def get_ssh_public_key() -> str | None:
    """Return the first stored SSH public key (back-compat helper)."""
    state = load_state()
    keys = state.get("ssh_public_keys", [])
    return keys[0] if keys else state.get("ssh_public_key")


def get_ssh_public_keys() -> list[str]:
    """Return all stored SSH public keys."""
    return load_state().get("ssh_public_keys", [])


def save_setup(
    *,
    ssh_public_key: str | None = None,
    ssh_public_keys: list[str] | None = None,
) -> None:
    """Persist SSH public key(s) and mark setup complete.

    Accepts a single key via *ssh_public_key* (legacy callers) or a list via
    *ssh_public_keys*.  When both are supplied they are merged.  Each key is
    validated for format, duplicates are removed (order preserved), and the
    first key is also stored in the legacy ``ssh_public_key`` field for
    backward compatibility.

    Note: changing keys only affects *new* images/instances.  A base-image
    rebuild is required to bake new keys into future VMs.
    """
    raw: list[str] = []
    if ssh_public_keys:
        raw.extend(ssh_public_keys)
    if ssh_public_key and ssh_public_key not in raw:
        raw.append(ssh_public_key)

    if not raw:
        raise ValueError("At least one SSH public key is required")

    validated: list[str] = [_validate_key(k) for k in raw]

    # Dedupe, preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for k in validated:
        if k not in seen:
            seen.add(k)
            deduped.append(k)

    state = load_state()
    state["ssh_public_keys"] = deduped
    state["ssh_public_key"] = deduped[0]  # back-compat: first key
    state["setup_complete"] = True
    save_state(state)


def is_setup_complete() -> bool:
    state = load_state()
    has_key = bool(state.get("ssh_public_keys") or state.get("ssh_public_key"))
    return bool(state.get("setup_complete") and has_key)


def set_built_template(image_id: str, template_id: int) -> None:
    state = load_state()
    state.setdefault("built_templates", {})[image_id] = template_id
    save_state(state)


def get_built_template(image_id: str) -> int | None:
    state = load_state()
    return state.get("built_templates", {}).get(image_id)


def register_custom_template(name: str, template_id: int, base_image_id: str) -> None:
    state = load_state()
    state.setdefault("custom_templates", {})[name] = {
        "template_id": template_id,
        "base_image_id": base_image_id,
    }
    save_state(state)


def register_vm(name: str, record: dict) -> None:
    state = load_state()
    state.setdefault("vms", {})[name] = record
    save_state(state)


def unregister_vm(name: str) -> None:
    state = load_state()
    state.get("vms", {}).pop(name, None)
    save_state(state)


def list_registered_vms() -> dict:
    return load_state().get("vms", {})


def hydrate_registry() -> None:
    from homecloud.images.registry import BUILTIN_IMAGES

    state = load_state()
    for image_id, template_id in state.get("built_templates", {}).items():
        if image_id in BUILTIN_IMAGES:
            BUILTIN_IMAGES[image_id].template_id = template_id


# ---------------------------------------------------------------------------
# Instance helpers (Phase 04 additions — additive, non-breaking)
# ---------------------------------------------------------------------------


def get_instance(name: str) -> dict | None:
    """Return the state record for instance *name*, or None if not registered."""
    return load_state().get("vms", {}).get(name)


def set_instance_web_service(
    instance_name: str,
    *,
    service: str,
    port: int,
    public_host: str,
    public: bool,
    cloudflare_record_id: str,
    caddy_config: str,
) -> None:
    """Upsert a web service entry in the instance's ``web`` list.

    Finds any existing entry with the same ``service`` name and replaces it;
    appends a new entry otherwise.  Does not modify other keys of the instance
    record.
    """
    state = load_state()
    vm = state.setdefault("vms", {}).setdefault(instance_name, {})
    web_list: list[dict] = vm.setdefault("web", [])

    entry = {
        "service": service,
        "port": port,
        "public_host": public_host,
        "public": public,
        "cloudflare_record_id": cloudflare_record_id,
        "caddy_config": caddy_config,
    }

    for i, item in enumerate(web_list):
        if item.get("service") == service:
            web_list[i] = entry
            break
    else:
        web_list.append(entry)

    save_state(state)


def remove_instance_web_service(instance_name: str, service: str) -> None:
    """Remove the web service entry for *service* from *instance_name*.

    No-op when the instance or service is not found.
    """
    state = load_state()
    vm = state.get("vms", {}).get(instance_name)
    if vm is None:
        return
    vm["web"] = [e for e in vm.get("web", []) if e.get("service") != service]
    save_state(state)


# ---------------------------------------------------------------------------
# Port-scan helpers (Phase 05 additions — additive, non-breaking)
# ---------------------------------------------------------------------------


def set_instance_ports(instance_name: str, ports: list[dict]) -> None:
    """Persist port-scan results for *instance_name*.

    Stores the list under ``ports_seen`` and records the current UTC timestamp
    in ``ports_scanned_at``.  Creates the instance entry if it does not yet
    exist in state (edge case: scan called before full registration).
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    state = load_state()
    vm = state.setdefault("vms", {}).setdefault(instance_name, {})
    vm["ports_seen"] = list(ports)
    vm["ports_scanned_at"] = datetime.now(UTC).isoformat()
    save_state(state)
