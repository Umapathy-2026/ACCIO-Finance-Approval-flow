Current state after 2026-06-23 security fixes
- SECRET_KEY handling: No fallback string. App now requires SECRET_KEY to be set via environment. If missing, create_app raises RuntimeError with a clear message. Session cookies stay secure/httponly with SameSite=Lax; secure flag depends on FLASK_ENV.
- Dev-only seeding: seed_database() only runs when FLASK_ENV == "development". The seeded admin’s temporary password is generated using secrets.token_urlsafe(16) and logged to console with a [SETUP] prefix. must_change_password is set to True.
- Excel formula injection mitigations: In requester export, added sanitize_cell(value) and applied to all user-controlled strings before writing to Excel cells (ticket details, payload values, and approval history rows). Static headers unaffected.
- Silent exceptions: Admin export date parsing uses explicit except Exception as e with current_app.logger.warning to log invalid dates (no bare except: pass remain in the indicated areas).
- Test artifact: check.py now reads admin password from TEST_ADMIN_PASSWORD env var; project .gitignore includes check.py to avoid committing test credentials.

Other notable context
- Tech stack and dependency versions pinned in requirements.txt (Flask 3.0.3, Flask-Limiter 3.5.0, openpyxl 3.1.2, etc.).
- App follows the factory pattern; blueprints for auth, requester, approver, admin, api are registered in create_app.
- Database auto-creates tables on startup (no migrations). SQLite used by default via instance folder unless SQLALCHEMY_DATABASE_URI provided (supports Azure SQL via pyodbc).
- Email and file storage utilities encapsulated in app/utils; Azure Blob integration optional via env vars.
- Local development now expects a .env file. wsgi.py loads environment variables via python-dotenv (load_dotenv()), so set SECRET_KEY and FLASK_ENV in .env for local runs.

What changed today and why
- Enforced environment-based SECRET_KEY to eliminate hardcoded secrets in production (Bandit/Snyk rule).
- Restricted seeding to development and replaced static admin password to prevent default credential exposure.
- Added Excel cell sanitization to prevent CSV/Excel injection by maliciously crafted input.
- Replaced silent exception patterns with logged warnings to aid observability and avoid hidden failures.
- Removed hardcoded test credentials from check.py to align with secure testing practices.

Known issues / TODOs
- No migration framework; schema changes require manual handling.
- Rate limiter uses in-memory storage, which may not be suitable for multi-instance production.
- Email sending may fail in low-permission environments; already wrapped in try/except with logging in requester routes.