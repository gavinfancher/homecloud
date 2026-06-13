# Execution Guide — running the plan with multiple agents

This guide turns the phase docs (`00`–`08`) into delegable work. Each phase is sized for one
agent. Every agent must read `README.md` + `00-architecture.md` + its own phase doc before
writing code.

## Ground rules (every agent)

- **Scope:** implement exactly your phase's "Changes". If you find work that belongs to another
  phase, leave a `TODO(phase-XX):` and move on.
- **Branch:** one branch per phase, named `feat/<phase>-<slug>` (e.g. `feat/01-rename`). Open a
  PR into `main`; do not push to `main` directly. Do not commit secrets or `.env`.
- **Quality gate (definition of done):** `uv run pytest -q` and `uv run ruff check src/` pass,
  and your phase's **Acceptance criteria** are demonstrably met. Add tests described in your
  phase's "Testing" section.
- **Graceful degradation:** any external side effect (Cloudflare API, Caddy reload, CoreDNS
  zone write, SSH) must **no-op with a warning** when its creds/paths are unset, so local runs
  and other agents' tests keep working without full infra.
- **Long operations** (build, deploy, scan, DNS/proxy sync) run through the jobs system
  (`src/homecloud/jobs.py`) and persist to `.homecloud/state.json` via `src/homecloud/state.py`.
- **Do not deploy.** Land code + tests locally. A human (or a dedicated deploy step) ships to the
  control node — recent deploys broke from `rsync --delete`/path mistakes, so deployment is
  handled separately and deliberately.
- **Report back:** in the PR description, list each acceptance criterion with pass/fail and note
  any open questions or assumptions.

## Dependency graph

```
01 rename ─┬─► 02 sizes ───────────────► 07 ssh-key ─┐
           │                                          ├─► 08 web-ui
           ├─► 03 cloudflare-dns ─► 04 caddy+tunnel ─► 05 ports ─┤
           │                    └─► 06 split-dns ────────────────┘
           └─ (cleanup unblocks all)
```

- **01 must merge first** (rename touches many files; doing it first avoids conflicts).
- After 01: **02**, **03**, and **07** can proceed in parallel.
- **04** needs **03**. **05** needs **04**. **06** needs **03** (independent of 04).
- **08** is last; it consumes 02–06 endpoints.

## Waves (recommended)

| Wave | Phases (parallel)        | Notes                                                      |
| ---- | ------------------------ | --------------------------------------------------------- |
| 0    | Manual prereqs (below)   | Human task; gates 03/04/06. Start immediately.            |
| 1    | **01 rename**            | Merge before anything else.                               |
| 2    | **02 sizes**, **03 dns** | Independent; both small/testable.                         |
| 3    | **04 proxy+tunnel**, **06 split-dns** | 04 after 03; 06 after 03.                    |
| 4    | **05 ports**, **07 ssh** | 05 after 04; 07 after 02.                                 |
| 5    | **08 web-ui**            | After 02–06 land.                                         |

## Wave 0 — manual infra prerequisites (human, no code)

