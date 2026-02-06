"""Database discovery, selection, and dump orchestration."""

from __future__ import annotations
import os
import grp
import json
import re
import subprocess

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .utils import run, ensure_dir, shell_quote

@dataclass
class DBDiscovery:
    """Container for DB discovery results and any errors."""
    mysql_dbs: List[str]
    postgres_dbs: List[str]
    docker_dbs: List[str]
    mysql_error: Optional[str] = None
    postgres_error: Optional[str] = None
    docker_error: Optional[str] = None
    raw: Dict[str, Any] = None

DOCKER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

def _docker_db_id(engine: str, container: str, dbname: str) -> str:
    """Format a docker DB identifier for config/UI."""
    return f"{engine}@{container}/{dbname}"

def _parse_docker_db_id(value: str) -> Optional[Tuple[str, str, str]]:
    """Parse docker DB identifier into (engine, container, dbname)."""
    if not isinstance(value, str) or "@" not in value or "/" not in value:
        return None
    engine, rest = value.split("@", 1)
    container, dbname = rest.split("/", 1)
    if not engine or not container or not dbname:
        return None
    return engine, container, dbname

def _docker_db_engine(image: str) -> Optional[str]:
    """Best-effort engine detection from image name."""
    img = (image or "").lower()
    if "postgres" in img:
        return "postgres"
    if any(k in img for k in ("mysql", "mariadb", "percona")):
        return "mysql"
    return None

def _safe_container_name(name: str) -> str:
    """Sanitize docker container names for filesystem usage."""
    if isinstance(name, str) and DOCKER_ID_RE.match(name):
        return name
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "container")

def _docker_ps() -> List[Dict[str, str]]:
    """List running docker containers (id, name, image)."""
    cp = run(["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}"], check=False)
    if cp.returncode != 0:
        raise RuntimeError(cp.stdout.strip() or "docker ps failed")
    out = []
    for line in (cp.stdout or "").splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 3:
            out.append({"id": parts[0], "name": parts[1], "image": parts[2]})
    return out

def _docker_env(container: str) -> Dict[str, str]:
    """Fetch container environment variables (key/value map)."""
    cp = run(["docker", "inspect", "-f", "{{json .Config.Env}}", container], check=False)
    if cp.returncode != 0:
        return {}
    try:
        env_list = json.loads(cp.stdout) or []
    except Exception:
        return {}
    env = {}
    for item in env_list:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            env[k] = v
    return env

def _mysql_credentials_from_env(env: Dict[str, str]) -> List[Tuple[str, Optional[str], str]]:
    """Return candidate MySQL credentials as (user, password, label)."""
    creds: List[Tuple[str, Optional[str], str]] = []
    root_pw = env.get("MYSQL_ROOT_PASSWORD") or env.get("MARIADB_ROOT_PASSWORD")
    if root_pw:
        creds.append(("root", root_pw, "root_env"))
    user = env.get("MYSQL_USER") or env.get("MARIADB_USER")
    user_pw = env.get("MYSQL_PASSWORD") or env.get("MARIADB_PASSWORD")
    if user and user_pw:
        creds.append((user, user_pw, "user_env"))
    if env.get("MYSQL_ALLOW_EMPTY_PASSWORD") or env.get("MARIADB_ALLOW_EMPTY_ROOT_PASSWORD"):
        creds.append(("root", None, "empty_root"))
    creds.append(("root", None, "no_password"))
    # de-dupe
    seen = set()
    uniq = []
    for user, pw, label in creds:
        key = (user, pw)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((user, pw, label))
    return uniq

def _docker_exec_missing(output: str) -> bool:
    """Detect 'command not found' style docker exec errors."""
    msg = (output or "").lower()
    return "executable file not found" in msg or "no such file or directory" in msg

def _docker_mysql_dbs(container: str) -> Tuple[List[str], Dict[str, Any]]:
    """Discover MySQL DBs inside a docker container."""
    env = _docker_env(container)
    creds = _mysql_credentials_from_env(env)
    query = "SHOW DATABASES;"
    last_err = None
    for client in ("mariadb", "mysql"):
        client_missing = False
        for user, pw, label in creds:
            cmd = ["docker", "exec", container, client]
            if user:
                cmd += ["-u", user]
            if pw:
                cmd += [f"--password={pw}"]
            cmd += ["-Nse", query]
            try:
                cp = run(cmd, check=False, timeout=10)
            except subprocess.TimeoutExpired:
                last_err = "docker mysql discovery timed out"
                continue
            if cp.returncode == 0:
                dbs = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
                return dbs, {"engine": "mysql", "container": container, "client": client, "auth": label}
            if _docker_exec_missing(cp.stdout):
                client_missing = True
                break
            last_err = cp.stdout.strip() or f"{client} query failed"
        if client_missing:
            continue
    raise RuntimeError(last_err or "docker mysql discovery failed")

