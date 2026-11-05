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

Every step lands in the VM's log, stored in Postgres and opened with **Log** in the UI. It records
what the worker is doing, how long each piece took, and, when a Proxmox task fails, the end of
Proxmox's own task log, which is usually where the real reason is. While a VM is busy, its latest
log line shows under its status.

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

1. **Proxmox: a pool, a storage, and a token that can only use those.** On the node:
   ```sh
   pveum pool add homecloud --comment "VMs made by homecloud"
   # Its own directory storage for the seed/answer ISOs and downloaded images. Deleting a file
   # no VM owns needs Datastore.Allocate, and that's only safe on a storage that's all homecloud's.
   mkdir -p /var/lib/vz/homecloud
   pvesm add dir homecloud --path /var/lib/vz/homecloud --content iso,import --create-subdirs 1

   pveum role add HomecloudVM --privs "VM.Allocate VM.Audit VM.Config.CDROM VM.Config.CPU VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.Console VM.PowerMgmt VM.GuestAgent.Audit"
   pveum role add HomecloudFiles --privs "Datastore.Allocate Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit"
   pveum role add HomecloudStorage --privs "Datastore.Audit Datastore.AllocateSpace Datastore.AllocateTemplate"
   pveum role add HomecloudRead --privs "Datastore.Audit"
   # download-url needs Sys.AccessNetwork on the node (or Sys.Modify on /, the whole datacenter)
   pveum role add HomecloudDownload --privs "Sys.AccessNetwork"

   pveum user add homecloud@pve --comment "homecloud API"
   pveum acl modify /pool/homecloud    --users homecloud@pve --roles HomecloudVM
   pveum acl modify /storage/homecloud --users homecloud@pve --roles HomecloudFiles
   pveum acl modify /storage/local-lvm --users homecloud@pve --roles HomecloudStorage   # VM disks
   pveum acl modify /storage/local     --users homecloud@pve --roles HomecloudRead      # the Windows ISO
   pveum acl modify /sdn/zones/localnetwork --users homecloud@pve --roles PVESDNUser
   pveum acl modify /nodes/pve --users homecloud@pve --roles PVEAuditor,HomecloudDownload
   pveum user token add homecloud@pve homecloud --privsep 0   # prints the secret once
   ```
   The Windows 11 ISO goes at `local:iso/Win11-Enterprise-eval.iso`.

   Two Proxmox quirks shape `backend/app/pve.py`: a VM is created untagged and tagged right
   after, because the create call checks the tag permission on `/vms/<id>` before the VM has
   joined the pool; and the token is never given `Datastore.Allocate` on `local`, where it
   would let it delete backups and other ISOs.
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

## When something fails

| Failure | What happens |
| --- | --- |
| A step hangs (Proxmox slow, guest agent never reports) | Each step has a timeout (15 min by default; Ubuntu wait 20 min, Windows wait 90 min, first create 60 min for the image download). Past it, the VM is marked **failed** with the step and the error. |
| A Proxmox task fails | The VM is marked **failed**, and the tail of Proxmox's own task log goes into the VM's log, so the real reason is one click away. |
| A delete fails | It stays **deleting** and retries every 5 s until it works, logging each new error once. |
| The pod restarts mid-create (deploy, node reboot) | The next pod picks up at the same step. Every step checks what Proxmox already has, so nothing is created twice. |
| Two pods overlap during a rolling update | A Postgres advisory lock keeps it to one worker. |
| Postgres down | `/readyz` returns 503 and the pod leaves the Service. The worker logs the error and retries. |
| The cluster or home network is down | The site shows a Cloudflare error. VMs already made keep running: they live on Proxmox, not in homecloud. |

## What broke and how I fixed it

**Every clone got the same IP address** (v1). VMs were cloned from a template, and two of them
sat on the same IP, ARP-fighting so that one was unreachable. systemd-networkd builds its DHCP
client ID from `/etc/machine-id`, and every clone had the template's. The template prep *did*
clear machine-id, but it ran through the guest agent's fire-and-forget exec, and the build then
hard-stopped the VM with no `sync`, so the change died in the page cache. Fixed three ways: wait
for the command and `sync` before stopping, refuse to make a template that still has a
machine-id, and set `dhcp-identifier: mac` so DHCP identity follows each clone's own MAC
(`d76dbd9`).

**The locked-down token couldn't create VMs with tags.** Proxmox checks the tag permission on
`/vms/<id>` during create, before the VM has joined the pool the token is scoped to. Giving the
token wider rights would have defeated the point, so homecloud now creates untagged and tags
right after, in a step that's safe to repeat (`fbceb9e`).

**Deleting an ISO needed a dangerous permission.** Removing the seed ISO needs
`Datastore.Allocate`. On the shared `local` storage, that would let the token delete backups
and every other ISO. homecloud got its own `homecloud` storage instead, and the token is
read-only on `local`.

## Known gaps

- **One replica.** If its worker node dies, the site is down until the pod is rescheduled (about
  a minute). Nothing in flight is lost: the worker resumes.
- **No database backups.** Postgres (`postgres.ad.gavinf.com`) is one box shared with wishly and
  easydocs, with no backups.
- **No alerting.** A VM stuck in **failed** is only seen in the UI.
- **One Windows admin password** for every Windows VM. Fine for throwaway lab VMs, but it should
  be generated per VM and shown once.
- **One Proxmox host.** If it's down, there's nothing to create VMs on.

## Local dev

```sh
make -C backend test   # starts a throwaway postgres:18.4 on 127.0.0.1:5434 the first time
make -C backend dev    # http://localhost:8000, no sign-in; talks to the real Proxmox
```

`make dev` needs the Proxmox settings in your shell, e.g. `infisical run --env=dev -- make -C backend dev`.
