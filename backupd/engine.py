from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from .config import load_config, validate_config
from .logging_setup import setup_logging
from .utils import ensure_dir, run, hostname_short, shell_quote
from . import rclone as rcl
from . import retention
from . import db as dbmod
from .scheduler import should_run_times, mark_run, should_dump_db, mark_db_dump
from .notify import notify_failure
from shutil import rmtree


@dataclass
class RunResult:
    ok: bool
    message: str
    archive_path: Optional[str] = None
    uploaded: bool = False
    retention_local_deleted: int = 0
    retention_remote_deleted: int = 0
    db_dump_dir: Optional[str] = None

def _effective_include_paths(cfg: Dict[str, Any]) -> list[str]:
    return ["/backup"] if cfg.get("mode") == "hestia" else cfg.get("include_paths", ["/etc","/home","/var/www"])

def build_archive(cfg: Dict[str, Any], include_paths: list[str], extra_paths: list[str], logger) -> str:
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = datetime.now(tz)
    host = hostname_short()
    stamp = now.strftime("%Y%m%d_%H%M%S")

    local_dir = Path(cfg.get("local_dir", "/var/backups/backupd"))
    ensure_dir(local_dir, mode=0o750)
    archive = local_dir / f"{host}_{stamp}.tar.gz"

    rels = []
    for p in include_paths + extra_paths:
        p = p.strip()
        if not p:
            continue
        rels.append(p.lstrip("/") if p.startswith("/") else p)

    excludes = cfg.get("exclude_globs", [])
    cmd = ["tar", "-czf", str(archive), "-C", "/"]
    for ex in excludes:
        cmd.append(f"--exclude={(ex.lstrip('/') if ex.startswith('/') else ex)}")
    # prevent recursion: never include the destination of the archives
    p = str(local_dir)
    cmd.append(f"--exclude={(p.lstrip('/') if p.startswith('/') else p)}/*")

    # exclude only transient staging workdir (keep staging/db_dumps included!)
    staging_work = str(Path(cfg.get("staging_dir", "/var/lib/backupd/staging")) / "work")
    cmd.append(f"--exclude={(staging_work.lstrip('/') if staging_work.startswith('/') else staging_work)}/*")
    cmd += rels

    logger.info("Creating archive: %s", shell_quote(cmd))
    run(cmd, check=True)
    return str(archive)

def run_backup(now_override: Optional[datetime] = None, force: bool = False, only_cleanup: bool = False) -> RunResult:
    cfg = load_config()
    validate_config(cfg)
    logger = setup_logging()
    tz = ZoneInfo(cfg.get("timezone", "UTC"))
    now = now_override or datetime.now(tz)

    try:
        key = None
        if not force and not only_cleanup:
            due, key = should_run_times(now, cfg.get("schedule_times", []), int(cfg.get("tolerance_minutes", 2)), "backup")
            if not due:
                return RunResult(ok=True, message="Not due.")

        db_dump_dir = None
        extra_paths: list[str] = []

        if not only_cleanup and cfg.get("db", {}).get("enabled"):
            pol = cfg.get("db", {}).get("policy", "hybrid")
            if pol == "every_backup":
                dump_due, dump_key = True, "db:every_backup"
            else:
                dump_due, dump_key = should_dump_db(now, cfg)

            if dump_due:
                disc = dbmod.discover_databases(cfg)
                sel = dbmod.selected_databases(cfg, disc)
                db_path = dbmod.dump_databases(cfg, sel, logger)
                db_dump_dir = str(db_path)
                extra_paths.append(str(db_path))
                if dump_key and dump_key.startswith("dbdump:"):
                    mark_db_dump(dump_key)

        archive_path = None
        uploaded = False

        if not only_cleanup:
            archive_path = build_archive(cfg, _effective_include_paths(cfg), extra_paths, logger)
            if cfg.get("upload_enabled", True):
                rcl.upload_file(cfg, archive_path, logger)
                uploaded = True


        # cleanup db dumps after archiving (they're inside the tar now)
        if db_dump_dir:
            try:
                rmtree(db_dump_dir)
            except Exception as e:
                logger.warning("Could not remove db dump dir %s: %s", db_dump_dir, e)
                
        local_plan = retention.apply_prune(cfg, "local", logger)
        remote_plan = retention.apply_prune(cfg, "remote", logger) if cfg.get("upload_enabled", True) else {"delete": []}

        if key:
            mark_run(key)

        return RunResult(
            ok=True,
            message="OK",
            archive_path=archive_path,
            uploaded=uploaded,
            retention_local_deleted=len(local_plan.get("delete", [])),
            retention_remote_deleted=len(remote_plan.get("delete", [])),
            db_dump_dir=db_dump_dir,
        )
    except Exception as e:
        msg = f"BackupD failed: {e}"
        logger.error(msg)
        try:
            notify_failure(cfg, subject="BackupD failure", body=msg, logger=logger)
        except Exception:
            pass
        # Preserve partial state if it exists
        try:
            return RunResult(
                ok=False,
                message=msg,
                archive_path=locals().get("archive_path"),
                uploaded=locals().get("uploaded", False),
                retention_local_deleted=0,
                retention_remote_deleted=0,
                db_dump_dir=locals().get("db_dump_dir"),
            )
        except Exception:
            return RunResult(ok=False, message=msg)
