"""Integration tests against live Proxmox (requires .env with valid token)."""

from __future__ import annotations

import pytest

from homecloud.access import ssh_config_block
from homecloud.config import settings
from homecloud.dns.names import vm_fqdn
from homecloud.proxmox.client import ProxmoxClient


pytestmark = pytest.mark.skipif(
    not settings.proxmox_token_value,
    reason="PROXMOX_TOKEN_VALUE not configured",
)


def test_settings():
    assert settings.proxmox_node == "pve-root"
    assert settings.tailscale_tailnet


def test_list_templates_includes_ubuntu_base():
    client = ProxmoxClient()
    templates = client.list_templates()
    assert 9000 in {t["vmid"] for t in templates}


def test_ssh_config_block():
    block = ssh_config_block(host_alias="dagster", hostname="dagster")
    assert "Host dagster" in block
    assert vm_fqdn("dagster") in block
