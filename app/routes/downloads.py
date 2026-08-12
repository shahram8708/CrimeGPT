from flask import Blueprint, abort, send_file
from flask_login import current_user, login_required
from io import BytesIO

from app.models.evidence import DiaryExport, EvidenceItem
from app.services.audit_service import write_audit
from app.services.authz import can_export_diary, require_case
from app.services.file_service import file_service, generated_files

downloads_bp = Blueprint("downloads", __name__)


def _safe_name(name, fallback):
    text = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in (name or fallback))
    return (text.strip() or fallback)[:80]


@downloads_bp.route("/downloads/upload/<uuid>")
@login_required
def original(uuid):
    item = EvidenceItem.query.filter_by(uuid=uuid).first()
    if item is None or item.deleted_at:
        lib = _library_file(uuid)
        if lib is not None:
            return lib
        abort(404)
    require_case(current_user, item.case, "view")
    data = file_service.get(item.stored_path)
    if data is None:
        abort(404)
    write_audit(
        "evidence.downloaded",
        object_type="evidence",
        object_id=item.uuid,
        case_id=item.case_id,
    )
    name = _safe_name(item.original_filename, item.stored_name)
    return send_file(
        BytesIO(data),
        mimetype=item.mime or "application/octet-stream",
        as_attachment=True,
        download_name=name,
    )


@downloads_bp.route("/downloads/thumb/<uuid>")
@login_required
def thumb(uuid):
    item = EvidenceItem.query.filter_by(uuid=uuid).first()
    if item is None or item.deleted_at:
        abort(404)
    require_case(current_user, item.case, "view")
    if not item.thumbnail_path:
        abort(404)
    data = file_service.get(item.thumbnail_path)
    if data is None:
        abort(404)
    return send_file(BytesIO(data), mimetype="image/jpeg")


def _library_file(uuid_value):
    from app.models.document import LibraryDocument
    from app.services.authz import case_is_visible

    row = LibraryDocument.query.filter_by(uuid=uuid_value).first()
    if row is None:
        return None
    if current_user.role not in ("super_admin", "admin"):
        if row.uploaded_by_id != current_user.id:
            if not row.case or not case_is_visible(current_user, row.case):
                abort(404)
    data = file_service.get(row.stored_path)
    if data is None:
        abort(404)
    write_audit("library.downloaded", object_type="library_document", object_id=row.uuid, case_id=row.case_id)
    name = _safe_name(row.original_filename, row.stored_name)
    return send_file(BytesIO(data), mimetype=row.mime or "application/octet-stream", as_attachment=True, download_name=name)


def _court_file(uuid_value, kind):
    from app.models.document import GeneratedDocument

    row = GeneratedDocument.query.filter_by(uuid=uuid_value).first()
    if row is None:
        return None
    require_case(current_user, row.case, "view")
    path = row.docx_path if kind == "docx" else row.pdf_path
    if not path:
        abort(404)
    data = generated_files.get(path)
    if data is None:
        abort(404)
    write_audit("document.downloaded", object_type="generated_document", object_id=row.uuid, case_id=row.case_id)
    cr = (row.case.cr_number or "draft").replace("/", "-")
    code = row.case.station.code if row.case.station else "STN"
    name = f"{code}_{cr}_{row.doc_type}_v{row.version_number}.{kind}"
    mime = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if kind == "docx"
        else "application/pdf"
    )
    return send_file(BytesIO(data), mimetype=mime, as_attachment=True, download_name=name)


@downloads_bp.route("/downloads/docx/<uuid>")
@login_required
def docx(uuid):
    court = _court_file(uuid, "docx")
    if court is not None:
        return court
    exp = DiaryExport.query.filter_by(uuid=uuid).first()
    if exp is None or not exp.docx_path:
        abort(404)
    require_case(current_user, exp.case, "view")
    if not can_export_diary(current_user, exp.case):
        abort(403)
    data = generated_files.get(exp.docx_path)
    if data is None:
        abort(404)
    write_audit("diary.exported_download", object_type="diary_export", object_id=exp.uuid, case_id=exp.case_id)
    cr = (exp.case.cr_number or "draft").replace("/", "-")
    code = exp.case.station.code if exp.case.station else "STN"
    name = f"{code}_{cr}_diary_{exp.date_from}_{exp.date_to}.docx"
    return send_file(
        BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=name,
    )


@downloads_bp.route("/downloads/pdf/<uuid>")
@login_required
def pdf(uuid):
    court = _court_file(uuid, "pdf")
    if court is not None:
        return court
    exp = DiaryExport.query.filter_by(uuid=uuid).first()
    if exp is None or not exp.pdf_path:
        abort(404)
    require_case(current_user, exp.case, "view")
    if not can_export_diary(current_user, exp.case):
        abort(403)
    data = generated_files.get(exp.pdf_path)
    if data is None:
        abort(404)
    write_audit("diary.exported_download", object_type="diary_export", object_id=exp.uuid, case_id=exp.case_id)
    cr = (exp.case.cr_number or "draft").replace("/", "-")
    code = exp.case.station.code if exp.case.station else "STN"
    name = f"{code}_{cr}_diary_{exp.date_from}_{exp.date_to}.pdf"
    return send_file(
        BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=name,
    )
