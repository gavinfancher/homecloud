"""Deploy, reconfigure and tear down instances — Proxmox and Tailscale APIs only.

Deploy clones the current base image and hands the clone everything it needs
on a NoCloud seed ISO: hostname, SSH keys, the rendered role script and a
single-use Tailscale auth key. cloud-init runs the script on first boot; the
controller only watches through the QEMU guest agent, then deletes the seed
and records the tailnet device. Reconfigure writes a fresh script through the
guest agent and runs it. Nothing here opens an SSH connection.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import yaml

from homecloud.access import ssh_config_block
from homecloud.config import settings
from homecloud.dns.names import connection_info
from homecloud.dns.zone import write_zone
from homecloud.images.base import current_build, emit_cloud_init_errors, get_build
from homecloud.jobs import JobCancelled
from homecloud.provision.catalog import resolve_roles
from homecloud.provision.script import (
    AUTHKEY_PATH,
    LOG_PATH,
    SCRIPT_PATH,
    render_script,
    run_command,
)
from homecloud.proxmox.client import ProxmoxClient
from homecloud.state import (
    get_instance,
    get_ssh_public_keys,
    register_vm,
    unregister_vm,
)
from homecloud.tailscale.client import TailscaleClient

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]

# Picking a free vmid and creating the clone must not interleave between two
# deploys in this process, or both would pick the same id.
_vmid_lock = threading.Lock()

# First boot runs apt, Docker's installer and the like; give it room.
PROVISION_TIMEOUT = 3600


def _noop_log(_level: str, _message: str) -> None:
    pass


def instance_user_data(
    *, hostname: str, ssh_keys: list[str], script: str, auth_key: str
) -> str:
    """The #cloud-config for an instance's first boot."""
    doc = {
        "hostname": hostname,
        "ssh_authorized_keys": list(ssh_keys),
        "write_files": [
            {"path": SCRIPT_PATH, "permissions": "0700", "content": script},
            {"path": AUTHKEY_PATH, "permissions": "0600", "content": auth_key},
        ],
        "runcmd": [run_command()],
    }
    return "#cloud-config\n" + yaml.safe_dump(doc, sort_keys=False, width=4096)


