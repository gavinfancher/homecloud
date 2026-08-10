"""Custom image definitions: cloud-init composition, validation, and CRUD.

The CRUD half needs Postgres and is skipped unless TEST_DATABASE_URL is set
(CI and `make test-db` provide one; see tests/README.md).
"""

from __future__ import annotations

import os

import pytest
import yaml
from pydantic import ValidationError

from homecloud.api.schemas import CloudImageRequest, ConfigFileSpec, CustomImageRequest
from homecloud.images.builder import _cloud_init_error_detail
from homecloud.images.catalog import BUILTIN_CATALOG
from homecloud.images.composer import (
    BOOTSTRAP_DONE_MARKER,
    compose_cloud_init,
    normalize_config_file,
)

# ---------------------------------------------------------------------------
# composer — cloud-init generation
# ---------------------------------------------------------------------------


def _compose(**overrides):
    kwargs = {
        "hostname": "tpl-web",
        "ssh_user": "ubuntu",
        "ssh_public_keys": ["ssh-ed25519 AAAAC3Nza test@host"],
    }
    kwargs.update(overrides)
    return compose_cloud_init(**kwargs)


def test_cloud_init_starts_with_the_cloud_config_header():
    assert _compose().startswith("#cloud-config\n")


def test_cloud_init_is_valid_yaml():
    assert isinstance(yaml.safe_load(_compose()), dict)


def test_guest_agent_is_never_in_the_packages_list():
    """cloud-init installs `packages:` in one call, so a bad user package there
    would take the agent down with it and strand the build."""
    doc = yaml.safe_load(_compose(packages=["nginx"]))
    assert "qemu-guest-agent" not in doc.get("packages", [])


def test_guest_agent_is_installed_first_from_runcmd():
    doc = yaml.safe_load(_compose(packages=["nginx"], run_commands=["echo hi"]))
    first = doc["runcmd"][0]
    assert first[0] == "bash"
    assert "qemu-guest-agent" in first[2]
    assert "systemctl enable --now qemu-guest-agent" in first[2]


def test_agent_bootstrap_covers_apt_and_dnf_distros():
    script = yaml.safe_load(_compose())["runcmd"][0][2]
    assert "apt-get install -y qemu-guest-agent" in script
    assert "dnf install -y qemu-guest-agent" in script


def test_user_packages_are_passed_through_in_order():
    doc = yaml.safe_load(_compose(packages=["nginx", "htop"]))
    assert doc["packages"] == ["nginx", "htop"]


def test_duplicate_packages_are_collapsed():
    doc = yaml.safe_load(_compose(packages=["nginx", "nginx", "htop"]))
    assert doc["packages"] == ["nginx", "htop"]


def test_blank_packages_are_dropped():
    doc = yaml.safe_load(_compose(packages=["nginx", "  ", ""]))
    assert doc["packages"] == ["nginx"]


def test_no_packages_key_when_none_requested():
    assert "packages" not in yaml.safe_load(_compose())


def test_config_files_become_write_files():
    doc = yaml.safe_load(
        _compose(
            config_files=[
                {"path": "/etc/app.toml", "content": "key = 1\n", "permissions": "0600"}
            ]
        )
    )
    assert doc["write_files"] == [
        {"path": "/etc/app.toml", "content": "key = 1\n", "permissions": "0600"}
    ]


def test_write_files_survives_yaml_hostile_content():
    """Colons, quotes, tabs, and blank lines must round-trip byte for byte."""
    content = 'a: "b"\n\tindented\n\n#comment: yes\n- item\n'
    doc = yaml.safe_load(_compose(config_files=[{"path": "/etc/tricky.conf", "content": content}]))
    assert doc["write_files"][0]["content"] == content


def test_no_write_files_key_when_no_config_files():
    assert "write_files" not in yaml.safe_load(_compose())


def test_run_commands_land_between_agent_setup_and_the_done_marker():
    doc = yaml.safe_load(_compose(run_commands=["echo hi", "systemctl restart nginx"]))
    runcmd = doc["runcmd"]
    assert runcmd.index("echo hi") == 1
    assert runcmd.index("systemctl restart nginx") < runcmd.index(
        ["touch", BOOTSTRAP_DONE_MARKER]
    )


