from sqlalchemy import inspect, text

from app.extensions import db


def _columns(table):
    try:
        return {col["name"] for col in inspect(db.engine).get_columns(table)}
    except Exception:
        return set()


def _tables():
    try:
        return set(inspect(db.engine).get_table_names())
    except Exception:
        return set()


def ensure_additive_schema():
    tables = _tables()
    if "celery_jobs" in tables:
        jcols = _columns("celery_jobs")
        if "is_starred" not in jcols:
            db.session.execute(
                text("ALTER TABLE celery_jobs ADD COLUMN is_starred BOOLEAN DEFAULT 0 NOT NULL")
            )
        if "payload_json" not in jcols:
            db.session.execute(text("ALTER TABLE celery_jobs ADD COLUMN payload_json TEXT"))
    if "police_stations" in tables:
        scols = _columns("police_stations")
        alters = {
            "plan_key": "ALTER TABLE police_stations ADD COLUMN plan_key VARCHAR(32) DEFAULT 'pilot' NOT NULL",
            "monthly_gemini_allowance": "ALTER TABLE police_stations ADD COLUMN monthly_gemini_allowance INTEGER DEFAULT 40 NOT NULL",
            "extra_credits": "ALTER TABLE police_stations ADD COLUMN extra_credits INTEGER DEFAULT 0 NOT NULL",
            "max_users": "ALTER TABLE police_stations ADD COLUMN max_users INTEGER DEFAULT 8 NOT NULL",
            "evidence_quota_bytes": "ALTER TABLE police_stations ADD COLUMN evidence_quota_bytes BIGINT DEFAULT 2147483648 NOT NULL",
            "allow_all_document_types": "ALTER TABLE police_stations ADD COLUMN allow_all_document_types BOOLEAN DEFAULT 0 NOT NULL",
            "allow_legal_review": "ALTER TABLE police_stations ADD COLUMN allow_legal_review BOOLEAN DEFAULT 0 NOT NULL",
            "allow_sho_queue": "ALTER TABLE police_stations ADD COLUMN allow_sho_queue BOOLEAN DEFAULT 0 NOT NULL",
            "allow_station_fts": "ALTER TABLE police_stations ADD COLUMN allow_station_fts BOOLEAN DEFAULT 0 NOT NULL",
            "allow_cctns_demo": "ALTER TABLE police_stations ADD COLUMN allow_cctns_demo BOOLEAN DEFAULT 0 NOT NULL",
            "allow_audit_export": "ALTER TABLE police_stations ADD COLUMN allow_audit_export BOOLEAN DEFAULT 0 NOT NULL",
        }
        for name, sql in alters.items():
            if name not in scols:
                db.session.execute(text(sql))
    if "users" in tables and "invited_by_id" not in _columns("users"):
        db.session.execute(text("ALTER TABLE users ADD COLUMN invited_by_id INTEGER"))
    if "cases" in tables:
        cols = _columns("cases")
        if "assigned_legal_id" not in cols:
            db.session.execute(text("ALTER TABLE cases ADD COLUMN assigned_legal_id INTEGER"))
    if "diary_exports" in tables:
        dcols = _columns("diary_exports")
        if "summarize" not in dcols:
            db.session.execute(text("ALTER TABLE diary_exports ADD COLUMN summarize BOOLEAN DEFAULT 0 NOT NULL"))
        if "summary_text" not in dcols:
            db.session.execute(text("ALTER TABLE diary_exports ADD COLUMN summary_text TEXT"))
        if "summarize_error" not in dcols:
            db.session.execute(text("ALTER TABLE diary_exports ADD COLUMN summarize_error TEXT"))
    if "user_preferences" in tables:
        prefs = _columns("user_preferences")
        if "evidence_consent_at" not in prefs:
            db.session.execute(text("ALTER TABLE user_preferences ADD COLUMN evidence_consent_at DATETIME"))
        if "diary_oldest_first" not in prefs:
            db.session.execute(
                text("ALTER TABLE user_preferences ADD COLUMN diary_oldest_first BOOLEAN DEFAULT 1 NOT NULL")
            )
    db.session.commit()
    db.session.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_case_station_year_cr "
            "ON cases (station_id, year, cr_number) "
            "WHERE cr_number IS NOT NULL AND deleted_at IS NULL"
        )
    )
    db.session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS case_fts USING fts5("
            "case_id UNINDEXED, cr_number, narrative, party_names, diary_blob, "
            "tokenize='unicode61')"
        )
    )
    db.session.commit()
