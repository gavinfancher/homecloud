"""Port discovery for homecloud instances.

Runs ``ss -H -tlnp`` in the guest through the Proxmox QEMU guest agent — no
SSH. The agent runs commands as root, so process names are included.

The ``parse_ss_output`` function is intentionally pure (no I/O) so it can
be unit-tested without any network access.
"""
from __future__ import annotations

import re

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

        # ss appends the interface to scoped binds (127.0.0.53%lo).
        publishable = address.split("%")[0] not in _LOOPBACK_ADDRS and not address.startswith(
            "127."
        )
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
# Transport — the guest agent
# ---------------------------------------------------------------------------


def scan_ports(instance: dict) -> list[dict]:
    """Scan listening TCP ports on *instance* (needs ``vmid``).

    Raises when the guest agent cannot run the command, so the job shows why.
    """
    # Import lazily so the module can be imported without a Proxmox connection.
    from homecloud.proxmox.client import ProxmoxClient  # noqa: PLC0415

    result = ProxmoxClient().guest_run(int(instance["vmid"]), ["ss", "-H", "-tlnp"], timeout=60)
    if result["exitcode"] != 0:
        raise RuntimeError(f"ss failed in the guest: {result['err'].strip() or result['exitcode']}")
    return parse_ss_output(result["out"])
