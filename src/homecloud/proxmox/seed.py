"""Build NoCloud seed ISOs so cloud-init user-data never needs snippets storage.

Proxmox only reads custom user-data (``cicustom``) from ``snippets`` storage,
and its API refuses to upload snippets — writing one means a shell on the node.
Instead the controller renders the whole NoCloud datasource itself, packs it
into a small ISO labelled ``cidata``, and uploads that as ordinary ``iso``
content.  Every stock cloud image ships the NoCloud datasource, so the guest
reads it exactly as it would read Proxmox's own cloud-init drive.
"""

from __future__ import annotations

import io
import uuid

import pycdlib
import yaml

SEED_VOLUME_LABEL = "cidata"


def seed_iso_filename(vmid: int) -> str:
    return f"homecloud-seed-{vmid}.iso"


def render_meta_data(*, hostname: str, instance_id: str | None = None) -> str:
    """NoCloud meta-data.

    A fresh instance-id on every render makes cloud-init treat the boot as a
    new instance and run its per-instance modules, which is what a clone of a
    ``cloud-init clean``-ed template needs.
    """
    doc = {
        "instance-id": instance_id or f"homecloud-{uuid.uuid4().hex}",
        "local-hostname": hostname,
    }
    return yaml.safe_dump(doc, sort_keys=False)


def render_network_config(mac: str) -> str:
    """DHCP on the VM's NIC, matched by MAC and left under its kernel name.

    Renaming it (to ``eth0``) fails on current images, where the NIC is
    already up as ``ens18`` by the time cloud-init runs.  The DHCP client
    identifier is keyed off the MAC rather than ``/etc/machine-id``, so clones
    can never collide on a lease even if a machine-id slips through.
    """
    doc = {
        "version": 2,
        "ethernets": {
            "nic0": {
                "match": {"macaddress": mac.lower()},
                "dhcp4": True,
                "dhcp-identifier": "mac",
            }
        },
    }
    return yaml.safe_dump(doc, sort_keys=False)


def build_seed_iso(*, user_data: str, meta_data: str, network_config: str | None = None) -> bytes:
    """Pack the NoCloud files into an ISO9660 image labelled ``cidata``.

    Rock Ridge and Joliet names carry the real (lowercase, hyphenated) file
    names; the plain ISO9660 names are only there because the format requires
    them.
    """
    files = {"user-data": user_data, "meta-data": meta_data}
    if network_config is not None:
        files["network-config"] = network_config

    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident=SEED_VOLUME_LABEL)
    for name, content in files.items():
        data = content.encode()
        iso_name = "/" + name.replace("-", "").upper()[:8] + ".;1"
        iso.add_fp(
            io.BytesIO(data),
            len(data),
            iso_name,
            rr_name=name,
            joliet_path=f"/{name}",
        )

    out = io.BytesIO()
    iso.write_fp(out)
    iso.close()
    return out.getvalue()
