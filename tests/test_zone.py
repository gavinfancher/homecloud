from homecloud.dns import zone

INSTANCES = {
    "pixie": {"vmid": 501, "tailscale_ip": "100.125.128.54"},
    "pending": {"vmid": 503, "tailscale_ip": None},
}


def test_render_zone_has_name_and_wildcard_per_instance(settings, monkeypatch):
    monkeypatch.setattr(settings, "owner_username", "")
    text = zone.render_zone(INSTANCES, "100.74.161.39", serial=1, domain="vm.gavinf.com")
    lines = text.splitlines()
    assert lines[0] == "$ORIGIN vm.gavinf.com."
    assert any(line.split() == ["pixie", "IN", "A", "100.125.128.54"] for line in lines)
    assert any(line.split() == ["*.pixie", "IN", "A", "100.125.128.54"] for line in lines)
    assert "pending" not in text  # no tailnet IP yet → no record


def test_write_zone_serves_current_and_legacy_zones(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "domain", "vm.gavinf.com")
    legacy = " vm.dns.gavinf.com, vm.homecloud.gavinf.com , "
    monkeypatch.setattr(settings, "dns_legacy_domains", legacy)
    monkeypatch.setattr(settings, "coredns_zone_dir", str(tmp_path))
    monkeypatch.setattr(settings, "control_node_tailscale_ip", "100.74.161.39")
    monkeypatch.setattr(zone, "list_registered_vms", lambda: INSTANCES)

    assert zone.zone_domains() == [
        "vm.gavinf.com",
        "vm.dns.gavinf.com",
        "vm.homecloud.gavinf.com",
    ]
    zone.write_zone()

    for domain in zone.zone_domains():
        text = (tmp_path / f"db.{domain}").read_text()
        assert text.startswith(f"$ORIGIN {domain}.")
        assert "100.125.128.54" in text


def test_write_zone_skips_without_zone_dir(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "coredns_zone_dir", str(tmp_path / "missing"))
    zone.write_zone()  # no error, nothing written
    assert not (tmp_path / "missing").exists()
