from homecloud.ports import parse_ss_output


def test_ipv4_with_process_name():
    out = 'LISTEN 0 4096 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=812,fd=3))\n'
    assert parse_ss_output(out) == [
        {"port": 22, "proc": "sshd", "address": "0.0.0.0", "publishable": True}
    ]


def test_without_process_column():
    [entry] = parse_ss_output("LISTEN 0 511 10.0.0.5:8080 0.0.0.0:*")
    assert entry == {"port": 8080, "proc": None, "address": "10.0.0.5", "publishable": True}


def test_ipv6_wildcard_and_loopback():
    out = "\n".join(
        [
            'LISTEN 0 4096 [::]:443 [::]:* users:(("caddy",pid=1,fd=7))',
            "LISTEN 0 4096 [::1]:5432 [::]:*",
        ]
    )
    wildcard, loopback = parse_ss_output(out)
    assert wildcard == {"port": 443, "proc": "caddy", "address": "::", "publishable": True}
    assert loopback["address"] == "::1"
    assert loopback["publishable"] is False
    assert "loopback" in loopback["not_publishable_reason"]


def test_star_is_normalised_to_ipv4_wildcard():
    [entry] = parse_ss_output("LISTEN 0 128 *:80 *:*")
    assert entry["address"] == "0.0.0.0"
    assert entry["port"] == 80


def test_ipv4_loopback_not_publishable():
    [entry] = parse_ss_output("LISTEN 0 128 127.0.0.1:6379 0.0.0.0:*")
    assert entry["publishable"] is False
    assert entry["not_publishable_reason"]


def test_ipv4_and_ipv6_on_same_port_are_distinct():
    out = "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 128 [::]:22 [::]:*\n"
    assert [(e["address"], e["port"]) for e in parse_ss_output(out)] == [
        ("0.0.0.0", 22),
        ("::", 22),
    ]


def test_dedup_keeps_first_occurrence():
    out = "\n".join(
        [
            'LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1,fd=6))',
            'LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=2,fd=6))',
            'LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:(("other",pid=3,fd=6))',
        ]
    )
    [entry] = parse_ss_output(out)
    assert entry["proc"] == "nginx"


def test_first_process_name_wins_when_several_share_a_socket():
    out = 'LISTEN 0 128 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=2,fd=6),("nginx-w",pid=3,fd=6))'
    assert parse_ss_output(out)[0]["proc"] == "nginx"


def test_skips_blank_short_and_malformed_lines():
    out = "\n".join(
        [
            "",
            "   ",
            "LISTEN 0 128",
            "LISTEN 0 128 noport 0.0.0.0:*",
            "LISTEN 0 128 0.0.0.0:http 0.0.0.0:*",
            "LISTEN 0 128 [::1 [::]:*",
            "LISTEN 0 128 0.0.0.0:9000 0.0.0.0:*",
        ]
    )
    assert [e["port"] for e in parse_ss_output(out)] == [9000]


def test_empty_output():
    assert parse_ss_output("") == []
