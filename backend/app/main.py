"""homecloud: spin up an Ubuntu 26.04 or Windows 11 VM on Proxmox from a web page.

The pages are static files on Cloudflare (frontend/, homecloud.gavinf.com). They call this API
at homecloud-api.gavinf.com, a Cloudflare Tunnel to the cluster. Every /api call except signing
in needs a session token (auth.py). Creating and deleting VMs is done by the worker
(provision.py), in the background; the API only records what was asked for.
"""

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import auth, config, db, provision, pve

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

if config.FAKE_PROXMOX:
    from app import fake_pve as pve  # noqa: F811

    provision.pve = pve

if not config.LOCAL and not config.ADMIN_PASSWORD_HASH:
    raise RuntimeError("Set HOMECLOUD_ADMIN_PASSWORD_HASH (make one with: uv run python -m app.auth)")

# Lowercase letters, digits and hyphens, starting with a letter. 15 characters at most, the
# limit on a Windows computer name, so one rule works for both.
NAME = re.compile(r"[a-z]([a-z0-9-]{0,13}[a-z0-9])?")
OSES = {
    "ubuntu": {"label": "Ubuntu 26.04", "min_disk_gb": 10, "min_memory_gb": 1},
    "windows": {"label": "Windows 11", "min_disk_gb": 64, "min_memory_gb": 4},
}
LIMITS = {"cores": 16, "memory_gb": 64, "disk_gb": 1000}
PRESETS = [
    {"label": "Small", "cores": 1, "memory_gb": 2, "disk_gb": 20},
    {"label": "Medium", "cores": 2, "memory_gb": 4, "disk_gb": 40},
    {"label": "Large", "cores": 4, "memory_gb": 8, "disk_gb": 80},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    stop = provision.start_thread()
    yield
    stop.set()


app = FastAPI(title="homecloud", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


OPEN_API = {"/api/login", "/api/session"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if (not config.LOCAL and path.startswith("/api/") and path not in OPEN_API
            and request.method != "OPTIONS"):
        if not await run_in_threadpool(auth.valid_session, bearer(request)):
            return JSONResponse({"detail": "Sign in first"}, status_code=401)
    response = await call_next(request)
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Added last, so it runs first: answers preflights and labels every response, 401s included.
if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                       allow_methods=["GET", "POST", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"], max_age=3600)


# ---------- health ----------

@app.get("/healthz")
def healthz():
    """Is the process up. Never touches the database, so a database blip doesn't restart it."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    try:
        db.ping()
    except Exception:
        raise HTTPException(503, "database unreachable") from None
    return {"status": "ready"}


# ---------- sign-in ----------

class LoginBody(BaseModel):
    password: str


def client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


@app.post("/api/login")
def login(request: Request, body: LoginBody):
    ip = client_ip(request)
    if auth.throttled(ip):
        raise HTTPException(429, "Too many wrong passwords. Try again in 15 minutes.")
    if not auth.check_password(body.password):
        auth.record_failure(ip)
        raise HTTPException(401, "Wrong password")
    return {"token": auth.start_session(), "days": auth.SESSION_DAYS}


@app.post("/api/logout")
def logout(request: Request):
    auth.end_session(bearer(request))
    return {"ok": True}


@app.get("/api/session")
def session(request: Request):
    signed_in = config.LOCAL or auth.valid_session(bearer(request))
    return {"signed_in": signed_in}


# ---------- VMs ----------

@app.get("/api/config")
def get_config():
    return {"oses": OSES, "limits": LIMITS, "presets": PRESETS, "proxmox_ui": config.PROXMOX_UI, "proxmox_node": config.PROXMOX_NODE,
            "windows_ready": bool(config.WINDOWS_ADMIN_PASSWORD), "ubuntu_ready": bool(config.SSH_KEYS)}


def _view(vm: dict, live: dict | None) -> dict:
    power = (live or {}).get("status") if vm["vmid"] is not None else None
    return {
        "name": vm["name"], "os": vm["os"], "os_label": OSES[vm["os"]]["label"],
        "cores": vm["cores"], "memory_gb": vm["memory_mb"] // 1024, "disk_gb": vm["disk_gb"],
        "vmid": vm["vmid"], "state": vm["state"], "step": vm["step"], "error": vm["error"],
        "ip": vm["ip"], "power": power, "uptime": (live or {}).get("uptime", 0),
        "created_at": vm["created_at"].isoformat(),
        "last_event": vm.get("last_event"), "last_level": vm.get("last_level"),
    }


@app.get("/api/vms")
def list_vms():
    vms = db.list_vms()
    try:
        live = pve.status_by_vmid()
        reachable = True
    except Exception:
        logging.getLogger("homecloud").warning("Proxmox unreachable", exc_info=True)
        live, reachable = {}, False
    return {"proxmox": reachable, "vms": [_view(v, live.get(v["vmid"])) for v in vms]}


class NewVM(BaseModel):
    name: str
    os: str
    cores: int
    memory_gb: int
    disk_gb: int


@app.post("/api/vms", status_code=201)
def create_vm(body: NewVM):
    name = body.name.strip().lower()
    if not NAME.fullmatch(name):
        raise HTTPException(400, "Names are 1-15 lowercase letters, digits or hyphens, starting with a letter")
    if body.os not in OSES:
        raise HTTPException(400, "OS must be ubuntu or windows")
    spec = OSES[body.os]
    if not 1 <= body.cores <= LIMITS["cores"]:
        raise HTTPException(400, f"Cores must be 1-{LIMITS['cores']}")
    if not spec["min_memory_gb"] <= body.memory_gb <= LIMITS["memory_gb"]:
        raise HTTPException(400, f"Memory must be {spec['min_memory_gb']}-{LIMITS['memory_gb']} GB for {spec['label']}")
    if not spec["min_disk_gb"] <= body.disk_gb <= LIMITS["disk_gb"]:
        raise HTTPException(400, f"Disk must be {spec['min_disk_gb']}-{LIMITS['disk_gb']} GB for {spec['label']}")
    if body.os == "windows" and not config.WINDOWS_ADMIN_PASSWORD:
        raise HTTPException(400, "Set HOMECLOUD_WINDOWS_ADMIN_PASSWORD first")
    if body.os == "ubuntu" and not config.SSH_KEYS:
        raise HTTPException(400, "Set HOMECLOUD_SSH_KEYS first, or you couldn't sign in to it")
    try:
        db.add_vm(name, body.os, body.cores, body.memory_gb * 1024, body.disk_gb)
    except db.Exists:
        raise HTTPException(409, f"There's already a VM called {name}") from None
    db.add_event(name, f"Asked for: {spec['label']}, {body.cores} vCPU, {body.memory_gb} GB memory, "
                       f"{body.disk_gb} GB disk")
    return _view(db.get_vm(name), None)


def _ready_vm(name: str) -> dict:
    vm = db.get_vm(name)
    if not vm:
        raise HTTPException(404, "No such VM")
    if vm["state"] != "ready":
        raise HTTPException(409, f"{name} is {vm['state']}")
    return vm


def _power(name: str, verb: str, fn) -> dict:
    vm = _ready_vm(name)
    try:
        fn(vm["vmid"])
    except Exception as e:
        db.add_event(name, f"{verb} failed: {e}", "error")
        raise HTTPException(502, f"{verb} failed: {e}") from None
    db.add_event(name, f"{verb}: done")
    return {"ok": True}


@app.post("/api/vms/{name}/start")
def start_vm(name: str):
    return _power(name, "Start", pve.start)


@app.post("/api/vms/{name}/shutdown")
def shutdown_vm(name: str):
    return _power(name, "Shut down", pve.shutdown)


@app.delete("/api/vms/{name}", status_code=202)
def delete_vm(name: str):
    """Mark it for deletion; the worker stops it and deletes it and its disks."""
    if not db.get_vm(name):
        raise HTTPException(404, "No such VM")
    db.update_vm(name, state="deleting", error=None)
    db.add_event(name, "Delete asked for")
    return {"ok": True}


@app.get("/api/vms/{name}/events")
def vm_events(name: str, after: int = 0):
    """The VM's log, oldest first. With *after* (the last id you have), only what's new."""
    if not db.get_vm(name):
        raise HTTPException(404, "No such VM")
    return {"events": [{"id": e["id"], "at": e["at"].isoformat(), "level": e["level"], "message": e["message"]}
                       for e in db.events(name, after)]}


# ---------- local dev: serve the pages too ----------

if config.STATIC_DIR:
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return RedirectResponse("/static/index.html")

    @app.get("/login")
    def login_page():
        return RedirectResponse("/static/login.html")
