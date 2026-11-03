"""Postgres: the VMs homecloud made, and sign-in sessions. Nothing else is kept.

A VM's row is the source of truth for what homecloud is doing with it:

  state      creating -> ready, or failed; deleting until the row is removed
  step       within creating: which step comes next (see provision.py)
  vmid       reserved before the VM is created, so a restart mid-create finds it again

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
    with conn() as c:
        return c.execute(f"SELECT {VM_FIELDS} FROM vms ORDER BY created_at").fetchall()


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
