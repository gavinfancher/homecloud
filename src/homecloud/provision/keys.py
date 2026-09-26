"""The controller's own SSH identity.

Ansible and the port scanner reach instances as the controller, not as a
user: the keypair is generated once into the persisted ``.homecloud`` volume
and its public half is authorized on every VM at deploy time, next to the
user's keys.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

KEY_PATH = Path(".homecloud/controller_ed25519")

_lock = threading.Lock()


def controller_key_path() -> Path:
    """Path to the private key, generating the keypair on first use."""
    with _lock:
        if not KEY_PATH.exists():
            KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                    "-C", "homecloud-controller", "-f", str(KEY_PATH),
                ],
                check=True,
            )
        KEY_PATH.chmod(0o600)
    return KEY_PATH.resolve()


def controller_public_key() -> str:
    path = controller_key_path()
    return path.with_suffix(".pub").read_text().strip()
