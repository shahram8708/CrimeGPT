import json

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.tool_forms import ApplyIntelForm, LinkCaseForm
from app.models import Case
from app.models.ai import LegalSuggestion, SavedResult
from app.services.authz import can_apply_intel as authz_can_apply
from app.services.authz import case_is_visible
from app.services.case_service import completeness, list_for
from app.services.i18n import translate
from app.services.intel_service import (
    apply_selected,
    can_apply_intel,
    can_view_suggestion,
    enqueue_legal_intel,
    link_suggestion_to_case,
    parsed_result,
)

results_bp = Blueprint("results", __name__)


def _load(rid):
    row = LegalSuggestion.query.filter_by(uuid=rid).first()
    if row is None or not can_view_suggestion(current_user, row):
        abort(404)
    return row


def _case_choices():
    return [(c.id, f"{c.display_cr} · {c.category_label}") for c in list_for(current_user, {})]


@results_bp.route("/results/legal-intel/<rid>")
@login_required
def legal_intel(rid):
    sugg = _load(rid)
    data = parsed_result(sugg) or {}
    apply_form = ApplyIntelForm()
    link_form = LinkCaseForm()
    link_form.case_id.choices = _case_choices()
    buckets = completeness(sugg.case)["buckets"] if sugg.case else {}
    may_apply = can_apply_intel(current_user, sugg.case) if sugg.case else False
    return render_template(
        "results/legal_intel.html",
        sugg=sugg,
        data=data,
        raw_json=sugg.result_json or "",
        apply_form=apply_form,
        link_form=link_form,
        may_apply=may_apply,
        writer_blocked=current_user.role == "writer",
        buckets=buckets,
        applyable_count=sum(
            1
            for key in ("bns", "bnss", "bsa")
            for row in data.get(key) or []
            if row.get("applyable")
        ),
    )


@results_bp.route("/results/legal-intel/<rid>/apply", methods=["POST"])
@login_required
def apply(rid):
    sugg = _load(rid)
    if current_user.role == "writer":
        abort(403)
    keys = request.form.getlist("selected")
    try:
        applied, already = apply_selected(current_user, sugg, keys)
    except PermissionError:
        abort(403)
    except RuntimeError as exc:
        if str(exc) == "no_case":
            flash(translate("intel.link_first"), "warning")
            return redirect(url_for("results.legal_intel", rid=sugg.uuid))
        if str(exc) == "refused":
            flash(translate("intel.ethics"), "danger")
            return redirect(url_for("results.legal_intel", rid=sugg.uuid))
        abort(403)
    if applied:
        flash(translate("flash.intel_applied", n=applied), "success")
    if already:
        flash(translate("flash.section_dup"), "warning")
    if not applied and not already:
        flash(translate("intel.none_selected"), "info")
    if sugg.case:
        return redirect(url_for("cases.sections", uuid=sugg.case.uuid))
    return redirect(url_for("results.legal_intel", rid=sugg.uuid))


@results_bp.route("/results/legal-intel/<rid>/link", methods=["POST"])
@login_required
def link(rid):
    sugg = _load(rid)
    form = LinkCaseForm()
    form.case_id.choices = _case_choices()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("results.legal_intel", rid=sugg.uuid))
    case = db.session.get(Case, form.case_id.data)
    if case is None or not case_is_visible(current_user, case):
        abort(404)
    try:
        link_suggestion_to_case(current_user, sugg, case)
    except PermissionError:
        abort(404)
    flash(translate("flash.intel_linked"), "success")
    return redirect(url_for("results.legal_intel", rid=sugg.uuid))


