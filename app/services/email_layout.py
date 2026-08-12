from datetime import datetime
import os

from flask import current_app, render_template, url_for
from markupsafe import Markup, escape

_PATHS = {
    "main.landing": "/",
    "main.privacy": "/privacy",
    "main.terms": "/terms",
    "main.contact": "/contact",
    "main.disclaimer": "/disclaimer",
}

_EYEBROW = {
    "verify": "Account",
    "reset": "Security",
    "invite": "Invitation",
    "contact": "Support desk",
    "transactional": "Notice",
}


def public_url(endpoint, **values):
    try:
        return url_for(endpoint, _external=True, **values)
    except Exception:
        pass
    base = (
        (current_app.config.get("PUBLIC_BASE_URL") if current_app else None)
        or os.environ.get("PUBLIC_BASE_URL")
        or ""
    ).rstrip("/")
    if not base and current_app:
        server = (current_app.config.get("SERVER_NAME") or "").strip()
        if server:
            scheme = current_app.config.get("PREFERRED_URL_SCHEME") or "http"
            base = f"{scheme}://{server}".rstrip("/")
    path = _PATHS.get(endpoint, "/")
    if values:
        return f"{base}{path}" if base else path
    return f"{base}{path}" if base else path


def site_name():
    try:
        from app.models import ApplicationSetting

        return ApplicationSetting.get("site_name", "CrimeGPT") or "CrimeGPT"
    except Exception:
        return "CrimeGPT"


def short_disclaimer():
    fallback = "Draft assistance only. Not legal advice. Officers remain responsible for every filed document."
    try:
        from app.models import ApplicationSetting

        return ApplicationSetting.get("disclaimer_short_en", fallback) or fallback
    except Exception:
        return fallback


def paragraphs_html(text):
    if not text:
        return ""
    blocks = [chunk.strip() for chunk in str(text).replace("\r\n", "\n").split("\n\n")]
    parts = []
    style = (
        "margin:0 0 16px 0;font-family:Arial,Helvetica,sans-serif;"
        "font-size:16px;line-height:1.65;color:#1c2430;"
    )
    for block in blocks:
        if not block:
            continue
        lines = "<br>\n".join(str(escape(line)) for line in block.split("\n"))
        parts.append(f'<p style="{style}">{lines}</p>')
    return Markup("".join(parts))


def email_context(**extra):
    ctx = {
        "site_name": site_name(),
        "home_url": public_url("main.landing") or "#",
        "privacy_url": public_url("main.privacy") or "#",
        "terms_url": public_url("main.terms") or "#",
        "contact_url": public_url("main.contact") or "#",
        "disclaimer_url": public_url("main.disclaimer") or "#",
        "year": datetime.utcnow().year,
        "disclaimer": short_disclaimer(),
        "preheader": extra.get("subject") or "",
        "eyebrow": "CrimeGPT",
        "heading": extra.get("subject") or "CrimeGPT",
        "cta_url": None,
        "cta_label": None,
        "fallback_note": None,
        "note_html": None,
        "body_html": "",
    }
    ctx.update(extra)
    return ctx


def render_email(template_name, **extra):
    return render_template(template_name, **email_context(**extra))


def ensure_html(subject, body, html=None, purpose=None):
    if html:
        start = html.lstrip()[:15].lower()
        if start.startswith("<!doctype") or start.startswith("<html"):
            return html
        inner = Markup(html)
    else:
        inner = paragraphs_html(body)
    return render_email(
        "email/generic.html",
        subject=subject or site_name(),
        heading=subject or site_name(),
        preheader=subject or "",
        eyebrow=_EYEBROW.get(purpose or "", "Notice"),
        body_html=inner,
    )
