"""Instance and SSH key records, stored in Postgres.

Every write is a single short transaction on one row, so concurrent jobs and
requests can no longer overwrite each other's changes the way the old
read-modify-write of ``state.json`` could.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, exists, select

from homecloud.db.models import Instance, SshKey
from homecloud.db.session import session_scope

_VALID_KEY_PREFIXES = ("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")

# Instance record keys that map straight onto columns.
_INSTANCE_FIELDS = (
    "vmid",
    "source_id",
    "size_id",
    "cores",
    "memory_mb",
    "disk_gb",
    "local_ip",
    "tailscale_ip",
    "roles",
    "web",
    "ports_seen",
)


def _validate_key(raw: str) -> str:
    """Normalize and validate a single SSH public key; raise ValueError if invalid."""
    key = raw.strip().splitlines()[0]
    if not key.startswith(_VALID_KEY_PREFIXES):
        short = key[:60]
        raise ValueError(f"Invalid SSH public key format: {short!r}")
    return key


def get_ssh_public_keys() -> list[str]:
    """Return all stored SSH public keys, oldest first."""
    with session_scope() as session:
        return list(session.scalars(select(SshKey.public_key).order_by(SshKey.id)))


def save_setup(
    *,
    ssh_public_key: str | None = None,
    ssh_public_keys: list[str] | None = None,
) -> None:
    """Replace the stored SSH public keys.

    Accepts a single key via *ssh_public_key* (legacy callers) or a list via
    *ssh_public_keys*; both are merged when supplied.  Each key is validated
    and duplicates are removed (order preserved).

    Note: changing keys only affects instances deployed afterwards.
    """
    raw: list[str] = []
    if ssh_public_keys:
        raw.extend(ssh_public_keys)
    if ssh_public_key and ssh_public_key not in raw:
        raw.append(ssh_public_key)

    if not raw:
        raise ValueError("At least one SSH public key is required")

    keys = list(dict.fromkeys(_validate_key(k) for k in raw))
    with session_scope() as session:
        session.execute(delete(SshKey))
        session.add_all(SshKey(public_key=k) for k in keys)


def is_setup_complete() -> bool:
    with session_scope() as session:
        return bool(session.scalar(select(exists().select_from(SshKey))))


def register_vm(name: str, record: dict) -> None:
    """Create or update the instance *name* from a record dict.

    ``memory_gb`` is accepted for callers that only know the size in GB.
    """
    fields = {k: record[k] for k in _INSTANCE_FIELDS if k in record}
    if "memory_mb" not in fields and record.get("memory_gb") is not None:
        fields["memory_mb"] = int(record["memory_gb"] * 1024)
    if "tailscale_ip" not in fields and record.get("ip"):
        fields["tailscale_ip"] = record["ip"]
    with session_scope() as session:
        row = session.get(Instance, name)
        if row is None:
            session.add(Instance(name=name, **fields))
            return
        for key, value in fields.items():
            setattr(row, key, value)


def set_instance_local_ip(name: str, local_ip: str) -> None:
    """Record the LAN address of *name*, but only when it actually changed.

    DHCP can move a VM to a new lease, so the stored value is refreshed from
    the guest agent; skipping no-op writes keeps the row quiet.
    """
    with session_scope() as session:
        row = session.get(Instance, name)
        if row is not None and row.local_ip != local_ip:
            row.local_ip = local_ip


def unregister_vm(name: str) -> None:
    with session_scope() as session:
        session.execute(delete(Instance).where(Instance.name == name))


def list_registered_vms() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(Instance).order_by(Instance.name))
        return {row.name: row.to_dict() for row in rows}


def get_instance(name: str) -> dict | None:
    """Return the record for instance *name*, or None if not registered."""
    with session_scope() as session:
        row = session.get(Instance, name)
        return row.to_dict() if row else None


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

    Replaces any existing entry with the same ``service`` name and appends a
    new one otherwise.  No-op when the instance is not registered.
    """
    entry = {
        "service": service,
        "port": port,
        "public_host": public_host,
        "public": public,
        "cloudflare_record_id": cloudflare_record_id,
        "caddy_config": caddy_config,
    }
    with session_scope() as session:
        row = session.get(Instance, instance_name, with_for_update=True)
        if row is None:
            return
        row.web = [e for e in row.web if e.get("service") != service] + [entry]


def remove_instance_web_service(instance_name: str, service: str) -> None:
    """Remove the web service entry for *service* from *instance_name*.

    No-op when the instance or service is not found.
    """
    with session_scope() as session:
        row = session.get(Instance, instance_name, with_for_update=True)
        if row is not None:
            row.web = [e for e in row.web if e.get("service") != service]


def set_instance_ports(instance_name: str, ports: list[dict]) -> None:
    """Persist port-scan results for *instance_name*. No-op when not registered."""
    with session_scope() as session:
        row = session.get(Instance, instance_name)
        if row is not None:
            row.ports_seen = list(ports)
            row.ports_scanned_at = datetime.now(UTC)
