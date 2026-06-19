# ACCIO — Full Azure Deployment Fix Prompt for Cline

## Context

This is the ACCIO Finance AR Ticketing System — a Flask web application with role-based access (User/Approver/Admin), ticket lifecycle management, file attachments, email notifications via Office365, and Excel exports.

The app currently works locally with SQLite. The goal is to make ALL changes needed so the app deploys cleanly to **Azure App Service** and runs entirely on Azure services. Local functionality is secondary — Azure must work perfectly.

The project root is the folder containing `app.py`, `requirements.txt`, and `Procfile`.

---

## OBJECTIVE

Make ALL of the following changes in one pass. Do not ask for confirmation between steps. Apply every change completely. After all changes, the app should:
- Connect to **Azure SQL Database** (via `SQLALCHEMY_DATABASE_URI` env var)
- Store/serve file attachments via **Azure Blob Storage** (via `AZURE_STORAGE_CONNECTION_STRING`)
- Send emails via Office365 SMTP (unchanged, via `MAIL_USERNAME` / `MAIL_PASSWORD`)
- Run on Azure App Service with `gunicorn` via `Procfile`
- Have all security hardening applied (session cookies, CSRF, password validation, token hashing)
- Have a working attachment download route

---

## CHANGE 1 — `requirements.txt` (REPLACE ENTIRE FILE)

```
Flask==3.0.3
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-WTF==1.2.1
Flask-Limiter==3.5.0
Werkzeug==3.0.3
python-dotenv==1.0.1
openpyxl==3.1.2
gunicorn==21.2.0
pyodbc==5.1.0
azure-storage-blob==12.19.0
python-magic==0.4.27
```

---

## CHANGE 2 — `runtime.txt` (REPLACE ENTIRE FILE)

```
python-3.12
```

---

## CHANGE 3 — `.env` (REPLACE ENTIRE FILE)

```
SECRET_KEY=dev-only-insecure-key-do-not-use-in-prod
FLASK_DEBUG=true
FLASK_ENV=development
MAIL_USERNAME=
MAIL_PASSWORD=
# Leave these blank for local dev — app will use SQLite and local file storage
SQLALCHEMY_DATABASE_URI=
AZURE_STORAGE_CONNECTION_STRING=
AZURE_STORAGE_CONTAINER=accio-uploads
```

---

## CHANGE 4 — `app/__init__.py` (REPLACE ENTIRE FILE)

