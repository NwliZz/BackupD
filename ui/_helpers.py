import json
import math
import re
import subprocess
from typing import Any, Dict, Optional, Tuple

import streamlit as st


def inject_css() -> None:
    st.markdown(
        """
<style>
:root{
  --ok:#22c55e;
  --warn:#f59e0b;
  --bad:#ef4444;
  --muted: rgba(120,120,140,.9);
  --card: rgba(255,255,255,.05);
  --border: rgba(255,255,255,.10);
  --shadow: rgba(0,0,0,.25);
}
.bk-row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:.25rem 0 .75rem 0; }
.bk-badge{
  display:inline-flex; align-items:center; gap:8px;
  padding:6px 12px; border-radius:999px;
  border:1px solid var(--border);
  background: var(--card);
  box-shadow: 0 8px 18px var(--shadow);
  font-weight:700; font-size: .90rem;
}
.bk-dot{ width:10px; height:10px; border-radius:999px; display:inline-block; }
.bk-ok{ color: var(--ok); border-color: rgba(34,197,94,.35); background: rgba(34,197,94,.10); }
.bk-warn{ color: var(--warn); border-color: rgba(245,158,11,.35); background: rgba(245,158,11,.10); }
.bk-bad{ color: var(--bad); border-color: rgba(239,68,68,.35); background: rgba(239,68,68,.10); }
.bk-card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px 16px 12px 16px;
  box-shadow: 0 10px 24px var(--shadow);
}
.bk-title{ font-size:1.05rem; font-weight:900; margin:0 0 .25rem 0; }
.bk-sub{ color: var(--muted); font-size:.92rem; margin:0 0 .5rem 0;}
.bk-kv{ color: rgba(255,255,255,.86); font-size:.95rem; }
hr.bk-hr{ border:none; border-top:1px solid var(--border); margin:.75rem 0; }
.small-mono code { font-size: .85rem !important; }
</style>
        """,
        unsafe_allow_html=True,
    )


def hbytes(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return "0 B"
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = min(int(math.floor(math.log(n, 1024))), len(units) - 1)
    p = 1024**i
    v = n / p
    return f"{v:.2f} {units[i]}" if v < 10 and i > 0 else f"{v:.1f} {units[i]}"


def badge(label: str, kind: str = "ok") -> None:
    color = {"ok": "var(--ok)", "warn": "var(--warn)", "bad": "var(--bad)"}[kind]
    cls = {"ok": "bk-ok", "warn": "bk-warn", "bad": "bk-bad"}[kind]
    st.markdown(
        f"""
<div class="bk-row">
  <span class="bk-badge {cls}">
    <span class="bk-dot" style="background:{color};"></span>
    {label}
  </span>
</div>
        """,
        unsafe_allow_html=True,
    )


def run_root(cmd, input_text: Optional[str] = None, timeout: int = 1800) -> Tuple[int, str, str]:
    p = subprocess.run(
        ["sudo", "/usr/local/sbin/backupctl"] + list(cmd),
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return p.returncode, p.stdout, p.stderr


def parse_json_best_effort(text: str) -> Optional[Dict[str, Any]]:
    s = (text or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    # If logs are mixed in, try to extract the last JSON object
    m = re.search(r"(\{.*\})\s*$", s, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None


def show_logs(stderr: str, title: str = "Details / logs") -> None:
    if not stderr.strip():
        return
    with st.expander(title):
        st.code(stderr.strip(), language="text")


def card(title: str, subtitle: str = "") -> Any:
    st.markdown(
        f"""
<div class="bk-card">
  <div class="bk-title">{title}</div>
  <div class="bk-sub">{subtitle}</div>
</div>
        """,
        unsafe_allow_html=True,
    )