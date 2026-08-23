# homecloud

A self-hosted mini-cloud: a control plane that provisions VMs on a Proxmox
hypervisor with one API call, joins them to a private WireGuard mesh
(Tailscale), and optionally publishes their web services to the internet
through a Cloudflare Tunnel — with SSO in front of everything.

Think "tiny AWS for a homelab": instances, images, private DNS, public
ingress, and a web console, all driven by a single FastAPI service.

```
                        ┌──────────────── Cloudflare edge ────────────────┐
   you (anywhere) ──►   │  gavinf-homecloud Worker     Tunnel (cloudflared)│
                        │  └─ homecloud (console SPA)    ▼                 │
                        │     (gavinf.com + proxmox live  Caddy ── controller│
                        │      in the gavinf repo)         │                │
                        └──────────────────────────────│──────────────────┘
                                                       │ control node VM
   you (on tailnet) ──► CoreDNS (split DNS) ───────────┤  docker compose:
        *.vm.homecloud.gavinf.com → tailnet IPs        │  controller · caddy
                                                       │  cloudflared · coredns
                                                       ▼
                                             Proxmox API + SSH
                                             (cloud-init, VM lifecycle)
                                                       │
                                          instances join the tailnet
```

## What it does

- **Instance lifecycle** — create / start / stop / suspend / resume / delete
  Proxmox VMs through a REST API, with async jobs and streamed provisioning
  logs (`POST /api/vms` returns a `job_id`; poll `/api/jobs/{id}`).
- **Image pipeline** — builds a cloud-init base template on Proxmox and clones
  instances from it; per-app deploy specs are Jinja2 cloud-init templates.
- **Custom images** — pick an upstream distro cloud image (Ubuntu, Debian,
  Fedora, Rocky), declare the packages, config files, and shell commands you
  want baked in, and the controller downloads the image onto the node, imports
  it, bakes your definition in via cloud-init, and converts the result to a
  reusable Proxmox template. Definitions live in Postgres; the downloaded base
  is cached so only the first build pays for it.
- **Zero-config networking** — every instance auto-joins the Tailscale
  tailnet; SSH works from anywhere via MagicDNS with no port forwarding.
- **Private DNS** — the controller renders an RFC 1035 zone file and serves
  `*.vm.homecloud.gavinf.com` → tailnet IPs via CoreDNS + Tailscale split DNS.
- **Public ingress on demand** — "publish" an instance port and the controller
  writes a Caddy site, creates the Cloudflare DNS record pointing at the
  tunnel, and reloads the proxy. Published apps sit behind Clerk forward-auth.
- **Port discovery** — scans an instance for listening services so the console
  can offer one-click publishing.
- **Auth everywhere** — Clerk JWTs on the API (issuer/JWKS/azp verified),
  Clerk session gate on published apps via Caddy `forward_auth`, fail-closed
  in production and fail-open (loudly) for local dev.
- **Web console** — React SPA for instances, images, jobs, and activity, plus
  a portal/dashboard and a unified navigation rail shared across sites
  (including a wrapped Proxmox UI).

## Stack

| Layer | Tech |
|---|---|
| Control plane | Python 3.12, FastAPI, Pydantic Settings, uv |
| Virtualization | Proxmox VE (API + SSH cloud-init snippets) |
| Networking | Tailscale (WireGuard mesh, MagicDNS, split DNS), CoreDNS |
| Ingress | Cloudflare Tunnel, Caddy, Cloudflare DNS API |
| Auth | Clerk (JWT verification, forward-auth SSO cookie) |
| Data | Postgres 18.4 + SQLAlchemy (image catalog and custom image definitions) |
| Web | React + TypeScript + Vite, single Cloudflare Worker serving all sites |
| Runtime | Docker Compose on a control-node VM |
| CI/CD | GitHub Actions (tests + self-hosted-runner backend deploy), Cloudflare Workers Git (web) |
| Tests | pytest — 185 tests across auth, DNS, proxy, ports, lifecycle |

## Repo layout

