from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from concurrent.futures import ThreadPoolExecutor

SMTP_HOST = os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("GMAIL_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("GMAIL_SMTP_USERNAME", "").strip()
SMTP_APP_PASSWORD = os.getenv("GMAIL_SMTP_APP_PASSWORD", "").replace(" ", "").strip()
SMTP_FROM_EMAIL = os.getenv("GMAIL_FROM_EMAIL", SMTP_USERNAME).strip()
_executor = ThreadPoolExecutor(max_workers=2)


def smtp_configured() -> bool:
    return bool(SMTP_USERNAME and SMTP_APP_PASSWORD and SMTP_FROM_EMAIL)


def _send(to_email: str, subject: str, body: str) -> None:
    if not smtp_configured():
        raise RuntimeError("Gmail SMTP is not configured. Set GMAIL_SMTP_USERNAME and GMAIL_SMTP_APP_PASSWORD in backend/.env")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(SMTP_USERNAME, SMTP_APP_PASSWORD)
        smtp.send_message(msg)


def send_otp_email(to_email: str, otp: str, purpose: str) -> None:
    action = "verify your LandWise AI account" if purpose == "signup" else "reset your LandWise AI password"
    subject = "LandWise AI verification code" if purpose == "signup" else "LandWise AI password reset code"
    body = f"""Hello,\n\nYour LandWise AI OTP to {action} is:\n\n{otp}\n\nThis code expires in 10 minutes and can be used only once.\n\nIf you did not request this code, you can safely ignore this email.\n\nLandWise AI\n"""
    _send(to_email, subject, body)


def send_otp_email_async(to_email: str, otp: str, purpose: str) -> None:
    # Execute SMTP off the FastAPI event loop.
    _executor.submit(send_otp_email, to_email, otp, purpose).result()
