"""Tests for username-namespaced hostnames (phase 12)."""
from __future__ import annotations

import homecloud.publish as publish_module
from homecloud.dns.names import connection_info, private_fqdn, ssh_command
from homecloud.dns.zone import render_zone
from homecloud.publish import host_label

CONTROL_IP = "100.64.0.1"
INSTANCES = {"dagster": {"tailscale_ip": "100.1.1.1"}}


def test_private_fqdn_flat_without_username(monkeypatch):
    monkeypatch.setattr(publish_module.settings, "owner_username", "")
    monkeypatch.setattr(publish_module.settings, "domain", "myhomecloud.dev")
    assert private_fqdn("dagster") == "dagster.myhomecloud.dev"


def test_private_fqdn_namespaced_with_username(monkeypatch):
    monkeypatch.setattr(publish_module.settings, "owner_username", "gavin")
    monkeypatch.setattr(publish_module.settings, "domain", "myhomecloud.dev")
    assert private_fqdn("dagster") == "dagster.gavin.myhomecloud.dev"


def test_connection_info_exposes_private_and_magic(monkeypatch):
    monkeypatch.setattr(publish_module.settings, "owner_username", "gavin")
    monkeypatch.setattr(publish_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(publish_module.settings, "vm_ssh_user", "ubuntu")
    monkeypatch.setattr(
        "homecloud.dns.names.TailscaleClient.fqdn",
        lambda _name: "dagster.tailnet.ts.net",
    )
    info = connection_info("dagster", "100.1.1.1")
    assert info["hostname"] == "dagster.gavin.myhomecloud.dev"
    assert info["private_host"] == "dagster.gavin.myhomecloud.dev"
    assert info["magic_dns"] == "dagster.tailnet.ts.net"
    assert info["ssh"] == "ssh ubuntu@dagster.gavin.myhomecloud.dev"


def test_ssh_command_uses_private_host(monkeypatch):
    monkeypatch.setattr(publish_module.settings, "owner_username", "gavin")
    monkeypatch.setattr(publish_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(publish_module.settings, "vm_ssh_user", "ubuntu")
    assert ssh_command("dagster") == "ssh ubuntu@dagster.gavin.myhomecloud.dev"


def test_host_label_flat_without_username(monkeypatch):
    monkeypatch.setattr(publish_module.settings, "owner_username", "")
    assert host_label("airflow", "dagster") == "airflow.dagster"


def test_host_label_namespaced_with_username(monkeypatch):
    monkeypatch.setattr(publish_module.settings, "owner_username", "gavin")
    assert host_label("airflow", "dagster") == "airflow.dagster.gavin"


def test_render_zone_namespaces_under_username():
    zone = render_zone(INSTANCES, CONTROL_IP, serial=1, username="gavin")
    assert "dagster.gavin" in zone
    assert "*.dagster.gavin" in zone


def test_render_zone_flat_without_username():
    zone = render_zone(INSTANCES, CONTROL_IP, serial=1, username="")
    assert "dagster.gavin" not in zone
    # flat record still present
    assert any(line.startswith("dagster") for line in zone.splitlines())