@results_bp.route("/results/legal-intel/<rid>/rerun", methods=["POST"])
@login_required
def rerun(rid):
    sugg = _load(rid)
    if not can_view_suggestion(current_user, sugg):
        abort(404)
    from app.services.authz import can_run_legal_intel, gemini_ready

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not gemini_ready():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("results.legal_intel", rid=sugg.uuid))
    try:
        job, _ = enqueue_legal_intel(
            current_user,
            sugg.narrative_snapshot,
            language=sugg.language,
            focus=sugg.focus,
            use_search=bool(sugg.use_search),
            case=sugg.case,
        )
    except RuntimeError as exc:
        flash(translate("intel.quota") if str(exc) == "quota" else translate("intel.missing_key"), "warning")
        return redirect(url_for("results.legal_intel", rid=sugg.uuid))
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@results_bp.route("/history/saved/<sid>/star", methods=["POST"])
@login_required
def star_saved(sid):
    row = SavedResult.query.filter_by(uuid=sid).first()
    if row is None:
        abort(404)
    if current_user.role not in ("super_admin", "admin") and row.user_id != current_user.id:
        abort(404)
    row.is_starred = not bool(row.is_starred)
    db.session.commit()
    return redirect(request.referrer or url_for("dashboard.history"))


def _can_see_compare(row):
    if current_user.role in ("super_admin", "admin"):
        return True
    if row.user_id == current_user.id:
        return True
    if row.case and case_is_visible(current_user, row.case):
        return True
    return False


@results_bp.route("/results/compare/<rid>")
@login_required
def compare(rid):
    from app.models.document import CompareResult, GeneratedDocument, LibraryDocument
    from app.services.document_service import parse_ctx

    row = CompareResult.query.filter_by(uuid=rid).first()
    if row is None or not _can_see_compare(row):
        abort(404)
    data = {}
    if row.result_json:
        try:
            data = json.loads(row.result_json)
        except (TypeError, ValueError):
            data = {}
    left = (
        GeneratedDocument.query.filter_by(uuid=row.left_ref).first()
        if row.left_kind == "generated"
        else LibraryDocument.query.filter_by(uuid=row.left_ref).first()
    )
    right = (
        GeneratedDocument.query.filter_by(uuid=row.right_ref).first()
        if row.right_kind == "generated"
        else LibraryDocument.query.filter_by(uuid=row.right_ref).first()
    )
    return render_template(
        "results/compare.html",
        row=row,
        data=data,
        left=left,
        right=right,
        left_kind=row.left_kind,
        right_kind=row.right_kind,
        left_ctx=parse_ctx(left) if row.left_kind == "generated" and left else {},
        right_ctx=parse_ctx(right) if row.right_kind == "generated" and right else {},
    )


@results_bp.route("/results/identify/<rid>")
@login_required
def identify(rid):
    from app.models.document import ClauseAnalysis

    row = ClauseAnalysis.query.filter_by(uuid=rid).first()
    if row is None:
        abort(404)
    if current_user.role not in ("super_admin", "admin") and row.user_id != current_user.id:
        if row.case_id:
            from app.models import Case

            case = db.session.get(Case, row.case_id)
            if case is None or not case_is_visible(current_user, case):
                abort(404)
        else:
            abort(404)
    data = {}
    if row.result_json:
        try:
            data = json.loads(row.result_json)
        except (TypeError, ValueError):
            data = {}
    return render_template("results/identify.html", row=row, data=data)


def _can_see_analysis(row):
    if current_user.role in ("super_admin", "admin"):
        return True
    if row.user_id == current_user.id:
        return True
    if row.case_id:
        case = db.session.get(Case, row.case_id)
        return case is not None and case_is_visible(current_user, case)
    return False


@results_bp.route("/results/analysis/<rid>")
@login_required
def analysis(rid):
    from app.forms.tool_forms import ApplyFieldForm, EmptyPostForm
    from app.models.ai import DocumentAnalysis
    from app.services.analysis_service import parsed_analysis
    from app.services.authz import can_edit_case_facts

    row = DocumentAnalysis.query.filter_by(uuid=rid).first()
    if row is None or not _can_see_analysis(row):
        abort(404)
    data = parsed_analysis(row)
    parties = []
    if row.case:
        parties = [
            (p.id, f"{p.role}: {p.full_name}")
            for p in row.case.live_parties()
            if p.role in ("injured", "complainant", "accused")
        ]
    apply_form = ApplyFieldForm()
    apply_form.party_id.choices = [(0, "-")] + parties
    return render_template(
        "results/analysis.html",
        row=row,
        data=data,
        apply_form=apply_form,
        rerun_form=EmptyPostForm(),
        may_apply=bool(row.case and (can_edit_case_facts(current_user, row.case) or current_user.role == "super_admin")),
        parties=parties,
    )


