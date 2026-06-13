from __future__ import annotations

from homecloud.config import settings
from homecloud.tailscale.client import TailscaleClient


def short_name(name: str) -> str:
    """Strip any domain suffix — VMs register on Tailscale by short hostname."""
    return name.split(".")[0]


def vm_fqdn(name: str) -> str:
    return TailscaleClient.fqdn(short_name(name))


def ssh_command(name: str) -> str:
    return f"ssh {settings.vm_ssh_user}@{vm_fqdn(name)}"


def connection_info(name: str, tailscale_ip: str) -> dict:
    fqdn = vm_fqdn(name)
    return {
        "hostname": fqdn,
        "magic_dns": fqdn,
        "tailscale_ip": tailscale_ip,
        "ip": tailscale_ip,
        "ssh": ssh_command(name),
    }
