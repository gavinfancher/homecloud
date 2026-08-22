# Proxmox

The hypervisor behind homecloud. A single node, `pve-root`, reached over
Tailscale at `100.106.79.65:8006` — it is not exposed publicly.

## In this section

- [VM status API](/proxmox/vm-status) — what `status/current` returns, field by field

## Access

API tokens authenticate with a `PVEAPIToken=user@realm!tokenid=secret` header.
Credentials live in `.env` at the repo root (`PROXMOX_*`), and the node's
self-signed certificate means `verify_ssl` is off — acceptable only because the
transport is already a Tailscale tunnel.

`ProxmoxClient` in `src/homecloud/proxmox/client.py` wraps `proxmoxer` and reads
all of this from `settings`; prefer it over hand-rolled requests in application
code.

## Layout

- VM `500` — `homecloud`, the control plane itself
- `8001` (`tpl-homecloud-base`), `9100` (`cloudimg-debian-12`) — templates that
  new instances are cloned from
- Storage `local-lvm`, bridge `vmbr0`, snippets in `/var/lib/vz/snippets`
