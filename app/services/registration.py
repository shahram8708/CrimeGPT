from flask import current_app

from app.models import ApplicationSetting
from app.utils.security_utils import constant_time_equals, hash_password_token


def setting_truthy(key, fallback=False):
    raw = ApplicationSetting.get(key)
    if raw is None:
        return fallback
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def registration_is_open():
    return setting_truthy("registration_open", bool(current_app.config.get("REGISTRATION_OPEN")))


def enrollment_hash():
    return ApplicationSetting.get("enrollment_code_hash") or ""


def enrollment_mode_active():
    return bool(enrollment_hash())


def registration_visible():
    return registration_is_open() or enrollment_mode_active()


def enrollment_required():
    return (not registration_is_open()) or setting_truthy("enrollment_required", False)


def enrollment_matches(code):
    expected = enrollment_hash()
    if not expected:
        return False
    given = hash_password_token((code or "").strip())
    return constant_time_equals(expected, given)


def mail_gateway_configured():
    return bool((current_app.config.get("MAIL_SERVER") or "").strip())
