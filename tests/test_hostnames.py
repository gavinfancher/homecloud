"""Tests for username-namespaced hostnames (phase 12)."""
from __future__ import annotations

import homecloud.publish as publish_module
from homecloud.dns.zone import render_zone
from homecloud.publish import host_label

CONTROL_IP = "100.64.0.1"
INSTANCES = {"dagster": {"tailscale_ip": "100.1.1.1"}}


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
