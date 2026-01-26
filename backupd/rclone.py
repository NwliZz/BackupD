"""Thin wrappers around rclone for cloud operations."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from .utils import run, hostname_short

def remote_dir(cfg: Dict[str, Any]) -> str:
    """Compute the remote directory path for this host."""
    host = hostname_short()
    remote = cfg.get("rclone_remote", "onedrive")
    base = cfg.get("remote_path", "VPS-Backups").strip("/")
    return f"{remote}:{base}/{host}"

def test_cloud(cfg: Dict[str, Any]) -> str:
    """Create the remote directory and list it to verify access."""
    rd = remote_dir(cfg)
    run(["rclone", "mkdir", rd], check=True)
    out = run(["rclone", "lsd", rd], check=True).stdout
    return f"OK: {rd}\n{out}"

def upload_file(cfg: Dict[str, Any], local_path: str, logger) -> None:
    """Upload a local backup file to the configured remote."""
    rd = remote_dir(cfg)
    run(["rclone", "mkdir", rd], check=True)
    run(["rclone", "copyto", local_path, f"{rd}/{local_path.split('/')[-1]}"], check=True)

def lsjson(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return remote file listing via rclone lsjson."""
    rd = remote_dir(cfg)
    out = run(["rclone", "lsjson", "--files-only", rd], check=True).stdout
    return json.loads(out) if out.strip() else []

def deletefile(cfg: Dict[str, Any], name: str, logger) -> None:
    """Delete a remote file, ignoring errors."""
    rd = remote_dir(cfg)
    run(["rclone", "deletefile", f"{rd}/{name}"], check=False)
