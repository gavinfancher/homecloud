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
from contextlib import contextmanager
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


# ---------- the VM's log ----------

_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}


def note(vm: dict, message: str, level: str = "info") -> None:
    """One line in the VM's log (the Log panel in the UI), and in the pod's log."""
    log.log(_LEVELS[level], "%s: %s", vm["name"], message)
    try:
        db.add_event(vm["name"], message[:4000], level)
    except Exception:
        log.exception("couldn't save a log line for %s", vm["name"])


def took(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


@contextmanager
def doing(vm: dict, what: str):
    """Log *what* is starting, then that it finished and how long it took. (A failure is logged
    by tick(), with the error.)"""
    note(vm, f"{what}…")
    began = time.monotonic()
    yield
    note(vm, f"↳ done in {took(time.monotonic() - began)}")


# ---------- creating ----------

def step_create(vm: dict) -> bool:
    vmid = vm["vmid"]
    spec = f"{vm['cores']} vCPU, {vm['memory_mb'] // 1024} GB memory, {vm['disk_gb']} GB disk"
    if vmid is None:
        vmid = pve.free_vmid(config.VMID_START, db.used_vmids())
        # Saved before anything is made, so a retry (or a delete) finds the same VM.
        if not db.update_vm(vm["name"], only_if="creating", vmid=vmid):
            return False  # deleted meanwhile
        note(vm, f"Reserved VM ID {vmid}")
    progress = lambda line: note(vm, line)  # noqa: E731
    if pve.exists(vmid):
        note(vm, f"VM {vmid} already exists from an earlier try; finishing it")
    elif vm["os"] == "ubuntu":
        with doing(vm, "Getting the Ubuntu 26.04 cloud image"):
            image = pve.ubuntu_image(progress)
        with doing(vm, "Uploading the cloud-init seed ISO (hostname, SSH keys, guest agent)"):
            seed = pve.upload_iso(media.seed_iso_name(vmid), media.ubuntu_seed(vm["name"]))
        with doing(vm, f"Creating VM {vmid} ({spec}) with the cloud image as its disk"):
            pve.create_ubuntu(vmid, vm["name"], vm["cores"], vm["memory_mb"], vm["disk_gb"], seed, image)
    else:
        with doing(vm, "Getting the VirtIO drivers ISO"):
            virtio = pve.virtio_iso(progress)
        with doing(vm, "Uploading the answer ISO (autounattend.xml)"):
            answer = pve.upload_iso(media.seed_iso_name(vmid), media.windows_answer(vm["name"]))
        with doing(vm, f"Creating VM {vmid} ({spec}; UEFI, Secure Boot, TPM 2.0)"):
            pve.create_windows(vmid, vm["name"], vm["cores"], vm["memory_mb"], vm["disk_gb"], answer, virtio)
    grow = f" and growing the disk to {vm['disk_gb']} GB" if vm["os"] == "ubuntu" else ""
    with doing(vm, f"Tagging it '{pve.TAG}'{grow}"):
        pve.finish(vmid, vm["os"], vm["disk_gb"])
    return True


def step_start(vm: dict) -> bool:
    if pve.status(vm["vmid"]) == "running":
        note(vm, "Already running")
        return True
    with doing(vm, "Powering on"):
        pve.start(vm["vmid"])
    if vm["os"] == "windows":
        with doing(vm, "Pressing Enter for “Press any key to boot from CD or DVD”"):
            pve.press_enter(vm["vmid"])
    return True


WAIT_REPORT = 120  # seconds between "still waiting" lines
_wait_reported: dict[str, int] = {}


def step_wait(vm: dict) -> bool:
    name = vm["name"]
    waited = (datetime.now(UTC) - vm["step_started"]).total_seconds()
    if name not in _wait_reported:
        expect = "a minute or two" if vm["os"] == "ubuntu" else "20–40 minutes while Windows installs"
        resumed = " (resumed after a restart)" if waited > 30 else ""
        note(vm, f"Waiting for the guest agent to report an IP: usually {expect}{resumed}")
        _wait_reported[name] = int(waited // WAIT_REPORT)
    ip = pve.lan_ip(vm["vmid"])
    if ip:
        _wait_reported.pop(name, None)
        db.update_vm(name, only_if="creating", ip=ip)
        note(vm, f"Guest agent reports {ip} (after {took(waited)})")
        return True
    if int(waited // WAIT_REPORT) > _wait_reported[name]:
        _wait_reported[name] = int(waited // WAIT_REPORT)
        power = pve.status(vm["vmid"])
        why = "no answer from the guest agent yet" if power == "running" else f"the VM is {power}"
        note(vm, f"Still waiting for an IP after {took(waited)}: {why}", "info" if power == "running" else "warn")
    return False


def step_cleanup(vm: dict) -> bool:
    drives = ["ide2"] if vm["os"] == "ubuntu" else ["ide0", "ide1", "ide2"]
    with doing(vm, "Ejecting the install discs and deleting the uploaded ISO"):
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
            age = (datetime.now(UTC) - vm["created_at"]).total_seconds()
            note(vm, f"Ready, {took(age)} after it was asked for")
        return
    limit = TIMEOUTS.get((vm["os"], vm["step"]), DEFAULT_TIMEOUT)
    if (datetime.now(UTC) - vm["step_started"]).total_seconds() > limit:
        raise TimeoutError(f"Still on '{vm['step']}' after {limit // 60} minutes")


# ---------- deleting ----------

def remove(vm: dict) -> None:
    vmid = vm["vmid"]
    if vmid is not None and pve.exists(vmid):
        # Ours if it's tagged homecloud or in the homecloud pool (a create that stopped before
        # tagging leaves it in the pool, untagged).
        info = pve.status_by_vmid()[vmid]
        if pve.TAG not in (info.get("tags") or "").split(";") and info.get("pool") != config.PROXMOX_POOL:
            raise pve.PveError(f"VM {vmid} isn't tagged '{pve.TAG}' or in pool '{config.PROXMOX_POOL}'; refusing to delete it")
        with doing(vm, f"Stopping and destroying VM {vmid} and its disks"):
            pve.stop(vmid)
            pve.destroy(vmid)
    if vmid is not None:
        pve.delete_volume(_seed_volid(vmid))
    db.delete_vm_row(vm["name"])  # its log goes with it
    log.info("%s: deleted", vm["name"])


# ---------- the loop ----------

def _record_failure(vm: dict, e: Exception) -> None:
    if vm["state"] == "creating":
        note(vm, f"Failed at '{vm['step']}': {e}", "error")
        db.update_vm(vm["name"], only_if="creating", state="failed", error=f"{vm['step']}: {e}"[:500])
    else:
        # A failed delete stays `deleting` and is retried every few seconds: log it once per
        # new error, not on every retry.
        error = f"delete: {e}"[:500]
        if error != vm["error"]:
            note(vm, f"Delete failed; retrying every {TICK}s until it works: {e}", "error")
        db.update_vm(vm["name"], error=error)
    task_log = getattr(e, "log", None)
    if task_log and (vm["state"] == "creating" or f"delete: {e}"[:500] != vm["error"]):
        note(vm, "Proxmox's task log ended with:\n" + "\n".join(task_log), "error")


def tick(last_refresh: dict[str, float]) -> None:
    for vm in db.vms_in("creating", "deleting"):
        try:
            if vm["state"] == "deleting":
                remove(vm)
            else:
                advance(vm)
        except Exception as e:
            log.exception("%s: %s failed", vm["name"], vm["step"])
            _record_failure(vm, e)
    # DHCP can hand out a new address, so check the ready ones now and then.
    now = time.monotonic()
    for vm in db.vms_in("ready"):
        if now - last_refresh.get(vm["name"], 0) > IP_REFRESH:
            last_refresh[vm["name"]] = now
            ip = pve.lan_ip(vm["vmid"])
            if ip and ip != vm["ip"]:
                db.update_vm(vm["name"], only_if="ready", ip=ip)
                note(vm, f"IP changed: {vm['ip'] or 'none'} → {ip}")


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
