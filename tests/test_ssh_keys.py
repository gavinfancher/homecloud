"""Unit tests for Phase 07 — SSH key management (multi-key support).

Tests cover:
- save_setup / get_ssh_public_key / get_ssh_public_keys (state.py)
- SetupRequest schema normalization (schemas.py)
- Cloud-init template rendering with one and many keys
- Back-compat: old single-key state files still work
"""
from __future__ import annotations

import json

import pytest

import homecloud.state as state_module
from homecloud.images.cloud_init import render_cloud_init


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KEY_ED = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyOne user@host"
KEY_RSA = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC example-rsa-key user2@host"
KEY_ECDSA = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBB example user3@host"
KEY_BAD = "not-a-valid-key AAAA garbage"


@pytest.fixture()
def state_file(tmp_path, monkeypatch):
    """Redirect STATE_FILE to a fresh temp path; return the Path."""
    sf = tmp_path / ".homecloud" / "state.json"
    monkeypatch.setattr(state_module, "STATE_FILE", sf)
    return sf


# ---------------------------------------------------------------------------
# save_setup — single key (legacy path)
# ---------------------------------------------------------------------------


def test_save_setup_single_key_stores_correctly(state_file):
    state_module.save_setup(ssh_public_key=KEY_ED)
    assert state_module.get_ssh_public_key() == KEY_ED
    assert state_module.get_ssh_public_keys() == [KEY_ED]
    assert state_module.is_setup_complete()


def test_save_setup_single_key_kwarg_ssh_public_keys(state_file):
    state_module.save_setup(ssh_public_keys=[KEY_ED])
    assert state_module.get_ssh_public_key() == KEY_ED
    assert state_module.get_ssh_public_keys() == [KEY_ED]


def test_save_setup_rsa_key_accepted(state_file):
    state_module.save_setup(ssh_public_key=KEY_RSA)
    assert state_module.get_ssh_public_key() == KEY_RSA


def test_save_setup_ecdsa_key_accepted(state_file):
    state_module.save_setup(ssh_public_key=KEY_ECDSA)
    assert state_module.get_ssh_public_key() == KEY_ECDSA


def test_save_setup_invalid_key_raises(state_file):
    with pytest.raises(ValueError, match="Invalid SSH public key"):
        state_module.save_setup(ssh_public_key=KEY_BAD)


def test_save_setup_no_key_raises(state_file):
    with pytest.raises(ValueError, match="required"):
        state_module.save_setup()


# ---------------------------------------------------------------------------
# save_setup — multiple keys
# ---------------------------------------------------------------------------


def test_save_setup_multiple_keys_stores_all(state_file):
    state_module.save_setup(ssh_public_keys=[KEY_ED, KEY_RSA])
    keys = state_module.get_ssh_public_keys()
    assert keys == [KEY_ED, KEY_RSA]


def test_save_setup_multiple_keys_first_is_compat_key(state_file):
    state_module.save_setup(ssh_public_keys=[KEY_ED, KEY_RSA])
    assert state_module.get_ssh_public_key() == KEY_ED


def test_save_setup_deduplicates(state_file):
    state_module.save_setup(ssh_public_keys=[KEY_ED, KEY_RSA, KEY_ED])
    keys = state_module.get_ssh_public_keys()
    assert keys == [KEY_ED, KEY_RSA]
    assert len(keys) == 2


def test_save_setup_dedup_across_single_and_list(state_file):
    """When both ssh_public_key and ssh_public_keys are passed, dedupe is applied."""
    state_module.save_setup(ssh_public_key=KEY_ED, ssh_public_keys=[KEY_ED, KEY_RSA])
    keys = state_module.get_ssh_public_keys()
    assert KEY_ED in keys
    assert KEY_RSA in keys
    assert len(keys) == 2


def test_save_setup_invalid_key_in_list_raises(state_file):
    with pytest.raises(ValueError, match="Invalid SSH public key"):
        state_module.save_setup(ssh_public_keys=[KEY_ED, KEY_BAD])


def test_save_setup_strips_trailing_whitespace(state_file):
    padded = KEY_ED + "   "
    state_module.save_setup(ssh_public_key=padded)
    assert state_module.get_ssh_public_key() == KEY_ED


# ---------------------------------------------------------------------------
# Backward compatibility — legacy state file with only ssh_public_key
# ---------------------------------------------------------------------------


