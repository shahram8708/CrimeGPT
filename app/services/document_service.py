import json
from datetime import date, timedelta

from flask import current_app

from app.extensions import db
from app.models import Case, Notification, UsageCounter, User
from app.models.document import ALL_DOC_CARDS, GeneratedDocument, LIVE_DOC_TYPES
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_generate_documents
from app.services.gemini_service import PLATFORM_DISCLAIMER, gemini_configured
from app.services.intel_service import increment_gemini_calls, quota_reached, station_for
from app.utils.formatting_utils import format_ist, redact_sensitive

DOC_TITLES = {
    "medical_letter": "Medical Treatment Letter",
    "seizure_receipt": "Seizure Receipt",
    "remand_pc": "Remand Request (Police Custody)",
    "face_identification": "Accused Face Identification Form",
    "purvani_chargesheet": "Purvani Chargesheet",
    "court_custody": "Court Custody Letter",
    "accused_panchanama": "Accused Panchanama",
    "lers_request": "Legal request letter (template)",
}

NOTICE = {
    "en": "This file is a draft assistance output. The officer remains responsible for statutory accuracy.",
    "hi": "यह फ़ाइल मसौदा सहायता है। वैधानिक शुद्धता का उत्तरदायित्व अधिकारी का है।",
    "gu": "આ ફાઇલ મુસદ્દો સહાય છે. કાનૂની ચોકસાઈની જવાબદારી અધિકારીની છે.",
}

DISCLAIMER = {
    "en": PLATFORM_DISCLAIMER,
    "hi": (
        "एआई-जनित कानूनी जानकारी में त्रुटियाँ हो सकती हैं और इसे प्रामाणिक कानूनी "
        "स्रोतों से सत्यापित किया जाना चाहिए। यह मंच कानूनी सलाह प्रदान नहीं करता है। "
        "महत्वपूर्ण कानूनी परिणामों वाले मामलों के लिए कृपया एक योग्य कानूनी पेशेवर से परामर्श करें।"
    ),
    "gu": (
        "એઆઈ-જનિત કાનૂની માહિતીમાં ભૂલો હોઈ શકે છે અને તેને પ્રમાણભૂત કાનૂની સ્ત્રોતો "
        "સામે ચકાસવી જોઈએ. આ પ્લેટફોર્મ કાનૂની સલાહ આપતું નથી. નોંધપાત્ર કાનૂની "
        "પરિણામો ધરાવતા મામલાઓ માટે કૃપા કરીને લાયક કાનૂની વ્યાવસાયિકની સલાહ લો."
    ),
}


def _miss(field, label, href):
    return {"field": field, "label": label, "href": href}


def _diary_gist(case):
    try:
        from app.models.evidence import CaseDiaryEntry

        rows = (
            CaseDiaryEntry.query.filter_by(case_id=case.id, status="signed")
            .order_by(CaseDiaryEntry.occurred_at.desc())
            .limit(3)
            .all()
        )
        return " ".join((r.body or "")[:240] for r in rows)
    except Exception:
        return ""


def _first_sentence(text):
    raw = (text or "").strip()
    if not raw:
        return ""
    for sep in (". ", "। ", "।"):
        if sep in raw:
            return raw.split(sep, 1)[0].strip()
    return raw[:240]


