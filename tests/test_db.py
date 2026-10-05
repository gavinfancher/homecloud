"""State, jobs, migrations and the legacy import against a real Postgres.

Skipped unless ``TEST_DATABASE_URL`` points at a disposable database — every
test starts by dropping and recreating the public schema.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text, update

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterialOnlyForTests user@mac"


@pytest.fixture
def db(settings, monkeypatch):
    from homecloud.db import session as db_session

    monkeypatch.setattr(settings, "database_url", TEST_DATABASE_URL)
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_Session", None)
    engine = db_session.get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    db_session.init_db()
    yield engine
    engine.dispose()


def test_migrate_is_idempotent_and_adopts_create_all_cloud_images(db):
    from homecloud.db.migrate import migrate

    assert migrate(db) == []
    # A database from before the runner: cloud_images exists, nothing recorded.
    with db.begin() as conn:
        conn.execute(text("DROP TABLE schema_migrations, ssh_keys, instances, job_logs, jobs"))
        conn.execute(text("CREATE TABLE custom_images (id text)"))
    assert migrate(db) == ["001_init"]
    with db.connect() as conn:
        tables = set(
            conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        )
        catalog = conn.scalar(text("SELECT count(*) FROM cloud_images"))
    assert "custom_images" not in tables
    assert {"instances", "jobs", "job_logs", "ssh_keys", "cloud_images"} <= tables
    assert catalog > 0


def test_ssh_keys_replace_and_setup(db):
    from homecloud import state

    assert not state.is_setup_complete()
    state.save_setup(ssh_public_keys=[KEY, KEY + "\n"])
    assert state.get_ssh_public_keys() == [KEY]
    assert state.is_setup_complete()
    with pytest.raises(ValueError):
        state.save_setup(ssh_public_keys=["not-a-key"])
    assert state.get_ssh_public_keys() == [KEY]


def test_instance_lifecycle(db):
    from homecloud import state

    state.register_vm(
        "pixie",
        {"vmid": 501, "name": "pixie", "tailscale_ip": "100.1.2.3", "memory_gb": 2.0, "cores": 2},
    )
    vm = state.get_instance("pixie")
    assert vm["vmid"] == 501
    assert vm["memory_mb"] == 2048 and vm["memory_gb"] == 2.0
    assert vm["ip"] == "100.1.2.3"
    assert vm["roles"] == [] and vm["ports_seen"] is None

    state.set_instance_local_ip("pixie", "10.0.0.55")
    # Partial update: only the given fields change.
    state.register_vm("pixie", {"roles": [{"id": "docker", "vars": {}}]})
    state.set_instance_ports("pixie", [{"port": 22}])
    state.set_instance_web_service(
        "pixie",
        service="app",
        port=80,
        public_host="app.pixie",
        public=False,
        cloudflare_record_id="",
        caddy_config="app.pixie.caddy",
    )
    state.set_instance_web_service(
        "pixie",
        service="app",
        port=8080,
        public_host="app.pixie",
        public=False,
        cloudflare_record_id="",
        caddy_config="app.pixie.caddy",
    )
    vm = state.list_registered_vms()["pixie"]
    assert vm["local_ip"] == "10.0.0.55"
    assert vm["roles"] == [{"id": "docker", "vars": {}}]
    assert vm["ports_seen"] == [{"port": 22}] and vm["ports_scanned_at"]
    assert [w["port"] for w in vm["web"]] == [8080]

    state.remove_instance_web_service("pixie", "app")
    assert state.get_instance("pixie")["web"] == []
    state.unregister_vm("pixie")
    assert state.get_instance("pixie") is None


def test_job_queue_claim_finish_and_cancel(db):
    from homecloud.jobs import JobStore

    store = JobStore()
    first = store.enqueue("deploy_vm", label="a", meta={"m": 1}, payload={"p": 1})
    second = store.enqueue("deploy_vm", label="b")
    assert first["status"] == "pending" and first["logs"] == []

    assert store.claim_next() == (first["id"], "deploy_vm", {"p": 1})
    store.log(first["id"], "hello")
    store.finish(first["id"], "completed", result={"ok": True})

    assert store.request_cancel(second["id"])  # pending → cancelled outright
    assert store.claim_next() is None
    assert not store.request_cancel(first["id"])  # already finished

    jobs = {j["id"]: j for j in store.list()}
    assert jobs[first["id"]]["status"] == "completed"
    assert jobs[first["id"]]["result"] == {"ok": True}
    assert [entry["message"] for entry in jobs[first["id"]]["logs"]] == ["hello"]
    assert jobs[second["id"]]["status"] == "cancelled"


def test_stale_running_job_is_failed(db):
    from homecloud.db.models import Job
    from homecloud.db.session import session_scope
    from homecloud.jobs import JobStore

    store = JobStore()
    job = store.enqueue("deploy_vm", label="orphan")
    store.claim_next()
    with session_scope() as session:
        session.execute(
            update(Job)
            .where(Job.id == job["id"])
            .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=5))
        )
    assert store.fail_stale() == 1
    got = store.get(job["id"])
    assert got["status"] == "failed" and "Interrupted" in got["error"]


def test_runner_runs_handlers(db):
    from homecloud.jobs import JobCancelled, JobRunner, JobStore

    def ok(ctx, payload):
        ctx.log("info", "working")
        return {"echo": payload["x"]}

    def boom(_ctx, _payload):
        raise RuntimeError("kaput")

    def cancelled(_ctx, _payload):
        raise JobCancelled("stopped by user")

    store = JobStore()
    runner = JobRunner(
        {"ok": ok, "boom": boom, "cancel": cancelled}, store=store, workers=2, poll_interval=0.1
    )
    runner.start()
    try:
        ids = {
            "ok": store.enqueue("ok", label="ok", payload={"x": 7})["id"],
            "boom": store.enqueue("boom", label="boom")["id"],
            "cancel": store.enqueue("cancel", label="cancel")["id"],
            "unknown": store.enqueue("nope", label="nope")["id"],
        }
        deadline = time.time() + 10
        while time.time() < deadline:
            if all(store.get(i)["status"] not in ("pending", "running") for i in ids.values()):
                break
            time.sleep(0.1)
    finally:
        runner.stop()

    assert store.get(ids["ok"])["status"] == "completed"
    assert store.get(ids["ok"])["result"] == {"echo": 7}
    assert store.get(ids["boom"])["error"] == "kaput"
    assert store.get(ids["cancel"])["status"] == "cancelled"
    assert store.get(ids["unknown"])["status"] == "failed"


def test_import_legacy_state_is_idempotent(db, tmp_path):
    from homecloud import state
    from homecloud.legacy import import_state

    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "setup_complete": True,
                "ssh_public_key": KEY,
                "ssh_public_keys": [KEY],
                "built_templates": {},
                "custom_templates": {},
                "vms": {
                    "pixie": {
                        "vmid": 501,
                        "name": "pixie",
                        "ip": "100.125.128.54",
                        "tailscale_ip": "100.125.128.54",
                        "local_ip": "10.0.0.55",
                        "hostname": "pixie.vm.homecloud.gavinf.com",
                        "size_id": "custom",
                        "cores": 2,
                        "memory_gb": 2.0,
                        "memory_mb": 2048,
                        "disk_gb": 50,
                        "image_id": "homecloud-base",
                    }
                },
            }
        )
    )
    first = import_state(path)
    assert first["instances_added"] == ["pixie"] and len(first["ssh_keys_added"]) == 1
    second = import_state(path)
    assert second == {"ssh_keys_added": [], "instances_added": [], "instances_skipped": ["pixie"]}

    vm = state.get_instance("pixie")
    assert vm["source_id"] is None and vm["roles"] == []
    assert vm["tailscale_ip"] == "100.125.128.54" and vm["disk_gb"] == 50
    assert state.get_ssh_public_keys() == [KEY]
