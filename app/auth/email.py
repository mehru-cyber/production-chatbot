import smtplib
from email.message import EmailMessage

from app.config import settings
from app.observability.logging_config import get_logger

log = get_logger(__name__)


def send_verification_email(to_email: str, token: str) -> None:
    """
    No-ops silently if SMTP isn't configured — registration still succeeds
    and the account is auto-verified in that case (see auth/routes.py).
    Uses only the standard library (smtplib), so no new dependency is
    required to enable this — just SMTP_* env vars.
    """
    if not settings.smtp_configured:
        return

    verify_url = f"{settings.app_base_url}/auth/verify-email?token={token}"

    msg = EmailMessage()
    msg["Subject"] = "Verify your account"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(
        f"Confirm your account by visiting:\n\n{verify_url}\n\n"
        "If you didn't request this, you can ignore this email."
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        log.info("verification_email_sent", to=to_email)
    except Exception as exc:
        # Never let a flaky SMTP provider break registration itself.
        log.warning("verification_email_failed", to=to_email, error=str(exc))