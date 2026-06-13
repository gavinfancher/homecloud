"""Unit tests for publish_web / unpublish_web orchestration helpers.

All external calls (Cloudflare API, Caddy admin API / httpx) are disabled or
mocked.  A temporary directory is used for caddy_config_dir and a temporary
``.homecloud`` directory is used for state, so tests are fully isolated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import homecloud.proxy.caddy as caddy_module
import homecloud.publish as publish_module
import homecloud.state as state_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Redirect caddy_config_dir and state file to temporary directories."""
    caddy_dir = tmp_path / "caddy_sites"
    caddy_dir.mkdir()
    state_dir = tmp_path / ".homecloud"
    state_dir.mkdir()
    state_file = state_dir / "state.json"

    # Patch caddy settings.
    monkeypatch.setattr(caddy_module.settings, "caddy_config_dir", str(caddy_dir))
    monkeypatch.setattr(caddy_module.settings, "caddy_reload_cmd", "")  # no network
    monkeypatch.setattr(caddy_module.settings, "domain", "myhomecloud.dev")

    # Patch publish.settings (same object, but module-level access via settings).
    monkeypatch.setattr(publish_module.settings, "domain", "myhomecloud.dev")

    # Redirect state file.
    monkeypatch.setattr(state_module, "STATE_FILE", state_file)

    # Disable Cloudflare — patch CloudflareDNS in the publish module's namespace
    # so instances created there return disabled no-ops (no network calls).
    from homecloud.cloudflare.dns import CloudflareDNS

    class _DisabledDNS(CloudflareDNS):
        def __init__(self):
            self.token = ""
            self.zone_id = ""
            self.tunnel_cname = ""
            self.domain = "myhomecloud.dev"

    # publish.py imports CloudflareDNS at module level, so we patch it there.
    monkeypatch.setattr("homecloud.publish.CloudflareDNS", lambda: _DisabledDNS())

    # Disable httpx in caddy module so no actual HTTP calls are attempted.
    def _noop_post(*args, **kwargs):
        pass  # caddy_reload_cmd is empty anyway; this is a belt-and-suspenders guard

    monkeypatch.setattr(caddy_module.httpx, "post", _noop_post)

    return {
        "caddy_dir": caddy_dir,
        "state_file": state_file,
    }


# ---------------------------------------------------------------------------
# publish_web — Caddy site file
# ---------------------------------------------------------------------------


def test_publish_web_writes_caddy_file(isolated):
    publish_module.publish_web(
        "app", "grafana", 3000, upstream_host="100.1.2.3"
    )
    expected = isolated["caddy_dir"] / "grafana.app.caddy"
    assert expected.exists(), "Caddy site file must be created"


def test_publish_web_caddy_file_contents(isolated):
    publish_module.publish_web(
        "app", "grafana", 3000, upstream_host="100.1.2.3"
    )
    contents = (isolated["caddy_dir"] / "grafana.app.caddy").read_text()
    assert "http://grafana.app.myhomecloud.dev" in contents
    assert "reverse_proxy 100.1.2.3:3000" in contents


def test_publish_web_returns_dict(isolated):
    result = publish_module.publish_web(
        "myvm", "api", 8080, upstream_host="100.7.7.7"
    )
    assert result["hostname"] == "api.myvm.myhomecloud.dev"
    assert "caddy_config" in result
    assert "cloudflare_record_id" in result


# ---------------------------------------------------------------------------
# publish_web — state effects
# ---------------------------------------------------------------------------


def test_publish_web_records_state(isolated):
    publish_module.publish_web(
        "app", "grafana", 3000, upstream_host="100.1.2.3", public=True
    )
    state = json.loads(isolated["state_file"].read_text())
    web_list = state["vms"]["app"]["web"]
    assert len(web_list) == 1
    entry = web_list[0]
    assert entry["service"] == "grafana"
    assert entry["port"] == 3000
    assert entry["public_host"] == "grafana.app.myhomecloud.dev"
    assert entry["public"] is True
    assert entry["caddy_config"] == "grafana.app.caddy"


