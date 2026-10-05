"""Clerk auth without a network: disabled mode, token extraction, and RS256
verification against a locally generated key (``get_signing_key`` is patched)."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.requests import Request

from homecloud import auth

ISSUER = "https://clerk.example.test"


def _request(headers: dict[str, str] | None = None, path: str = "/api/instances") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": path, "headers": raw})


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def clerk(settings, monkeypatch, key):
    """Enabled Clerk auth whose signing key is the local test key."""
    monkeypatch.setattr(settings, "clerk_jwks_url", f"{ISSUER}/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", ISSUER)
    monkeypatch.setattr(settings, "clerk_authorized_parties", "https://app.example.test, ")
    auth.reset_clerk_auth()
    instance = auth.get_clerk_auth()
    monkeypatch.setattr(instance, "get_signing_key", lambda _token: key.public_key())
    yield instance
    auth.reset_clerk_auth()


@pytest.fixture
def disabled(settings, monkeypatch):
    monkeypatch.setattr(settings, "clerk_jwks_url", "")
    monkeypatch.setattr(settings, "clerk_issuer", "")
    auth.reset_clerk_auth()
    yield auth.get_clerk_auth()
    auth.reset_clerk_auth()


def _token(key, **claims) -> str:
    now = int(time.time())
    payload = {"sub": "user_1", "iss": ISSUER, "iat": now, "exp": now + 60, **claims}
    return jwt.encode(payload, key, algorithm="RS256")


def test_disabled_mode_allows_anonymous(disabled):
    assert disabled.enabled is False
    assert auth.require_auth(_request()) == {"sub": "anonymous", "auth": "disabled"}


def test_enabled_needs_both_jwks_and_issuer(settings, monkeypatch):
    monkeypatch.setattr(settings, "clerk_jwks_url", f"{ISSUER}/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_issuer", "")
    auth.reset_clerk_auth()
    try:
        assert auth.get_clerk_auth().enabled is False
    finally:
        auth.reset_clerk_auth()


def test_authorized_parties_are_parsed(clerk):
    assert clerk.authorized_parties == ["https://app.example.test"]


@pytest.mark.parametrize(
    ("headers", "token"),
    [
        ({"Authorization": "Bearer abc"}, "abc"),
        ({"Authorization": "bearer  abc "}, "abc"),
        ({"Authorization": "Bearer "}, None),
        ({"Cookie": "__session=xyz"}, "xyz"),
        ({"Authorization": "Basic Zm9v", "Cookie": "__session=xyz"}, "xyz"),
        ({"Authorization": "Bearer abc", "Cookie": "__session=xyz"}, "abc"),
        ({}, None),
    ],
)
def test_extract_token(headers, token):
    assert auth.extract_token(_request(headers)) == token


def test_valid_token(clerk, key):
    token = _token(key, azp="https://app.example.test")
    claims = auth.require_auth(_request({"Authorization": f"Bearer {token}"}))
    assert claims["sub"] == "user_1"


def test_token_without_azp_is_accepted(clerk, key):
    assert clerk.verify_token(_token(key))["sub"] == "user_1"


def test_missing_token_is_401(clerk):
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(_request())
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"azp": "https://evil.example.test"},
        {"iss": "https://other.example.test"},
        {"exp": int(time.time()) - 600},
    ],
)
def test_rejected_claims_are_401(clerk, key, claims):
    token = _token(key, **claims)
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(_request({"Authorization": f"Bearer {token}"}))
    assert exc.value.status_code == 401


def test_token_signed_by_another_key_is_401(clerk):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(other)
    with pytest.raises(HTTPException) as exc:
        auth.require_auth(_request({"Cookie": f"__session={token}"}))
    assert exc.value.status_code == 401
