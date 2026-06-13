"""Tests for homecloud.config — controller settings and back-compat."""

from __future__ import annotations

import importlib
import os

import pytest


def _load_settings(**env_overrides):
    """Load a fresh Settings instance with the given env vars set."""
    import homecloud.config as cfg_mod

    old = {k: os.environ.get(k) for k in env_overrides}
    try:
        for k, v in env_overrides.items():
            os.environ[k] = v
        # Re-instantiate Settings (don't read .env so we control the env)
        from pydantic_settings import BaseSettings, SettingsConfigDict

        class _TestSettings(cfg_mod.Settings):
            model_config = SettingsConfigDict(
                env_file=None, env_file_encoding="utf-8", extra="ignore"
            )

        return _TestSettings()
    finally:
        for k, old_v in old.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


def test_default_controller_port():
    """Default controller_port is 8080."""
    s = _load_settings()
    assert s.controller_port == 8080


def test_controller_port_via_new_env():
    """CONTROLLER_PORT sets controller_port."""
    s = _load_settings(CONTROLLER_PORT="9090")
    assert s.controller_port == 9090


def test_controller_port_via_legacy_agent_port():
    """AGENT_PORT (legacy) is still honored for back-compat."""
    s = _load_settings(AGENT_PORT="7777")
    assert s.controller_port == 7777


def test_controller_host_via_legacy_agent_host():
    """AGENT_HOST (legacy) is still honored for back-compat."""
    s = _load_settings(AGENT_HOST="127.0.0.1")
    assert s.controller_host == "127.0.0.1"


def test_optional_settings_have_safe_defaults():
    """Phase 03-06 settings default to empty/safe values so dev runs work."""
    s = _load_settings()
    assert s.domain == "myhomecloud.dev"
    assert s.cloudflare_api_token == ""
    assert s.cloudflare_zone_id == ""
    assert s.cloudflare_tunnel_id == ""
    assert s.cloudflare_tunnel_cname == ""
    assert s.caddy_config_dir == "/etc/caddy/sites"
    assert s.caddy_reload_cmd == ""
    assert s.coredns_zone_path == "/etc/coredns/db.myhomecloud.dev"
    assert s.coredns_reload_cmd == ""
    assert s.control_node_tailscale_ip == ""
    assert s.default_web_port == 80
