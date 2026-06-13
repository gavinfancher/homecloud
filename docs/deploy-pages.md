# Deploy the console (Cloudflare Pages + GitHub)

The SPA in `frontend/` is a static Vite build deployed to **Cloudflare Pages**.
Pages runs on the Workers platform; you do not need a separate Worker for the console.

Production URL: `https://app.myhomecloud.dev`  
API URL (separate stack): `https://api.myhomecloud.dev`

## One-time: connect GitHub → Pages

In [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**:

| Setting | Value |
|---|---|
| Repository | `gavinfancher/homecloud` |
| **Production branch** | `main` |
| **Root directory** | `frontend` |
| **Framework preset** | Vite (or None) |
| **Build command** | `npm run build` |
| **Build output directory** | `dist` |
| **Node.js version** | `22` (matches `frontend/.node-version`) |

Enable **automatic deployments** on push to `main`.

### Environment variables (Pages → Settings → Environment variables)

Set these for **Production** (and Preview if you want Clerk on preview deploys):

| Variable | Value | Notes |
|---|---|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | `pk_live_…` or `pk_test_…` | From Clerk Dashboard or `clerk env pull` |
| `VITE_API_BASE` | `https://api.myhomecloud.dev` | Also in `frontend/.env.production` (checked in) |

**Do not** set `VITE_DEV_BYPASS_AUTH` in Production. It is only for local `vite dev` and is ignored in prod builds anyway (`import.meta.env.DEV` is false).

### Custom domain

Pages → **Custom domains** → add `app.myhomecloud.dev` (likely already attached if the site is live).

## Backend alignment (control node `.env`)

When Clerk is enabled on the controller, set:

```bash
CLERK_JWKS_URL=https://<slug>.clerk.accounts.dev/.well-known/jwks.json
CLERK_ISSUER=https://<slug>.clerk.accounts.dev
CLERK_AUTHORIZED_PARTIES=https://app.myhomecloud.dev
CLERK_PUBLISHABLE_KEY=pk_…
FRONTEND_ORIGIN=https://app.myhomecloud.dev
CONSOLE_URL=https://app.myhomecloud.dev
API_PUBLIC_HOST=api.myhomecloud.dev
OWNER_USERNAME=gavin
```

Redeploy the stack on the control node after changing `.env`:

```bash
make deploy-stack   # or: docker compose up -d --build
```

## Verify a deploy

After pushing to `main`:

1. Cloudflare Pages → **Deployments** — build should succeed.
2. Open `https://app.myhomecloud.dev` — sign-in screen (Clerk), not the dev bypass badge.
3. Browser devtools → Network — API calls go to `https://api.myhomecloud.dev/api/…`.

## Local dev (unchanged)

```bash
make dev-api    # controller on :8080
make dev-web    # Vite on :5173/5174, proxies /api to controller
```

`frontend/.env.local`: `VITE_DEV_BYPASS_AUTH=true` skips Clerk locally.

## Manual deploy (optional)

If you need a one-off upload without Git:

```bash
make deploy-frontend   # requires wrangler login or CLOUDFLARE_API_TOKEN
```

Git-connected Pages is the preferred path for production.
