"""Postgres: the VMs homecloud made, each one's log, and sign-in sessions.

A VM's row is the source of truth for what homecloud is doing with it:

  state      creating -> ready, or failed; deleting until the row is removed
  step       within creating: which step comes next (see provision.py)
  vmid       reserved before the VM is created, so a restart mid-create finds it again

A VM's log (vm_events) is what the worker did and when, for the Log panel in the UI. It goes
when the VM's row goes.

Live facts (running or stopped, uptime) are always read from Proxmox, never stored.
"""

from contextlib import contextmanager
from functools import cache

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS vms (
    name         text PRIMARY KEY,
    os           text NOT NULL CHECK (os IN ('ubuntu', 'windows')),
    cores        int  NOT NULL,
    memory_mb    int  NOT NULL,
    disk_gb      int  NOT NULL,
    vmid         int  UNIQUE,
    state        text NOT NULL DEFAULT 'creating'
                 CHECK (state IN ('creating', 'ready', 'failed', 'deleting')),
    step         text NOT NULL DEFAULT 'create',
    step_started timestamptz NOT NULL DEFAULT now(),
    ip           text,
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vm_events (
    id      bigserial PRIMARY KEY,
    vm      text NOT NULL REFERENCES vms (name) ON DELETE CASCADE,
    at      timestamptz NOT NULL DEFAULT now(),
    level   text NOT NULL DEFAULT 'info' CHECK (level IN ('info', 'warn', 'error')),
    message text NOT NULL
);
CREATE INDEX IF NOT EXISTS vm_events_vm_id ON vm_events (vm, id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash text PRIMARY KEY,
    expires    timestamptz NOT NULL
);
"""

VM_FIELDS = "name, os, cores, memory_mb, disk_gb, vmid, state, step, step_started, ip, error, created_at"


@cache
def pool() -> ConnectionPool:
    return ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, open=True,
                          kwargs={"row_factory": dict_row})


@contextmanager
def conn():
    """A connection in a transaction that commits when the block ends (rolls back on error)."""
    with pool().connection() as c:
        yield c


def init_schema() -> None:
    with conn() as c:
        c.execute(SCHEMA)


def ping() -> None:
    with conn() as c:
        c.execute("SELECT 1")


# ---------- vms ----------

class Exists(Exception):
    pass


def list_vms() -> list[dict]:
    """Every VM, each with its latest log line (last_event, last_level)."""
    fields = ", ".join(f"v.{f.strip()}" for f in VM_FIELDS.split(","))
    with conn() as c:
        return c.execute(
            f"SELECT {fields}, e.message AS last_event, e.level AS last_level FROM vms v "
            "LEFT JOIN LATERAL (SELECT message, level FROM vm_events WHERE vm = v.name "
            "ORDER BY id DESC LIMIT 1) e ON true ORDER BY v.created_at").fetchall()


def get_vm(name: str) -> dict | None:
    with conn() as c:
        return c.execute(f"SELECT {VM_FIELDS} FROM vms WHERE name = %s", (name,)).fetchone()


def add_vm(name: str, os: str, cores: int, memory_mb: int, disk_gb: int) -> None:
    with conn() as c:
        r = c.execute("INSERT INTO vms (name, os, cores, memory_mb, disk_gb) VALUES (%s, %s, %s, %s, %s) "
                      "ON CONFLICT (name) DO NOTHING", (name, os, cores, memory_mb, disk_gb))
        if r.rowcount == 0:
            raise Exists(name)


def update_vm(name: str, only_if: str | None = None, **fields) -> bool:
    """Set some columns. Moving to a new step also restarts that step's clock.

    With only_if, only while the VM is in that state: the worker uses it so that a delete
    clicked mid-create isn't overwritten by the create finishing.
    """
    cols = ", ".join(f"{k} = %({k})s" for k in fields)
    if "step" in fields or "state" in fields:
        cols += ", step_started = now()"
    where = "name = %(name)s" + (" AND state = %(only_if)s" if only_if else "")
    with conn() as c:
        r = c.execute(f"UPDATE vms SET {cols} WHERE {where}", {**fields, "name": name, "only_if": only_if})
        return r.rowcount > 0


def delete_vm_row(name: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM vms WHERE name = %s", (name,))


def vms_in(*states: str) -> list[dict]:
    with conn() as c:
        return c.execute(f"SELECT {VM_FIELDS} FROM vms WHERE state = ANY(%s) ORDER BY created_at",
                         (list(states),)).fetchall()


def used_vmids() -> set[int]:
    with conn() as c:
        return {r["vmid"] for r in c.execute("SELECT vmid FROM vms WHERE vmid IS NOT NULL")}


# ---------- the log ----------

def add_event(name: str, message: str, level: str = "info") -> None:
    """Append to a VM's log. Quietly does nothing if the VM's row is already gone."""
    with conn() as c:
        c.execute("INSERT INTO vm_events (vm, level, message) SELECT name, %s, %s FROM vms WHERE name = %s",
                  (level, message, name))


def events(name: str, after: int = 0, limit: int = 500) -> list[dict]:
    """A VM's log, oldest first: the newest *limit* entries with an id above *after*."""
    with conn() as c:
        return c.execute("SELECT id, at, level, message FROM (SELECT * FROM vm_events WHERE vm = %s AND id > %s "
                         "ORDER BY id DESC LIMIT %s) e ORDER BY id", (name, after, limit)).fetchall()
