"""Unit tests for CloudflareDNS — normalization and disabled-mode no-op.

These tests make NO network calls. Live Cloudflare behaviour is verified
manually with credentials set (see plan/03-public-dns-cloudflare.md § Testing).
"""

from __future__ import annotations

import pytest

from homecloud.cloudflare.dns import CloudflareDNS, publish_dns, unpublish_dns


# ---------------------------------------------------------------------------
# Helpers — stub subclasses so tests are independent of real .env values
# ---------------------------------------------------------------------------


class _DisabledDNS(CloudflareDNS):
    """CloudflareDNS with all credentials cleared → enabled=False."""

    def __init__(self) -> None:
        super().__init__()
        self.token = ""
        self.zone_id = ""
        self.tunnel_cname = ""
        self.domain = "myhomecloud.dev"


class _EnabledDNS(CloudflareDNS):
    """CloudflareDNS with stub credentials → enabled=True (no real network)."""

    def __init__(self) -> None:
        super().__init__()
        self.token = "fake-token"
        self.zone_id = "fake-zone-id"
        self.tunnel_cname = "fake-uuid.cfargotunnel.com"
        self.domain = "myhomecloud.dev"


# ---------------------------------------------------------------------------
# enabled property
# ---------------------------------------------------------------------------


def test_enabled_false_when_no_creds():
    dns = _DisabledDNS()
    assert dns.enabled is False


def test_enabled_true_when_all_creds_set():
    dns = _EnabledDNS()
    assert dns.enabled is True


def test_enabled_false_when_zone_id_missing():
    dns = _EnabledDNS()
    dns.zone_id = ""
    assert dns.enabled is False


def test_enabled_false_when_token_missing():
    dns = _EnabledDNS()
    dns.token = ""
    assert dns.enabled is False


def test_enabled_false_when_tunnel_cname_missing():
    dns = _EnabledDNS()
    dns.tunnel_cname = ""
    assert dns.enabled is False


# ---------------------------------------------------------------------------
# _normalize — label / FQDN normalization (pure, no network)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host_label, expected_label, expected_fqdn",
    [
        # bare single-label
        ("app", "app", "app.myhomecloud.dev"),
        # multi-label (dots in the label)
        ("grafana.app", "grafana.app", "grafana.app.myhomecloud.dev"),
        # full FQDN single-label
        ("app.myhomecloud.dev", "app", "app.myhomecloud.dev"),
        # full FQDN multi-label
        ("grafana.app.myhomecloud.dev", "grafana.app", "grafana.app.myhomecloud.dev"),
        # deeper label
        ("api.grafana.app", "api.grafana.app", "api.grafana.app.myhomecloud.dev"),
    ],
)
def test_normalize(host_label: str, expected_label: str, expected_fqdn: str) -> None:
    dns = _DisabledDNS()
    label, fqdn = dns._normalize(host_label)
    assert label == expected_label
    assert fqdn == expected_fqdn


# ---------------------------------------------------------------------------
# disabled-mode no-op — ensure NO network calls are made
# ---------------------------------------------------------------------------


def _make_fail_client():
    """Return a callable that raises if called, simulating _client() being invoked."""
    def _fail():
        raise AssertionError("_client() was called despite enabled=False")

    return _fail


def test_ensure_record_disabled_returns_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_record must NOT call _client and must return {"skipped": True, ...}."""
    dns = _DisabledDNS()
    assert not dns.enabled
    monkeypatch.setattr(dns, "_client", _make_fail_client())

    result = dns.ensure_record("app")

    assert result == {"skipped": True, "hostname": "app.myhomecloud.dev"}


def test_ensure_record_disabled_multi_label(monkeypatch: pytest.MonkeyPatch) -> None:
    dns = _DisabledDNS()
    monkeypatch.setattr(dns, "_client", _make_fail_client())

    result = dns.ensure_record("grafana.app")

    assert result["skipped"] is True
    assert result["hostname"] == "grafana.app.myhomecloud.dev"


def test_ensure_record_disabled_fqdn_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full-FQDN input to ensure_record also no-ops and returns the correct hostname."""
    dns = _DisabledDNS()
    monkeypatch.setattr(dns, "_client", _make_fail_client())

    result = dns.ensure_record("app.myhomecloud.dev")

    assert result["skipped"] is True
    assert result["hostname"] == "app.myhomecloud.dev"


def test_delete_record_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """delete_record must NOT call _client and must not raise when disabled."""
    dns = _DisabledDNS()
    monkeypatch.setattr(dns, "_client", _make_fail_client())

    dns.delete_record("app")  # should complete without error or network call


def test_delete_record_disabled_multi_label(monkeypatch: pytest.MonkeyPatch) -> None:
    dns = _DisabledDNS()
    monkeypatch.setattr(dns, "_client", _make_fail_client())

    dns.delete_record("grafana.app")  # no-op, no error


# ---------------------------------------------------------------------------
# Module-level helpers — smoke test delegation (disabled, so no network)
# ---------------------------------------------------------------------------


def test_publish_dns_disabled_returns_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """publish_dns delegates to CloudflareDNS.ensure_record."""
    # Monkeypatch CloudflareDNS so it behaves as disabled
    monkeypatch.setattr(
        "homecloud.cloudflare.dns.CloudflareDNS",
        lambda: _DisabledDNS(),
    )
    result = publish_dns("app")
    assert result["skipped"] is True


def test_unpublish_dns_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """unpublish_dns delegates to CloudflareDNS.delete_record and must not raise."""
    monkeypatch.setattr(
        "homecloud.cloudflare.dns.CloudflareDNS",
        lambda: _DisabledDNS(),
    )
    unpublish_dns("app")  # no error expected
