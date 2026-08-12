import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

UPLOAD_MAX_BYTES = 15 * 1024 * 1024
ALLOWED_EXT = {"pdf", "jpg", "jpeg", "png"}
EXT_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
BLOCKED_EXT = {"html", "htm", "svg", "js", "xml", "xhtml", "php", "exe"}


def ensure_directories(app=None):
    root = Path(app.root_path).resolve().parent if app else Path.cwd()
    instance = Path(app.instance_path) if app else root / "instance"
    upload = Path(app.config["UPLOAD_FOLDER"]) if app else root / "uploads"
    generated = Path(app.config["GENERATED_FOLDER"]) if app else root / "generated"
    if not upload.is_absolute():
        upload = root / upload
    if not generated.is_absolute():
        generated = root / generated
    for path in (instance, upload, generated):
        path.mkdir(parents=True, exist_ok=True)
    return instance, upload, generated


def resolved_upload_root():
    root = Path(current_app.config["UPLOAD_FOLDER"])
    if not root.is_absolute():
        root = Path(current_app.root_path).resolve().parent / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def resolved_generated_root():
    root = Path(current_app.config["GENERATED_FOLDER"])
    if not root.is_absolute():
        root = Path(current_app.root_path).resolve().parent / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def sniff_mime(data):
    if not data or len(data) < 5:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:2] == b"PK":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return None


def validate_upload(filename, data, allow_docx=False):
    if not filename or data is None:
        return None, "Choose a file."
    if len(data) > UPLOAD_MAX_BYTES:
        return None, "This file is over 15 MB. Limit is 15 MB."
    name = secure_filename(filename) or "upload"
    lower = name.lower()
    parts = lower.split(".")
    allowed = set(ALLOWED_EXT)
    if allow_docx:
        allowed.add("docx")
    if len(parts) < 2:
        return None, "File must have an extension: pdf, jpg, jpeg, png" + (", or docx." if allow_docx else ".")
    if len(parts) > 2:
        return None, "Double extensions are not allowed."
    ext = parts[-1]
    if ext in BLOCKED_EXT:
        return None, "That file type is not allowed."
    if ext not in allowed:
        return None, "Only pdf, jpg, jpeg, and png are accepted." if not allow_docx else "Only pdf, docx, jpg, jpeg, and png are accepted."
    sniffed = sniff_mime(data)
    expected = EXT_MIME[ext]
    if sniffed != expected:
        return None, "File content does not match the extension."
    if ext in ("jpg", "jpeg", "png"):
        try:
            from io import BytesIO

            from PIL import Image

            img = Image.open(BytesIO(data))
            img.verify()
        except Exception:
            return None, "The image could not be verified."
    stored = f"{uuid.uuid4().hex}.{'jpg' if ext == 'jpeg' else ext}"
    return {
        "display_name": name[:240],
        "stored_name": stored,
        "ext": ext,
        "mime": expected,
        "size": len(data),
    }, None
