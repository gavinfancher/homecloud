# Deploy the control plane (Proxmox control node)

The backend runs as Docker Compose on a **control node VM** on your tailnet (not on the
Proxmox host itself). The SPA is deployed separately via Cloudflare — see
[deploy-frontend.md](./deploy-frontend.md).

```
app.myhomecloud.dev  → Cloudflare Workers (frontend, auto on push)
api.myhomecloud.dev  → Tunnel → Caddy → controller:8080 (this stack)
```

## Architecture

| Service | Role |
|---------|------|
| `controller` | FastAPI — Proxmox API, jobs, DNS/proxy sync |
| `caddy` | Reverse proxy for published instance services + `api.myhomecloud.dev` |
| `cloudflared` | Cloudflare Tunnel connector |
| `coredns` | Split DNS for `*.myhomecloud.dev` on the tailnet |

**Your setup:** Proxmox host `pve-root` (100.106.79.65), control node VM `homecloud`
(100.76.205.59).

## CI/CD (recommended)

| Trigger | What runs | Where |
|---------|-----------|-------|
| PR / push to `main` | **CI** — `pytest`, frontend lint + build | GitHub-hosted (`ci.yml`) |
| Push to `main` (any change) | **Deploy** — sync `main`, rebuild controller, restart stack | Self-hosted runner on `homecloud` |
| Push to `main` (`frontend/`) | Cloudflare Workers Git deploy | Cloudflare |
| Actions → Deploy backend → Run workflow | Manual backend deploy | Self-hosted runner |

### Self-hosted runner (deploy)

The deploy workflow runs on a **self-hosted runner** installed on the control node VM. GitHub
queues the job; the runner on `homecloud` picks it up and runs `~/homecloud/scripts/control-node-deploy.sh` locally — no SSH, no Tailscale OAuth, no deploy secrets.

**Pros:** Simple, fast, works on a tailnet-only VM, no ACL/OAuth setup.  
**Cons:** Runner is a persistent process on the VM; only use on **private** repos (or lock down who can trigger workflows).

#### One-time: install the runner on homecloud

```bash
ssh ubuntu@100.76.205.59
cd ~/homecloud && git pull   # get install-github-runner.sh

# GitHub → repo Settings → Actions → Runners → New self-hosted runner → Linux x64
# Copy the registration token (expires in ~1 hour)
export RUNNER_TOKEN='paste-token-here'
./scripts/install-github-runner.sh
```

Verify in GitHub → **Settings → Actions → Runners** — you should see `homecloud` with labels
`self-hosted`, `linux`, `homecloud` (idle or active).

The workflow matches `runs-on: [self-hosted, linux, homecloud]`. Re-run the install script
with a new `RUNNER_TOKEN` if you need to re-register.

**Runner user:** the script installs the service as your current user (`ubuntu`). That user
must be able to run `docker compose` (same as manual deploy).

Optional: add a **production** environment in GitHub for approval gates before deploy — no
secrets required for the self-hosted path.

<details>
<summary>Alternative: hosted runners + Tailscale (not used by default)</summary>

