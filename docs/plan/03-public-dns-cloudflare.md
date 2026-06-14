# 03 — Public DNS via Cloudflare

## Objective

Programmatically manage `myhomecloud.dev` DNS records so that publishing an instance or a
service creates the right public hostname pointing at the Cloudflare Tunnel.

## Context

- `src/homecloud/cloudflare/dns.py` already implements create/update/delete of a proxied CNAME
  → tunnel CNAME, but references settings that were removed. This phase **rewires it** to the
  settings added in `00-architecture.md §5` and generalizes it for arbitrary hostnames.
- Records must be **proxied** (orange cloud) CNAMEs to `<tunnel-id>.cfargotunnel.com`.
- Multi-label wildcards are not proxied on non-Enterprise plans → create **explicit** records
  per hostname (`app`, `grafana.app`, ...).

## Changes

1. **Config**: ensure settings exist: `domain`, `cloudflare_api_token`, `cloudflare_zone_id`,
   `cloudflare_tunnel_cname` (full `<id>.cfargotunnel.com`). Add to `.env.example`.
2. **Rewrite** `src/homecloud/cloudflare/dns.py`:
   - `enabled` property = all of token/zone/tunnel set.
   - `ensure_record(host_label: str) -> dict`: create/update proxied CNAME for
     `<host_label>.myhomecloud.dev` → tunnel; idempotent (lookup by name first); returns
     `{hostname, record_id, content}`. When `not enabled`, log a warning and return
     `{"skipped": True, "hostname": ...}` (no crash).
   - `delete_record(host_label: str)`: remove matching records; no-op when disabled.
   - `host_label` is the part before `.myhomecloud.dev` and may contain dots
     (`grafana.app`). Handle FQDN-or-label inputs.
3. **Tooling helper**: a thin module function or method the proxy/port phases call, e.g.
   `publish_dns(hostname)` / `unpublish_dns(hostname)`.

## Manual infra prerequisites (document in the phase output, do not automate here)

- Create a Cloudflare API token scoped to **Zone:DNS:Edit** for `myhomecloud.dev`.
- Create a **named Cloudflare Tunnel** (Phase 04 runs the connector); note its UUID; the CNAME
  target is `<uuid>.cfargotunnel.com`.
- Put `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_TUNNEL_CNAME` in `.env`.

## Acceptance criteria

- With creds set, calling `ensure_record("app")` creates a proxied CNAME
  `app.myhomecloud.dev → <uuid>.cfargotunnel.com` and is idempotent on repeat.
- `ensure_record("grafana.app")` creates `grafana.app.myhomecloud.dev` similarly.
- `delete_record(...)` removes them.
- With creds **unset**, both functions no-op and log, and the app still runs.
- `uv run ruff check src/` passes.

## Testing

- Unit-test label/FQDN normalization and the disabled-mode no-op without network.
- Live test (manual, behind the `CLOUDFLARE_*` env gate) creating/deleting a throwaway record.

## Out of scope

- The tunnel connector and Caddy (Phase 04). This phase only manages DNS records.
