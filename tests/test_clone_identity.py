"""Per-machine identity must not survive cloning.

Anything unique-per-host that is left in the template gets copied into every
clone and stops being unique. The failure this guards against is not loud: two
VMs deriving the same DHCP identity are handed the same lease, both answer ARP
for one address, and roughly half of all packets reach the wrong guest — which
presents as ~50% packet loss on a network that is otherwise healthy.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import yaml

from homecloud.images.cloud_init import render_cloud_init
from homecloud.proxmox.client import ProxmoxClient


def _seal_command(vmid: int = 8001) -> str:
    """Return the shell command `prepare_for_template` runs inside the guest."""
    client = ProxmoxClient.__new__(ProxmoxClient)
    client.wait_for_guest_agent = MagicMock()  # type: ignore[method-assign]
    client.guest_exec = MagicMock()  # type: ignore[method-assign]

    ProxmoxClient.prepare_for_template(client, vmid)

    client.guest_exec.assert_called_once()
    argv = client.guest_exec.call_args.args[1]
    assert argv[:2] == ["bash", "-c"]
    return argv[2]


def test_seal_clears_both_machine_id_locations():
    """`/etc/machine-id` alone is not enough.

    `systemd-machine-id-setup` re-adopts the ID from `/var/lib/dbus/machine-id`
    when it exists, which silently undoes truncating the canonical file.
    """
    command = _seal_command()
    assert "truncate -s 0 /etc/machine-id" in command
    assert "/var/lib/dbus/machine-id" in command


def test_seal_removes_ssh_host_keys():
    """Clones sharing host keys are indistinguishable to an SSH client."""
    command = _seal_command()
    assert "/etc/ssh/ssh_host_" in command


def test_seal_clears_cloud_init_state():
    command = _seal_command()
    assert "cloud-init clean" in command
    assert "/var/lib/cloud/instances/*" in command


def _base_image_files() -> dict[str, dict]:
    """Render the base-image spec and index its `write_files` entries by path."""
    rendered = render_cloud_init(
        "base-image.yaml.j2",
        hostname="tpl-test",
        ssh_user="ubuntu",
        ssh_public_keys=["ssh-ed25519 AAAAC3Nza test@host"],
    )
    config = yaml.safe_load(rendered)
    return {entry["path"]: entry for entry in config["write_files"]}


def test_base_image_pins_dhcp_identity_to_the_mac():
    """DHCP identity must come from the MAC, which Proxmox makes unique.

    netplan's default (`duid`) derives the identifier from /etc/machine-id, so
    any clone that inherits one collides with its sibling.
    """
    entry = _base_image_files()["/etc/netplan/99-dhcp-identifier.yaml"]
    netplan = yaml.safe_load(entry["content"])
    assert netplan["network"]["ethernets"]["eth0"]["dhcp-identifier"] == "mac"


def test_dhcp_drop_in_outranks_the_file_cloud_init_rewrites():
    """cloud-init rewrites 50-cloud-init.yaml every boot; ours must survive.

    netplan merges lexicographically, so a 99- prefix both persists and wins.
    """
    path = "/etc/netplan/99-dhcp-identifier.yaml"
    assert path in _base_image_files()
    assert path.rsplit("/", 1)[1] > "50-cloud-init.yaml"
