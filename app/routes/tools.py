from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.tool_forms import LegalIntelForm
from app.models import Case
from app.services.authz import can_run_legal_intel, case_is_visible, gemini_ready
from app.services.case_service import list_for
from app.services.i18n import translate
from app.services.intel_service import enqueue_legal_intel, quota_reached

tools_bp = Blueprint("tools", __name__)


def _case_choices():
    rows = [(0, "-")]
    for case in list_for(current_user, {}):
        rows.append((case.id, f"{case.display_cr} · {case.category_label}"))
    return rows


def _maybe_hide_modal(form):
    if form.hide_again.data in ("y", "1", "true", "on") and current_user.preferences:
        current_user.preferences.hide_intel_modal = True
        db.session.commit()


@tools_bp.route("/tools/legal-intel", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def legal_intel():
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    form = LegalIntelForm()
    form.case_id.choices = _case_choices()
    form.case_id.coerce = lambda v: int(v or 0)
    if request.method == "GET":
        form.use_search.data = True
        if current_user.preferences:
            form.language.data = (
                current_user.preferences.document_language
                or current_user.preferences.ui_language
                or "en"
            )
        pre = request.args.get("case")
        if pre:
            case = Case.query.filter_by(uuid=pre).first()
            if case and case_is_visible(current_user, case):
                form.case_id.data = case.id
                form.narrative.data = case.narrative or ""
                form.language.data = case.narrative_language or form.language.data
        excerpt = session.pop("intel_prefill", None)
        if excerpt:
            form.narrative.data = excerpt[:20000]
    if form.validate_on_submit():
        if not current_user.disclaimer_accepted_at:
            flash(translate("flash.need_disclaimer"), "danger")
            return render_template(
                "tools/legal_intel.html",
                form=form,
                gemini_ok=gemini_ready(),
                quota=quota_reached(current_user),
            )
        if not gemini_ready():
            form.narrative.errors = list(form.narrative.errors) + [
                translate("intel.missing_key")
            ]
        else:
            case = None
            cid = form.case_id.data or 0
            if cid:
                case = db.session.get(Case, cid)
                if case is None or not case_is_visible(current_user, case):
                    abort(404)
            try:
                _maybe_hide_modal(form)
                job, _ = enqueue_legal_intel(
                    current_user,
                    form.narrative.data,
                    language=form.language.data,
                    focus=form.focus.data,
                    use_search=bool(form.use_search.data),
                    case=case,
                )
                return redirect(url_for("jobs.progress", job_uuid=job.uuid))
            except RuntimeError as exc:
                code = str(exc)
                if code == "quota":
                    flash(translate("intel.quota"), "warning")
                elif code == "not_configured":
                    form.narrative.errors = list(form.narrative.errors) + [
                        translate("intel.missing_key")
                    ]
                elif code == "disclaimer":
                    flash(translate("flash.need_disclaimer"), "danger")
                else:
                    flash(translate("form.fix"), "danger")
            except ValueError:
                form.narrative.errors = list(form.narrative.errors) + [
                    translate("intel.narrative_short")
                ]
    return render_template(
        "tools/legal_intel.html",
        form=form,
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user),
        show_modal=not (current_user.preferences and current_user.preferences.hide_intel_modal),
    )


