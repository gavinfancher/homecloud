"""Job handlers: what each queued job type actually does.

A handler takes the job context and the payload the route enqueued, and
returns the job's result.  Raising marks the job failed with the message;
raising ``JobCancelled`` marks it cancelled.
"""

from __future__ import annotations

import httpx

from homecloud.images.deployer import VMDeployer, VMManager
from homecloud.images.sources import ensure_source_template
from homecloud.jobs import Handler, JobContext
from homecloud.ports import scan_ports as scan_instance_ports
from homecloud.state import get_instance, set_instance_ports


def import_source(ctx: JobContext, payload: dict) -> dict:
    source_id = payload["source_id"]
    template_id = ensure_source_template(
        source_id, log=ctx.log, cancel_check=ctx.cancel_requested
    )
    return {"source_id": source_id, "template_id": template_id}


def deploy_vm(ctx: JobContext, payload: dict) -> dict:
    try:
        return VMDeployer().deploy(**payload, log=ctx.log, cancel_check=ctx.cancel_requested)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Tailscale API error: {exc}") from exc


def provision_vm(ctx: JobContext, payload: dict) -> dict:
    return VMDeployer().provision(
        payload["name"], payload["roles"], log=ctx.log, cancel_check=ctx.cancel_requested
    )


def delete_vm(ctx: JobContext, payload: dict) -> dict:
    vmid, name = payload["vmid"], payload.get("name")
    label = name or f"vm-{vmid}"
    ctx.log("info", f"Deleting {label}…")
    result = VMManager().delete(vmid, name=name, log=ctx.log)
    ctx.log("info", f"Deleted {label}")
    return result


def scan_ports(ctx: JobContext, payload: dict) -> dict:
    name = payload["name"]
    instance = get_instance(name)
    if instance is None:
        raise ValueError(f"Instance '{name}' is no longer registered")
    ctx.log("info", f"Starting port scan for {name} ({instance.get('tailscale_ip') or 'no-ip'})")
    ports = scan_instance_ports(instance)
    set_instance_ports(name, ports)
    ctx.log("info", f"Found {len(ports)} listening port(s)")
    return {"ports": ports, "count": len(ports)}


HANDLERS: dict[str, Handler] = {
    "import_source": import_source,
    "deploy_vm": deploy_vm,
    "provision_vm": provision_vm,
    "delete_vm": delete_vm,
    "scan_ports": scan_ports,
}