def test_done_marker_is_the_final_command():
    """The builder waits on this file, so nothing may run after it."""
    doc = yaml.safe_load(_compose(run_commands=["echo hi"]))
    assert doc["runcmd"][-1] == ["touch", BOOTSTRAP_DONE_MARKER]


def test_ssh_user_gets_passwordless_sudo_and_the_keys():
    key = "ssh-ed25519 AAAAC3Nza test@host"
    doc = yaml.safe_load(_compose(ssh_user="gavin", ssh_public_keys=[key]))
    user = doc["users"][0]
    assert user["name"] == "gavin"
    assert user["sudo"] == "ALL=(ALL) NOPASSWD:ALL"
    assert user["ssh_authorized_keys"] == [key]


def test_normalize_config_file_rejects_relative_paths():
    with pytest.raises(ValueError, match="absolute"):
        normalize_config_file({"path": "etc/app.conf", "content": ""})


def test_normalize_config_file_rejects_missing_path():
    with pytest.raises(ValueError, match="need a path"):
        normalize_config_file({"content": "x"})


def test_normalize_config_file_omits_unset_optionals():
    assert normalize_config_file({"path": "/etc/a", "content": "x"}) == {
        "path": "/etc/a",
        "content": "x",
    }


# ---------------------------------------------------------------------------
# builder — reading cloud-init's verdict
# ---------------------------------------------------------------------------

# Verbatim from a build that requested `nvim` (which does not exist on Debian).
REAL_PACKAGE_FAILURE = (
    "status: error\n"
    "boot_status_code: enabled-by-generator\n"
    "last_update: Mon, 10 Aug 2026 16:33:29 +0000\n"
    "detail:\n"
    "('package-update-upgrade-install', ProcessExecutionError(\"Unexpected error while "
    "running command.\\nCommand: ['apt-get', '--option=Dpkg::Options::=--force-confold', "
    "'--assume-yes', '--quiet', 'install', 'qemu-guest-agent', 'nvim', 'btop']\\n"
    "Exit code: 100\\nReason: -\\nStdout: -\\nStderr: -\"))"
)


def test_package_failure_names_the_packages_that_were_attempted():
    detail = _cloud_init_error_detail(REAL_PACKAGE_FAILURE)
    assert "nvim" in detail
    assert "btop" in detail


def test_package_failure_explains_the_all_or_nothing_install():
    detail = _cloud_init_error_detail(REAL_PACKAGE_FAILURE)
    assert "one command" in detail
    assert "neovim" in detail, "should point at the actual Debian package name"


def test_unrecognised_failure_falls_back_to_the_raw_detail():
    output = "status: error\ndetail:\n('something-else', RuntimeError('disk full'))"
    assert "disk full" in _cloud_init_error_detail(output)


def test_error_detail_is_bounded():
    output = "status: error\ndetail:\n" + ("x" * 5000)
    assert len(_cloud_init_error_detail(output)) <= 400


# ---------------------------------------------------------------------------
# wait_for_guest_file — cancellation
# ---------------------------------------------------------------------------


class _FakeProxmox:
    """Guest that never produces the marker, so the wait always polls."""

    def __init__(self):
        self.polls = 0

    def guest_run(self, vmid, command, timeout=30):
        self.polls += 1
        return {"exitcode": 1, "out": "", "err": ""}


def test_wait_for_guest_file_aborts_when_cancelled():
    """Without this the console's Cancel button does nothing for ~30 minutes."""
    from homecloud.jobs import JobCancelled
    from homecloud.proxmox.client import ProxmoxClient

    fake = _FakeProxmox()

    def check_cancel():
        raise JobCancelled("cancelled by user")

    with pytest.raises(JobCancelled):
        ProxmoxClient.wait_for_guest_file(
            fake, 8001, "/var/lib/homecloud/image-build.done", check_cancel=check_cancel
        )
    assert fake.polls == 0, "must bail out before polling the guest"


def test_wait_for_guest_file_returns_once_the_marker_exists():
    from homecloud.proxmox.client import ProxmoxClient

    class _Ready(_FakeProxmox):
        def guest_run(self, vmid, command, timeout=30):
            self.polls += 1
            return {"exitcode": 0, "out": "", "err": ""}

    ready = _Ready()
    ProxmoxClient.wait_for_guest_file(ready, 8001, "/marker", timeout=10)
    assert ready.polls == 1


