from __future__ import annotations

import os
from typing import Any, Dict
from zoneinfo import ZoneInfo

from .utils import read_json, write_json_atomic, ensure_dir

DEFAULT_CONFIG_PATH = "/etc/backupd/config.json"

SYSTEM_DB_DEFAULTS = {
    "mysql": ["information_schema", "performance_schema", "sys"],
    "postgres": ["template0", "template1"],
}

def default_config() -> Dict[str, Any]:
    return {
        "mode": "custom",  # "custom" or "hestia"
        "include_paths": ["/etc", "/home", "/var/www"],
        "exclude_globs": [
            "/proc/*", "/sys/*", "/dev/*", "/run/*",
            "/tmp/*", "/mnt/*", "/media/*", "/lost+found",
            "/var/cache/*", "/var/tmp/*", "/swapfile",
        ],
        "compression": "gz",
        "local_dir": "/var/backups/backupd",
        "staging_dir": "/var/lib/backupd/staging",
        "upload_enabled": True,
        "rclone_remote": "onedrive",
        "remote_path": "VPS-Backups",
        "schedule_times": ["03:00"],  # file backup times
        "timezone": "Europe/Athens",
        "tolerance_minutes": 2,

        "db": {
            "enabled": True,
            "policy": "hybrid",  # "every_backup" | "daily" | "hybrid"
            "dump_times": ["03:05"],  # used by daily/hybrid
            "mysql": {
                "enabled": True,
                "exclude_system_dbs": SYSTEM_DB_DEFAULTS["mysql"],
                "include_dbs": [],  # empty means auto-select non-system
                "exclude_dbs": [],
                "dump_options": ["--single-transaction", "--routines", "--events", "--triggers"],
                "compress": True,
            },
            "postgres": {
                "enabled": True,
                "exclude_system_dbs": SYSTEM_DB_DEFAULTS["postgres"],
                "include_dbs": [],
                "exclude_dbs": [],
                "format": "custom",  # "custom" or "plain"
                "compress": False,
            },
        },

        "retention": {
            "local":  {"keep_all_days": 7,  "keep_daily_until_days": 14,  "keep_weekly_until_days": 60,  "keep_monthly_until_days": 0},
            "remote": {"keep_all_days": 15, "keep_daily_until_days": 30,  "keep_weekly_until_days": 120, "keep_monthly_until_days": 365},
        },

        "notifications": {
            "enabled": False,
            "method": "smtp",  # "smtp" or "sendmail"
            "from": "backupd@localhost",
            "to": [],
            "smtp": {
                "host": "",
                "port": 587,
                "username": "",
                "password": "",
                "starttls": True,
            },
        },

        "ui": {"port": 8050, "bind": "127.0.0.1"},
        "system_db_defaults": SYSTEM_DB_DEFAULTS,
    }

def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    cfg = read_json(path, default=None)
    if cfg is None:
        cfg = default_config()
        save_config(cfg, path)
    validate_config(cfg)
    return cfg

def save_config(cfg: Dict[str, Any], path: str = DEFAULT_CONFIG_PATH) -> None:
    ensure_dir(os.path.dirname(path), mode=0o755)
    write_json_atomic(path, cfg, mode=0o600)

def validate_time_str(t: str) -> None:
    if not isinstance(t, str) or len(t) != 5 or t[2] != ":":
        raise ValueError(f"Bad time '{t}' (expected HH:MM)")
    hh = int(t[0:2]); mm = int(t[3:5])
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        raise ValueError(f"Bad time '{t}' (expected HH:MM)")

def validate_config(cfg: Dict[str, Any]) -> None:
    if cfg.get("mode") not in ("custom", "hestia"):
        raise ValueError("mode must be 'custom' or 'hestia'")

    tz = cfg.get("timezone", "UTC")
    ZoneInfo(tz)  # validate

    times = cfg.get("schedule_times", [])
    if not isinstance(times, list) or not times:
        raise ValueError("schedule_times must be a non-empty list")
    for t in times:
        validate_time_str(t)

    db = cfg.get("db", {})
    if db.get("enabled"):
        if db.get("policy") not in ("every_backup", "daily", "hybrid"):
            raise ValueError("db.policy must be every_backup|daily|hybrid")
        for t in db.get("dump_times", []):
            validate_time_str(t)

    for scope in ("local", "remote"):
        pol = cfg.get("retention", {}).get(scope, {})
        for k in ("keep_all_days", "keep_daily_until_days", "keep_weekly_until_days", "keep_monthly_until_days"):
            v = int(pol.get(k, 0))
            if v < 0:
                raise ValueError(f"retention.{scope}.{k} must be >= 0")
