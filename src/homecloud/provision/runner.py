"""Run the catalog roles against one instance with ansible-runner.

Each run gets a throwaway private data dir holding a one-host inventory and a
generated playbook. Ansible's event stream is translated into job log lines,
so the console's job drawer shows each task as it runs.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import ansible_runner
import yaml

from homecloud.config import settings
from homecloud.jobs import JobCancelled
from homecloud.provision.catalog import ROLES_DIR
from homecloud.provision.keys import controller_key_path

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]


class ProvisionError(RuntimeError):
    pass


def _noop_log(_level: str, _message: str) -> None:
    pass


def build_playbook(roles: list[dict]) -> list[dict]:
    """One play, every selected role in catalog order with its own vars."""
    return [
        {
            "name": "homecloud provision",
            "hosts": "all",
            "become": True,
            "gather_facts": True,
            "roles": [{"role": r["id"], "vars": r["vars"]} for r in roles],
        }
    ]


def _result_message(res: dict) -> str:
    for key in ("msg", "stderr", "stdout"):
        value = res.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return ""


def run_roles(
    host: str,
    roles: list[dict],
    *,
    hostname: str,
    log: LogFn | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Apply *roles* (already resolved by ``catalog.resolve_roles``) to *host*.

    Raises ``JobCancelled`` when *cancel_check* fires mid-run and
    ``ProvisionError`` naming the failing task otherwise.
    """
    emit = log or _noop_log
    failures: list[str] = []

    def on_event(event: dict) -> bool:
        kind = event.get("event", "")
        data = event.get("event_data") or {}
        task = data.get("task", "")
        if kind == "playbook_on_task_start":
            emit("info", f"▸ {task}")
        elif kind == "runner_on_ok" and data.get("res", {}).get("changed"):
            emit("info", f"  changed: {task}")
        elif kind == "runner_on_failed" and not data.get("ignore_errors"):
            detail = _result_message(data.get("res") or {})
            failures.append(f"{task}: {detail}" if detail else task)
            emit("error", f"  failed: {task}{f' — {detail}' if detail else ''}")
        elif kind == "runner_on_unreachable":
            detail = _result_message(data.get("res") or {})
            failures.append(f"host unreachable: {detail}")
            emit("error", f"  unreachable: {detail}")
        elif kind == "playbook_on_stats":
            emit("info", "Ansible run finished")
        return True

    cancelled = False

    def should_cancel() -> bool:
        nonlocal cancelled
        if cancel_check is not None and cancel_check():
            cancelled = True
        return cancelled

    private_dir = Path(tempfile.mkdtemp(prefix="homecloud-ansible-"))
    try:
        project = private_dir / "project"
        project.mkdir()
        (project / "site.yml").write_text(yaml.safe_dump(build_playbook(roles), sort_keys=False))

        inventory = {
            "all": {
                "hosts": {
                    hostname: {
                        "ansible_host": host,
                        "ansible_user": settings.vm_ssh_user,
                        "ansible_ssh_private_key_file": str(controller_key_path()),
                        "ansible_python_interpreter": "auto_silent",
                    }
                }
            }
        }
        extravars = {
            "homecloud_hostname": hostname,
            "homecloud_user": settings.vm_ssh_user,
            "tailscale_auth_key": settings.tailscale_auth_key,
        }
        result = ansible_runner.run(
            private_data_dir=str(private_dir),
            playbook="site.yml",
            inventory=inventory,
            extravars=extravars,
            roles_path=[str(ROLES_DIR)],
            envvars={
                "ANSIBLE_HOST_KEY_CHECKING": "False",
                "ANSIBLE_PIPELINING": "True",
                "ANSIBLE_SSH_ARGS": "-o ControlMaster=auto -o ControlPersist=60s "
                "-o UserKnownHostsFile=/dev/null",
            },
            event_handler=on_event,
            cancel_callback=should_cancel,
            quiet=True,
        )
    finally:
        # The extravars file holds the Tailscale auth key.
        shutil.rmtree(private_dir, ignore_errors=True)

    if cancelled:
        raise JobCancelled("Provisioning cancelled by user")
    if result.status != "successful" or result.rc != 0:
        reason = failures[0] if failures else f"ansible exited {result.rc} ({result.status})"
        raise ProvisionError(f"Provisioning failed — {reason}")