def _docker_postgres_dbs(container: str) -> Tuple[List[str], Dict[str, Any]]:
    """Discover Postgres DBs inside a docker container."""
    query = "SELECT datname FROM pg_database WHERE datistemplate = false;"
    last_err = None
    for use_user in (True, False):
        cmd = ["docker", "exec"]
        if use_user:
            cmd += ["-u", "postgres"]
        cmd += [container, "psql", "-Atc", query]
        try:
            cp = run(cmd, check=False, timeout=10)
        except subprocess.TimeoutExpired:
            last_err = "docker postgres discovery timed out"
            continue
        if cp.returncode == 0:
            dbs = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
            return dbs, {"engine": "postgres", "container": container, "client": "psql", "user": "postgres" if use_user else "default"}
        if _docker_exec_missing(cp.stdout):
            last_err = "psql not found in container"
            continue
        last_err = cp.stdout.strip() or "psql query failed"
    raise RuntimeError(last_err or "docker postgres discovery failed")

def _discover_docker_dbs() -> Tuple[List[str], Dict[str, Any]]:
    """Discover DBs in running docker containers."""
    raw = {"containers": []}
    out: List[str] = []
    containers = _docker_ps()
    raw["containers_checked"] = len(containers)
    for c in containers:
        engine = _docker_db_engine(c.get("image", ""))
        if not engine:
            continue
        entry = {"name": c.get("name"), "image": c.get("image"), "engine": engine}
        try:
            if engine == "mysql":
                dbs, meta = _docker_mysql_dbs(c["name"])
            else:
                dbs, meta = _docker_postgres_dbs(c["name"])
            entry.update(meta)
            entry["dbs"] = dbs
            for dbname in dbs:
                out.append(_docker_db_id(engine, c["name"], dbname))
        except Exception as e:
            entry["error"] = str(e)
        raw["containers"].append(entry)
    return out, raw

def _sanitize_cmd(cmd: List[str]) -> List[str]:
    """Mask passwords in command args for logging."""
    out = []
    for c in cmd:
        if isinstance(c, str) and c.startswith("--password="):
            out.append("--password=***")
        else:
            out.append(c)
    return out

def _docker_mysql_dump(container: str, dbname: str, dump_options: List[str]) -> Tuple[str, Dict[str, Any]]:
    """Run a MySQL dump inside docker and return stdout + metadata."""
    env = _docker_env(container)
    creds = _mysql_credentials_from_env(env)
    last_err = None
    for client in ("mariadb-dump", "mysqldump"):
        client_missing = False
        for user, pw, label in creds:
            cmd = ["docker", "exec", container, client]
            if user:
                cmd += ["-u", user]
            if pw:
                cmd += [f"--password={pw}"]
            cmd += list(dump_options or []) + ["--databases", dbname]
            cp = run(cmd, check=False)
            if cp.returncode == 0:
                meta = {"client": client, "auth": label, "cmd": _sanitize_cmd(cmd)}
                return cp.stdout, meta
            if _docker_exec_missing(cp.stdout):
                client_missing = True
                break
            last_err = cp.stdout.strip() or f"{client} dump failed"
        if client_missing:
            continue
    raise RuntimeError(last_err or "docker mysql dump failed")

def _docker_postgres_dump(container: str, dbname: str, fmt: str) -> Tuple[bytes, Dict[str, Any]]:
    """Run a Postgres dump inside docker and return bytes + metadata."""
    last_err = None
    for use_user in (True, False):
        cmd = ["docker", "exec"]
        if use_user:
            cmd += ["-u", "postgres"]
        if fmt == "custom":
            cmd += [container, "pg_dump", "-Fc", "-d", dbname]
        else:
            cmd += [container, "pg_dump", "-d", dbname]
        cp = run(cmd, check=False, text=False)
        if cp.returncode == 0:
            meta = {"client": "pg_dump", "user": "postgres" if use_user else "default", "cmd": cmd}
            return cp.stdout, meta
        if _docker_exec_missing(cp.stdout.decode("utf-8", "ignore")):
            last_err = "pg_dump not found in container"
            continue
        last_err = (cp.stdout or b"").decode("utf-8", "ignore").strip() or "pg_dump failed"
    raise RuntimeError(last_err or "docker postgres dump failed")

def _ensure_postgres_group_dir(p: Path, mode: int) -> None:
    """Ensure directory exists and is accessible by postgres group."""
    ensure_dir(p, mode=mode)
    try:
        gid = grp.getgrnam("postgres").gr_gid
        os.chown(p, -1, gid)      # keep owner, set group to postgres
        os.chmod(p, mode)         # enforce mode (important if dir already existed)
    except (KeyError, PermissionError):
        pass

