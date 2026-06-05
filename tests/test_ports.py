"""Tests for Phase 05 — port discovery and service routing.

All tests are unit / integration-lite: no network, no SSH, no Proxmox.
The ``parse_ss_output`` function is tested with static fixtures.
The API routes are tested via FastAPI ``TestClient`` with all external effects
(Cloudflare, Caddy, SSH) disabled through monkeypatching.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import homecloud.proxy.caddy as caddy_module
import homecloud.publish as publish_module
import homecloud.state as state_module
from homecloud.ports import parse_ss_output


# ---------------------------------------------------------------------------
# Fixtures: sample ``ss`` output strings
# ---------------------------------------------------------------------------

# Root format — with process names (ss -H -tlnp)
SS_ROOT_IPV4 = """\
LISTEN  0  128  0.0.0.0:22       0.0.0.0:*  users:(("sshd",pid=847,fd=3))
LISTEN  0  100  0.0.0.0:80       0.0.0.0:*  users:(("nginx",pid=1234,fd=6))
LISTEN  0  50   127.0.0.1:5432   0.0.0.0:*  users:(("postgres",pid=3000,fd=5))
"""

# Root format — IPv6 entries
SS_ROOT_IPV6 = """\
LISTEN  0  128  [::]:22          [::]:*  users:(("sshd",pid=847,fd=4))
LISTEN  0  50   [::1]:6379       [::]:*  users:(("redis",pid=4000,fd=3))
LISTEN  0  100  [::]:3000        [::]:*  users:(("grafana",pid=5000,fd=7))
"""

# Non-root format — no process names (ss -H -tln)
SS_NON_ROOT = """\
LISTEN  0  128  0.0.0.0:22       0.0.0.0:*
LISTEN  0  100  0.0.0.0:80       0.0.0.0:*
LISTEN  0  50   127.0.0.1:5432   0.0.0.0:*
"""

# Wildcard address (*) form used by some ss versions
SS_WILDCARD = """\
LISTEN  0  128  *:22             *:*  users:(("sshd",pid=1,fd=3))
LISTEN  0  100  *:443            *:*  users:(("caddy",pid=2,fd=4))
"""

# Duplicate lines (same address+port should appear only once)
SS_DUPLICATES = """\
LISTEN  0  128  0.0.0.0:22       0.0.0.0:*  users:(("sshd",pid=1,fd=3))
LISTEN  0  128  0.0.0.0:22       0.0.0.0:*  users:(("sshd",pid=2,fd=3))
"""

# Mixed IPv4 + IPv6 on same port (dual-stack: both should appear)
SS_DUAL_STACK = """\
LISTEN  0  128  0.0.0.0:22       0.0.0.0:*
LISTEN  0  128  [::]:22          [::]:*
"""

# Empty / garbage lines
SS_EMPTY = ""
SS_GARBAGE = "not valid ss output at all\n\n"


# ---------------------------------------------------------------------------
# parse_ss_output — port, proc, address extraction
# ---------------------------------------------------------------------------


def test_ipv4_root_port_and_proc():
    results = parse_ss_output(SS_ROOT_IPV4)
    by_port = {r["port"]: r for r in results}
    assert by_port[22]["proc"] == "sshd"
    assert by_port[22]["address"] == "0.0.0.0"
    assert by_port[80]["proc"] == "nginx"
    assert by_port[5432]["proc"] == "postgres"
    assert by_port[5432]["address"] == "127.0.0.1"


def test_ipv6_root_port_and_proc():
    results = parse_ss_output(SS_ROOT_IPV6)
    by_port = {r["port"]: r for r in results}
    assert by_port[22]["address"] == "::"
    assert by_port[22]["proc"] == "sshd"
    assert by_port[6379]["address"] == "::1"
    assert by_port[6379]["proc"] == "redis"
    assert by_port[3000]["address"] == "::"
    assert by_port[3000]["proc"] == "grafana"


def test_non_root_no_proc():
    results = parse_ss_output(SS_NON_ROOT)
    assert all(r["proc"] is None for r in results)
    ports = {r["port"] for r in results}
    assert {22, 80, 5432} == ports


def test_wildcard_normalised_to_ipv4_any():
    results = parse_ss_output(SS_WILDCARD)
    addresses = {r["address"] for r in results}
    assert "0.0.0.0" in addresses
    assert "*" not in addresses


def test_wildcard_proc_extracted():
    results = parse_ss_output(SS_WILDCARD)
    by_port = {r["port"]: r for r in results}
    assert by_port[22]["proc"] == "sshd"
    assert by_port[443]["proc"] == "caddy"


# ---------------------------------------------------------------------------
# parse_ss_output — loopback flagging
# ---------------------------------------------------------------------------


def test_loopback_ipv4_not_publishable():
    results = parse_ss_output(SS_ROOT_IPV4)
    by_port = {r["port"]: r for r in results}
    assert by_port[5432]["publishable"] is False
    assert "not_publishable_reason" in by_port[5432]


def test_wildcard_ipv4_publishable():
    results = parse_ss_output(SS_ROOT_IPV4)
    by_port = {r["port"]: r for r in results}
    assert by_port[22]["publishable"] is True
    assert by_port[80]["publishable"] is True


def test_loopback_ipv6_not_publishable():
    results = parse_ss_output(SS_ROOT_IPV6)
    by_port = {r["port"]: r for r in results}
    assert by_port[6379]["publishable"] is False
    assert "not_publishable_reason" in by_port[6379]


def test_wildcard_ipv6_publishable():
    results = parse_ss_output(SS_ROOT_IPV6)
    by_port = {r["port"]: r for r in results}
    assert by_port[22]["publishable"] is True
    assert by_port[3000]["publishable"] is True


# ---------------------------------------------------------------------------
# parse_ss_output — de-duplication
# ---------------------------------------------------------------------------


def test_dedup_same_address_port():
    results = parse_ss_output(SS_DUPLICATES)
    assert len(results) == 1
    assert results[0]["port"] == 22


def test_dual_stack_both_included():
    """IPv4 and IPv6 entries on the same port are different (different address)."""
    results = parse_ss_output(SS_DUAL_STACK)
    assert len(results) == 2
    addresses = {r["address"] for r in results}
    assert "0.0.0.0" in addresses
    assert "::" in addresses


# ---------------------------------------------------------------------------
# parse_ss_output — edge cases
# ---------------------------------------------------------------------------


def test_empty_string_returns_empty():
    assert parse_ss_output(SS_EMPTY) == []


def test_garbage_returns_empty():
    assert parse_ss_output(SS_GARBAGE) == []


def test_result_has_required_keys():
    results = parse_ss_output(SS_ROOT_IPV4)
    for r in results:
        assert "port" in r
        assert "proc" in r
        assert "address" in r
        assert "publishable" in r
        assert isinstance(r["port"], int)


# ---------------------------------------------------------------------------
# Fixtures: isolated API test environment (no network)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_api(tmp_path, monkeypatch):
    """
    Redirect state and caddy config to tmp dirs; disable all external I/O.
    Returns a FastAPI TestClient.
    """
    caddy_dir = tmp_path / "caddy_sites"
    caddy_dir.mkdir()
    state_dir = tmp_path / ".homecloud"
    state_dir.mkdir()
    state_file = state_dir / "state.json"

    monkeypatch.setattr(caddy_module.settings, "caddy_config_dir", str(caddy_dir))
    monkeypatch.setattr(caddy_module.settings, "caddy_reload_cmd", "")
    monkeypatch.setattr(caddy_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(publish_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(state_module, "STATE_FILE", state_file)

    # Disable Cloudflare DNS
    from homecloud.cloudflare.dns import CloudflareDNS

    class _DisabledDNS(CloudflareDNS):
        def __init__(self):
            self.token = ""
            self.zone_id = ""
            self.tunnel_cname = ""
            self.domain = "myhomecloud.dev"

    monkeypatch.setattr("homecloud.publish.CloudflareDNS", lambda: _DisabledDNS())

    # Disable httpx in caddy module (belt-and-suspenders)
    monkeypatch.setattr(caddy_module.httpx, "post", lambda *a, **kw: None)

    # Seed state with a registered instance that has tailscale_ip + ports_seen
    seed_state = {
        "setup_complete": True,
        "ssh_public_key": "ssh-ed25519 AAAAC3 test",
        "built_templates": {},
        "custom_templates": {},
        "vms": {
            "app": {
                "vmid": 501,
                "name": "app",
                "tailscale_ip": "100.1.2.3",
                "web": [],
                "ports_seen": [
                    {"port": 3000, "proc": "grafana", "address": "0.0.0.0", "publishable": True},
                    {"port": 22, "proc": "sshd", "address": "0.0.0.0", "publishable": True},
                    {"port": 5432, "proc": "postgres", "address": "127.0.0.1", "publishable": False,
                     "not_publishable_reason": "loopback-only bind"},
                ],
                "ports_scanned_at": "2026-06-05T12:00:00+00:00",
            }
        },
    }
    state_file.write_text(json.dumps(seed_state))

    from homecloud.main import app

    client = TestClient(app, raise_server_exceptions=True)
    return {"client": client, "state_file": state_file, "caddy_dir": caddy_dir}


# ---------------------------------------------------------------------------
# GET /api/vms/{name}/ports
# ---------------------------------------------------------------------------


def test_get_ports_returns_seen(isolated_api):
    resp = isolated_api["client"].get("/api/vms/app/ports")
    assert resp.status_code == 200
    data = resp.json()
    assert "ports_seen" in data
    ports = {p["port"] for p in data["ports_seen"]}
    assert 3000 in ports
    assert data["ports_scanned_at"] is not None


def test_get_ports_unknown_instance(isolated_api):
    resp = isolated_api["client"].get("/api/vms/ghost/ports")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/vms/{name}/services — validation
# ---------------------------------------------------------------------------


def test_publish_service_bad_name_uppercase(isolated_api):
    resp = isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "Grafana", "port": 3000, "public": True},
    )
    assert resp.status_code == 422  # schema validation


def test_publish_service_bad_name_starts_digit(isolated_api):
    resp = isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "1grafana", "port": 3000, "public": True},
    )
    assert resp.status_code == 422


def test_publish_service_bad_name_too_long(isolated_api):
    long_name = "a" * 32  # exceeds 31-char limit
    resp = isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": long_name, "port": 3000, "public": True},
    )
    assert resp.status_code == 422


def test_publish_service_unseen_port_rejected(isolated_api):
    """Port 9999 was not in the last scan; must be rejected without force."""
    resp = isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "metrics", "port": 9999, "public": True},
    )
    assert resp.status_code == 400
    assert "9999" in resp.json()["detail"]


def test_publish_service_unseen_port_force_allowed(isolated_api):
    """force=true bypasses the seen-port check."""
    resp = isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "metrics", "port": 9999, "public": False, "force": True},
    )
    assert resp.status_code == 200
    assert "hostname" in resp.json()


def test_publish_service_seen_port_succeeds(isolated_api):
    resp = isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "grafana", "port": 3000, "public": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hostname"] == "grafana.app.myhomecloud.dev"


def test_publish_service_persists_state(isolated_api):
    isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "grafana", "port": 3000, "public": False},
    )
    state = json.loads(isolated_api["state_file"].read_text())
    web = state["vms"]["app"]["web"]
    assert any(e["service"] == "grafana" for e in web)


def test_publish_service_unknown_instance(isolated_api):
    resp = isolated_api["client"].post(
        "/api/vms/ghost/services",
        json={"service": "grafana", "port": 3000, "public": False},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/vms/{name}/services/{service}
# ---------------------------------------------------------------------------


def test_delete_service_removes_state(isolated_api):
    # First publish
    isolated_api["client"].post(
        "/api/vms/app/services",
        json={"service": "grafana", "port": 3000, "public": False},
    )
    state = json.loads(isolated_api["state_file"].read_text())
    assert any(e["service"] == "grafana" for e in state["vms"]["app"]["web"])

    # Then unpublish
    resp = isolated_api["client"].delete("/api/vms/app/services/grafana")
    assert resp.status_code == 200
    state = json.loads(isolated_api["state_file"].read_text())
    assert not any(e["service"] == "grafana" for e in state["vms"]["app"].get("web", []))


def test_delete_service_noop_not_published(isolated_api):
    resp = isolated_api["client"].delete("/api/vms/app/services/nonexistent")
    assert resp.status_code == 200  # no-op is graceful


# ---------------------------------------------------------------------------
# POST /api/vms/{name}/scan-ports — job creation (no live SSH)
# ---------------------------------------------------------------------------


def test_scan_ports_creates_job(isolated_api, monkeypatch):
    """scan-ports returns a job_id without making network calls."""
    import homecloud.ports as ports_module

    # Stub scan_ports to return a fixture list immediately
    monkeypatch.setattr(
        ports_module,
        "scan_ports",
        lambda _instance: [
            {"port": 80, "proc": "nginx", "address": "0.0.0.0", "publishable": True}
        ],
    )

    resp = isolated_api["client"].post("/api/vms/app/scan-ports")
    assert resp.status_code == 200
    assert "job_id" in resp.json()


def test_scan_ports_unknown_instance(isolated_api):
    resp = isolated_api["client"].post("/api/vms/ghost/scan-ports")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PublishServiceRequest validator (direct schema test)
# ---------------------------------------------------------------------------


def test_schema_valid_service_name():
    from homecloud.api.schemas import PublishServiceRequest

    req = PublishServiceRequest(service="grafana", port=3000, public=True)
    assert req.service == "grafana"


def test_schema_invalid_service_uppercase():
    from pydantic import ValidationError

    from homecloud.api.schemas import PublishServiceRequest

    with pytest.raises(ValidationError):
        PublishServiceRequest(service="Grafana", port=3000)


def test_schema_invalid_service_starts_digit():
    from pydantic import ValidationError

    from homecloud.api.schemas import PublishServiceRequest

    with pytest.raises(ValidationError):
        PublishServiceRequest(service="1bad", port=3000)


def test_schema_valid_service_with_hyphen():
    from homecloud.api.schemas import PublishServiceRequest

    req = PublishServiceRequest(service="my-api", port=8080)
    assert req.service == "my-api"


def test_schema_force_default_false():
    from homecloud.api.schemas import PublishServiceRequest

    req = PublishServiceRequest(service="api", port=8080)
    assert req.force is False
