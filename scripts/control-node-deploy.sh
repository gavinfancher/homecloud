#!/usr/bin/env bash
# Idempotent deploy on the control node: sync main, rebuild controller, restart stack.
# Requires: git clone of this repo, filled .env, docker + compose plugin.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="$ROOT/infra/docker/docker-compose.yml"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill secrets first." >&2
  exit 1
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository. Run scripts/bootstrap-control-node.sh first." >&2
  exit 1
fi

BRANCH="${DEPLOY_BRANCH:-main}"
echo "→ Syncing origin/${BRANCH}…"
git fetch origin "$BRANCH"
git reset --hard "origin/${BRANCH}"

echo "→ Building controller image…"
compose build controller

echo "→ Starting stack (controller, caddy, cloudflared, coredns)…"
compose up -d --remove-orphans

echo "→ Health check…"
sleep 3
curl -fsS "http://localhost:${CONTROLLER_PORT:-8080}/api/health" >/dev/null
echo "✓ Controller healthy on :${CONTROLLER_PORT:-8080}"

compose ps
