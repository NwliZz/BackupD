#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root (sudo ./scripts/install.sh)"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/8] Installing apt dependencies..."
apt-get update -y
apt-get install -y rclone python3-venv python3-pip mariadb-client postgresql-client tar gzip

echo "[2/8] Creating directories..."
mkdir -p /etc/backupd /var/backups/backupd /var/lib/backupd /var/log/backupd
chmod 755 /etc/backupd
chmod 750 /var/backups/backupd || true
chmod 755 /var/log/backupd || true

if [[ ! -f /etc/backupd/config.json ]]; then
  echo "[3/8] Installing default config..."
  cp "$ROOT_DIR/scripts/sample-config.json" /etc/backupd/config.json
  chmod 600 /etc/backupd/config.json
else
  echo "[3/8] Config exists, leaving as-is: /etc/backupd/config.json"
fi

echo "[4/8] Creating UI system user (backupui)..."
if ! id backupui >/dev/null 2>&1; then
  adduser --system --home /opt/backupd --group backupui
fi

echo "[5/8] Creating venv and installing BackupD..."
cd "$ROOT_DIR"
python3 -m venv "$ROOT_DIR/.venv"
"$ROOT_DIR/.venv/bin/pip" install --upgrade pip
"$ROOT_DIR/.venv/bin/pip" install -e "$ROOT_DIR"
"$ROOT_DIR/.venv/bin/pip" install streamlit

echo "[6/8] Installing backupctl shim..."
ln -sf "$ROOT_DIR/.venv/bin/backupctl" /usr/local/sbin/backupctl

echo "[7/8] Installing sudoers rules for UI..."
cat >/etc/sudoers.d/backupui-backupd <<'SUDO'
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl get-config
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl set-config
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl status
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl test-cloud
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl discover-dbs
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl test-dbs
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl backup-now
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl retention-plan
backupui ALL=(root) NOPASSWD: /usr/local/sbin/backupctl retention-apply
SUDO
chmod 440 /etc/sudoers.d/backupui-backupd

echo "[8/8] Installing systemd units..."
cp "$ROOT_DIR/systemd/backupd.service" /etc/systemd/system/backupd.service
cp "$ROOT_DIR/systemd/backupd.timer" /etc/systemd/system/backupd.timer
cp "$ROOT_DIR/systemd/backup-ui.service" /etc/systemd/system/backup-ui.service

systemctl daemon-reload
systemctl enable --now backupd.timer
systemctl enable --now backup-ui.service

echo
echo "Installed."
echo "- Config: /etc/backupd/config.json"
echo "- Logs: /var/log/backupd/backupd.log (plus journald)"
echo "- UI: localhost:8050 (use SSH tunnel)"
echo
echo "Next: configure OneDrive remote for rclone as root:"
echo "  sudo -i"
echo "  rclone config"
echo "  rclone lsd onedrive:"
