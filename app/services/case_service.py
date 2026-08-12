import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape
from sqlalchemy import or_, text

from app.extensions import db
from app.models import Case, CaseArrest, CaseItem, CaseParty, CaseSection, User
from app.services.authz import case_is_visible

IST = ZoneInfo("Asia/Kolkata")
NARRATIVE_MIN = 50
PLACE_MIN = 5

DOC_PREFLIGHT = (
    ("purvani", "Purvani Chargesheet", "identity", "edit"),
    ("medical", "Medical Treatment Letter", "medical", "medical"),
    ("remand_pc", "Remand Request (Police Custody)", "arrest", "arrests"),
    ("seizure", "Seizure Receipt", "items", "items"),
    ("court_custody", "Court Custody Letter", "arrest", "arrests"),
    ("panchanama", "Accused Panchanama", "accused", "parties"),
    ("face_id", "Accused Face Identification Form", "accused", "parties"),
)

PROGRESS_CHAIN = (
    ("draft", "Draft"),
    ("facts_captured", "Facts captured"),
    ("sections_confirmed", "Sections confirmed"),
    ("key_docs", "Key docs generated"),
    ("arrest_recorded", "Arrest recorded"),
    ("first_production", "First production"),
)


def _alive(query):
    return query.filter(Case.deleted_at.is_(None))


def base_query(user):
    q = _alive(Case.query)
    if not user or not getattr(user, "is_authenticated", False):
        return q.filter(Case.id == -1)
    if user.role in ("super_admin", "admin"):
        return q
    if user.role == "constable":
        from app.models.evidence import CaseAssignment

        ids = [a.case_id for a in CaseAssignment.query.filter_by(user_id=user.id).all()]
        if not ids:
            return q.filter(Case.id == -1)
        return q.filter(Case.id.in_(ids))
    if not user.station_id:
        return q.filter(Case.id == -1)
    q = q.filter(Case.station_id == user.station_id)
    if user.role == "sho":
        return q
    if user.role == "writer":
        return q
    if user.role == "io":
        return q.filter(or_(Case.created_by_id == user.id, Case.assigned_io_id == user.id))
    if user.role == "legal":
        return q.filter(Case.assigned_legal_id == user.id)
    return q.filter(Case.id == -1)


def apply_filters(query, filters):
    filters = filters or {}
    status = (filters.get("status") or "").strip()
    if status:
        query = query.filter(Case.status == status)
    year = (filters.get("year") or "").strip()
    if year.isdigit():
        query = query.filter(Case.year == int(year))
    category = (filters.get("category") or "").strip()
    if category:
        query = query.filter(Case.category == category)
    term = (filters.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(
                Case.cr_number.ilike(like),
                Case.gd_number.ilike(like),
                Case.place_of_occurrence.ilike(like),
                Case.narrative.ilike(like),
            )
        )
    return query


def list_for(user, filters=None, limit=None):
    q = apply_filters(base_query(user), filters).order_by(Case.incident_at.desc())
    if limit:
        return q.limit(limit).all()
    return q.all()