```
src/homecloud/       Controller (FastAPI)
  api/               REST routes + schemas
  proxmox/           Proxmox API client (VM lifecycle, cloud-init)
  images/            Image builder, cloud image catalog/importer, cloud-init
                     composer, image store, app deployer
  db/                SQLAlchemy models + session (Postgres)
  tailscale/         Tailscale API client + SSH config helpers
  cloudflare/        Idempotent DNS records → tunnel
  dns/               Zone rendering for CoreDNS (private split DNS)
  proxy/             Caddy site management + reload
  ports.py           Service discovery on instances
  publish.py         Publish flow (Caddy + DNS + state)
  auth.py            Clerk JWT verification / forward-auth target
  jobs.py, state.py  Async job runner, persistent state
frontend/            Console SPA (homecloud.gavinf.com), deployed as the
                     gavinf-homecloud Worker (see docs/deploy-web.md)
infra/
  docker/            Dockerfile + compose stack (controller, caddy,
                     cloudflared, coredns)
  caddy/, coredns/   Base proxy config, split-DNS Corefile
scripts/             Bootstrap + deploy helpers for the control node
ssh/                 SSH config mounted into the controller for Proxmox
                     access — keys and the real config live only on the
                     control node; ssh/config.example is the tracked template
tests/               Pytest suite
docs/                Deploy runbooks + archived design/implementation plan
```

## Run it

On the control node (or any Docker host that can reach Proxmox):

```bash
cp .env.example .env        # Proxmox host/token, Tailscale keys, Clerk, domain
cp ssh/config.example ssh/config   # point "pve" at your Proxmox host
# place the Proxmox SSH keypair in ssh/ (compose mounts it read-only into
# the controller; both the keys and ssh/config are gitignored)
docker compose -f infra/docker/docker-compose.yml up -d --build
curl localhost:8080/api/health
```

Local development:

```bash
make install    # editable Python install + npm install
make test       # pytest + frontend lint/build
make dev-api    # uvicorn with reload
make dev-web    # Vite dev server
```

## Create an instance

```bash
curl -X POST https://homecloud-api.gavinf.com/api/vms \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "dagster", "cores": 2, "memory_gb": 4, "disk_gb": 20}'
# → {"job_id": "..."}   poll /api/jobs/{id} for provisioning logs
```

A few minutes later: `ssh ubuntu@dagster` over the tailnet, private DNS at
`dagster.vm.homecloud.gavinf.com`, and one API call away from a public URL.

## API surface

| Endpoint | Description |
|---|---|
| `GET  /api/dashboard` | Overview stats |
| `POST /api/vms` | Create instance (async job) |
| `POST /api/vms/{id}/start·stop·suspend·resume` | Lifecycle |
| `DELETE /api/vms/{id}` | Delete instance + DNS + tailnet device |
| `POST /api/images/homecloud-base/build` | Build base template |
| `GET  /api/cloud-images` | Upstream distro cloud images (base layer catalog) |
| `POST /api/cloud-images` | Register your own cloud image URL |
| `GET  /api/images` | Built-in + custom image definitions |
| `POST /api/images` | Define a custom image (packages, config files, commands) |
| `PATCH·DELETE /api/images/{id}` | Edit or remove a custom image definition |
| `POST /api/images/{id}/build` | Bake a custom image into a template (async job) |
| `GET  /api/jobs/{id}` / `POST …/cancel` | Job status, logs, cancel |
| `GET  /api/config` | Public bootstrap config for the SPA |
| `GET  /auth/verify` | Caddy forward-auth target (Clerk session gate) |

## Deploys

- **Backend** — push to `main` → GitHub Actions on a self-hosted runner on the
  control node → rebuild + restart the compose stack
  ([docs/deploy-backend.md](docs/deploy-backend.md)).
- **Web** — push to `main` → Cloudflare Workers Git builds the console and
  deploys the `gavinf-homecloud` Worker
  ([docs/deploy-web.md](docs/deploy-web.md)). The portal at `gavinf.com` and
  the docs at `docs.gavinf.com` are separate Workers in the `gavinf` and
  `mydocs` repos.

## Design history

The system was built in phases — architecture, instance sizing, public DNS,
tunnel + reverse proxy, port discovery, split DNS, web UI, auth. The original
plan documents are preserved in [`docs/plan/`](docs/plan/).
