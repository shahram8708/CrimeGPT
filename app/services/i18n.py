import json
from pathlib import Path

from flask import has_request_context, request, session
from flask_login import current_user

ALLOWED_LANGS = ("en", "hi", "gu")
LOCALE_DIR = Path(__file__).resolve().parent.parent / "static" / "i18n"


def _load_locale(code):
    key = f"locale:{code}"
    try:
        from app.extensions import cache

        hit = cache.get(key)
        if hit is not None:
            return hit
    except Exception:
        hit = None
    path = LOCALE_DIR / f"{code}.json"
    data = {}
    if path.is_file():
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    try:
        from app.extensions import cache

        cache.set(key, data, timeout=600)
    except Exception:
        pass
    return data


def get_current_lang():
    if has_request_context():
        if getattr(current_user, "is_authenticated", False) and current_user.preferences:
            lang = (current_user.preferences.ui_language or "").lower()
            if lang in ALLOWED_LANGS:
                return lang
        sess = session.get("lang")
        if sess in ALLOWED_LANGS:
            return sess
        qs = (request.args.get("lang") or "").lower()
        if qs in ALLOWED_LANGS:
            return qs
    return "en"


def translate(key, **kwargs):
    lang = kwargs.pop("lang", None) or get_current_lang()
    data = _load_locale(lang)
    text = data.get(key)
    if text is None and lang != "en":
        text = _load_locale("en").get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def set_language(code, user=None):
    if code not in ALLOWED_LANGS:
        return False
    session["lang"] = code
    target = user
    if target is None and getattr(current_user, "is_authenticated", False):
        target = current_user
    if target is not None and getattr(target, "preferences", None):
        target.preferences.ui_language = code
        from app.extensions import db

        db.session.commit()
    return True
