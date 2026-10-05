from types import SimpleNamespace

import pytest
import yaml

from homecloud.images import sources


def _image(url: str, id: str = "ubuntu-24.04"):
    return SimpleNamespace(id=id, url=url)


def test_template_name():
    assert sources.template_name("debian-12") == "source-debian-12"


@pytest.mark.parametrize(
    ("url", "filename"),
    [
        (
            "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
            "ubuntu-24.04.qcow2",
        ),
        ("https://example.com/images/disk.QCOW2", "ubuntu-24.04.qcow2"),
        ("https://example.com/images/disk.raw?sig=abc#frag", "ubuntu-24.04.raw"),
        ("https://example.com/disk.vmdk", "ubuntu-24.04.vmdk"),
    ],
)
def test_import_filename(url, filename):
    assert sources.import_filename(_image(url)) == filename


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/debian-12-genericcloud-amd64.tar.xz",
        "https://example.com/image",
        "https://example.com/",
    ],
)
def test_import_filename_rejects_unsupported_formats(url):
    with pytest.raises(ValueError, match="Cannot import"):
        sources.import_filename(_image(url))


def test_bake_user_data():
    text = sources.bake_user_data()
    assert text.startswith("#cloud-config\n")
    doc = yaml.safe_load(text)

    [netplan] = doc["write_files"]
    assert netplan["path"] == "/etc/netplan/99-homecloud-dhcp-identifier.yaml"
    assert netplan["permissions"] == "0600"
    assert yaml.safe_load(netplan["content"]) == {
        "network": {"version": 2, "ethernets": {"eth0": {"dhcp-identifier": "mac"}}}
    }

    [cmd] = doc["runcmd"]
    assert cmd[:2] == ["bash", "-c"]
    assert "qemu-guest-agent" in cmd[2]
    assert "systemctl enable --now qemu-guest-agent" in cmd[2]
