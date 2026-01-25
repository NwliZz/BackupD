from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .utils import read_json, write_json_atomic, ensure_dir

INDEX_PATH = "/var/lib/backupd/index.json"


def _load() -> Dict[str, Any]:
    data = read_json(INDEX_PATH, default=None)
    if not data:
        return {"backups": {}}
    if "backups" not in data:
        data["backups"] = {}
    return data


def _save(data: Dict[str, Any]) -> None:
    ensure_dir("/var/lib/backupd", mode=0o755)
    write_json_atomic(INDEX_PATH, data, mode=0o600)


def record_backup(
    name: str,
    created_at: Optional[str],
    origin: str,
    uploaded: bool,
    db_dumps: bool,
) -> None:
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
    data = _load()
    return data.get("backups", {}).get(name, {})
