from __future__ import annotations
import os
import grp

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from .utils import run, ensure_dir, shell_quote

@dataclass
class DBDiscovery:
    mysql_dbs: List[str]
    postgres_dbs: List[str]
    mysql_error: Optional[str] = None
    postgres_error: Optional[str] = None
    raw: Dict[str, Any] = None

def _ensure_postgres_group_dir(p: Path, mode: int) -> None:
    ensure_dir(p, mode=mode)
    try:
        gid = grp.getgrnam("postgres").gr_gid
        os.chown(p, -1, gid)      # keep owner, set group to postgres
        os.chmod(p, mode)         # enforce mode (important if dir already existed)
    except (KeyError, PermissionError):
        pass

def discover_databases(cfg: Dict[str, Any]) -> DBDiscovery:
    raw = {}
    mysql_dbs, pg_dbs = [], []
    mysql_err, pg_err = None, None

    if cfg.get("db", {}).get("mysql", {}).get("enabled", True):
        try:
            cp = run(["mariadb", "-Nse", "SHOW DATABASES;"], check=True)
            mysql_dbs = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
            raw["mysql_cmd"] = "mariadb -Nse 'SHOW DATABASES;'"
            raw["mysql_out"] = mysql_dbs
        except Exception as e:
            mysql_err = str(e)
            raw["mysql_error"] = mysql_err

    if cfg.get("db", {}).get("postgres", {}).get("enabled", True):
        try:
            q = "SELECT datname FROM pg_database WHERE datistemplate = false;"
            cp = run(["runuser", "-u", "postgres", "--", "psql", "-Atc", q], check=True)
            pg_dbs = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
            raw["postgres_cmd"] = "runuser -u postgres -- psql -Atc '<query>'"
            raw["postgres_query"] = q
            raw["postgres_out"] = pg_dbs
        except Exception as e:
            pg_err = str(e)
            raw["postgres_error"] = pg_err

    return DBDiscovery(mysql_dbs=mysql_dbs, postgres_dbs=pg_dbs, mysql_error=mysql_err, postgres_error=pg_err, raw=raw)

def _filter_dbs(all_dbs: List[str], include: List[str], exclude: List[str], system_exclude: List[str]) -> List[str]:
    exclude_set = set(exclude or []) | set(system_exclude or [])
    if include:
        return [d for d in include if d in all_dbs and d not in set(exclude or [])]
    return [d for d in all_dbs if d not in exclude_set]

def selected_databases(cfg: Dict[str, Any], disc: DBDiscovery) -> Dict[str, List[str]]:
    db_cfg = cfg.get("db", {})
    out = {"mysql": [], "postgres": []}

    m = db_cfg.get("mysql", {})
    if db_cfg.get("enabled") and m.get("enabled", True) and disc.mysql_dbs:
        out["mysql"] = _filter_dbs(disc.mysql_dbs, m.get("include_dbs", []), m.get("exclude_dbs", []), m.get("exclude_system_dbs", []))

    p = db_cfg.get("postgres", {})
    if db_cfg.get("enabled") and p.get("enabled", True) and disc.postgres_dbs:
        out["postgres"] = _filter_dbs(disc.postgres_dbs, p.get("include_dbs", []), p.get("exclude_dbs", []), p.get("exclude_system_dbs", []))

    return out

def test_db_access(cfg: Dict[str, Any]) -> Dict[str, Any]:
    res = {"mysql": {"ok": False, "detail": ""}, "postgres": {"ok": False, "detail": ""}}
    try:
        cp = run(["mariadb", "-Nse", "SELECT 1;"], check=True)
        res["mysql"] = {"ok": True, "detail": cp.stdout.strip()}
    except Exception as e:
        res["mysql"] = {"ok": False, "detail": str(e)}

    try:
        cp = run(["runuser", "-u", "postgres", "--", "psql", "-Atc", "SELECT 1;"], check=True)
        res["postgres"] = {"ok": True, "detail": cp.stdout.strip()}
    except Exception as e:
        res["postgres"] = {"ok": False, "detail": str(e)}
    return res

def dump_databases(cfg: Dict[str, Any], selected: Dict[str, List[str]], logger) -> Path:
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = datetime.now(tz)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    staging = Path(cfg.get("staging_dir", "/var/lib/backupd/staging"))
    dumps_parent = staging / "db_dumps"
    dump_root = dumps_parent / now.strftime("%Y%m%d")

    # postgres must be able to traverse staging, and write into db_dumps
    _ensure_postgres_group_dir(staging, mode=0o750)
    _ensure_postgres_group_dir(dumps_parent, mode=0o770)
    _ensure_postgres_group_dir(dump_root, mode=0o770)

    mcfg = cfg.get("db", {}).get("mysql", {})
    if selected.get("mysql"):
        for dbname in selected["mysql"]:
            out = dump_root / f"mysql_{dbname}_{stamp}.sql"
            cmd = ["mariadb-dump"] + list(mcfg.get("dump_options", [])) + ["--databases", dbname]
            logger.info("Dumping MySQL DB %s with: %s", dbname, shell_quote(cmd))
            cp = run(cmd, check=True)
            out.write_text(cp.stdout, encoding="utf-8")
            if mcfg.get("compress", True):
                run(["gzip", "-f", str(out)], check=True)

    pcfg = cfg.get("db", {}).get("postgres", {})
    if selected.get("postgres"):
        fmt = pcfg.get("format", "custom")
        for dbname in selected["postgres"]:
            if fmt == "custom":
                out = dump_root / f"pg_{dbname}_{stamp}.dump"
                cmd = ["runuser", "-u", "postgres", "--", "pg_dump", "-Fc", "-d", dbname, "-f", str(out)]
            else:
                out = dump_root / f"pg_{dbname}_{stamp}.sql"
                cmd = ["runuser", "-u", "postgres", "--", "pg_dump", "-d", dbname, "-f", str(out)]
            logger.info("Dumping Postgres DB %s with: %s", dbname, shell_quote(cmd))
            run(cmd, check=True)
            if fmt == "plain" and pcfg.get("compress", False):
                run(["gzip", "-f", str(out)], check=True)

    return dump_root
