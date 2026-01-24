#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

systemctl disable --now backupd.timer || true
systemctl disable --now backup-ui.service || true

rm -f /etc/systemd/system/backupd.service /etc/systemd/system/backupd.timer /etc/systemd/system/backup-ui.service
systemctl daemon-reload

rm -f /usr/local/sbin/backupctl
rm -f /etc/sudoers.d/backupui-backupd

echo "Uninstalled services/shims. Data/config not removed."
