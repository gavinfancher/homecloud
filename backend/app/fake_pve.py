"""A pretend Proxmox, in memory, for trying the UI locally (HOMECLOUD_FAKE_PROXMOX=1, `make demo`).

Same functions as pve.py, the ones the API and worker use. VMs move through the real worker
steps, just faster: an Ubuntu VM gets its IP about 10 seconds after it starts, Windows about 30.
Nothing here touches the network, and it all resets when the process restarts.
"""

import itertools
import threading
import time

from app import config

TAG = "homecloud"
BOOT_SECONDS = {"ubuntu": 10, "windows": 30}


class PveError(Exception):
    pass


_lock = threading.Lock()
_vms: dict[int, dict] = {}
_ips = (f"10.0.4.{n}" for n in itertools.count(150))


def status_by_vmid() -> dict[int, dict]:
    with _lock:
        now = time.time()
        return {vmid: {"vmid": vmid, "name": v["name"], "tags": TAG, "status": v["status"],
                       "uptime": int(now - v["started"]) if v["status"] == "running" else 0}
                for vmid, v in _vms.items()}


def exists(vmid: int) -> bool:
    return vmid in _vms


def free_vmid(start: int, also_taken: set[int]) -> int:
    vmid = start
    while vmid in _vms or vmid in also_taken:
        vmid += 1
    return vmid


def upload_iso(filename: str, data: bytes) -> str:
    return f"{config.PROXMOX_FILE_STORAGE}:iso/{filename}"


def delete_volume(volid: str) -> None:
    pass


def _create(os: str, vmid: int, name: str) -> None:
    time.sleep(2)  # creating takes a moment
    with _lock:
        _vms[vmid] = {"name": name, "os": os, "status": "stopped", "started": 0, "ip": None}


def create_ubuntu(vmid, name, cores, memory_mb, disk_gb, seed):
    _create("ubuntu", vmid, name)


def create_windows(vmid, name, cores, memory_mb, disk_gb, answer):
    _create("windows", vmid, name)


def finish(vmid: int, os: str, disk_gb: int) -> None:
    pass


def status(vmid: int) -> str:
    return _vms[vmid]["status"]


def start(vmid: int) -> None:
    with _lock:
        vm = _vms[vmid]
        if vm["status"] != "running":
            vm["status"], vm["started"] = "running", time.time()


def press_enter(vmid: int, times: int = 15) -> None:
    pass


def stop(vmid: int) -> None:
    with _lock:
        _vms[vmid]["status"] = "stopped"


shutdown = stop


def lan_ip(vmid: int) -> str | None:
    with _lock:
        vm = _vms.get(vmid)
        if not vm or vm["status"] != "running" or time.time() - vm["started"] < BOOT_SECONDS[vm["os"]]:
            return None
        vm["ip"] = vm["ip"] or next(_ips)
        return vm["ip"]


def eject(vmid: int, *drives: str) -> None:
    pass


def destroy(vmid: int) -> None:
    time.sleep(1)
    with _lock:
        _vms.pop(vmid, None)
