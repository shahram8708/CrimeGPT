from pathlib import Path

import yaml

from app.models.document import GeneratedDocument

PLAYBOOK_DIR = Path(__file__).resolve().parent.parent / "data" / "playbooks"
KNOWN = ("hurt", "theft", "house_trespass", "intimidation", "accident", "ndps_adjacent", "other")

DEEP_KEYS = {
    "medical": "medical",
    "arrests": "arrests",
    "arrest": "arrests",
    "items": "items",
    "sections": "sections",
    "diary": "diary",
    "evidence": "evidence",
    "parties": "parties",
    "edit": "edit",
    "documents.remand_pc": "documents.remand_pc",
    "documents.medical_letter": "documents.medical_letter",
    "documents.seizure_receipt": "documents.seizure_receipt",
}


def load_playbook(category):
    key = category if category in KNOWN else "other"
    path = PLAYBOOK_DIR / f"{key}.yaml"
    if not path.is_file():
        path = PLAYBOOK_DIR / "other.yaml"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("category", key)
    data.setdefault("expected_documents", [])
    data.setdefault("expected_process", [])
    data.setdefault("expected_elements", [])
    data.setdefault("common_gaps", [])
    return data


def case_graph(case):
    from app.models.evidence import CaseDiaryEntry, EvidenceItem

    parties = [{"role": p.role, "name": p.full_name, "juvenile": p.is_juvenile} for p in case.live_parties()]
    items = [{"description": i.description, "qty": i.quantity, "exhibit": i.exhibit_no} for i in case.live_items()]
    arrests = [
        {
            "accused": a.accused.full_name if a.accused else "",
            "rights_informed": a.rights_informed,
            "produced_before": a.produced_before or "",
        }
        for a in case.live_arrests()
    ]
    med = case.medical
    medical = {
        "hospital_name": (med.hospital_name or "").strip() if med else "",
        "mlc_no": (med.mlc_no or "").strip() if med else "",
        "department": (med.department or "").strip() if med else "",
    }
    sections = [
        {"family": s.statute_family, "code": s.code, "status": s.status}
        for s in case.sections.all()
    ]
    docs = [
        {"type": d.doc_type, "status": d.status}
        for d in GeneratedDocument.query.filter_by(case_id=case.id).all()
    ]
    diary_n = CaseDiaryEntry.query.filter_by(case_id=case.id).count()
    ev_n = EvidenceItem.query.filter_by(case_id=case.id, deleted_at=None).count()
    return {
        "category": case.category,
        "cr": case.display_cr,
        "place": case.place_of_occurrence,
        "narrative_len": len((case.narrative or "").strip()),
        "parties": parties,
        "items": items,
        "arrests": arrests,
        "medical": medical,
        "sections": sections,
        "generated_docs": docs,
        "diary_count": diary_n,
        "evidence_count": ev_n,
        "panch_count": len(case.live_parties("panch")),
        "complainant": bool(case.live_parties("complainant") or case.live_parties("injured")),
    }


def _card(severity, label, message, deep_link=None, source="playbook"):
    return {
        "severity": severity or "medium",
        "label": label,
        "message": message,
        "deep_link": deep_link,
        "source": source,
    }


def deterministic_gaps(case, playbook=None):
    playbook = playbook or load_playbook(case.category)
    graph = case_graph(case)
    cards = []
    med = graph["medical"]
    for item in playbook.get("expected_process") or []:
        field = item.get("field")
        label = item.get("label") or field or "Check"
        sev = item.get("severity") or "medium"
        link = item.get("deep_link")
        if field == "hospital_name" and not med.get("hospital_name"):
            cards.append(_card("high", label, "Hospital name is empty on the medical card.", link))
        elif field == "mlc_no" and not med.get("mlc_no"):
            cards.append(_card(sev, label, "MLC number is empty.", link))
        elif field == "rights_informed":
            arrests = graph["arrests"]
            if arrests and not all(a.get("rights_informed") for a in arrests):
                cards.append(_card("high", label, "At least one arrest has rights_informed unchecked.", link))
        elif field == "items" and not graph["items"]:
            cards.append(_card(sev, label, "No seized item is on the pool.", link))
        elif field == "panch" and graph["panch_count"] < 2:
            cards.append(_card("high", label, "Fewer than two panch names.", link))
        elif field == "complainant" and not graph["complainant"]:
            cards.append(_card("high", label, "No complainant or injured party.", link))
        elif field == "narrative" and graph["narrative_len"] < 50:
            cards.append(_card("high", label, "Narrative is shorter than 50 characters.", link))
        elif field == "sections" and not any(s.get("status") == "confirmed" for s in graph["sections"]):
            cards.append(_card(sev, label, "No confirmed section on the pool.", link))
        elif field == "place" and len((case.place_of_occurrence or "").strip()) < 5:
            cards.append(_card(sev, label, "Place of occurrence is too short.", link))
    have = {d["type"] for d in graph["generated_docs"] if d["status"] in ("completed", "final")}
    for dtype in playbook.get("expected_documents") or []:
        if dtype not in have:
            cards.append(
                _card(
                    "medium",
                    f"Missing generated paper: {dtype}",
                    "The playbook expects this paper. Generate it from the documents hub when the pool is ready.",
                    f"documents.{dtype}" if dtype else "documents",
                )
            )
    order = {"high": 0, "medium": 1, "low": 2}
    cards.sort(key=lambda c: order.get(c["severity"], 9))
    return cards


def merge_gap_cards(det, model_cards):
    seen = {(c.get("label") or "").lower() for c in det}
    out = list(det)
    for card in model_cards or []:
        if not isinstance(card, dict):
            continue
        label = (card.get("label") or card.get("title") or "").strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        out.append(
            _card(
                card.get("severity") or "medium",
                label,
                card.get("message") or card.get("why") or "",
                card.get("deep_link") or card.get("suggested_deep_link"),
                source="ai",
            )
        )
    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda c: order.get(c["severity"], 9))
    return out


def map_deep_link(case, key):
    if not case or not key:
        return None
    token = str(key).strip()
    if token not in DEEP_KEYS and not token.startswith("documents."):
        return None
    uuid = case.uuid
    if token in ("medical",):
        return f"/cases/{uuid}/medical"
    if token in ("arrests", "arrest"):
        return f"/cases/{uuid}/arrests"
    if token == "items":
        return f"/cases/{uuid}/items"
    if token == "sections":
        return f"/cases/{uuid}/sections"
    if token == "diary":
        return f"/cases/{uuid}/diary"
    if token == "evidence":
        return f"/cases/{uuid}/evidence"
    if token == "parties":
        return f"/cases/{uuid}/parties"
    if token == "edit":
        return f"/cases/{uuid}/edit"
    if token.startswith("documents."):
        dtype = token.split(".", 1)[1]
        return f"/cases/{uuid}/documents/generate?type={dtype}"
    if token == "documents":
        return f"/cases/{uuid}/documents"
    return None
