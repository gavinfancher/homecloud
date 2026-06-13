from __future__ import annotations

from homecloud.config import settings
from homecloud.dns.names import vm_fqdn


def ssh_config_block(
    *,
    host_alias: str,
    hostname: str,
    user: str | None = None,
    identity_file: str | None = None,
) -> str:
    user = user or settings.vm_ssh_user
    fqdn = vm_fqdn(hostname)
    lines = [f"Host {host_alias}", f"    HostName {fqdn}", f"    User {user}"]
    if identity_file:
        lines.append(f"    IdentityFile {identity_file}")
    lines.append("")
    return "\n".join(lines)
