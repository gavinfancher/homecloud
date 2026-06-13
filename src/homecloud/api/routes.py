from __future__ import annotations

import threading

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from homecloud.access import ssh_config_block
from homecloud.api.schemas import DeployVMRequest, PublishServiceRequest, SetupRequest
from homecloud.auth import extract_token, get_clerk_auth
from homecloud.config import settings
from homecloud.dns.names import connection_info, vm_fqdn
from homecloud.images.builder import ImageBuilder
from homecloud.images.deployer import VMDeployer, VMManager
from homecloud.images.registry import list_images
from homecloud.jobs import JobCancelled, job_store
from homecloud.ports import scan_ports
from homecloud.proxmox.client import ProxmoxClient
from homecloud.publish import publish_web, unpublish_web
from homecloud.sizes import list_sizes
from homecloud.state import (
    get_built_template,
    get_instance,
    get_ssh_public_keys,
    hydrate_registry,
    is_setup_complete,
    list_registered_vms,
    save_setup,
    set_built_template,
    set_instance_ports,
)

router = APIRouter(prefix="/api", tags=["api"])
# Unauthenticated endpoints (health + SPA bootstrap config).
public_router = APIRouter(prefix="/api", tags=["public"])
# Caddy forward-auth gate for published instance apps (no prefix).
auth_router = APIRouter(tags=["auth"])


def _merge_registered(vms: list[dict]) -> list[dict]:
    registered = list_registered_vms()
    for vm in vms:
        name = vm.get("name", "")
        if name in registered:
            vm.update(registered[name])
        # Always expose current MagicDNS hostname (migrates away from legacy .home records)
        if name:
            fqdn = vm_fqdn(name)
            vm["hostname"] = fqdn
            vm["magic_dns"] = fqdn
            if vm.get("tailscale_ip") or vm.get("ip"):
                ip = vm.get("tailscale_ip") or vm.get("ip")
                vm.update(connection_info(name, ip))
        if vm.get("memory_gb") is None and vm.get("memory_mb"):
            vm["memory_gb"] = round(vm["memory_mb"] / 1024, 2)
    return vms


@public_router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@public_router.get("/config")
def public_config() -> dict:
    """Bootstrap config the SPA needs before the user authenticates."""
    return {
        "clerk_publishable_key": settings.clerk_publishable_key,
        "domain": settings.domain,
        "owner_username": settings.owner_username,
        "auth_enabled": get_clerk_auth().enabled,
    }


@auth_router.get("/auth/verify")
def auth_verify(request: Request):
    """Forward-auth target for Caddy: 2xx allows, 302 redirects to login.

    Gates published instance apps behind the same Clerk session. In disabled
    (dev) mode it allows everything.
    """
    auth = get_clerk_auth()
    if not auth.enabled:
        return {"status": "auth-disabled"}
    token = extract_token(request)
    if token:
        try:
            claims = auth.verify_token(token)
            return JSONResponse(
                {"sub": claims.get("sub")},
                headers={"X-Auth-Sub": claims.get("sub", "") or ""},
            )
        except Exception:  # noqa: BLE001 — fall through to the login redirect
            pass
    # Browser hitting a protected app with no/invalid session → send to console login.
    if settings.console_url:
        target = request.headers.get("X-Forwarded-Uri", "")
        sep = "&" if "?" in settings.console_url else "?"
        return RedirectResponse(f"{settings.console_url}{sep}redirect={target}", status_code=302)
    raise HTTPException(401, "Unauthenticated")


@router.get("/dashboard")
def dashboard() -> dict:
    hydrate_registry()
    proxmox = ProxmoxClient()
    vms = _merge_registered(proxmox.list_vms())
    templates = proxmox.list_templates()
    running = sum(1 for vm in vms if vm.get("status") == "running")
    return {
        "setup_complete": is_setup_complete(),
        "base_image_built": get_built_template("homecloud-base") is not None,
        "tailscale_tailnet": settings.tailscale_tailnet,
        "proxmox_node": settings.proxmox_node,
        "proxmox_storage": settings.proxmox_storage,
        "stats": {
            "total_vms": len(vms),
            "running": running,
            "stopped": len(vms) - running,
            "templates": len(templates),
        },
        "recent_jobs": job_store.list(limit=8),
    }


@router.get("/setup")
def setup_status() -> dict:
    hydrate_registry()
    keys = get_ssh_public_keys()
    return {
        "setup_complete": is_setup_complete(),
        "base_image_built": get_built_template("homecloud-base") is not None,
        "tailscale_tailnet": settings.tailscale_tailnet,
        "proxmox_node": settings.proxmox_node,
        "proxmox_storage": settings.proxmox_storage,
        "vm_ssh_user": settings.vm_ssh_user,
        "ssh_public_keys_count": len(keys),
        "ssh_public_keys": keys,
        "rebuild_note": (
            "Changing SSH keys only affects new images/instances. "
            "A base-image rebuild is required to bake new keys into future VMs."
        ),
    }