def test_publish_web_private_skips_cloudflare_record_id(isolated):
    """When public=False, cloudflare_record_id should be empty."""
    result = publish_module.publish_web(
        "db", "postgres", 5432, upstream_host="100.2.2.2", public=False
    )
    assert result["cloudflare_record_id"] == ""
    state = json.loads(isolated["state_file"].read_text())
    entry = state["vms"]["db"]["web"][0]
    assert entry["public"] is False
    assert entry["cloudflare_record_id"] == ""


def test_publish_web_upserts_existing_service(isolated):
    """Publishing the same service twice must update the existing entry, not append."""
    publish_module.publish_web("app", "grafana", 3000, upstream_host="100.1.2.3")
    publish_module.publish_web("app", "grafana", 3001, upstream_host="100.1.2.4")

    state = json.loads(isolated["state_file"].read_text())
    web_list = state["vms"]["app"]["web"]
    assert len(web_list) == 1, "Duplicate service must not create a second entry"
    assert web_list[0]["port"] == 3001
    assert web_list[0]["public_host"] == "grafana.app.myhomecloud.dev"


def test_publish_web_multiple_services(isolated):
    publish_module.publish_web("app", "grafana", 3000, upstream_host="100.1.2.3")
    publish_module.publish_web("app", "prometheus", 9090, upstream_host="100.1.2.3")

    state = json.loads(isolated["state_file"].read_text())
    services = {e["service"] for e in state["vms"]["app"]["web"]}
    assert services == {"grafana", "prometheus"}


# ---------------------------------------------------------------------------
# unpublish_web — Caddy site file removed
# ---------------------------------------------------------------------------


def test_unpublish_web_removes_caddy_file(isolated):
    publish_module.publish_web("app", "grafana", 3000, upstream_host="100.1.2.3")
    assert (isolated["caddy_dir"] / "grafana.app.caddy").exists()

    publish_module.unpublish_web("app", "grafana")
    assert not (isolated["caddy_dir"] / "grafana.app.caddy").exists()


def test_unpublish_web_removes_state_entry(isolated):
    publish_module.publish_web("app", "grafana", 3000, upstream_host="100.1.2.3")
    publish_module.unpublish_web("app", "grafana")

    state = json.loads(isolated["state_file"].read_text())
    web_list = state["vms"]["app"].get("web", [])
    assert all(e["service"] != "grafana" for e in web_list)


def test_unpublish_web_only_removes_target_service(isolated):
    publish_module.publish_web("app", "grafana", 3000, upstream_host="100.1.2.3")
    publish_module.publish_web("app", "prometheus", 9090, upstream_host="100.1.2.3")
    publish_module.unpublish_web("app", "grafana")

    state = json.loads(isolated["state_file"].read_text())
    web_list = state["vms"]["app"]["web"]
    services = [e["service"] for e in web_list]
    assert "grafana" not in services
    assert "prometheus" in services


def test_unpublish_web_noop_when_not_published(isolated):
    """unpublish_web must not raise when the service was never published."""
    publish_module.unpublish_web("ghost-vm", "nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# state helpers — set_instance_web_service / remove_instance_web_service
# ---------------------------------------------------------------------------


def test_set_instance_web_service_creates_entry(isolated):
    state_module.set_instance_web_service(
        "myvm",
        service="api",
        port=8080,
        public_host="api.myvm.myhomecloud.dev",
        public=True,
        cloudflare_record_id="rec123",
        caddy_config="api.myvm.caddy",
    )
    vm = state_module.get_instance("myvm")
    assert vm is not None
    assert len(vm["web"]) == 1
    assert vm["web"][0]["service"] == "api"


def test_remove_instance_web_service_removes_entry(isolated):
    state_module.set_instance_web_service(
        "myvm",
        service="api",
        port=8080,
        public_host="api.myvm.myhomecloud.dev",
        public=True,
        cloudflare_record_id="rec123",
        caddy_config="api.myvm.caddy",
    )
    state_module.remove_instance_web_service("myvm", "api")
    vm = state_module.get_instance("myvm")
    assert vm is not None
    assert vm["web"] == []


def test_remove_instance_web_service_noop_unknown_instance(isolated):
    state_module.remove_instance_web_service("ghost", "api")  # must not raise


def test_get_instance_returns_none_for_unknown(isolated):
    assert state_module.get_instance("nope") is None
