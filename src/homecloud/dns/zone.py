"""CoreDNS zone-file generation for private split DNS (Phase 06).

render_zone() produces a valid RFC 1035 zone file for the myhomecloud.dev zone,
assigning each registered instance its tailnet IP.  write_zone() reads state and
writes the file to the configured path, then optionally runs a reload command.

Both functions degrade gracefully when the zone directory does not exist (dev
environment without CoreDNS infra).
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from homecloud.config import settings
from homecloud.state import list_registered_vms

logger = logging.getLogger(__name__)


def _default_serial() -> int:
    """Return a monotonically increasing serial based on the current unix timestamp."""
    return int(time.time())


def render_zone(
    instances: dict,
    control_node_ip: str,
    *,
    serial: int | None = None,
    domain: str | None = None,
    username: str | None = None,
) -> str:
    """Render a CoreDNS zone file string for *domain* (default: settings.domain).

    Parameters
    ----------
    instances:
        Dict of instance name → state record.  Records without a ``tailscale_ip``
        are silently skipped.
    control_node_ip:
        Tailnet IP of the control node, used for the NS ``A`` record.
    serial:
        Zone serial number.  Defaults to the current unix timestamp (monotonic
        across calls).  Pass an explicit value for deterministic tests.
    domain:
        Zone origin.  Defaults to ``settings.domain`` (``myhomecloud.dev``).
    """
    _domain = domain or settings.domain
    _serial = serial if serial is not None else _default_serial()
    _username = settings.owner_username if username is None else username

    lines: list[str] = [
        f"$ORIGIN {_domain}.",
        "$TTL 60",
        (
            f"@   IN SOA ns.{_domain}. admin.{_domain}."
            f" ( {_serial} 7200 3600 1209600 60 )"
        ),
        f"@   IN NS  ns.{_domain}.",
        f"ns  IN A   {control_node_ip}",
    ]

    for name, record in instances.items():
        ip = record.get("tailscale_ip") or record.get("ip")
        if not ip:
            continue
        # Namespace under the owner's username to mirror the public scheme
        # (<instance>.<username>); fall back to the flat name when unset.
        node = f"{name}.{_username}" if _username else name
        lines.append(f"{node:<20} IN A   {ip}")
        lines.append(f"*.{node:<18} IN A   {ip}")

    lines.append("")  # trailing newline
    return "\n".join(lines)


def write_zone() -> None:
    """Read instances from state, render the zone file, and write it to disk.

    No-ops gracefully when the target directory does not exist (dev environment
    without CoreDNS).  A zone-write failure is logged as a warning and never
    propagates to the caller.
    """
    zone_path = Path(settings.coredns_zone_path)
    if not zone_path.parent.exists():
        logger.warning(
            "CoreDNS zone directory %s does not exist — skipping zone write (no infra)",
            zone_path.parent,
        )
        return

    try:
        instances = list_registered_vms()
        control_ip = settings.control_node_tailscale_ip
        if not control_ip:
            logger.warning(
                "CONTROL_NODE_TAILSCALE_IP is not set — zone NS record will be empty"
            )
        zone_text = render_zone(instances, control_ip or "")
        zone_path.write_text(zone_text)
        logger.info("Wrote CoreDNS zone to %s (%d instance(s))", zone_path, len(instances))
    except Exception:
        logger.warning("Failed to write CoreDNS zone to %s", zone_path, exc_info=True)
        return

    reload_cmd = settings.coredns_reload_cmd
    if reload_cmd:
        try:
            subprocess.run(reload_cmd, shell=True, check=True, timeout=10)  # noqa: S602
            logger.info("CoreDNS reload command ran successfully")
        except Exception:
            logger.warning("CoreDNS reload command failed", exc_info=True)
