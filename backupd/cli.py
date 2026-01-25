from __future__ import annotations

import argparse
import json
import sys

from .utils import is_root
from .config import load_config, save_config, validate_config
from .logging_setup import setup_logging
from .engine import run_backup
from . import rclone as rcl
from . import db as dbmod
from . import retention
from .status import get_status
from . import manager


def cmd_inventory(_args):
    cfg = load_config()
    print(json.dumps(manager.inventory(cfg), indent=2, ensure_ascii=False))

def cmd_manage_apply(_args):
    _require_root()
    cfg = load_config()
    logger = setup_logging()
    plan = json.loads(sys.stdin.read() or "{}")
    out = manager.apply_plan(cfg, plan, logger)
    # if we changed pinned list, persist config
    if out.get("pinned_saved"):
        save_config(cfg)
    print(json.dumps(out, indent=2, ensure_ascii=False))

def _require_root():
    if not is_root():
        print("backupctl must be run as root", file=sys.stderr)
        sys.exit(2)

def cmd_get_config(_args):
    print(json.dumps(load_config(), indent=2, ensure_ascii=False))

def cmd_set_config(_args):
    cfg = json.loads(sys.stdin.read())
    validate_config(cfg)
    save_config(cfg)
    print("OK")

def cmd_status(_args):
    print(json.dumps(get_status(), indent=2, ensure_ascii=False))

def cmd_test_cloud(_args):
    print(rcl.test_cloud(load_config()))

def cmd_discover_dbs(_args):
    cfg = load_config()
    disc = dbmod.discover_databases(cfg)
    sel = dbmod.selected_databases(cfg, disc)
    out = {
        "mysql_dbs": disc.mysql_dbs,
        "postgres_dbs": disc.postgres_dbs,
        "selected": sel,
        "errors": {"mysql": disc.mysql_error, "postgres": disc.postgres_error},
        "raw_report": disc.raw,
        "system_db_defaults": cfg.get("system_db_defaults", {}),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

def cmd_test_dbs(_args):
    print(json.dumps(dbmod.test_db_access(load_config()), indent=2, ensure_ascii=False))

def cmd_backup_now(_args):
    setup_logging()
    res = run_backup(force=True)
    print(json.dumps(res.__dict__, indent=2, ensure_ascii=False))
    sys.exit(0 if res.ok else 1)

def cmd_run_if_due(_args):
    setup_logging()
    res = run_backup(force=False)
    print(json.dumps(res.__dict__, indent=2, ensure_ascii=False))
    sys.exit(0 if res.ok else 1)

def cmd_retention_plan(_args):
    cfg = load_config()
    out = {
        "local": retention.plan_prune(cfg, "local"),
        "remote": retention.plan_prune(cfg, "remote") if cfg.get("upload_enabled", True) else {"scope":"remote","keep":[],"delete":[]},
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

def cmd_retention_apply(_args):
    cfg = load_config()
    logger = setup_logging()
    out = {
        "local": retention.apply_prune(cfg, "local", logger),
        "remote": retention.apply_prune(cfg, "remote", logger) if cfg.get("upload_enabled", True) else {"delete":[]},
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backupctl", description="BackupD control utility")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("get-config").set_defaults(fn=cmd_get_config)
    sub.add_parser("set-config").set_defaults(fn=cmd_set_config)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("test-cloud").set_defaults(fn=cmd_test_cloud)
    sub.add_parser("discover-dbs").set_defaults(fn=cmd_discover_dbs)
    sub.add_parser("test-dbs").set_defaults(fn=cmd_test_dbs)
    sub.add_parser("backup-now").set_defaults(fn=cmd_backup_now)
    sub.add_parser("run-if-due").set_defaults(fn=cmd_run_if_due)
    sub.add_parser("retention-plan").set_defaults(fn=cmd_retention_plan)
    sub.add_parser("retention-apply").set_defaults(fn=cmd_retention_apply)
    sp = sub.add_parser("inventory", help="List local+remote backups with metadata")
    sp.set_defaults(fn=cmd_inventory)

    sp = sub.add_parser("manage-apply", help="Apply backup manager decisions (copy/migrate/delete/pin)")
    sp.set_defaults(fn=cmd_manage_apply)
    return p

def main(argv=None):
    _require_root()
    args = build_parser().parse_args(argv)
    args.fn(args)
