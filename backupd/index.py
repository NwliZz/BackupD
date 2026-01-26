"""Local metadata index for backups (origin, timestamps, flags)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .utils import read_json, write_json_atomic, ensure_dir

INDEX_PATH = "/var/lib/backupd/index.json"


def _load() -> Dict[str, Any]:
    """Load the JSON index, creating the base shape if missing."""
    data = read_json(INDEX_PATH, default=None)
    if not data:
        return {"backups": {}}
    if "backups" not in data:
        data["backups"] = {}
    return data


def _save(data: Dict[str, Any]) -> None:
    """Persist index data atomically."""
    ensure_dir("/var/lib/backupd", mode=0o755)
    write_json_atomic(INDEX_PATH, data, mode=0o600)


def record_backup(
    name: str,
    created_at: Optional[str],
    origin: str,
    uploaded: bool,
    db_dumps: bool,
) -> None:
    """Upsert metadata for a backup name."""
    data = _load()
    data["backups"][name] = {
        "created_at": created_at,
        "origin": origin,          # "manual" | "scheduled"
        "uploaded": bool(uploaded),
        "db_dumps": bool(db_dumps),
        "updated_at_utc": datetime.utcnow().isoformat() + "Z",
    }
    _save(data)


def get_meta(name: str) -> Dict[str, Any]:
    """Return stored metadata for a backup name (or empty dict)."""
    data = _load()
    return data.get("backups", {}).get(name, {})
