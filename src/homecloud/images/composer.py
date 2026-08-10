"""Compose cloud-init user-data from a custom image definition.

The document is built as a dict and serialized with PyYAML rather than
rendered from a Jinja template: config file contents are arbitrary user input
(TOML, JSON, shell, keys with colons and newlines) and string interpolation
into YAML would break on them.
"""

from __future__ import annotations

from typing import Any

import yaml

BOOTSTRAP_DONE_MARKER = "/var/lib/homecloud/image-build.done"

# The guest agent is the controller's only channel into the VM, so it must not
# be installed through cloud-init's `packages:` list. That list is handed to a
# single `apt-get install pkg1 pkg2 …`, so one bad user package (`nvim` instead
# of `neovim`) fails the whole transaction and the agent never appears — the
# build then waits on a guest it can never reach. Installing it from runcmd
# keeps it independent: runcmd still executes after the package module fails.
_AGENT_BOOTSTRAP = """\
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y qemu-guest-agent
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y qemu-guest-agent
elif command -v yum >/dev/null 2>&1; then
  yum install -y qemu-guest-agent
fi
systemctl enable --now qemu-guest-agent || true
"""


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
    for pkg in packages or []:
        pkg = pkg.strip()
        if pkg and pkg not in seen:
            seen.add(pkg)
            all_packages.append(pkg)
    if all_packages:
        doc["packages"] = all_packages

    write_files = [normalize_config_file(f) for f in (config_files or [])]
    if write_files:
        doc["write_files"] = write_files

    runcmd: list[Any] = [["bash", "-c", _AGENT_BOOTSTRAP]]
    runcmd.extend(cmd for cmd in (run_commands or []) if cmd.strip())
    # A marker file lets the builder confirm cloud-init reached the end instead
    # of guessing from a fixed sleep. It means "finished", not "succeeded" —
    # runcmd still runs after an earlier module fails — so the builder checks
    # `cloud-init status` once the marker appears.
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