# ---------------------------------------------------------------------------
# schemas — request validation
# ---------------------------------------------------------------------------


def _image_body(**overrides):
    body = {"id": "web-node", "name": "Web Node", "cloud_image_id": "ubuntu-24.04"}
    body.update(overrides)
    return body


def test_custom_image_request_defaults():
    req = CustomImageRequest(**_image_body())
    assert req.packages == []
    assert req.config_files == []
    assert (req.default_cores, req.default_memory_mb, req.default_disk_gb) == (2, 2048, 10)


@pytest.mark.parametrize("bad_id", ["Web", "1web", "w", "web_node", "web node", ""])
def test_custom_image_request_rejects_bad_ids(bad_id):
    with pytest.raises(ValidationError):
        CustomImageRequest(**_image_body(id=bad_id))


def test_custom_image_request_strips_blank_packages():
    req = CustomImageRequest(**_image_body(packages=["nginx", "", "  ", "htop"]))
    assert req.packages == ["nginx", "htop"]


@pytest.mark.parametrize("bad_pkg", ["nginx; rm -rf /", "$(whoami)", "a b", "-flag"])
def test_custom_image_request_rejects_shell_metacharacters_in_packages(bad_pkg):
    with pytest.raises(ValidationError):
        CustomImageRequest(**_image_body(packages=[bad_pkg]))


def test_config_file_spec_rejects_relative_path():
    with pytest.raises(ValidationError):
        ConfigFileSpec(path="etc/app.conf")


@pytest.mark.parametrize("mode", ["0644", "644", "0600"])
def test_config_file_spec_accepts_octal_modes(mode):
    assert ConfigFileSpec(path="/etc/a", permissions=mode).permissions == mode


@pytest.mark.parametrize("mode", ["rw-r--r--", "0999", "64", "06444"])
def test_config_file_spec_rejects_non_octal_modes(mode):
    with pytest.raises(ValidationError):
        ConfigFileSpec(path="/etc/a", permissions=mode)


def test_config_file_spec_treats_empty_permissions_as_unset():
    assert ConfigFileSpec(path="/etc/a", permissions="").permissions is None


def test_cloud_image_request_requires_http_url():
    with pytest.raises(ValidationError):
        CloudImageRequest(
            id="alpine-3", name="Alpine", distro="alpine", version="3", url="ftp://x/y.img"
        )


def test_cloud_image_request_rejects_malformed_sha256():
    with pytest.raises(ValidationError):
        CloudImageRequest(
            id="alpine-3",
            name="Alpine",
            distro="alpine",
            version="3",
            url="https://x/y.img",
            sha256="deadbeef",
        )


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------


def test_catalog_ids_are_unique():
    ids = [e.id for e in BUILTIN_CATALOG]
    assert len(ids) == len(set(ids))


def test_catalog_urls_are_direct_image_downloads():
    for entry in BUILTIN_CATALOG:
        assert entry.url.startswith("https://"), entry.id
        assert entry.url.endswith((".img", ".qcow2")), entry.id


def test_catalog_has_an_ubuntu_lts_default():
    assert any(e.id == "ubuntu-24.04" for e in BUILTIN_CATALOG)


# ---------------------------------------------------------------------------
# store — CRUD against a real Postgres
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to run image store tests"
)


@pytest.fixture
def store(monkeypatch):
    """Image store bound to a freshly created schema in the test database."""
    from homecloud.config import settings
    from homecloud.db import models
    from homecloud.db import session as db_session
    from homecloud.images import store as image_store

    monkeypatch.setattr(settings, "database_url", TEST_DATABASE_URL)
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_Session", None)

    engine = db_session.get_engine()
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    with db_session.session_scope() as session:
        from homecloud.images.catalog import seed_catalog

        seed_catalog(session)

    yield image_store

    models.Base.metadata.drop_all(engine)
    engine.dispose()
    db_session._engine = None
    db_session._Session = None


@requires_db
def test_catalog_is_seeded_on_init(store):
    ids = {img["id"] for img in store.list_cloud_images()}
    assert {e.id for e in BUILTIN_CATALOG} <= ids