def preflight(case, doc_type, form=None):
    form = form or {}
    uuid = case.uuid
    missing = []
    warnings = []
    station = case.station
    if not (station and station.name):
        missing.append(_miss("station", "Station letterhead name", f"/cases/{uuid}"))
    if doc_type == "medical_letter":
        injured = [p for p in case.live_parties() if p.role in ("injured", "complainant")]
        if not injured:
            missing.append(_miss("injured", "Injured or complainant party", f"/cases/{uuid}/parties/new"))
        if not (case.medical and (case.medical.hospital_name or "").strip()):
            missing.append(_miss("hospital_name", "Hospital name", f"/cases/{uuid}/medical"))
        if not case.incident_at:
            missing.append(_miss("incident_at", "Incident time", f"/cases/{uuid}/edit"))
        if not _first_sentence(case.narrative):
            missing.append(_miss("gist", "Short alleged offence gist", f"/cases/{uuid}/edit"))
    elif doc_type == "seizure_receipt":
        items = [i for i in case.live_items() if (i.description or "").strip() and (i.quantity or "").strip()]
        if not items:
            missing.append(_miss("items", "At least one item with description and quantity", f"/cases/{uuid}/items/new"))
        panch = case.live_parties("panch")
        if len(panch) < 2:
            missing.append(_miss("panch", "Seizure receipt needs two panch names", f"/cases/{uuid}/parties/new"))
        has_place = any((i.place or "").strip() for i in case.live_items()) or (case.place_of_occurrence or "").strip()
        if not has_place:
            missing.append(_miss("place", "Place of seizure", f"/cases/{uuid}/items"))
        if not any(i.seized_at for i in case.live_items()):
            warnings.append({"field": "seized_at", "label": "Seizure time will use the incident time."})
        if not case.live_parties("accused"):
            warnings.append({"field": "possessor", "label": "Accused or possessor is not recorded."})
    elif doc_type == "remand_pc":
        accused = case.live_parties("accused")
        if not accused:
            missing.append(_miss("accused", "At least one accused", f"/cases/{uuid}/parties/new"))
        arrests = {a.accused_id: a for a in case.live_arrests()}
        if accused and not any(arrests.get(p.id) and arrests[p.id].arrest_at and arrests[p.id].place for p in accused):
            missing.append(_miss("arrest", "Arrest time and place", f"/cases/{uuid}/arrests"))
        if any(arrests.get(p.id) and not arrests[p.id].rights_informed for p in accused):
            warnings.append({"field": "rights", "label": "Rights informed is not ticked on an arrest row."})
        if not any(s.status == "confirmed" for s in case.sections.all()):
            missing.append(_miss("sections", "At least one confirmed section", f"/cases/{uuid}/sections"))
        hours = (form.get("custody_hours_sought") or "").strip()
        if not hours:
            missing.append(_miss("custody_hours_sought", "Hours of police custody sought", f"/cases/{uuid}/documents/generate?type=remand_pc"))
        court = (form.get("court_name") or "").strip()
        produced = any((a.produced_before or "").strip() for a in case.live_arrests())
        if not court and not produced:
            missing.append(_miss("court", "Court name or produced-before", f"/cases/{uuid}/arrests"))
        if any(p.is_juvenile for p in accused):
            warnings.append({"field": "juvenile", "label": "A selected accused is recorded as a juvenile."})
    elif doc_type == "face_identification":
        accused = case.live_parties("accused")
        if not accused:
            missing.append(_miss("accused", "Accused identity", f"/cases/{uuid}/parties/new"))
        else:
            row = accused[0]
            if not row.full_name:
                missing.append(_miss("accused_name", "Accused name", f"/cases/{uuid}/parties"))
        if not (case.assigned_io or form.get("officer_name")):
            warnings.append({"field": "io", "label": "Investigating officer name will use the signed-in officer."})
    elif doc_type == "purvani_chargesheet":
        if not case.live_parties("complainant"):
            missing.append(_miss("complainant", "At least one complainant", f"/cases/{uuid}/parties/new"))
        if len((case.narrative or "").strip()) < 50:
            missing.append(_miss("narrative", "Narrative of at least 50 characters", f"/cases/{uuid}/edit"))
        if not any(s.status == "confirmed" for s in case.sections.all()):
            missing.append(_miss("sections", "At least one confirmed section", f"/cases/{uuid}/sections"))
        if not case.live_parties("witness"):
            warnings.append({"field": "witness", "label": "No witness party is recorded."})
        if not case.live_items():
            warnings.append({"field": "exhibits", "label": "No exhibits are listed on the case."})
    elif doc_type == "court_custody":
        if not case.live_parties("accused"):
            missing.append(_miss("accused", "Accused", f"/cases/{uuid}/parties/new"))
        produced = any((a.produced_before or "").strip() for a in case.live_arrests())
        if not produced and not (form.get("production_at") or "").strip() and not (form.get("court_name") or "").strip():
            missing.append(_miss("production", "Production datetime or court name", f"/cases/{uuid}/arrests"))
    elif doc_type == "accused_panchanama":
        if not case.live_parties("accused"):
            missing.append(_miss("accused", "Accused identity", f"/cases/{uuid}/parties/new"))
        if len(case.live_parties("panch")) < 2:
            missing.append(_miss("panch", "Two panch parties", f"/cases/{uuid}/parties/new"))
        if any(p.is_juvenile for p in case.live_parties("accused")):
            warnings.append({"field": "juvenile", "label": "A selected accused is recorded as a juvenile."})
    elif doc_type == "lers_request":
        if not case.cr_number and not case.display_cr:
            warnings.append({"field": "cr", "label": "CR number is not set; the letter will show Draft."})
        if not (form.get("date_from") or "").strip():
            warnings.append({"field": "date_from", "label": "Add a date range for the request."})
    ready = not missing
    return {"ready": ready, "missing": missing, "warnings": warnings}


