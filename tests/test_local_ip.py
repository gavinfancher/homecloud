"""LAN address discovery — the guest-agent payload must yield the local IP,
not the loopback, tailnet, or container-bridge addresses."""
from __future__ import annotations

from homecloud.proxmox.client import ProxmoxClient

LAN_IP = "192.168.1.42"


def _iface(name: str, *ips: str) -> dict:
    return {
        "name": name,
        "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": ip} for ip in ips],
    }


def test_picks_lan_address_over_loopback_and_tailnet():
    interfaces = [
        _iface("lo", "127.0.0.1"),
        _iface("tailscale0", "100.101.102.103"),
        _iface("eth0", LAN_IP),
    ]
    assert ProxmoxClient._lan_ip_from_interfaces(interfaces) == LAN_IP


def test_skips_container_bridges():
    interfaces = [
        _iface("docker0", "172.17.0.1"),
        _iface("br-1a2b3c", "172.18.0.1"),
        _iface("ens18", LAN_IP),
    ]
    assert ProxmoxClient._lan_ip_from_interfaces(interfaces) == LAN_IP


def test_unwraps_result_envelope():
    payload = {"result": [_iface("eth0", LAN_IP)]}
    assert ProxmoxClient._lan_ip_from_interfaces(payload) == LAN_IP


def test_ignores_ipv6_and_link_local():
    interfaces = [
        {
            "name": "eth0",
            "ip-addresses": [
                {"ip-address-type": "ipv6", "ip-address": "fe80::1"},
                {"ip-address-type": "ipv4", "ip-address": "169.254.10.1"},
                {"ip-address-type": "ipv4", "ip-address": LAN_IP},
            ],
        }
    ]
    assert ProxmoxClient._lan_ip_from_interfaces(interfaces) == LAN_IP


def test_returns_none_when_only_tailnet_is_up():
    assert ProxmoxClient._lan_ip_from_interfaces([_iface("tailscale0", "100.64.0.7")]) is None


def test_returns_none_for_empty_payload():
    assert ProxmoxClient._lan_ip_from_interfaces(None) is None
    assert ProxmoxClient._lan_ip_from_interfaces([]) is None


def test_cgnat_range_is_not_a_lan_address():
    # A VM on 100.x could legitimately be a public range outside CGNAT.
    assert ProxmoxClient._is_lan_ipv4("100.64.0.1") is False
    assert ProxmoxClient._is_lan_ipv4("100.127.255.255") is False
    assert ProxmoxClient._is_lan_ipv4("100.63.255.255") is True
    assert ProxmoxClient._is_lan_ipv4("not-an-ip") is False