def test_load_legacy_state_backfills_list(state_file):
    """Old state files without ssh_public_keys should be migrated on load."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "setup_complete": True,
        "ssh_public_key": KEY_ED,
        "built_templates": {},
        "custom_templates": {},
        "vms": {},
    }
    state_file.write_text(json.dumps(legacy))
    assert state_module.get_ssh_public_key() == KEY_ED
    assert state_module.get_ssh_public_keys() == [KEY_ED]
    assert state_module.is_setup_complete()


def test_is_setup_complete_false_when_no_key(state_file):
    assert not state_module.is_setup_complete()


# ---------------------------------------------------------------------------
# SetupRequest schema — normalization
# ---------------------------------------------------------------------------


def _make_setup_request(**kwargs):
    from homecloud.api.schemas import SetupRequest

    return SetupRequest(**kwargs)


def test_schema_single_key_normalizes_to_list():
    req = _make_setup_request(ssh_public_key=KEY_ED)
    assert req.ssh_public_keys == [KEY_ED]
    assert req.ssh_public_key == KEY_ED


def test_schema_list_normalizes_back_compat():
    req = _make_setup_request(ssh_public_keys=[KEY_ED, KEY_RSA])
    assert req.ssh_public_key == KEY_ED
    assert len(req.ssh_public_keys) == 2


def test_schema_deduplicates():
    req = _make_setup_request(ssh_public_keys=[KEY_ED, KEY_ED, KEY_RSA])
    assert len(req.ssh_public_keys) == 2


def test_schema_no_key_raises():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _make_setup_request()


def test_schema_empty_list_raises():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _make_setup_request(ssh_public_keys=[])


def test_schema_both_provided_merges():
    req = _make_setup_request(ssh_public_key=KEY_ECDSA, ssh_public_keys=[KEY_ED, KEY_RSA])
    # All three unique keys should be in ssh_public_keys; order: list first, then single
    assert KEY_ED in req.ssh_public_keys
    assert KEY_RSA in req.ssh_public_keys
    assert KEY_ECDSA in req.ssh_public_keys
    assert len(req.ssh_public_keys) == 3


# ---------------------------------------------------------------------------
# Cloud-init template rendering — all keys appear under ssh_authorized_keys
# ---------------------------------------------------------------------------


def test_base_image_template_single_key_baked_in():
    rendered = render_cloud_init(
        "base-image.yaml.j2",
        hostname="tpl-homecloud-base",
        ssh_user="ubuntu",
        ssh_public_keys=[KEY_ED],
    )
    assert "ssh_authorized_keys:" in rendered
    assert KEY_ED in rendered


def test_base_image_template_multiple_keys_all_baked_in():
    rendered = render_cloud_init(
        "base-image.yaml.j2",
        hostname="tpl-homecloud-base",
        ssh_user="ubuntu",
        ssh_public_keys=[KEY_ED, KEY_RSA],
    )
    assert "ssh_authorized_keys:" in rendered
    assert KEY_ED in rendered
    assert KEY_RSA in rendered


def test_base_image_template_no_keys_omits_section():
    rendered = render_cloud_init(
        "base-image.yaml.j2",
        hostname="tpl-homecloud-base",
        ssh_user="ubuntu",
        ssh_public_keys=[],
    )
    assert "ssh_authorized_keys:" not in rendered


def test_deploy_template_single_key():
    rendered = render_cloud_init(
        "deploy.yaml.j2",
        hostname="my-vm",
        tailscale_auth_key="tskey-test",
        ssh_public_keys=[KEY_ED],
    )
    assert "ssh_authorized_keys:" in rendered
    assert KEY_ED in rendered


def test_deploy_template_multiple_keys():
    rendered = render_cloud_init(
        "deploy.yaml.j2",
        hostname="my-vm",
        tailscale_auth_key="tskey-test",
        ssh_public_keys=[KEY_ED, KEY_RSA],
    )
    assert "ssh_authorized_keys:" in rendered
    assert KEY_ED in rendered
    assert KEY_RSA in rendered


def test_deploy_template_legacy_single_key_arg():
    """Old callers passing ssh_public_key (string) still work."""
    rendered = render_cloud_init(
        "deploy.yaml.j2",
        hostname="my-vm",
        tailscale_auth_key="tskey-test",
        ssh_public_key=KEY_ED,
    )
    assert "ssh_authorized_keys:" in rendered
    assert KEY_ED in rendered


def test_deploy_template_keys_are_list_items():
    """Each key must appear as a list entry (prefixed with '  - ')."""
    rendered = render_cloud_init(
        "deploy.yaml.j2",
        hostname="my-vm",
        tailscale_auth_key="tskey-test",
        ssh_public_keys=[KEY_ED, KEY_RSA],
    )
    assert f"  - {KEY_ED}" in rendered
    assert f"  - {KEY_RSA}" in rendered