@results_bp.route("/results/analysis/<rid>/apply", methods=["POST"])
@login_required
def analysis_apply(rid):
    from app.forms.tool_forms import ApplyFieldForm
    from app.models.ai import DocumentAnalysis
    from app.services.analysis_service import apply_extracted_field

    row = DocumentAnalysis.query.filter_by(uuid=rid).first()
    if row is None or not _can_see_analysis(row):
        abort(404)
    form = ApplyFieldForm()
    parties = []
    if row.case:
        parties = [(p.id, p.full_name) for p in row.case.live_parties()]
    form.party_id.choices = [(0, "-")] + parties
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("results.analysis", rid=row.uuid))
    try:
        status = apply_extracted_field(
            current_user,
            row,
            form.field_key.data,
            form.field_value.data,
            party_id=form.party_id.data or None,
            confirm=bool(form.confirm.data),
        )
    except PermissionError:
        abort(403)
    except RuntimeError as exc:
        code = str(exc)
        if code == "statute":
            flash(translate("flash.statute_not_applied"), "warning")
        elif code == "need_party":
            flash(translate("an.need_party"), "warning")
        elif code == "need_confirm":
            flash(translate("an.need_confirm"), "warning")
        elif code == "cr_blocked":
            flash(translate("an.cr_blocked"), "danger")
        elif code == "unknown_field":
            flash(translate("an.unknown"), "warning")
        else:
            flash(translate("form.fix"), "danger")
        return redirect(url_for("results.analysis", rid=row.uuid))
    except ValueError:
        flash(translate("form.fix"), "danger")
        return redirect(url_for("results.analysis", rid=row.uuid))
    if status == "applied":
        flash(translate("flash.field_applied"), "success")
    elif status == "suggested":
        flash(translate("flash.section_needs_io"), "info")
    elif status == "already":
        flash(translate("flash.section_dup"), "warning")
    return redirect(url_for("results.analysis", rid=row.uuid))


@results_bp.route("/results/analysis/<rid>/rerun", methods=["POST"])
@login_required
def analysis_rerun(rid):
    from app.forms.tool_forms import EmptyPostForm
    from app.models.ai import DocumentAnalysis
    from app.services.analysis_service import enqueue_analyze
    from app.services.authz import gemini_ready

    if not EmptyPostForm().validate_on_submit():
        abort(400)
    row = DocumentAnalysis.query.filter_by(uuid=rid).first()
    if row is None or not _can_see_analysis(row) or row.document is None:
        abort(404)
    if not gemini_ready():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("results.analysis", rid=row.uuid))
    try:
        job, _ = enqueue_analyze(current_user, row.document, case=row.case, language=row.language or "en")
    except RuntimeError as exc:
        flash(translate("intel.quota") if str(exc) == "quota" else translate("intel.missing_key"), "warning")
        return redirect(url_for("results.analysis", rid=row.uuid))
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@results_bp.route("/results/translate/<rid>", endpoint="translate")
@login_required
def translate_result(rid):
    from app.models.ai import TranslateResult

    row = TranslateResult.query.filter_by(uuid=rid).first()
    if row is None:
        abort(404)
    if current_user.role not in ("super_admin", "admin") and row.user_id != current_user.id:
        if row.case_id:
            case = db.session.get(Case, row.case_id)
            if case is None or not case_is_visible(current_user, case):
                abort(404)
        else:
            abort(404)
    return render_template("results/translate.html", row=row)