def _party_dict(p):
    return {
        "name": p.full_name or "-",
        "guardian": p.guardian_name or "-",
        "age": p.age if p.age is not None else "-",
        "gender": p.gender or "-",
        "address": p.address or "-",
        "alias": p.alias or "-",
        "is_juvenile": bool(p.is_juvenile),
        "id": p.id,
    }


def build_context(case, doc_type, user, options=None):
    options = options or {}
    lang = options.get("language") or "en"
    station = case.station
    accused_ids = options.get("accused_ids") or []
    accused_all = case.live_parties("accused")
    if accused_ids:
        wanted = {int(i) for i in accused_ids}
        accused = [p for p in accused_all if p.id in wanted]
    else:
        accused = accused_all
    injured = next((p for p in case.live_parties() if p.role in ("injured", "complainant")), None)
    sections = [
        {"family": s.statute_family, "code": s.code, "title": s.title or ""}
        for s in case.sections.all()
        if s.status == "confirmed"
    ]
    items = []
    for item in case.live_items():
        items.append(
            {
                "description": item.description,
                "quantity": item.quantity or "-",
                "unit": item.unit or "",
                "marking": item.serial_or_marking or "-",
                "exhibit": item.exhibit_no or "-",
                "place": item.place or case.place_of_occurrence or "-",
                "seized_at": format_ist(item.seized_at or case.incident_at),
            }
        )
    arrests = []
    by_id = {a.accused_id: a for a in case.live_arrests()}
    for p in accused:
        ar = by_id.get(p.id)
        arrests.append(
            {
                "accused_name": p.full_name,
                "arrest_at": format_ist(ar.arrest_at) if ar and ar.arrest_at else "-",
                "place": ar.place if ar else "-",
                "rights_informed": bool(ar and ar.rights_informed),
                "produced_before": (ar.produced_before if ar else "") or "-",
            }
        )
    photo = None
    try:
        from app.models.evidence import EvidenceItem

        ev = (
            EvidenceItem.query.filter_by(case_id=case.id, deleted_at=None)
            .filter(EvidenceItem.tag.in_(("injury", "scene", "other")))
            .first()
        )
        if ev:
            photo = ev.uuid
    except Exception:
        photo = None
    med = case.medical
    io = case.assigned_io
    ctx = {
        "doc_type": doc_type,
        "doc_title": DOC_TITLES.get(doc_type, doc_type),
        "language": lang,
        "station_name": station.name if station else "-",
        "station_code": station.code if station else "-",
        "district": (station.district if station else "") or "-",
        "address": (station.address if station else "") or "-",
        "phone": (station.phone if station else "") or "-",
        "letterhead_2": (station.letterhead_line2 if station else "") or "",
        "letterhead_3": (station.letterhead_line3 if station else "") or "",
        "cr": case.display_cr,
        "gd": case.gd_number or "-",
        "incident_at": format_ist(case.incident_at),
        "place": case.place_of_occurrence or "-",
        "gist": _first_sentence(case.narrative),
        "disclaimer": DISCLAIMER.get(lang) or DISCLAIMER["en"],
        "notice": NOTICE.get(lang) or NOTICE["en"],
        "generated_at": format_ist(utcnow()),
        "is_incomplete": bool(options.get("is_incomplete")),
        "officer_name": user.full_name if user else "-",
        "officer_rank": (user.rank_label if user else "") or (user.role_label if user else ""),
        "io_name": io.full_name if io else (user.full_name if user else "-"),
        "io_rank": (io.rank_label if io else "") or "",
        "injured": _party_dict(injured) if injured else None,
        "accused": [_party_dict(p) for p in accused],
        "panch": [_party_dict(p) for p in case.live_parties("panch")],
        "items": items,
        "sections": sections,
        "arrests": arrests,
        "hospital_name": (med.hospital_name if med else "") or "-",
        "department": (med.department if med else "") or "-",
        "mlc_no": (med.mlc_no if med else "") or "-",
        "history_reported": (med.history_reported if med else "") or "",
        "requested_exam": (med.requested_exam if med else "") or "",
        "escort_name": (med.escorting_officer.full_name if med and med.escorting_officer else "-"),
        "custody_hours": options.get("custody_hours_sought") or "",
        "court_name": options.get("court_name") or next(
            ((a.produced_before or "") for a in case.live_arrests() if a.produced_before),
            "",
        ),
        "grounds": options.get("grounds") or "",
        "witnesses": [_party_dict(p) for p in case.live_parties("witness")],
        "complainants": [_party_dict(p) for p in case.live_parties("complainant")],
        "narrative": (case.narrative or "")[:4000],
        "investigation_gist": options.get("investigation_gist") or _diary_gist(case),
        "production_at": options.get("production_at") or "",
        "person_description": options.get("description") or "",
        "date_from": options.get("date_from") or "",
        "date_to": options.get("date_to") or "",
        "request_target": options.get("request_target") or "the service provider",
        "photo": photo,
        "photo_note": "To be affixed" if not photo else "",
        "ai": options.get("ai") or {},
        "ai_confidence": (options.get("ai") or {}).get("confidence"),
    }
    return ctx


