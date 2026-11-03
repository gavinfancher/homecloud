#!/usr/bin/env bash
# Turn off the "No valid subscription" popup in the Proxmox web UI.
#
#   infra/proxmox/remove-subscription-popup.sh          # host "pve" from ~/.ssh/config
#   infra/proxmox/remove-subscription-popup.sh root@10.0.4.10
#
# The popup comes from proxmoxlib.js (package proxmox-widget-toolkit). This installs
# /usr/local/sbin/pve-no-nag, which edits that file so the check skips the popup and carries on,
# and an apt hook that runs it again after every apt run, since each toolkit update puts the file
# back. Safe to run again: it only edits the file when the popup is still there.
#
# Afterwards, hard-refresh the Proxmox tab (Cmd+Shift+R) so the browser drops the cached JS.
# To undo: rm /usr/local/sbin/pve-no-nag /etc/apt/apt.conf.d/99-pve-no-nag &&
#          apt reinstall proxmox-widget-toolkit
set -euo pipefail

ssh "${1:-pve}" 'bash -s' <<'REMOTE'
set -euo pipefail

cat > /usr/local/sbin/pve-no-nag <<'FIX'
#!/bin/sh
# Skip the "No valid subscription" popup (installed by homecloud/infra/proxmox).
f=/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
[ -f "$f" ] || exit 0
grep -q 'pve-no-nag' "$f" && exit 0
# Ext.Msg.show({ title: gettext('No valid subscription'), ... callback: orig_cmd ... });
# becomes: orig_cmd(); void({ ...same object, never shown... });
perl -0pi -e "s/Ext\.Msg\.show\(\{(\s+title: gettext\('No valid subscription'\))/orig_cmd(); \/* pve-no-nag *\/ void({\$1/" "$f"
if grep -q 'pve-no-nag' "$f"; then
  systemctl try-restart pveproxy.service
  echo "pve-no-nag: popup removed"
else
  echo "pve-no-nag: popup code not found; proxmox-widget-toolkit may have changed" >&2
fi
FIX
chmod 755 /usr/local/sbin/pve-no-nag

cat > /etc/apt/apt.conf.d/99-pve-no-nag <<'HOOK'
// Re-apply after package updates put proxmoxlib.js back (homecloud/infra/proxmox).
DPkg::Post-Invoke { "/usr/local/sbin/pve-no-nag || true"; };
HOOK

/usr/local/sbin/pve-no-nag
grep -c 'pve-no-nag' /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js >/dev/null \
  && echo "done: hard-refresh the Proxmox tab"
REMOTE
