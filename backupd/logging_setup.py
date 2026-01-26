"""Logging configuration for the backup daemon and CLI."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

DEFAULT_LOG_DIR = "/var/log/backupd"
DEFAULT_LOG_FILE = "backupd.log"

def setup_logging(log_dir: str = DEFAULT_LOG_DIR, level: int = logging.INFO) -> logging.Logger:
    """Create a rotating file logger and console logger if not already set."""
    logger = logging.getLogger("backupd")
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(log_dir, 0o755)
    except PermissionError:
        pass

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    fh = RotatingFileHandler(os.path.join(log_dir, DEFAULT_LOG_FILE), maxBytes=5*1024*1024, backupCount=5)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger
