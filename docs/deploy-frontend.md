# Deploy the console (Cloudflare Workers + GitHub)

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
make deploy-stack   # or: docker compose -f infra/docker/docker-compose.yml up -d --build
```

## Troubleshooting

### Cloudflare Git stopped building on push

Your normal path is **Workers & Pages → homecloud → Settings → Builds** (Git connected to `main`, root `frontend`). That does **not** use GitHub secrets — Cloudflare pulls from GitHub and runs `npm run build` + `npx wrangler deploy` on their side.

If pushes no longer show up under **Deployments**:

1. **Retry manually** — Deployments → ⋯ on last build → **Retry build**, or **Create deployment** → branch `main` → latest commit.
2. **Build watch paths** — Settings → Build → **Build watch paths**. Include should be `*` (or at least `frontend/**`). If includes are too narrow, commits that only touch other folders won't trigger a build.
3. **Root directory** — must be `frontend` (not repo root).
4. **Reconnect Git** — Settings → Build → disconnect and reconnect the GitHub repo (fixes stale webhooks). See [Cloudflare Git integration troubleshooting](https://developers.cloudflare.com/workers/ci-cd/builds/troubleshoot/).
5. **Stale build token** — if Builds settings reference an API token that was rolled, create a new token in Build settings and retry.

Check GitHub → repo **Settings → Integrations → Applications** → Cloudflare Workers — recent webhook deliveries should show `push` events for your commits.

GitHub Actions **Deploy frontend** (if present) is an optional manual backup (`workflow_dispatch` only), not your primary deploy path.

### Optional: GitHub Actions deploy (not required)

Cloudflare **Workers Git** builds are separate from GitHub Actions CI. Check **Workers & Pages → homecloud → Deployments**:

- If the latest build is older than your last `git push`, the GitHub ↔ Cloudflare webhook may have stalled (common after repo settings changes).
- **Quick fix:** Deployments → **Retry deployment** on the latest commit, or **Create deployment** → branch `main`.
- **Reliable fix:** use the repo workflow `.github/workflows/deploy-frontend.yml` (runs on `frontend/**` pushes). Set GitHub **production** environment secrets:
  - `CLOUDFLARE_API_TOKEN` — Workers deploy permission
  - `CLOUDFLARE_ACCOUNT_ID` — from Cloudflare dashboard URL or `wrangler whoami`
  - `VITE_CLERK_PUBLISHABLE_KEY` — same value as Cloudflare build env

You can disable automatic Git builds in Cloudflare once GitHub Actions deploy is working (avoids duplicate deploys).

**Manual deploy from your laptop** (same as Workers Git uses):

```bash
cd frontend
export VITE_CLERK_PUBLISHABLE_KEY=pk_test_…   # or source from clerk env pull
npm run build
npx wrangler deploy
```

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
