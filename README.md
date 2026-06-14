# homecloud

Spin up Proxmox instances from a Docker-hosted control plane. Instances join your Tailscale tailnet and are reachable via MagicDNS from anywhere.

Deploy tests: backend pushes sync via self-hosted runner; frontend pushes deploy via Cloudflare Workers Git.

## Repo layout

```
src/homecloud/     # Controller (FastAPI)
frontend/          # Console SPA (Vite → Cloudflare Workers)
infra/
  docker/          # Dockerfile, compose stack
  caddy/           # Caddy base config
  coredns/         # CoreDNS Corefile
scripts/           # Deploy + bootstrap helpers
tests/             # Pytest suite
docs/              # Deploy runbooks + archived implementation plan
```

## Run (Docker)

On your control node VM:

```bash
cp .env.example .env   # PROXMOX_HOST, Tailscale keys, etc.
docker compose -f infra/docker/docker-compose.yml up -d --build
# or: make deploy-stack
```

Open `http://<control-node-tailscale-ip>:8080/`

The container needs:
- Network access to Proxmox API (`PROXMOX_HOST`)
- SSH to Proxmox for cloud-init snippets (`PROXMOX_SSH_HOST=pve` — mount keys at `./ssh`)
- Writable volume for state (`.homecloud/`)

## Create an instance

Set **CPU**, **RAM (GB)**, and **disk (GB)** yourself. RAM: 0.5–64 GB.

```json
POST /api/vms
{
  "name": "dagster",
  "cores": 1,
  "memory_gb": 0.5,
  "disk_gb": 10
}
```

Returns a `job_id` — poll `/api/jobs/{id}` for provisioning logs.

## DNS + SSH

Instance joins Tailscale with hostname `dagster` → MagicDNS: `dagster.kudu-cliff.ts.net` → `ssh ubuntu@dagster.kudu-cliff.ts.net`

No Pi-hole or local network required. Ensure **MagicDNS** is enabled in your [Tailscale admin DNS settings](https://login.tailscale.com/admin/dns).

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard` | Overview stats |
| `POST /api/setup` | Save SSH public key |
| `POST /api/images/homecloud-base/build` | Build base template (async job) |
| `POST /api/vms` | Create instance (async job) |
| `GET /api/jobs/{id}` | Job status + logs |
| `POST /api/jobs/{id}/cancel` | Cancel an in-flight job (e.g. a deploy) |
| `POST /api/vms/{id}/start` | Start instance |
| `POST /api/vms/{id}/stop` | Stop instance |
| `POST /api/vms/{id}/suspend` | Pause (suspend to RAM) |
| `POST /api/vms/{id}/resume` | Resume a suspended instance |
| `DELETE /api/vms/{id}?name=...` | Delete instance |
| `GET /api/config` | Public bootstrap config for the SPA (no auth) |
| `GET /auth/verify` | Caddy forward-auth target (Clerk session gate) |

## Auth (Clerk)

The `/api/*` endpoints and every published instance app are gated by **Clerk**.
Set `CLERK_JWKS_URL` + `CLERK_ISSUER` (and `CLERK_AUTHORIZED_PARTIES`) to enforce;
when unset, auth is disabled for local/dev (logged loudly).

The console is a React + Vite SPA in `frontend/`, deployed to **Cloudflare Workers** on
push to `main` — see [`docs/deploy-frontend.md`](docs/deploy-frontend.md).

Backend deploy: self-hosted GitHub Actions runner on the control node — see
[`docs/deploy-backend.md`](docs/deploy-backend.md).

Legacy config: [`legacy/initial`](../../tree/legacy/initial) branch.