@requires_db
def test_seeding_twice_does_not_duplicate(store):
    from homecloud.db.session import session_scope
    from homecloud.images.catalog import seed_catalog

    with session_scope() as session:
        assert seed_catalog(session) == 0


@requires_db
def test_create_and_read_back_a_custom_image(store):
    created = store.create_custom_image(
        {
            "id": "web-node",
            "name": "Web Node",
            "description": "nginx box",
            "cloud_image_id": "ubuntu-24.04",
            "packages": ["nginx"],
            "config_files": [{"path": "/etc/app.conf", "content": "x"}],
            "run_commands": ["systemctl enable nginx"],
        }
    )
    assert created["status"] == "draft"
    assert created["built"] is False

    fetched = store.get_custom_image("web-node")
    assert fetched["packages"] == ["nginx"]
    assert fetched["config_files"] == [{"path": "/etc/app.conf", "content": "x"}]


@requires_db
def test_duplicate_id_conflicts(store):
    payload = {"id": "web-node", "name": "Web", "cloud_image_id": "ubuntu-24.04"}
    store.create_custom_image(payload)
    with pytest.raises(store.ImageConflict):
        store.create_custom_image(payload)


@requires_db
def test_unknown_cloud_image_is_rejected(store):
    with pytest.raises(store.ImageNotFound):
        store.create_custom_image(
            {"id": "web-node", "name": "Web", "cloud_image_id": "plan9-4"}
        )


@requires_db
def test_editing_packages_invalidates_an_existing_build(store):
    """A built template no longer matches the definition, so it drops to draft."""
    from homecloud.db.models import BuildStatus, CustomImage
    from homecloud.db.session import session_scope

    store.create_custom_image({"id": "web", "name": "Web", "cloud_image_id": "ubuntu-24.04"})
    with session_scope() as session:
        image = session.get(CustomImage, "web")
        image.status = BuildStatus.BUILT
        image.template_id = 8001

    updated = store.update_custom_image("web", {"packages": ["nginx"]})
    assert updated["status"] == "draft"
    assert updated["built"] is False


@requires_db
def test_renaming_keeps_an_existing_build(store):
    from homecloud.db.models import BuildStatus, CustomImage
    from homecloud.db.session import session_scope

    store.create_custom_image({"id": "web", "name": "Web", "cloud_image_id": "ubuntu-24.04"})
    with session_scope() as session:
        image = session.get(CustomImage, "web")
        image.status = BuildStatus.BUILT
        image.template_id = 8001

    updated = store.update_custom_image("web", {"name": "Web Server"})
    assert updated["status"] == "built"
    assert updated["template_id"] == 8001


@requires_db
def test_cannot_edit_or_delete_while_building(store):
    from homecloud.db.models import BuildStatus, CustomImage
    from homecloud.db.session import session_scope

    store.create_custom_image({"id": "web", "name": "Web", "cloud_image_id": "ubuntu-24.04"})
    with session_scope() as session:
        session.get(CustomImage, "web").status = BuildStatus.BUILDING

    with pytest.raises(store.ImageConflict):
        store.update_custom_image("web", {"name": "Nope"})
    with pytest.raises(store.ImageConflict):
        store.delete_custom_image("web")


@requires_db
def test_delete_removes_the_definition(store):
    store.create_custom_image({"id": "web", "name": "Web", "cloud_image_id": "ubuntu-24.04"})
    store.delete_custom_image("web")
    assert store.get_custom_image("web") is None


@requires_db
def test_builtin_cloud_images_cannot_be_deleted(store):
    with pytest.raises(store.ImageConflict):
        store.delete_cloud_image("ubuntu-24.04")


@requires_db
def test_cloud_image_in_use_cannot_be_deleted(store):
    store.create_cloud_image(
        {
            "id": "alpine-3",
            "name": "Alpine 3",
            "distro": "alpine",
            "version": "3",
            "url": "https://example.invalid/alpine.qcow2",
            "sha256": None,
            "ssh_user": "alpine",
            "arch": "amd64",
        }
    )
    store.create_custom_image({"id": "tiny", "name": "Tiny", "cloud_image_id": "alpine-3"})
    with pytest.raises(store.ImageConflict):
        store.delete_cloud_image("alpine-3")
