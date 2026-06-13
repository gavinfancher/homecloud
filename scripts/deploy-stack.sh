#!/usr/bin/env bash
# Build and (re)start the control-plane stack via docker compose.
# Run on the control node with a filled .env (Proxmox, Tailscale, Cloudflare, Clerk).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill in secrets first." >&2
  exit 1
fi

echo "→ Building controller image…"
docker compose build controller

echo "→ Starting stack (controller, caddy, cloudflared, coredns)…"
docker compose up -d

echo "→ Health check…"
sleep 2
curl -fsS "http://localhost:${CONTROLLER_PORT:-8080}/api/health" >/dev/null
echo "✓ Controller healthy on :${CONTROLLER_PORT:-8080}"

docker compose ps