class VMDeployer:
    """Deploy and reconfigure instances."""

    def __init__(
        self,
        proxmox: ProxmoxClient | None = None,
        tailscale: TailscaleClient | None = None,
    ) -> None:
        self.proxmox = proxmox or ProxmoxClient()
        self.tailscale = tailscale or TailscaleClient()

    def deploy(
        self,
        *,
        name: str,
        cores: int,
        memory_gb: float,
        disk_gb: int,
        roles: list[dict],
        size_id: str = "custom",
        base_image_id: int | None = None,
        mac_address: str | None = None,
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        emit = log or _noop_log

        def check_cancel() -> None:
            if cancel_check and cancel_check():
                raise JobCancelled("Deployment cancelled by user")

        emit("info", "Validating configuration…")
        if not settings.tailscale_api_key:
            raise ValueError("TAILSCALE_API_KEY required — it mints each VM's tailnet key")
        if get_instance(name) is not None:
            raise ValueError(f"An instance named {name!r} already exists")
        roles = resolve_roles(roles)
        base = get_build(base_image_id) if base_image_id else current_build()
        if base is None or base["status"] != "ready":
            raise ValueError("No ready base image — build one from the Base image page first")
        ssh_keys = get_ssh_public_keys()
        if not ssh_keys:
            raise ValueError("No SSH public key — add one in Settings first")
        check_cancel()

        pve = self.proxmox
        with _vmid_lock:
            vmid = pve.next_vmid()
            emit(
                "info",
                f"Cloning base image v{base['id']} (#{base['template_vmid']}) to VM {vmid}",
            )
            clone_task = pve.clone_template(base["template_vmid"], vmid, name)
        started: datetime | None = None
        try:
            pve.wait_for_task(clone_task)
            check_cancel()

            # A MAC no other VM has → its own DHCP lease → its own IP. The
            # seed's network config is rendered from this MAC, so it goes first.
            mac = pve.assign_unique_mac(vmid, mac_address)
            emit("info", f"Assigned MAC {mac}")

            memory_mb = int(memory_gb * 1024)
            emit("info", f"Setting resources: {cores} vCPU, {memory_gb} GB RAM, {disk_gb} GB disk")
            pve.set_resources(vmid, cores=cores, memory_mb=memory_mb)
            pve.grow_disk(vmid, "scsi0", disk_gb)

            script = render_script(roles, user=settings.vm_ssh_user, hostname=name)
            auth_key = self.tailscale.create_vm_auth_key(name)
            pve.attach_seed(
                vmid,
                hostname=name,
                user_data=instance_user_data(
                    hostname=name, ssh_keys=ssh_keys, script=script, auth_key=auth_key
                ),
            )

            # Margin for clock skew between this host and Tailscale's servers.
            started = datetime.now(UTC) - timedelta(minutes=2)
            emit("info", "Starting VM…")
            pve.wait_for_task(pve.start(vmid), timeout=120)

            local_ip = pve.wait_for_vm_ip(vmid, timeout=600, check_cancel=check_cancel)
            role_ids = ", ".join(r["id"] for r in roles)
            emit("info", f"Booted on {local_ip} — running roles: {role_ids}")
            result = pve.guest_run(
                vmid,
                ["cloud-init", "status", "--wait"],
                timeout=PROVISION_TIMEOUT,
                check_cancel=check_cancel,
            )
            self._emit_provision_log(vmid, emit, failed=result["exitcode"] not in (0, 2))
            if result["exitcode"] not in (0, 2):  # 2 = finished with warnings
                emit_cloud_init_errors(pve, vmid, emit)
                raise RuntimeError(
                    f"First-boot provisioning failed (cloud-init exit {result['exitcode']})"
                )
            # The seed held the auth key; it has been spent, and now goes too.
            pve.detach_seed(vmid)

            device = self._wait_for_device(name, since=started, log=emit, check_cancel=check_cancel)
        except BaseException:
            emit("warning", f"Deploy failed — removing VM {vmid}")
            self._discard(vmid, name, joined_since=started)
            raise

        tailscale_ip = TailscaleClient.tailnet_ip(device) or ""
        emit("info", f"Joined the tailnet as {tailscale_ip}")
        record = {
            "vmid": vmid,
            "name": name,
            "base_image_id": base["id"],
            "size_id": size_id,
            "cores": cores,
            "memory_mb": memory_mb,
            "disk_gb": disk_gb,
            "local_ip": local_ip,
            "tailscale_ip": tailscale_ip,
            "tailscale_device_id": TailscaleClient.device_id(device),
            "roles": roles,
        }
        register_vm(name, record)
        write_zone()
        ProxmoxClient.invalidate_vm_list_cache()

        dns = connection_info(name, tailscale_ip, local_ip)
        emit("info", f"Deployment complete — {dns['hostname']}")
        return {
            **record,
            "hostname": dns["hostname"],
            "status": "running",
            "ssh_command": dns["ssh"],
            "ssh_config": ssh_config_block(host_alias=name, hostname=name),
        }

    def provision(
        self,
        name: str,
        roles: list[dict],
        *,
        log: LogFn | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        """Re-apply *roles* to a running instance through the guest agent."""
        emit = log or _noop_log

        def check_cancel() -> None:
            if cancel_check and cancel_check():
                raise JobCancelled("Reconfigure cancelled by user")

        instance = get_instance(name)
        if instance is None:
            raise ValueError(f"Unknown instance: {name}")
        roles = resolve_roles(roles)
        vmid = instance["vmid"]
        pve = self.proxmox

        pve.wait_for_guest_agent(vmid, timeout=60, check_cancel=check_cancel)
        pve.guest_write_file(
            vmid, SCRIPT_PATH, render_script(roles, user=settings.vm_ssh_user, hostname=name)
        )
        emit("info", f"Running roles on {name}: {', '.join(r['id'] for r in roles)}")
        result = pve.guest_run(
            vmid, run_command(), timeout=PROVISION_TIMEOUT, check_cancel=check_cancel
        )
        self._emit_provision_log(vmid, emit, failed=result["exitcode"] != 0)
        if result["exitcode"] != 0:
            raise RuntimeError(f"Reconfigure failed (exit {result['exitcode']})")

        # Only the fields this run changed — the rest may have moved meanwhile.
        fields: dict = {"roles": roles}
        local_ip = pve.get_lan_ip(vmid, use_cache=False)
        if local_ip:
            fields["local_ip"] = local_ip
        register_vm(name, fields)
        emit("info", f"{name} reconfigured")
        return {"name": name, "roles": roles}

    def _emit_provision_log(self, vmid: int, emit: LogFn, *, failed: bool) -> None:
        """Copy the tail of the guest's provision log into the job log."""
        try:
            tail = self.proxmox.guest_run(vmid, ["tail", "-n", "40" if failed else "8", LOG_PATH])
        except Exception:  # noqa: BLE001 — the log is a courtesy
            logger.debug("Could not read provision log on VM %s", vmid, exc_info=True)
            return
        for line in tail["out"].splitlines():
            if line.strip():
                emit("error" if failed else "info", f"  {line}")

    def _wait_for_device(
        self,
        hostname: str,
        *,
        since: datetime,
        timeout: int = 180,
        log: LogFn,
        check_cancel: Callable[[], None],
    ) -> dict:
        deadline = time.time() + timeout
        last_log = 0.0
        while time.time() < deadline:
            check_cancel()
            device = self.tailscale.find_new_device(hostname, since=since)
            if device and TailscaleClient.tailnet_ip(device):
                return device
            if time.time() - last_log >= 15:
                log("info", f"Waiting for {hostname} to appear on the tailnet…")
                last_log = time.time()
            time.sleep(5)
        raise TimeoutError(f"{hostname} did not join the tailnet within {timeout}s")

    def _discard(self, vmid: int, name: str, *, joined_since: datetime | None) -> None:
        """Best-effort removal of a half-deployed VM and its tailnet device.

        Only a device that joined after this deploy booted the VM is removed;
        anything older with the same name belongs to someone else.
        """
        if joined_since is not None:
            try:
                device = self.tailscale.find_new_device(name, since=joined_since)
                if device:
                    self.tailscale.delete_device(TailscaleClient.device_id(device))
            except Exception:  # noqa: BLE001
                logger.warning("Could not check the tailnet for %s", name, exc_info=True)
        VMManager(self.proxmox, self.tailscale).remove_vm(vmid)


class VMManager:
    """Power actions and teardown for registered instances."""

    def __init__(
        self,
        proxmox: ProxmoxClient | None = None,
        tailscale: TailscaleClient | None = None,
    ) -> None:
        self.proxmox = proxmox or ProxmoxClient()
        self.tailscale = tailscale or TailscaleClient()

    def start(self, vmid: int) -> dict:
        self.proxmox.wait_for_task(self.proxmox.start(vmid), timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        # A restarted VM can come back on a different DHCP lease.
        ProxmoxClient.invalidate_lan_ip_cache(vmid)
        return {"vmid": vmid, "status": "running"}

    def stop(self, vmid: int) -> dict:
        self.proxmox.wait_for_task(self.proxmox.stop(vmid), timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        return {"vmid": vmid, "status": "stopped"}

    def suspend(self, vmid: int) -> dict:
        self.proxmox.wait_for_task(self.proxmox.suspend(vmid), timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        return {"vmid": vmid, "status": "paused"}

    def resume(self, vmid: int) -> dict:
        self.proxmox.wait_for_task(self.proxmox.resume(vmid), timeout=120)
        ProxmoxClient.invalidate_vm_list_cache()
        ProxmoxClient.invalidate_lan_ip_cache(vmid)
        return {"vmid": vmid, "status": "running"}

    def delete(self, name: str, *, log: LogFn | None = None) -> dict:
        """Tear down instance *name*: tailnet device, DNS, VM, then the record.

        Every step tolerates the thing already being gone, so a failed
        teardown can simply be run again.
        """
        log = log or _noop_log
        instance = get_instance(name)
        if instance is None:
            raise ValueError(f"Unknown instance: {name}")
        vmid = instance["vmid"]

        tailscale_removed = False
        try:
            device_id = instance.get("tailscale_device_id")
            if device_id:
                self.tailscale.delete_device(device_id)
                tailscale_removed = True
            else:  # instances from before device ids were recorded
                tailscale_removed = self.tailscale.delete_device_by_hostname(name)
        except Exception as exc:  # noqa: BLE001 — a stale device must not block teardown
            logger.warning("Tailscale device delete failed for %s", name, exc_info=True)
            log("warning", f"Could not remove {name} from the tailnet: {exc}")
        else:
            log("info", "Removed from the tailnet" if tailscale_removed else "No tailnet device")

        self.remove_vm(vmid)
        log("info", f"Deleted VM {vmid}")
        unregister_vm(name)
        write_zone()
        return {
            "vmid": vmid,
            "name": name,
            "status": "deleted",
            "tailscale_removed": tailscale_removed,
        }

    def remove_vm(self, vmid: int) -> None:
        pve = self.proxmox
        if pve.get_vm(vmid) is not None:
            try:
                pve.wait_for_task(pve.stop(vmid), timeout=120)
            except Exception:  # noqa: BLE001 — already stopped
                logger.debug("Stop of VM %s failed", vmid, exc_info=True)
            task = pve.delete_vm(vmid)
            if task:
                pve.wait_for_task(task, timeout=300)
        try:
            pve.delete_seed(vmid)
        except Exception:  # noqa: BLE001
            logger.warning("Leftover seed ISO for VM %s", vmid, exc_info=True)
        ProxmoxClient.invalidate_vm_list_cache()
        # next_vmid reuses ids — a stale entry would label the next VM wrongly.
        ProxmoxClient.invalidate_lan_ip_cache(vmid)
