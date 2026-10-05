"""CoreDNS zone files for the private split-DNS names of instances.

render_zone() produces an RFC 1035 zone giving each instance ``<vm>`` and
``*.<vm>`` → its tailnet IP. write_zone() renders it from the instances table
for the current zone and any legacy zones still being served, so a rename of
the zone can roll out without names disappearing mid-move.

Both degrade gracefully when the zone directory does not exist (dev
environment without CoreDNS infra).
"""

from __future__ import annotations

import logging
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
        Zone origin.  Defaults to ``settings.domain``.
    """
    _domain = domain or settings.domain
    _serial = serial if serial is not None else _default_serial()
    _username = settings.owner_username if username is None else username

    lines: list[str] = [
        f"$ORIGIN {_domain}.",
        "$TTL 30",
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


def zone_domains() -> list[str]:
    """The current zone first, then any legacy zones still being served."""
    legacy = [d.strip() for d in settings.dns_legacy_domains.split(",") if d.strip()]
    return list(dict.fromkeys([settings.domain, *legacy]))


def write_zone() -> None:
    """Render every served zone from the instances table and write it to disk.

    CoreDNS's ``file`` plugin notices the change and reloads on its own.
    No-ops when the zone directory does not exist (dev without CoreDNS); a
    failure is logged as a warning and never propagates to the caller.
    """
    zone_dir = Path(settings.coredns_zone_dir)
    if not zone_dir.is_dir():
        logger.warning("CoreDNS zone directory %s does not exist — skipping zone write", zone_dir)
        return

    try:
        instances = list_registered_vms()
        control_ip = settings.control_node_tailscale_ip
        if not control_ip:
            logger.warning("CONTROL_NODE_TAILSCALE_IP is not set — zone NS record will be empty")
        for domain in zone_domains():
            path = zone_dir / f"db.{domain}"
            path.write_text(render_zone(instances, control_ip or "", domain=domain))
            logger.info("Wrote CoreDNS zone %s (%d instance(s))", path, len(instances))
    except Exception:
        logger.warning("Failed to write CoreDNS zones to %s", zone_dir, exc_info=True)
