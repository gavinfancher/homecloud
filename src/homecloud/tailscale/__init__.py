"""Tailscale integration — MagicDNS, auth keys, SSH config export."""

from homecloud.tailscale.client import TailscaleClient
from homecloud.tailscale.ssh_config import access_summary, ssh_config_block

__all__ = ["TailscaleClient", "access_summary", "ssh_config_block"]