@tools_bp.route("/tools/compare", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def compare():
    from app.forms.document_forms import CompareForm
    from app.models.document import CompareResult, GeneratedDocument
    from app.services.authz import can_generate_documents
    from app.services.task_service import enqueue_job
    from app.tasks.ai_tasks import run_compare_documents

    if not (can_run_legal_intel(current_user, require_key=False) or can_generate_documents(current_user)):
        abort(403)
    form = CompareForm()
    cases = list_for(current_user, {})
    allowed_ids = [c.id for c in cases]
    form.case_id.choices = [(0, "-")] + [(c.id, c.display_cr) for c in cases]
    gens = GeneratedDocument.query.filter(
        GeneratedDocument.case_id.in_(allowed_ids or [-1]),
        GeneratedDocument.status.in_(("completed", "final")),
    ).order_by(GeneratedDocument.created_at.desc()).limit(80).all()
    form.left_generated.choices = [(0, "-")] + [
        (g.id, f"{g.doc_type} v{g.version_number} · {g.language}") for g in gens
    ]
    form.right_generated.choices = form.left_generated.choices
    if request.method == "POST":
        try:
            posted_left = int(request.form.get("left_generated") or 0)
            posted_right = int(request.form.get("right_generated") or 0)
        except (TypeError, ValueError):
            posted_left = posted_right = 0
        for did in (posted_left, posted_right):
            if not did:
                continue
            doc = db.session.get(GeneratedDocument, did)
            if doc is None or doc.case_id not in allowed_ids:
                abort(404)
    if form.validate_on_submit():
        left_id = form.left_generated.data or 0
        right_id = form.right_generated.data or 0
        if not left_id or not right_id or left_id == right_id:
            flash(translate("cmp.need_two"), "danger")
        else:
            left = db.session.get(GeneratedDocument, left_id)
            right = db.session.get(GeneratedDocument, right_id)
            if left is None or right is None:
                abort(404)
            if left.case_id not in allowed_ids or right.case_id not in allowed_ids:
                abort(404)
            row = CompareResult(
                user_id=current_user.id,
                case_id=left.case_id if left.case_id == right.case_id else None,
                left_kind="generated",
                left_ref=left.uuid,
                right_kind="generated",
                right_ref=right.uuid,
                language=form.language.data or "en",
            )
            db.session.add(row)
            db.session.commit()
            job = enqueue_job(
                current_user,
                "crimegpt.compare_documents",
                run_compare_documents,
                extra={"compare_id": row.id, "user_id": current_user.id},
                case_id=row.case_id,
            )
            row.job_id = job.id
            db.session.commit()
            return redirect(url_for("jobs.progress", job_uuid=job.uuid))
    return render_template(
        "tools/compare.html",
        form=form,
        gemini_ok=gemini_ready(),
    )


def _resolve_case(cid):
    if not cid:
        return None
    case = db.session.get(Case, int(cid))
    if case is None or not case_is_visible(current_user, case):
        abort(404)
    return case


@tools_bp.route("/tools/qa", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def qa_list():
    from app.forms.tool_forms import QaForm
    from app.models.ai import QaThread
    from app.services.qa_service import enqueue_qa_turn

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    form = QaForm()
    form.case_id.choices = _case_choices()
    pre = request.args.get("case")
    if request.method == "GET" and pre:
        case = Case.query.filter_by(uuid=pre).first()
        if case and case_is_visible(current_user, case):
            form.case_id.data = case.id
    if form.validate_on_submit():
        if not gemini_ready():
            form.body.errors = list(form.body.errors) + [translate("intel.missing_key")]
        else:
            case = _resolve_case(form.case_id.data)
            try:
                job, thread = enqueue_qa_turn(current_user, form.body.data, case=case)
                return redirect(url_for("tools.qa_thread", tid=thread.uuid))
            except RuntimeError as exc:
                code = str(exc)
                if code == "quota":
                    flash(translate("intel.quota"), "warning")
                elif code == "not_configured":
                    form.body.errors = list(form.body.errors) + [translate("intel.missing_key")]
                elif code == "disclaimer":
                    flash(translate("flash.need_disclaimer"), "danger")
                else:
                    flash(translate("form.fix"), "danger")
            except ValueError:
                flash(translate("qa.length"), "danger")
    q = QaThread.query
    if current_user.role not in ("super_admin", "admin"):
        q = q.filter_by(user_id=current_user.id)
    threads = q.order_by(QaThread.updated_at.desc()).limit(40).all()
    return render_template(
        "tools/qa_list.html",
        form=form,
        threads=threads,
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user),
    )


@tools_bp.route("/tools/qa/<tid>", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def qa_thread(tid):
    import json

    from app.forms.tool_forms import QaForm
    from app.models import CeleryJob
    from app.models.ai import QaMessage, QaThread
    from app.services.qa_service import can_view_thread, enqueue_qa_turn

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    thread = QaThread.query.filter_by(uuid=tid).first()
    if thread is None or not can_view_thread(current_user, thread):
        abort(404)
    form = QaForm()
    form.case_id.choices = _case_choices()
    if form.validate_on_submit():
        if not gemini_ready():
            flash(translate("intel.missing_key"), "danger")
        else:
            try:
                enqueue_qa_turn(current_user, form.body.data, case=thread.case, thread=thread)
                return redirect(url_for("tools.qa_thread", tid=thread.uuid))
            except RuntimeError as exc:
                flash(translate("intel.quota") if str(exc) == "quota" else translate("form.fix"), "warning")
            except ValueError:
                flash(translate("qa.length"), "danger")
    messages = thread.messages.order_by(QaMessage.id.asc()).all()
    pending = None
    last = messages[-1] if messages else None
    if last and last.role == "user" and last.job_id:
        job = db.session.get(CeleryJob, last.job_id)
        if job and job.status in ("queued", "processing"):
            pending = job
    follows = []
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.followups_json:
            try:
                follows = json.loads(msg.followups_json) or []
            except (TypeError, ValueError):
                follows = []
            break
    return render_template(
        "tools/qa_thread.html",
        thread=thread,
        messages=messages,
        form=form,
        pending=pending,
        follows=follows,
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user),
    )


@tools_bp.route("/tools/qa/<tid>/save-notes", methods=["POST"])
@login_required
def qa_save_notes(tid):
    from app.forms.tool_forms import EmptyPostForm
    from app.models.ai import QaThread
    from app.models.evidence import CaseDiaryEntry
    from app.models.mixins import utcnow
    from app.services.qa_service import can_view_thread, last_exchange

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not EmptyPostForm().validate_on_submit():
        abort(400)
    thread = QaThread.query.filter_by(uuid=tid).first()
    if thread is None or not can_view_thread(current_user, thread):
        abort(404)
    if not thread.case_id:
        flash(translate("qa.need_case"), "warning")
        return redirect(url_for("tools.qa_thread", tid=thread.uuid))
    q, a = last_exchange(thread)
    body = f"Q&A note (unconfirmed).\nQ: {q[:800]}\nA: {a[:1600]}"
    db.session.add(
        CaseDiaryEntry(
            case_id=thread.case_id,
            author_id=current_user.id,
            entry_type="other",
            occurred_at=utcnow(),
            body=body,
            status="draft",
        )
    )
    db.session.commit()
    flash(translate("flash.qa_saved"), "success")
    return redirect(url_for("tools.qa_thread", tid=thread.uuid))


@tools_bp.route("/tools/qa/<tid>/send-intel", methods=["POST"])
@login_required
def qa_send_intel(tid):
    from app.forms.tool_forms import EmptyPostForm
    from app.models.ai import QaThread
    from app.services.qa_service import can_view_thread, last_exchange

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not EmptyPostForm().validate_on_submit():
        abort(400)
    thread = QaThread.query.filter_by(uuid=tid).first()
    if thread is None or not can_view_thread(current_user, thread):
        abort(404)
    q, a = last_exchange(thread)
    session["intel_prefill"] = f"{q}\n\n{a[:1200]}"
    dest = url_for("tools.legal_intel", case=thread.case.uuid) if thread.case else url_for("tools.legal_intel")
    flash(translate("qa.intel_prefill"), "info")
    return redirect(dest)


@tools_bp.route("/tools/analyze", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def analyze():
    from app.forms.tool_forms import AnalyzeForm
    from app.models.document import LibraryDocument
    from app.models.mixins import utcnow
    from app.services.analysis_service import enqueue_analyze
    from app.services.file_service import file_service
    from app.utils.file_utils import validate_upload

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    form = AnalyzeForm()
    form.case_id.choices = _case_choices()
    prefs = current_user.preferences
    need_consent = not (prefs and prefs.evidence_consent_at)
    if form.validate_on_submit():
        if not gemini_ready():
            flash(translate("intel.missing_key"), "danger")
        elif need_consent and not form.consent.data:
            form.consent.errors = list(form.consent.errors) + [translate("ev.consent_box")]
        else:
            upload = request.files.get("file")
            data = upload.read() if upload else b""
            meta, err = validate_upload(upload.filename if upload else "", data, allow_docx=True)
            if err:
                flash(err, "danger")
            else:
                case = _resolve_case(form.case_id.data)
                key = f"library/{current_user.uuid}/{meta['stored_name']}"
                file_service.put(data, key)
                row = LibraryDocument(
                    case_id=case.id if case else None,
                    uploaded_by_id=current_user.id,
                    original_filename=meta["display_name"],
                    stored_name=meta["stored_name"],
                    stored_path=key,
                    mime=meta["mime"],
                    size_bytes=meta["size"],
                    source="analyse",
                )
                if prefs and not prefs.evidence_consent_at:
                    prefs.evidence_consent_at = utcnow()
                db.session.add(row)
                db.session.commit()
                try:
                    job, _ = enqueue_analyze(current_user, row, case=case, language=form.language.data or "en")
                except RuntimeError as exc:
                    flash(translate("intel.quota") if str(exc) == "quota" else translate("intel.missing_key"), "warning")
                    return redirect(url_for("tools.analyze"))
                return redirect(url_for("jobs.progress", job_uuid=job.uuid))
    return render_template(
        "tools/analyze.html",
        form=form,
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user),
        need_consent=need_consent,
    )


@tools_bp.route("/tools/explain", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per hour", methods=["POST"])
def explain():
    from app.forms.tool_forms import ExplainForm
    from app.models.ai import TranslateResult
    from app.services.intel_service import quota_reached as quota_hit
    from app.services.task_service import enqueue_job
    from app.tasks.ai_tasks import run_translate

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    form = ExplainForm()
    form.case_id.choices = _case_choices()
    if form.validate_on_submit():
        if not gemini_ready():
            form.source_text.errors = list(form.source_text.errors) + [translate("intel.missing_key")]
        elif quota_hit(current_user):
            flash(translate("intel.quota"), "warning")
        else:
            case = _resolve_case(form.case_id.data)
            row = TranslateResult(
                user_id=current_user.id,
                case_id=case.id if case else None,
                mode=form.mode.data or "explain",
                source_text=form.source_text.data.strip(),
                target_lang=form.target_lang.data or "en",
            )
            db.session.add(row)
            db.session.commit()
            job = enqueue_job(
                current_user,
                "crimegpt.translate",
                run_translate,
                extra={"translate_id": row.id, "user_id": current_user.id},
                case_id=row.case_id,
            )
            row.job_id = job.id
            db.session.commit()
            return redirect(url_for("jobs.progress", job_uuid=job.uuid))
    return render_template(
        "tools/explain.html",
        form=form,
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user),
    )
