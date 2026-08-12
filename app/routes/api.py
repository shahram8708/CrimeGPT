from flask import Blueprint, abort, jsonify
from flask_login import current_user, login_required

from app.models import CeleryJob
from app.routes.jobs import job_redirect_path
from app.services.authz import can_view_job

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/jobs/<job_uuid>")
@login_required
def job_status(job_uuid):
    job = CeleryJob.query.filter_by(uuid=job_uuid).first()
    if job is None or not can_view_job(current_user, job):
        abort(404)
    payload = job.to_poll_dict()
    dest = job_redirect_path(job)
    if dest:
        payload["redirect"] = dest
    return jsonify(payload)
