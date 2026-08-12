import logging

from app.extensions import celery

logger = logging.getLogger(__name__)


def _get_app():
    try:
        from flask import current_app
        if current_app:
            return None
    except RuntimeError:
        pass
    from app import create_app
    return create_app()


def run_send_email(to, subject, body, html=None, purpose=None, user_id=None):
    from app.services.mail_service import send_email_message
    app = _get_app()
    if app is not None:
        with app.app_context():
            return send_email_message(
                to=to, subject=subject, body=body,
                html=html, purpose=purpose, user_id=user_id,
            )
    return send_email_message(
        to=to, subject=subject, body=body,
        html=html, purpose=purpose, user_id=user_id,
    )


@celery.task(name="crimegpt.send_email", bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, to, subject, body, html=None, purpose=None, user_id=None):
    try:
        result = run_send_email(to, subject, body, html, purpose, user_id)
        if not result:
            logger.warning("send_email returned False for to=%s purpose=%s", to, purpose)
        return result
    except Exception as exc:
        logger.exception("send_email_task failed for to=%s purpose=%s", to, purpose)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return False
