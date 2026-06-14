# 04 — Reverse proxy (Caddy) + Cloudflare Tunnel

## Objective

Run a Cloudflare Tunnel + Caddy on the control node so that public hostnames created in
Phase 03 actually reach the right instance port. Generate Caddy site configs from the
controller.

## Context

- `src/homecloud/proxy/caddy.py` already writes per-host `*.caddy` files and reloads Caddy, but
  references removed settings. This phase rewires it to `00-architecture.md §5`.
- Upstream target = the instance's **tailnet IP** (control node is on the tailnet).

## Infra (control node `docker-compose.yml`)

Add services alongside the controller (shared volumes so the controller writes config the
others read):

```yaml
services:
  controller:            # existing homecloud app (renamed)
    # ...
    volumes:
      - ./.homecloud:/app/.homecloud
      - ./ssh:/mnt/ssh:ro
      - caddy_sites:/etc/caddy/sites          # controller WRITES site files
      - coredns_zones:/etc/coredns            # Phase 06
    environment:
      - CADDY_CONFIG_DIR=/etc/caddy/sites
      - CADDY_RELOAD_CMD=                      # see note below

  caddy:
    image: caddy:2
    restart: unless-stopped
    volumes:
      - ./infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_sites:/etc/caddy/sites          # caddy READS site files
    # no public ports needed; cloudflared reaches it over the compose network

  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on: [caddy]

volumes:
  caddy_sites:
  coredns_zones:
```

`infra/caddy/Caddyfile` (root) imports per-site files:

```
{
    admin 0.0.0.0:2019
}
import /etc/caddy/sites/*.caddy
```

Cloudflare Tunnel ingress (configured in the Cloudflare dashboard for the named tunnel):
`*.myhomecloud.dev` and `myhomecloud.dev` → `http://caddy:80`. (The tunnel runs in the same
compose network as caddy; service name `caddy` resolves.)

**Reload approach:** prefer Caddy's admin API or `caddy reload`. Since the controller is a
separate container, set `CADDY_RELOAD_CMD` to hit the admin endpoint, e.g.
`curl -s -X POST http://caddy:2019/load ...`, **or** rely on Caddy watching the imported files.
Simplest robust option: have the controller POST to the Caddy admin API
(`http://caddy:2019`). Document whichever you implement.

## Changes (code)

1. **Rewire** `src/homecloud/proxy/caddy.py` to use `settings.caddy_config_dir`,
   `settings.caddy_reload_cmd`, `settings.domain`. Keep `ensure_route(hostname, upstream_host,
   upstream_port)` and `remove_route(hostname)`. Make reload no-op gracefully when the command
   is empty.
2. Each `*.caddy` file should serve the public host and proxy to the instance tailnet IP:port:
   ```
   grafana.app.myhomecloud.dev {
       reverse_proxy 100.x.x.x:3000
   }
   ```
   (TLS is handled at the Cloudflare edge; Caddy speaks plain HTTP to the tunnel. Disable
   Caddy auto-HTTPS for these sites or bind only on :80.)
3. A small orchestration helper `publish_web(instance, service, port, public=True)` that:
   - writes/updates the Caddy site (`<service>.<instance>` host → `tailnet_ip:port`),
   - if `public`, calls Phase 03 `ensure_record("<service>.<instance>")`,
   - records the mapping in state (`web[]`).
   And `unpublish_web(instance, service)` that reverses both + state.
   (Phase 05 wires this to the UI/port discovery; define it here.)

## Acceptance criteria

- `docker compose up -d` on the control node starts controller + caddy + cloudflared.
- `publish_web(...)` writes a `*.caddy` file, reloads Caddy, creates the Cloudflare record, and
  records state; `unpublish_web(...)` reverses all three.
- Visiting `https://<service>.<instance>.myhomecloud.dev` from off-tailnet reaches the
  instance's service.
- Reload/DNS calls no-op cleanly when their creds/paths are unset.
- `uv run ruff check src/` passes.

## Testing

- Unit-test the Caddy file contents and path for a given host/upstream, and the disabled-reload
  no-op.
- Manual end-to-end with a real service on a test instance.

## Out of scope

- Detecting which ports exist (Phase 05). Here you publish a known port.
