#!/usr/bin/env bash
# Install a GitHub Actions self-hosted runner on the control node VM.
# Run on homecloud (ubuntu@100.76.205.59), not from your laptop.
#
# 1. GitHub → repo Settings → Actions → Runners → New self-hosted runner → Linux x64
# 2. Copy the registration token (expires in ~1 hour)
# 3. On the VM:
#      export RUNNER_TOKEN='paste-token-here'
#      ./scripts/install-github-runner.sh
set -euo pipefail

REPO="${GITHUB_REPO:-gavinfancher/homecloud}"
RUNNER_NAME="${RUNNER_NAME:-homecloud}"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
RUNNER_VERSION="${RUNNER_VERSION:-2.329.0}"
LABELS="${RUNNER_LABELS:-homecloud,linux}"
ARCH="${RUNNER_ARCH:-x64}"

if [[ -z "${RUNNER_TOKEN:-}" ]]; then
  echo "Set RUNNER_TOKEN from GitHub → Settings → Actions → Runners → New self-hosted runner" >&2
  exit 1
fi

case "$ARCH" in
  x64) RUNNER_PKG="actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" ;;
  arm64) RUNNER_PKG="actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz" ;;
  *)
    echo "Unsupported RUNNER_ARCH=$ARCH (use x64 or arm64)" >&2
    exit 1
    ;;
esac

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [[ ! -f ./config.sh ]]; then
  echo "→ Downloading runner ${RUNNER_VERSION}…"
  curl -fsSL -o "$RUNNER_PKG" \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_PKG}"
  tar xzf "$RUNNER_PKG"
  rm -f "$RUNNER_PKG"
fi

if [[ -f .runner ]]; then
  echo "Runner already configured in $RUNNER_DIR (remove .runner to re-register)"
else
  echo "→ Configuring runner ${RUNNER_NAME} for ${REPO}…"
  ./config.sh \
    --url "https://github.com/${REPO}" \
    --token "$RUNNER_TOKEN" \
    --name "$RUNNER_NAME" \
    --labels "$LABELS" \
    --work "_work" \
    --unattended \
    --replace
fi

echo "→ Installing systemd service (runs as $(whoami))…"
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status

echo "✓ Runner installed. Labels: ${LABELS}"
echo "  Deploy workflow uses: runs-on: [self-hosted, linux, homecloud]"
