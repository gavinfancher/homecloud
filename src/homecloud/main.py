from __future__ import annotations

import argparse
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from homecloud.api.routes import auth_router, public_router, router
from homecloud.auth import require_auth
from homecloud.config import settings
from homecloud.db import init_db
from homecloud.jobs import JobRunner
from homecloud.tasks import HANDLERS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    # No database, no controller: fail startup so the container restarts
    # until Postgres is reachable, instead of serving half a console.
    init_db()
    runner = JobRunner(HANDLERS)
    runner.start()
    try:
        yield
    finally:
        runner.stop()


app = FastAPI(
    title="Homecloud Controller",
    description="Control plane for Proxmox-based instances — Tailscale MagicDNS",
    version="0.3.0",
    lifespan=lifespan,
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


def cli() -> None:
    parser = argparse.ArgumentParser(prog="homecloud")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the API and job runner (default)")
    sub.add_parser("migrate", help="Apply pending database migrations and exit")
    legacy = sub.add_parser("import-legacy", help="Import a pre-Postgres state.json")
    legacy.add_argument("state_file", type=Path)
    args = parser.parse_args()

    if args.command == "migrate":
        init_db()
    elif args.command == "import-legacy":
        from homecloud.legacy import import_state

        init_db()
        print(json.dumps(import_state(args.state_file), indent=2))
    else:
        uvicorn.run(
            "homecloud.main:app",
            host=settings.controller_host,
            port=settings.controller_port,
            reload=False,
        )


if __name__ == "__main__":
    cli()