```python
import os
import warnings
from flask import Flask, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
csrf = CSRFProtect()
limiter = Limiter(get_remote_address, default_limits=["500 per day", "100 per hour"], storage_uri="memory://")


def create_app(testing=False):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    instance_dir = os.path.join(os.path.dirname(base_dir), 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    app = Flask(__name__, static_folder='static', instance_path=instance_dir)

    # SECRET_KEY validation
    secret = os.getenv('SECRET_KEY')
    if not secret:
        env = os.getenv('FLASK_ENV', 'development')
        if env == 'production':
            raise RuntimeError("FATAL: SECRET_KEY environment variable is not set.")
        else:
            warnings.warn("SECRET_KEY not set. Using insecure default for development only.", stacklevel=2)
            secret = 'dev-only-insecure-key-do-not-use-in-prod'
    app.config['SECRET_KEY'] = secret

    # Session cookie security
    is_production = os.getenv('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SECURE'] = is_production
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True

    # Database — env var takes priority, SQLite fallback for local dev only
    default_db = 'sqlite:///' + os.path.join(instance_dir, 'ticketing.db')
    db_uri = os.getenv('SQLALCHEMY_DATABASE_URI') or default_db
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Azure SQL pool settings (only if using mssql)
    if 'mssql' in db_uri or 'pyodbc' in db_uri:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True,
            'pool_recycle': 1800,
            'pool_size': 5,
            'max_overflow': 10,
            'connect_args': {'timeout': 30}
        }

    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
    app.config['UPLOAD_FOLDER'] = os.path.join(instance_dir, 'uploads')
    app.config['MAIL_SERVER'] = 'smtp.office365.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['AZURE_STORAGE_CONNECTION_STRING'] = os.getenv('AZURE_STORAGE_CONNECTION_STRING', '')
    app.config['AZURE_STORAGE_CONTAINER'] = os.getenv('AZURE_STORAGE_CONTAINER', 'accio-uploads')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = User.query.get(int(user_id))
        if user is None:
            return None
        if not user.is_active:
            return None
        return user

    # Force password change guard
    @app.before_request
    def enforce_password_change():
        from flask_login import current_user
        allowed_endpoints = {'auth.force_change_password', 'auth.logout', 'static'}
        if (current_user.is_authenticated
                and current_user.must_change_password
                and request.endpoint not in allowed_endpoints):
            return redirect(url_for('auth.force_change_password'))

    # Rate limit exceeded handler
    from flask_limiter.errors import RateLimitExceeded

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        if request.is_json or request.path.startswith('/api'):
            return jsonify(error="Too many requests. Please try again later."), 429
        flash("Too many requests. Please wait a moment and try again.", "warning")
        return redirect(request.referrer or url_for('auth.login'))

    from app.routes.auth import auth_bp
    from app.routes.requester import req_bp
    from app.routes.approver import appr_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(req_bp)
    app.register_blueprint(appr_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        from app.models import User, IssueForm, Ticket, ApprovalLog, Notification, AdminAuditLog
        db.create_all()
        seed_database()

    return app


def seed_database():
    from app.models import User, IssueForm
    if User.query.first() is None:
        from werkzeug.security import generate_password_hash
        admin = User(
            email='admin@company.com',
            display_name='Admin',
            password_hash=generate_password_hash('Admin123'),
            role='admin',
            is_active=True,
            must_change_password=True
        )
        db.session.add(admin)
        db.session.commit()

    if IssueForm.query.first() is None:
        issue_types = [
            "Approved Price WF - Incorrect billing",
            "Approved Logistics WF - Logistics administrative cost",
            "Approved Logistics WF - Logistics Claim and compensation",
            "Approved Logistics WF - Logistics Container usage",
            "Approved Logistics WF - Logistics Customs duty",
            "Approved Logistics WF - Logistics Delivery cost",
            "Approved Logistics WF - Logistics Packaging",
            "Approved Logistics WF - Short of delivery",
            "Approved Price WF - OTP One time payment to customer",
            "Approved WF - Others",
            "Approved Price WF - Price adjustment for invoice",
            "Approved Price WF - Price change approved by BU",
            "Approved Price WF - Price discrepancy",
            "Approved Quality Logistics WF - Quality claim and compensation",
            "Approved Quality Logistics WF - Scrapping",
            "Approved Quality Logistics WF - Sorting cost",
            "Approved Quality Logistics WF - Warranty",
            "Approved Price WF - Quantity discrepancy item has not been delivered to the customer",
            "Approved Price WF - Rebate payment",
            "VAT issue",
            "Master Customer issue",
        ]
        default_fields_base = [
            {"name": "customer_name", "label": "Customer Name", "type": "text", "required": True, "options": ""},
            {"name": "customer_code", "label": "Customer Code", "type": "text", "required": True, "options": ""},
            {"name": "amount", "label": "Amount", "type": "number", "required": True, "options": ""},
            {"name": "currency", "label": "Currency", "type": "dropdown", "required": True,
             "options": "USD,EUR,GBP,INR,CNY,JPY,SGD,AUD,CAD,MYR,THB,VND"},
            {"name": "invoice_number", "label": "Invoice Number", "type": "text", "required": False, "options": ""},
            {"name": "invoice_date", "label": "Invoice Date", "type": "date", "required": False, "options": ""},
            {"name": "reference_notes", "label": "Reference Notes", "type": "text", "required": False, "options": ""},
        ]
        for name in issue_types:
            form = IssueForm(name=name, is_active=True, fields=default_fields_base)
            db.session.add(form)
        db.session.commit()
```

