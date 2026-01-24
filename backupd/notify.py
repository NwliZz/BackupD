from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Dict

from .utils import run

def notify_failure(cfg: Dict[str, Any], subject: str, body: str, logger) -> None:
    ncfg = cfg.get("notifications", {})
    if not ncfg.get("enabled"):
        return

    method = ncfg.get("method", "smtp")
    sender = ncfg.get("from", "backupd@localhost")
    recipients = ncfg.get("to", [])
    if not recipients:
        logger.warning("Notifications enabled but notifications.to is empty")
        return

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if method == "sendmail":
            run(["/usr/sbin/sendmail", "-t", "-i"], check=True, input_text=msg.as_string())
            return

        smtp = ncfg.get("smtp", {})
        host = smtp.get("host", "")
        port = int(smtp.get("port", 587))
        user = smtp.get("username", "")
        pwd = smtp.get("password", "")
        starttls = bool(smtp.get("starttls", True))

        if not host:
            logger.warning("SMTP enabled but smtp.host is empty")
            return

        with smtplib.SMTP(host, port, timeout=20) as s:
            if starttls:
                s.starttls()
            if user:
                s.login(user, pwd)
            s.send_message(msg)
    except Exception as e:
        logger.error("Failed to send notification: %s", e)
