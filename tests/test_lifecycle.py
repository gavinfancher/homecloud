"""Tests for VM pause/resume (phase 13) and cooperative job cancellation."""
from __future__ import annotations

import pytest

import homecloud.images.deployer as deployer_module
import homecloud.jobs as jobs_module
from homecloud.images.deployer import VMDeployer, VMManager
from homecloud.jobs import JobCancelled, JobStore


class FakeProxmox:
    def __init__(self):
        self.calls = []

    def suspend(self, vmid):
        self.calls.append(("suspend", vmid))
        return "UPID:suspend"

    def resume(self, vmid):
        self.calls.append(("resume", vmid))
        return "UPID:resume"

    def wait_for_task(self, task, **kwargs):
        self.calls.append(("wait", task))


# ---------------------------------------------------------------------------
# VMManager suspend / resume
# ---------------------------------------------------------------------------


def test_suspend_calls_proxmox_and_waits():
    fp = FakeProxmox()
    result = VMManager(proxmox=fp).suspend(501)
    assert result == {"vmid": 501, "status": "paused"}
    assert ("suspend", 501) in fp.calls
    assert ("wait", "UPID:suspend") in fp.calls


def test_resume_calls_proxmox_and_waits():
    fp = FakeProxmox()
    result = VMManager(proxmox=fp).resume(501)
    assert result == {"vmid": 501, "status": "running"}
    assert ("resume", 501) in fp.calls
    assert ("wait", "UPID:resume") in fp.calls


# ---------------------------------------------------------------------------
# Job cancellation
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_module, "JOBS_FILE", tmp_path / "jobs.json")
    return JobStore()


def test_request_cancel_flags_running_job(store):
    job = store.create("deploy_vm", label="app")
    store.start(job["id"])
    assert store.request_cancel(job["id"]) is True
    assert store.is_cancel_requested(job["id"]) is True


def test_request_cancel_returns_false_for_completed(store):
    job = store.create("deploy_vm", label="app")
    store.complete(job["id"], {"ok": True})
    assert store.request_cancel(job["id"]) is False


def test_request_cancel_returns_false_for_unknown():
    s = JobStore()
    assert s.request_cancel("nope") is False


def test_cancelled_sets_terminal_status(store):
    job = store.create("deploy_vm", label="app")
    store.start(job["id"])
    store.cancelled(job["id"])
    assert store.get(job["id"])["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Deploy honours cancellation checkpoints
# ---------------------------------------------------------------------------


def test_deploy_raises_at_first_checkpoint(monkeypatch):
    monkeypatch.setattr(deployer_module, "hydrate_registry", lambda: None)
    deployer = VMDeployer.__new__(VMDeployer)  # bypass __init__ (no Proxmox/Tailscale)
    with pytest.raises(JobCancelled):
        deployer.deploy(
            name="app", cores=1, memory_gb=1, disk_gb=10, cancel_check=lambda: True
        )


def test_wait_for_tailscale_ip_cancels():
    deployer = VMDeployer.__new__(VMDeployer)
    with pytest.raises(JobCancelled):
        deployer._wait_for_tailscale_ip("app", cancel_check=lambda: True)
