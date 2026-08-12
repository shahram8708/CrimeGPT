import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models import ApplicationSetting, Case, CaseSection, Notification, UsageCounter, User
from app.models.ai import AiInteraction, LegalSuggestion, SavedResult
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import can_confirm_sections, can_run_legal_intel, case_is_visible
from app.services.gemini_service import PLATFORM_DISCLAIMER, gemini_configured
from app.services.i18n import translate
from app.utils.formatting_utils import redact_sensitive


FOCUS_CHOICES = ("charging", "remand", "evidence")


def narrative_hash(narrative, language, focus, use_search):
    norm = " ".join((narrative or "").split()).lower()
    payload = f"{norm}|{(language or 'en').lower()}|{(focus or 'charging').lower()}|{1 if use_search else 0}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def station_for(user, case=None):
    if case is not None and getattr(case, "station_id", None):
        return case.station_id
    return getattr(user, "station_id", None)


def compact_case_facts(case):
    if case is None:
        return None
    from app.models.evidence import CaseDiaryEntry

    parties = []
    for p in case.live_parties():
        parties.append(
            {
                "role": p.role,
                "name": p.full_name,
                "age": p.age,
                "gender": p.gender,
            }
        )
    items = []
    for item in case.live_items():
        items.append({"description": item.description, "exhibit": item.exhibit_no})
    diary = []
    rows = (
        CaseDiaryEntry.query.filter_by(case_id=case.id)
        .order_by(CaseDiaryEntry.occurred_at.desc())
        .limit(8)
        .all()
    )
    for entry in rows:
        diary.append({"type": entry.entry_type, "text": (entry.body or "")[:400]})
    blob = json.dumps({"parties": parties, "items": items, "recent_diary": diary}, ensure_ascii=False)
    return redact_sensitive(blob)


def prepare_prompt_bundle(case, narrative):
    text = narrative or ""
    extra = None
    if case is not None:
        extra = compact_case_facts(case)
        combined = text + (extra or "")
        if len(combined) > 24000:
            text = text[:18000]
    return text, extra


def find_cache(station_id, digest):
    cutoff = utcnow() - timedelta(hours=24)
    q = LegalSuggestion.query.filter(
        LegalSuggestion.narrative_hash == digest,
        LegalSuggestion.created_at >= cutoff,
        LegalSuggestion.result_json.isnot(None),
    )
    if station_id is None:
        q = q.filter(LegalSuggestion.station_id.is_(None))
    else:
        q = q.filter(LegalSuggestion.station_id == station_id)
    return q.order_by(LegalSuggestion.created_at.desc()).first()


def _soft_limit():
    raw = ApplicationSetting.get("gemini_daily_soft_limit", "40")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def today_gemini_calls(station_id=None, platform=False):
    today = date.today()
    if platform:
        total = sum(r.gemini_calls or 0 for r in UsageCounter.query.filter_by(day=today).all())
        extra = ApplicationSetting.get(f"gemini_calls_platform_{today.isoformat()}", "0")
        try:
            total += int(extra or 0)
        except (TypeError, ValueError):
            pass
        return total
    if not station_id:
        extra = ApplicationSetting.get(f"gemini_calls_platform_{today.isoformat()}", "0")
        try:
            return int(extra or 0)
        except (TypeError, ValueError):
            return 0
    return sum(
        r.gemini_calls or 0 for r in UsageCounter.query.filter_by(station_id=station_id, day=today).all()
    )


def quota_reached(user, case=None):
    from app.services.entitlement_service import monthly_exhausted

    if monthly_exhausted(user, case):
        return True
    limit = _soft_limit()
    if limit <= 0:
        return False
    sid = station_for(user, case)
    if getattr(user, "role", None) == "super_admin" and not sid:
        return today_gemini_calls(platform=True) >= limit
    return today_gemini_calls(station_id=sid, platform=False) >= limit


