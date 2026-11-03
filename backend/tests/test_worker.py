from app import db, provision


def run_until_settled(fake_pve, ticks=10):
    for _ in range(ticks):
        provision.tick({})


def test_ubuntu_goes_to_ready(anon, fake_pve):
    db.add_vm("web1", "ubuntu", 2, 4096, 40)
    provision.tick({})  # create
    vm = db.get_vm("web1")
    assert vm["vmid"] == 700 and vm["step"] == "start"
    assert fake_pve.isos == {"local:iso/homecloud-700-seed.iso"}

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
    fake_pve.vms[700]["tags"] = ""  # someone else's VM got this id somehow
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