---

## CHANGE 5 — `app/utils/storage.py` (REPLACE ENTIRE FILE)

```python
import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'xlsx', 'xls', 'doc', 'docx', 'eml', 'msg'}
ALLOWED_MIMES = {
    'application/pdf', 'image/png', 'image/jpeg', 'image/gif',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel', 'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'message/rfc822', 'application/vnd.ms-outlook'
}


def allowed_file(file):
    """Validate file extension and optionally MIME type. Returns (is_valid, error_msg)."""
    filename = secure_filename(file.filename)
    if '.' not in filename:
        return False, 'File must have an extension.'
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f'File type .{ext} is not allowed.'
    try:
        import magic
        header = file.read(2048)
        file.seek(0)
        mime = magic.from_buffer(header, mime=True)
        if mime not in ALLOWED_MIMES:
            return False, f'File content type {mime} is not permitted.'
    except ImportError:
        pass  # fallback to extension-only validation if python-magic not available
    return True, None


def save_file(file):
    """
    Save uploaded file.
    - If AZURE_STORAGE_CONNECTION_STRING is set: uploads to Azure Blob Storage.
    - Otherwise: saves to local filesystem (dev only).
    Returns (original_filename, unique_name).
    """
    if not file or not file.filename:
        return None, None

    original_filename = secure_filename(file.filename)
    unique_name = f'{uuid.uuid4().hex}_{original_filename}'

    conn_str = current_app.config.get('AZURE_STORAGE_CONNECTION_STRING', '')
    container = current_app.config.get('AZURE_STORAGE_CONTAINER', 'accio-uploads')

    if conn_str:
        try:
            from azure.storage.blob import BlobServiceClient
            blob_service = BlobServiceClient.from_connection_string(conn_str)
            blob_client = blob_service.get_blob_client(container=container, blob=unique_name)
            file.seek(0)
            blob_client.upload_blob(file.read(), overwrite=True)
            current_app.logger.info(f'Uploaded blob: {unique_name} to container: {container}')
            return original_filename, unique_name
        except Exception as e:
            current_app.logger.error(f'Azure Blob upload failed: {e}')
            raise RuntimeError(f'File upload to Azure Blob failed: {e}')

    # Local filesystem fallback (development only)
    upload_folder = current_app.config['UPLOAD_FOLDER']
    filepath = os.path.join(upload_folder, unique_name)
    file.save(filepath)
    return original_filename, unique_name


def get_file_path(filename):
    """Get full local path for a stored file (dev fallback only)."""
    return os.path.join(current_app.config['UPLOAD_FOLDER'], filename)


def get_download_url(blob_name, original_name=None):
    """
    Returns a short-lived SAS URL for Azure Blob (production),
    or None if running locally.
    """
    conn_str = current_app.config.get('AZURE_STORAGE_CONNECTION_STRING', '')
    container = current_app.config.get('AZURE_STORAGE_CONTAINER', 'accio-uploads')

    if not conn_str:
        return None

    try:
        from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timezone, timedelta

        client = BlobServiceClient.from_connection_string(conn_str)
        account_name = client.account_name
        account_key = client.credential.account_key

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=1),
            content_disposition=f'attachment; filename="{original_name or blob_name}"'
        )
        return f'https://{account_name}.blob.core.windows.net/{container}/{blob_name}?{sas_token}'
    except Exception as e:
        current_app.logger.error(f'Failed to generate SAS URL: {e}')
        return None
```

---

## CHANGE 6 — `app/routes/auth.py` — PATCH TWO SECTIONS

### 6a. In the `forgot_password` route — patch reset token storage to store a SHA-256 hash

Find this block (in the `if user:` section of `forgot_password`):
```python
token = secrets.token_urlsafe(48)
user.reset_token = token
user.reset_token_expiry = ...
```

Replace with:
```python
import hashlib
token = secrets.token_urlsafe(48)
token_hash = hashlib.sha256(token.encode()).hexdigest()
user.reset_token = token_hash
user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
```

