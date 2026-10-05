from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from homecloud.access import ssh_config_block
from homecloud.api.schemas import (
    BaseImageConfigRequest,
    DeployVMRequest,
    ProvisionRequest,
    SetupRequest,
)
from homecloud.auth import get_clerk_auth
from homecloud.config import settings
from homecloud.dns.names import connection_info, private_fqdn
from homecloud.images import base
from homecloud.images.deployer import VMManager
from homecloud.jobs import job_store
from homecloud.provision.catalog import RoleError, list_roles, resolve_roles
from homecloud.proxmox.client import ProxmoxClient
from homecloud.sizes import list_sizes
from homecloud.state import (
    get_instance,
    get_ssh_public_keys,
    is_setup_complete,
    list_registered_vms,
    save_setup,
    set_instance_local_ip,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])
# Unauthenticated endpoints (health + SPA bootstrap config).
public_router = APIRouter(prefix="/api", tags=["public"])


def _local_ip(vm: dict, proxmox: ProxmoxClient | None) -> str:
    """LAN address for *vm* — live from the guest agent, falling back to state.

    Running VMs are re-probed (cached in the client) because DHCP can move a VM
    to a new lease; the stored value is refreshed whenever it changes so a
    stopped VM still shows the address it last had.
    """
    stored = vm.get("local_ip") or ""
    if proxmox is None or vm.get("status") != "running" or not vm.get("vmid"):
        return stored
    live = proxmox.get_lan_ip(vm["vmid"])
    if not live:
        return stored
    if live != stored and vm.get("name"):
        set_instance_local_ip(vm["name"], live)
    return live


def _merge_registered(vms: list[dict], proxmox: ProxmoxClient | None = None) -> list[dict]:
    """Registered instances only, each merged with its live Proxmox status.

    Other VMs on the node (the control VM itself, anything made by hand) are
    left out, so the console can never stop or delete them.
    """
    registered = list_registered_vms()
    managed = {r["vmid"] for r in registered.values()}
    vms = [vm for vm in vms if vm.get("vmid") in managed]
    for vm in vms:
        name = vm.get("name", "")
        if name in registered:
            reg = registered[name]
            vm.update(reg)
            # Proxmox list API omits disk on some builds; keep registry values.
            if vm.get("disk_gb") is None and reg.get("disk_gb") is not None:
                vm["disk_gb"] = reg["disk_gb"]
            if vm.get("cores") is None and reg.get("cores") is not None:
                vm["cores"] = reg["cores"]
            if vm.get("memory_gb") is None and reg.get("memory_gb") is not None:
                vm["memory_gb"] = reg["memory_gb"]
        # Always expose the current split-DNS hostname and LAN address
        # (migrates away from legacy .home records).
        if name:
            local_ip = _local_ip(vm, proxmox)
            if vm.get("tailscale_ip") or vm.get("ip"):
                ip = vm.get("tailscale_ip") or vm.get("ip")
                vm.update(connection_info(name, ip, local_ip))
            else:
                vm["hostname"] = private_fqdn(name)
                vm["local_ip"] = local_ip
        if vm.get("memory_gb") is None and vm.get("memory_mb"):
            # maxmem from the cluster list is bytes; config memory is MB.
            mb = vm["memory_mb"]
            if mb > 10000:
                mb = mb // (1024 * 1024)
            vm["memory_gb"] = round(mb / 1024, 2)
    return vms


def _sort_vms(vms: list[dict]) -> list[dict]:
    """Stable list order — Proxmox cluster list order is not consistent across polls."""
    return sorted(vms, key=lambda v: ((v.get("name") or "").lower(), v.get("vmid") or 0))


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


