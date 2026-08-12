import json

from app.services.gemini_service import PLATFORM_DISCLAIMER


def deterministic_compare(left_ctx, right_ctx):
    left_ctx = left_ctx or {}
    right_ctx = right_ctx or {}
    changed = []
    risks = []

    def pair(label, lv, rv):
        ls = "" if lv is None else str(lv)
        rs = "" if rv is None else str(rv)
        if ls != rs:
            changed.append({"label": label, "left": ls, "right": rs})

    pair("CR / FIR", left_ctx.get("cr"), right_ctx.get("cr"))
    pair("Place", left_ctx.get("place"), right_ctx.get("place"))
    pair("Court", left_ctx.get("court_name"), right_ctx.get("court_name"))
    pair("Prayer / grounds", left_ctx.get("grounds"), right_ctx.get("grounds"))
    lacc = left_ctx.get("accused") or []
    racc = right_ctx.get("accused") or []
    n = max(len(lacc), len(racc))
    for i in range(n):
        la = lacc[i] if i < len(lacc) else {}
        ra = racc[i] if i < len(racc) else {}
        pair(f"Accused {i + 1} name", la.get("name"), ra.get("name"))
        pair(f"Accused {i + 1} guardian", la.get("guardian"), ra.get("guardian"))
        if (la.get("guardian") or "") != (ra.get("guardian") or ""):
            risks.append(
                {
                    "severity": "high",
                    "label": "Guardian / father's name changed",
                    "detail": f"{la.get('guardian') or '-'} → {ra.get('guardian') or '-'}",
                }
            )
    lsec = {f"{s.get('family')} {s.get('code')}" for s in (left_ctx.get("sections") or [])}
    rsec = {f"{s.get('family')} {s.get('code')}" for s in (right_ctx.get("sections") or [])}
    section_changes = {
        "added": sorted(rsec - lsec),
        "removed": sorted(lsec - rsec),
    }
    litems = left_ctx.get("items") or []
    ritems = right_ctx.get("items") or []
    for i in range(max(len(litems), len(ritems))):
        li = litems[i] if i < len(litems) else {}
        ri = ritems[i] if i < len(ritems) else {}
        pair(f"Item {i + 1} qty", li.get("quantity"), ri.get("quantity"))
        pair(f"Item {i + 1} description", li.get("description"), ri.get("description"))
    return {
        "changed_fields": changed,
        "added_facts": [],
        "removed_facts": [],
        "section_changes": section_changes,
        "risk_notes": risks,
        "overall_summary": f"{len(changed)} field(s) differ.",
        "confidence": 100 if changed or risks else 80,
        "disclaimer": PLATFORM_DISCLAIMER,
        "limitations": ["Deterministic pool-field compare. Not a legal opinion."],
        "source": "deterministic",
    }


import difflib


def compute_text_diff(left_text, right_text):
    left_text = (left_text or "").strip()
    right_text = (right_text or "").strip()
    if not left_text and not right_text:
        return {
            "has_diff": False,
            "summary": "Both documents are empty.",
            "diff_lines": [],
            "stats": {"added": 0, "removed": 0, "unchanged": 0, "similarity": 100.0},
        }

    left_lines = [l for l in left_text.splitlines() if l.strip()]
    right_lines = [r for r in right_text.splitlines() if r.strip()]

    matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
    ratio = round(matcher.ratio() * 100, 1)

    diff_lines = []
    added_cnt = 0
    removed_cnt = 0
    unchanged_cnt = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in left_lines[i1:i2]:
                unchanged_cnt += 1
                if len(diff_lines) < 120:
                    diff_lines.append({"tag": "equal", "text": line})
        elif tag == "replace":
            for line in left_lines[i1:i2]:
                removed_cnt += 1
                if len(diff_lines) < 120:
                    diff_lines.append({"tag": "delete", "text": line})
            for line in right_lines[j1:j2]:
                added_cnt += 1
                if len(diff_lines) < 120:
                    diff_lines.append({"tag": "insert", "text": line})
        elif tag == "delete":
            for line in left_lines[i1:i2]:
                removed_cnt += 1
                if len(diff_lines) < 120:
                    diff_lines.append({"tag": "delete", "text": line})
        elif tag == "insert":
            for line in right_lines[j1:j2]:
                added_cnt += 1
                if len(diff_lines) < 120:
                    diff_lines.append({"tag": "insert", "text": line})

    has_diff = added_cnt > 0 or removed_cnt > 0
    summary = f"{ratio}% similarity. {added_cnt} line(s) added, {removed_cnt} line(s) removed."

    return {
        "has_diff": has_diff,
        "similarity": ratio,
        "summary": summary,
        "stats": {"added": added_cnt, "removed": removed_cnt, "unchanged": unchanged_cnt, "similarity": ratio},
        "diff_lines": diff_lines,
    }


