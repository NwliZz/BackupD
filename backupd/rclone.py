from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from .utils import run, hostname_short

def remote_dir(cfg: Dict[str, Any]) -> str:
    host = hostname_short()
    remote = cfg.get("rclone_remote", "onedrive")
    base = cfg.get("remote_path", "VPS-Backups").strip("/")
    return f"{remote}:{base}/{host}"

def test_cloud(cfg: Dict[str, Any]) -> str:
    rd = remote_dir(cfg)
    run(["rclone", "mkdir", rd], check=True)
    out = run(["rclone", "lsd", rd], check=True).stdout
    return f"OK: {rd}\n{out}"

def upload_file(cfg: Dict[str, Any], local_path: str, logger) -> None:
    rd = remote_dir(cfg)
    run(["rclone", "mkdir", rd], check=True)
    run(["rclone", "copyto", local_path, f"{rd}/{local_path.split('/')[-1]}"], check=True)

def lsjson(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    rd = remote_dir(cfg)
    out = run(["rclone", "lsjson", "--files-only", rd], check=True).stdout
    return json.loads(out) if out.strip() else []

def deletefile(cfg: Dict[str, Any], name: str, logger) -> None:
    rd = remote_dir(cfg)
    run(["rclone", "deletefile", f"{rd}/{name}"], check=False)
