import os

import pytest

# Tests need a Postgres; `make test` starts one in Docker. They wipe its tables.
os.environ["HOMECLOUD_DATABASE_URL"] = os.environ.get(
    "HOMECLOUD_TEST_DATABASE_URL", "postgresql://postgres:test@localhost:5434/postgres")
os.environ.pop("HOMECLOUD_LOCAL", None)
os.environ["HOMECLOUD_SSH_KEYS"] = "ssh-ed25519 AAAAtest test@laptop"
os.environ["HOMECLOUD_WINDOWS_ADMIN_PASSWORD"] = "Pa<ss>&word1!"

from app import auth, config  # noqa: E402

PASSWORD = "correct horse battery staple"
config.ADMIN_PASSWORD_HASH = auth.hash_password(PASSWORD)

from fastapi.testclient import TestClient  # noqa: E402

from app import db, main  # noqa: E402


@pytest.fixture
def anon():
    """Someone who hasn't signed in. (No `with`, so the worker thread doesn't start.)"""
    db.init_schema()
    with db.conn() as c:
        c.execute("TRUNCATE vm_events, vms, sessions")
    auth._failures.clear()
    return TestClient(main.app)


@pytest.fixture
def client(anon):
    r = anon.post("/api/login", json={"password": PASSWORD})
    assert r.status_code == 200, r.text
    anon.headers["Authorization"] = "Bearer " + r.json()["token"]
    return anon


class FakePve:
    """Stands in for app.pve: remembers VMs in a dict instead of calling Proxmox."""

    TAG = "homecloud"
    PveError = RuntimeError

    def __init__(self):
        self.vms: dict[int, dict] = {}
        self.isos: set[str] = set()
        self.agent_ip: str | None = None

    def status_by_vmid(self):
        return {k: dict(v) for k, v in self.vms.items()}

    def exists(self, vmid):
        return vmid in self.vms

    def free_vmid(self, start, taken):
        vmid = start
        while vmid in self.vms or vmid in taken:
            vmid += 1
        return vmid

    def upload_iso(self, filename, data):
        volid = f"{config.PROXMOX_FILE_STORAGE}:iso/{filename}"
        self.isos.add(volid)
        return volid

    def delete_volume(self, volid):
        self.isos.discard(volid)

    def ubuntu_image(self, progress=None):
        return "local:import/ubuntu.qcow2"

    def virtio_iso(self, progress=None):
        return "local:iso/virtio.iso"

    def create_ubuntu(self, vmid, name, cores, memory_mb, disk_gb, seed, image, *rest):
        # Like Proxmox: created in the pool, untagged; finish() tags it.
        self.vms[vmid] = {"name": name, "status": "stopped", "tags": "", "pool": "homecloud",
                          "cds": {"ide2": seed}}

    create_windows = create_ubuntu

    def finish(self, vmid, os, disk_gb):
        self.vms[vmid]["tags"] = "homecloud"

    def status(self, vmid):
        return self.vms[vmid]["status"]

    def start(self, vmid):
        self.vms[vmid]["status"] = "running"

    def press_enter(self, vmid):
        pass

    def stop(self, vmid):
        self.vms[vmid]["status"] = "stopped"

    def shutdown(self, vmid):
        self.stop(vmid)

    def lan_ip(self, vmid):
        return self.agent_ip

    def eject(self, vmid, *drives):
        for d in drives:
            self.vms[vmid]["cds"].pop(d, None)

    def destroy(self, vmid):
        del self.vms[vmid]


@pytest.fixture
def fake_pve(monkeypatch):
    from app import provision

    fake = FakePve()
    monkeypatch.setattr(provision, "pve", fake)
    monkeypatch.setattr(main, "pve", fake)
    return fake
