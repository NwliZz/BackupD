"""Schedule state tracking for backups and database dumps."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from .utils import read_json, write_json_atomic, ensure_dir

STATE_PATH = "/var/lib/backupd/state.json"

def _load_state() -> Dict[str, Any]:
    """Load scheduler state from disk, creating a base shape if missing."""
    st = read_json(STATE_PATH, default=None)
    if st is None:
        st = {"runs": {}, "db_dumps": {}}
    return st

def _save_state(st: Dict[str, Any]) -> None:
    """Persist scheduler state atomically."""
    ensure_dir("/var/lib/backupd", mode=0o755)
    write_json_atomic(STATE_PATH, st, mode=0o600)

def should_run_times(now: datetime, times: list[str], tolerance_minutes: int, state_key_prefix: str) -> Tuple[bool, Optional[str]]:
    """Check whether any scheduled time is due and not already run today."""
    # Decide if a scheduled slot is due within tolerance and wasn't already run today.
    tol = int(tolerance_minutes)
    today = now.strftime("%Y-%m-%d")
    st = _load_state()
    runs = st.setdefault("runs", {})
    for t in times:
        hh, mm = map(int, t.split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((now - target).total_seconds()) <= tol * 60:
            key = f"{state_key_prefix}:{today} {t}"
            if runs.get(key):
                continue
            return True, key
    return False, None

def mark_run(key: str) -> None:
    """Record a completed scheduled run and prune old state."""
    st = _load_state()
    st.setdefault("runs", {})[key] = datetime.utcnow().isoformat() + "Z"
    cutoff = datetime.utcnow() - timedelta(days=10)
    new_runs = {}
    for k, v in st["runs"].items():
        try:
            dt = datetime.fromisoformat(v.replace("Z", ""))
        except Exception:
            continue
        if dt >= cutoff:
            new_runs[k] = v
    st["runs"] = new_runs
    _save_state(st)

def should_dump_db(now: datetime, cfg: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Check if a database dump should run based on policy and schedule."""
    db = cfg.get("db", {})
    if not db.get("enabled"):
        return False, None

    policy = db.get("policy", "hybrid")
    if policy == "every_backup":
        return True, "db:every_backup"

    times = db.get("dump_times", [])
    if not times:
        return False, None

    tol = int(cfg.get("tolerance_minutes", 2))
    today = now.strftime("%Y-%m-%d")
    st = _load_state()
    dumps = st.setdefault("db_dumps", {})
    for t in times:
        hh, mm = map(int, t.split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((now - target).total_seconds()) <= tol * 60:
            key = f"dbdump:{today} {t}"
            if dumps.get(key):
                continue
            return True, key
    return False, None

def mark_db_dump(key: str) -> None:
    """Record a completed database dump and prune old state."""
    st = _load_state()
    st.setdefault("db_dumps", {})[key] = datetime.utcnow().isoformat() + "Z"
    cutoff = datetime.utcnow() - timedelta(days=10)
    new_dumps = {}
    for k, v in st["db_dumps"].items():
        try:
            dt = datetime.fromisoformat(v.replace("Z", ""))
        except Exception:
            continue
        if dt >= cutoff:
            new_dumps[k] = v
    st["db_dumps"] = new_dumps
    _save_state(st)
