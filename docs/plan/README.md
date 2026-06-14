# Homecloud Implementation Plan

This directory contains a phased implementation plan for evolving **homecloud** from a
basic Proxmox VM launcher into a small self-hosted cloud platform with public web
publishing, private database access, and automatic DNS + reverse proxy.

Each phase document is written as a self-contained brief for an implementing agent. Read
`00-architecture.md` first — it defines the terminology, network model, and decisions that
every phase depends on.

## Terminology (important)

The running service was previously called the **agent**. There is no AI involved, so we are
renaming it. Throughout this plan:

| Old term            | New term            | Meaning                                                        |
| ------------------- | ------------------- | ------------------------------------------------------------- |
| agent / orchestrator | **controller**      | The FastAPI service that manages VMs, DNS, and proxy config.  |
| —                   | **control plane**   | The whole homecloud system (controller + proxy + DNS).        |
| —                   | **control node**    | The dedicated VM that runs the controller + proxy + resolver. |
| workload VM         | **instance**        | A user-created VM running their workloads.                    |

Phase 01 performs the rename. Later phases assume the new names.

## What we are building

1. **Web UI + API** to create instances from a base image in selectable **sizes**.
2. **Public web publishing**: creating an instance named `app` makes it reachable at
   `app.myhomecloud.dev`; individual HTTP services on detected ports are published at
   `<service>.app.myhomecloud.dev`.
3. **Private database / TCP access** over Tailscale, using **split DNS** so the same
   `myhomecloud.dev` names resolve to private tailnet IPs when you are on the tailnet.
4. **Port discovery** on instances so the UI can offer to publish a listening port.
5. **SSH key baked into the base image** (done last; partially exists already).

## Network model (one-paragraph summary)

`myhomecloud.dev` is owned in Cloudflare. **Off the tailnet**, public web hostnames resolve
via Cloudflare → a Cloudflare Tunnel on the control node → Caddy → the instance's tailnet
IP:port. **On the tailnet**, Tailscale split DNS sends `myhomecloud.dev` lookups to a small
resolver on the control node, which answers with the instance's **tailnet IP** directly — so
databases and other TCP services stay private and never get a public record. See
`00-architecture.md` for the full design.

## Phases

| #   | File                                   | Outcome                                                       | Depends on |
| --- | -------------------------------------- | ------------------------------------------------------------ | ---------- |
| 00  | `00-architecture.md`                   | Architecture, naming, network planes, decisions              | —          |
| 01  | `01-rename-to-control-plane.md`        | Rename agent → controller; remove stale modules              | 00         |
| 02  | `02-instance-sizes-and-api.md`         | Size presets + custom; cleaned create API                    | 01         |
| 03  | `03-public-dns-cloudflare.md`          | Cloudflare DNS records per instance/service                  | 01         |
| 04  | `04-reverse-proxy-and-tunnel.md`       | Caddy + Cloudflare Tunnel on the control node                | 03         |
| 05  | `05-port-discovery-and-service-routing.md` | Detect ports; publish `<svc>.<vm>` web routes            | 04         |
| 06  | `06-private-split-dns.md`              | Local resolver + Tailscale split DNS for private TCP         | 03         |
| 07  | `07-ssh-key-base-image.md`            | Bake imported SSH key into the base image                     | 02         |
| 08  | `08-web-ui.md`                         | UI surfaces for sizes, publishing, ports, DNS                | 02–06      |

Recommended order: 00 → 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08. Phases 03–06 can overlap once
01 is done, but 04 needs 03 and 05 needs 04.

## Conventions for implementing agents

- Code lives in `src/homecloud/`. Tests in `tests/`. Run `uv run pytest -q` and
  `uv run ruff check src/` before declaring a phase done.
- Long-running operations (build, deploy, port scan, DNS sync) go through the existing
  **jobs** system (`src/homecloud/jobs.py`) so the UI can stream logs.
- All new persisted state goes in `.homecloud/state.json` via helpers in
  `src/homecloud/state.py` (do not invent new state files unless a phase says so).
- External side effects (Cloudflare API, Caddy reload, resolver reload) must **no-op
  gracefully** when their credentials/paths are not configured, logging a warning. This keeps
  local/dev runs working without full infra.
- Each phase has an **Acceptance criteria** section. Treat it as the definition of done.

## Open questions / decisions to confirm with the owner

These are resolved with a recommended default in `00-architecture.md`, but flag them if you
disagree while implementing:

1. **Public exposure** via Cloudflare Tunnel (recommended) vs. router port-forward + public
   IP + wildcard TLS. Plan assumes Tunnel.
2. **Resolver** for split DNS: CoreDNS (recommended) vs. dnsmasq/Technitium.
3. **Per-service wildcard DNS**: Cloudflare does not proxy multi-label wildcards
   (`*.app.myhomecloud.dev`) on non-Enterprise plans, so we create **explicit records per
   published service**. Confirm this is acceptable.
4. **Auth on public services**: **decided** — the `myhomecloud.dev` zone sits behind
   **Cloudflare Access**. Published web hostnames are gated at the edge by Access policies, not
   open to the world. Implications:
   - The controller console is reached over the tailnet (`http://<control-node>:8080`) and is
     intentionally **not** behind Access (no lockout risk, no Access dependency to manage VMs).
   - Machine-to-machine access to a published hostname needs an **Access service token** or a
     bypass policy; document per service when needed.
   - Phases 03/04 do not need to implement Access; a wildcard/self-hosted Access app on
     `*.myhomecloud.dev` covers new hostnames automatically. Optional future work: have the
     controller create per-hostname Access apps/policies via the Cloudflare API.
