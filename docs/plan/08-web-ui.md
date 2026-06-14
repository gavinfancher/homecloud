# 08 — Web UI surfaces

## Objective

Expose the new capabilities in the existing console UI (`src/homecloud/static/`): sizes on the
create form, an instance detail view with networking (public web services + private access),
port discovery, and publish/unpublish actions.

## Context

- The UI is a vanilla JS console (sidebar nav, tables, detail view, jobs/activity log) in
  `src/homecloud/static/{index.html,app.js,style.css}`. It already polls the jobs API and has a
  VM detail page. Build on it; do not introduce a framework.
- APIs to consume: `/api/sizes` (02), `/api/vms` + `/api/vms/{name}` (existing, extended),
  `/api/vms/{name}/scan-ports`, `/ports`, `/services` (05), and the dashboard/jobs endpoints.

## Changes

1. **Create form** (`create` view):
   - Add a **size** selector (cards or a `<select>`) from `GET /api/sizes`; choosing a size sets
     the sliders; a **Custom** option re-enables the cores/memory/disk sliders.
   - Optional checkbox "Publish web (port 80) at `name.myhomecloud.dev`" (default off).
   - Live summary should show the resulting public hostname and the private (tailnet) name.
2. **Instance detail** (`vm-detail` view): add a **Networking** panel with two sections:
   - **Public web services**: table of `web[]` (service, port, `https://<host>`, public toggle,
     delete). A "Publish a port" button opens the port picker.
   - **Private access (Tailscale)**: show the tailnet name and the
     `access_summary`-style note that all TCP ports are reachable at
     `<instance>.myhomecloud.dev:<port>` on the tailnet; show a copy-able `psql`/`ssh` example.
3. **Port discovery**: a "Scan ports" button → calls `scan-ports`, streams the job log, then
   renders `ports_seen` as a table with a **Publish** action per row (prompts for a service
   label and public/private). Loopback-only ports are shown disabled with a tooltip explaining
   they must bind `0.0.0.0`/tailnet first.
4. **DNS/Activity**: surface DNS + proxy operations as jobs in the existing Activity log so the
   user sees record creation / Caddy reloads / zone writes.
5. **Settings**: show the configured `domain`, whether Cloudflare/Caddy/CoreDNS are enabled
   (from a `GET /api/dashboard` or `/api/setup` extension), and the split-DNS instructions.

## Acceptance criteria

- Creating an instance via the UI supports both size presets and custom.
- The detail page lists public web services and lets the user publish/unpublish a scanned port,
  with the URL becoming reachable.
- The private-access panel clearly explains tailnet name + ports.
- All long operations show in the Activity log with streaming logs.
- No console errors; works in a current Chromium.

## Testing

- Manual click-through of: create (size + custom), scan ports, publish, visit URL, unpublish,
  delete instance.
- Verify the UI degrades gracefully (clear messaging) when Cloudflare/Caddy/CoreDNS are not
  configured.

## Out of scope

- Auth/login for the console itself (future).
