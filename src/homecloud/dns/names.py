from __future__ import annotations

from homecloud.config import settings
from homecloud.tailscale.client import TailscaleClient


def short_name(name: str) -> str:
    """Strip any domain suffix — VMs register on Tailscale by short hostname."""
    return name.split(".")[0]


def vm_fqdn(name: str) -> str:
    return TailscaleClient.fqdn(short_name(name))


def private_fqdn(name: str) -> str:
    """Friendly private hostname on the split-DNS zone (CoreDNS).

    With ``OWNER_USERNAME`` set: ``<instance>.<username>.<domain>``
    (e.g. ``dagster.gavin.homecloud.dev``).  Without it: ``<instance>.<domain>``.
    """
    instance = short_name(name)
    if settings.owner_username:
        return f"{instance}.{settings.owner_username}.{settings.domain}"
    return f"{instance}.{settings.domain}"


def ssh_command(name: str) -> str:
    return f"ssh {settings.vm_ssh_user}@{private_fqdn(name)}"


def connection_info(name: str, tailscale_ip: str, local_ip: str | None = None) -> dict:
    """Connection details surfaced by the API for an instance.

    *local_ip* is the VM's LAN (DHCP) address; the Tailscale MagicDNS name is
    deliberately not exposed — the split-DNS ``hostname`` is the name to use.
    """
    private = private_fqdn(name)
    return {
        "hostname": private,
        "private_host": private,
        "tailscale_ip": tailscale_ip,
        "ip": tailscale_ip,
        "local_ip": local_ip or "",
        "ssh": ssh_command(name),
    }
