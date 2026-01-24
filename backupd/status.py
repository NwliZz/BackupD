from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from .config import load_config
from .retention import local_inventory, remote_inventory

def disk_usage(path: str) -> Dict[str, Any]:
    try:
        st = os.statvfs(path)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = total - free
        return {"path": path, "total_bytes": total, "used_bytes": used, "free_bytes": free}
    except Exception:
        return {"path": path, "total_bytes": 0, "used_bytes": 0, "free_bytes": 0}

def get_status() -> Dict[str, Any]:
    cfg = load_config()
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = datetime.now(tz).isoformat()

    local = local_inventory(cfg)
    remote = []
    if cfg.get("upload_enabled", True):
        try:
            remote = remote_inventory(cfg)
        except Exception:
            remote = []

    return {
        "now": now,
        "mode": cfg.get("mode"),
        "local_dir": cfg.get("local_dir"),
        "local_count": len(local),
        "local_latest": local[0][0] if local else None,
        "remote_count": len(remote),
        "remote_latest": remote[0][0] if remote else None,
        "disk": disk_usage(cfg.get("local_dir", "/var/backups/backupd")),
    }
