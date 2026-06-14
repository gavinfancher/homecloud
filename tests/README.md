# Tests

Pytest suite for the controller (`src/homecloud`). Run via `make test` or `pytest -q`.

| File | Covers |
|------|--------|
| `test_auth.py` | Clerk JWT / forward-auth helpers |
| `test_caddy.py` | Caddy config generation and reload |
| `test_cloudflare_dns.py` | Cloudflare DNS API (integration-style; needs creds) |
| `test_config.py` | Settings / env loading |
| `test_dns_zone.py` | CoreDNS zone rendering, fallthrough, instance records |
| `test_hostnames.py` | MagicDNS / FQDN helpers |
| `test_lifecycle.py` | VM deploy cancel / Tailscale wait |
| `test_ports.py` | Port discovery via SSH / publish routing |
| `test_proxmox_integration.py` | Live Proxmox smoke (skipped without env) |
| `test_publish_web.py` | Public web publish + Access headers |
| `test_sizes.py` | Instance size presets API |
| `test_ssh_keys.py` | Cloud-init SSH key injection |

Frontend lint/build is exercised in CI (`npm run lint` / `build`) but has no dedicated
test files yet.
