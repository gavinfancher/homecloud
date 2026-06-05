"""Port discovery for homecloud instances.

Preferred transport: SSH to the instance's Tailscale IP, running
``ss -H -tlnp`` (with process names when root) or ``ss -H -tln`` (fallback).

Fallback transport: Proxmox QEMU guest-agent ``exec``.

The ``parse_ss_output`` function is intentionally pure (no I/O) so it can
be unit-tested without any network access.
"""
from __future__ import annotations

import logging
import re
import subprocess

from homecloud.config import settings

logger = logging.getLogger(__name__)

# Loopback addresses that indicate a port cannot be directly proxied.
_LOOPBACK_ADDRS = frozenset({"127.0.0.1", "::1"})

# Matches the first quoted name inside a ``users:((...))`` field.
_PROC_RE = re.compile(r'"([^"]+)"')

_NOT_PUBLISHABLE_REASON = (
    "loopback-only bind; the service must listen on 0.0.0.0 or a tailnet "
    "address before it can be proxied"
)


# ---------------------------------------------------------------------------
# Pure parser — no I/O, fully unit-testable
# ---------------------------------------------------------------------------


def parse_ss_output(text: str) -> list[dict]:
    """Parse ``ss -H -tln[p]`` text output into a list of port dicts.

    Each dict contains:
        port        int       – listening port number
        proc        str|None  – process name (None when run without -p / not root)
        address     str       – bind address (e.g. "0.0.0.0", "127.0.0.1", "::")
        publishable bool      – False when the bind address is loopback-only
        not_publishable_reason  str  – (only present when publishable is False)

    Entries are de-duplicated by (address, port); first occurrence wins.
    IPv6 ``[::]`` and IPv4 ``*`` wildcards are preserved as-is (``*`` is
    normalised to ``0.0.0.0``).
    """
    results: list[dict] = []
    seen: set[tuple[str, int]] = set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        # Minimum columns: State  Recv-Q  Send-Q  Local:Port  Peer:Port
        if len(parts) < 5:
            continue

        local_addr_str = parts[3]

        # IPv6 format: [addr]:port
        if local_addr_str.startswith("["):
            try:
                bracket_end = local_addr_str.index("]")
            except ValueError:
                continue
            address = local_addr_str[1:bracket_end]
            port_str = local_addr_str[bracket_end + 2:]  # skip "]:"
        else:
            # IPv4 / wildcard: addr:port  (rfind handles dotted addresses)
            colon_pos = local_addr_str.rfind(":")
            if colon_pos == -1:
                continue
            address = local_addr_str[:colon_pos]
            port_str = local_addr_str[colon_pos + 1:]

        # Normalise wildcard shortcuts used by some ss versions
        if address in ("*", ""):
            address = "0.0.0.0"

        try:
            port = int(port_str)
        except ValueError:
            continue

        key = (address, port)
        if key in seen:
            continue
        seen.add(key)

        # Extract process name from: users:(("proc",pid=X,fd=Y),...)
        proc: str | None = None
        # The users field may be at index 5 or later; join tail to be safe.
        tail = " ".join(parts[5:]) if len(parts) > 5 else ""
        if tail:
            m = _PROC_RE.search(tail)
            if m:
                proc = m.group(1)

        publishable = address not in _LOOPBACK_ADDRS
        entry: dict = {
            "port": port,
            "proc": proc,
            "address": address,
            "publishable": publishable,
        }
        if not publishable:
            entry["not_publishable_reason"] = _NOT_PUBLISHABLE_REASON

        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# Transport layer — SSH preferred, guest_exec fallback
# ---------------------------------------------------------------------------


def scan_ports(instance: dict) -> list[dict]:
    """Scan listening TCP ports on *instance*.

    Args:
        instance: Instance state dict; must contain ``tailscale_ip`` and/or
                  ``vmid``.  Extra keys are ignored.

    Returns:
        List of port dicts as returned by :func:`parse_ss_output`.
        Returns an empty list when all transports fail (non-fatal).
    """
    tailscale_ip: str | None = instance.get("tailscale_ip")
    vmid: int | str | None = instance.get("vmid")
    name: str = instance.get("name", "<unknown>")

    if tailscale_ip and settings.vm_ssh_user:
        try:
            ports = _scan_via_ssh(tailscale_ip)
            logger.info("SSH port scan succeeded for %s: %d ports", name, len(ports))
            return ports
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SSH port scan failed for %s (%s): %s; trying guest_exec",
                name,
                tailscale_ip,
                exc,
            )

    if vmid is not None:
        try:
            ports = _scan_via_guest_exec(int(vmid))
            logger.info(
                "guest_exec port scan succeeded for %s (vmid=%s): %d ports",
                name,
                vmid,
                len(ports),
            )
            return ports
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "guest_exec port scan failed for %s (vmid=%s): %s",
                name,
                vmid,
                exc,
            )

    logger.error(
        "Port scan failed: no reachable transport for instance %s", name
    )
    return []


def _scan_via_ssh(tailscale_ip: str) -> list[dict]:
    """SSH into *tailscale_ip* and run ``ss``."""
    user = settings.vm_ssh_user
    # Try privileged scan first (includes process names); fall back gracefully
    # within the remote shell if the user is not root.
    remote_cmd = "ss -H -tlnp 2>/dev/null || ss -H -tln"
    result = subprocess.run(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            f"{user}@{tailscale_ip}",
            remote_cmd,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ssh exited {result.returncode}: {result.stderr.strip()}"
        )
    return parse_ss_output(result.stdout)


def _scan_via_guest_exec(vmid: int) -> list[dict]:
    """Use Proxmox QEMU guest agent to run ``ss -H -tln``."""
    # Import lazily so the module can be imported without a Proxmox connection.
    from homecloud.proxmox.client import ProxmoxClient  # noqa: PLC0415

    client = ProxmoxClient()
    output = client.guest_exec(vmid, ["ss", "-H", "-tln"])
    return parse_ss_output(output)
