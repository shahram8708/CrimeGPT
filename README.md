<p align="center">
  <img src="app/static/icons/icon-512.png" alt="CrimeGPT shield" width="150">
</p>

<h1 align="center">CrimeGPT</h1>

<p align="center"><strong>A local-first station workspace for Indian police case records, evidence, legal review, and court-ready drafting.</strong></p>

<p align="center">
  <a href="https://github.com/shahram8708/CrimeGPT/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/shahram8708/CrimeGPT?style=flat-square"></a>
  <a href="https://github.com/shahram8708/CrimeGPT"><img alt="Top language" src="https://img.shields.io/github/languages/top/shahram8708/CrimeGPT?style=flat-square"></a>
  <a href="https://github.com/shahram8708/CrimeGPT"><img alt="Repository size" src="https://img.shields.io/github/repo-size/shahram8708/CrimeGPT?style=flat-square"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Version not released" src="https://img.shields.io/badge/version-unreleased-6c757d?style=flat-square">
  <img alt="License not specified" src="https://img.shields.io/badge/license-not%20specified-dc3545?style=flat-square">
</p>

<p align="center">
  Built for the <strong>Kanad S.H.I.E.L.D. Innovation Challenge 2026</strong> · Ahmedabad City Police · Problem ID <code>PS-69EEFDFB90B99</code>
</p>

> **Legal and operational notice:** CrimeGPT produces draft assistance and candidate legal information, not legal advice or court findings. An authorised officer must verify every BNS, BNSS, and BSA reference against an authoritative source before using an output.

