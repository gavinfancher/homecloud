"""Keep tests independent of the developer's ``.env`` and shell environment.

``homecloud.config`` builds its ``Settings`` at import time from env vars and
a cwd-relative ``.env``. It is imported here from an empty directory, and every
field is then reset to its declared default, so no real value can leak into a
test. Tests that need a setting use the ``settings`` fixture to patch it.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_cwd = os.getcwd()
with tempfile.TemporaryDirectory() as _empty:
    os.chdir(_empty)
    try:
        from homecloud.config import Settings
        from homecloud.config import settings as _settings
    finally:
        os.chdir(_cwd)

for _name, _field in Settings.model_fields.items():
    setattr(_settings, _name, _field.get_default(call_default_factory=True))


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    """The shared settings object; patch fields with ``monkeypatch.setattr``."""
    yield _settings
