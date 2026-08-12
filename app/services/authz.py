from functools import wraps

from flask import abort
from flask_login import current_user, login_required

ROLE_RANK = {
    "constable": 10,
    "writer": 20,
    "io": 30,
    "legal": 40,
    "sho": 50,
    "admin": 60,
    "super_admin": 100,
}

SHO_INVITE_ROLES = ("constable", "writer", "io", "legal")
PUBLIC_REGISTER_ROLES = ("constable", "writer")


def _ok(user):
    return bool(user and getattr(user, "is_authenticated", False))


def is_super_admin(user=None):
    user = user if user is not None else current_user
    return _ok(user) and user.role == "super_admin"


def is_admin(user=None):
    user = user if user is not None else current_user
    if is_super_admin(user):
        return True
    return _ok(user) and user.role == "admin"


def is_sho(user=None):
    user = user if user is not None else current_user
    if is_super_admin(user):
        return True
    return _ok(user) and user.role == "sho"


def role_at_least(min_role, user=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role == "super_admin":
        return True
    return ROLE_RANK.get(user.role, 0) >= ROLE_RANK.get(min_role, 0)


def can_create_case(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("writer", "io", "sho", "admin", "super_admin")


def can_edit_case_facts(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("writer", "io", "sho", "admin", "super_admin")


def can_upload_evidence(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role == "legal":
        return False
    if user.role == "constable":
        return bool(case and is_assigned_officer(user, case))
    return user.role in ("writer", "io", "sho", "admin", "super_admin")


def can_view_evidence(user=None, case=None):
    return case_is_visible(user, case)


def can_delete_evidence(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if case and case.is_locked and user.role != "super_admin":
        return False
    return user.role in ("io", "sho", "admin", "super_admin")


def can_add_diary(user=None, case=None, entry_type=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role == "constable":
        if not (case and is_assigned_officer(user, case)):
            return False
        return entry_type in (None, "evidence_note")
    return user.role in ("writer", "io", "sho", "legal", "admin", "super_admin")


def can_sign_diary(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("io", "sho", "super_admin")


def can_correct_diary(user=None, case=None, entry=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role == "constable":
        if not (case and is_assigned_officer(user, case)):
            return False
        if entry is None:
            return True
        return entry.author_id == user.id and entry.entry_type == "evidence_note"
    return user.role in ("writer", "io", "sho", "legal", "admin", "super_admin")


def can_export_diary(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("writer", "io", "sho", "legal", "admin", "super_admin")


def can_assign_case_user(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("io", "sho", "admin", "super_admin")


def gemini_ready():
    try:
        from flask import current_app

        return bool((current_app.config.get("GEMINI_API_KEY") or "").strip())
    except Exception:
        return False


def can_run_legal_intel(user=None, case=None, require_key=True):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role not in ("writer", "io", "sho", "legal", "admin", "super_admin"):
        return False
    if require_key and not gemini_ready():
        return False
    return True


def can_apply_intel(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role == "writer":
        return False
    if case is not None and case.is_locked and user.role != "super_admin":
        return False
    return user.role in ("io", "sho", "legal", "admin", "super_admin")


def can_confirm_sections(user=None, case=None, platform_override=False):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role in ("io", "sho", "super_admin"):
        return True
    return False


def can_lock_case(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("io", "sho", "admin", "super_admin")


def can_delete_case(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("sho", "admin", "super_admin")


def can_generate_documents(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("writer", "io", "sho", "legal", "admin", "super_admin")


def can_finalize_or_lock(user=None, case=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("io", "sho", "super_admin")


def can_view_station_case_list(user=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("sho", "admin", "super_admin")


def can_view_own_or_assigned_cases(user=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("io", "writer", "legal")


def can_access_case_list(user=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return True


def can_manage_station_users(user=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    return user.role in ("sho", "admin", "super_admin")


def can_manage_all_users_and_admins(user=None):
    user = user if user is not None else current_user
    return is_super_admin(user)


def can_invite(user=None, role=None, station_id=None):
    user = user if user is not None else current_user
    if not _ok(user):
        return False
    if user.role == "super_admin":
        return True
    if user.role == "admin":
        return role != "super_admin"
    if user.role == "sho":
        if role and role not in SHO_INVITE_ROLES:
            return False
        if station_id is not None and user.station_id and int(station_id) != int(user.station_id):
            return False
        return True
    return False


def invite_role_choices(user=None):
    user = user if user is not None else current_user
    if is_super_admin(user):
        return [
            "constable",
            "writer",
            "io",
            "sho",
            "legal",
            "admin",
            "super_admin",
        ]
    if _ok(user) and user.role == "admin":
        return ["constable", "writer", "io", "sho", "legal", "admin"]
    if _ok(user) and user.role == "sho":
        return list(SHO_INVITE_ROLES)
    return []


def can_approve_user(actor=None, target=None):
    actor = actor if actor is not None else current_user
    if not can_manage_station_users(actor):
        return False
    if target is None:
        return True
    return can_manage_user(actor, target)


def can_manage_user(actor, target):
    if not _ok(actor) or target is None:
        return False
    if actor.role == "super_admin":
        return True
    if target.role == "super_admin":
        return False
    if actor.role == "admin":
        return True
    if actor.role == "sho":
        if target.role in ("admin", "super_admin"):
            return False
        return target.station_id == actor.station_id
    return False


def can_assign_role(actor, role):
    if not _ok(actor):
        return False
    if actor.role == "super_admin":
        return True
    if actor.role == "admin":
        return role != "super_admin"
    if actor.role == "sho":
        return role in SHO_INVITE_ROLES
    return False


def can_view_all_audit(user=None):
    user = user if user is not None else current_user
    return _ok(user) and user.role in ("admin", "super_admin")


def can_view_job(user, job):
    if not _ok(user):
        return False
    if user.role in ("super_admin", "admin"):
        return True
    return job.user_id == user.id


def _assigned_to(user, case):
    if case is None:
        return False
    uid = getattr(user, "id", None)
    if uid and getattr(case, "created_by_id", None) == uid:
        return True
    if uid and getattr(case, "assigned_io_id", None) == uid:
        return True
    if uid and getattr(case, "assigned_legal_id", None) == uid:
        return True
    return False


def is_assigned_officer(user, case):
    if _assigned_to(user, case):
        return True
    if not user or not case:
        return False
    from app.models.evidence import CaseAssignment

    return (
        CaseAssignment.query.filter_by(case_id=case.id, user_id=user.id).first() is not None
    )


def case_is_visible(user, case):
    if not _ok(user) or case is None:
        return False
    if getattr(case, "deleted_at", None) and user.role != "super_admin":
        return False
    if user.role in ("super_admin", "admin"):
        return True
    if user.role == "constable":
        return is_assigned_officer(user, case)
    station_id = getattr(user, "station_id", None)
    if not station_id or case.station_id != station_id:
        return False
    if user.role == "sho":
        return True
    if user.role == "writer":
        return True
    if user.role == "io":
        return case.created_by_id == user.id or case.assigned_io_id == user.id
    if user.role == "legal":
        return case.assigned_legal_id == user.id
    return False


def require_case(user, case, perm="view"):
    if case is None or (getattr(case, "deleted_at", None) and not (user and user.role == "super_admin")):
        abort(404)
    if not case_is_visible(user, case):
        abort(404)
    if perm == "view":
        return case
    if perm == "edit":
        if not can_edit_case_facts(user, case):
            abort(403)
        if case.is_locked:
            abort(403)
        return case
    if perm == "confirm":
        if not can_confirm_sections(user, case):
            abort(403)
        if case.is_locked:
            abort(403)
        return case
    if perm == "lock":
        if not can_lock_case(user, case):
            abort(403)
        return case
    if perm == "delete":
        if not can_delete_case(user, case):
            abort(403)
        return case
    if perm == "upload":
        if not can_upload_evidence(user, case):
            abort(403)
        return case
    if perm == "delete_evidence":
        if not can_delete_evidence(user, case):
            abort(403)
        return case
    if perm == "diary":
        if not can_add_diary(user, case):
            abort(403)
        return case
    if perm == "sign":
        if not can_sign_diary(user, case):
            abort(403)
        return case
    if perm == "export":
        if not can_export_diary(user, case):
            abort(403)
        return case
    if perm == "assign":
        if not can_assign_case_user(user, case):
            abort(403)
        return case
    if perm == "generate":
        if not can_generate_documents(user, case):
            abort(403)
        if case.is_locked and user.role != "super_admin":
            abort(403)
        return case
    abort(403)


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role == "super_admin" or current_user.role in roles:
                return fn(*args, **kwargs)
            abort(403)

        return wrapped

    return decorator


require_login = login_required
