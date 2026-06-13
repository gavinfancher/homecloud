"""Clerk authentication for the controller API and the Caddy forward-auth gate.

Phase 09: verify Clerk-issued JWTs (RS256, JWKS) for every ``/api/*`` call.
Phase 11: a ``/auth/verify`` endpoint that Caddy calls (``forward_auth``) to
gate published instance web apps behind the same Clerk identity.

Graceful degradation (repo convention): when ``CLERK_JWKS_URL`` /
``CLERK_ISSUER`` are unset the system is in **disabled / dev mode** — auth is a
no-op that allows requests and logs a loud warning. With both set it is
**fail-closed**: missing or invalid tokens are rejected. Production deployments
must set them.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from homecloud.config import settings

logger = logging.getLogger(__name__)

# Clerk sets its session JWT in this cookie on the app's domain.
SESSION_COOKIE = "__session"


class ClerkAuth:
    """Verify Clerk RS256 session tokens against the tenant's JWKS."""

    def __init__(self) -> None:
        self.jwks_url = settings.clerk_jwks_url.strip()
        self.issuer = settings.clerk_issuer.strip()
        self.authorized_parties = [
            p.strip() for p in settings.clerk_authorized_parties.split(",") if p.strip()
        ]
        self._jwk_client: PyJWKClient | None = (
            PyJWKClient(self.jwks_url) if self.jwks_url else None
        )

    @property
    def enabled(self) -> bool:
        """True only when both JWKS URL and issuer are configured."""
        return bool(self.jwks_url and self.issuer)

    def get_signing_key(self, token: str):
        """Resolve the RSA signing key for *token* from the JWKS endpoint.

        Isolated so tests can monkeypatch it with a local public key.
        """
        if self._jwk_client is None:
            raise RuntimeError("Clerk JWKS not configured")
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def verify_token(self, token: str) -> dict:
        """Return verified claims for *token* or raise ``jwt`` errors."""
        key = self.get_signing_key(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=self.issuer,
            # Clerk session tokens carry no `aud`; authorize via `azp` instead.
            options={"verify_aud": False},
        )
        if self.authorized_parties:
            azp = claims.get("azp")
            if azp and azp not in self.authorized_parties:
                raise jwt.InvalidTokenError(
                    f"azp '{azp}' is not an authorized party"
                )
        return claims


@lru_cache(maxsize=1)
def get_clerk_auth() -> ClerkAuth:
    """Cached ClerkAuth so the JWKS client reuses its key cache across requests."""
    return ClerkAuth()


def reset_clerk_auth() -> None:
    """Drop the cached ClerkAuth (tests call this after changing settings)."""
    get_clerk_auth.cache_clear()


def extract_token(request: Request) -> str | None:
    """Pull a bearer token (API) or the Clerk ``__session`` cookie (browser)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    cookie = request.cookies.get(SESSION_COOKIE)
    return cookie.strip() if cookie else None


def require_auth(request: Request) -> dict:
    """FastAPI dependency: verify the caller's Clerk token.

    Disabled mode returns an anonymous principal (dev). Enabled mode raises
    HTTP 401 on a missing or invalid token.
    """
    auth = get_clerk_auth()
    if not auth.enabled:
        logger.warning(
            "Clerk auth DISABLED — allowing unauthenticated request to %s "
            "(set CLERK_JWKS_URL + CLERK_ISSUER to enforce)",
            request.url.path,
        )
        return {"sub": "anonymous", "auth": "disabled"}

    token = extract_token(request)
    if not token:
        raise HTTPException(401, "Missing authentication token")
    try:
        return auth.verify_token(token)
    except Exception as exc:  # noqa: BLE001 — any verify failure is a 401
        raise HTTPException(401, f"Invalid token: {exc}") from exc