def discover_databases(cfg: Dict[str, Any]) -> DBDiscovery:
    """Detect MySQL/Postgres databases available for backup."""
    raw = {}
    mysql_dbs, pg_dbs, docker_dbs = [], [], []
    mysql_err, pg_err, docker_err = None, None, None

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

    if cfg.get("db", {}).get("docker", {}).get("enabled", True):
        try:
            docker_dbs, docker_raw = _discover_docker_dbs()
            raw["docker"] = docker_raw
        except Exception as e:
            docker_err = str(e)
            raw["docker_error"] = docker_err

    return DBDiscovery(
        mysql_dbs=mysql_dbs,
        postgres_dbs=pg_dbs,
        docker_dbs=docker_dbs,
        mysql_error=mysql_err,
        postgres_error=pg_err,
        docker_error=docker_err,
        raw=raw,
    )

def _filter_dbs(all_dbs: List[str], include: List[str], exclude: List[str], system_exclude: List[str]) -> List[str]:
    """Apply include/exclude rules for database selection."""
    exclude_set = set(exclude or []) | set(system_exclude or [])
    if include:
        return [d for d in include if d in all_dbs and d not in set(exclude or [])]
    return [d for d in all_dbs if d not in exclude_set]

def _filter_docker_dbs(
    all_dbs: List[str],
    include: List[str],
    exclude: List[str],
    system_defaults: Dict[str, List[str]],
) -> List[str]:
    """Filter docker DB identifiers with engine-aware system DB excludes."""
    exclude_set = set(exclude or [])
    if include:
        return [d for d in include if d in all_dbs and d not in exclude_set]
    out = []
    for d in all_dbs:
        if d in exclude_set:
            continue
        parsed = _parse_docker_db_id(d)
        if not parsed:
            out.append(d)
            continue
        engine, _container, dbname = parsed
        sys_dbs = (system_defaults or {}).get(engine, [])
        if dbname in sys_dbs:
            continue
        out.append(d)
    return out

def selected_databases(cfg: Dict[str, Any], disc: DBDiscovery) -> Dict[str, List[str]]:
    """Compute final DB lists based on config and discovery results."""
    db_cfg = cfg.get("db", {})
    out = {"mysql": [], "postgres": [], "docker": []}

    m = db_cfg.get("mysql", {})
    if db_cfg.get("enabled") and m.get("enabled", True) and disc.mysql_dbs:
        out["mysql"] = _filter_dbs(disc.mysql_dbs, m.get("include_dbs", []), m.get("exclude_dbs", []), m.get("exclude_system_dbs", []))

    p = db_cfg.get("postgres", {})
    if db_cfg.get("enabled") and p.get("enabled", True) and disc.postgres_dbs:
        out["postgres"] = _filter_dbs(disc.postgres_dbs, p.get("include_dbs", []), p.get("exclude_dbs", []), p.get("exclude_system_dbs", []))

    d = db_cfg.get("docker", {})
    if db_cfg.get("enabled") and d.get("enabled", True) and disc.docker_dbs:
        out["docker"] = _filter_docker_dbs(
            disc.docker_dbs,
            d.get("include_dbs", []),
            d.get("exclude_dbs", []),
            cfg.get("system_db_defaults", {}),
        )

    return out

def test_db_access(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Run a lightweight query against DBs to verify access."""
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
    """Dump selected databases into a dated staging folder."""
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

    if selected.get("docker"):
        fmt = pcfg.get("format", "custom")
        for item in selected["docker"]:
            parsed = _parse_docker_db_id(item)
            if not parsed:
                logger.warning("Skipping docker DB target with unrecognized format: %s", item)
                continue
            engine, container, dbname = parsed
            safe_container = _safe_container_name(container)
            if engine == "mysql":
                out = dump_root / f"docker_mysql_{safe_container}_{dbname}_{stamp}.sql"
                dump_text, meta = _docker_mysql_dump(container, dbname, mcfg.get("dump_options", []))
                logger.info(
                    "Dumping Docker MySQL DB %s (container %s) with: %s",
                    dbname,
                    container,
                    shell_quote(meta.get("cmd", [])),
                )
                out.write_text(dump_text, encoding="utf-8")
                if mcfg.get("compress", True):
                    run(["gzip", "-f", str(out)], check=True)
            elif engine == "postgres":
                if fmt == "custom":
                    out = dump_root / f"docker_pg_{safe_container}_{dbname}_{stamp}.dump"
                else:
                    out = dump_root / f"docker_pg_{safe_container}_{dbname}_{stamp}.sql"
                dump_bytes, meta = _docker_postgres_dump(container, dbname, fmt)
                logger.info(
                    "Dumping Docker Postgres DB %s (container %s) with: %s",
                    dbname,
                    container,
                    shell_quote(meta.get("cmd", [])),
                )
                if fmt == "custom":
                    out.write_bytes(dump_bytes)
                else:
                    out.write_text(dump_bytes.decode("utf-8", "ignore"), encoding="utf-8")
                    if pcfg.get("compress", False):
                        run(["gzip", "-f", str(out)], check=True)
            else:
                logger.warning("Skipping docker DB target with unknown engine: %s", item)

    return dump_root
