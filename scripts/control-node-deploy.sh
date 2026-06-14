#!/usr/bin/env bash
# Idempotent deploy on the control node: sync main, rebuild controller, restart stack.
# Requires: git clone of this repo, filled .env, docker + compose plugin.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
STACK_COMPOSE="$ROOT/infra/docker/docker-compose.yml"
compose() { docker compose -f "$STACK_COMPOSE" --env-file "$ROOT/.env" "$@"; }

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill secrets first." >&2
  exit 1
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository. Run scripts/bootstrap-control-node.sh first." >&2
  exit 1
fi

BRANCH="${DEPLOY_BRANCH:-main}"
if [[ -z "${HOMECLOUD_DEPLOY_SYNCED:-}" ]]; then
  echo "→ Syncing origin/${BRANCH}…"
  git fetch origin "$BRANCH"
  git reset --hard "origin/${BRANCH}"
  export HOMECLOUD_DEPLOY_SYNCED=1
  exec "$0" "$@"
fi

if [[ ! -f "$STACK_COMPOSE" ]]; then
  echo "Missing $STACK_COMPOSE — repo layout may be out of date." >&2
  exit 1
fi

echo "→ Building controller image…"
compose build controller

echo "→ Starting stack (controller, caddy, cloudflared, coredns)…"
compose up -d --remove-orphans

echo "→ Health check…"
sleep 3
curl -fsS "http://localhost:${CONTROLLER_PORT:-8080}/api/health" >/dev/null
echo "✓ Controller healthy on :${CONTROLLER_PORT:-8080}"

compose ps
