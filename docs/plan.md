# homecloud — path to prod

Status: draft for review (2026-10-04). The DNS decisions in §4 need sign-off before Stage 4.

## Target

One control VM (`ubuntu@100.74.161.39`) running one Docker Compose stack:

| container     | image                                   | notes                                              |
|---------------|-----------------------------------------|----------------------------------------------------|
| `api`         | `ghcr.io/gavinfancher/homecloud:<sha>`  | FastAPI + DB-backed job runner in one process      |
| `postgres`    | `postgres:18.4`                         | named volume, **all** state lives here             |
| `cloudflared` | `cloudflare/cloudflared:<pinned>`       | tunnel `homecloud-api.gavinf.com` → `http://api:8080` |
| `coredns`     | `coredns/coredns:<pinned>`              | split DNS for `dns.gavinf.com`, bound to the VM's tailnet IP:53 |

Everything else is removed: Caddy, Ansible, the `ssh/` mount, `.homecloud/*.json` and `.env` files on disk. The CoreDNS zone file is a *derived* artifact: it is rebuilt from the `instances` table on startup and on every change, and is never read back, so all state really is in Postgres.

Rules:
- **No SSH, ever.** Proxmox is driven by its API. Guests are configured with cloud-init (a seed ISO uploaded through the API) at deploy time and with the QEMU guest agent (`agent/exec`, `agent/file-write`) after that. Monitoring later uses the same APIs (`status/current`, `rrddata`, `agent/get-fsinfo`).
- **The controller only makes outbound HTTPS calls**: Proxmox, Tailscale, Infisical, plus Postgres and the CoreDNS zone volume on the compose network. It needs no Cloudflare API token. It never needs a route to the LAN or tailnet IPs of the VMs it creates. That is also what keeps a later move to k8s cheap.
- **Secrets come from Infisical.** The only credential on disk is the Infisical machine identity.

## Stages

Each stage can be shipped on its own, and prod keeps running between stages.

