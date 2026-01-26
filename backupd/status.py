"""Status aggregation for the UI and CLI."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from .config import load_config
from .retention import local_inventory, remote_inventory
from datetime import datetime, timedelta, time

def _parse_hhmm(s: str) -> time | None:
    """Parse HH:MM into a time object, returning None on failure."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        hh, mm = s.split(":")
        return time(hour=int(hh), minute=int(mm))
    except Exception:
        return None

def _human_delta(seconds: int) -> str:
    """Format a positive seconds delta as HH:MM:SS."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def _next_prev_occurrence(now: datetime, hhmm_list: list[str]) -> tuple[datetime | None, datetime | None]:
    """Compute next and previous occurrences for a list of daily times."""
    times = [t for t in (_parse_hhmm(x) for x in (hhmm_list or [])) if t is not None]
    if not times:
        return None, None

    today = now.date()
    # build today's occurrences
    todays = [datetime.combine(today, t, tzinfo=now.tzinfo) for t in times]

    # next: soonest occurrence strictly after now, else tomorrow's earliest
    future = [dt for dt in todays if dt > now]
    if future:
        nxt = min(future)
    else:
        nxt = min(todays) + timedelta(days=1)

    # prev: latest occurrence at/before now, else yesterday's latest
    past = [dt for dt in todays if dt <= now]
    if past:
        prv = max(past)
    else:
        prv = max(todays) - timedelta(days=1)

    return nxt, prv

def disk_usage(path: str) -> Dict[str, Any]:
    """Return filesystem usage stats for a path."""
    try:
        st = os.statvfs(path)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = total - free
        return {"path": path, "total_bytes": total, "used_bytes": used, "free_bytes": free}
    except Exception:
        return {"path": path, "total_bytes": 0, "used_bytes": 0, "free_bytes": 0}

def get_status() -> Dict[str, Any]:
    """Build a status snapshot for the UI dashboard."""
    cfg = load_config()
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = datetime.now(tz).isoformat()
    now_dt = datetime.now(tz)

    next_bk, prev_bk = _next_prev_occurrence(now_dt, cfg.get("schedule_times", []))
    next_bk_in = int((next_bk - now_dt).total_seconds()) if next_bk else None

    # DB dumps (optional)
    db_cfg = cfg.get("db", {})
    next_db, prev_db = (None, None)
    next_db_in = None
    if db_cfg.get("enabled"):
        next_db, prev_db = _next_prev_occurrence(now_dt, db_cfg.get("dump_times", []))
        next_db_in = int((next_db - now_dt).total_seconds()) if next_db else None

    local = local_inventory(cfg)
    local_bytes = sum(size for _name, _ts, size in local)
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
        "local_bytes": local_bytes,
        "remote_count": len(remote),
        "remote_latest": remote[0][0] if remote else None,
        "disk": disk_usage(cfg.get("local_dir", "/var/backups/backupd")),
        "next_backup_at": next_bk.isoformat() if next_bk else None,
        "next_backup_in_seconds": next_bk_in,
        "next_backup_in_human": _human_delta(next_bk_in) if next_bk_in is not None else None,
        "prev_backup_scheduled_at": prev_bk.isoformat() if prev_bk else None,

        "next_db_dump_at": next_db.isoformat() if next_db else None,
        "next_db_dump_in_seconds": next_db_in,
        "next_db_dump_in_human": _human_delta(next_db_in) if next_db_in is not None else None,
    }
