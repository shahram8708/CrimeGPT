from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import CeleryJob
from app.services.authz import can_view_job
from app.services.task_service import enqueue_system_ping

jobs_bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _owned_job(job_uuid):
    job = CeleryJob.query.filter_by(uuid=job_uuid).first()
    if job is None or not can_view_job(current_user, job):
        abort(404)
    return job


def job_redirect_path(job):
    if job is None or job.status != "completed" or not job.result_ref_table or not job.result_ref_id:
        return None
    if job.result_ref_table == "legal_suggestions":
        from app.models.ai import LegalSuggestion

        row = db.session.get(LegalSuggestion, job.result_ref_id)
        if row:
            return url_for("results.legal_intel", rid=row.uuid)
    if job.result_ref_table == "diary_exports":
        from app.models.evidence import DiaryExport

        exp = db.session.get(DiaryExport, job.result_ref_id)
        if exp and exp.case:
            return url_for("diary.diary_export_result", uuid=exp.case.uuid, export_uuid=exp.uuid)
    if job.result_ref_table == "generated_documents":
        from app.models.document import GeneratedDocument

        row = db.session.get(GeneratedDocument, job.result_ref_id)
        if row and row.case:
            return url_for("documents.preview", uuid=row.case.uuid, did=row.uuid)
    if job.result_ref_table == "compare_results":
        from app.models.document import CompareResult

        row = db.session.get(CompareResult, job.result_ref_id)
        if row:
            return url_for("results.compare", rid=row.uuid)
    if job.result_ref_table == "clause_analyses":
        from app.models.document import ClauseAnalysis

        row = db.session.get(ClauseAnalysis, job.result_ref_id)
        if row:
            return url_for("results.identify", rid=row.uuid)
    if job.result_ref_table == "qa_threads":
        from app.models.ai import QaThread

        row = db.session.get(QaThread, job.result_ref_id)
        if row:
            return url_for("tools.qa_thread", tid=row.uuid)
    if job.result_ref_table == "document_analyses":
        from app.models.ai import DocumentAnalysis

        row = db.session.get(DocumentAnalysis, job.result_ref_id)
        if row:
            return url_for("results.analysis", rid=row.uuid)
    if job.result_ref_table == "translate_results":
        from app.models.ai import TranslateResult

        row = db.session.get(TranslateResult, job.result_ref_id)
        if row:
            return url_for("results.translate", rid=row.uuid)
    if job.result_ref_table == "legal_checklists":
        from app.models.ai import LegalChecklist

        row = db.session.get(LegalChecklist, job.result_ref_id)
        if row and row.case:
            return url_for("assist.checklist", uuid=row.case.uuid)
    if job.result_ref_table == "gap_results":
        from app.models.ai import GapResult

        row = db.session.get(GapResult, job.result_ref_id)
        if row and row.case:
            return url_for("assist.gaps", uuid=row.case.uuid)
    return None


@jobs_bp.route("/<job_uuid>")
@login_required
def progress(job_uuid):
    job = _owned_job(job_uuid)
    dest = job_redirect_path(job)
    if dest and request.args.get("stay") != "1":
        return redirect(dest)
    return render_template("jobs/progress.html", job=job)


@jobs_bp.route("/<job_uuid>/retry", methods=["POST"])
@login_required
def retry(job_uuid):
    job = _owned_job(job_uuid)
    if job.task_name != "crimegpt.legal_intel":
        ping = enqueue_system_ping(current_user)
        return redirect(url_for("jobs.progress", job_uuid=ping.uuid))
    from app.models.ai import LegalSuggestion
    from app.services.authz import can_run_legal_intel, gemini_ready
    from app.services.intel_service import enqueue_legal_intel

    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not gemini_ready():
        abort(403)
    sugg = LegalSuggestion.query.filter_by(job_id=job.id).first()
    if sugg is None:
        abort(404)
    new_job, _ = enqueue_legal_intel(
        current_user,
        sugg.narrative_snapshot,
        language=sugg.language,
        focus=sugg.focus,
        use_search=bool(sugg.use_search),
        case=sugg.case,
    )
    return redirect(url_for("jobs.progress", job_uuid=new_job.uuid))


@jobs_bp.route("/ping", methods=["POST"])
@login_required
def ping():
    job = enqueue_system_ping(current_user)
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))