def list_paginated(user, filters=None, page=1, per_page=20):
    q = apply_filters(base_query(user), filters).order_by(Case.incident_at.desc())
    total = q.count()
    page = max(int(page or 1), 1)
    pages = max((total + per_page - 1) // per_page, 1)
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return items, total, page, pages


def get_by_uuid(user, uuid_value):
    case = Case.query.filter_by(uuid=uuid_value).first()
    if case is None or not case_is_visible(user, case):
        return None
    return case


def count_open(user):
    return base_query(user).filter(Case.status.in_(("draft", "open"))).count()


def recent_for(user, limit=5):
    return list_for(user, {}, limit=limit)


def _party_ready(case, roles):
    return any(p.full_name and p.role in roles for p in case.live_parties())


def completeness(case):
    accused = case.live_parties("accused")
    identity = bool(case.incident_at and len((case.place_of_occurrence or "").strip()) >= PLACE_MIN)
    complainant = _party_ready(case, ("complainant", "injured"))
    narrative = len((case.narrative or "").strip()) >= NARRATIVE_MIN
    accused_ok = bool(accused)
    items_ok = bool(case.live_items())
    arrest_applicable = bool(accused)
    arrest_ok = False
    if arrest_applicable:
        arrests = {a.accused_id: a for a in case.live_arrests()}
        arrest_ok = all(
            arrests.get(p.id)
            and arrests[p.id].arrest_at
            and arrests[p.id].place
            and arrests[p.id].rights_informed
            for p in accused
        )
    medical_ok = bool(
        case.medical
        and (case.medical.hospital_name or "").strip()
        and complainant
    )
    sections_ok = any(s.status == "confirmed" for s in case.sections.all())
    buckets = {
        "identity": {"ready": identity, "applicable": True},
        "complainant": {"ready": complainant, "applicable": True},
        "narrative": {"ready": narrative, "applicable": True},
        "accused": {"ready": accused_ok, "applicable": True},
        "items": {"ready": items_ok, "applicable": True},
        "arrest": {"ready": arrest_ok, "applicable": arrest_applicable},
        "medical": {"ready": medical_ok, "applicable": True},
        "sections": {"ready": sections_ok, "applicable": True},
    }
    counted = [b for b in buckets.values() if b["applicable"]]
    percent = int(round(100 * sum(1 for b in counted if b["ready"]) / len(counted))) if counted else 0
    return {"percent": percent, "buckets": buckets}


def next_actions(case):
    comp = completeness(case)
    buckets = comp["buckets"]
    uuid = case.uuid
    actions = []
    if not buckets["complainant"]["ready"]:
        actions.append({"label": "Add complainant", "href": f"/cases/{uuid}/parties/new"})
    if not buckets["accused"]["ready"]:
        actions.append({"label": "Add accused", "href": f"/cases/{uuid}/parties/new"})
    if not buckets["items"]["ready"]:
        actions.append({"label": "Add seized item", "href": f"/cases/{uuid}/items/new"})
    if buckets["arrest"]["applicable"] and not buckets["arrest"]["ready"]:
        actions.append({"label": "Record arrest time", "href": f"/cases/{uuid}/arrests"})
    if not buckets["medical"]["ready"] and buckets["accused"]["ready"]:
        actions.append(
            {
                "label": "Add hospital name for a medical treatment letter",
                "href": f"/cases/{uuid}/medical",
            }
        )
    elif not buckets["medical"]["ready"]:
        actions.append({"label": "Add hospital for medical letter", "href": f"/cases/{uuid}/medical"})
    if not buckets["sections"]["ready"]:
        actions.append({"label": "Confirm at least one section", "href": f"/cases/{uuid}/sections"})
    if not buckets["narrative"]["ready"]:
        actions.append({"label": "Add a narrative of at least 50 characters", "href": f"/cases/{uuid}/edit"})
    if not actions:
        actions.append(
            {
                "label": "Remand will need arrest time and confirmed sections",
                "href": f"/cases/{uuid}",
            }
        )
    panch = case.live_parties("panch")
    if buckets["items"]["ready"] and len(panch) < 2:
        actions.insert(
            0,
            {
                "label": "Seizure receipt needs two panch names",
                "href": f"/cases/{uuid}/parties/new",
            },
        )
    from app.models.ai import GapResult, LegalChecklist

    if LegalChecklist.query.filter_by(case_id=case.id).first() is None:
        actions.append({"label": "Generate checklist", "href": f"/cases/{uuid}/checklist"})
    if GapResult.query.filter_by(case_id=case.id).first() is None:
        actions.append({"label": "Run gap analysis", "href": f"/cases/{uuid}/gaps"})
    return actions


def progress_state(case):
    buckets = completeness(case)["buckets"]
    narrative_ok = buckets["narrative"]["ready"]
    identity_ok = buckets["identity"]["ready"]
    has_party = bool(case.live_parties())
    facts = identity_ok and has_party and narrative_ok
    sections = buckets["sections"]["ready"]
    arrest = any(a.rights_informed for a in case.live_arrests())
    production = any((a.produced_before or "").strip() for a in case.live_arrests()) or case.status == "in_court"
    current = "draft"
    if not identity_ok or case.status == "draft" and not facts:
        current = "draft"
    if facts:
        current = "facts_captured"
    if sections:
        current = "sections_confirmed"
    if arrest:
        current = "arrest_recorded"
    if production:
        current = "first_production"
    if not facts:
        current = "draft"
    return current


def progress_chain(case):
    current = progress_state(case)
    return [{"key": key, "label": label, "current": key == current} for key, label in PROGRESS_CHAIN]


def document_readiness(case):
    from app.services.document_service import last_for

    live_map = {
        "medical": "medical_letter",
        "seizure": "seizure_receipt",
        "remand_pc": "remand_pc",
        "face_id": "face_identification",
    }
    buckets = completeness(case)["buckets"]
    chips = []
    for key, title, bucket, endpoint in DOC_PREFLIGHT:
        ready = buckets.get(bucket, {}).get("ready")
        href = f"/cases/{case.uuid}/{endpoint}"
        label = "Missing fields"
        dtype = live_map.get(key)
        if dtype:
            last = last_for(case, dtype)
            if last:
                href = f"/cases/{case.uuid}/documents/{last.uuid}"
                label = f"v{last.version_number}"
            elif ready:
                href = f"/cases/{case.uuid}/documents"
                label = "Ready"
        elif not ready:
            href = f"/cases/{case.uuid}/{endpoint}"
        else:
            href = f"/cases/{case.uuid}/documents"
            label = "Not available"
        chips.append({"key": key, "title": title, "ready": ready, "label": label, "href": href})
    return chips


def cr_taken(station_id, year, cr_number, exclude_id=None):
    if not cr_number:
        return False
    q = Case.query.filter(
        Case.station_id == station_id,
        Case.year == year,
        Case.cr_number == cr_number.strip(),
        Case.deleted_at.is_(None),
    )
    if exclude_id:
        q = q.filter(Case.id != exclude_id)
    return q.first() is not None


def timestamps_match(stored, incoming):
    if stored is None or not incoming:
        return True
    try:
        other = datetime.fromisoformat(str(incoming).replace("Z", "+00:00"))
    except ValueError:
        return False
    left = stored if stored.tzinfo else stored.replace(tzinfo=timezone.utc)
    right = other if other.tzinfo else other.replace(tzinfo=timezone.utc)
    return abs((left - right).total_seconds()) < 1.5


def field_diff(case, incoming):
    mapping = {
        "cr_number": case.cr_number or "",
        "gd_number": case.gd_number or "",
        "place_of_occurrence": case.place_of_occurrence or "",
        "category": case.category or "",
        "narrative": case.narrative or "",
        "status": case.status or "",
        "year": str(case.year or ""),
    }
    rows = []
    for key, old in mapping.items():
        new = str(incoming.get(key) or "")
        if str(old) != new:
            rows.append({"field": key, "old": old, "new": new})
    return rows


def rebuild_fts(case):
    if case is None or case.id is None:
        return
    names = " ".join(p.full_name for p in case.live_parties() if p.full_name)
    items = " ".join(i.description for i in case.live_items() if i.description)
    diary = ""
    try:
        from app.models.evidence import CaseDiaryEntry

        bodies = [
            e.body
            for e in CaseDiaryEntry.query.filter_by(case_id=case.id).all()
            if e.body
        ]
        diary = " ".join(bodies)
    except Exception:
        diary = ""
    db.session.execute(text("DELETE FROM case_fts WHERE case_id = :id"), {"id": case.id})
    db.session.execute(
        text(
            "INSERT INTO case_fts (case_id, cr_number, narrative, party_names, diary_blob) "
            "VALUES (:id, :cr, :nar, :names, :diary)"
        ),
        {
            "id": case.id,
            "cr": case.cr_number or "",
            "nar": (case.narrative or "") + " " + items,
            "names": names,
            "diary": diary,
        },
    )
    db.session.commit()


def _fts_tokens(raw):
    return [t for t in re.findall(r"[A-Za-z0-9\u0900-\u0D7F]+", raw or "") if len(t) >= 2]


def search_fts(user, raw, filters=None):
    tokens = _fts_tokens(raw)
    if not tokens:
        return []
    match = " OR ".join(tokens)
    try:
        rows = db.session.execute(
            text(
                "SELECT case_id, cr_number, narrative, party_names "
                "FROM case_fts WHERE case_fts MATCH :q"
            ),
            {"q": match},
        ).fetchall()
    except Exception:
        db.session.rollback()
        rows = []
    allowed = {c.id: c for c in base_query(user).all()}
    results = []
    seen = set()
    for row in rows:
        case = allowed.get(row[0])
        if case is None or case.id in seen:
            continue
        seen.add(case.id)
        blob = " ".join(filter(None, [row[2], row[3], row[1]]))
        results.append(
            {
                "case": case,
                "snippet": highlight_snippet(blob[:280], tokens),
            }
        )
    like = f"%{(raw or '').strip()}%"
    extra = (
        base_query(user)
        .filter(or_(Case.cr_number.ilike(like), Case.gd_number.ilike(like)))
        .all()
    )
    for case in extra:
        if case.id in seen:
            continue
        results.append({"case": case, "snippet": highlight_snippet(case.cr_number or "", tokens)})
    return results


def highlight_snippet(text, tokens):
    escaped = str(escape(text or ""))
    for tok in tokens:
        safe_tok = str(escape(tok))
        if not safe_tok:
            continue
        escaped = re.sub(
            re.escape(safe_tok),
            lambda m: f"<mark>{m.group(0)}</mark>",
            escaped,
            flags=re.IGNORECASE,
        )
    return Markup(escaped)


def remand_clock(user):
    cases = base_query(user).filter(Case.status.in_(("draft", "open", "in_court"))).all()
    rows = []
    for case in cases:
        for arrest in case.live_arrests():
            if arrest.arrest_at and not (arrest.produced_before or "").strip():
                rows.append({"case": case, "arrest": arrest})
    rows.sort(key=lambda r: r["arrest"].arrest_at)
    return rows


def incomplete_queue(user):
    rows = []
    for case in base_query(user).filter(Case.status.in_(("draft", "open"))).all():
        comp = completeness(case)
        missing = [
            name
            for name, bucket in comp["buckets"].items()
            if bucket.get("applicable", True) and not bucket["ready"]
        ]
        if comp["percent"] < 80 or "arrest" in missing or "medical" in missing:
            io = case.assigned_io.full_name if case.assigned_io else "-"
            rows.append(
                {
                    "case": case,
                    "cr": case.display_cr,
                    "io": io,
                    "missing": ", ".join(missing[:4]) or "-",
                    "incident_at": case.incident_at,
                }
            )
    return rows


def counts_for_dashboard(user):
    open_cases = count_open(user)
    needing = 0
    for case in base_query(user).filter(Case.status.in_(("draft", "open"))).all():
        if not any(s.status == "confirmed" for s in case.sections.all()):
            needing += 1
    from app.services.document_service import docs_this_week

    return {
        "open_cases": open_cases,
        "documents_this_week": docs_this_week(user),
        "items_needing_sections": needing,
        "incomplete_queue": incomplete_queue(user),
        "remand_clock": remand_clock(user),
    }


def station_io_choices(station_id):
    if not station_id:
        return []
    return (
        User.query.filter(
            User.station_id == station_id,
            User.is_active.is_(True),
            User.role.in_(("io", "sho")),
        )
        .order_by(User.full_name)
        .all()
    )


def station_legal_choices(station_id):
    if not station_id:
        return []
    return (
        User.query.filter(
            User.station_id == station_id,
            User.is_active.is_(True),
            User.role == "legal",
        )
        .order_by(User.full_name)
        .all()
    )


def station_user_choices(station_id):
    if not station_id:
        return []
    return (
        User.query.filter(User.station_id == station_id, User.is_active.is_(True))
        .order_by(User.full_name)
        .all()
    )
