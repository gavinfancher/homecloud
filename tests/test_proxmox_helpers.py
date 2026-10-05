import pytest

from homecloud.proxmox.client import ProxmoxClient, _nic_mac


@pytest.mark.parametrize(
    ("net", "mac"),
    [
        ("virtio=BC:24:11:AA:BB:CC,bridge=vmbr0", "BC:24:11:AA:BB:CC"),
        ("bridge=vmbr0,virtio=bc:24:11:aa:bb:cc,firewall=1", "bc:24:11:aa:bb:cc"),
        ("e1000=00:11:22:33:44:55", "00:11:22:33:44:55"),
        ("bridge=vmbr0", None),
        ("virtio=BC:24:11:AA:BB,bridge=vmbr0", None),
        ("", None),
    ],
)
def test_nic_mac(net, mac):
    assert _nic_mac(net) == mac


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("10.0.0.42", True),
        ("192.168.1.5", True),
        ("100.63.255.255", True),
        ("100.64.0.1", False),  # tailnet CGNAT
        ("100.127.255.254", False),
        ("127.0.0.1", False),
        ("169.254.1.1", False),
        ("0.0.0.0", False),
        ("fe80::1", False),
        ("2001:db8::1", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_is_lan_ipv4(ip, expected):
    assert ProxmoxClient._is_lan_ipv4(ip) is expected


def _iface(name, *addrs):
    return {
        "name": name,
        "ip-addresses": [
            {"ip-address-type": kind, "ip-address": ip, "prefix": 24} for kind, ip in addrs
        ],
    }


def test_lan_ip_skips_loopback_tailscale_and_container_bridges():
    interfaces = [
        _iface("lo", ("ipv4", "127.0.0.1")),
        _iface("tailscale0", ("ipv4", "100.101.102.103")),
        _iface("docker0", ("ipv4", "172.17.0.1")),
        _iface("br-1a2b3c", ("ipv4", "172.18.0.1")),
        _iface("veth123", ("ipv4", "172.19.0.1")),
        _iface("eth0", ("ipv6", "fe80::1"), ("ipv4", "10.0.0.42")),
    ]
    assert ProxmoxClient._lan_ip_from_interfaces(interfaces) == "10.0.0.42"


def test_lan_ip_accepts_guest_agent_result_envelope():
    payload = {"result": [_iface("ens18", ("ipv4", "192.168.1.20"))]}
    assert ProxmoxClient._lan_ip_from_interfaces(payload) == "192.168.1.20"


def test_lan_ip_does_not_skip_nics_that_merely_start_with_lo():
    interfaces = [_iface("lowpan0", ("ipv4", "10.1.1.1"))]
    assert ProxmoxClient._lan_ip_from_interfaces(interfaces) == "10.1.1.1"


def test_lan_ip_skips_cgnat_on_a_real_nic():
    interfaces = [_iface("eth0", ("ipv4", "100.64.1.1"), ("ipv4", "10.0.0.7"))]
    assert ProxmoxClient._lan_ip_from_interfaces(interfaces) == "10.0.0.7"


@pytest.mark.parametrize("payload", [None, [], {"result": []}, [_iface("eth0")]])
def test_lan_ip_none_when_nothing_usable(payload):
    assert ProxmoxClient._lan_ip_from_interfaces(payload) is None


@pytest.mark.parametrize(
    ("config", "size"),
    [
        ({"scsi0": "local-lvm:vm-500-disk-0,iothread=1,size=40G"}, 40),
        ({"scsi0": "local-lvm:vm-500-disk-0,size=3584M"}, None),
        ({"scsi0": "local-lvm:vm-500-disk-0"}, None),
        ({}, None),
    ],
)
def test_disk_gb_from_config(config, size):
    assert ProxmoxClient._disk_gb_from_config(config) == size
