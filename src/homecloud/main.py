from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from homecloud.api.routes import auth_router, public_router, router, ui_index
from homecloud.auth import require_auth
from homecloud.config import settings
from homecloud.state import hydrate_registry

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

static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return ui_index()


@app.on_event("startup")
def startup() -> None:
    hydrate_registry()


def cli() -> None:
    uvicorn.run(
        "homecloud.main:app",
        host=settings.controller_host,
        port=settings.controller_port,
        reload=False,
    )


if __name__ == "__main__":
    cli()
