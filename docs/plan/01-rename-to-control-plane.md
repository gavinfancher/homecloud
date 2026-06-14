# 01 — Rename agent → controller; remove stale modules

## Objective

Adopt the new terminology (see `README.md`) and remove dead code so later phases build on a
clean base. No new features.

## Context

- The service is referred to as "agent" in settings, CLI, docs, and infra. There is no AI; we
  use **controller** (service) / **control plane** (system) / **control node** (host VM).
- `src/homecloud/proxy/caddy.py` and `src/homecloud/cloudflare/dns.py` import settings that no
  longer exist (`settings.domain`, `settings.caddy_config_dir`, `settings.cloudflare_*`,
  `settings.tailscale_ssh_user`). They are not wired into the app but will crash if imported.
  Leave the files in place (Phases 03/04 rewrite them) but ensure nothing imports them yet.

## Changes

1. **Settings** (`src/homecloud/config.py`): rename `agent_host`/`agent_port` →
   `controller_host`/`controller_port`. Keep env var compatibility by reading both
   (`AGENT_HOST`/`CONTROLLER_HOST`) — use pydantic `AliasChoices` or a validator so existing
   `.env` files keep working. Default port stays `8080`.
2. **Entrypoint** (`src/homecloud/main.py`): update the `uvicorn.run` host/port references and
   the FastAPI `title`/`description` to "Homecloud Controller". Keep the console-script name
   `homecloud` (it is the binary name, not the term).
3. **Docs**: update `README.md` top-level to use controller/control node/instance.
4. **`.env.example`**: rename keys with a comment noting the old names are still accepted.
5. **UI copy** (`src/homecloud/static/`): replace user-facing "agent" with "controller"
   (e.g. the sidebar footer "Agent online" → "Controller online"). Endpoint paths under
   `/api` do **not** change in this phase to avoid churn.
6. **Grep sweep**: `rg -i "agent|orchestrator"` and update comments/strings, except the
   `homecloud` binary name and any third-party references (e.g. Proxmox "guest agent",
   Tailscale). Be careful not to rename "QEMU guest agent" usages in `proxmox/client.py`.
7. **Land the settings block** (coordination): add the full optional settings block from
   `00-architecture.md §5` (`domain`, `cloudflare_*`, `caddy_*`, `coredns_*`,
   `control_node_tailscale_ip`, `default_web_port`) with safe empty defaults, plus matching
   `.env.example` entries. They are unused this phase, but landing them here lets Phases 03–06
   only *use* settings instead of each re-adding them (avoids merge churn). Adding settings must
   not break startup or the stale-settings grep check below (those modules will start resolving
   real settings, which is fine — they remain unimported).

## Out of scope

- Renaming `/api` routes or Python module paths.
- Touching the stale `proxy/`, `cloudflare/` modules beyond confirming they are unused.

## Acceptance criteria

- `uv run pytest -q` and `uv run ruff check src/` pass.
- App starts with an existing `.env` that still uses `AGENT_PORT` (compat preserved).
- No user-facing "agent"/"orchestrator" wording remains in UI or README (excluding the
  binary name and third-party "guest agent").
- The stale modules remain **unimported** by the app: `rg -n "settings\.(domain|caddy_|cloudflare_|tailscale_ssh_user)"`
  shows usages only in `proxy/caddy.py`, `cloudflare/dns.py`, and `tailscale/ssh_config.py`.
  (After step 7 these settings are now *defined* in `config.py`, but the modules using them are
  still not imported anywhere in the active code path.) `tailscale_ssh_user` specifically is a
  leftover in `ssh_config.py`; do not add it as a setting — the active code uses `vm_ssh_user`.
  Phase 06 reuses `access_summary` from that module and will fix the reference then.

## Testing

- Add a small test asserting `settings.controller_port == 8080` and that setting `AGENT_PORT`
  in the environment is still honored.
