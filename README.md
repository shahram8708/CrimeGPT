# CrimeGPT

Station-grade documentation assistance for Ahmedabad City Police and the Kanad S.H.I.E.L.D. Ahmedabad City Police Innovation Challenge 2026. Problem ID `PS-69EEFDFB90B99`.

CrimeGPT does not provide legal advice. It does not replace CCTNS, ICJS, a Magistrate, or a public prosecutor.

## Run locally

Python 3.11 or 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

`run.py` keeps `use_reloader=False`. First run creates SQLite under `instance/`, folders, and the NRP seed.

Demo accounts (password `Navrangpura!2026` except Super Admin):

| Identifier | Role |
| --- | --- |
| `superadmin` / `CrimeGPT!Admin2026` | Super Admin |
| `admin.nrp` | Admin |
| `sho.nrp` | SHO |
| `io.nrp` | IO |
| `writer.nrp` | Writer |
| `legal.nrp` | Legal |
| `constable.nrp` | Constable |

Seeded case: CR `118/2026` (hurt).

Redis is recommended. Celery worker:

```bash
celery -A celery_app.celery worker --loglevel=info
```

Optional beat for retention (see `app/tasks/maintenance_tasks.py`):

```bash
celery -A celery_app.celery call crimegpt.purge_tombstoned
```

## Production

- Terminate HTTPS on nginx (required for the service worker and Secure cookies).
- `gunicorn -w 2 -b 0.0.0.0:8000 wsgi:app` (2–4 workers).
- Separate Celery worker. Redis for broker and Flask-Caching.
- Set `FLASK_ENV=production`, `DATABASE_URL`, `SECRET_KEY`, `GEMINI_API_KEY` via systemd or a secret manager. Do not commit `.env`.
- `ProductionConfig` turns `RATE_LIMIT_ENABLED` on.
- Hourly copy of `instance/app.db` if you stay on SQLite.
- Disk alerts on `uploads/` and `generated/`.
- Gemini key rotation: change the env value, restart web and workers, never log the new key.
- Postgres: set `DATABASE_URL`. FTS stays SQLite-specific; isolate it later. No rewrite is required to point the ORM at Postgres.

## Kanad demo

1. Sign in as `io.nrp`.
2. Open CR `118/2026`.
3. Run Legal Intelligence on the narrative.
4. Confirm two BNS sections as a human.
5. Generate the medical letter and a remand or seizure paper.
6. Open the diary timeline.

Every AI line is labeled. Every section on the pool was confirmed by an officer. The product does not file an FIR, match faces, or give legal advice.

## PWA checklist (manual)

Install on Android Chrome. Offline: landing and how-it-works should open from cache. Generate / Legal Intelligence copy should say you need a network. Confirm Cache Storage has no case JSON.

## Tests

```bash
pytest
```

## What is not in this product

Live CCTNS, face recognition, offline Gemini, an SCC Online licence, or a claim that CrimeGPT replaces the public prosecutor. SQLite write lock is accepted for the pilot. ReportLab will not pixel-match a 1998 Word stencil.
