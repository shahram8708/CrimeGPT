import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

IST = ZoneInfo("Asia/Kolkata")
PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
STATUTE_RE = re.compile(
    r"^(BNS|BNSS|BSA|IPC|CrPC|IEA)?\s*(\d{1,4}(?:\s*\([0-9A-Za-z]+\))*(?:\s*/\s*\d{1,4})?)$",
    re.IGNORECASE,
)
FAMILY_PREFIX = {
    "BNS": "BNS",
    "BNSS": "BNSS",
    "BSA": "BSA",
    "IPC": "IPC",
    "CRPC": "CrPC",
    "IEA": "IEA",
}


def to_ist(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def format_ist(dt, fmt="%d %b %Y, %H:%M"):
    local = to_ist(dt)
    if local is None:
        return ""
    return local.strftime(fmt)


def format_ist_long(dt):
    return format_ist(dt, "%d %B %Y, %H:%M IST")


def greeting_for_hour(hour):
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def nl2br(text):
    if text is None:
        return ""
    escaped = escape(str(text))
    return Markup(escaped.replace("\n", Markup("<br>\n")))


def extract_json(text):
    if not text or not str(text).strip():
        raise ValueError("Empty model output")
    raw = str(text).strip()
    raw = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    raise ValueError("Model returned unreadable output")


def redact_sensitive(text):
    if not text:
        return text
    out = PHONE_RE.sub("[phone]", str(text))
    out = AADHAAR_RE.sub("[id]", out)
    return out


_STATUTE_STRIP_RE = re.compile(
    r"^(?:section|sec\.?|s\.?|dhara|धारा)\s+", re.IGNORECASE
)
_STATUTE_TAIL_RE = re.compile(
    r"\s+(?:of\s+)?(?:the\s+)?(?:BNS|BNSS|BSA|IPC|CrPC|IEA)(?:\s+\d{4})?\s*$", re.IGNORECASE
)


def statute_token_ok(code, family=None):
    token = (code or "").strip()
    if not token:
        return False
    token = _STATUTE_STRIP_RE.sub("", token)
    token = _STATUTE_TAIL_RE.sub("", token).strip()
    if not token:
        return False
    match = STATUTE_RE.match(token)
    if not match:
        return bool(family and re.match(r"^\d{1,4}(?:\s*\([0-9A-Za-z]+\))*$", token))
    prefix = (match.group(1) or "").upper()
    if not prefix:
        return bool(family)
    if family and prefix not in (str(family).upper(), str(family).upper().replace("CRPC", "CRPC")):
        if prefix == "CRPC" and str(family).upper() == "CRPC":
            return True
        if prefix != str(family).upper():
            return False
    return True


def sanitize_error(exc):
    text = str(exc) if exc else "Unexpected error"
    text = text.replace("\n", " ").strip()
    if len(text) > 240:
        text = text[:237] + "..."
    lowered = text.lower()
    for secretish in ("password", "secret", "api_key", "token", "broker"):
        if secretish in lowered:
            return "A background task failed. Check server logs."
    return text
