#!/bin/bash
# One-time setup of a fresh control VM (Ubuntu). Idempotent; run as root:
#
#   sudo deploy/bootstrap.sh
#
# Installs Docker and the Infisical CLI and creates /etc/homecloud. Tailscale
# must already be up: CoreDNS binds the VM's tailnet IP, and Tailscale split
# DNS points at it. Then put the machine identity in /etc/homecloud/infisical.env
# and run deploy.sh (see README.md).
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "bootstrap.sh must run as root" >&2; exit 1; }

if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale is not up — install it and run 'tailscale up' first" >&2
  exit 1
fi
echo "✓ tailscale up ($(tailscale ip -4 | head -1))"

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
echo "✓ $(docker --version)"

if ! command -v infisical >/dev/null; then
  curl -1sLf https://artifacts-cli.infisical.com/setup.deb.sh | bash
  apt-get install -y infisical
fi
echo "✓ infisical $(infisical --version 2>/dev/null | awk '{print $NF}')"

install -d -m 700 /etc/homecloud
if [ ! -e /etc/homecloud/infisical.env ]; then
  install -m 600 /dev/null /etc/homecloud/infisical.env
  cat > /etc/homecloud/infisical.env <<'EOF'
# Machine identity (Universal Auth) for the Infisical project "homecloud".
INFISICAL_CLIENT_ID=
INFISICAL_CLIENT_SECRET=
INFISICAL_PROJECT_ID=
# INFISICAL_API_URL=https://app.infisical.com/api
EOF
  echo "→ fill in /etc/homecloud/infisical.env, then run deploy.sh"
else
  echo "✓ /etc/homecloud/infisical.env exists"
fi
