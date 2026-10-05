import pytest
import yaml

from homecloud.images.base import (
    BaseImageError,
    bake_user_data,
    import_filename,
    parse_extra_user_data,
    template_name,
)
from homecloud.images.deployer import instance_user_data
from homecloud.provision.script import AUTHKEY_PATH, SCRIPT_PATH, run_command

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample user@mac"
URL = (
    "https://cloud-images.ubuntu.com/releases/resolute/release-20260927/"
    "ubuntu-26.04-server-cloudimg-amd64.img"
)


def _load(user_data: str) -> dict:
    assert user_data.startswith("#cloud-config\n")
    return yaml.safe_load(user_data)


def test_bake_user_data_has_agent_tailscale_keys_and_packages():
    doc = _load(bake_user_data(ssh_keys=[KEY], packages=["tmux", "qemu-guest-agent"]))
    assert doc["ssh_authorized_keys"] == [KEY]
    assert doc["packages"] == ["qemu-guest-agent", "tmux"]
    runcmd = [" ".join(c) for c in doc["runcmd"]]
    assert "systemctl enable --now qemu-guest-agent" in runcmd
    assert any("tailscale.com/install.sh" in c for c in runcmd)
    assert not any("tailscale up" in c for c in runcmd)


def test_extra_user_data_merges_lists_and_overrides_scalars():
    extra = "packages: [jq]\nruncmd:\n  - echo hi\ntimezone: America/Chicago\n"
    doc = _load(bake_user_data(ssh_keys=[KEY], packages=[], extra_user_data=extra))
    assert doc["packages"] == ["qemu-guest-agent", "jq"]
    assert doc["runcmd"][-1] == "echo hi"
    assert doc["timezone"] == "America/Chicago"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- not\n- a mapping\n", "mapping"),
        ("users: []\n", "may not set"),
        ("packages: jq\n", "must be a list"),
        ("a: [unclosed\n", "not valid YAML"),
    ],
)
def test_bad_extra_user_data_is_rejected(text, message):
    with pytest.raises(BaseImageError, match=message):
        parse_extra_user_data(text)


def test_blank_extra_user_data_is_empty():
    assert parse_extra_user_data("  \n") == {}


def test_import_filename_keeps_release_serials_apart():
    assert import_filename(URL) == (
        "homecloud-release-20260927-ubuntu-26.04-server-cloudimg-amd64.qcow2"
    )
    with pytest.raises(BaseImageError):
        import_filename("https://example.com/image.iso")


def test_template_name():
    assert template_name(3) == "homecloud-base-v3"


def test_instance_user_data_carries_script_key_and_runs_it():
    doc = _load(
        instance_user_data(hostname="pixie", ssh_keys=[KEY], script="#!/bin/bash\n", auth_key="k")
    )
    assert doc["hostname"] == "pixie"
    assert doc["ssh_authorized_keys"] == [KEY]
    files = {f["path"]: f for f in doc["write_files"]}
    assert files[SCRIPT_PATH]["permissions"] == "0700"
    assert files[AUTHKEY_PATH] == {"path": AUTHKEY_PATH, "permissions": "0600", "content": "k"}
    assert doc["runcmd"] == [run_command()]