### 6b. In the `reset_password` route — patch token lookup to compare hash

Find:
```python
user = User.query.filter_by(reset_token=token).first()
```

Replace with:
```python
import hashlib
token_hash = hashlib.sha256(token.encode()).hexdigest()
user = User.query.filter_by(reset_token=token_hash).first()
```

---

## CHANGE 7 — `app/routes/requester.py` — PATCH THREE SECTIONS

### 7a. Fix `generate_ticket_number()` — replace entire function

Find and replace the entire `generate_ticket_number` function with:

```python
def generate_ticket_number():
    import secrets as _secrets
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    for attempt in range(10):
        count = Ticket.query.filter(
            Ticket.ticket_number.like(f'ACC-{today}-%')
        ).count()
        candidate = f'ACC-{today}-{count + 1:04d}'
        if not Ticket.query.filter_by(ticket_number=candidate).first():
            return candidate
    # Fallback: random suffix to avoid collision under high concurrency
    return f'ACC-{today}-{_secrets.token_hex(3).upper()}'
```

### 7b. Add attachment download route — add this new route at the END of the file (before any trailing code)

```python
@req_bp.route('/attachment/<int:ticket_id>')
@login_required
def download_attachment(ticket_id):
    """Serve ticket attachment — works for both Azure Blob and local storage."""
    from flask import abort, redirect, send_file
    from app.utils.storage import get_file_path, get_download_url
    import os

    ticket = Ticket.query.get_or_404(ticket_id)

    # Permission: only ticket creator, assigned approver, or admin
    if (current_user.id != ticket.created_by
            and current_user.id != ticket.assigned_to
            and current_user.role != 'admin'):
        abort(403)

    if not ticket.attachment_path:
        abort(404)

    # Azure Blob: redirect to time-limited SAS URL
    sas_url = get_download_url(ticket.attachment_path, ticket.attachment_name)
    if sas_url:
        return redirect(sas_url)

    # Local dev fallback
    filepath = get_file_path(ticket.attachment_path)
    if not os.path.exists(filepath):
        abort(404)
    return send_file(
        filepath,
        as_attachment=True,
        download_name=ticket.attachment_name or ticket.attachment_path
    )
```

### 7c. Add sanitize helper and patch export filename — find the export_tickets route in requester.py

Find the section where the download filename is built from date/status values (look for `filename = f'ACCIO_...`). Add a sanitizer before it and use it:

```python
import re

def _sanitize_filename_part(value, default='all'):
    return re.sub(r'[^a-zA-Z0-9_\-]', '', str(value or default))[:30]
```

Then update the filename construction to use `_sanitize_filename_part()` on any user-supplied query params.

---

## CHANGE 8 — `app/routes/admin.py` — PATCH TWO SECTIONS

### 8a. Add password validation to user creation route

In the admin user creation POST handler, find where a new `User` is created from form data. Before `db.session.add(new_user)`, insert:

```python
from app.routes.auth import validate_password_strength
errors = validate_password_strength(password)
if errors:
    for err in errors:
        flash(err, 'error')
    return redirect(url_for('admin.users'))
```

### 8b. Add manager validation to user creation/edit

When `manager_id` is set from form data, before assigning it to the user model, add:

```python
if manager_id:
    manager = User.query.filter_by(id=manager_id, is_active=True).first()
    if not manager or manager.role not in ('approver', 'admin'):
        flash('Invalid manager assignment. Manager must be an active approver or admin.', 'error')
        return redirect(url_for('admin.users'))
```

### 8c. Sanitize export filename in admin export route

Find the `export_tickets` route where the download filename is constructed using `from`, `to`, `status` query params. Apply sanitization:

```python
import re

def _sanitize_filename_part(value, default='all'):
    return re.sub(r'[^a-zA-Z0-9_\-]', '', str(value or default))[:30]

from_dt = _sanitize_filename_part(request.args.get('from'))
to_dt = _sanitize_filename_part(request.args.get('to'))
status_val = _sanitize_filename_part(request.args.get('status'))
filename = f'ACCIO_tickets_{from_dt}_to_{to_dt}_{status_val}.xlsx'
```

