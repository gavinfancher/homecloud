from __future__ import annotations

import logging

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from homecloud.api.routes import auth_router, public_router, router
from homecloud.auth import require_auth
from homecloud.config import settings
from homecloud.db import db_enabled, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Homecloud Controller",
    description="Control plane for Proxmox-based instances — Tailscale MagicDNS",
    version="0.2.0",
)

# CORS for the Cloudflare Pages SPA (comma-separated origins). No-op when unset.
_origins = [o.strip() for o in settings.frontend_origin.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Public (unauthenticated): health + SPA bootstrap config + forward-auth gate.
app.include_router(public_router)
app.include_router(auth_router)
# Everything under /api requires a valid Clerk token (no-op in dev — see auth.py).
app.include_router(router, dependencies=[Depends(require_auth)])

@app.get("/")
def index() -> dict:
    """The controller is API-only; the console is the Cloudflare Pages SPA."""
    return {
        "service": "homecloud-controller",
        "console": settings.console_url or None,
        "docs": "/docs",
    }


@app.on_event("startup")
def startup() -> None:
    if db_enabled():
        # A database hiccup must not stop the controller from serving instances;
        # only the source views are unavailable until it recovers.
        try:
            init_db()
        except Exception:
            logging.getLogger(__name__).exception("Image database unavailable at startup")
    else:
        logging.getLogger(__name__).warning(
            "DATABASE_URL is unset — sources are unavailable, so instances cannot be deployed"
        )


def cli() -> None:
    uvicorn.run(
        "homecloud.main:app",
        host=settings.controller_host,
        port=settings.controller_port,
        reload=False,
    )


if __name__ == "__main__":
    cli()
