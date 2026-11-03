"""Every setting homecloud reads, all from environment variables.

In production the secret ones come from Infisical (project homecloud, env prod) through the
`homecloud` Kubernetes Secret, and the rest are plain values in deploy/k8s/api.yaml.
"""

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# No sign-in, for running on a laptop (see backend/compose.yml). Never set in the cluster.
LOCAL = _env("HOMECLOUD_LOCAL") == "1"

DATABASE_URL = _env("HOMECLOUD_DATABASE_URL")
# scrypt hash of the one account's password; make one with `uv run python -m app.auth`.
ADMIN_PASSWORD_HASH = _env("HOMECLOUD_ADMIN_PASSWORD_HASH")
# Where the pages are served from (https://homecloud.gavinf.com), allowed by CORS.
CORS_ORIGINS = [o.strip() for o in _env("HOMECLOUD_CORS_ORIGINS").split(",") if o.strip()]
# A pretend Proxmox in memory (app/fake_pve.py), for trying the UI. Never set in the cluster.
FAKE_PROXMOX = _env("HOMECLOUD_FAKE_PROXMOX") == "1"
# Set locally to serve the pages from this app too.
STATIC_DIR = _env("HOMECLOUD_STATIC_DIR")

# --- Proxmox --------------------------------------------------------------------------------
PROXMOX_HOST = _env("HOMECLOUD_PROXMOX_HOST", "10.0.4.10")
# An API token: "<user>@<realm>!<token name>" and its secret.
PROXMOX_TOKEN_ID = _env("HOMECLOUD_PROXMOX_TOKEN_ID")
PROXMOX_TOKEN_SECRET = _env("HOMECLOUD_PROXMOX_TOKEN_SECRET")
# Proxmox ships a self-signed certificate; the API is only reached on the LAN.
PROXMOX_VERIFY_TLS = _env("HOMECLOUD_PROXMOX_VERIFY_TLS", "false").lower() == "true"
PROXMOX_NODE = _env("HOMECLOUD_PROXMOX_NODE", "pve")
# Where VM disks go.
PROXMOX_DISK_STORAGE = _env("HOMECLOUD_PROXMOX_DISK_STORAGE", "local-lvm")
# Directory storage for ISOs and downloaded cloud images: needs the "iso" and "import" content types.
PROXMOX_FILE_STORAGE = _env("HOMECLOUD_PROXMOX_FILE_STORAGE", "local")
PROXMOX_BRIDGE = _env("HOMECLOUD_PROXMOX_BRIDGE", "vmbr0")
# Every VM homecloud makes goes in this pool; the API token only has rights on it.
PROXMOX_POOL = _env("HOMECLOUD_PROXMOX_POOL", "homecloud")
# The web UI, for the "console" link on each VM. Only reachable on the LAN or tailnet.
PROXMOX_UI = _env("HOMECLOUD_PROXMOX_UI", "https://pve.ad.gavinf.com:8006")
# New VMs get the lowest free id at or above this, so they're easy to tell apart.
VMID_START = int(_env("HOMECLOUD_VMID_START", "700"))

# --- Ubuntu ---------------------------------------------------------------------------------
# Pinned to one build of 26.04 (26.04.1); its checksum comes from SHA256SUMS next to it.
UBUNTU_IMAGE_URL = _env(
    "HOMECLOUD_UBUNTU_IMAGE_URL",
    "https://cloud-images.ubuntu.com/releases/resolute/release-20261016/ubuntu-26.04-server-cloudimg-amd64.img",
)
# Public keys allowed to SSH in as `ubuntu`, one per line. Ubuntu VMs have no password.
SSH_KEYS = [k.strip() for k in _env("HOMECLOUD_SSH_KEYS").splitlines() if k.strip()]

# --- Windows --------------------------------------------------------------------------------
# The Windows 11 install ISO, already on the Proxmox host.
WINDOWS_ISO = _env("HOMECLOUD_WINDOWS_ISO", "local:iso/Win11-Enterprise-eval.iso")
# Local Administrator password on every Windows VM.
WINDOWS_ADMIN_PASSWORD = _env("HOMECLOUD_WINDOWS_ADMIN_PASSWORD")
# Index of the edition to install inside install.wim. The Enterprise eval ISO has just one.
WINDOWS_IMAGE_INDEX = int(_env("HOMECLOUD_WINDOWS_IMAGE_INDEX", "1"))
WINDOWS_TIMEZONE = _env("HOMECLOUD_WINDOWS_TIMEZONE", "Central Standard Time")
# VirtIO guest tools, for the QEMU guest agent (how homecloud learns the VM is up, and its IP).
VIRTIO_ISO_URL = _env(
    "HOMECLOUD_VIRTIO_ISO_URL",
    "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/"
    "virtio-win-0.1.302-1/virtio-win-0.1.302.iso",
)
