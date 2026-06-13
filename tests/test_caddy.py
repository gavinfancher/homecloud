"""Unit tests for CaddyProxy — site-file contents, path, and reload no-op.

No network calls are made.  All tests use a temporary directory for
caddy_config_dir and patch settings so they are independent of .env values.
"""
from __future__ import annotations

import pytest

from homecloud.proxy.caddy import CaddyProxy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Caddy(CaddyProxy):
    """CaddyProxy with injected config_dir and domain (no settings dependency)."""

    def __init__(self, config_dir, *, domain="myhomecloud.dev", reload_cmd=""):
        # Skip the default __init__ so we don't touch settings.
        self.config_dir = config_dir
        self.domain = domain
        self._reload_cmd = reload_cmd

    def _reload(self) -> None:
        if self._reload_cmd:
            raise AssertionError("_reload unexpectedly invoked with a non-empty cmd")


# ---------------------------------------------------------------------------
# fqdn helper
# ---------------------------------------------------------------------------


def test_fqdn_bare_label(tmp_path):
    caddy = _Caddy(tmp_path)
    assert caddy.fqdn("app") == "app.myhomecloud.dev"


def test_fqdn_multi_label(tmp_path):
    caddy = _Caddy(tmp_path)
    assert caddy.fqdn("grafana.app") == "grafana.app.myhomecloud.dev"


def test_fqdn_already_fqdn(tmp_path):
    caddy = _Caddy(tmp_path)
    assert caddy.fqdn("grafana.app.myhomecloud.dev") == "grafana.app.myhomecloud.dev"


# ---------------------------------------------------------------------------
# ensure_route — site file path and contents
# ---------------------------------------------------------------------------


def test_ensure_route_writes_file(tmp_path):
    caddy = _Caddy(tmp_path)
    result = caddy.ensure_route("grafana.app", upstream_host="100.1.2.3", upstream_port=3000)

    expected_path = tmp_path / "grafana.app.caddy"
    assert expected_path.exists(), "site file must be written to config_dir/<label>.caddy"
    assert result["config"] == str(expected_path)


def test_ensure_route_file_contents(tmp_path):
    caddy = _Caddy(tmp_path)
    caddy.ensure_route("grafana.app", upstream_host="100.1.2.3", upstream_port=3000)

    contents = (tmp_path / "grafana.app.caddy").read_text()
    assert "http://grafana.app.myhomecloud.dev" in contents, "must use http:// prefix (no auto-HTTPS)"
    assert "reverse_proxy 100.1.2.3:3000" in contents


def test_ensure_route_no_auto_https(tmp_path):
    """Site file must NOT contain plain host binding that would trigger auto-HTTPS."""
    caddy = _Caddy(tmp_path)
    caddy.ensure_route("myapp.vm", upstream_host="100.9.9.9", upstream_port=8080)

    contents = (tmp_path / "myapp.vm.caddy").read_text()
    # The very first token in the site block must be `http://...`
    first_line = contents.splitlines()[0]
    assert first_line.startswith("http://"), f"Expected http:// prefix, got: {first_line!r}"


def test_ensure_route_fqdn_input(tmp_path):
    """Passing a full FQDN to ensure_route must produce the same file as a bare label."""
    caddy = _Caddy(tmp_path)
    caddy.ensure_route(
        "grafana.app.myhomecloud.dev",
        upstream_host="100.1.2.3",
        upstream_port=3000,
    )
    assert (tmp_path / "grafana.app.caddy").exists()


def test_ensure_route_single_label(tmp_path):
    """Single-label hostname (instance base route) → <label>.caddy."""
    caddy = _Caddy(tmp_path)
    result = caddy.ensure_route("app", upstream_host="100.5.5.5", upstream_port=80)

    expected_path = tmp_path / "app.caddy"
    assert expected_path.exists()
    assert result["hostname"] == "app.myhomecloud.dev"


def test_ensure_route_returns_dict(tmp_path):
    caddy = _Caddy(tmp_path)
    result = caddy.ensure_route("svc.vm", upstream_host="100.2.2.2", upstream_port=8000)

    assert result["hostname"] == "svc.vm.myhomecloud.dev"
    assert result["upstream"] == "100.2.2.2:8000"
    assert "config" in result


# ---------------------------------------------------------------------------
# remove_route
# ---------------------------------------------------------------------------


def test_remove_route_deletes_file(tmp_path):
    caddy = _Caddy(tmp_path)
    caddy.ensure_route("app", upstream_host="100.1.1.1", upstream_port=80)
    assert (tmp_path / "app.caddy").exists()

    caddy.remove_route("app")
    assert not (tmp_path / "app.caddy").exists()


def test_remove_route_noop_if_missing(tmp_path):
    """remove_route must not raise if the file does not exist."""
    caddy = _Caddy(tmp_path)
    caddy.remove_route("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# Reload — disabled (empty caddy_reload_cmd)
# ---------------------------------------------------------------------------


def test_reload_noop_when_cmd_empty(tmp_path, monkeypatch):
    """When caddy_reload_cmd is empty, _reload must not call httpx or subprocess."""
    import homecloud.proxy.caddy as caddy_module

    monkeypatch.setattr(caddy_module.settings, "caddy_reload_cmd", "")
    monkeypatch.setattr(caddy_module.settings, "caddy_config_dir", str(tmp_path))
    monkeypatch.setattr(caddy_module.settings, "domain", "myhomecloud.dev")

    # Patch httpx.post to fail loudly if called.
    def _fail_post(*args, **kwargs):
        raise AssertionError("httpx.post was called despite caddy_reload_cmd being empty")

    monkeypatch.setattr(caddy_module.httpx, "post", _fail_post)

    proxy = caddy_module.CaddyProxy()
    # Should not raise and should not call httpx.post.
    proxy._reload()


def test_ensure_route_no_network_when_reload_cmd_empty(tmp_path, monkeypatch):
    """ensure_route must complete without network when caddy_reload_cmd is empty."""
    import homecloud.proxy.caddy as caddy_module

    monkeypatch.setattr(caddy_module.settings, "caddy_reload_cmd", "")
    monkeypatch.setattr(caddy_module.settings, "caddy_config_dir", str(tmp_path))
    monkeypatch.setattr(caddy_module.settings, "domain", "myhomecloud.dev")

    def _fail_post(*args, **kwargs):
        raise AssertionError("httpx.post should not be called")

    monkeypatch.setattr(caddy_module.httpx, "post", _fail_post)

    proxy = caddy_module.CaddyProxy()
    result = proxy.ensure_route("app", upstream_host="10.0.0.1", upstream_port=80)
    assert result["hostname"] == "app.myhomecloud.dev"
    assert (tmp_path / "app.caddy").exists()
