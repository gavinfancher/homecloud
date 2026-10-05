"""The base image: one editable definition, built into versioned templates.

A build snapshots ``base_image_config`` (plus the current SSH keys) into a
``base_images`` row and turns it into a Proxmox template, entirely through the
Proxmox API:

1. the node downloads the Ubuntu cloud image (``download-url``), checked
   against the release's ``SHA256SUMS``;
2. a VM imports it as its disk and boots once from a NoCloud seed ISO that
   installs the guest agent, Tailscale, the configured packages and keys;
3. the guest agent waits out cloud-init, the identity is wiped, and the VM
   becomes the template ``homecloud-base-v<id>``.

Deploys clone the newest ready build. Builds never change in place, so editing
the config or rebuilding leaves existing instances untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
import yaml
from sqlalchemy import select

from homecloud.db.models import BaseImage, BaseImageConfig
from homecloud.db.session import session_scope
from homecloud.jobs import JobCancelled
from homecloud.proxmox.client import ProxmoxClient
from homecloud.state import get_ssh_public_keys

logger = logging.getLogger(__name__)
LogFn = Callable[[str, str], None]

# Templates live above the instance range so they are easy to spot on the node.
TEMPLATE_VMID_START = 9100

# The stock cloud image disk is ~3.5 GB — too small for the bake's packages.
# Clones grow from here to their own size.
BAKE_DISK_GB = 8

# cloud-config keys whose lists are concatenated (not replaced) when the extra
# user-data is merged in.
_LIST_KEYS = ("packages", "runcmd", "write_files", "ssh_authorized_keys", "bootcmd")
# Keys the builder owns; extra user-data may not override them.
_RESERVED_KEYS = ("users", "user", "hostname", "fqdn")


class BaseImageError(ValueError):
    pass


def _noop_log(_level: str, _message: str) -> None:
    pass


def template_name(build_id: int) -> str:
    return f"homecloud-base-v{build_id}"


def parse_extra_user_data(text: str) -> dict:
    """Validate the extra #cloud-config; returns it as a mapping."""
    if not text.strip():
        return {}
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BaseImageError(f"Extra user-data is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise BaseImageError("Extra user-data must be a YAML mapping (#cloud-config keys)")
    reserved = sorted(set(doc) & set(_RESERVED_KEYS))
    if reserved:
        raise BaseImageError(f"Extra user-data may not set: {', '.join(reserved)}")
    for key in _LIST_KEYS:
        if key in doc and not isinstance(doc[key], list):
            raise BaseImageError(f"Extra user-data {key!r} must be a list")
    return doc


def bake_user_data(
    *, ssh_keys: list[str], packages: list[str], extra_user_data: str = ""
) -> str:
    """The #cloud-config for the one boot that turns a cloud image into a base."""
    doc: dict = {
        "ssh_authorized_keys": list(ssh_keys),
        "package_update": True,
        "packages": ["qemu-guest-agent", *[p for p in packages if p != "qemu-guest-agent"]],
        "runcmd": [
            ["systemctl", "enable", "--now", "qemu-guest-agent"],
            # Installed, not joined: each instance joins with its own key.
            ["bash", "-c", "curl -fsSL https://tailscale.com/install.sh | sh"],
        ],
    }
    for key, value in parse_extra_user_data(extra_user_data).items():
        if key in _LIST_KEYS:
            doc[key] = [*doc.get(key, []), *value]
        else:
            doc[key] = value
    return "#cloud-config\n" + yaml.safe_dump(doc, sort_keys=False, width=4096)


def import_filename(image_url: str) -> str:
    """Name the image is cached under in the node's ``import`` storage.

    Proxmox infers the format from the extension; Ubuntu's ``.img`` cloud
    images are qcow2 inside.
    """
    name = PurePosixPath(urlparse(image_url).path).name
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in (".img", ".qcow2"):
        raise BaseImageError(f"Expected a .img or .qcow2 cloud image, got {name!r}")
    # The release serial in the URL keeps different releases apart in the cache.
    serial = PurePosixPath(urlparse(image_url).path).parent.name
    return f"homecloud-{serial}-{PurePosixPath(name).stem}.qcow2"


def fetch_sha256(image_url: str) -> str:
    """Checksum for *image_url* from ``SHA256SUMS`` next to it."""
    base, _, name = image_url.rpartition("/")
    resp = httpx.get(f"{base}/SHA256SUMS", timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise BaseImageError(f"{name} is not listed in {base}/SHA256SUMS")


# -- config and builds ---------------------------------------------------------


def get_config() -> dict:
    with session_scope() as session:
        return session.get(BaseImageConfig, 1).to_dict()


def update_config(*, image_url: str, packages: list[str], extra_user_data: str) -> dict:
    if not urlparse(image_url).scheme.startswith("http"):
        raise BaseImageError("image_url must be an http(s) URL")
    import_filename(image_url)
    parse_extra_user_data(extra_user_data)
    with session_scope() as session:
        row = session.get(BaseImageConfig, 1)
        row.image_url = image_url.strip()
        row.packages = [p.strip() for p in packages if p.strip()]
        row.extra_user_data = extra_user_data
        session.flush()
        return row.to_dict()


def list_builds(limit: int = 20) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(BaseImage).order_by(BaseImage.id.desc()).limit(limit))
        return [row.to_dict() for row in rows]


def current_build() -> dict | None:
    """The newest ready build — what deploys clone."""
    with session_scope() as session:
        row = session.scalars(
            select(BaseImage)
            .where(BaseImage.status == "ready")
            .order_by(BaseImage.id.desc())
            .limit(1)
        ).first()
        return row.to_dict() if row else None


def get_build(build_id: int) -> dict | None:
    with session_scope() as session:
        row = session.get(BaseImage, build_id)
        return row.to_dict() if row else None


def start_build() -> int:
    """Snapshot the config and current SSH keys into a new ``building`` row."""
    keys = get_ssh_public_keys()
    if not keys:
        raise BaseImageError("Add an SSH public key in Settings before building the base image")
    with session_scope() as session:
        config = session.get(BaseImageConfig, 1)
        row = BaseImage(
            status="building",
            image_url=config.image_url,
            ssh_keys=keys,
            packages=list(config.packages),
            extra_user_data=config.extra_user_data,
        )
        session.add(row)
        session.flush()
        return row.id


def _finish_build(build_id: int, **fields) -> None:
    with session_scope() as session:
        row = session.get(BaseImage, build_id)
        for key, value in fields.items():
            setattr(row, key, value)


def fail_unfinished_builds() -> None:
    """Builds left ``building`` by a dead controller can never finish."""
    with session_scope() as session:
        for row in session.scalars(select(BaseImage).where(BaseImage.status == "building")):
            row.status = "failed"
            row.error = "Interrupted — the controller stopped during the build"


def build(
    build_id: int,
    *,
    proxmox: ProxmoxClient | None = None,
    log: LogFn | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> int:
    """Turn build *build_id* into a template; returns its vmid."""
    emit = log or _noop_log
    pve = proxmox or ProxmoxClient()

    def check_cancel() -> None:
        if cancel_check is not None and cancel_check():
            raise JobCancelled("Base image build cancelled by user")

    spec = get_build(build_id)
    if spec is None:
        raise BaseImageError(f"Unknown base image build {build_id}")

    vmid: int | None = None
    try:
        sha256 = fetch_sha256(spec["image_url"])
        _finish_build(build_id, sha256=sha256)
        filename = import_filename(spec["image_url"])

        volid = f"{pve.image_storage}:import/{filename}"
        if pve.volume_exists(volid):
            emit("info", f"Cloud image already on the node: {volid}")
        else:
            emit("info", f"Downloading {spec['image_url']} — this can take a few minutes…")
            volid = pve.download_cloud_image(spec["image_url"], filename, sha256=sha256)
            emit("info", f"Downloaded and verified {volid}")
        check_cancel()

        vmid = pve.next_vmid(start=TEMPLATE_VMID_START)
        name = template_name(build_id)
        emit("info", f"Creating VM {vmid} ({name}) and importing the disk")
        pve.wait_for_task(pve.create_vm(vmid, name))
        pve.import_cloud_image_disk(vmid, volid)
        pve.grow_disk(vmid, "scsi0", BAKE_DISK_GB)
        check_cancel()

        emit("info", "Booting once to bake in the guest agent, Tailscale and packages…")
        user_data = bake_user_data(
            ssh_keys=spec["ssh_keys"],
            packages=spec["packages"],
            extra_user_data=spec["extra_user_data"],
        )
        pve.attach_seed(vmid, hostname=name, user_data=user_data)
        pve.wait_for_task(pve.start(vmid), timeout=120)
        pve.wait_for_guest_agent(vmid, timeout=900, check_cancel=check_cancel)
        result = pve.guest_run(
            vmid, ["cloud-init", "status", "--wait"], timeout=1800, check_cancel=check_cancel
        )
        if result["exitcode"] not in (0, 2):  # 2 = finished with warnings
            emit_cloud_init_errors(pve, vmid, emit)
            raise RuntimeError(f"cloud-init failed while baking (exit {result['exitcode']})")
        emit("info", "Bake boot finished — preparing the template")

        pve.prepare_for_template(vmid)
        pve.wait_for_task(pve.stop(vmid), timeout=120)
        pve.detach_seed(vmid)
        pve.convert_to_template(vmid)
    except BaseException as exc:
        emit("warning", "Build failed — cleaning up")
        if vmid is not None:
            _cleanup_vm(pve, vmid)
        status_error = "Cancelled" if isinstance(exc, JobCancelled) else str(exc)
        _finish_build(build_id, status="failed", error=status_error)
        raise

    _finish_build(build_id, status="ready", template_vmid=vmid, built_at=datetime.now(UTC))
    emit("info", f"Base image v{build_id} ready — template #{vmid}")
    return vmid


def emit_cloud_init_errors(pve: ProxmoxClient, vmid: int, emit: LogFn) -> None:
    """Copy cloud-init's own account of a failure into the job log.

    Runs before cleanup deletes the VM, which would take the evidence with it.
    """
    commands = [
        ["cloud-init", "status", "--long"],
        ["tail", "-n", "30", "/var/log/cloud-init-output.log"],
        ["bash", "-c", "grep -E 'WARNING|ERROR|Traceback' /var/log/cloud-init.log | tail -n 20"],
    ]
    for command in commands:
        try:
            result = pve.guest_run(vmid, command, timeout=60)
        except Exception:  # noqa: BLE001 — diagnostics are best-effort
            logger.debug("Diagnostic %s failed on VM %s", command, vmid, exc_info=True)
            continue
        for line in (result["out"] + result["err"]).splitlines():
            if line.strip():
                emit("error", f"  {line}")


def _cleanup_vm(pve: ProxmoxClient, vmid: int) -> None:
    try:
        pve.wait_for_task(pve.stop(vmid), timeout=120)
    except Exception:  # noqa: BLE001 — may already be stopped
        logger.debug("Could not stop VM %s", vmid, exc_info=True)
    try:
        pve.wait_for_task(pve.delete_vm(vmid), timeout=120)
    except Exception:  # noqa: BLE001
        logger.warning("Leftover base image VM %s needs manual cleanup", vmid)
    try:
        pve.delete_seed(vmid)
    except Exception:  # noqa: BLE001
        logger.warning("Leftover seed ISO for VM %s", vmid, exc_info=True)
