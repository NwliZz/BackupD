"""Shared utilities for filesystem, subprocess, and JSON handling."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

def ensure_dir(p: str | Path, mode: int = 0o755) -> Path:
    """Create a directory if needed and set permissions best-effort."""
    path = Path(p)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except PermissionError:
        pass
    return path

def run(
    args: List[str],
    *,
    check: bool = True,
    capture: bool = True,
    text: bool = True,
    input_text: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess with common defaults and optional input text."""
    return subprocess.run(
        args,
        check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=text,
        input=input_text,
        env=env,
        timeout=timeout,
    )

def shell_quote(cmd: List[str]) -> str:
    """Return a shell-escaped string for logging/debug output."""
    return " ".join(shlex.quote(c) for c in cmd)

def read_json(path: str | Path, default: Any = None) -> Any:
    """Read JSON from disk, returning a default on missing file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def write_json_atomic(path: str | Path, obj: Any, mode: int = 0o600) -> None:
    """Write JSON atomically via a temp file and rename."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)

def is_root() -> bool:
    """Return True when running as root (for privileged CLI)."""
    return os.geteuid() == 0

def hostname_short() -> str:
    """Get a short hostname, falling back to a stable default."""
    try:
        out = run(["hostname", "-s"]).stdout.strip()
        return out or "vps"
    except Exception:
        return "vps"
