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
    (e.g. ``dagster.gavin.myhomecloud.dev``).  Without it: ``<instance>.<domain>``.
    """
    instance = short_name(name)
    if settings.owner_username:
        return f"{instance}.{settings.owner_username}.{settings.domain}"
    return f"{instance}.{settings.domain}"


def ssh_command(name: str) -> str:
    return f"ssh {settings.vm_ssh_user}@{private_fqdn(name)}"


def connection_info(name: str, tailscale_ip: str) -> dict:
    magic = vm_fqdn(name)
    private = private_fqdn(name)
    return {
        "hostname": private,
        "private_host": private,
        "magic_dns": magic,
        "tailscale_ip": tailscale_ip,
        "ip": tailscale_ip,
        "ssh": ssh_command(name),
    }