The repository does not contain a hosted demo URL or product screenshot. The bundled shield above is the installable PWA icon; follow [Getting Started](#getting-started) to run the full interface locally.

## Table of Contents

- [About the Project](#about-the-project)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
  - [Running the Project](#running-the-project)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [Roadmap](#roadmap)
- [License](#license)
- [Acknowledgements](#acknowledgements)
- [Contact / Author](#contact--author)

## About the Project

CrimeGPT turns the moving parts of a police-station case—parties, property, arrests, medical records, diary entries, evidence, statutory sections, and generated papers—into one structured, auditable workspace. It is aimed at station writers, constables, investigating officers, SHOs, legal-cell users, administrators, and challenge evaluators working with Indian criminal-law documentation. The application is especially useful when a team needs repeatable BNS/BNSS/BSA checks and multilingual drafts without sending case material to a paid cloud AI service. What makes it interesting is the combination of strict role gates, immutable-style diary corrections, local document processing, multilingual court templates, and explicit human-verification safeguards in a single Flask application.

## Key Features

- **Station-scoped case pool:** Capture CR/FIR references, incident facts, parties, seized items, arrests, medical details, assignments, status, and confirmed or suggested statutory sections in one record.
- **Role-aware workflows:** Enforce distinct permissions for constables, writers, IOs, SHOs, legal-cell users, station admins, and super admins.
- **Evidence handling:** Accept verified PDF, JPEG, and PNG uploads up to 15 MiB, generate image thumbnails, track exhibits, control EXIF retention, apply station quotas, and tombstone deleted files for later purging.
- **Case diary:** Add chronological entries, sign them, correct signed entries by creating linked correction records, connect exhibits, and export a date range as DOCX and PDF.
- **Local legal assistance:** Suggest candidate BNS, BNSS, and BSA provisions from bundled statute fixtures, show IPC/CrPC/IEA crosswalks, retrieve curated judgment fixtures, and refuse requests to fabricate or hide evidence.
- **Operational checklists and gap analysis:** Merge offence-specific YAML playbooks with case facts to highlight missing process steps, documents, witnesses, medical data, and sections.
- **Court-paper generation:** Produce versioned DOCX/PDF drafts for eight document types, including medical letters, seizure receipts, police-custody remand requests, panchanamas, and supplementary chargesheets.
- **Document intelligence:** Extract text from DOCX and digital PDFs, use Tesseract for supported images, identify common legal clauses, compare versions, and apply selected extracted facts back to a case under permission checks.
- **Multilingual interface:** Ship 670+ UI strings per locale for English, Hindi, and Gujarati, plus document templates in all three languages.
- **PWA support:** Cache only the public shell for offline access, exclude sensitive case routes from service-worker caching, and optionally save case-wizard drafts in browser IndexedDB.
- **Background work:** Run legal analysis, document generation, evidence processing, email, exports, and maintenance through Celery with Redis, with an in-process development fallback when no external broker is configured.
- **Administration and audit:** Manage stations, plans, quotas, enrollment, users, mail logs, usage, jobs, settings, letterheads, and structured audit events; CCTNS and Bharatpol integrations are clearly marked local mocks.

## Tech Stack

Versions are shown only where the repository pins or vendors them. Python package versions in `requirements.txt` are currently **unconstrained**.

### Frontend

| Technology | Role | Version found |
|---|---|---:|
| Jinja2 | Server-rendered pages and reusable template partials | Unpinned |
| Bootstrap | Responsive layout, forms, navigation, modals, and components | **5.3.3** (vendored) |
| Vanilla JavaScript | Job polling, wizard state, upload UX, password meter, language switching, and PWA installation | Native browser APIs |
| Marked | Markdown rendering for the Q&A interface | **4.3.0** (vendored) |
| CSS3 | Custom navy-and-gold station UI, responsive views, print rules, and chat styling | — |
| Service Worker, Web App Manifest, IndexedDB | Installable PWA shell and optional local wizard drafts | Native browser APIs |

### Backend

| Technology / library | Role | Version found |
|---|---|---:|
| Python | Application runtime; `zoneinfo` usage implies Python 3.9+ | Not pinned |
| Flask | Application factory, blueprints, sessions, routing, JSON, and templating | Unpinned |
| Flask-SQLAlchemy / SQLAlchemy | ORM, transactions, relationships, schema inspection, and SQL execution | Unpinned |
| Flask-Login | Session authentication and strong session protection | Unpinned |
| Flask-WTF / WTForms / email-validator | CSRF-protected forms and validation | Unpinned |
| Flask-Migrate | Migration integration is initialized, although no migration directory is committed | Unpinned |
| Flask-Limiter | Optional request limiting, including the contact form | Unpinned |
| Flask-Caching | In-memory or Redis-backed caching | Unpinned |
| Celery / Redis | Background jobs, result storage, and daily maintenance scheduling | Unpinned |
| Werkzeug, itsdangerous, Click, Bleach | Security and Flask ecosystem utilities declared by the project | Unpinned |
| Gunicorn | Production WSGI server | Unpinned |
| python-dotenv | `.env` loading for web, worker, and WSGI entry points | Unpinned |

### Database

| Technology | Role | Version found |
|---|---|---:|
| SQLite | Default database, foreign-key enforcement, partial indexes, and FTS5 case search | Runtime-provided |
| SQLAlchemy ORM | Database abstraction and model layer | Unpinned |
| SQLite FTS5 | Search across CR number, narrative, parties, and diary text | Runtime-provided |

> The code accepts a SQLAlchemy `DATABASE_URL`, but the additive schema helper creates SQLite-specific FTS5 and partial indexes. Treat SQLite as the supported database in this revision unless you adapt that schema code.

### Document, OCR, and Local Analysis

| Technology / library | Role | Version found |
|---|---|---:|
| Pillow | Image verification and thumbnails | Unpinned |
| Tesseract / pytesseract | English, Hindi, and Gujarati image OCR | System package / unpinned wrapper |
| pypdf | Text extraction from digital PDFs | Unpinned |
| python-docx / docxtpl | DOCX reading and Jinja-style court-template rendering | Unpinned |
| ReportLab | PDF generation | Unpinned |
| PyYAML | Operational playbook loading | Unpinned |
| langdetect | Local language detection | Unpinned |
| spaCy, Transformers, PyTorch, SentencePiece, sentence-transformers, FAISS CPU | Declared local-AI dependencies and configuration targets | Unpinned; not imported by the current implementation |

The current `local_ai_service.py` is local and deterministic: it uses keyword/rule analysis, bundled statute and judgment fixtures, clause detectors, language detection, and OCR. Configuration exists for transformer, embedding, spaCy, translation, and vector-index models, but this revision does not load those model stacks directly. The legacy `gemini_service.py` name is only a compatibility wrapper around the local service; no Gemini or OpenAI call is made.

### DevOps and Other Tools

- **pytest** is declared for testing, but no test modules are committed yet.
- **SMTP via Python `smtplib`** sends verification, reset, invite, and contact email.
- **Gunicorn** serves `wsgi:app` in production.
- **Celery Beat** schedules the daily `crimegpt.purge_tombstoned` task.
- No Dockerfile, Compose file, CI workflow, cloud manifest, lint config, formatter config, or pinned lockfile is present.

## Project Structure

The tree below includes every top-level repository item and the key files inside each application area.

```text
.
├── .env.example                       # Development configuration template
├── .gitignore                         # Ignores secrets, runtime data, caches, and build output
├── README.md                          # Project documentation
├── requirements.txt                   # Unpinned Python runtime and analysis dependencies
├── run.py                             # Local Flask entry point on 0.0.0.0:$PORT
├── wsgi.py                            # Gunicorn/WSGI entry point exposing `app`
├── celery_app.py                      # Top-level Celery import target
├── celerybeat-schedule-shm            # Committed SQLite shared-memory artifact from Celery Beat
├── celerybeat-schedule-wal            # Committed SQLite WAL artifact from Celery Beat
└── app/
    ├── __init__.py                    # App factory, extension wiring, blueprints, errors, headers, and startup
    ├── config.py                      # Development, testing, and production configuration classes
    ├── extensions.py                  # SQLAlchemy, Login, CSRF, Cache, Limiter, Migrate, and Celery objects
    ├── forms/
    │   ├── admin_forms.py             # Station, setting, invitation, and user-management forms
    │   ├── auth.py                    # Legacy login form
    │   ├── auth_forms.py              # Login, registration, verification, reset, invite, and onboarding forms
    │   ├── case_forms.py              # Case wizard, party, item, arrest, medical, and section forms
    │   ├── contact.py                 # Public contact form with honeypot field
    │   ├── document_forms.py          # Generation, upload, comparison, diary, and review forms
    │   ├── evidence_forms.py          # Evidence, diary, export, and assignment forms
    │   ├── profile_forms.py           # Profile, preference, and password forms
    │   ├── tool_forms.py              # Legal intel, Q&A, analysis, translation, and gap forms
    │   └── __init__.py                # Form exports
    ├── models/
    │   ├── user.py                    # Users, preferences, auth tokens, roles, and password handling
    │   ├── station.py                 # Police stations, plans, quotas, and feature flags
    │   ├── case.py                    # Cases, parties, items, arrests, medical records, and sections
    │   ├── evidence.py                # Evidence, diary entries, assignments, proposals, and exports
    │   ├── document.py                # Generated/uploaded documents, comparisons, clauses, and reviews
    │   ├── ai.py                      # Suggestions, interactions, Q&A, analyses, checklists, and gaps
    │   ├── job.py                     # Pollable background-job records
    │   ├── system.py                  # Settings, audit, notifications, usage, mail, integrations, and contact
    │   ├── mixins.py                  # UTC timestamps
    │   └── __init__.py                # Model exports
    ├── routes/
    │   ├── main.py                    # Public pages, contact, locales, PWA assets, and health check
    │   ├── auth.py                    # Account, verification, invite, reset, lockout, and logout flows
    │   ├── dashboard.py               # Dashboard, onboarding, notifications, history, and starred jobs
    │   ├── cases.py                   # Case wizard and facts, parties, items, arrests, medical, and sections
    │   ├── evidence.py                # Evidence gallery, processing, proposals, and assignments
    │   ├── diary.py                   # Diary timeline, signing, correction, and export
    │   ├── documents.py               # Document hub, generation, versions, uploads, review, and clause analysis
    │   ├── tools.py                   # Legal intel, compare, Q&A, document analysis, explain, and translate
    │   ├── results.py                 # Result views and controlled application of extracted suggestions
    │   ├── assist.py                  # Checklists and case-gap workflows
    │   ├── jobs.py                    # Job progress, retry, ping, and result redirection
    │   ├── api.py                     # Authenticated JSON job polling endpoint
    │   ├── downloads.py               # Authorised evidence, thumbnail, DOCX, and PDF downloads
    │   ├── profile.py                 # User profile, preferences, security, and activity
    │   ├── admin.py                   # Stations, audit, settings, jobs, usage, and CSV exports
    │   ├── admin_users.py             # Scoped user administration and development mail log
    │   └── __init__.py                # Route package marker
    ├── services/
    │   ├── local_ai_service.py        # Local rule-based legal, Q&A, clause, translation, and OCR logic
    │   ├── gemini_service.py          # Backward-compatible exports for the local AI service
    │   ├── intel_service.py           # Suggestion persistence, quotas, caching, application, and audit
    │   ├── analysis_service.py        # Uploaded-document extraction and controlled field application
    │   ├── compare_service.py         # Structured and line-based document comparisons
    │   ├── case_service.py            # Case visibility, filters, completeness, FTS, and dashboard counts
    │   ├── document_service.py        # Document preflight, context, versions, quota, and enqueueing
    │   ├── docx_service.py            # Court and diary DOCX generation
    │   ├── pdf_service.py             # Court and diary PDF generation
    │   ├── playbook_service.py        # YAML playbook loading and deterministic gaps
    │   ├── qa_service.py              # Q&A thread access and job orchestration
    │   ├── task_service.py            # Celery dispatch and development thread fallback
    │   ├── authz.py                   # Central role and object-level authorisation rules
    │   ├── entitlement_service.py     # Plan caps, flags, usage, evidence quotas, and letterheads
    │   ├── audit_service.py           # Structured audit writer
    │   ├── account_mail.py            # Account and contact email composition
    │   ├── email_layout.py            # Shared HTML email shell and public links
    │   ├── mail_service.py            # SMTP send, logging, queueing, and fallback
    │   ├── token_service.py           # Expiring one-time account tokens
    │   ├── registration.py            # Registration and enrollment-code policy
    │   ├── seed.py                    # First-run settings and super-admin seed
    │   ├── file_service.py            # Local upload and generated-file storage
    │   ├── i18n.py                    # JSON locale loader and session language
    │   ├── integrations/
    │   │   ├── cctns_mock.py          # Local mock returning an acknowledgement number
    │   │   ├── bharatpol_mock.py      # Local mock returning an acknowledgement number
    │   │   └── __init__.py            # Integration package marker
    │   └── __init__.py                # Service package marker
    ├── tasks/
    │   ├── celery_app.py              # Worker config, task imports, beat schedule, and Flask context
    │   ├── ai_tasks.py                # Legal intel, compare, identify, Q&A, analysis, translate, checklist, gaps
    │   ├── document_tasks.py          # Evidence processing, diary export, and document generation
    │   ├── mail_tasks.py              # SMTP task
    │   ├── maintenance_tasks.py       # Retention-based tombstone purge
    │   ├── system_tasks.py            # Database/storage/audit system ping
    │   └── __init__.py                # Task package marker
    ├── utils/
    │   ├── file_utils.py              # Upload allowlist, content sniffing, size limits, and directories
    │   ├── formatting_utils.py        # IST formatting, redaction, JSON extraction, and sanitisation
    │   ├── schema.py                  # Additive SQLite columns, indexes, and FTS5 table
    │   ├── security_utils.py          # Tokens, password policy, constant-time compare, and safe redirects
    │   └── __init__.py                # Utility package marker
    ├── data/
    │   ├── DATA_LICENSES.md           # Dataset provenance and licensing notes
    │   ├── playbooks/                 # accident, house_trespass, hurt, intimidation, NDPS-adjacent, other, theft
    │   └── statutes/                  # BNS, BNSS, BSA, and curated judgment JSON fixtures
    ├── static/
    │   ├── css/app.css                # Full custom responsive and print stylesheet
    │   ├── js/app.js                  # Main UI behaviours, polling, wizard, uploads, and IndexedDB drafts
    │   ├── js/pwa.js                  # Service-worker registration and install prompts
    │   ├── i18n/{en,hi,gu}.json       # English, Hindi, and Gujarati UI dictionaries
    │   ├── icons/{icon-192,icon-512}.png # PWA shield icons
    │   ├── vendor/bootstrap/          # Vendored Bootstrap 5.3.3 CSS and bundle
    │   ├── vendor/marked.min.js       # Vendored Marked 4.3.0
    │   ├── manifest.json              # Standalone PWA metadata
    │   └── sw.js                      # Public-shell caching with sensitive-route exclusions
    ├── templates/
    │   ├── base.html                  # Shared page shell
    │   ├── admin/                     # Admin home, stations, users, audit, jobs, usage, settings, and mail log
    │   ├── auth/                      # Login, register, verify, forgot/reset password, and invite acceptance
    │   ├── cases/                     # Case pool, wizard, overview, facts, evidence, diary, gaps, and checklist
    │   ├── dashboard/                 # Home, history, onboarding, and notifications
    │   ├── documents/                 # Hub, generation, previews, versions, uploads, and uploaded details
    │   ├── email/                     # Responsive base, generic, contact, invite, reset, and verification email
    │   ├── errors/                    # 403, 404, 413, and 500 pages
    │   ├── includes/                  # Alerts, footer, macros, modals, navbar, profile nav, and quota banner
    │   ├── jobs/                      # Live job progress view
    │   ├── profile/                   # Profile, preferences, security, and activity
    │   ├── public/                    # Landing, about, contact, features, guide, legal pages, and offline page
    │   ├── results/                   # Legal intel, compare, identify, analysis, and translation results
    │   └── tools/                     # Legal intel, compare, Q&A, analyze, and explain forms
    └── templates_docx/                # 8 court templates × English, Hindi, and Gujarati (24 DOCX files)
```

The two `celerybeat-schedule-*` files are runtime SQLite WAL/SHM artifacts, not source configuration. They are tracked in the current repository even though the base `celerybeat-schedule` file is ignored.

## Getting Started

### Prerequisites

Install these tools before you begin:

1. **[Git](https://git-scm.com/downloads)** to clone the repository.
2. **[Python 3.9 or newer](https://www.python.org/downloads/)**; Python 3.11 is a practical choice for this codebase.
3. **pip and `venv`**, normally included with Python.
4. **[Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html)** plus English, Hindi, and Gujarati language packs if you want image OCR.
5. **[Redis](https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/)** for production background jobs; local development can use the built-in thread fallback.

Ubuntu/Debian OCR packages:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-guj
```

On Windows, install Tesseract and either add `tesseract.exe` to `PATH` or set `TESSERACT_CMD` to its full path. On macOS, install Tesseract with Homebrew and add the required trained-language data to the Tesseract `tessdata` directory.

> `requirements.txt` includes PyTorch, Transformers, sentence-transformers, spaCy, and FAISS, so the full install is large even though the current deterministic local service does not import those packages.

### Installation

1. Clone the repository and enter it:

   ```bash
   git clone https://github.com/shahram8708/CrimeGPT.git
   cd CrimeGPT-Hackathon
   ```

2. Create a virtual environment:

   ```bash
   python -m venv .venv
   ```

3. Activate it:

   **Linux/macOS**

   ```bash
   source .venv/bin/activate
   ```

   **Windows PowerShell**

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

4. Upgrade packaging tools and install dependencies:

   ```bash
   python -m pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```

5. Create your local environment file:

   **Linux/macOS**

   ```bash
   cp .env.example .env
   ```

   **Windows PowerShell**

   ```powershell
   Copy-Item .env.example .env
   ```

6. Set a unique application secret and a strong first-run administrator password in `.env`:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Copy the result to `SECRET_KEY`, replace `SEED_SUPERADMIN_PASSWORD`, and never deploy the example credentials.

7. Start the application:

   ```bash
   python run.py
   ```

8. Open [http://localhost:5000](http://localhost:5000), then sign in with the identifier from `SEED_SUPERADMIN_IDENTIFIER` and the password you set. On the first boot CrimeGPT creates the SQLite schema, FTS5 index, default settings, storage folders, and super-admin account.

9. Create a station under **Admin → Stations**, then invite or register station users. A fresh database contains the platform super admin but no police station.

### Environment Variables

The table covers every environment variable read by the code, including compatibility and advanced variables omitted from `.env.example`.

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | Signs Flask sessions and CSRF data; replace the insecure fallback before any shared deployment. | `4c7d...64-random-hex-chars...` |
| `FLASK_ENV` | Selects `development`, `testing`, or `production` config. | `development` |
| `DATABASE_URL` | SQLAlchemy database URI; required when `FLASK_ENV=production`. | `sqlite:////srv/crimegpt/instance/app.db` |
| `PORT` | Port used by `run.py`. | `5000` |
| `UPLOAD_FOLDER` | Evidence and library-document storage root, relative to the repository unless absolute. | `uploads` |
| `GENERATED_FOLDER` | Generated DOCX/PDF storage root. | `generated` |
| `MAX_CONTENT_LENGTH` | Flask request-body cap in bytes; upload validation separately enforces 15 MiB per file. | `16777216` |
| `RATE_LIMIT_ENABLED` | Enables Flask-Limiter outside config-class overrides; production forces it on and development forces it off. | `false` |
| `REGISTRATION_OPEN` | Controls public registration outside config-class overrides; development forces it on. | `true` |
| `SEED_SUPERADMIN_IDENTIFIER` | Identifier created on the first empty-database boot. | `superadmin` |
| `SEED_SUPERADMIN_PASSWORD` | Password for that first-run super admin; must be changed from the committed example. | `use-a-unique-strong-password` |
| `MAIL_SERVER` | SMTP host; blank means mail cannot be delivered and is logged as failed/fallback. | `smtp.example.org` |
| `MAIL_PORT` | SMTP port. | `587` |
| `MAIL_USERNAME` | SMTP username. | `crimegpt@example.org` |
| `MAIL_PASSWORD` | SMTP password or app password. | `smtp-app-password` |
| `MAIL_DEFAULT_SENDER` | From address used by account and contact mail. | `noreply@example.org` |
| `MAIL_USE_TLS` | Enables STARTTLS; defaults to true. | `true` |
| `MAIL_USE_SSL` | Enables implicit SMTP SSL; defaults to false. | `false` |
| `PUBLIC_BASE_URL` | Absolute base URL used when email templates build links. | `https://crimegpt.example.org` |
| `CELERY_BROKER_URL` | Celery broker; `memory://` triggers the development thread fallback and cannot connect separate processes. | `redis://127.0.0.1:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend. | `redis://127.0.0.1:6379/1` |
| `REDIS_URL` | Redis cache URL; falls back to the Celery broker URL when it is Redis. | `redis://127.0.0.1:6379/2` |
| `LOCAL_LLM_MODEL_PATH` | Configured local model name/path reserved for the local model stack. | `Qwen/Qwen2.5-3B-Instruct` |
| `LOCAL_LLM_DEVICE` | Configured local inference device. | `auto` |
| `LOCAL_EMBED_DEVICE` | If set, currently overrides `LOCAL_LLM_DEVICE` in `app/config.py`. | `cpu` |
| `LOCAL_EMBED_MODEL` | Configured embedding model name/path. | `all-MiniLM-L6-v2` |
| `SPACY_MODEL` | Configured spaCy model name. | `en_core_web_sm` |
| `TESSERACT_CMD` | Full Tesseract executable path when it is not on `PATH`. | `/usr/bin/tesseract` |
| `TESSDATA_PREFIX` | Directory containing Tesseract language data. | `/usr/share/tesseract-ocr/5/tessdata` |
| `TRANSLATION_MODEL_PATH` | Optional configured local translation-model path. | `/opt/crimegpt/models/translation` |
| `VECTOR_INDEX_PATH` | Optional configured on-disk vector-index path. | `/srv/crimegpt/data/vector_index.bin` |
| `GEMINI_API_KEY` | Legacy compatibility setting read into Flask config; the current local service does not require or call Gemini. | `` (leave blank) |
| `GEMINI_MODEL` | Compatibility model label recorded with AI interactions; defaults to `local-instruct-model`. | `local-instruct-model` |
| `GEMINI_LOG_PROMPTS` | Legacy prompt-logging flag defined in config; no active prompt logger consumes it in this revision. | `0` |

### Running the Project

#### Development: simplest mode

The default `memory://` broker causes supported jobs to run in a daemon thread inside the Flask process, so one terminal is enough:

```bash
python run.py
```

The application listens on `0.0.0.0:5000` by default. Debug mode follows `FLASK_ENV=development`, but the reloader is deliberately disabled.

#### Development with Redis and a real worker

Set these values in `.env`:

```dotenv
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
REDIS_URL=redis://127.0.0.1:6379/2
```

Then run each process in its own terminal:

```bash
# Terminal 1
redis-server
```

```bash
# Terminal 2
celery -A celery_app.celery worker --loglevel=info
```

```bash
# Terminal 3
python run.py
```

Run Celery Beat as a fourth process if you want the daily tombstoned-file purge:

```bash
celery -A celery_app.celery beat --loglevel=info
```

On Windows, the worker configuration automatically selects Celery's `solo` pool.

#### Production build and run

There is no frontend compile step; Bootstrap, Marked, CSS, JavaScript, and PWA files are already committed. Set `FLASK_ENV=production`, provide all required secrets and a `DATABASE_URL`, configure Redis, and start the web process with Gunicorn:

```bash
FLASK_ENV=production gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 180 wsgi:app
```

One Gunicorn worker is the conservative starting point for SQLite. Run Celery Worker and Celery Beat separately with the commands above.

## Usage

CrimeGPT is a server-rendered, session-authenticated workspace rather than a public case-management REST API. A typical station flow looks like this:

1. **Create the station:** Sign in as the seeded super admin, open `/admin/stations/new`, add the station letterhead and plan, and keep the station active.
2. **Provision the team:** Invite users from `/admin/users/new`; assign `constable`, `writer`, `io`, `sho`, `legal`, `admin`, or `super_admin` according to the central authorisation rules.
3. **Open a case:** Use `/cases/new` to enter year, CR/FIR or GD number, incident date, place, category, complainant, and narrative.
4. **Build the case pool:** Add parties, property, arrest blocks, medical details, evidence, diary entries, and statutory sections from the case sub-navigation.
5. **Review assistance:** Run Legal Intelligence, a checklist, or gap analysis; treat every result as a candidate and let an authorised officer confirm any section.
6. **Generate papers:** Open the document hub, pass the document-specific preflight checks, choose English/Hindi/Gujarati, preview the output, edit allowed narrative blocks, finalise it, and download DOCX or PDF.
7. **Audit and supervise:** SHOs, legal users, and admins can inspect progress, review generated papers, lock cases, view usage, and follow audit history within their permission scope.

### Health-check example

```bash
curl -s http://localhost:5000/healthz
```

Expected healthy response:

```json
{
  "status": "ok",
  "db": "ok",
  "time": "2026-08-13T11:30:00.000000+00:00"
}
```

A database failure returns HTTP `503` with `status` and `db` set to `error`.

### Background-job polling example

The progress page calls this endpoint every 2.5 seconds with the authenticated browser session:

```bash
curl -b cookies.txt \
  -H "Accept: application/json" \
  -H "X-Requested-With: XMLHttpRequest" \
  http://localhost:5000/api/jobs/0f754891-8f68-4af5-8cdd-844f35388c42
```

Example processing response:

```json
{
  "status": "processing",
  "progress": 50,
  "message": "Checking storage folders",
  "redirect": null,
  "error": null
}
```

When the job completes, `redirect` points to the legal-intel result, diary export, generated document, comparison, clause analysis, Q&A thread, uploaded-document analysis, translation, checklist, or gap page associated with the job.

### Supported generated papers

| Key | Document |
|---|---|
| `medical_letter` | Medical Treatment Letter |
| `seizure_receipt` | Seizure Receipt |
| `remand_pc` | Remand Request (Police Custody) |
| `face_identification` | Accused Face Identification Form |
| `purvani_chargesheet` | Purvani Chargesheet |
| `court_custody` | Court Custody Letter |
| `accused_panchanama` | Accused Panchanama |
| `lers_request` | Legal request letter template |

Each type has English, Hindi, and Gujarati DOCX templates. Pilot plans allow the first four by default; station, zone, and commissionerate plans can enable all document types.

## API Documentation

Only two JSON endpoints are implemented. All other application operations use CSRF-protected HTML forms and redirects.

### `GET /healthz`

| Item | Details |
|---|---|
| Authentication | None |
| CSRF | Exempt |
| Description | Checks that the web process can execute `SELECT 1` against the database. |
| Request body | None |
| Success | `200 OK` with `{ "status": "ok", "db": "ok", "time": "<UTC ISO-8601>" }` |
| Failure | `503 Service Unavailable` with `{ "status": "error", "db": "error", "time": "<UTC ISO-8601>" }` |

### `GET /api/jobs/<job_uuid>`

| Item | Details |
|---|---|
| Authentication | Required Flask-Login session cookie |
| Authorisation | The current user must pass `can_view_job`; inaccessible and unknown jobs both return 404. |
| Description | Returns the current state of a persisted background job and a result redirect when available. |
| Path parameter | `job_uuid`: UUID stored in `celery_jobs.uuid` |
| Request body | None |
| Success | `200 OK` with the payload below |
| Unauthenticated | `401 Unauthorized` with `{ "error": "authentication required" }` |
| Missing/forbidden | `404 Not Found` JSON from the application error handler |

```json
{
  "status": "queued | processing | completed | failed",
  "progress": 0,
  "message": "Queued",
  "redirect": null,
  "error": null
}
```

The `error` field is populated only for failed jobs. `redirect` remains `null` until a completed job has a recognised result record.

### Supporting machine-readable routes

- `GET /manifest.webmanifest` returns `app/static/manifest.json` as a web-app manifest.
- `GET /sw.js` serves the service worker with `Service-Worker-Allowed: /` and `Cache-Control: no-cache`.

These are PWA resources, not application APIs.

## Configuration

### Runtime profiles

`app/config.py` selects a profile from `FLASK_ENV`:

| Profile | Database | Registration | Rate limiting | Secure cookies |
|---|---|---:|---:|---:|
| `development` / `dev` | `DATABASE_URL` or local SQLite | Forced on | Forced off | Off |
| `testing` / `test` | In-memory shared SQLite | On | Off | Off |
| `production` / `prod` | `DATABASE_URL` is required | Environment/default policy | On | On |

Production cookies require HTTPS. The application also sends `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, and `Referrer-Policy: strict-origin-when-cross-origin`.

### First-run seed and database schema

- `create_app()` creates the configured folders and calls `db.create_all()` on startup.
- `app/utils/schema.py` applies additive columns, creates a unique active-case CR index, and creates the SQLite `case_fts` FTS5 table.
- `app/services/seed.py` inserts translated legal disclaimers, registration settings, a 365-day retention default, an enrollment-code hash, and the initial super admin.
- No Alembic migration revisions are committed, despite Flask-Migrate being initialized.
- Back up the database before allowing a newer revision to execute the additive schema helper.

### Application settings

Super admins can change these database-backed values under `/admin/settings`:

- Site name and public-registration state.
- Enrollment-code hash and enrollment rotation.
- Daily AI soft limit and retention days.
- Full and short legal disclaimers in English, Hindi, and Gujarati.

The seeded enrollment phrase is hashed before storage. Rotate it through the admin interface before allowing enrollment in a shared environment.

### Station plans and flags

Stations support `pilot`, `station`, `zone`, and `commissionerate` plans. The stored station record controls monthly AI allowance, extra credits, maximum users, evidence bytes, access to paid document types, legal review, SHO queue, station-wide search, CCTNS demo, and audit export. Development unlocks a station with code `NRP` if that station already exists; startup does not create it.

### Content and operational data

- `app/data/playbooks/*.yaml` defines expected documents, expected process steps, legal elements, and common gaps for seven case categories.
- `app/data/statutes/*.json` contains compact BNS 2023, BNSS 2023, BSA 2023, and judgment fixtures used by local retrieval.
- Judgment fixtures deliberately set `needs_verification: true`.
- `app/static/i18n/*.json` controls UI text; missing keys fall back to English and then the key name.
- `app/templates_docx/*.docx` controls generated document layout and exposes placeholders such as `station_name`, `letterhead_2`, `letterhead_3`, `disclaimer`, `notice`, and `body_block`.
- `app/static/sw.js` caches public pages and static assets but explicitly bypasses APIs, cases, tools, results, documents, downloads, admin, jobs, and dashboard routes.

### Upload rules

Evidence accepts PDF, JPG/JPEG, and PNG. Library documents can additionally accept DOCX. The validator rejects double extensions, blocked web/executable formats, content that does not match the extension, invalid images, and files larger than 15 MiB. `MAX_CONTENT_LENGTH` should stay above that per-file limit to leave room for the multipart request.

## Testing

`pytest` appears in `requirements.txt`, but the repository contains **no test files, fixtures, or test configuration**. Running the suite in the analyzed revision reports:

```text
no tests ran in 0.03s
```

and exits with pytest status `5` (“no tests collected”). Do not treat that as a passing test suite.

After installing dependencies, run the intended test command with:

```bash
pytest -q
```

Useful smoke checks today are:

```bash
# Validate Python syntax
python -m compileall -q .

# Start the app, then verify database reachability
curl --fail http://localhost:5000/healthz
```

The analyzed source passes `python -m compileall`. The highest-priority automated coverage should target authorisation boundaries, registration and lockout, case visibility, upload validation, section confirmation, diary correction/signing, document preflight, job fallback, and download access.

## Deployment

This repository includes Gunicorn and Celery support, but it does **not** include Docker, Docker Compose, Kubernetes, Heroku, Vercel, AWS, systemd, Nginx, or CI/CD configuration. A production deployment is therefore a manual stateful Python deployment.

### Recommended Linux deployment

1. **Provision a host** with Python 3.9+, Tesseract language packs, Redis, persistent disk, and HTTPS termination.

2. **Clone and install** the application in a dedicated virtual environment:

   ```bash
   git clone https://github.com/shahram8708/CrimeGPT.git /srv/crimegpt
   cd /srv/crimegpt
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt
   ```

3. **Create persistent directories** owned by the service account:

   ```bash
   mkdir -p /srv/crimegpt/instance /srv/crimegpt/uploads /srv/crimegpt/generated
   ```

4. **Create `/srv/crimegpt/.env`** with at least:

   ```dotenv
   FLASK_ENV=production
   SECRET_KEY=<a-long-random-secret>
   DATABASE_URL=sqlite:////srv/crimegpt/instance/app.db
   UPLOAD_FOLDER=/srv/crimegpt/uploads
   GENERATED_FOLDER=/srv/crimegpt/generated
   SEED_SUPERADMIN_IDENTIFIER=superadmin
   SEED_SUPERADMIN_PASSWORD=<a-unique-first-run-password>
   CELERY_BROKER_URL=redis://127.0.0.1:6379/0
   CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
   REDIS_URL=redis://127.0.0.1:6379/2
   PUBLIC_BASE_URL=https://crimegpt.example.org
   RATE_LIMIT_ENABLED=true
   REGISTRATION_OPEN=false
   ```

5. **Start the web process** from `/srv/crimegpt`:

   ```bash
   source .venv/bin/activate
   gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 4 --timeout 180 wsgi:app
   ```

6. **Start the Celery worker**:

   ```bash
   source .venv/bin/activate
   celery -A celery_app.celery worker --loglevel=info
   ```

7. **Start Celery Beat** for daily retention cleanup:

   ```bash
   source .venv/bin/activate
   celery -A celery_app.celery beat --loglevel=info
   ```

8. **Put a reverse proxy in front** of `127.0.0.1:8000`, enable TLS, preserve `Host` and `X-Forwarded-For`, and cap request bodies consistently with `MAX_CONTENT_LENGTH`.

9. **Verify the deployment**:

   ```bash
   curl --fail https://crimegpt.example.org/healthz
   ```

10. **Complete secure first-run setup:** sign in, change the administrator password, create the station, rotate enrollment, configure SMTP, review registration, confirm station quotas, and test a Celery system ping.

### Persistent data and backups

Back up these paths together so database references and files remain consistent:

- The database addressed by `DATABASE_URL`.
- `UPLOAD_FOLDER`.
- `GENERATED_FOLDER`.
- `.env` through a secrets-safe backup process.
- Any custom DOCX templates, locale files, statute fixtures, or station logos.

Do not run production with `memory://`: `task_service.py` intentionally marks jobs failed in production when a broker is unavailable instead of starting the development thread fallback.

## Contributing

Contributions are welcome when they preserve the project's core rule: AI can assist, but an authorised human owns every legal and operational decision.

1. Fork [the repository](https://github.com/shahram8708/CrimeGPT/fork).
2. Create a focused branch:

   ```bash
   git checkout -b feat/short-descriptive-name
   ```

3. Make the change in the correct layer: route handlers for HTTP flow, services for business rules, models for persistence, tasks for background execution, and templates/static files for presentation.
4. Preserve CSRF protection, station scoping, object-level authorisation, audit logging, legal disclaimers, and the service worker's sensitive-route exclusions.
5. Add tests under a new `tests/` directory and run:

   ```bash
   pytest -q
   python -m compileall -q app
   ```

6. Commit with an imperative message:

   ```bash
   git commit -m "Add case diary export coverage"
   ```

7. Push the branch and open a pull request against `main` with the problem, implementation, security impact, test evidence, and screenshots for UI changes.

No formatter or linter is configured. Follow the existing PEP 8-style Python, snake_case names, thin-route/service separation, Jinja inheritance, Bootstrap patterns, and dependency-free JavaScript style. Do not commit `.env`, case files, generated papers, database files, credentials, downloaded model weights, or real personal/legal data.

### Reporting bugs

Open a [GitHub issue](https://github.com/shahram8708/CrimeGPT/issues) without including real case data. A useful report follows this template:

```markdown
## Summary
A concise description of the problem.

## Environment
- OS and Python version:
- Browser:
- FLASK_ENV:
- SQLite and Redis/Celery setup:
- Commit SHA:

## Steps to reproduce
1.
2.
3.

## Expected behaviour
What should have happened.

## Actual behaviour
What happened, including a sanitised error reference or traceback.

## Security / data impact
State whether authorisation, personal data, evidence, or generated legal text is involved.

## Sanitised logs or screenshots
Remove names, identifiers, tokens, CR/FIR numbers, and evidence before attaching anything.
```

Report suspected security vulnerabilities privately to the commit-author email in [Contact / Author](#contact--author) rather than publishing exploit details.

### Requesting features

Open an issue that describes the station workflow, affected roles, legal or data-retention constraints, expected audit event, offline behaviour, and a clear acceptance test. Distinguish a UI improvement from a change to legal inference, because the latter needs authoritative-source review and stronger regression coverage.

## Roadmap

No `TODO`, `FIXME`, `XXX`, or `HACK` markers are present, and no formal roadmap is committed. The planned items below are therefore inferred from implemented features and concrete repository gaps, not promises from the maintainer.

- [x] Structured, station-scoped case pool with role-based access.
- [x] Evidence gallery, signed diary workflow, assignments, and export.
- [x] Local statutory fixtures, candidate section suggestions, checklists, and gap analysis.
- [x] English/Hindi/Gujarati PWA interface and multilingual court templates.
- [x] Background-job records, Redis/Celery dispatch, progress polling, retry, and development fallback.
- [x] Audit, quotas, station plans, account lifecycle, and SMTP logging.
- [ ] Add comprehensive unit, integration, authorisation, task, and browser tests.
- [ ] Pin dependencies and publish explicit Python compatibility and release versions.
- [ ] Connect the configured transformer, spaCy, embedding, translation, and FAISS paths—or remove unused heavyweight dependencies until they are implemented.
- [ ] Add robust rasterisation before Tesseract OCR for image-only PDF pages.
- [ ] Replace startup-time additive schema changes with reviewed Alembic migrations.
- [ ] Add Docker/Compose and CI for repeatable builds, tests, dependency review, and security scanning.
- [ ] Remove committed Celery Beat WAL/SHM artifacts and ignore the complete schedule-file family.
- [ ] Document or implement a portable search strategy before claiming non-SQLite database support.
- [ ] Expand the compact statute fixtures with verified source links, provenance metadata, update policy, and regression tests.

## License

No root `LICENSE` file or software-license declaration was found. That means the CrimeGPT source code is **not currently offered under an explicit open-source license**; copyright law reserves reuse, modification, and redistribution rights unless the rightsholder grants permission.

This is separate from `app/data/DATA_LICENSES.md`, which records the following dataset provenance:

- BNS 2023, BNSS 2023, and BSA 2023 material is derived from Official Gazette of India public-domain sources.
- Landmark-judgment fixtures contain curated public holdings, avoid proprietary reporter headnotes, and require verification.
- Operational playbook YAML files are original challenge material.

Add a recognised root license before describing the full repository as open source. Bootstrap and Marked retain their own license notices in the vendored files.

## Acknowledgements

- [Ahmedabad City Police](https://ahmedabadcitypolice.org/) and the Kanad S.H.I.E.L.D. Innovation Challenge 2026 for the station-documentation problem context.
- The [Ministry of Law and Justice, Government of India](https://legislative.gov.in/) for official BNS, BNSS, and BSA source material referenced by the bundled fixtures.
- The Supreme Court of India decisions represented by the curated, verification-required judgment metadata.
- [Flask](https://flask.palletsprojects.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [Celery](https://docs.celeryq.dev/), and [Redis](https://redis.io/) for the application and job foundation.
- [Bootstrap 5.3.3](https://getbootstrap.com/), [Marked 4.3.0](https://marked.js.org/), and the browser PWA APIs for the interface.
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract), [Pillow](https://python-pillow.org/), [pypdf](https://pypdf.readthedocs.io/), [python-docx](https://python-docx.readthedocs.io/), [docxtpl](https://docxtpl.readthedocs.io/), and [ReportLab](https://www.reportlab.com/) for document processing and generation.
- The local-model ecosystems declared by the project: [Qwen](https://qwenlm.github.io/), [spaCy](https://spacy.io/), [Hugging Face Transformers](https://huggingface.co/docs/transformers/), [Sentence Transformers](https://www.sbert.net/), and [FAISS](https://github.com/facebookresearch/faiss).

## Contact / Author

- **Repository:** [shahram8708/CrimeGPT](https://github.com/shahram8708/CrimeGPT)
- **Repository owner:** [@shahram8708](https://github.com/shahram8708)
- **Analyzed branch:** `main`
