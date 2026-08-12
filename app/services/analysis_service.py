import json
import re
from datetime import datetime, timezone
from io import BytesIO

from app.extensions import db
from app.models import CaseMedical, CaseParty, CaseSection
from app.models.ai import DocumentAnalysis, SavedResult
from app.models.document import LibraryDocument
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_confirm_sections, can_edit_case_facts, can_run_legal_intel
from app.services.file_service import file_service
from app.services.gemini_service import gemini_configured
from app.utils.formatting_utils import statute_token_ok

FACT_KEYS = {
    "hospital_name": ("medical", "hospital_name"),
    "mlc_no": ("medical", "mlc_no"),
    "department": ("medical", "department"),
    "history_reported": ("medical", "history_reported"),
    "requested_exam": ("medical", "requested_exam"),
    "injured_name": ("party", "full_name"),
    "complainant_name": ("party", "full_name"),
    "party_name": ("party", "full_name"),
    "incident_date": ("case", "incident_at"),
}

STATUTE_HINT = re.compile(r"(section|statute|bns|bnss|bsa|ipc|offence_code|offense_code)", re.I)


def extract_docx_text(data):
    from docx import Document

    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def extract_pdf_text(data):
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def prepare_source(row):
    data = file_service.get(row.stored_path) or b""
    mime = (row.mime or "").lower()
    name = (row.original_filename or "").lower()
    if mime.endswith("wordprocessingml.document") or name.endswith(".docx"):
        return {"kind": "text", "text": extract_docx_text(data), "bytes": None, "mime": mime}
    if mime == "application/pdf" or name.endswith(".pdf"):
        text = extract_pdf_text(data)
        if len((text or "").strip()) >= 200:
            return {"kind": "text", "text": text, "bytes": None, "mime": mime}
        return {"kind": "bytes", "text": text or "", "bytes": data, "mime": "application/pdf"}
    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png")):
        return {"kind": "bytes", "text": "", "bytes": data, "mime": mime or "image/jpeg"}
    return {"kind": "text", "text": "", "bytes": None, "mime": mime}


def enqueue_analyze(user, library_row, case=None, language="en"):
    from app.services.intel_service import quota_reached
    from app.services.task_service import enqueue_job
    from app.tasks.ai_tasks import run_analyze_document

    if not can_run_legal_intel(user, require_key=False):
        raise PermissionError("forbidden")
    if not gemini_configured():
        raise RuntimeError("not_configured")
    if not user.disclaimer_accepted_at:
        raise RuntimeError("disclaimer")
    if quota_reached(user, case):
        raise RuntimeError("quota")
    row = DocumentAnalysis(
        document_id=library_row.id,
        case_id=case.id if case else library_row.case_id,
        user_id=user.id,
        language=language or "en",
    )
    db.session.add(row)
    db.session.commit()
    job = enqueue_job(
        user,
        "crimegpt.analyze_document",
        run_analyze_document,
        extra={"analysis_id": row.id, "user_id": user.id},
        case_id=row.case_id,
    )
    row.job_id = job.id
    db.session.commit()
    return job, row


def looks_like_statute(key, value):
    if STATUTE_HINT.search(key or ""):
        return True
    token = (value or "").strip()
    return bool(token) and (statute_token_ok(token, "BNS") or statute_token_ok(token, None))


def _medical(case):
    med = case.medical
    if med is None:
        med = CaseMedical(case_id=case.id)
        db.session.add(med)
        db.session.flush()
    return med


def apply_extracted_field(user, analysis, key, value, party_id=None, confirm=False):
    case = analysis.case
    if case is None:
        raise RuntimeError("no_case")
    if case.is_locked and user.role != "super_admin":
        raise PermissionError("locked")
    if not can_edit_case_facts(user, case) and user.role != "super_admin":
        raise PermissionError("forbidden")
    key = (key or "").strip()
    value = (value or "").strip()
    if not key or not value:
        raise ValueError("empty")
    if key in ("cr_number", "cr", "fir", "fir_number"):
        raise RuntimeError("cr_blocked")
    if looks_like_statute(key, value):
        if user.role == "writer" or not can_confirm_sections(user, case):
            if user.role not in ("io", "sho", "legal", "admin", "super_admin"):
                raise RuntimeError("statute")
        if user.role == "writer":
            raise RuntimeError("statute")
        family = "BNS"
        lowered = key.lower()
        if "bnss" in lowered:
            family = "BNSS"
        elif "bsa" in lowered:
            family = "BSA"
        dup = CaseSection.query.filter_by(case_id=case.id, statute_family=family, code=value).first()
        if dup:
            return "already"
        sec = CaseSection(
            case_id=case.id,
            statute_family=family,
            code=value[:40],
            title=key[:240],
            status="suggested",
            source="gemini-recommend",
        )
        db.session.add(sec)
        db.session.commit()
        write_audit(
            "case.field_applied_from_document",
            object_type="document_analysis",
            object_id=analysis.uuid,
            actor=user,
            station_id=case.station_id,
            case_id=case.id,
            meta={"key": key, "old": "", "new": value, "as": "suggested_section", "platform_override": user.role == "super_admin"},
        )
        return "suggested"
    target = FACT_KEYS.get(key)
    if target is None:
        raise RuntimeError("unknown_field")
    kind, attr = target
    old = ""
    if kind == "medical":
        med = _medical(case)
        old = getattr(med, attr) or ""
        setattr(med, attr, value[:200] if attr in ("hospital_name", "department", "mlc_no") else value)
    elif kind == "party":
        if not party_id:
            raise RuntimeError("need_party")
        party = CaseParty.query.filter_by(id=int(party_id), case_id=case.id, deleted_at=None).first()
        if party is None or party.role not in ("injured", "complainant", "accused"):
            raise RuntimeError("need_party")
        old = party.full_name
        party.full_name = value[:160]
    elif kind == "case":
        if not confirm:
            raise RuntimeError("need_confirm")
        old = case.incident_at.isoformat() if case.incident_at else ""
        try:
            day = datetime.fromisoformat(value[:10]).date()
        except ValueError as exc:
            raise ValueError("bad_date") from exc
        current = case.incident_at or utcnow()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        case.incident_at = current.replace(year=day.year, month=day.month, day=day.day)
    db.session.commit()
    write_audit(
        "case.field_applied_from_document",
        object_type="document_analysis",
        object_id=analysis.uuid,
        actor=user,
        station_id=case.station_id,
        case_id=case.id,
        meta={"key": key, "old": old, "new": value, "platform_override": user.role == "super_admin"},
    )
    return "applied"


def parsed_analysis(row):
    if not row or not row.result_json:
        return {}
    try:
        return json.loads(row.result_json)
    except (TypeError, ValueError):
        return {}


def save_analysis_result(user, row):
    existing = SavedResult.query.filter_by(
        user_id=user.id, ref_table="document_analyses", ref_id=row.id
    ).first()
    if existing:
        return existing
    title = f"Analysis - {row.document_type or 'document'}"
    db.session.add(
        SavedResult(
            user_id=user.id,
            case_id=row.case_id,
            result_type="analysis",
            ref_table="document_analyses",
            ref_id=row.id,
            title=title[:200],
        )
    )
