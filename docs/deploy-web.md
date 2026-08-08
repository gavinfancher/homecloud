# Deploy the web apps (Cloudflare Workers)

All public sites are served by **one Cloudflare Worker: `gavinf-prod`**
(source in [`frontend/gavinf-prod/`](../frontend/gavinf-prod)). The worker
routes by hostname over a combined static-asset tree:

| Hostname | Serves |
|---|---|
| `gavinf.com`, `auth.gavinf.com`, `dash.gavinf.com` | Portal SPA (`frontend/dashboard/` → `dist/portal`) |
| `homecloud.gavinf.com` | Console SPA (`frontend/` → `dist/console`) |
| `proxmox.gavinf.com` | Portal-rail shell for navigations; everything else passes through to the Proxmox origin via the Cloudflare Tunnel |

## Primary path: Cloudflare Workers Git

Push to `main` → Cloudflare builds and deploys automatically. Build config
(Workers & Pages → gavinf-prod → Settings → Build):

| Setting | Value |
|---|---|
| Repository | `gavinfancher/homecloud`, branch `main` |
| Root directory | `frontend/gavinf-prod` |
| Build command | `npm run build` (builds both SPAs, assembles `dist/{portal,console}`) |
| Deploy command | `npx wrangler deploy` |
| Build watch paths | include `frontend/*` — backend-only pushes skip the build |
| Environment | `VITE_CLERK_PUBLISHABLE_KEY` (public key; baked into both bundles) |

The console's API base URL comes from `frontend/.env.production`
(`VITE_API_BASE=https://homecloud-api.gavinf.com`, checked in).

## Backup path: local wrangler

```bash
make deploy-web
# equivalent to: cd frontend/gavinf-prod && npm run build && npx wrangler deploy
```

Requires `wrangler login` and `VITE_CLERK_PUBLISHABLE_KEY` in the environment.

## Auth wiring (Clerk)

- Production Clerk instance lives on the `gavinf.com` domain (`clerk.gavinf.com`).
- Sign-in happens on `auth.gavinf.com`; the console redirects there when signed out.
- **Any new subdomain that loads Clerk must be added to the instance's
  `allowed_origins`** (Backend API `PATCH /instance`) or the page hangs blank
  with a 403 "subdomain not in the allowed subdomains list".
- The backend independently enforces `CLERK_AUTHORIZED_PARTIES` on the API.

## Verify a deploy

1. `curl -s https://dash.gavinf.com | grep '<title>'` → `gavinf.com`
2. `curl -s https://homecloud.gavinf.com | grep '<title>'` → `homecloud`
3. Open `https://homecloud.gavinf.com` — Clerk sign-in, then console;
   API calls go to `https://homecloud-api.gavinf.com/api/…`.
