"""Email to the admins (a refund request came in). Sent over SMTP, which works with a Gmail app
password (smtp.gmail.com) or Resend (smtp.resend.com, user "resend", the API key as the password).

Not set up yet? The message is logged instead, and nothing else is affected.
"""
import asyncio
import os
import smtplib
from email.message import EmailMessage

from . import auth
from .book.log import record


def recipients() -> list[str]:
    listed = os.getenv("NOTIFY_EMAILS", "")
    return [e.strip() for e in listed.split(",") if e.strip()] or sorted(auth.admin_emails())


def _send(msg: EmailMessage) -> None:
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


async def send_admins(subject: str, body: str) -> bool:
    """Never raises: a failed email must not fail the request that caused it."""
    to = recipients()
    if not (os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD")) or not to:
        await record("WARNING", "email", "not set up", subject=subject)
        return False
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, ", ".join(to)
    msg["From"] = os.getenv("SMTP_FROM") or os.environ["SMTP_USER"]
    msg.set_content(body)
    try:
        await asyncio.to_thread(_send, msg)
    except Exception as e:
        await record("ERROR", "email", "failed", subject=subject, error=f"{type(e).__name__}: {e}")
        return False
    await record("INFO", "email", "sent", subject=subject, to=len(to))
    return True
