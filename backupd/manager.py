from __future__ import annotations

import os
import re
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional
from zoneinfo import ZoneInfo

from .utils import hostname_short
from . import index as bindex


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.tar\.gz$")


def _tz(cfg: Dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(cfg.get("timezone", "UTC"))


def _remote_dir(cfg: Dict[str, Any]) -> str:
    remote = cfg.get("rclone_remote", "onedrive")
    base = cfg.get("remote_path", "VPS-Backups").strip().strip("/")
    host = hostname_short()
    return f"{remote}:{base}/{host}"


def _remote_file(cfg: Dict[str, Any], name: str) -> str:
    return f"{_remote_dir(cfg)}/{name}"


def _local_dir(cfg: Dict[str, Any]) -> Path:
    return Path(cfg.get("local_dir", "/var/backups/backupd"))


def _safe_name(name: str) -> None:
    if "/" in name or "\\" in name or not SAFE_NAME_RE.match(name):
        raise ValueError(f"Unsafe backup name: {name}")


def _parse_stamp_from_name(name: str, tz: ZoneInfo) -> Optional[str]:
    m = re.search(r"_(\d{8})_(\d{6})\.tar\.gz$", name)
    if not m:
        return None
    dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return dt.replace(tzinfo=tz).isoformat()


def _rclone_lsjson(path: str) -> List[Dict[str, Any]]:
    cp = subprocess.run(
        ["rclone", "lsjson", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "rclone lsjson failed")
    try:
        return json.loads(cp.stdout)
    except Exception as e:
        raise RuntimeError(f"Failed to parse rclone lsjson: {e}")


def inventory(cfg: Dict[str, Any]) -> Dict[str, Any]:
    tz = _tz(cfg)
    pinned = set(cfg.get("retention", {}).get("pinned", []))

    # local
    local_items: List[Dict[str, Any]] = []
    ld = _local_dir(cfg)
    if ld.exists():
        for p in ld.glob("*.tar.gz"):
            name = p.name
            if not SAFE_NAME_RE.match(name):
                continue
            st = p.stat()
            stamp = _parse_stamp_from_name(name, tz)
            meta = bindex.get_meta(name)
            local_items.append(
                {
                    "name": name,
                    "size_bytes": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime, tz).isoformat(),
                    "stamp": stamp,
                    "origin": meta.get("origin") or "unknown",
                    "pinned": name in pinned,
                }
            )
    local_items.sort(key=lambda x: x.get("stamp") or x.get("mtime") or "", reverse=True)

    # remote
    remote_items: List[Dict[str, Any]] = []
    if cfg.get("upload_enabled", True):
        rd = _remote_dir(cfg)
        try:
            rows = _rclone_lsjson(rd)
            for r in rows:
                if r.get("IsDir"):
                    continue
                name = r.get("Name") or ""
                if not name.endswith(".tar.gz") or not SAFE_NAME_RE.match(name):
                    continue
                stamp = _parse_stamp_from_name(name, tz)
                meta = bindex.get_meta(name)
                # ModTime may be missing depending on provider
                remote_items.append(
                    {
                        "name": name,
                        "size_bytes": int(r.get("Size") or 0),
                        "mtime": r.get("ModTime") or None,
                        "stamp": stamp,
                        "origin": meta.get("origin") or "unknown",
                        "pinned": name in pinned,
                    }
                )
        except Exception:
            remote_items = []

    remote_items.sort(key=lambda x: x.get("stamp") or x.get("mtime") or "", reverse=True)

    return {
        "local": local_items,
        "remote": remote_items,
        "pinned": sorted(list(pinned)),
        "remote_dir": _remote_dir(cfg),
        "local_dir": str(_local_dir(cfg)),
    }


def apply_plan(cfg: Dict[str, Any], plan: Dict[str, Any], logger) -> Dict[str, Any]:
    """
    Plan format (from UI):
    {
      "actions": {
         "<name>": {"action": "destroy|keep_local|keep_cloud|copy_to_local|copy_to_cloud|none"},
         ...
      },
      "pinned": ["...tar.gz", ...]
    }
    """
    tz = _tz(cfg)
    inv = inventory(cfg)

    local_set: Set[str] = {x["name"] for x in inv["local"]}
    remote_set: Set[str] = {x["name"] for x in inv["remote"]}

    actions = plan.get("actions", {}) or {}
    new_pinned = plan.get("pinned", None)

    results = {
        "copied_to_cloud": [],
        "copied_to_local": [],
        "deleted_local": [],
        "deleted_cloud": [],
        "errors": [],
        "pinned_saved": False,
    }

    # Update pinned list first (so retention won't fight us after apply)
    if isinstance(new_pinned, list):
        cfg.setdefault("retention", {})
        cfg["retention"]["pinned"] = [n for n in new_pinned if isinstance(n, str)]
        results["pinned_saved"] = True

    # Helper paths
    ld = _local_dir(cfg)
    rd = _remote_dir(cfg)

    def copy_to_cloud(name: str) -> None:
        _safe_name(name)
        src = str(ld / name)
        dst = _remote_file(cfg, name)
        logger.info("Copy local->cloud: %s -> %s", src, dst)
        subprocess.run(["rclone", "copyto", src, dst], check=True)

    def copy_to_local(name: str) -> None:
        _safe_name(name)
        src = _remote_file(cfg, name)
        dst = str(ld / name)
        logger.info("Copy cloud->local: %s -> %s", src, dst)
        # ensure dir
        ld.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rclone", "copyto", src, dst], check=True)

    def delete_local(name: str) -> None:
        _safe_name(name)
        p = ld / name
        if p.exists():
            logger.info("Delete local: %s", p)
            p.unlink()

    def delete_cloud(name: str) -> None:
        _safe_name(name)
        rf = _remote_file(cfg, name)
        logger.info("Delete cloud: %s", rf)
        subprocess.run(["rclone", "deletefile", rf], check=True)

    # Execute actions safely:
    # - For migrate/copy: do COPY first, then delete source if needed.
    for name, spec in actions.items():
        try:
            if not isinstance(spec, dict):
                continue
            action = spec.get("action", "none")
            if action == "none":
                continue

            _safe_name(name)
            in_local = name in local_set
            in_remote = name in remote_set

            if action == "destroy":
                # delete wherever exists
                if in_local:
                    delete_local(name)
                    results["deleted_local"].append(name)
                if in_remote and cfg.get("upload_enabled", True):
                    delete_cloud(name)
                    results["deleted_cloud"].append(name)

            elif action == "keep_local":
                # migrate to local only (delete cloud; if missing locally, copy from cloud first)
                if not in_local and in_remote:
                    copy_to_local(name)
                    results["copied_to_local"].append(name)
                    local_set.add(name)
                if in_remote and cfg.get("upload_enabled", True):
                    delete_cloud(name)
                    results["deleted_cloud"].append(name)

            elif action == "keep_cloud":
                # migrate to cloud only (delete local; if missing in cloud, copy first)
                if cfg.get("upload_enabled", True):
                    if not in_remote and in_local:
                        copy_to_cloud(name)
                        results["copied_to_cloud"].append(name)
                        remote_set.add(name)
                    if in_local:
                        delete_local(name)
                        results["deleted_local"].append(name)

            elif action == "copy_to_cloud":
                if cfg.get("upload_enabled", True) and in_local and not in_remote:
                    copy_to_cloud(name)
                    results["copied_to_cloud"].append(name)
                    remote_set.add(name)

            elif action == "copy_to_local":
                if in_remote and not in_local:
                    copy_to_local(name)
                    results["copied_to_local"].append(name)
                    local_set.add(name)

        except Exception as e:
            results["errors"].append({"name": name, "error": str(e)})

    return results
