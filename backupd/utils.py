from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

def ensure_dir(p: str | Path, mode: int = 0o755) -> Path:
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
    return " ".join(shlex.quote(c) for c in cmd)

def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def write_json_atomic(path: str | Path, obj: Any, mode: int = 0o600) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)

def is_root() -> bool:
    return os.geteuid() == 0

def hostname_short() -> str:
    try:
        out = run(["hostname", "-s"]).stdout.strip()
        return out or "vps"
    except Exception:
        return "vps"
