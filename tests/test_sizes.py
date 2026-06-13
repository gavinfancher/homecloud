"""Unit tests for sizes catalog and DeployVMRequest size resolution."""

from __future__ import annotations

import pytest

from homecloud.sizes import SIZES, get_size, list_sizes


# ---------------------------------------------------------------------------
# sizes.py — catalog helpers
# ---------------------------------------------------------------------------


def test_list_sizes_returns_all_presets():
    sizes = list_sizes()
    ids = [s.id for s in sizes]
    assert ids == ["micro", "small", "medium", "large", "xlarge"]


def test_get_size_known():
    size = get_size("medium")
    assert size is not None
    assert size.id == "medium"
    assert size.cores == 2
    assert size.memory_gb == 4.0
    assert size.disk_gb == 40


def test_get_size_all_presets():
    expected = {
        "micro": (1, 1.0, 10),
        "small": (1, 2.0, 20),
        "medium": (2, 4.0, 40),
        "large": (4, 8.0, 80),
        "xlarge": (8, 16.0, 160),
    }
    for size_id, (cores, memory_gb, disk_gb) in expected.items():
        s = get_size(size_id)
        assert s is not None, f"get_size('{size_id}') returned None"
        assert s.cores == cores
        assert s.memory_gb == memory_gb
        assert s.disk_gb == disk_gb


def test_get_size_unknown_returns_none():
    assert get_size("nonexistent") is None


def test_get_size_custom_returns_none():
    # "custom" is not a preset entry
    assert get_size("custom") is None


def test_sizes_are_frozen():
    size = get_size("micro")
    assert size is not None
    with pytest.raises((AttributeError, TypeError)):
        size.cores = 99  # type: ignore[misc]


def test_sizes_catalog_count():
    assert len(SIZES) == 5


# ---------------------------------------------------------------------------
# DeployVMRequest — size resolution
# ---------------------------------------------------------------------------


def _make_request(**kwargs):  # type: ignore[return]
    """Helper to create a DeployVMRequest, propagating ValidationError."""
    from homecloud.api.schemas import DeployVMRequest

    return DeployVMRequest(**kwargs)


def test_deploy_request_size_id_resolves_resources():
    req = _make_request(name="test-vm", size_id="medium", image_id="homecloud-base")
    assert req.cores == 2
    assert req.memory_gb == 4.0
    assert req.disk_gb == 40
    assert req.size_id == "medium"


def test_deploy_request_size_id_micro():
    req = _make_request(name="test-vm", size_id="micro")
    assert req.cores == 1
    assert req.memory_gb == 1.0
    assert req.disk_gb == 10


def test_deploy_request_custom_explicit_resources():
    req = _make_request(name="test-vm", cores=3, memory_gb=6.0, disk_gb=50)
    assert req.cores == 3
    assert req.memory_gb == 6.0
    assert req.disk_gb == 50
    assert req.size_id == "custom"


def test_deploy_request_explicit_size_id_custom_with_resources():
    req = _make_request(name="test-vm", size_id="custom", cores=3, memory_gb=6.0, disk_gb=50)
    assert req.cores == 3
    assert req.size_id == "custom"


def test_deploy_request_invalid_size_id_raises_400():
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        _make_request(name="test-vm", size_id="enormous")
    assert "enormous" in str(exc_info.value)


def test_deploy_request_conflicting_size_and_resources_raises_400():
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        _make_request(name="test-vm", size_id="medium", cores=4, memory_gb=8.0, disk_gb=80)
    assert "Conflicting" in str(exc_info.value) or "size_id" in str(exc_info.value)


def test_deploy_request_missing_resources_no_size_raises_400():
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        _make_request(name="test-vm", cores=2)
    assert "Missing" in str(exc_info.value) or "must be provided" in str(exc_info.value)


def test_deploy_request_partial_resources_missing_disk():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _make_request(name="test-vm", cores=2, memory_gb=4.0)


def test_deploy_request_no_size_no_resources_raises_400():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _make_request(name="test-vm")
