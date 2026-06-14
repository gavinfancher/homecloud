#!/usr/bin/env bash
# Build and (re)start the control-plane stack via docker compose.
# On a git clone, prefer scripts/control-node-deploy.sh (syncs main first).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="$ROOT/infra/docker/docker-compose.yml"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

if git rev-parse --git-dir >/dev/null 2>&1; then
  exec "$ROOT/scripts/control-node-deploy.sh"
fi

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill in secrets first." >&2
  exit 1
fi

echo "→ Building controller image…"
compose build controller

echo "→ Starting stack (controller, caddy, cloudflared, coredns)…"
compose up -d --remove-orphans

echo "→ Health check…"
sleep 2
curl -fsS "http://localhost:${CONTROLLER_PORT:-8080}/api/health" >/dev/null
echo "✓ Controller healthy on :${CONTROLLER_PORT:-8080}"

compose ps
