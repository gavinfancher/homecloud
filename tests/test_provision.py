import pytest

from homecloud.provision import catalog
from homecloud.provision.catalog import ROLES_DIR, RoleError, resolve_roles
from homecloud.provision.script import RENDERERS


def test_roles_dir_ships_every_role():
    shipped = {p.name for p in ROLES_DIR.iterdir() if (p / "homecloud.yml").exists()}
    assert shipped == set(catalog.load_catalog())
    # Every catalog role has a script renderer, and nothing else does.
    assert shipped == set(RENDERERS)


def test_catalog_is_in_play_order():
    roles = catalog.list_roles()
    keys = [(r["order"], r["id"]) for r in roles]
    assert keys == sorted(keys)
    assert roles[0]["id"] == "tailscale"


def test_role_metadata_is_well_formed():
    for role in catalog.list_roles():
        assert role["label"] and role["description"]
        if role["required"]:
            assert role["default_enabled"] is True
        for var in role["vars"]:
            assert var["type"] in catalog.VAR_TYPES


def test_empty_selection_gets_required_roles_with_defaults():
    assert resolve_roles([]) == [
        {"id": "tailscale", "vars": {"tailscale_accept_routes": True, "tailscale_ssh": False}}
    ]


def test_selection_is_returned_in_catalog_order_with_defaults_filled():
    result = resolve_roles(
        [
            {"id": "commands", "vars": {"commands": ["  echo hi  ", "", "  "]}},
            {"id": "packages"},
            {"id": "tailscale", "vars": {"tailscale_ssh": True}},
        ]
    )
    assert [r["id"] for r in result] == ["tailscale", "packages", "commands"]
    by_id = {r["id"]: r["vars"] for r in result}
    assert by_id["tailscale"] == {"tailscale_accept_routes": True, "tailscale_ssh": True}
    assert by_id["packages"] == {"packages": []}
    assert by_id["commands"] == {"commands": ["echo hi"]}


def test_files_are_normalised():
    [_, files] = resolve_roles(
        [
            {
                "id": "files",
                "vars": {
                    "files": [
                        {"path": " /etc/motd ", "content": "hi", "mode": "644"},
                        {"path": "/opt/x", "owner": " ubuntu "},
                    ]
                },
            }
        ]
    )
    assert files == {
        "id": "files",
        "vars": {
            "files": [
                {"path": "/etc/motd", "content": "hi", "mode": "644", "owner": None},
                {"path": "/opt/x", "content": "", "mode": None, "owner": "ubuntu"},
            ]
        },
    }


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ([{"id": "nope"}], "Unknown role: nope"),
        ([{"id": "docker"}, {"id": "docker"}], "Role listed twice"),
        ([{"id": "docker", "vars": {"x": 1}}], "Unknown variables for docker: x"),
        ([{"id": "tailscale", "vars": {"tailscale_ssh": "yes"}}], "true or false"),
        ([{"id": "packages", "vars": {"packages": "curl"}}], "list of strings"),
        ([{"id": "packages", "vars": {"packages": ["curl", 1]}}], "list of strings"),
        ([{"id": "files", "vars": {"files": {}}}], "list of files"),
        ([{"id": "files", "vars": {"files": ["x"]}}], "entries must be objects"),
        ([{"id": "files", "vars": {"files": [{"path": "etc/x"}]}}], "must be absolute"),
        (
            [{"id": "files", "vars": {"files": [{"path": "/x", "mode": "rwx"}]}}],
            "mode must be octal",
        ),
        (
            [{"id": "files", "vars": {"files": [{"path": "/x", "mode": "0999"}]}}],
            "mode must be octal",
        ),
    ],
)
def test_invalid_selections_are_rejected(selection, message):
    with pytest.raises(RoleError, match=message):
        resolve_roles(selection)
