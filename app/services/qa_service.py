import json

from flask import url_for

from app.extensions import db
from app.models.ai import QaMessage, QaThread, SavedResult
from app.models.mixins import utcnow
from app.services.authz import can_run_legal_intel, case_is_visible
from app.services.gemini_service import gemini_configured
from app.utils.formatting_utils import redact_sensitive


def first_name(full):
    parts = [p for p in (full or "").split() if p]
    return parts[0] if parts else ""


def redacted_case_brief(case):
    if case is None:
        return ""
    parties = []
    for p in case.live_parties():
        parties.append(
            {
                "role": p.role,
                "name": first_name(p.full_name),
                "age": p.age,
                "gender": p.gender,
                "phone": p.phone or "",
                "id_number": p.id_number or "",
            }
        )
    items = [{"description": (i.description or "")[:160]} for i in case.live_items()]
    sections = [
        {"family": s.statute_family, "code": s.code}
        for s in case.sections.filter_by(status="confirmed").all()
    ]
    blob = {
        "category": case.category,
        "incident_at": case.incident_at.isoformat() if case.incident_at else None,
        "place": case.place_of_occurrence,
        "parties": parties,
        "sections": sections,
        "items": items,
    }
    return redact_sensitive(json.dumps(blob, ensure_ascii=False))


def can_view_thread(user, thread):
    if not user or not getattr(user, "is_authenticated", False) or thread is None:
        return False
    if user.role in ("super_admin", "admin"):
        return True
    if thread.user_id == user.id:
        return True
    if thread.case_id and thread.case:
        if not case_is_visible(user, thread.case):
            return False
        return user.role in ("io", "sho")
    return False


def thread_title(body):
    line = " ".join((body or "").split())
    return (line[:80] + "…") if len(line) > 80 else (line or "Question")


def enqueue_qa_turn(user, body, case=None, thread=None):
    from app.services.intel_service import quota_reached
    from app.services.task_service import enqueue_job
    from app.tasks.ai_tasks import run_qa_turn

    if not can_run_legal_intel(user, require_key=False):
        raise PermissionError("forbidden")
    if not gemini_configured():
        raise RuntimeError("not_configured")
    if not user.disclaimer_accepted_at:
        raise RuntimeError("disclaimer")
    text = (body or "").strip()
    if len(text) < 5 or len(text) > 4000:
        raise ValueError("length")
    if quota_reached(user, case):
        raise RuntimeError("quota")
    if thread is None:
        thread = QaThread(user_id=user.id, case_id=case.id if case else None, title=thread_title(text))
        db.session.add(thread)
        db.session.flush()
    else:
        thread.updated_at = utcnow()
        if case is not None and thread.case_id is None:
            thread.case_id = case.id
    msg = QaMessage(thread_id=thread.id, role="user", body=text)
    db.session.add(msg)
    db.session.commit()
    job = enqueue_job(
        user,
        "crimegpt.qa_turn",
        run_qa_turn,
        extra={"thread_id": thread.id, "user_id": user.id},
        case_id=thread.case_id,
    )
    msg.job_id = job.id
    db.session.commit()
    return job, thread


def save_thread_result(user, thread):
    existing = SavedResult.query.filter_by(
        user_id=user.id, ref_table="qa_threads", ref_id=thread.id
    ).first()
    if existing:
        return existing
    row = SavedResult(
        user_id=user.id,
        case_id=thread.case_id,
        result_type="qa",
        ref_table="qa_threads",
        ref_id=thread.id,
        title=(thread.title or "Q&A")[:200],
    )
    db.session.add(row)
    return row


def last_exchange(thread):
    rows = thread.messages.order_by(QaMessage.id.desc()).limit(8).all()
    question = next((m.body for m in rows if m.role == "user"), "")
    answer = next((m.body for m in rows if m.role == "assistant"), "")
    return question, answer


def result_url(thread):
    return url_for("tools.qa_thread", tid=thread.uuid)
