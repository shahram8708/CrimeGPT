from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user

from app.extensions import csrf, db, limiter
from app.forms import ContactForm
from app.models import ApplicationSetting, ContactMessage
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.i18n import ALLOWED_LANGS, set_language, translate
from app.services.account_mail import send_contact_email

main_bp = Blueprint("main", __name__)


def _setting(key, default=""):
    try:
        return ApplicationSetting.get(key, default) or default
    except Exception:
        return default


@main_bp.app_context_processor
def inject_public():
    lang = None
    try:
        from app.services.i18n import get_current_lang

        lang = get_current_lang()
    except Exception:
        lang = "en"
    short = _setting(f"disclaimer_short_{lang}", _setting("disclaimer_short_en", ""))
    return {
        "site_name": _setting("site_name", "CrimeGPT"),
        "footer_disclaimer": short,
        "disclaimer_en": _setting("disclaimer_en", ""),
        "disclaimer_hi": _setting("disclaimer_hi", ""),
        "disclaimer_gu": _setting("disclaimer_gu", ""),
    }


@main_bp.route("/")
def landing():
    return render_template("public/landing.html")


@main_bp.route("/about")
def about():
    return render_template("public/about.html")


@main_bp.route("/how-it-works")
def how_it_works():
    return render_template("public/how_it_works.html")


@main_bp.route("/features")
def features():
    return render_template("public/features.html")


@main_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html", retention_days=_setting("retention_days", "365"))


@main_bp.route("/terms")
def terms():
    return render_template("public/terms.html")


@main_bp.route("/disclaimer")
def disclaimer():
    return render_template("public/disclaimer.html")


@main_bp.route("/offline")
def offline():
    return render_template("public/offline.html")


@main_bp.route("/contact", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def contact():
    form = ContactForm()
    sent = request.args.get("sent") == "1"
    if form.validate_on_submit():
        honeypot = (form.website.data or "").strip()
        if honeypot:
            row = ContactMessage(
                name=(form.name.data or "")[:120],
                email=(form.email.data or "")[:180],
                organisation=(form.organisation.data or "")[:160],
                station_note=(form.station_note.data or "")[:160],
                message=(form.message.data or "")[:2000],
                ip=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=(request.user_agent.string or "")[:300],
                honeypot_hit=True,
            )
            db.session.add(row)
            db.session.commit()
            return redirect(url_for("main.contact", sent=1))

        row = ContactMessage(
            name=form.name.data.strip(),
            email=form.email.data.strip().lower(),
            organisation=(form.organisation.data or "").strip() or None,
            station_note=(form.station_note.data or "").strip() or None,
            message=form.message.data.strip(),
            ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=(request.user_agent.string or "")[:300],
            honeypot_hit=False,
        )
        db.session.add(row)
        db.session.commit()

        mailed = send_contact_email(row)
        if mailed:
            row.emailed_at = utcnow()
            db.session.commit()
        write_audit(
            "contact.submitted",
            object_type="contact_message",
            object_id=row.uuid,
            meta={"emailed": bool(mailed)},
        )
        flash(translate("flash.contact_sent"), "success")
        return redirect(url_for("main.contact", sent=1))
    return render_template("public/contact.html", form=form, sent=sent)


@main_bp.route("/lang/<code>", methods=["GET", "POST"])
def set_lang(code):
    set_language(code.lower())
    dest = request.referrer or url_for("main.landing")
    if not dest.startswith(request.host_url) and not dest.startswith("/"):
        dest = url_for("main.landing")
    return redirect(dest)


@main_bp.route("/sw.js")
def service_worker():
    response = send_from_directory(
        current_app.static_folder, "sw.js", mimetype="application/javascript"
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@main_bp.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        current_app.static_folder, "manifest.json", mimetype="application/manifest+json"
    )


@main_bp.route("/healthz")
@csrf.exempt
def healthz():
    payload = {"status": "ok", "db": "ok", "time": utcnow().isoformat()}
    code = 200
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        payload["status"] = "error"
        payload["db"] = "error"
        code = 503
    return jsonify(payload), code
