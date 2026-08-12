import smtplib
import threading
from email.message import EmailMessage

from flask import current_app

from app.extensions import db
from app.models import MailLog
from app.services.email_layout import ensure_html
from app.utils.formatting_utils import sanitize_error


def _store_body():
    return current_app.config.get("ENV_NAME") != "production"


def send_email_message(to, subject, body, html=None, purpose=None, user_id=None):
    cfg = current_app.config
    sender = cfg.get("MAIL_DEFAULT_SENDER") or "noreply@crimegpt.local"
    recipients = [to] if isinstance(to, str) else list(to or [])
    to_address = ", ".join(recipients)[:180]
    sent_ok = False
    error_class = None
    try:
        html = ensure_html(subject, body, html=html, purpose=purpose)
    except Exception as exc:
        current_app.logger.warning("email html render failed: %s", sanitize_error(exc))
    server = (cfg.get("MAIL_SERVER") or "").strip()
    if server and recipients:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_address
        msg.set_content(body or "")
        if html:
            msg.add_alternative(html, subtype="html")
        try:
            port = int(cfg.get("MAIL_PORT") or 587)
            with smtplib.SMTP(server, port, timeout=12) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls()
                except smtplib.SMTPException:
                    pass
                username = cfg.get("MAIL_USERNAME") or ""
                password = cfg.get("MAIL_PASSWORD") or ""
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
            sent_ok = True
        except (OSError, smtplib.SMTPException) as exc:
            current_app.logger.warning("mail send failed: %s", sanitize_error(exc))
            error_class = type(exc).__name__
    log = MailLog(
        to_address=to_address or "(none)",
        subject=(subject or "")[:240],
        purpose=purpose,
        user_id=user_id,
        sent_ok=sent_ok,
        error_class=error_class,
        body=(body if _store_body() else None),
    )
    db.session.add(log)
    db.session.commit()
    return sent_ok


def send_mail(subject, body, to_addrs=None, html=None, purpose="transactional"):
    inbox = current_app.config.get("MAIL_DEFAULT_SENDER")
    target = to_addrs[0] if to_addrs else inbox
    return send_email_message(target, subject, body, html=html, purpose=purpose)


def _broker_needs_fallback(broker):
    broker = (broker or "").strip().lower()
    return (not broker) or broker.startswith("memory://") or broker.startswith("cache+")


def enqueue_email(to, subject, body, html=None, purpose=None, user_id=None):
    payload = {
        "to": to,
        "subject": subject,
        "body": body,
        "html": html,
        "purpose": purpose,
        "user_id": user_id,
    }
    if current_app.config.get("TESTING"):
        return send_email_message(**payload)

    broker = current_app.config.get("CELERY_BROKER_URL", "memory://")
    launched = False
    if not _broker_needs_fallback(broker):
        try:
            from app.tasks.mail_tasks import send_email_task

            send_email_task.apply_async(kwargs=payload)
            launched = True
        except Exception as exc:
            current_app.logger.warning("email apply_async failed: %s", sanitize_error(exc))
            launched = False
    if not launched:
        app_obj = current_app._get_current_object()

        def _run():
            with app_obj.app_context():
                send_email_message(**payload)

        thread = threading.Thread(target=_run, daemon=True, name="mail-send")
        thread.start()
    return True