def next_version(case_id, doc_type):
    last = (
        GeneratedDocument.query.filter_by(case_id=case_id, doc_type=doc_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (last.version_number + 1) if last else 1


def last_for(case, doc_type):
    return (
        GeneratedDocument.query.filter_by(case_id=case.id, doc_type=doc_type)
        .filter(GeneratedDocument.status.in_(("completed", "final")))
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )


def increment_doc_generations(user, case=None):
    today = date.today()
    sid = station_for(user, case)
    if not sid:
        return
    row = UsageCounter.query.filter_by(station_id=sid, user_id=user.id, day=today).first()
    if row is None:
        row = UsageCounter(station_id=sid, user_id=user.id, day=today, gemini_calls=0, doc_generations=0)
        db.session.add(row)
    row.doc_generations = (row.doc_generations or 0) + 1


def docs_this_week(user):
    from app.services.case_service import base_query

    week = utcnow() - timedelta(days=7)
    ids = [c.id for c in base_query(user).all()]
    if not ids:
        return 0
    return GeneratedDocument.query.filter(
        GeneratedDocument.case_id.in_(ids),
        GeneratedDocument.status.in_(("completed", "final")),
        GeneratedDocument.created_at >= week,
    ).count()


def enqueue_generate(user, case, doc_type, options):
    from app.services.task_service import enqueue_job
    from app.tasks.document_tasks import run_generate_document

    if doc_type not in LIVE_DOC_TYPES:
        raise ValueError("unavailable")
    if not can_generate_documents(user, case):
        raise PermissionError("forbidden")
    from app.services.entitlement_service import doc_type_allowed

    if not doc_type_allowed(user, case, doc_type):
        raise RuntimeError("plan")
    use_ai = bool(options.get("use_ai")) and gemini_configured()
    if use_ai and quota_reached(user, case):
        raise RuntimeError("quota")
    row = GeneratedDocument(
        case_id=case.id,
        created_by_id=user.id,
        doc_type=doc_type,
        language=options.get("language") or "en",
        version_number=next_version(case.id, doc_type),
        parent_id=options.get("parent_id"),
        status="pending",
        ai_used=use_ai,
        is_incomplete=bool(options.get("is_incomplete")),
        context_json=json.dumps(
            {
                "accused_ids": options.get("accused_ids") or [],
                "combined": options.get("combined", True),
                "custody_hours_sought": options.get("custody_hours_sought") or "",
                "court_name": options.get("court_name") or "",
                "grounds": options.get("grounds") or "",
                "investigation_gist": options.get("investigation_gist") or "",
                "production_at": options.get("production_at") or "",
                "description": options.get("description") or "",
                "date_from": options.get("date_from") or "",
                "date_to": options.get("date_to") or "",
                "request_target": options.get("request_target") or "",
                "use_ai": use_ai,
                "edited_ai": options.get("edited_ai") or {},
            },
            ensure_ascii=False,
        ),
    )
    db.session.add(row)
    db.session.commit()
    job = enqueue_job(
        user,
        "crimegpt.generate_document",
        run_generate_document,
        extra={"document_id": row.id, "user_id": user.id},
        case_id=case.id,
    )
    return job, row


def parse_ctx(doc):
    if not doc or not doc.context_json:
        return {}
    try:
        return json.loads(doc.context_json)
    except (TypeError, ValueError):
        return {}
