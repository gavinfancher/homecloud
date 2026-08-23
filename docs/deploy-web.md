# Deploying the web console

`homecloud.gavinf.com` is served by its own Cloudflare Worker,
**`gavinf-homecloud`** — a static assets Worker with no script, built from
[`frontend/`](../frontend).

```json
// frontend/wrangler.json
{
  "name": "gavinf-homecloud",
  "assets": {
    "directory": "./dist",
    "not_found_handling": "single-page-application"
  },
  "routes": [{ "pattern": "homecloud.gavinf.com", "custom_domain": true }]
}
```

`not_found_handling` matters: the console uses `react-router` with
`BrowserRouter`, so `/instances` and friends must fall back to `index.html`
rather than 404.

## Deploy

Git-connected build on push to `main` (Workers & Pages → gavinf-homecloud →
Settings → Builds):

| Setting | Value |
|---|---|
| Build command | `npm run build` |
| Deploy command | `npx wrangler deploy` |
| Root directory | `frontend` |

By hand: `make deploy-web`.

## The other sites on gavinf.com

This repo used to serve all of them from one Worker (`gavinf-prod`) that routed
by hostname. They are now separate Workers in their own repos:

| Host | Worker | Repo |
|---|---|---|
| `homecloud.gavinf.com` | `gavinf-homecloud` | this repo |
| `gavinf.com`, `auth`, `dash`, `proxmox` | `gavinf-dash` | `gavinf` |
| `docs.gavinf.com` | `gavinf-docs` | `mydocs` |

The nav rail in [`frontend/src/PortalRail.tsx`](../frontend/src/PortalRail.tsx)
is mirrored as inline markup in the `gavinf` repo's `worker.js`, for the shell
wrapped around the Proxmox UI. Keep them in sync — a user crosses between them
with no page-level cue.
