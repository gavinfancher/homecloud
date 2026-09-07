#!/bin/sh
set -e

if [ -d /mnt/ssh ]; then
  mkdir -p /root/.ssh
  cp -r /mnt/ssh/. /root/.ssh/
  chmod 700 /root/.ssh
  chmod 600 /root/.ssh/* 2>/dev/null || true
fi

# ssh/config is gitignored, so `git reset --hard` during a control-node deploy
# can leave the checkout without one. Synthesize a minimal config from the
# environment so the PROXMOX_SSH_HOST alias always resolves.
if [ ! -f /root/.ssh/config ] && [ -n "${PROXMOX_SSH_HOST:-}" ] && [ -n "${PROXMOX_HOST:-}" ]; then
  mkdir -p /root/.ssh
  chmod 700 /root/.ssh
  key=$(ls /root/.ssh/*-key 2>/dev/null | head -n 1)
  {
    echo "Host ${PROXMOX_SSH_HOST}"
    echo "  Hostname ${PROXMOX_HOST}"
    echo "  User root"
    [ -n "$key" ] && echo "  IdentityFile ${key}"
    echo "  StrictHostKeyChecking accept-new"
  } > /root/.ssh/config
  chmod 600 /root/.ssh/config
  echo "entrypoint: generated /root/.ssh/config for host '${PROXMOX_SSH_HOST}' -> ${PROXMOX_HOST}"
fi

exec "$@"