---

## CHANGE 9 — `app/routes/api.py` — REMOVE `@csrf.exempt` from notification endpoints

Find the two routes decorated with `@csrf.exempt` that are NOT the health check:
- `mark_all_read`
- `mark_one_read` (or similarly named notification-marking routes)

Remove `@csrf.exempt` from both of those routes. Keep `@csrf.exempt` only on the `health()` route.

---

## CHANGE 10 — `app/templates/base.html` — PATCH JS notification fetch calls

Find the JavaScript in `base.html` that calls the notification mark-as-read endpoints via `fetch()`. These calls must include the CSRF token header.

Find any `fetch('/api/notifications/...', { method: 'POST'` calls and add the CSRF token header. The CSRF token meta tag is already in the `<head>` as `<meta name="csrf-token" content="{{ csrf_token() }}">`.

Add this helper function to the notification JS section (near the top of the script block):

```javascript
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}
```

Then for every notification POST fetch call, add to the headers:
```javascript
'X-CSRFToken': getCsrfToken()
```

Example — find patterns like:
```javascript
fetch('/api/notifications/mark-all-read', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
```

And change to:
```javascript
fetch('/api/notifications/mark-all-read', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()
    }
```

Apply the same pattern to mark-one-read fetch calls.

---

## CHANGE 11 — Create `startup.sh` (NEW FILE in project root)

```bash
#!/bin/bash
# Azure App Service startup script
python -m flask db upgrade 2>/dev/null || true
gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 --access-logfile=- --error-logfile=- app:app
```

---

## CHANGE 12 — Update `Procfile` (REPLACE ENTIRE FILE)

```
web: gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 --access-logfile=- --error-logfile=- app:app
```

---

## CHANGE 13 — Create `.azure-env-template.txt` (NEW FILE in project root)

This is a reference file listing all Azure App Settings to configure. Do NOT put real values here.

```
# Copy these into Azure App Service > Configuration > Application Settings
# Fill in your actual values — never commit real secrets to source control

SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
FLASK_ENV=production
FLASK_DEBUG=false

# Azure SQL Database (get from Azure Portal > SQL Database > Connection strings > ODBC)
SQLALCHEMY_DATABASE_URI=mssql+pyodbc://<username>:<password>@<server>.database.windows.net/<dbname>?driver=ODBC+Driver+18+for+SQL+Server

# Office365 SMTP Email
MAIL_USERNAME=<your-office365-email@company.com>
MAIL_PASSWORD=<your-office365-app-password>

# Azure Blob Storage (get from Azure Portal > Storage Account > Access keys)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=<name>;AccountKey=<key>;EndpointSuffix=core.windows.net
AZURE_STORAGE_CONTAINER=accio-uploads

# Azure App Service sets PORT automatically — do not set this manually
```

---

## CHANGE 14 — Create `AZURE_DEPLOYMENT_STEPS.md` (NEW FILE in project root)

```markdown
# ACCIO — Azure Deployment Steps

## Step 1: Azure Resources to Create

Create these in Azure Portal in this order:

1. **Resource Group** — e.g. `rg-accio-prod`
2. **Azure SQL Database**
   - Server: create new, e.g. `accio-sql-server`
   - Database: `accio`
   - Tier: Serverless, General Purpose (cheapest)
   - Allow Azure services to access: YES
   - Note the connection string from Portal > SQL Database > Connection strings > ODBC
3. **Azure Storage Account**
   - Name: e.g. `acciostorage`
   - Redundancy: LRS
   - After creation: Create a blob container named `accio-uploads` (access level: Private)
   - Note the connection string from Portal > Storage Account > Access keys
4. **Azure App Service**
   - Runtime: Python 3.12
   - OS: Linux
   - Plan: B1 (Basic)
   - Region: same as your SQL and Storage

## Step 2: Configure App Settings in Azure Portal

Go to App Service > Configuration > Application Settings and add ALL keys from `.azure-env-template.txt`.

Key ones:
- `SECRET_KEY` — generate a long random string
- `FLASK_ENV` = `production`
- `FLASK_DEBUG` = `false`
- `SQLALCHEMY_DATABASE_URI` — Azure SQL ODBC connection string
- `MAIL_USERNAME` and `MAIL_PASSWORD`
- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_CONTAINER` = `accio-uploads`

