#!/bin/sh
set -e

if [ -d /mnt/ssh ]; then
  mkdir -p /root/.ssh
  cp -r /mnt/ssh/. /root/.ssh/
  chmod 700 /root/.ssh
  chmod 600 /root/.ssh/* 2>/dev/null || true
fi

exec "$@"
