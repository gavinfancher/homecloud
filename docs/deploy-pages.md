# Deploy the console (Cloudflare Pages + GitHub)

The SPA in `frontend/` is deployed as **static assets on a Cloudflare Worker**
(Git-connected: build → `wrangler deploy`). You do not need a separate Worker script.

Production URL: `https://app.myhomecloud.dev`  
API URL (separate stack): `https://api.myhomecloud.dev`

## One-time: connect GitHub → Workers & Pages

In [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create** → connect Git:

| Setting | Value |
|---|---|
| Repository | `gavinfancher/homecloud` |
| **Production branch** | `main` |
| **Root directory** | `frontend` |
| **Build command** | `npm run build` |
| **Deploy command** | `npx wrangler deploy` |
| **Version command** | `npx wrangler versions upload` *(default — leave as-is)* |
| **Node.js version** | `22` |

The deploy command **cannot be removed** on Workers Git projects — that's expected.
`frontend/wrangler.toml` tells `wrangler deploy` to upload `./dist` as static assets.

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

## Troubleshooting

### Build succeeds, deploy fails with "Missing entry-point"

Your project uses **Workers Git deploy** (`npx wrangler deploy`). Ensure
`frontend/wrangler.toml` includes:

```toml
[assets]
directory = "./dist"
not_found_handling = "single-page-application"
```

Commit, push to `main`, and retry. Do **not** try to delete the deploy command —
Workers Git projects require it.

### Build fails: missing Clerk key

Add `VITE_CLERK_PUBLISHABLE_KEY` under Pages → **Environment variables** (Production), then retry.

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
