import pytest

from homecloud.dns import names


@pytest.fixture
def cfg(settings, monkeypatch):
    monkeypatch.setattr(settings, "domain", "dns.example.com")
    monkeypatch.setattr(settings, "owner_username", "")
    monkeypatch.setattr(settings, "vm_ssh_user", "ubuntu")
    monkeypatch.setattr(settings, "tailscale_tailnet", "tail1234.ts.net")
    return settings


@pytest.mark.parametrize(
    ("name", "short"),
    [("pixie", "pixie"), ("pixie.dns.example.com", "pixie"), ("", "")],
)
def test_short_name(name, short):
    assert names.short_name(name) == short


def test_private_fqdn_flat(cfg):
    assert names.private_fqdn("pixie.anything") == "pixie.dns.example.com"


def test_private_fqdn_with_owner(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "owner_username", "gavin")
    assert names.private_fqdn("pixie") == "pixie.gavin.dns.example.com"


def test_vm_fqdn_uses_tailnet(cfg):
    assert names.vm_fqdn("pixie.dns.example.com") == "pixie.tail1234.ts.net"


def test_vm_fqdn_without_tailnet(cfg, monkeypatch):
    monkeypatch.setattr(cfg, "tailscale_tailnet", "")
    assert names.vm_fqdn("pixie") == "pixie"


def test_ssh_command(cfg):
    assert names.ssh_command("pixie") == "ssh ubuntu@pixie.dns.example.com"


def test_connection_info(cfg):
    assert names.connection_info("pixie", "100.64.0.9", "10.0.0.9") == {
        "hostname": "pixie.dns.example.com",
        "private_host": "pixie.dns.example.com",
        "tailscale_ip": "100.64.0.9",
        "ip": "100.64.0.9",
        "local_ip": "10.0.0.9",
        "ssh": "ssh ubuntu@pixie.dns.example.com",
    }
    assert names.connection_info("pixie", "100.64.0.9")["local_ip"] == ""
