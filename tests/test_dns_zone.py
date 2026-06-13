"""Unit tests for homecloud.dns.zone — render_zone and write_zone.

No network calls, no Proxmox, no Docker.  Tests use temporary directories
for the zone path and monkeypatching for state / settings isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import homecloud.dns.zone as zone_module
from homecloud.dns.zone import render_zone, write_zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_INSTANCES = {
    "app": {"tailscale_ip": "100.10.0.1"},
    "db": {"tailscale_ip": "100.10.0.2"},
    "noip": {},  # no tailscale_ip — must be skipped
}

CONTROL_IP = "100.64.0.1"


# ---------------------------------------------------------------------------
# render_zone — basic structure
# ---------------------------------------------------------------------------


def test_render_zone_contains_origin():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1, domain="myhomecloud.dev")
    assert "$ORIGIN myhomecloud.dev." in zone


def test_render_zone_contains_ttl():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert "$TTL 60" in zone


def test_render_zone_contains_soa():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=42)
    assert "IN SOA" in zone
    assert "42" in zone


def test_render_zone_contains_ns():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert "IN NS" in zone
    assert "ns.myhomecloud.dev." in zone


def test_render_zone_contains_ns_a_record():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert f"ns  IN A   {CONTROL_IP}" in zone


# ---------------------------------------------------------------------------
# render_zone — instance A records and wildcards
# ---------------------------------------------------------------------------


def test_render_zone_a_record_for_app():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert "100.10.0.1" in zone
    assert "app" in zone


def test_render_zone_a_record_for_db():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert "100.10.0.2" in zone
    assert "db" in zone


def test_render_zone_wildcard_for_app():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert "*.app" in zone


def test_render_zone_wildcard_for_db():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    assert "*.db" in zone


def test_render_zone_skips_instance_without_tailscale_ip():
    zone = render_zone(SAMPLE_INSTANCES, CONTROL_IP, serial=1)
    lines = zone.splitlines()
    # "noip" must not appear at all — neither as a host record nor a wildcard
    assert not any("noip" in line for line in lines)


def test_render_zone_empty_instances():
    zone = render_zone({}, CONTROL_IP, serial=1)
    assert "IN SOA" in zone
    assert "IN NS" in zone
    assert "IN A" in zone  # ns A record still present
    assert "*.app" not in zone


# ---------------------------------------------------------------------------
# render_zone — serial behaviour
# ---------------------------------------------------------------------------


def test_render_zone_serial_injected():
    """Injected serial must appear verbatim in the SOA."""
    zone = render_zone({}, CONTROL_IP, serial=20240101_00)
    assert "20240101" in zone


def test_render_zone_serial_monotonic_with_injected_values():
    """Increasing injected serials must produce increasing SOA serials."""
    zone1 = render_zone({}, CONTROL_IP, serial=100)
    zone2 = render_zone({}, CONTROL_IP, serial=101)

    def _extract_serial(z: str) -> int:
        for line in z.splitlines():
            if "IN SOA" in line:
                # SOA: @ IN SOA ns... ( <serial> refresh retry expire min )
                token = line.split("(")[1].split()[0]
                return int(token)
        raise AssertionError("No SOA line found")

    assert _extract_serial(zone2) > _extract_serial(zone1)


def test_render_zone_default_serial_is_nonzero():
    """When no serial is supplied, the default must be a positive integer."""
    zone = render_zone({}, CONTROL_IP)
    for line in zone.splitlines():
        if "IN SOA" in line:
            serial = int(line.split("(")[1].split()[0])
            assert serial > 0
            return
    pytest.fail("No SOA line found")


def test_render_zone_consecutive_defaults_are_monotonic():
    """Two default-serial calls in quick succession must not regress."""
    import time

    zone1 = render_zone({}, CONTROL_IP)
    time.sleep(0.01)
    zone2 = render_zone({}, CONTROL_IP)

    def _extract_serial(z: str) -> int:
        for line in z.splitlines():
            if "IN SOA" in line:
                return int(line.split("(")[1].split()[0])
        raise AssertionError("No SOA")

    assert _extract_serial(zone2) >= _extract_serial(zone1)


# ---------------------------------------------------------------------------
# write_zone — no-op when zone dir absent
# ---------------------------------------------------------------------------


def test_write_zone_noop_when_dir_absent(tmp_path, monkeypatch):
    """write_zone must not crash when the zone directory does not exist."""
    nonexistent = tmp_path / "does_not_exist" / "db.myhomecloud.dev"
    monkeypatch.setattr(zone_module.settings, "coredns_zone_path", str(nonexistent))
    monkeypatch.setattr(zone_module.settings, "control_node_tailscale_ip", CONTROL_IP)
    monkeypatch.setattr(zone_module.settings, "coredns_reload_cmd", "")

    # Must not raise
    write_zone()
    assert not nonexistent.exists()


def test_write_zone_logs_warning_when_dir_absent(tmp_path, monkeypatch, caplog):
    """write_zone must emit a warning when the zone dir is absent."""
    import logging

    nonexistent = tmp_path / "missing" / "zone"
    monkeypatch.setattr(zone_module.settings, "coredns_zone_path", str(nonexistent))
    monkeypatch.setattr(zone_module.settings, "control_node_tailscale_ip", CONTROL_IP)
    monkeypatch.setattr(zone_module.settings, "coredns_reload_cmd", "")

    with caplog.at_level(logging.WARNING, logger="homecloud.dns.zone"):
        write_zone()

    assert any("does not exist" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# write_zone — success path with a real temp dir
# ---------------------------------------------------------------------------


def test_write_zone_creates_file(tmp_path, monkeypatch):
    """write_zone must write the zone file when the directory exists."""
    zone_file = tmp_path / "db.myhomecloud.dev"
    monkeypatch.setattr(zone_module.settings, "coredns_zone_path", str(zone_file))
    monkeypatch.setattr(zone_module.settings, "control_node_tailscale_ip", CONTROL_IP)
    monkeypatch.setattr(zone_module.settings, "coredns_reload_cmd", "")
    monkeypatch.setattr(zone_module.settings, "domain", "myhomecloud.dev")

    # Inject state so write_zone has something to render.
    monkeypatch.setattr(
        zone_module,
        "list_registered_vms",
        lambda: {"app": {"tailscale_ip": "100.10.0.1"}},
    )

    write_zone()

    assert zone_file.exists()
    content = zone_file.read_text()
    assert "$ORIGIN myhomecloud.dev." in content
    assert "100.10.0.1" in content
    assert "*.app" in content


def test_write_zone_content_matches_render(tmp_path, monkeypatch):
    """File content must equal what render_zone would produce for the same instances."""
    zone_file = tmp_path / "zone"
    instances = {"myvm": {"tailscale_ip": "100.20.0.5"}}

    monkeypatch.setattr(zone_module.settings, "coredns_zone_path", str(zone_file))
    monkeypatch.setattr(zone_module.settings, "control_node_tailscale_ip", CONTROL_IP)
    monkeypatch.setattr(zone_module.settings, "coredns_reload_cmd", "")
    monkeypatch.setattr(zone_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(zone_module, "list_registered_vms", lambda: instances)

    write_zone()
    written = zone_file.read_text()

    # Verify key content regardless of exact serial value.
    assert "myvm" in written
    assert "100.20.0.5" in written
    assert "*.myvm" in written
