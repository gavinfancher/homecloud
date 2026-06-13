# 05 — Port discovery + service routing

## Objective

Detect which TCP ports an instance is listening on, show them in the UI, and let the user
publish a chosen port as `<service>.<instance>.myhomecloud.dev` (web) with one action.

## Context

- The control node can reach instances over the tailnet and has the baked SSH key
  (Phase 07 / existing setup key). It can also use the Proxmox QEMU guest agent
  (`ProxmoxClient.guest_exec`).
- Phase 04 provides `publish_web(instance, service, port, public)` /
  `unpublish_web(instance, service)`.

## Design

### Port scan

Add `src/homecloud/ports.py` with a `scan_ports(instance) -> list[dict]`:

- Preferred: SSH to `vm_ssh_user@<tailnet_ip>` and run
  `ss -H -tlnp` (or `ss -H -tln` without `-p` if not root) to list listening TCP sockets.
- Fallback: `ProxmoxClient.guest_exec(vmid, ["ss","-H","-tln"])`.
- Parse into `[{"port": 3000, "proc": "grafana", "address": "0.0.0.0"}]`. De-dupe, drop
  loopback-only unless asked, always include the bind address so the UI can warn about
  `127.0.0.1`-only services (those need the service reconfigured to bind `0.0.0.0` or a
  tailnet address before they can be proxied).
- Run as a **job** so the UI streams progress; persist results to
  `state.vms[instance].ports_seen` + `ports_scanned_at`.

### Routes (API)

- `POST /api/vms/{name}/scan-ports` → returns a `job_id`; on completion stores `ports_seen`.
- `GET /api/vms/{name}/ports` → last scan results from state.
- `POST /api/vms/{name}/services` body `{service, port, public: bool}` → calls
  `publish_web(...)`; returns the resulting record/host. Validates `service` matches
  `^[a-z][a-z0-9-]{1,30}$` and that `port` was seen (or allow override with a flag).
- `DELETE /api/vms/{name}/services/{service}` → `unpublish_web(...)`.
- `GET /api/vms/{name}` (existing) should include `web[]` and `ports_seen` in its response.

### Primary web host

When an instance is created, optionally publish its base host `app.myhomecloud.dev` →
`tailnet_ip:default_web_port` if a web port is detected. Make this opt-in (a checkbox in the UI;
default off) to avoid publishing things by accident.

## Acceptance criteria

- `POST /api/vms/{name}/scan-ports` returns a job; after it completes, `GET .../ports` lists the
  instance's listening TCP ports with process names where available.
- `POST /api/vms/{name}/services {service:"grafana", port:3000, public:true}` makes
  `https://grafana.app.myhomecloud.dev` reach the service, and records it in `web[]`.
- Deleting the service removes the Caddy route, the Cloudflare record, and the state entry.
- Loopback-only ports are clearly flagged as not publishable as-is.
- `uv run pytest -q` and `uv run ruff check src/` pass.

## Testing

- Unit-test the `ss` output parser with sample fixtures (root and non-root formats, IPv4/IPv6,
  loopback vs wildcard binds).
- Manual: run a container on a test instance, scan, publish, hit the URL, unpublish.

## Out of scope

- TCP/database routing (Phase 06 — that is tailnet-direct, not via Caddy).
- UI (Phase 08), though the endpoints here are what the UI calls.
