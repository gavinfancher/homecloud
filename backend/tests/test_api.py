from app import auth, db
from tests.conftest import PASSWORD

UBUNTU = {"name": "web1", "os": "ubuntu", "cores": 2, "memory_gb": 4, "disk_gb": 40}


def test_health_needs_no_login(anon):
    assert anon.get("/healthz").json() == {"status": "ok"}
    assert anon.get("/readyz").json() == {"status": "ready"}


def test_api_needs_login(anon):
    assert anon.get("/api/vms").status_code == 401
    assert anon.get("/api/vms", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert anon.get("/api/session").json() == {"signed_in": False}


def test_wrong_password_then_throttle(anon):
    for _ in range(auth.MAX_FAILURES):
        assert anon.post("/api/login", json={"password": "nope"}).status_code == 401
    # Even the right password is refused while throttled.
    assert anon.post("/api/login", json={"password": PASSWORD}).status_code == 429


def test_logout_ends_session(client):
    assert client.get("/api/session").json() == {"signed_in": True}
    client.post("/api/logout")
    assert client.get("/api/vms").status_code == 401


def test_create_and_list(client, fake_pve):
    r = client.post("/api/vms", json=UBUNTU)
    assert r.status_code == 201, r.text
    vms = client.get("/api/vms").json()["vms"]
    assert [(v["name"], v["state"], v["memory_gb"]) for v in vms] == [("web1", "creating", 4)]
    assert client.post("/api/vms", json=UBUNTU).status_code == 409


def test_validation(client, fake_pve):
    bad = [
        {**UBUNTU, "name": "Has Spaces"},
        {**UBUNTU, "name": "a-name-thats-too-long"},
        {**UBUNTU, "name": "ends-"},
        {**UBUNTU, "os": "debian"},
        {**UBUNTU, "cores": 0},
        {**UBUNTU, "memory_gb": 999},
        {**UBUNTU, "os": "windows", "disk_gb": 40},  # Windows needs 64
        {**UBUNTU, "os": "windows", "memory_gb": 2},  # and 4 GB
    ]
    for body in bad:
        assert client.post("/api/vms", json=body).status_code == 400, body


def test_delete_marks_for_worker(client, fake_pve):
    client.post("/api/vms", json=UBUNTU)
    assert client.delete("/api/vms/web1").status_code == 202
    assert db.get_vm("web1")["state"] == "deleting"
    assert client.delete("/api/vms/nope").status_code == 404


def test_power_only_when_ready(client, fake_pve):
    client.post("/api/vms", json=UBUNTU)
    assert client.post("/api/vms/web1/start").status_code == 409
