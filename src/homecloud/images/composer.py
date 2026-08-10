"""Compose cloud-init user-data from a custom image definition.

The document is built as a dict and serialized with PyYAML rather than
rendered from a Jinja template: config file contents are arbitrary user input
(TOML, JSON, shell, keys with colons and newlines) and string interpolation
into YAML would break on them.
"""

from __future__ import annotations

from typing import Any

import yaml

# Always present so the controller can drive the VM after boot: the guest
# agent is how `prepare_for_template` and IP discovery talk to it.
REQUIRED_PACKAGES = ["qemu-guest-agent"]

BOOTSTRAP_DONE_MARKER = "/var/lib/homecloud/image-build.done"


def normalize_config_file(entry: dict) -> dict[str, Any]:
    """Turn one stored config-file entry into a cloud-init ``write_files`` item."""
    path = str(entry.get("path", "")).strip()
    if not path:
        raise ValueError("Config file entries need a path")
    if not path.startswith("/"):
        raise ValueError(f"Config file path must be absolute: {path!r}")

    item: dict[str, Any] = {
        "path": path,
        "content": entry.get("content", ""),
    }
    if entry.get("permissions"):
        item["permissions"] = str(entry["permissions"])
    if entry.get("owner"):
        item["owner"] = str(entry["owner"])
    return item


def compose_cloud_init(
    *,
    hostname: str,
    ssh_user: str,
    ssh_public_keys: list[str],
    packages: list[str] | None = None,
    config_files: list[dict] | None = None,
    run_commands: list[str] | None = None,
) -> str:
    """Build the cloud-config document used to bake a custom image."""
    doc: dict[str, Any] = {
        "hostname": hostname,
        "package_update": True,
        "package_upgrade": True,
    }

    if ssh_public_keys:
        doc["ssh_authorized_keys"] = list(ssh_public_keys)

    # Dedupe while preserving the order the user listed them in.
    seen: set[str] = set()
    all_packages: list[str] = []
    for pkg in [*REQUIRED_PACKAGES, *(packages or [])]:
        pkg = pkg.strip()
        if pkg and pkg not in seen:
            seen.add(pkg)
            all_packages.append(pkg)
    doc["packages"] = all_packages

    write_files = [normalize_config_file(f) for f in (config_files or [])]
    if write_files:
        doc["write_files"] = write_files

    runcmd: list[Any] = [["systemctl", "enable", "--now", "qemu-guest-agent"]]
    runcmd.extend(cmd for cmd in (run_commands or []) if cmd.strip())
    # A marker file lets the builder confirm the run commands actually finished
    # instead of guessing from a fixed sleep.
    runcmd.append(["mkdir", "-p", "/var/lib/homecloud"])
    runcmd.append(["touch", BOOTSTRAP_DONE_MARKER])
    doc["runcmd"] = runcmd

    doc["users"] = [
        {
            "name": ssh_user,
            "sudo": "ALL=(ALL) NOPASSWD:ALL",
            "shell": "/bin/bash",
            "lock_passwd": True,
            **({"ssh_authorized_keys": list(ssh_public_keys)} if ssh_public_keys else {}),
        }
    ]

    doc["final_message"] = "homecloud image build complete"

    body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=4096)
    return f"#cloud-config\n{body}"
