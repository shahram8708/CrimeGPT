from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import ApplicationSetting, User, UserPreference
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.utils.security_utils import hash_password_token

DISCLAIMER_EN = (
    "AI-generated legal information may contain errors and should be verified "
    "against authoritative legal sources. This platform does not provide legal "
    "advice. For matters with significant legal consequences, please consult a "
    "qualified legal professional."
)

DISCLAIMER_HI = (
    "एआई-जनित कानूनी जानकारी में त्रुटियाँ हो सकती हैं और इसे प्रामाणिक कानूनी "
    "स्रोतों से सत्यापित किया जाना चाहिए। यह मंच कानूनी सलाह प्रदान नहीं करता है। "
    "महत्वपूर्ण कानूनी परिणामों वाले मामलों के लिए कृपया एक योग्य कानूनी पेशेवर से "
    "परामर्श करें।"
)

DISCLAIMER_GU = (
    "એઆઈ-જનિત કાનૂની માહિતીમાં ભૂલો હોઈ શકે છે અને તેને પ્રમાણભૂત કાનૂની સ્ત્રોતો "
    "સામે ચકાસવી જોઈએ. આ પ્લેટફોર્મ કાનૂની સલાહ આપતું નથી. નોંધપાત્ર કાનૂની "
    "પરિણામો ધરાવતા મામલાઓ માટે કૃપા કરીને લાયક કાનૂની વ્યાવસાયિકની સલાહ લો."
)

SHORT_EN = (
    "Draft assistance only. Not legal advice. Officers must verify BNS / BNSS / BSA."
)
SHORT_HI = (
    "केवल मसौदा सहायता। कानूनी सलाह नहीं। अधिकारियों को भा.ना.सं. / भा.ना.सु.सं. / भा.सा.अ. सत्यापित करना होगा।"
)
SHORT_GU = (
    "માત્ર મુસદ્દો સહાય. કાનૂની સલાહ નથી. અધિકારીઓએ ભા.ન્યા.સં. / ભા.ન્યા.સુ.સં. / ભા.સા.અ. ચકાસવા જોઈએ."
)


def _ensure_prefs(user, ui_language="en"):
    if user.preferences:
        return user.preferences
    prefs = UserPreference(user=user, ui_language=ui_language, document_language="gu")
    db.session.add(prefs)
    return prefs


def _seed_settings(app):
    defaults = {
        "site_name": "CrimeGPT",
        "registration_open": "true" if app.config.get("REGISTRATION_OPEN") else "false",
        "enrollment_code_hash": hash_password_token("NRP-PILOT-2026"),
        "gemini_daily_soft_limit": "40",
        "retention_days": "365",
        "disclaimer_en": DISCLAIMER_EN,
        "disclaimer_hi": DISCLAIMER_HI,
        "disclaimer_gu": DISCLAIMER_GU,
        "disclaimer_short_en": SHORT_EN,
        "disclaimer_short_hi": SHORT_HI,
        "disclaimer_short_gu": SHORT_GU,
    }
    for key, value in defaults.items():
        if ApplicationSetting.query.filter_by(key=key).first() is None:
            db.session.add(ApplicationSetting(key=key, value=value))


def seed_if_empty(app):
    _seed_settings(app)
    ident = (app.config.get("SEED_SUPERADMIN_IDENTIFIER") or "superadmin").strip().lower()
    existing = User.query.filter(
        (User.identifier == ident) | (User.email == "superadmin@crimegpt.local")
    ).first()
    if existing is not None:
        _ensure_prefs(existing)
        db.session.commit()
        return False

    password = app.config.get("SEED_SUPERADMIN_PASSWORD") or "CrimeGPT!Admin2026"
    now = utcnow()
    admin = User(
        full_name="CrimeGPT Super Admin",
        identifier=ident,
        email="superadmin@crimegpt.local",
        password_hash=generate_password_hash(password),
        role="super_admin",
        rank_label="Platform Developer",
        station_id=None,
        is_active=True,
        email_verified_at=now,
        onboarding_completed_at=now,
        disclaimer_accepted_at=now,
    )
    db.session.add(admin)
    db.session.flush()
    _ensure_prefs(admin)
    db.session.commit()
    write_audit(
        "seed.completed",
        object_type="system",
        object_id="first-run",
        meta={"users": 1},
    )
    return True
