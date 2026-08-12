import hashlib
import hmac
import re
import secrets
from urllib.parse import urlparse

TRIVIAL_PASSWORDS = {
    "password",
    "password123",
    "password1234",
    "123456789012",
    "qwertyuiopas",
    "adminadmin12",
    "letmeinletme",
    "changeme1234",
    "crimegpt1234",
    "superadmin12",
    "abcdefghijkl",
    "iloveyou1234",
}


def hash_password_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_url_token():
    token = secrets.token_urlsafe(32)
    return token, hash_password_token(token)


def token_hash(raw=None):
    if raw is None:
        raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_equals(a, b):
    if a is None or b is None:
        return False
    return hmac.compare_digest(str(a), str(b))


def password_errors(password):
    errors = []
    if not password or len(password) < 12:
        errors.append("Password must be at least 12 characters.")
    if password and password.isdigit():
        errors.append("Password cannot be entirely numeric.")
    if password and password.lower() in TRIVIAL_PASSWORDS:
        errors.append("This password is too common.")
    if password and re.fullmatch(r"(.)\1{11,}", password or ""):
        errors.append("Password cannot be a repeated character.")
    return errors


def password_strength(password):
    if not password:
        return 0
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r"[A-Z]", password) and re.search(r"[a-z]", password):
        score += 1
    if re.search(r"\d", password) and re.search(r"[^A-Za-z0-9]", password):
        score += 1
    if password.isdigit() or password.lower() in TRIVIAL_PASSWORDS:
        score = min(score, 1)
    if re.fullmatch(r"(.)\1{7,}", password):
        score = min(score, 1)
    return max(0, min(4, score))


def is_strong_password(password):
    return not password_errors(password)


def safe_next_url(target, fallback="/dashboard"):
    if not target:
        return fallback
    target = str(target).strip()
    if not target.startswith("/") or target.startswith("//"):
        return fallback
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return fallback
    if "\\" in target:
        return fallback
    return target
