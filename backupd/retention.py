from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set
from zoneinfo import ZoneInfo

from . import rclone as rcl

NAME_RE = re.compile(r"_(\d{8})_(\d{6})\.tar\.gz$")

def _parse_ts_from_name(name: str, tz: ZoneInfo) -> datetime | None:
    m = NAME_RE.search(name)
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    return datetime(int(d[0:4]), int(d[4:6]), int(d[6:8]), int(t[0:2]), int(t[2:4]), int(t[4:6]), tzinfo=tz)

def _age_days(now: datetime, ts: datetime) -> float:
    return (now - ts).total_seconds() / 86400.0

def select_keep(files: List[Tuple[str, datetime]], now: datetime, policy: Dict[str, Any]) -> Set[str]:
    ka = int(policy.get("keep_all_days", 0))
    kd = int(policy.get("keep_daily_until_days", 0))
    kw = int(policy.get("keep_weekly_until_days", 0))
    km = int(policy.get("keep_monthly_until_days", 0))

    keep: Set[str] = set()

    for name, ts in files:
        if _age_days(now, ts) <= ka:
            keep.add(name)

    def keep_latest(min_days_excl: int, max_days_incl: int, key_fn):
        group = {}
        for name, ts in files:
            age = _age_days(now, ts)
            if age > min_days_excl and age <= max_days_incl:
                k = key_fn(ts)
                if k not in group or ts > group[k][1]:
                    group[k] = (name, ts)
        for name, _ in group.values():
            keep.add(name)

    if kd and kd > ka:
        keep_latest(ka, kd, lambda ts: ts.strftime("%Y-%m-%d"))
    if kw and kw > kd:
        keep_latest(kd, kw, lambda ts: f"{ts.isocalendar().year}-W{ts.isocalendar().week:02d}")
    if km and km > kw:
        keep_latest(kw, km, lambda ts: ts.strftime("%Y-%m"))

    return keep

def local_inventory(cfg: Dict[str, Any]) -> List[Tuple[str, datetime, int]]:
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    d = Path(cfg.get("local_dir", "/var/backups/backupd"))
    if not d.exists():
        return []
    items = []
    for name in os.listdir(d):
        if not name.endswith(".tar.gz"):
            continue
        p = d / name
        ts = _parse_ts_from_name(name, tz) or datetime.fromtimestamp(p.stat().st_mtime, tz=tz)
        items.append((name, ts, p.stat().st_size))
    items.sort(key=lambda x: x[1], reverse=True)
    return items

def remote_inventory(cfg: Dict[str, Any]) -> List[Tuple[str, datetime, int]]:
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    out = []
    for it in rcl.lsjson(cfg):
        name = it.get("Name")
        mt = it.get("ModTime")
        if not name or not mt:
            continue
        ts = datetime.fromisoformat(mt.replace("Z", "+00:00")).astimezone(tz)
        size = int(it.get("Size") or 0)
        out.append((name, ts, size))
    out.sort(key=lambda x: x[1], reverse=True)
    return out

def plan_prune(cfg: Dict[str, Any], scope: str) -> Dict[str, Any]:
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = datetime.now(tz)
    pol = cfg.get("retention", {}).get(scope, {})
    inv = [(n, ts) for (n, ts, _s) in (local_inventory(cfg) if scope=="local" else remote_inventory(cfg))]
    keep = select_keep(inv, now, pol)
    delete = [n for n, _ in inv if n not in keep]
    return {"scope": scope, "keep": sorted(list(keep)), "delete": delete, "policy": pol}

def apply_prune(cfg: Dict[str, Any], scope: str, logger) -> Dict[str, Any]:
    plan = plan_prune(cfg, scope)
    if scope == "local":
        d = Path(cfg.get("local_dir", "/var/backups/backupd"))
        for name in plan["delete"]:
            try:
                (d / name).unlink()
                logger.info("Deleted local backup: %s", name)
            except FileNotFoundError:
                pass
    else:
        for name in plan["delete"]:
            rcl.deletefile(cfg, name, logger)
    return plan