def deterministic_identify(ctx, doc_type=None):
    ctx = ctx or {}
    blocks = []
    flags = {
        "missing_second_panch": False,
        "empty_prayer": False,
        "no_confirmed_sections": False,
    }
    panch = ctx.get("panch") or []
    if len(panch) < 2:
        flags["missing_second_panch"] = True
        blocks.append(
            {
                "label": "panch_details",
                "quote": f"{len(panch)} panch recorded",
                "plain_language": "A seizure or panchanama paper normally needs two panch names.",
                "defect": True,
                "defect_message": "Missing second panch",
            }
        )
    else:
        blocks.append(
            {
                "label": "panch_details",
                "quote": ", ".join(p.get("name") or "" for p in panch[:2]),
                "plain_language": "Two panch names are present.",
                "defect": False,
                "defect_message": "",
            }
        )
    prayer = (ctx.get("ai") or {}).get("prayer") or ctx.get("grounds") or ""
    if doc_type in ("remand_pc", "purvani_chargesheet", "lers_request") and not str(prayer).strip():
        flags["empty_prayer"] = True
        blocks.append(
            {
                "label": "prayer",
                "quote": "",
                "plain_language": "The prayer or request line is empty.",
                "defect": True,
                "defect_message": "Empty prayer",
            }
        )
    if not (ctx.get("sections") or []):
        flags["no_confirmed_sections"] = True
        blocks.append(
            {
                "label": "sections_invoked",
                "quote": "",
                "plain_language": "No confirmed sections are printed.",
                "defect": True,
                "defect_message": "No confirmed sections",
            }
        )
    if ctx.get("accused"):
        blocks.append(
            {
                "label": "parties",
                "quote": ", ".join(a.get("name") or "" for a in ctx["accused"]),
                "plain_language": "Accused names taken from the case pool.",
                "defect": False,
                "defect_message": "",
            }
        )
    if ctx.get("items"):
        blocks.append(
            {
                "label": "seized_items",
                "quote": "; ".join(i.get("description") or "" for i in ctx["items"][:6]),
                "plain_language": "Exhibits listed from the case pool.",
                "defect": False,
                "defect_message": "",
            }
        )
    return {
        "blocks": blocks,
        "flags": flags,
        "disclaimer": PLATFORM_DISCLAIMER,
        "source": "deterministic",
    }


def extract_generated_text(ctx):
    if not ctx:
        return ""
    parts = [str(ctx.get("doc_title") or ""), str(ctx.get("cr") or ""), str(ctx.get("gist") or "")]
    for a in ctx.get("accused") or []:
        parts.append(f"{a.get('name')} guardian {a.get('guardian')}")
    for s in ctx.get("sections") or []:
        parts.append(f"{s.get('family')} {s.get('code')}")
    return "\n".join(p for p in parts if p)


def extract_file_text(data, mime, filename=""):
    text = ""
    name = (filename or "").lower()
    mime = mime or ""
    if "word" in mime or name.endswith(".docx") or (data and data[:2] == b"PK"):
        try:
            from io import BytesIO

            from docx import Document

            doc = Document(BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs if p.text)
        except Exception:
            text = ""
    if (not text or len(text) < 20) and (mime == "application/pdf" or (data and data[:4] == b"%PDF")):
        try:
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            pass
    return text or ""
