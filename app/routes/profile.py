from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required, login_user

from app.extensions import db
from app.forms.profile_forms import PreferencesForm, ProfileForm, SecurityForm
from app.models import AuditLog
from app.services.audit_service import write_audit
from app.services.i18n import translate

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data.strip()
        current_user.rank_label = (form.rank_label.data or "").strip() or None
        current_user.belt_no = (form.belt_no.data or "").strip() or None
        db.session.commit()
        write_audit(
            "profile.updated",
            object_type="user",
            object_id=current_user.id,
            actor=current_user,
            station_id=current_user.station_id,
        )
        flash(translate("flash.profile_saved"), "success")
        return redirect(url_for("profile.profile"))
    return render_template("profile/profile.html", form=form)


@profile_bp.route("/profile/preferences", methods=["GET", "POST"])
@login_required
def preferences():
    prefs = current_user.preferences
    form = PreferencesForm(obj=prefs) if prefs else PreferencesForm()
    if form.validate_on_submit() and prefs:
        prefs.ui_language = form.ui_language.data
        prefs.document_language = form.document_language.data
        prefs.offline_drafts = bool(form.offline_drafts.data)
        prefs.email_notifications = bool(form.email_notifications.data)
        prefs.hide_intel_modal = bool(form.hide_intel_modal.data)
        prefs.diary_oldest_first = bool(form.diary_oldest_first.data)
        db.session.commit()
        write_audit(
            "profile.preferences",
            object_type="user",
            object_id=current_user.id,
            actor=current_user,
            station_id=current_user.station_id,
        )
        flash(translate("flash.preferences_saved"), "success")
        return redirect(url_for("profile.preferences"))
    return render_template("profile/preferences.html", form=form)


@profile_bp.route("/profile/security", methods=["GET", "POST"])
@login_required
def security():
    form = SecurityForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors = list(form.current_password.errors) + [
                "Current password is incorrect."
            ]
        else:
            current_user.set_password(form.new_password.data)
            current_user.session_version = (current_user.session_version or 1) + 1
            db.session.commit()
            login_user(current_user)
            write_audit(
                "auth.password_change",
                object_type="user",
                object_id=current_user.id,
                actor=current_user,
                station_id=current_user.station_id,
                meta={"via": "security"},
            )
            flash(translate("flash.password_changed"), "success")
            return redirect(url_for("profile.security"))
    return render_template("profile/security.html", form=form)


@profile_bp.route("/profile/activity")
@login_required
def activity():
    rows = (
        AuditLog.query.filter_by(actor_id=current_user.id)
        .order_by(AuditLog.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template("profile/activity.html", rows=rows)