If you cannot install a runner on the VM, hosted runners can join the tailnet via
[`tailscale/github-action@v4`](https://github.com/tailscale/github-action) then SSH. Requires
OAuth client with `tag:ci`, `grants` for port 22, and secrets `TAILSCALE_OAUTH_*`,
`DEPLOY_SSH_PRIVATE_KEY`, `CONTROL_NODE_HOST`, `CONTROL_NODE_USER`. See Tailscale’s
[CI/CD guide](https://tailscale.com/docs/solutions/connect-github-CICD-workflows-to-private-infrastructure-without-public-exposure).

</details>

## One-time bootstrap (control node VM)

SSH to the control node:

```bash
ssh ubuntu@100.76.205.59
```

Clone and preserve existing state (if migrating from a copied tree):

```bash
curl -fsSL https://raw.githubusercontent.com/gavinfancher/homecloud/main/scripts/bootstrap-control-node.sh | bash
```

Or from a laptop with the repo:

```bash
ssh ubuntu@100.76.205.59 'bash -s' < scripts/bootstrap-control-node.sh
```

This backs up `~/homecloud` → `~/homecloud.bak.<timestamp>`, clones `main`, restores
`.env`, `.homecloud`, and `ssh/`, then runs the first deploy.

### `.env` checklist

Copy `.env.example` and fill all production values. Critical entries:

```bash
# Proxmox + Tailscale (VM provisioning)
PROXMOX_HOST=100.106.79.65
PROXMOX_SSH_HOST=pve
# ... token, storage, template id ...

# Public edge
DOMAIN=myhomecloud.dev
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ZONE_ID=...
CLOUDFLARE_TUNNEL_TOKEN=...
CLOUDFLARE_TUNNEL_CNAME=<uuid>.cfargotunnel.com

# Compose integration (required in production)
CADDY_RELOAD_CMD=http://caddy:2019
CADDY_FORWARD_AUTH_UPSTREAM=controller:8080
CONTROL_NODE_TAILSCALE_IP=100.76.205.59

# Clerk (required for production auth)
CLERK_JWKS_URL=https://<slug>.clerk.accounts.dev/.well-known/jwks.json
CLERK_ISSUER=https://<slug>.clerk.accounts.dev
CLERK_AUTHORIZED_PARTIES=https://app.myhomecloud.dev
CLERK_PUBLISHABLE_KEY=pk_...
FRONTEND_ORIGIN=https://app.myhomecloud.dev
CONSOLE_URL=https://app.myhomecloud.dev
API_PUBLIC_HOST=api.myhomecloud.dev
OWNER_USERNAME=gavin
```

Place Proxmox SSH keys in `ssh/` (gitignored). `ssh/config` should point `pve` at the
Proxmox host tailnet IP.

### SSH keys for controller → Proxmox

```bash
# On control node, in ~/homecloud/ssh/
# macbook-pro-key (private) + config with Host pve → Proxmox tailnet IP
chmod 700 ssh && chmod 600 ssh/*-key
```

## Deploy (day-to-day)

**From the control node:**

```bash
cd ~/homecloud
./scripts/control-node-deploy.sh
```

**From your laptop:**

```bash
CONTROL_NODE_HOST=100.76.205.59 make deploy-remote
```

**Automatic:** any merge to `main` (after the self-hosted runner is installed).

## Verify

```bash
curl -fsS http://localhost:8080/api/health
curl -fsS https://api.myhomecloud.dev/api/health
curl -fsS https://api.myhomecloud.dev/api/config   # auth_enabled: true when Clerk is set
docker compose -f infra/docker/docker-compose.yml ps   # controller, caddy, cloudflared, coredns all Up
```

Open `https://app.myhomecloud.dev` — Clerk sign-in, API calls to `api.myhomecloud.dev`.

## Troubleshooting

### New instance hostname doesn't resolve

You should **not** need to restart Tailscale after each VM. If a name fails right after
create, it's usually one of these:

1. **Deploy still running** — DNS is written only after the VM gets a Tailscale IP (last
   step of the job). Wait for the job to finish.
2. **CoreDNS zone reload** — the zone file updates immediately; CoreDNS reloads it every 5s
   (`reload 5s` in the Corefile).
3. **macOS DNS cache** — if you queried the name before it existed, macOS may cache
   NXDOMAIN. Flush without restarting Tailscale:

```bash
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder
```

Then verify:

```bash
dig @100.76.205.59 wishly.gavin.myhomecloud.dev +short   # tailnet IP from CoreDNS
dscacheutil -q host -a name wishly.gavin.myhomecloud.dev  # what SSH uses
```

Restarting the Tailscale app also clears macOS cache — that's why it seemed to help, but
it's heavier than a cache flush.

### Split DNS breaks `api` / `app` hostnames

If Tailscale split DNS sends all of `myhomecloud.dev` to CoreDNS, instance names resolve
privately but `api.myhomecloud.dev` and `app.myhomecloud.dev` must still reach Cloudflare.
The Corefile uses **fallthrough** so unknown names forward to public resolvers (1.1.1.1).

Verify on the tailnet:

```bash
dig @100.76.205.59 api.myhomecloud.dev    # should return Cloudflare IPs, not NXDOMAIN
dig @100.76.205.59 dagster.gavin.myhomecloud.dev  # instance tailnet IP
```

### CoreDNS won't start (port 53)

If `systemd-resolved` holds port 53:

```bash
sudo sed -i 's/#DNSStubListener=yes/DNSStubListener=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved
docker compose -f infra/docker/docker-compose.yml up -d coredns
```

### Auth disabled (`auth_enabled: false`)

Clerk vars missing in `.env`. Add `CLERK_*` entries and redeploy.

### Deploy broke after manual edits

```bash
cd ~/homecloud
git fetch origin main && git reset --hard origin/main
./scripts/control-node-deploy.sh
```

State in `.homecloud/` and secrets in `.env` are preserved across deploys.

## What we stopped doing

Do **not** `rsync --delete` the repo to the control node. Past rsyncs broke paths and
orphaned files. Git sync + `docker compose` is the supported path.
