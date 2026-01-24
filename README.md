# BackupD — VPS Backup + DB Dumps + OneDrive + Retention + Localhost UI

BackupD is a professional-grade backup utility for Linux VPS environments.

It provides:
- Curated filesystem backups (custom include/exclude) or **Hestia mode** (sync `/backup`)
- Dynamic DB discovery (MariaDB/MySQL + PostgreSQL) with optional scheduled dumps
- Compressed archive creation (`tar.gz`)
- Offsite upload to Microsoft OneDrive via `rclone`
- Automatic **Storage & Retention** (GFS-like thinning)
- Localhost-only Streamlit UI (access via SSH tunnel)

## Architecture

- `backupctl` (root CLI): backup engine, DB discovery/dumps, retention, cloud tests
- `backupd.timer` + `backupd.service`: scheduler (systemd)
- `backup-ui.service`: Streamlit UI bound to `127.0.0.1:8050`

## Quick start (Ubuntu 24.04)

### 1) Install system dependencies

```bash
sudo apt update
sudo apt install -y rclone python3-venv mariadb-client postgresql-client tar gzip
```

### 2) Configure OneDrive remote (rclone)
Run as root (so the service uses the same token):

```bash
sudo -i
rclone config
rclone lsd onedrive:
exit
```

### 3) Install BackupD from this repo

```bash
sudo mkdir -p /opt
sudo git clone <YOUR_GITHUB_REPO_URL> /opt/backupd
cd /opt/backupd
sudo ./scripts/install.sh
```

### 4) Access the UI via SSH tunnel

On your laptop/PC:

```bash
ssh -L 8050:127.0.0.1:8050 manos@<VPS_IP>
```

Open:

- http://localhost:8050

## Configuration

Config file: `/etc/backupd/config.json`

See `scripts/sample-config.json` for a full example.

## License
MIT
