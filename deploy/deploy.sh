#!/bin/bash
# Roll the homecloud stack to an image tag, with every secret from Infisical.
#
#   sudo deploy/deploy.sh sha-1234567
#
# Copies compose.yml, Corefile and this script into /opt/homecloud, then runs
# `docker compose up` inside `infisical run`, so containers get their env from
# Infisical (env "prod") at creation. If the api does not become healthy, the
# previous tag is redeployed and the script fails.
#
# Needs /etc/homecloud/infisical.env (root, 0600) with the machine identity:
#   INFISICAL_CLIENT_ID=...  INFISICAL_CLIENT_SECRET=...  INFISICAL_PROJECT_ID=...
#   INFISICAL_API_URL=https://app.infisical.com/api   (optional; EU/self-hosted differ)
set -euo pipefail

TAG=${1:?usage: deploy.sh <image tag, e.g. sha-1234567>}
SRC=$(cd "$(dirname "$0")" && pwd)
DEST=/opt/homecloud
CREDS=/etc/homecloud/infisical.env

[ "$(id -u)" = 0 ] || { echo "deploy.sh must run as root" >&2; exit 1; }
[ -r "$CREDS" ] || { echo "missing $CREDS — see deploy/README.md" >&2; exit 1; }

set -a
# shellcheck source=/dev/null
. "$CREDS"
set +a
: "${INFISICAL_CLIENT_ID:?} ${INFISICAL_CLIENT_SECRET:?} ${INFISICAL_PROJECT_ID:?}"
export INFISICAL_API_URL=${INFISICAL_API_URL:-https://app.infisical.com/api}
export INFISICAL_DISABLE_UPDATE_CHECK=true

install -d -m 755 "$DEST"
install -d -o 1000 -g 1000 -m 755 "$DEST/zones"
corefile_changed=0
if [ "$SRC" != "$DEST" ]; then
  cmp -s "$SRC/Corefile" "$DEST/Corefile" || corefile_changed=1
  install -m 644 "$SRC/compose.yml" "$SRC/Corefile" "$DEST/"
  install -m 755 "$SRC/deploy.sh" "$DEST/"
fi

compose() {
  local token
  token=$(infisical login --method=universal-auth \
    --client-id="$INFISICAL_CLIENT_ID" --client-secret="$INFISICAL_CLIENT_SECRET" \
    --silent --plain)
  infisical run --token="$token" --projectId="$INFISICAL_PROJECT_ID" --env=prod --silent -- \
    docker compose -f "$DEST/compose.yml" "$@"
}

healthy() {
  for _ in $(seq 45); do
    curl -fsS -o /dev/null http://127.0.0.1:8080/api/health && return 0
    sleep 2
  done
  return 1
}

up() {
  echo "→ deploying $1"
  HOMECLOUD_TAG=$1 compose up -d --pull always --remove-orphans
}

previous=$(cat "$DEST/.tag" 2>/dev/null || true)
up "$TAG"
# The Corefile is bind-mounted by inode; replacing it needs a restart to show.
if [ "$corefile_changed" = 1 ]; then
  HOMECLOUD_TAG=$TAG compose restart coredns
fi

if healthy; then
  echo "$TAG" > "$DEST/.tag"
  echo "✓ $TAG is live"
  exit 0
fi

echo "✗ $TAG did not become healthy" >&2
HOMECLOUD_TAG=$TAG compose logs --tail 50 api >&2 || true
if [ -n "$previous" ] && [ "$previous" != "$TAG" ]; then
  echo "↺ rolling back to $previous" >&2
  up "$previous"
  healthy && echo "✓ rolled back to $previous" >&2
fi
exit 1