def increment_gemini_calls(user, case=None):
    today = date.today()
    sid = station_for(user, case)
    if sid:
        row = UsageCounter.query.filter_by(station_id=sid, user_id=user.id, day=today).first()
        if row is None:
            row = UsageCounter(station_id=sid, user_id=user.id, day=today, gemini_calls=0)
            db.session.add(row)
        row.gemini_calls = (row.gemini_calls or 0) + 1
        return
    key = f"gemini_calls_platform_{today.isoformat()}"
    current = ApplicationSetting.get(key, "0")
    try:
        n = int(current or 0)
    except (TypeError, ValueError):
        n = 0
    ApplicationSetting.set(key, str(n + 1))


def parsed_result(suggestion):
    if not suggestion or not suggestion.result_json:
        return None
    try:
        return json.loads(suggestion.result_json)
    except (TypeError, ValueError):
        return None


def can_access_intel_role(user):
    return can_run_legal_intel(user, require_key=False)


def can_view_suggestion(user, suggestion):
    if not user or not getattr(user, "is_authenticated", False) or suggestion is None:
        return False
    if user.role in ("super_admin", "admin"):
        return True
    if suggestion.user_id == user.id:
        return True
    if suggestion.case_id and suggestion.case:
        return case_is_visible(user, suggestion.case)
    owner = suggestion.user
    if user.station_id and owner and owner.station_id == user.station_id:
        return user.role in ("writer", "io", "sho", "legal", "admin")
    return False


def can_apply_intel(user, case=None):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.role == "writer":
        return False
    if case is not None and case.is_locked and user.role != "super_admin":
        return False
    return user.role in ("io", "sho", "legal", "admin", "super_admin")


def apply_confirms(user):
    return getattr(user, "role", None) in ("io", "sho", "super_admin")


def last_run_for_case(case):
    if case is None:
        return None
    return (
        LegalSuggestion.query.filter(
            LegalSuggestion.case_id == case.id, LegalSuggestion.result_json.isnot(None)
        )
        .order_by(LegalSuggestion.created_at.desc())
        .first()
    )


def enqueue_legal_intel(user, narrative, language="en", focus="charging", use_search=True, case=None):
    from app.services.task_service import enqueue_job
    from app.tasks.ai_tasks import run_legal_intel

    if not can_access_intel_role(user):
        raise PermissionError("forbidden")
    if not gemini_configured():
        raise RuntimeError("not_configured")
    if not user.disclaimer_accepted_at:
        raise RuntimeError("disclaimer")
    snap = (narrative or "").strip()
    if len(snap) < 50:
        raise ValueError("short")
    if len(snap) > 20000:
        snap = snap[:20000]
    focus = focus if focus in FOCUS_CHOICES else "charging"
    language = language if language in ("en", "hi", "gu") else "en"
    digest = narrative_hash(snap, language, focus, bool(use_search))
    cached = find_cache(station_for(user, case), digest)
    if quota_reached(user, case) and cached is None:
        raise RuntimeError("quota")
    row = LegalSuggestion(
        case_id=case.id if case else None,
        user_id=user.id,
        station_id=station_for(user, case),
        narrative_hash=digest,
        narrative_snapshot=snap,
        language=language,
        focus=focus,
        use_search=bool(use_search),
    )
    db.session.add(row)
    db.session.commit()
    job = enqueue_job(
        user,
        "crimegpt.legal_intel",
        run_legal_intel,
        extra={"suggestion_id": row.id, "user_id": user.id},
        case_id=case.id if case else None,
    )
    row.job_id = job.id
    db.session.commit()
    return job, row


def record_interaction(user, suggestion, job, success, result=None, error_class=None, cached=False):
    model = current_app.config.get("GEMINI_MODEL") or "gemini-2.5-flash"
    prompt_chars = len(suggestion.narrative_snapshot or "") if suggestion else 0
    response_chars = 0
    in_tok = out_tok = latency = None
    if result:
        response_chars = len(result.get("raw_text") or "")
        in_tok = result.get("input_tokens")
        out_tok = result.get("output_tokens")
        latency = result.get("latency_ms")
    row = AiInteraction(
        user_id=user.id if user else suggestion.user_id,
        case_id=suggestion.case_id if suggestion else None,
        job_id=job.id if job else None,
        purpose="legal_intel",
        model=model,
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=latency,
        success=bool(success),
        error_class=("cache" if cached else error_class),
    )
    db.session.add(row)


