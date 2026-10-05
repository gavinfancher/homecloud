"""One-shot import of the pre-Postgres ``.homecloud/state.json``.

Idempotent: keys and instances already in the database are left alone, so
the import can be re-run safely.  ``jobs.json`` is intentionally not
imported — job history starts fresh.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from homecloud.db.models import Instance, SshKey
from homecloud.db.session import session_scope


def import_state(path: Path) -> dict:
    """Import SSH keys and instances from *path*; returns what was added."""
    data = json.loads(path.read_text())

    keys = list(data.get("ssh_public_keys") or [])
    if data.get("ssh_public_key") and data["ssh_public_key"] not in keys:
        keys.append(data["ssh_public_key"])

    added_keys: list[str] = []
    added_instances: list[str] = []
    skipped_instances: list[str] = []
    with session_scope() as session:
        existing_keys = set(session.scalars(select(SshKey.public_key)))
        for key in dict.fromkeys(k.strip() for k in keys if k.strip()):
            if key not in existing_keys:
                session.add(SshKey(public_key=key))
                added_keys.append(key.split()[-1] if len(key.split()) > 2 else key[:24])

        for name, record in (data.get("vms") or {}).items():
            if session.get(Instance, name) is not None or not record.get("vmid"):
                skipped_instances.append(name)
                continue
            memory_mb = record.get("memory_mb")
            if memory_mb is None and record.get("memory_gb") is not None:
                memory_mb = int(record["memory_gb"] * 1024)
            session.add(
                Instance(
                    name=name,
                    vmid=int(record["vmid"]),
                    # Legacy instances were cloned from the old homecloud-base
                    # template, which is not a source.
                    source_id=None,
                    size_id=record.get("size_id") or "custom",
                    cores=record.get("cores"),
                    memory_mb=memory_mb,
                    disk_gb=record.get("disk_gb"),
                    local_ip=record.get("local_ip"),
                    tailscale_ip=record.get("tailscale_ip") or record.get("ip"),
                    roles=record.get("roles") or [],
                    web=record.get("web") or [],
                    ports_seen=record.get("ports_seen"),
                )
            )
            added_instances.append(name)

    return {
        "ssh_keys_added": added_keys,
        "instances_added": added_instances,
        "instances_skipped": skipped_instances,
    }
