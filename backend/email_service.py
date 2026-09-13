"""SMTP notifications. Failures are logged, never raised to callers."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")


def send_email(to: str, subject: str, html_body: str) -> tuple[bool, str | None]:
    if not to:
        return False, "missing recipient"
    if not SMTP_HOST or not SMTP_FROM:
        print(f"[EMAIL SKIP] SMTP not configured. Would send to {to}: {subject}")
        return False, "smtp not configured"
    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to, msg.as_string())
        print(f"[EMAIL OK] {to}: {subject}")
        return True, None
    except Exception as exc:
        print(f"[EMAIL ERROR] {to}: {exc}")
        return False, str(exc)
