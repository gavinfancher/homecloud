#!/usr/bin/env bash
# Build and deploy the SPA to Cloudflare Pages.
# Requires: wrangler auth (`wrangler login`) OR CLOUDFLARE_API_TOKEN in the env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"

if [[ -z "${VITE_CLERK_PUBLISHABLE_KEY:-}" && -f .env.local ]]; then
  # shellcheck disable=SC1091
  set -a && source .env.local && set +a
fi

if [[ -z "${VITE_CLERK_PUBLISHABLE_KEY:-}" ]]; then
  echo "Missing VITE_CLERK_PUBLISHABLE_KEY — run 'clerk env pull' in frontend/" >&2
  exit 1
fi

echo "→ Building production bundle…"
npm run build

PROJECT="${PAGES_PROJECT_NAME:-homecloud}"
echo "→ Deploying dist/ to Cloudflare Pages project '${PROJECT}'…"
npx wrangler pages deploy dist --project-name="$PROJECT" --commit-dirty=true

echo "✓ Frontend deployed. Console: https://app.myhomecloud.dev (if DNS is wired)"
