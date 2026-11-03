# homecloud

Spin up a VM on my Proxmox host from a web page: pick **Ubuntu 26.04** or **Windows 11**, pick
a size, and a few minutes later it's running with an address on my LAN. Everything goes through
the Proxmox API with a token that can only touch homecloud's own VMs. No SSH, no clicking
through installers.

Live at https://homecloud.gavinf.com (sign-in required). Linked from https://dash.gavinf.com.

```
 browser ──► homecloud.gavinf.com ─── the pages: static files on Cloudflare (frontend/)
    │
    └──────► homecloud-api.gavinf.com ── tunnel ──► cloudflared ──► homecloud (FastAPI + worker)
                                                    k8s, namespace homecloud      │
                                                                                  ├──► Proxmox API (10.0.4.10:8006)
                                                                                  └──► Postgres "homecloud" on postgres.ad.gavinf.com
```

The same shape as [wishly](https://github.com/gavinfancher/wishly) and
[easydocs](https://github.com/gavinfancher/easydocs): static pages on Cloudflare's CDN, an API
in my k3s cluster reached through a Cloudflare Tunnel (nothing at home has an open port),
secrets from Infisical, and deploys by Argo CD from git.

## What happens when you click Create

The API writes a row to Postgres and returns. A worker in the same process moves each VM through
its steps, checking every few seconds:

| Step | Ubuntu 26.04 | Windows 11 |
| --- | --- | --- |
| **create** | Upload a cloud-init seed ISO (hostname, my SSH keys, `qemu-guest-agent`). Create the VM with the Ubuntu cloud image imported as its disk, then grow it to the size asked for. | Upload an ISO holding `autounattend.xml` (disk layout, computer name, admin password, RDP on). Create a UEFI + Secure Boot + TPM 2.0 VM with the Windows ISO, the answer ISO and the VirtIO tools ISO in its CD drives. |
| **start** | Power on. | Power on, and press Enter through the API for "Press any key to boot from CD". |
| **wait** | Until the guest agent reports a LAN IP (a minute or two). | Windows installs itself, signs in once, installs the VirtIO guest tools; then the agent reports its IP (20–40 minutes). |
| **cleanup** | Eject the seed ISO and delete it. | Eject the discs and delete the answer ISO, which holds the admin password. |

Then it's **ready**: `ssh ubuntu@<ip>` with my key (no passwords), or RDP to `<ip>` as
`Administrator`.

A few decisions worth calling out:

- **The token can't touch anything else.** Every VM homecloud makes goes into the Proxmox pool
  `homecloud`, and the API token only has VM rights on that pool. My k8s nodes, the domain
  controller and the Postgres VM are out of its reach, even with a bug. On top of that, the
  worker refuses to delete any VM that isn't tagged `homecloud`.
- **Every step is safe to repeat.** The VMID is saved before anything is created, and each step
  checks what Proxmox already has. If the pod restarts mid-create (a deploy, a node reboot),
  the next pod picks up where it stopped. A Postgres advisory lock keeps it to one worker,
  even while two pods overlap during a rolling update.
- **The answers ride in ISOs.** Proxmox's API can't upload cloud-init snippets, but it can
  upload ISOs, so homecloud builds the seed and answer discs itself (`backend/app/media.py`).
- **Images are pinned and verified.** The Ubuntu image URL is pinned to one build; Proxmox
  downloads it once and checks it against Ubuntu's `SHA256SUMS`.
- **No VM networking magic.** VMs get a DHCP address on `10.0.4.0/24`. I reach them over
  Tailscale through the Proxmox host's subnet route.

## Layout

```
backend/    the API and worker (FastAPI): app/, tests/, Dockerfile, compose.yml for local dev
frontend/   the pages, CSS and JS (static/), page routes (_redirects), wrangler.jsonc
deploy/     Kubernetes (k8s/) and the Argo CD Application (argocd/)
infra/      Terraform for the tunnel and DNS (terraform/), the database setup (sql/),
            Proxmox host tweaks (proxmox/)
```

| Piece | Where |
| --- | --- |
| API routes, validation | `backend/app/main.py` |
| The worker and its steps | `backend/app/provision.py` |
| Every Proxmox call | `backend/app/pve.py` |
| cloud-init seed, `autounattend.xml` | `backend/app/media.py` |
| Sign-in and sessions | `backend/app/auth.py` |
| Settings (all env vars, with defaults) | `backend/app/config.py` |

## Deploying

Push to `main`:

- **The API.** CI runs the tests, pushes `ghcr.io/gavinfancher/homecloud:<sha>` and commits that
  tag to `deploy/k8s/kustomization.yaml`. Argo CD sees the commit and rolls the pod. Roll back by
  reverting the `deploy: homecloud <sha>` commit.
- **The pages.** Cloudflare Workers Builds runs `npm run build` and `npx wrangler deploy` in
  `frontend/`.

```sh
make -C backend logs                          # tail the API
kubectl -n homecloud get pods                 # 1 homecloud + 1 cloudflared
curl https://homecloud-api.gavinf.com/readyz  # {"status":"ready"}
```

## Secrets

All in Infisical (project `homecloud`, env `prod`, at the root). The Infisical operator copies
them into the `homecloud` Secret and restarts the pods when one changes.

| Key | What |
| --- | --- |
| `HOMECLOUD_DATABASE_URL` | `postgresql://homecloud:<pw>@postgres.ad.gavinf.com:5432/homecloud` (step 2) |
| `HOMECLOUD_ADMIN_PASSWORD_HASH` | `make -C backend password-hash`. Change the password by pasting a new hash |
| `HOMECLOUD_PROXMOX_TOKEN_ID` | `homecloud@pve!homecloud` (step 1) |
| `HOMECLOUD_PROXMOX_TOKEN_SECRET` | the token's secret (step 1) |
| `HOMECLOUD_WINDOWS_ADMIN_PASSWORD` | the local Administrator password on every Windows VM |
| `HOMECLOUD_SSH_KEYS` | public keys for `ubuntu` on every Ubuntu VM, one per line |
| `TUNNEL_TOKEN` | `terraform -chdir=infra/terraform output -raw tunnel_token` (step 3) |

## Setting it up (once)

1. **Proxmox: a pool, a role, and a token that can only use them.** On the node:
   ```sh
   pveum pool add homecloud --comment "VMs made by homecloud"
   pveum role add HomecloudVM --privs "VM.Allocate VM.Audit VM.Config.CDROM VM.Config.CPU VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.Console VM.PowerMgmt VM.GuestAgent.Audit"
   pveum role add HomecloudStorage --privs "Datastore.Audit Datastore.AllocateSpace Datastore.AllocateTemplate"
   pveum user add homecloud@pve --comment "homecloud API"
   pveum acl modify /pool/homecloud --users homecloud@pve --roles HomecloudVM
   pveum acl modify /storage/local --users homecloud@pve --roles HomecloudStorage
   pveum acl modify /storage/local-lvm --users homecloud@pve --roles HomecloudStorage
   pveum acl modify /sdn/zones/localnetwork --users homecloud@pve --roles PVESDNUser
   # download-url (fetching the Ubuntu image) also needs these on the node:
   pveum acl modify /nodes/pve-root --users homecloud@pve --roles PVEAuditor
   pveum role add HomecloudDownload --privs "Sys.Modify"
   pveum acl modify /nodes/pve-root --users homecloud@pve --roles HomecloudDownload
   pveum user token add homecloud@pve homecloud --privsep 0   # prints the secret once
   ```
   The `local` storage needs the `iso` and `import` content types (it has both), and the
   Windows 11 ISO at `local:iso/Win11-Enterprise-eval.iso`.
2. **Postgres**: run `infra/sql/roles.sql` once against `postgres.ad.gavinf.com` (the commands
   are at the top of the file) and put the URL it prints in Infisical.
3. **Terraform** makes the tunnel and `homecloud-api.gavinf.com`. The API token needs
   Account · Cloudflare Tunnel: Edit and Zone · DNS: Edit on `gavinf.com`.
   ```sh
   cd infra/terraform
   cp backend.hcl.example backend.hcl && cp terraform.tfvars.example terraform.tfvars   # fill in the IDs
   export AWS_PROFILE=... CLOUDFLARE_API_TOKEN=...
   terraform init -backend-config=backend.hcl && terraform apply
   ```
4. **Infisical**: make the `homecloud` project, put every key above in `prod`, and make a machine
   identity (universal auth) a Viewer on it. Store its login in the cluster yourself:
   ```sh
   read "CID?Client ID: "; read -s "CSEC?Client secret: "; echo
   kubectl -n infisical-operator-system create secret generic infisical-homecloud-identity \
     --from-literal=clientId="$CID" --from-literal=clientSecret="$CSEC"; unset CID CSEC
   ```
   Put the project's slug in `deploy/k8s/infisical-secret.yaml` (`projectSlug`).
5. **Image**: push to `main`. The `homecloud` package on GHCR is already public, so the cluster
   pulls it without credentials.
6. **Cluster**: `kubectl apply -f deploy/argocd/homecloud.yaml`, wait for both pods, then
   `curl https://homecloud-api.gavinf.com/readyz`.
7. **Pages**: Workers & Pages → `homecloud` → Settings → Builds → connect
   `gavinfancher/homecloud`, root directory `frontend`, build `npm run build`, deploy
   `npx wrangler deploy`. The Worker's name must match `name` in `frontend/wrangler.jsonc`.

## Local dev

```sh
make -C backend test   # starts a throwaway postgres:18.4 on 127.0.0.1:5434 the first time
make -C backend dev    # http://localhost:8000, no sign-in; talks to the real Proxmox
```

`make dev` needs the Proxmox settings in your shell, e.g. `infisical run --env=dev -- make -C backend dev`.
