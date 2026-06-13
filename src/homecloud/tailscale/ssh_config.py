from __future__ import annotations

from homecloud.config import settings
from homecloud.tailscale.client import TailscaleClient


def ssh_config_block(
    *,
    host_alias: str,
    hostname: str,
    user: str | None = None,
    identity_file: str | None = None,
    local_forwards: list[tuple[int, str]] | None = None,
    comment: str | None = None,
) -> str:
    """Generate an OpenSSH config block for a tailnet host."""
    user = user or settings.tailscale_ssh_user
    fqdn = TailscaleClient.fqdn(hostname)
    lines: list[str] = []
    if comment:
        lines.append(f"# {comment}")
    lines.append(f"Host {host_alias}")
    lines.append(f"    HostName {fqdn}")
    lines.append(f"    User {user}")
    if identity_file:
        lines.append(f"    IdentityFile {identity_file}")
    for local_port, target in local_forwards or []:
        lines.append(f"    LocalForward {local_port} {target}")
    lines.append("")
    return "\n".join(lines)


def access_summary(
    *,
    host_alias: str,
    hostname: str,
    ports: list[int] | None = None,
) -> dict:
    """
    Summarize tailnet access for a machine.

    All TCP ports listening on the VM are reachable on the tailnet at
    hostname.tailnet:port — no per-port registration required.
    """
    fqdn = TailscaleClient.fqdn(hostname)
    port_urls = {str(p): TailscaleClient.magic_dns_url(hostname, p) for p in (ports or [])}
    return {
        "host_alias": host_alias,
        "magic_dns": fqdn,
        "ssh": ssh_config_block(host_alias=host_alias, hostname=hostname),
        "tailnet_ports": (
            "All TCP ports on this machine are reachable at "
            f"{fqdn}:<port> from your tailnet."
        ),
        "port_urls": port_urls,
    }
