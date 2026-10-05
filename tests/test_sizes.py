from homecloud.sizes import SIZES, get_size, list_sizes


def test_list_sizes_in_definition_order():
    assert [s.id for s in list_sizes()] == ["micro", "small", "medium", "large", "xlarge"]


def test_sizes_grow_monotonically():
    sizes = list_sizes()
    for smaller, larger in zip(sizes, sizes[1:], strict=False):
        assert smaller.cores <= larger.cores
        assert smaller.memory_gb < larger.memory_gb
        assert smaller.disk_gb < larger.disk_gb


def test_ids_match_keys():
    assert all(key == size.id for key, size in SIZES.items())


def test_get_size():
    medium = get_size("medium")
    assert (medium.cores, medium.memory_gb, medium.disk_gb) == (2, 4.0, 40)
    assert get_size("custom") is None
    assert get_size("") is None
