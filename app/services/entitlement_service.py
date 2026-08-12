from calendar import monthrange
from datetime import date
from pathlib import Path

from app.extensions import cache, db
from app.models import ApplicationSetting, Case, PoliceStation, UsageCounter, User
from app.models.evidence import EvidenceItem

PILOT_DOC_TYPES = ("medical_letter", "seizure_receipt", "remand_pc", "face_identification")
PAID_DOC_TYPES = ("purvani_chargesheet", "court_custody", "accused_panchanama")
PLAN_DEFAULTS = {
    "pilot": {
        "monthly_gemini_allowance": 40,
        "max_users": 8,
        "evidence_quota_bytes": 2147483648,
        "allow_all_document_types": False,
        "allow_legal_review": False,
        "allow_sho_queue": False,
        "allow_station_fts": False,
        "allow_cctns_demo": False,
        "allow_audit_export": False,
    },
    "station": {
        "monthly_gemini_allowance": 200,
        "max_users": 25,
        "evidence_quota_bytes": 10737418240,
        "allow_all_document_types": True,
        "allow_legal_review": True,
        "allow_sho_queue": True,
        "allow_station_fts": True,
        "allow_cctns_demo": True,
        "allow_audit_export": True,
    },
    "zone": {
        "monthly_gemini_allowance": 600,
        "max_users": 80,
        "evidence_quota_bytes": 32212254720,
        "allow_all_document_types": True,
        "allow_legal_review": True,
        "allow_sho_queue": True,
        "allow_station_fts": True,
        "allow_cctns_demo": True,
        "allow_audit_export": True,
    },
    "commissionerate": {
        "monthly_gemini_allowance": 2000,
        "max_users": 250,
        "evidence_quota_bytes": 107374182400,
        "allow_all_document_types": True,
        "allow_legal_review": True,
        "allow_sho_queue": True,
        "allow_station_fts": True,
        "allow_cctns_demo": True,
        "allow_audit_export": True,
    },
}


def unlock_demo_station(station):
    if station is None:
        return
    station.plan_key = "station"
    station.monthly_gemini_allowance = 400
    station.extra_credits = 100
    station.max_users = 40
    station.evidence_quota_bytes = 10737418240
    station.allow_all_document_types = True
    station.allow_legal_review = True
    station.allow_sho_queue = True
    station.allow_station_fts = True
    station.allow_cctns_demo = True
    station.allow_audit_export = True


def station_for(user, case=None):
    if case is not None and getattr(case, "station", None):
        return case.station
    if case is not None and getattr(case, "station_id", None):
        return db.session.get(PoliceStation, case.station_id)
    if user and getattr(user, "station", None):
        return user.station
    if user and getattr(user, "station_id", None):
        return db.session.get(PoliceStation, user.station_id)
    return None


def flag(station, name, default=False):
    if station is None:
        return default
    return bool(getattr(station, name, default))


def monthly_used(station_id, day=None):
    if not station_id:
        return 0
    day = day or date.today()
    start = date(day.year, day.month, 1)
    end = date(day.year, day.month, monthrange(day.year, day.month)[1])
    rows = UsageCounter.query.filter(
        UsageCounter.station_id == station_id,
        UsageCounter.day >= start,
        UsageCounter.day <= end,
    ).all()
    return sum(r.gemini_calls or 0 for r in rows)


def monthly_cap(station):
    if station is None:
        return 40
    return int(station.monthly_gemini_allowance or 0) + int(station.extra_credits or 0)


def monthly_remaining(station, day=None):
    if station is None:
        return 0
    return max(0, monthly_cap(station) - monthly_used(station.id, day))


def daily_limit():
    raw = ApplicationSetting.get("gemini_daily_soft_limit", "40")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 40


def daily_used(station_id, day=None):
    from app.services.intel_service import today_gemini_calls

    return today_gemini_calls(station_id=station_id)


def monthly_exhausted(user, case=None):
    if user and getattr(user, "role", None) == "super_admin":
        return False
    station = station_for(user, case)
    if station is None:
        return False
    return monthly_used(station.id) >= monthly_cap(station)


def ai_blocked(user, case=None):
    from app.services.intel_service import quota_reached

    if monthly_exhausted(user, case):
        return True
    return quota_reached(user, case)


def doc_type_allowed(user, case, doc_type):
    if user and getattr(user, "role", None) == "super_admin":
        return True
    if doc_type not in PAID_DOC_TYPES:
        return True
    station = station_for(user, case)
    return flag(station, "allow_all_document_types", False)


def legal_review_allowed(user, case=None):
    if user and getattr(user, "role", None) == "super_admin":
        return True
    return flag(station_for(user, case), "allow_legal_review", False)


def cctns_allowed(user, case=None):
    if user and getattr(user, "role", None) == "super_admin":
        return True
    return flag(station_for(user, case), "allow_cctns_demo", False)


def audit_export_allowed(user, station=None):
    if user and getattr(user, "role", None) in ("super_admin", "admin"):
        return True
    target = station or station_for(user)
    return flag(target, "allow_audit_export", False)


def evidence_bytes(station_id):
    if not station_id:
        return 0
    ids = [c.id for c in Case.query.filter_by(station_id=station_id, deleted_at=None).all()]
    if not ids:
        return 0
    return sum(
        r.size_bytes or 0
        for r in EvidenceItem.query.filter(EvidenceItem.case_id.in_(ids), EvidenceItem.deleted_at.is_(None)).all()
    )


def folder_bytes(path):
    root = Path(path)
    if not root.is_dir():
        return 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def snapshot(user, case=None):
    station = station_for(user, case)
    sid = station.id if station else None
    used_m = monthly_used(sid) if sid else 0
    cap = monthly_cap(station) if station else 0
    remain = max(0, cap - used_m)
    dlim = daily_limit()
    dused = daily_used(sid) if sid else 0
    ev_used = evidence_bytes(sid) if sid else 0
    ev_cap = int(station.evidence_quota_bytes or 0) if station else 0
    ev_pct = int(round(100 * ev_used / ev_cap)) if ev_cap else 0
    blocked = ai_blocked(user, case)
    return {
        "station": station,
        "plan": (station.plan_key if station else "pilot") or "pilot",
        "monthly_used": used_m,
        "monthly_cap": cap,
        "monthly_remaining": remain,
        "daily_used": dused,
        "daily_limit": dlim,
        "daily_remaining": max(0, dlim - dused) if dlim > 0 else None,
        "ai_blocked": blocked,
        "evidence_used": ev_used,
        "evidence_cap": ev_cap,
        "evidence_pct": ev_pct,
        "evidence_hot": ev_cap > 0 and ev_pct >= 80,
        "allow_all_docs": flag(station, "allow_all_document_types", False) or (user and user.role == "super_admin"),
        "allow_review": legal_review_allowed(user, case),
        "allow_cctns": cctns_allowed(user, case),
    }


def letterhead(station):
    if station is None:
        return {"name": "CrimeGPT", "line2": "", "line3": "", "logo": None}
    key = f"letterhead:{station.id}"
    hit = cache.get(key)
    if hit:
        return hit
    data = {
        "name": station.name,
        "line2": station.letterhead_line2 or "",
        "line3": station.letterhead_line3 or "",
        "logo": station.logo_path,
        "code": station.code,
    }
    cache.set(key, data, timeout=300)
    return data


def drop_letterhead(station_id):
    cache.delete(f"letterhead:{station_id}")