@router.post("/setup")
def complete_setup(body: SetupRequest) -> dict:
    try:
        save_setup(ssh_public_keys=body.ssh_public_keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    keys = get_ssh_public_keys()
    return {
        "setup_complete": True,
        "ssh_public_keys_count": len(keys),
        "rebuild_required": True,
        "rebuild_note": (
            "Changing SSH keys only affects new images/instances. "
            "A base-image rebuild is required to bake new keys into future VMs."
        ),
    }


@router.get("/sizes")
def sizes_list() -> list[dict]:
    return [
        {
            "id": s.id,
            "label": s.label,
            "cores": s.cores,
            "memory_gb": s.memory_gb,
            "disk_gb": s.disk_gb,
        }
        for s in list_sizes()
    ]


@router.get("/images")
def images_list() -> list[dict]:
    hydrate_registry()
    return [
        {
            "id": img.id,
            "name": img.name,
            "description": img.description,
            "built": (img.template_id or get_built_template(img.id)) is not None,
            "template_id": img.template_id or get_built_template(img.id),
            "default_cores": img.default_cores,
            "default_memory_mb": img.default_memory_mb,
            "default_disk_gb": img.default_disk_gb,
            "packages": img.packages,
        }
        for img in list_images()
    ]


@router.post("/images/homecloud-base/build")
def build_image() -> dict:
    if not is_setup_complete():
        raise HTTPException(400, "Upload your SSH public key in setup first")
    hydrate_registry()
    job = job_store.create(
        "build_image", label="homecloud-base", meta={"image_id": "homecloud-base"}
    )

    def run() -> None:
        job_store.start(job["id"])
        builder = ImageBuilder()
        try:
            result = builder.build_builtin("homecloud-base", log=job_store.logger(job["id"]))
            set_built_template("homecloud-base", result["template_id"])
            job_store.complete(job["id"], result)
        except Exception as exc:
            job_store.fail(job["id"], str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job["id"]}


@router.get("/jobs")
def list_jobs(limit: int = 30) -> list[dict]:
    return job_store.list(limit=min(limit, 50))


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Request cooperative cancellation of a running job (e.g. a deploy).

    The job stops at its next checkpoint; already-finished jobs are unaffected.
    """
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    requested = job_store.request_cancel(job_id)
    return {
        "job_id": job_id,
        "cancel_requested": requested,
        "status": job_store.get(job_id)["status"],
    }


@router.get("/vms")
def list_vms() -> list[dict]:
    proxmox = ProxmoxClient()
    return _merge_registered(proxmox.list_vms())


@router.get("/vms/{vmid}")
def get_vm(vmid: int) -> dict:
    proxmox = ProxmoxClient()
    vm = proxmox.get_vm(vmid)
    if vm is None:
        raise HTTPException(404, "VM not found")
    merged = _merge_registered([vm])[0]
    merged["registered"] = vm.get("name", "") in list_registered_vms()
    return merged


@router.post("/vms")
def deploy_vm(body: DeployVMRequest) -> dict:
    if not is_setup_complete():
        raise HTTPException(400, "Upload your SSH public key in setup first")
    hydrate_registry()
    job = job_store.create(
        "deploy_vm",
        label=body.name,
        meta={
            "name": body.name,
            "size_id": body.size_id,
            "cores": body.cores,
            "memory_gb": body.memory_gb,
            "disk_gb": body.disk_gb,
            "image_id": body.image_id,
        },
    )

    def run() -> None:
        job_store.start(job["id"])
        deployer = VMDeployer()
        try:
            result = deployer.deploy(
                name=body.name,
                size_id=body.size_id or "custom",
                cores=body.cores,  # type: ignore[arg-type]
                memory_gb=body.memory_gb,  # type: ignore[arg-type]
                disk_gb=body.disk_gb,  # type: ignore[arg-type]
                image_id=body.image_id,
                log=job_store.logger(job["id"]),
                cancel_check=lambda: job_store.is_cancel_requested(job["id"]),
            )
            job_store.complete(job["id"], result)
        except JobCancelled as exc:
            job_store.cancelled(job["id"], str(exc))
        except (ValueError, TimeoutError) as exc:
            job_store.fail(job["id"], str(exc))
        except httpx.HTTPError as exc:
            job_store.fail(job["id"], f"Tailscale API error: {exc}")
        except Exception as exc:
            job_store.fail(job["id"], str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job["id"]}


@router.post("/vms/{vmid}/start")
def start_vm(vmid: int) -> dict:
    manager = VMManager()
    try:
        return manager.start(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/vms/{vmid}/stop")
def stop_vm(vmid: int) -> dict:
    manager = VMManager()
    try:
        return manager.stop(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/vms/{vmid}/suspend")
def suspend_vm(vmid: int) -> dict:
    """Pause (suspend to RAM) a running instance."""
    manager = VMManager()
    try:
        return manager.suspend(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/vms/{vmid}/resume")
def resume_vm(vmid: int) -> dict:
    """Resume a previously suspended instance."""
    manager = VMManager()
    try:
        return manager.resume(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.delete("/vms/{vmid}")
def delete_vm(vmid: int, name: str | None = None) -> dict:
    manager = VMManager()
    if not name:
        for vm in ProxmoxClient().list_vms():
            if vm.get("vmid") == vmid:
                name = vm.get("name")
                break
    try:
        return manager.delete(vmid, name=name)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.get("/ssh-config")
def ssh_config_export() -> dict:
    lines = []
    for name, vm in list_registered_vms().items():
        lines.append(ssh_config_block(host_alias=name, hostname=vm.get("hostname", name)))
    return {"config": "".join(lines)}


# ---------------------------------------------------------------------------
# Phase 05 — Port discovery + service routing
# ---------------------------------------------------------------------------


def _require_instance(name: str) -> dict:
    """Return the registered state record for *name* or raise HTTP 404."""
    instance = get_instance(name)
    if instance is None:
        raise HTTPException(404, f"Instance '{name}' not found in state")
    return instance


@router.post("/vms/{name}/scan-ports")
def scan_ports_route(name: str) -> dict:
    """Create a background job that scans listening TCP ports on *name*.

    The job persists results to ``state.vms[name].ports_seen`` on completion.
    Returns ``{job_id}`` immediately.
    """
    instance = _require_instance(name)
    job = job_store.create(
        "scan_ports",
        label=name,
        meta={"instance": name, "tailscale_ip": instance.get("tailscale_ip", "")},
    )

    def run() -> None:
        job_store.start(job["id"])
        log = job_store.logger(job["id"])
        try:
            log("info", f"Starting port scan for {name} ({instance.get('tailscale_ip', 'no-ip')})")
            # Re-read instance in case state changed between request and thread start.
            current = get_instance(name) or instance
            ports = scan_ports(current)
            set_instance_ports(name, ports)
            log("info", f"Found {len(ports)} listening port(s)")
            job_store.complete(job["id"], {"ports": ports, "count": len(ports)})
        except Exception as exc:
            job_store.fail(job["id"], str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job["id"]}


@router.get("/vms/{name}/ports")
def get_ports(name: str) -> dict:
    """Return last port-scan results for *name* from state.

    Run ``POST /api/vms/{name}/scan-ports`` first to populate this.
    """
    instance = _require_instance(name)
    return {
        "ports_seen": instance.get("ports_seen", []),
        "ports_scanned_at": instance.get("ports_scanned_at"),
    }


@router.post("/vms/{name}/services")
def publish_service(name: str, body: PublishServiceRequest) -> dict:
    """Publish *body.port* on instance *name* as a named web service.

    Calls ``publish_web`` (Caddy site file + optional Cloudflare CNAME) and
    persists the entry under ``state.vms[name].web``.

    The ``service`` field must match ``^[a-z][a-z0-9-]{1,30}$`` (validated by
    the schema).  The ``port`` must appear in ``ports_seen`` unless
    ``force=true`` is set.
    """
    instance = _require_instance(name)

    # Port must have been seen in a recent scan (unless overridden).
    if not body.force:
        seen_ports = {p["port"] for p in instance.get("ports_seen", [])}
        if body.port not in seen_ports:
            raise HTTPException(
                400,
                f"Port {body.port} was not found in the last scan of '{name}'. "
                "Run POST /api/vms/{name}/scan-ports first, or set force=true to bypass.",
            )

    upstream_host: str = instance.get("tailscale_ip", "")
    if not upstream_host:
        raise HTTPException(
            400,
            f"Instance '{name}' has no tailscale_ip recorded in state; "
            "ensure the VM has joined the tailnet before publishing.",
        )

    result = publish_web(
        name,
        body.service,
        body.port,
        upstream_host=upstream_host,
        public=body.public,
    )
    return result


@router.delete("/vms/{name}/services/{service}")
def unpublish_service(name: str, service: str) -> dict:
    """Unpublish *service* from instance *name*.

    Removes the Caddy route, Cloudflare record (if present), and state entry.
    No-op when the service was not published.
    """
    _require_instance(name)
    unpublish_web(name, service)
    return {"ok": True, "removed": service}