Collect these and put them in `.env` (and the control node's `.env`). Phases 03/04/06 are
blocked without them, but all phases can be *coded and unit-tested* without them thanks to the
no-op rule.

- **Cloudflare**
  - API token with `Zone:DNS:Edit` on `myhomecloud.dev` → `CLOUDFLARE_API_TOKEN`
  - Zone ID → `CLOUDFLARE_ZONE_ID`
  - Named Tunnel: create it, note the **UUID** (`CLOUDFLARE_TUNNEL_CNAME=<uuid>.cfargotunnel.com`)
    and the connector token (`CLOUDFLARE_TUNNEL_TOKEN`)
  - Cloudflare **Access**: self-hosted app on `*.myhomecloud.dev` + a **service token** for
    machine clients (note for Phase 04/05 health checks)
- **Tailscale**
  - Control node tailnet IP → `CONTROL_NODE_TAILSCALE_IP` (zone SOA + Caddy upstream base)
  - Confirm `TAILSCALE_API_KEY` / `TAILSCALE_AUTH_KEY` / `TAILSCALE_TAILNET` are set
  - Split DNS is configured in Phase 06 (admin console step, documented there)

## Per-phase kickoff briefs (copy-paste to the implementing agent)

Each brief assumes the agent has the repo and can run `uv`. Replace nothing; the phase docs hold
the detail.

### Phase 01 — rename
> Implement Phase 01. Read `plan/README.md`, `plan/00-architecture.md`, and
> `plan/01-rename-to-control-plane.md`. Rename the service from "agent" to "controller"
> (settings `controller_host/port` with `AGENT_*` back-compat, entrypoint, docs, UI copy) and do
> the grep sweep, **without** renaming `/api` routes, Python module paths, the `homecloud`
> binary, or third-party "guest agent" usages. Keep `proxy/` and `cloudflare/` modules unused.
> Gate: `uv run pytest -q` + `uv run ruff check src/` pass; add the port back-compat test. Do
> not deploy. Branch `feat/01-rename`, open a PR listing acceptance criteria results.

### Phase 02 — instance sizes
> Implement Phase 02. Read `plan/00-architecture.md` and `plan/02-instance-sizes-and-api.md`.
> Add `src/homecloud/sizes.py` with the preset table, `GET /api/sizes`, extend `DeployVMRequest`
> for `size_id` + custom fallback with clear 400s, and persist `size_id`. Keep the existing
> custom create path working. Add unit tests for size resolution. No UI. Gate + PR as in Phase
> 01. Branch `feat/02-sizes`.

### Phase 03 — Cloudflare DNS
> Implement Phase 03. Read `plan/00-architecture.md` and `plan/03-public-dns-cloudflare.md`.
> Add the `domain` + `cloudflare_*` settings and `.env.example` entries, then rewrite
> `src/homecloud/cloudflare/dns.py` to manage proxied CNAMEs per hostname idempotently, with
> `ensure_record`/`delete_record` and a disabled-mode no-op. Support multi-label labels like
> `grafana.app`. Unit-test normalization + disabled no-op (no network). Gate + PR. Branch
> `feat/03-cloudflare-dns`.

### Phase 04 — Caddy + Tunnel
> Implement Phase 04. Read `plan/00-architecture.md` and `plan/04-reverse-proxy-and-tunnel.md`
> (depends on Phase 03). Rewire `src/homecloud/proxy/caddy.py` to the new settings; add the
> `infra/caddy/Caddyfile`, the control-node compose services (caddy, cloudflared) with shared
> volumes, and a `publish_web`/`unpublish_web` helper that writes the Caddy site, calls Phase 03
> DNS, and records state. Reload via the Caddy admin API; no-op when unset. Unit-test site-file
> contents. Gate + PR. Branch `feat/04-proxy-tunnel`.

### Phase 05 — port discovery + service routing
> Implement Phase 05. Read `plan/00-architecture.md` and
> `plan/05-port-discovery-and-service-routing.md` (depends on Phase 04). Add
> `src/homecloud/ports.py` (`ss` over SSH, guest-agent fallback, parser), the scan job, and the
> `/scan-ports`, `/ports`, `/services` endpoints wired to `publish_web`/`unpublish_web`. Flag
> loopback-only ports as not publishable. Unit-test the parser with fixtures. Gate + PR. Branch
> `feat/05-ports`.

### Phase 06 — private split DNS
> Implement Phase 06. Read `plan/00-architecture.md` and `plan/06-private-split-dns.md`
> (depends on Phase 03 settings/state, independent of 04). Add `infra/coredns/Corefile`, the
> coredns compose service, and `src/homecloud/dns/zone.py` (`render_zone` + `write_zone` with a
> monotonic serial and disabled no-op). Regenerate the zone on instance/service changes.
> Document the Tailscale split-DNS admin step. Unit-test `render_zone`. Gate + PR. Branch
> `feat/06-split-dns`.

### Phase 07 — SSH key in base image
> Implement Phase 07. Read `plan/00-architecture.md` and `plan/07-ssh-key-base-image.md`
> (depends on Phase 02). Verify the key is baked at base-image build and survives templating;
> support multiple keys (`ssh_public_keys`) with back-compat; ensure controller→instance SSH
> works non-interactively; surface the "rebuild required for new keys" note. Unit-test
> single/many key setup. Gate + PR. Branch `feat/07-ssh-key`.

### Phase 08 — web UI
> Implement Phase 08. Read `plan/00-architecture.md` and `plan/08-web-ui.md` (after 02–06).
> Extend the vanilla-JS console: size selector + custom on create, a Networking panel on the
> instance detail (public web services + private tailnet access), port scan/publish/unpublish
> flows, and Activity-log surfacing of DNS/proxy/zone jobs. Degrade gracefully when
> Cloudflare/Caddy/CoreDNS are unconfigured. Manual click-through per the phase doc. Gate + PR.
> Branch `feat/08-web-ui`.

## Coordination notes

- Phases 03–06 each add settings to `src/homecloud/config.py`. To avoid merge churn, the
  **Phase 01 agent** should land the full settings block from `00-architecture.md §5` (all
  optional, empty defaults) as part of the rename PR, so later phases only *use* settings rather
  than re-adding them. If 01 has already merged without it, the first of 03/04/06 to start adds
  the block and others rebase.
- `state.py` gains helpers in 02/04/05/06. Keep additions additive and namespaced per the
  schema in `00-architecture.md §4`; resolve conflicts by union, never by overwrite.
- After each merge to `main`, a human runs the deploy to the control node (local tests are the
  gate; deployment is intentionally out of agents' hands).