@router.get("/dashboard")
def dashboard() -> dict:
    proxmox = ProxmoxClient()
    # Dashboard only needs counts — skip the guest-agent LAN IP probe.
    vms = _sort_vms(_merge_registered(proxmox.list_vms()))
    templates = proxmox.list_templates()
    running = sum(1 for vm in vms if vm.get("status") == "running")
    return {
        "setup_complete": is_setup_complete(),
        "base_image_ready": base.current_build() is not None,
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
    keys = get_ssh_public_keys()
    return {
        "setup_complete": is_setup_complete(),
        "tailscale_tailnet": settings.tailscale_tailnet,
        "proxmox_node": settings.proxmox_node,
        "proxmox_storage": settings.proxmox_storage,
        "vm_ssh_user": settings.vm_ssh_user,
        "ssh_public_keys_count": len(keys),
        "ssh_public_keys": keys,
        "rebuild_note": "Changing SSH keys only affects base images built afterwards.",
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
        "rebuild_note": "Changing SSH keys only affects base images built afterwards.",
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


@router.get("/roles")
def roles_list() -> list[dict]:
    """The role catalog the create flow renders its configure step from."""
    return list_roles()


@router.get("/base-image")
def base_image() -> dict:
    """The editable base image definition, its builds, and the one deploys use."""
    return {
        "config": base.get_config(),
        "current": base.current_build(),
        "builds": base.list_builds(),
    }


@router.put("/base-image")
def update_base_image(body: BaseImageConfigRequest) -> dict:
    """Edit the definition. Takes effect on the next build, never on existing ones."""
    try:
        return base.update_config(
            image_url=body.image_url,
            packages=body.packages,
            extra_user_data=body.extra_user_data,
        )
    except base.BaseImageError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/base-image/build")
def build_base_image() -> dict:
    """Build a new base image version from the current definition and SSH keys."""
    try:
        build_id = base.start_build()
    except base.BaseImageError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = job_store.enqueue(
        "build_base_image",
        label=f"base image v{build_id}",
        meta={"build_id": build_id},
        payload={"build_id": build_id},
    )
    return {"job_id": job["id"], "build_id": build_id}


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
    return _sort_vms(_merge_registered(proxmox.list_vms(), proxmox))


@router.get("/vms/{vmid}")
def get_vm(vmid: int) -> dict:
    proxmox = ProxmoxClient()
    vm = proxmox.get_vm(vmid)
    if vm is None:
        raise HTTPException(404, "VM not found")
    merged = _merge_registered([vm], proxmox)[0]
    merged["registered"] = vm.get("name", "") in list_registered_vms()
    return merged


@router.post("/vms")
def deploy_vm(body: DeployVMRequest) -> dict:
    if not is_setup_complete():
        raise HTTPException(400, "Upload your SSH public key in setup first")
    if get_instance(body.name) is not None:
        raise HTTPException(409, f"An instance named {body.name!r} already exists")
    roles = [r.model_dump() for r in body.roles]
    try:
        resolve_roles(roles)  # fail fast; the job resolves again
    except RoleError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = job_store.enqueue(
        "deploy_vm",
        label=body.name,
        meta={
            "name": body.name,
            "size_id": body.size_id,
            "cores": body.cores,
            "memory_gb": body.memory_gb,
            "disk_gb": body.disk_gb,
            "base_image_id": body.base_image_id,
            "roles": [r["id"] for r in roles],
        },
        payload={
            "name": body.name,
            "size_id": body.size_id or "custom",
            "cores": body.cores,
            "memory_gb": body.memory_gb,
            "disk_gb": body.disk_gb,
            "base_image_id": body.base_image_id,
            "mac_address": body.mac_address,
            "roles": roles,
        },
    )
    return {"job_id": job["id"]}


@router.post("/vms/{name}/provision")
def provision_vm(name: str, body: ProvisionRequest) -> dict:
    """Re-run the role script on an existing instance with a new role selection."""
    _require_instance(name)
    roles = [r.model_dump() for r in body.roles]
    try:
        resolve_roles(roles)
    except RoleError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = job_store.enqueue(
        "provision_vm",
        label=name,
        meta={"name": name, "roles": [r["id"] for r in roles]},
        payload={"name": name, "roles": roles},
    )
    return {"job_id": job["id"]}


@router.post("/vms/{vmid}/start")
def start_vm(vmid: int) -> dict:
    _require_managed(vmid)
    manager = VMManager()
    try:
        return manager.start(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/vms/{vmid}/stop")
def stop_vm(vmid: int) -> dict:
    _require_managed(vmid)
    manager = VMManager()
    try:
        return manager.stop(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/vms/{vmid}/suspend")
def suspend_vm(vmid: int) -> dict:
    """Pause (suspend to RAM) a running instance."""
    _require_managed(vmid)
    manager = VMManager()
    try:
        return manager.suspend(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/vms/{vmid}/resume")
def resume_vm(vmid: int) -> dict:
    """Resume a previously suspended instance."""
    _require_managed(vmid)
    manager = VMManager()
    try:
        return manager.resume(vmid)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.delete("/vms/{vmid}")
def delete_vm(vmid: int) -> dict:
    name = _require_managed(vmid)["name"]
    job = job_store.enqueue(
        "delete_vm",
        label=name,
        meta={"vmid": vmid, "name": name},
        payload={"name": name},
    )
    return {"job_id": job["id"]}


@router.get("/ssh-config")
def ssh_config_export() -> dict:
    lines = []
    for name, vm in list_registered_vms().items():
        lines.append(ssh_config_block(host_alias=name, hostname=vm.get("hostname", name)))
    return {"config": "".join(lines)}


# ---------------------------------------------------------------------------
# Phase 05 — Port discovery + service routing
# ---------------------------------------------------------------------------


def _require_managed(vmid: int) -> dict:
    """The registered instance with *vmid*, or 404 — other VMs are off limits."""
    for instance in list_registered_vms().values():
        if instance["vmid"] == vmid:
            return instance
    raise HTTPException(404, f"VM {vmid} is not a homecloud instance")


def _require_instance(name: str) -> dict:
    """Return the registered record for *name* or raise HTTP 404."""
    instance = get_instance(name)
    if instance is None:
        raise HTTPException(404, f"Instance '{name}' is not registered")
    return instance


@router.post("/vms/{name}/scan-ports")
def scan_ports_route(name: str) -> dict:
    """Create a background job that scans listening TCP ports on *name*.

    The job stores results on the instance (``ports_seen``) on completion.
    Returns ``{job_id}`` immediately.
    """
    instance = _require_instance(name)
    job = job_store.enqueue(
        "scan_ports",
        label=name,
        meta={"instance": name, "tailscale_ip": instance.get("tailscale_ip") or ""},
        payload={"name": name},
    )
    return {"job_id": job["id"]}


@router.get("/vms/{name}/ports")
def get_ports(name: str) -> dict:
    """Return the last port-scan results for *name*.

    Run ``POST /api/vms/{name}/scan-ports`` first to populate this.
    """
    instance = _require_instance(name)
    return {
        "ports_seen": instance.get("ports_seen") or [],
        "ports_scanned_at": instance.get("ports_scanned_at"),
    }
