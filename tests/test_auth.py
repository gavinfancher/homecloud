"""Tests for Clerk auth (phase 09) and the Caddy forward-auth gate (phase 11).

No network: a local RSA keypair signs tokens and ``ClerkAuth.get_signing_key``
is monkeypatched to return the matching public key (standing in for the JWKS
endpoint).
"""
from __future__ import annotations

import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import homecloud.auth as auth_module
from homecloud.auth import ClerkAuth, get_clerk_auth, reset_clerk_auth
from homecloud.main import app

ISSUER = "https://test.clerk.accounts.dev"


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_clerk_auth()
    yield
    reset_clerk_auth()


@pytest.fixture
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def _token(priv, *, issuer=ISSUER, azp=None, exp_delta=3600):
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": "user_123",
        "iss": issuer,
        "iat": now,
        "exp": now + datetime.timedelta(seconds=exp_delta),
    }
    if azp is not None:
        payload["azp"] = azp
    return jwt.encode(payload, priv, algorithm="RS256")


def _enable_clerk(monkeypatch, keypair, *, authorized_parties=""):
    _, pub = keypair
    monkeypatch.setattr(auth_module.settings, "clerk_jwks_url", "https://test/jwks.json")
    monkeypatch.setattr(auth_module.settings, "clerk_issuer", ISSUER)
    monkeypatch.setattr(auth_module.settings, "clerk_authorized_parties", authorized_parties)
    reset_clerk_auth()
    monkeypatch.setattr(ClerkAuth, "get_signing_key", lambda self, token: pub)


# ---------------------------------------------------------------------------
# ClerkAuth.verify_token
# ---------------------------------------------------------------------------


def test_enabled_flag():
    auth = ClerkAuth()
    assert auth.enabled is False  # nothing configured by default


def test_verify_token_success(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    priv, _ = keypair
    claims = get_clerk_auth().verify_token(_token(priv))
    assert claims["sub"] == "user_123"


def test_verify_token_bad_issuer_rejected(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    priv, _ = keypair
    with pytest.raises(jwt.InvalidIssuerError):
        get_clerk_auth().verify_token(_token(priv, issuer="https://evil.example"))


def test_verify_token_expired_rejected(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    priv, _ = keypair
    with pytest.raises(jwt.ExpiredSignatureError):
        get_clerk_auth().verify_token(_token(priv, exp_delta=-10))


def test_verify_token_unauthorized_azp_rejected(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair, authorized_parties="https://app.myhomecloud.dev")
    priv, _ = keypair
    with pytest.raises(jwt.InvalidTokenError):
        get_clerk_auth().verify_token(_token(priv, azp="https://attacker.example"))


def test_verify_token_authorized_azp_accepted(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair, authorized_parties="https://app.myhomecloud.dev")
    priv, _ = keypair
    claims = get_clerk_auth().verify_token(_token(priv, azp="https://app.myhomecloud.dev"))
    assert claims["sub"] == "user_123"


# ---------------------------------------------------------------------------
# API enforcement (disabled vs enabled)
# ---------------------------------------------------------------------------


def test_health_is_public():
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


def test_api_open_when_auth_disabled():
    # No Clerk config → dev mode → request allowed without a token.
    client = TestClient(app)
    assert client.get("/api/sizes").status_code == 200


def test_api_rejects_missing_token_when_enabled(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    client = TestClient(app)
    assert client.get("/api/sizes").status_code == 401


def test_api_accepts_valid_token_when_enabled(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    priv, _ = keypair
    client = TestClient(app)
    resp = client.get("/api/sizes", headers={"Authorization": f"Bearer {_token(priv)}"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /auth/verify (Caddy forward-auth target)
# ---------------------------------------------------------------------------


def test_auth_verify_allows_when_disabled():
    client = TestClient(app)
    resp = client.get("/auth/verify")
    assert resp.status_code == 200
    assert resp.json()["status"] == "auth-disabled"


def test_auth_verify_accepts_session_cookie(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    priv, _ = keypair
    client = TestClient(app)
    resp = client.get("/auth/verify", cookies={"__session": _token(priv)})
    assert resp.status_code == 200
    assert resp.headers.get("X-Auth-Sub") == "user_123"


def test_auth_verify_401_without_token_or_console(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    monkeypatch.setattr(auth_module.settings, "console_url", "")
    client = TestClient(app)
    assert client.get("/auth/verify").status_code == 401


def test_auth_verify_redirects_to_console(monkeypatch, keypair):
    _enable_clerk(monkeypatch, keypair)
    import homecloud.api.routes as routes_module

    monkeypatch.setattr(routes_module.settings, "console_url", "https://app.myhomecloud.dev")
    client = TestClient(app)
    resp = client.get("/auth/verify", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://app.myhomecloud.dev")


# ---------------------------------------------------------------------------
# Caddy forward-auth block rendering (phase 11)
# ---------------------------------------------------------------------------


def test_caddy_site_includes_forward_auth_when_configured(tmp_path, monkeypatch):
    import homecloud.proxy.caddy as caddy_module

    monkeypatch.setattr(caddy_module.settings, "caddy_config_dir", str(tmp_path))
    monkeypatch.setattr(caddy_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(caddy_module.settings, "caddy_reload_cmd", "")
    monkeypatch.setattr(caddy_module.settings, "caddy_forward_auth_upstream", "controller:8080")

    caddy_module.CaddyProxy().ensure_route(
        "airflow.dagster", upstream_host="100.1.1.1", upstream_port=8080
    )
    content = (tmp_path / "airflow.dagster.caddy").read_text()
    assert "forward_auth controller:8080" in content
    assert "uri /auth/verify" in content
    assert "reverse_proxy 100.1.1.1:8080" in content


def test_caddy_site_no_forward_auth_when_unset(tmp_path, monkeypatch):
    import homecloud.proxy.caddy as caddy_module

    monkeypatch.setattr(caddy_module.settings, "caddy_config_dir", str(tmp_path))
    monkeypatch.setattr(caddy_module.settings, "domain", "myhomecloud.dev")
    monkeypatch.setattr(caddy_module.settings, "caddy_reload_cmd", "")
    monkeypatch.setattr(caddy_module.settings, "caddy_forward_auth_upstream", "")

    caddy_module.CaddyProxy().ensure_route(
        "airflow.dagster", upstream_host="100.1.1.1", upstream_port=8080
    )
    content = (tmp_path / "airflow.dagster.caddy").read_text()
    assert "forward_auth" not in content
