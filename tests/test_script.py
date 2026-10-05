import base64
import subprocess

from homecloud.provision.catalog import resolve_roles
from homecloud.provision.script import AUTHKEY_PATH, SCRIPT_PATH, render_script, run_command


def _render(selection):
    return render_script(resolve_roles(selection), user="ubuntu", hostname="pixie")


def test_script_is_valid_bash():
    script = _render(
        [
            {"id": "packages", "vars": {"packages": ["jq", "htop"]}},
            {"id": "docker"},
            {"id": "uv"},
            {
                "id": "files",
                "vars": {"files": [{"path": "/etc/app/x.env", "content": "A='1'\nEOF\n"}]},
            },
            {"id": "commands", "vars": {"commands": ["echo \"it's fine\""]}},
        ]
    )
    assert script.startswith("#!/bin/bash\n")
    assert "set -euo pipefail" in script
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)


def test_roles_render_in_catalog_order():
    script = _render([{"id": "commands", "vars": {"commands": ["true"]}}, {"id": "docker"}])
    order = [script.index(f"▸ {role}") for role in ("docker", "commands", "tailscale")]
    assert order == sorted(order)


def test_tailscale_joins_only_with_the_one_time_key():
    script = _render([{"id": "tailscale", "vars": {"tailscale_ssh": True}}])
    assert f"if [ -s {AUTHKEY_PATH} ]" in script
    assert f"--auth-key=file:{AUTHKEY_PATH} --hostname=pixie" in script
    assert f"rm -f {AUTHKEY_PATH}" in script
    assert "tailscale set --operator=ubuntu --auto-update=true --accept-routes=true --ssh=true" in (
        script
    )


def test_files_round_trip_through_base64():
    content = "line with 'quotes' and $VARS\nEOF\n"
    script = _render(
        [{"id": "files", "vars": {"files": [{"path": "/opt/a b/c", "content": content,
                                             "mode": "0600", "owner": "ubuntu:ubuntu"}]}}]
    )
    encoded = base64.b64encode(content.encode()).decode()
    assert f"printf %s {encoded} | base64 -d > '/opt/a b/c'" in script
    assert "mkdir -p '/opt/a b'" in script
    assert "chmod 0600 '/opt/a b/c'" in script
    assert "chown ubuntu:ubuntu '/opt/a b/c'" in script


def test_empty_package_list_renders_nothing():
    script = _render([{"id": "packages", "vars": {"packages": []}}])
    assert "apt-get" not in script


def test_run_command_logs_to_file():
    assert run_command() == [
        "bash",
        "-c",
        f"bash {SCRIPT_PATH} > /var/log/homecloud-provision.log 2>&1",
    ]
