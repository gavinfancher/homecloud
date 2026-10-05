import io

import pycdlib
import pytest
import yaml

from homecloud.proxmox import seed


def test_seed_iso_filename():
    assert seed.seed_iso_filename(512) == "homecloud-seed-512.iso"


def test_meta_data_with_explicit_instance_id():
    doc = yaml.safe_load(seed.render_meta_data(hostname="pixie", instance_id="iid-1"))
    assert doc == {"instance-id": "iid-1", "local-hostname": "pixie"}


def test_meta_data_generates_fresh_instance_id():
    first = yaml.safe_load(seed.render_meta_data(hostname="pixie"))["instance-id"]
    second = yaml.safe_load(seed.render_meta_data(hostname="pixie"))["instance-id"]
    assert first.startswith("homecloud-")
    assert first != second


def test_network_config_lowercases_mac_and_names_eth0():
    doc = yaml.safe_load(seed.render_network_config("BC:24:11:AA:BB:CC"))
    assert doc["version"] == 1
    [nic] = doc["config"]
    assert nic == {
        "type": "physical",
        "name": "eth0",
        "mac_address": "bc:24:11:aa:bb:cc",
        "subnets": [{"type": "dhcp4"}],
    }


def _read_iso(data: bytes) -> pycdlib.PyCdlib:
    iso = pycdlib.PyCdlib()
    iso.open_fp(io.BytesIO(data))
    return iso


def _rr_file(iso: pycdlib.PyCdlib, name: str) -> str:
    out = io.BytesIO()
    iso.get_file_from_iso_fp(out, rr_path=f"/{name}")
    return out.getvalue().decode()


def _joliet_file(iso: pycdlib.PyCdlib, name: str) -> str:
    out = io.BytesIO()
    iso.get_file_from_iso_fp(out, joliet_path=f"/{name}")
    return out.getvalue().decode()


def _rr_names(iso: pycdlib.PyCdlib) -> set[str]:
    return {
        child.rock_ridge.name().decode()
        for child in iso.list_children(iso_path="/")
        if child.rock_ridge is not None and not (child.is_dot() or child.is_dotdot())
    }


@pytest.fixture
def files():
    return {
        "user-data": "#cloud-config\nhostname: pixie\n",
        "meta-data": seed.render_meta_data(hostname="pixie", instance_id="iid-1"),
        "network-config": seed.render_network_config("bc:24:11:00:00:01"),
    }


def test_seed_iso_round_trip(files):
    data = seed.build_seed_iso(
        user_data=files["user-data"],
        meta_data=files["meta-data"],
        network_config=files["network-config"],
    )
    iso = _read_iso(data)
    try:
        assert iso.pvd.volume_identifier.decode().strip() == seed.SEED_VOLUME_LABEL
        assert _rr_names(iso) == set(files)
        for name, content in files.items():
            assert _rr_file(iso, name) == content
            assert _joliet_file(iso, name) == content
    finally:
        iso.close()


def test_seed_iso_without_network_config(files):
    data = seed.build_seed_iso(user_data=files["user-data"], meta_data=files["meta-data"])
    iso = _read_iso(data)
    try:
        assert _rr_names(iso) == {"user-data", "meta-data"}
    finally:
        iso.close()
