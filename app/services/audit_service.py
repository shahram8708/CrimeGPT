import json

from flask import has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def write_audit(
    action,
    object_type=None,
    object_id=None,
    actor=None,
    station_id=None,
    case_id=None,
    meta=None,
    ip=None,
    user_agent=None,
):
    if actor is None and has_request_context() and getattr(current_user, "is_authenticated", False):
        actor = current_user
    if has_request_context():
        ip = ip or request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        user_agent = user_agent or (request.user_agent.string or "")[:300]
        if station_id is None and actor is not None:
            station_id = getattr(actor, "station_id", None)
    meta_json = None
    if meta:
        try:
            meta_json = json.dumps(meta, default=str)[:4000]
        except (TypeError, ValueError):
            meta_json = None
    row = AuditLog(
        actor_id=getattr(actor, "id", None),
        station_id=station_id,
        case_id=case_id,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        ip=ip,
        user_agent=user_agent,
        meta_json=meta_json,
    )
    db.session.add(row)
    db.session.commit()
    return row