## Step 3: Deploy the App

**Option A — ZIP Deploy (quickest for first deployment):**
```bash
# From project root
zip -r accio.zip . -x "*.pyc" -x "__pycache__/*" -x "instance/*" -x ".git/*" -x ".env"
az webapp deployment source config-zip --resource-group rg-accio-prod --name <your-app-name> --src accio.zip
```

**Option B — GitHub Actions (for ongoing CI/CD):**
- Go to App Service > Deployment Center > GitHub
- Connect your repo and branch
- Azure auto-generates a GitHub Actions workflow

## Step 4: Set Startup Command

In App Service > Configuration > General Settings:
```
gunicorn --bind=0.0.0.0:8000 --workers=2 --timeout=120 --access-logfile=- --error-logfile=- app:app
```

## Step 5: First-Time Database Initialization

The app auto-creates tables on first request via `db.create_all()` in `create_app()`.
On first load, the seed admin account is created:
- **Email:** admin@company.com
- **Password:** Admin123 (you will be forced to change this on first login)

## Step 6: Verify Everything Works

1. Visit your app URL — should see ACCIO login page
2. Login with admin@company.com / Admin123
3. Change password when prompted
4. Create a test ticket with a file attachment
5. Verify the attachment appears in your Azure Blob Storage container

## Cost Estimate (Monthly)
| Service | Tier | Est. Cost |
|---|---|---|
| App Service | B1 Linux | ~$13 |
| Azure SQL | Serverless | ~$5 |
| Azure Blob Storage | LRS | ~$1 |
| Email (Office365 SMTP) | Existing | $0 |
| **Total** | | **~$19–25/month** |
```

---

## FINAL VERIFICATION CHECKLIST FOR CLINE

After making all changes, verify:

- [ ] `requirements.txt` includes `pyodbc`, `azure-storage-blob`, `python-magic`, `gunicorn`
- [ ] `runtime.txt` says `python-3.12`
- [ ] `app/__init__.py` reads `SQLALCHEMY_DATABASE_URI` from env var (SQLite only as fallback)
- [ ] `app/__init__.py` sets `SESSION_COOKIE_HTTPONLY = True` and `SESSION_COOKIE_SAMESITE = 'Lax'`
- [ ] `app/__init__.py` sets `SESSION_COOKIE_SECURE = True` only when `FLASK_ENV == production`
- [ ] `app/utils/storage.py` uses Azure Blob when `AZURE_STORAGE_CONNECTION_STRING` is set
- [ ] `app/utils/storage.py` has `get_download_url()` function that generates SAS URLs
- [ ] `app/routes/requester.py` has `download_attachment` route with permission check
- [ ] `app/routes/requester.py` `generate_ticket_number()` uses retry loop with collision check
- [ ] `app/routes/auth.py` stores SHA-256 hash of reset token, not plaintext
- [ ] `app/routes/admin.py` validates password strength on user creation
- [ ] `app/routes/admin.py` validates manager assignment on user creation/edit
- [ ] `app/routes/admin.py` export filename is sanitized
- [ ] `app/routes/api.py` has `@csrf.exempt` ONLY on health check, NOT on notification endpoints
- [ ] `app/templates/base.html` notification fetch calls include `X-CSRFToken` header
- [ ] `Procfile` uses gunicorn with `--bind=0.0.0.0:8000`
- [ ] `.azure-env-template.txt` exists with all required env var names
- [ ] `AZURE_DEPLOYMENT_STEPS.md` exists with step-by-step Azure setup guide

