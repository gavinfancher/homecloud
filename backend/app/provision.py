"""The worker: moves each VM through its steps until it's up, or deleted.

It's a loop, not a queue. Every few seconds it looks at the VMs that are `creating` or
`deleting` and does the next step for each. Every step is safe to repeat: it checks what
Proxmox already has before acting. So if the pod restarts halfway (a deploy, a node reboot),
the new one picks up where the old one stopped.

Creating:

  create      reserve a VMID, upload the seed/answer ISO, create the VM
  start       power on (Windows: press Enter at "boot from CD")
  wait        until the guest agent reports an IP: Ubuntu in a few minutes, Windows in ~20-40
  cleanup     eject the install discs and delete the uploaded ISO, then `ready`

Only one worker runs at a time, even with two pods during a rolling update: it holds a
Postgres advisory lock for as long as it runs.
"""

import logging
import threading
import time
from datetime import UTC, datetime

import psycopg

from app import config, db, media, pve

log = logging.getLogger("homecloud.worker")

LOCK_ID = 0x686F6D65  # "home"
TICK = 5
IP_REFRESH = 60
# How long a VM may sit on one step before it's marked failed.
TIMEOUTS = {
    ("ubuntu", "create"): 60 * 60,  # the first one downloads the cloud image
    ("ubuntu", "wait"): 20 * 60,
    ("windows", "create"): 60 * 60,  # the first one downloads the VirtIO ISO
    ("windows", "wait"): 90 * 60,
}
DEFAULT_TIMEOUT = 15 * 60


def _seed_volid(vmid: int) -> str:
    return f"{config.PROXMOX_FILE_STORAGE}:iso/{media.seed_iso_name(vmid)}"


# ---------- creating ----------

def step_create(vm: dict) -> bool:
    vmid = vm["vmid"]
    if vmid is None:
        vmid = pve.free_vmid(config.VMID_START, db.used_vmids())
        # Saved before anything is made, so a retry (or a delete) finds the same VM.
        if not db.update_vm(vm["name"], only_if="creating", vmid=vmid):
            return False  # deleted meanwhile
    if pve.exists(vmid):
        return True  # created on an earlier try
    if vm["os"] == "ubuntu":
        seed = pve.upload_iso(media.seed_iso_name(vmid), media.ubuntu_seed(vm["name"]))
        pve.create_ubuntu(vmid, vm["name"], vm["cores"], vm["memory_mb"], vm["disk_gb"], seed)
    else:
        answer = pve.upload_iso(media.seed_iso_name(vmid), media.windows_answer(vm["name"]))
        pve.create_windows(vmid, vm["name"], vm["cores"], vm["memory_mb"], vm["disk_gb"], answer)
    return True


def step_start(vm: dict) -> bool:
    if pve.status(vm["vmid"]) == "running":
        return True
    pve.start(vm["vmid"])
    if vm["os"] == "windows":
        pve.press_enter(vm["vmid"])
    return True


def step_wait(vm: dict) -> bool:
    ip = pve.lan_ip(vm["vmid"])
    if ip:
        db.update_vm(vm["name"], only_if="creating", ip=ip)
    return ip is not None


def step_cleanup(vm: dict) -> bool:
    drives = ["ide2"] if vm["os"] == "ubuntu" else ["ide0", "ide1", "ide2"]
    pve.eject(vm["vmid"], *drives)
    pve.delete_volume(_seed_volid(vm["vmid"]))
    return True


STEPS = {
    "create": (step_create, "start"),
    "start": (step_start, "wait"),
    "wait": (step_wait, "cleanup"),
    "cleanup": (step_cleanup, None),
}


def advance(vm: dict) -> None:
    """Do the VM's current step; on success move to the next one, or to `ready`."""
    fn, nxt = STEPS[vm["step"]]
    if fn(vm):
        if nxt:
            db.update_vm(vm["name"], only_if="creating", step=nxt)
        else:
            db.update_vm(vm["name"], only_if="creating", state="ready", step="done", error=None)
        log.info("%s: %s done", vm["name"], vm["step"])
        return
    limit = TIMEOUTS.get((vm["os"], vm["step"]), DEFAULT_TIMEOUT)
    if (datetime.now(UTC) - vm["step_started"]).total_seconds() > limit:
        raise TimeoutError(f"Still on '{vm['step']}' after {limit // 60} minutes")


# ---------- deleting ----------

def remove(vm: dict) -> None:
    vmid = vm["vmid"]
    if vmid is not None and pve.exists(vmid):
        tags = (pve.status_by_vmid()[vmid].get("tags") or "").split(";")
        if pve.TAG not in tags:
            raise pve.PveError(f"VM {vmid} isn't tagged '{pve.TAG}'; refusing to delete it")
        pve.stop(vmid)
        pve.destroy(vmid)
    if vmid is not None:
        pve.delete_volume(_seed_volid(vmid))
    db.delete_vm_row(vm["name"])
    log.info("%s: deleted", vm["name"])


# ---------- the loop ----------

def tick(last_refresh: dict[str, float]) -> None:
    for vm in db.vms_in("creating", "deleting"):
        try:
            if vm["state"] == "deleting":
                remove(vm)
            else:
                advance(vm)
        except Exception as e:
            log.exception("%s: %s failed", vm["name"], vm["step"])
            # A failed delete stays `deleting` and is retried; a failed create stops.
            if vm["state"] == "creating":
                db.update_vm(vm["name"], only_if="creating", state="failed", error=f"{vm['step']}: {e}"[:500])
            else:
                db.update_vm(vm["name"], error=f"delete: {e}"[:500])
    # DHCP can hand out a new address, so check the ready ones now and then.
    now = time.monotonic()
    for vm in db.vms_in("ready"):
        if now - last_refresh.get(vm["name"], 0) > IP_REFRESH:
            last_refresh[vm["name"]] = now
            ip = pve.lan_ip(vm["vmid"])
            if ip and ip != vm["ip"]:
                db.update_vm(vm["name"], only_if="ready", ip=ip)


def run(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            # A connection of its own, holding the lock for as long as this loop runs.
            with psycopg.connect(config.DATABASE_URL, autocommit=True) as lock_conn:
                if not lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
                    stop.wait(TICK)
                    continue
                log.info("worker running")
                last_refresh: dict[str, float] = {}
                while not stop.is_set():
                    tick(last_refresh)
                    lock_conn.execute("SELECT 1")  # notice a dropped connection (and lost lock)
                    stop.wait(TICK)
        except Exception:
            log.exception("worker loop error; retrying")
            stop.wait(TICK)


def start_thread() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=run, args=(stop,), name="worker", daemon=True).start()
    return stop