### Stage 0: Freeze and back up (prod, 10 min)
- Copy `~/homecloud/.env`, `.homecloud/state.json`, `.homecloud/jobs.json` and a `pg_dump` off the box.
- Note the PVE templates in use: `homecloud-base` (the clones' origin) and 9100 (`debian-12`).
- Prod stays on `65e57cd` until Stage 6.

### Stage 1: Build pipeline and packaging (repo only) — done
- `Dockerfile`: `python:3.12-slim` + `uv sync --frozen --no-dev`, non-root user, `HEALTHCHECK` on `/api/health`. `docker-entrypoint.sh` is gone; `openssh-client` stays until Stage 3 removes Ansible.
- `.github/workflows/ci.yml`: ruff + pytest + frontend build on PRs and on `main`.
- `.github/workflows/release.yml`: on push to `main`, build `linux/amd64` and push `ghcr.io/gavinfancher/homecloud:{sha,main}`. The repo is public, so the package can be public and the VM pulls without a login.
- Bring back the pure-logic tests that still apply (`parse_ss_output`, sizes, auth, names), plus new ones as the stages land.

### Stage 2: All state in Postgres (no Alembic) — done
Migrations are plain numbered SQL files (`src/homecloud/db/migrations/001_init.sql`, …). A ~30-line runner applies them in order inside one transaction and records each in `schema_migrations(version, applied_at)`. It runs on startup under `pg_advisory_lock`. That covers everything Alembic would do for us.

Tables:
- `ssh_keys(id, name, public_key, created_at)`: your Mac key, plus any others.
- `base_images(id, version, ubuntu_release, image_url, sha256, ssh_key_ids[], packages[], user_data_extra, template_vmid, status, built_at)`: the configurable base image (Stage 3), versioned. Each build is a new row and a new template, so existing instances never change underneath you.
- `instances(name PK, vmid, base_image_id, cores, memory_mb, disk_gb, status, lan_ip, tailscale_ip, tailscale_device_id, dns_record_ids jsonb, roles jsonb, ports jsonb, ports_scanned_at, created_at)`
- `jobs(id, type, status, payload jsonb, result jsonb, error, cancel_requested, attempts, heartbeat_at, created_at, updated_at)` and `job_logs(id, job_id, ts, level, message)`

Jobs: the API inserts a row, and a runner thread in the same process claims work with `SELECT … FOR UPDATE SKIP LOCKED`. On startup, any `running` job whose heartbeat is stale is marked `failed (interrupted)` and its cleanup hook runs. That fixes the current orphans: the `build_image` job stuck at `running` and the `custom_images` row stuck at `building`. Splitting the runner into its own container later only means a different entrypoint.

`homecloud import-legacy state.json` is a one-shot, idempotent command:
- 2 instances (`pixie`, `wishly-vm`) get `base_image_id = NULL` (legacy) and `roles = []`
- 1 SSH key is imported
- `jobs.json` is dropped
- table `custom_images` is dropped by `001_init.sql`; `cloud_images` stays until Stage 3 replaces it with `base_images`

`state.py` and `jobs.py` now use Postgres. `provision/keys.py` (the controller SSH key in `.homecloud/`) stays until Stage 3 removes SSH. `base_images` arrives in Stage 3 as `002_*.sql`.

### Stage 3: API-only provisioning — built, not yet deployed

Prod prerequisites before the first build:
- **Proxmox storage `local` needs the `import` content type.** Today it has `backup,iso,snippets,vztmpl`, so `download-url` refuses to fetch the cloud image. Fix: `pvesm set local --content backup,iso,snippets,vztmpl,import`, or Datacenter → Storage → local → Content.
- `TAILSCALE_API_KEY` mints the per-VM keys (an OAuth client can replace it later). `TAILSCALE_TAGS` is optional; set it only once the tailnet policy has `tagOwners` for the tag.
- The console changes ship with the frontend build. The old console calls `/api/sources`, which no longer exists, so deploy the backend and frontend together.

**Base image** (one definition, editable from the console and the API):
1. Proxmox `download-url` fetches the Ubuntu 26.04.1 cloud image. The URL is pinned to a release serial and checked against `SHA256SUMS`.
2. Create the VM, import the disk, attach a bake seed ISO. The seed contains the `qemu-guest-agent` install, `dhcp-identifier: mac`, `ubuntu` with the selected SSH keys in `authorized_keys`, the selected `packages`, `user_data_extra`, and Tailscale *installed but not joined*.
3. Wait for `cloud-init status --wait` via the guest agent, run the sysprep that already exists (machine-id etc.), and convert to the template `base-<version>`.

**Deploy**:
1. Clone the template, set resources, resize the disk.
2. Mint a **per-VM, single-use, pre-authorized, tagged** Tailscale auth key through the Tailscale API. This replaces the long-lived `TAILSCALE_AUTH_KEY`. As built: minted with `TAILSCALE_API_KEY`, single-use, with a 1h expiry, tagged when `TAILSCALE_TAGS` is set.
3. Render the instance user-data: hostname, extra keys, `tailscale up --authkey … --hostname <name>`, and role fragments.
4. Upload it as the seed ISO and start the VM.
5. Wait on the guest agent for `cloud-init status --wait`, then detach and delete the seed ISO, which contains the auth key.
6. Get the Tailscale IP from the Tailscale API and create the DNS records (§4).

**Roles** become one idempotent bash script (`provision/script.py`) instead of Ansible roles. cloud-init writes it from the seed and runs it from `runcmd`. **Reconfigure** writes the same script through `agent/file-write` and runs it through `agent/exec`, which needs no SSH. Output goes to `/var/log/homecloud-provision.log`, and its tail is copied into the job log. Ansible, `ansible-runner` and the controller keypair are removed.

**Port scan**: `ss -H -tlnp` over `agent/exec` via `guest_run`. This also fixes the existing bug where `guest_exec` returned a pid instead of output.

**Teardown**:
1. stop the VM
2. delete the Tailscale device by its stored `device_id`
3. delete the DNS records by their stored ids
4. delete the VM
5. delete the row

Each step is idempotent, so a failed teardown can be re-run.

**Cluster-safe ids**: VMIDs come from `/cluster/nextid` with a retry when the clone fails because the id is taken.

### Stage 4: DNS (decided, see §4)
- Zone `dns.gavinf.com`, rendered from `instances`: `<vm>` and `*.<vm>` → tailnet IP. CoreDNS keeps `file … { reload 5s }` and forwards everything else to 1.1.1.1/9.9.9.9.
- During the cutover CoreDNS serves **both** `dns.gavinf.com` and the old `vm.homecloud.gavinf.com`, so nothing breaks mid-move. Drop the old zone once the clients are updated.
- Tailscale split DNS: `dns.gavinf.com → 100.74.161.39`, set once in the admin console. It could be managed through the Tailscale API (`/tailnet/-/dns/split-dns`), but it's a one-time setting, so doing it by hand is simpler.
- Remove Caddy, `proxy/caddy.py`, `publish.py`, the `/services` routes, `cloudflare/dns.py` and the forward-auth endpoint.

### Stage 5: Infisical
- Project `homecloud` with envs `dev` and `prod`. Every key in today's `.env` moves there, minus the dead ones: `PROXMOX_SSH_HOST`, `PROXMOX_SNIPPETS_DIR`, `PROXMOX_BASE_TEMPLATE_ID`, `CLOUD_IMAGE_CACHE_DIR`, `AGENT_*`, `CADDY_*`, `CLOUDFLARE_API_TOKEN`/`ZONE_ID`, `TAILSCALE_AUTH_KEY`. `CONTROL_NODE_TAILSCALE_IP` stays, because the CoreDNS port binding needs it.
- Prod: a machine identity (Universal Auth). Its client id and secret live in `/etc/homecloud/infisical.env` (root, 0600), and that file is the only secret on the box. `deploy.sh` runs `infisical run --env=prod -- docker compose up -d`, which feeds `api`, `postgres` and `cloudflared`.
  - `up -d` recreates any container whose env changed. That avoids the earlier "restart doesn't reload env" trap.
- Local dev: `infisical run --env=dev -- uv run homecloud`.
- Pin the Infisical CLI version in `deploy.sh`.

### Stage 6: Cutover on the prod VM
1. Put `/opt/homecloud/{compose.yml,deploy.sh}` in place; prod no longer needs a git checkout of the repo. Install the Infisical CLI and machine identity.
2. The `release.yml` deploy job runs on the existing self-hosted runner after the image push: `deploy.sh <sha>` → `docker compose pull` → `up -d` → health check → roll back to the previous tag if the check fails. The runner is still registered to `gavinfancher/mycloud`. GitHub redirects renames, but re-register it against `homecloud` to be safe.
3. Cutover:
   1. stop the old stack (`docker compose -p homecloud down`, **keeping the `postgres_data` volume**)
   2. start the new stack against the same volume
   3. run `import-legacy`
   4. point the tunnel ingress for `homecloud-api.gavinf.com` at `http://api:8080`
   5. switch DNS for the two existing VMs (§4)
4. Verify:
   - the console loads
   - `pixie` and `wishly-vm` show up and resolve
   - build the 26.04 base image
   - deploy, reconfigure and tear down a throwaway VM
5. Rollback: `docker compose down`, then `git checkout 65e57cd && scripts/control-node-deploy.sh` in `~/homecloud`. The old JSON files are untouched.
6. Cleanup once it has been stable for a week: delete `~/homecloud`, the `ssh/` keys (including `macbook-pro-key`), the old PVE templates, the `homecloud_caddy_sites` volume, the old `vm.homecloud.gavinf.com` zone and its Tailscale split-DNS entry.

### Later
- Monitoring through the Proxmox `rrddata` and guest-agent APIs, polled by the job runner and stored in Postgres.
- Split the runner into a separate container, then k8s.

## §4 DNS

**Decided 2026-10-04:**
- **Names**: `<vm>.dns.gavinf.com`, plus a wildcard `*.<vm>.dns.gavinf.com`.
- **Resolution**: keep split DNS with CoreDNS, private to the tailnet.
- **Public app publishing**: dropped for now (Caddy goes).
- **Roles**: Ansible is replaced with cloud-init fragments plus guest-agent exec.

**Consequences of these decisions:**
- **Don't create Cloudflare records under `dns.gavinf.com`.** Off-tailnet resolvers will (correctly) return NXDOMAIN, and a public record would shadow the split DNS for anyone not on the tailnet.
- **The control VM's tailnet IP (`100.74.161.39`) is load-bearing.** If the VM is rebuilt, either keep its Tailscale identity or update the split-DNS entry.
- **Unpinned image**: `coredns:latest` gets pinned.
- **Cloudflare API token**: not needed (#7 below is moot).

Original analysis, kept for reference:

Current state, to be replaced:
- **Instances**: `<vm>.vm.homecloud.gavinf.com`, served by CoreDNS on the control VM through Tailscale split DNS.
- **Published apps**: `<svc>.<vm>.<owner>.vm.homecloud.gavinf.com` via Caddy plus Clerk forward-auth. This is unused in prod: there are no site files and no Cloudflare token is set.
- **`api.homecloud.dev`**: still in the Caddyfile. It goes away.

Issues:
1. **Instance zone.** Proposal: `<vm>.dns.gavinf.com`, e.g. `pixie.dns.gavinf.com`, plus a wildcard `*.pixie.dns.gavinf.com` for services on the box.
2. **Public records vs split DNS.** Recommendation: **DNS-only (grey cloud) Cloudflare A records → the tailnet 100.x IP**.
   - It removes CoreDNS, the Tailscale split-DNS config, and the tailnet-IP port binding on the control VM.
   - Names resolve from anywhere but only connect from inside the tailnet.
   - Cost: the VM names and tailnet IPs are visible in public DNS.
   - The alternative is to keep CoreDNS: one more container and the control VM's tailnet IP stays load-bearing.
3. **TLS depth.** Cloudflare's free Universal SSL covers `gavinf.com` and `*.gavinf.com` only, one level deep. That doesn't matter for grey-cloud records pointing at tailnet IPs. But any *proxied* public app at `x.pixie.dns.gavinf.com` gets **no edge certificate** without Advanced Certificate Manager. This is why public apps should get single-label names (`<svc>-<vm>.gavinf.com`) if they come back.
4. **Publishing apps publicly.** Recommendation: **defer**. If it comes back, the simplest no-Caddy, no-SSH version is a tunnel ingress rule added through the Cloudflare API, with Cloudflare Access as the gate instead of Clerk forward-auth. But `cloudflared` would then need a route to the tailnet IPs, which brings host tailnet routing back.
5. **Control-plane names stay**: console `homecloud.gavinf.com` (Worker, already in the Clerk allowlist) and API `homecloud-api.gavinf.com` (tunnel → `api:8080`). `proxmox.gavinf.com → 10.0.0.100:8006` stays on the same tunnel; this is unchanged, and the plan doesn't make the tunnel config any less exposed.
6. **Tunnel config.** Keep it remote-managed (dashboard or API), so `cloudflared` needs only `TUNNEL_TOKEN` and no config file.
7. **Cloudflare API token** (Infisical), scoped to `Zone:DNS:Edit` on `gavinf.com`. Add `Account:Cloudflare Tunnel:Edit` only if #4 comes back.
8. **Migrating the existing VMs.**
   - Create `pixie.dns.gavinf.com` and `wishly-vm.dns.gavinf.com` before turning CoreDNS off.
   - Find and update anything that uses `*.vm.homecloud.gavinf.com`: your `~/.ssh/config`, wishly's config, bookmarks.
   - Then remove the Tailscale split-DNS entry.
9. **Name collisions.** Tailscale names a second device with the same hostname `name-1`. The current code matches devices by hostname. The new code stores `tailscale_device_id` at deploy time and uses that id for lookup and teardown.
