# Cloudflare

Zones, tunnels, and the `gavinf-prod` Worker that fronts every `gavinf.com` site.

## In this section

- [Tunnel & DNS](/cloudflare/tunnel) — zone setup, the tunnel ingress, and Caddy routing

## Sites

`gavinf-prod` is one Worker + one Workers Assets bundle serving four hosts:

| Host | Serves |
|---|---|
| `gavinf.com`, `auth.gavinf.com`, `dash.gavinf.com` | portal SPA |
| `homecloud.gavinf.com` | console SPA |
| `docs.gavinf.com` | this site |
| `proxmox.gavinf.com` | rail shell + passthrough to the tunnel origin |

Routing lives in `worker.js`, keyed off `request.url`'s hostname — see [Tunnel & DNS](/cloudflare/tunnel).
