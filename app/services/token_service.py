from datetime import timedelta

from app.extensions import db
from app.models import AuthToken
from app.models.mixins import utcnow
from app.utils.security_utils import generate_url_token, hash_password_token


def issue_token(user, purpose, hours):
    AuthToken.query.filter_by(user_id=user.id, purpose=purpose, used_at=None).update(
        {"used_at": utcnow()}, synchronize_session=False
    )
    raw, hashed = generate_url_token()
    row = AuthToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=hashed,
        expires_at=utcnow() + timedelta(hours=hours),
    )
    db.session.add(row)
    db.session.commit()
    return raw, row


def load_token(raw, purpose):
    if not raw:
        return None
    hashed = hash_password_token(raw)
    row = AuthToken.query.filter_by(token_hash=hashed, purpose=purpose).first()
    return row


def token_is_valid(row):
    if row is None or row.used_at is not None:
        return False
    expires = row.expires_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    return expires > utcnow()


def mark_used(row):
    row.used_at = utcnow()
    db.session.commit()
