from app import db, provision
from app.pve import PveError


def run_until_settled(fake_pve, ticks=10):
    for _ in range(ticks):
        provision.tick({})


def test_ubuntu_goes_to_ready(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})  # create
    vm = db.get_vm("web1")
    assert vm["vmid"] == 700 and vm["step"] == "start"
    assert fake_pve.isos == {"homecloud:iso/homecloud-700-seed.iso"}

    provision.tick({})  # start
    provision.tick({})  # wait: no IP yet
    assert db.get_vm("web1")["step"] == "wait"

    fake_pve.agent_ip = "10.0.4.77"
    provision.tick({})  # wait: IP
    provision.tick({})  # cleanup
    vm = db.get_vm("web1")
    assert (vm["state"], vm["ip"]) == ("ready", "10.0.4.77")
    assert fake_pve.isos == set()  # seed deleted
    assert fake_pve.vms[700]["cds"] == {}  # and ejected


def test_create_is_resumable(anon, fake_pve):
    """A restart after the VM was made, but before the step was recorded, doesn't make another."""
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    db.update_vm("web1", step="create")  # pretend the step change was lost
    provision.tick({})
    assert list(fake_pve.vms) == [700]


def test_create_tags_after_joining_pool(anon, fake_pve):
    """Proxmox won't take tags in the create call from a pool-scoped token, so they come after."""
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    assert fake_pve.vms[700]["tags"] == "homecloud"


def test_create_finishes_after_stopping_before_tags(anon, fake_pve):
    """The VM exists, in the pool but untagged (the pod died between the two calls)."""
    fake_pve.finish, real_finish = (lambda *a: (_ for _ in ()).throw(RuntimeError("pod died"))), fake_pve.finish
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    assert fake_pve.vms[700]["tags"] == "" and db.get_vm("web1")["state"] == "failed"
    # Deleting it still works: it's in the homecloud pool.
    db.update_vm("web1", state="deleting")
    provision.tick({})
    assert db.get_vm("web1") is None and fake_pve.vms == {}

    fake_pve.finish = real_finish
    db.add_vm("web2", "ubuntu", 2, 4096, 40)
    fake_pve.vms[700] = {"name": "web2", "status": "stopped", "tags": "", "pool": "homecloud", "cds": {}}
    db.update_vm("web2", vmid=700)
    provision.tick({})  # exists already: just finishes it
    assert fake_pve.vms[700]["tags"] == "homecloud" and db.get_vm("web2")["step"] == "start"


def test_vmids_skip_taken(anon, fake_pve):
    fake_pve.vms[700] = {"name": "other", "status": "running", "tags": ""}
    db.add_vm("web1", "ubuntu", 1, 2048, 20)
    provision.tick({})
    assert db.get_vm("web1")["vmid"] == 701


def test_delete(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    run_until_settled(fake_pve, 2)
    db.update_vm("web1", state="deleting")
    provision.tick({})
    assert db.get_vm("web1") is None
    assert fake_pve.vms == {}


def test_delete_mid_create_wins(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    db.update_vm("web1", state="deleting")
    provision.tick({})
    assert db.get_vm("web1") is None and fake_pve.vms == {}


def test_never_deletes_untagged_vm(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    # Someone else's VM got this id somehow: not tagged, not in the pool.
    fake_pve.vms[700].update(tags="", pool=None)
    db.update_vm("web1", state="deleting")
    provision.tick({})
    assert 700 in fake_pve.vms
    assert "refusing" in db.get_vm("web1")["error"]


def test_failure_is_recorded(anon, fake_pve, monkeypatch):
    def boom(*a):
        raise RuntimeError("no space left")
    monkeypatch.setattr(fake_pve, "create_ubuntu", boom)
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    vm = db.get_vm("web1")
    assert vm["state"] == "failed" and "no space left" in vm["error"]


def test_log_tells_the_story(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    for _ in range(3):
        provision.tick({})  # create, start, wait (no IP yet)
    fake_pve.agent_ip = "10.0.4.77"
    provision.tick({})  # wait: IP
    provision.tick({})  # cleanup
    text = "\n".join(e["message"] for e in db.events("web1"))
    for expected in ("Reserved VM ID 700", "Creating VM 700", "Powering on", "Waiting for the guest agent",
                     "Guest agent reports 10.0.4.77", "Ejecting", "Ready"):
        assert expected in text
    assert db.list_vms()[0]["last_event"].startswith("Ready")


def test_failed_task_log_is_kept(anon, fake_pve):
    """When a Proxmox task fails, the end of its own log (usually the real reason) is saved too."""
    def broken(*args):
        raise PveError("Proxmox task failed: unable to create VM 700", log=["line 1", "TASK ERROR: no space"])

    fake_pve.create_ubuntu = broken
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    events = db.events("web1")
    assert db.get_vm("web1")["state"] == "failed"
    assert events[-2]["level"] == "error" and "unable to create VM 700" in events[-2]["message"]
    assert "TASK ERROR: no space" in events[-1]["message"]


def test_failed_delete_logged_once(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})
    fake_pve.destroy = lambda vmid: (_ for _ in ()).throw(RuntimeError("403 Forbidden"))
    db.update_vm("web1", state="deleting")
    for _ in range(3):
        provision.tick({})
    assert sum("Delete failed" in e["message"] for e in db.events("web1")) == 1