def save_completed(user, suggestion, job, normalized, cached=False):
    suggestion.result_json = json.dumps(normalized, ensure_ascii=False)
    suggestion.overall_confidence = normalized.get("overall_confidence") or 0
    cr = suggestion.case.display_cr if suggestion.case else "standalone"
    title = f"Legal Intelligence - {cr}"
    existing = SavedResult.query.filter_by(
        user_id=user.id, ref_table="legal_suggestions", ref_id=suggestion.id
    ).first()
    if existing is None:
        db.session.add(
            SavedResult(
                user_id=user.id,
                case_id=suggestion.case_id,
                result_type="intel",
                ref_table="legal_suggestions",
                ref_id=suggestion.id,
                title=title[:200],
            )
        )
    if job:
        job.result_ref_table = "legal_suggestions"
        job.result_ref_id = suggestion.id
    note = Notification(
        user_id=user.id,
        title="Legal Intelligence ready" if not cached else "Legal Intelligence ready (cached)",
        body="Structured suggestions are ready for review. They are not charges.",
        link_path=f"/results/legal-intel/{suggestion.uuid}",
    )
    db.session.add(note)


def apply_selected(user, suggestion, keys):
    case = suggestion.case if suggestion else None
    if suggestion is None or case is None:
        raise RuntimeError("no_case")
    if not can_view_suggestion(user, suggestion):
        raise PermissionError("hidden")
    if not can_apply_intel(user, case):
        raise PermissionError("forbidden")
    data = parsed_result(suggestion) or {}
    if data.get("refused"):
        raise RuntimeError("refused")
    wanted = set(keys or [])
    catalog = {}
    for family_key, family in (("bns", "BNS"), ("bnss", "BNSS"), ("bsa", "BSA")):
        for idx, row in enumerate(data.get(family_key) or []):
            catalog[f"{family_key}-{idx}"] = (family, row)
    applied = 0
    already = 0
    confirmed = apply_confirms(user)
    source = "gemini-recommend" if user.role == "legal" else "gemini"
    for key in wanted:
        hit = catalog.get(key)
        if not hit:
            continue
        family, row = hit
        if not row.get("applyable"):
            continue
        code = (row.get("code") or "").strip()
        if not code:
            continue
        dup = CaseSection.query.filter_by(
            case_id=case.id, statute_family=family, code=code, status="confirmed"
        ).first()
        if dup:
            already += 1
            continue
        sec = CaseSection(
            case_id=case.id,
            statute_family=family,
            code=code,
            title=(row.get("title") or "")[:240] or None,
            rationale=row.get("rationale") or None,
            status="confirmed" if confirmed else "suggested",
            source=source,
            confidence=row.get("confidence"),
            suggestion_id=suggestion.id,
        )
        if confirmed:
            sec.confirmed_by_id = user.id
            sec.confirmed_at = utcnow()
        db.session.add(sec)
        applied += 1
    db.session.commit()
    action = "section.confirmed" if confirmed else "section.recommended"
    write_audit(
        action,
        object_type="legal_suggestion",
        object_id=suggestion.uuid,
        actor=user,
        station_id=case.station_id,
        case_id=case.id,
        meta={
            "applied": applied,
            "already": already,
            "platform_override": user.role == "super_admin",
        },
    )
    return applied, already


def link_suggestion_to_case(user, suggestion, case):
    if suggestion.case_id:
        return suggestion
    if not case_is_visible(user, case):
        raise PermissionError("hidden")
    suggestion.case_id = case.id
    if suggestion.station_id is None:
        suggestion.station_id = case.station_id
    saved = SavedResult.query.filter_by(
        ref_table="legal_suggestions", ref_id=suggestion.id, user_id=user.id
    ).first()
    if saved:
        saved.case_id = case.id
        saved.title = f"Legal Intelligence - {case.display_cr}"[:200]
    db.session.commit()
    return suggestion
