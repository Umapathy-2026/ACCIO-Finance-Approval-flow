# ACCIO — Full Project Audit Report
**Finance AR Ticketing System | Code Review, Security & Feature Analysis**

---

## Table of Contents
1. [Critical Bugs](#1-critical-bugs)
2. [Logic Issues](#2-logic-issues)
3. [Security Vulnerabilities](#3-security-vulnerabilities)
4. [Architecture & Scalability Threats](#4-architecture--scalability-threats)
5. [Missing Features & UX Gaps](#5-missing-features--ux-gaps)
6. [Quick-Win Fixes Summary](#6-quick-win-fixes-summary)

---

## 1. Critical Bugs

These are things that are already broken or will silently fail right now.

---

### 🔴 BUG-01 — Broken "Review Ticket" Link in Email

**File:** `app/utils/email.py` → `send_ticket_created()`

```python
# CURRENT (BROKEN):
<a href="{ticket.ticket_number}" ...>Review Ticket</a>

# This renders as: href="ACC-20260615-0001" — a relative URL that goes nowhere.
```

**Also broken in `send_clarification_provided()`:**
```python
<a href="#" ...>Review Ticket</a>  # Just a "#"
```

**Fix:** Pass the full absolute URL to the email function.
```python
# In approver.py, when calling send_ticket_created:
from flask import url_for
review_url = url_for('appr.ticket_detail', ticket_id=ticket.id, _external=True)
send_ticket_created(ticket, approver.email, review_url)

# In email.py, accept and use the URL:
def send_ticket_created(ticket, approver_email, review_url):
    ...
    <a href="{review_url}" ...>Review Ticket</a>
```

---

### 🔴 BUG-02 — Ticket Number Race Condition (Duplicate IDs Under Load)

**File:** `app/routes/requester.py` → `new_ticket()`

```python
last_ticket = Ticket.query.filter(
    Ticket.ticket_number.like(f'ACC-{today_str}-%')
).order_by(Ticket.id.desc()).first()

if last_ticket:
    seq = int(last_ticket.ticket_number.split('-')[-1]) + 1
else:
    seq = 1

ticket_number = f'ACC-{today_str}-{seq:04d}'
```

Two concurrent submissions can both read the same `last_ticket`, compute the same `seq`, and attempt to insert the same `ticket_number`. SQLite may silently fail or raise an unhandled `IntegrityError`.

**Fix (Option A — Retry loop):**
```python
import time

for attempt in range(5):
    seq = (Ticket.query.filter(
        Ticket.ticket_number.like(f'ACC-{today_str}-%')
    ).count()) + 1
    ticket_number = f'ACC-{today_str}-{seq:04d}'
    try:
        # ... create ticket with this number
        db.session.commit()
        break
    except IntegrityError:
        db.session.rollback()
        time.sleep(0.05)
```

**Fix (Option B — UUID-based suffix, no collision):**
```python
import uuid
ticket_number = f'ACC-{today_str}-{uuid.uuid4().hex[:6].upper()}'
```

---

### 🔴 BUG-03 — Deactivated Users Remain Logged In

**File:** `app/__init__.py` → `load_user()`

```python
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))  # No is_active check
```

If an admin deactivates a user while they have an active session, they can continue using the app until the session naturally expires (30 minutes). For a finance system, this is unacceptable.

**Fix:**
```python
@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    if user and not user.is_active:
        return None  # Flask-Login treats None as "not authenticated"
    return user
```

---

### 🔴 BUG-04 — Bulk Action Sends No Email Notifications

**File:** `app/routes/approver.py` → `bulk_action()`

The bulk approve/reject creates in-app notifications but **never calls** `send_ticket_approved()` or `send_ticket_rejected()`. Requesters won't get email alerts when their tickets are bulk-processed.

```python
# Current — only in-app notification, NO email:
create_notification(ticket.created_by, 'Ticket Approved', ...)

# Fix — add email calls:
from app.utils.email import send_ticket_approved, send_ticket_rejected
if action == 'approve':
    ...
    send_ticket_approved(ticket)   # ADD THIS
else:
    ...
    send_ticket_rejected(ticket, log_comment)  # ADD THIS
```

---

### 🔴 BUG-05 — `Sent to Fulfilment` Status Is Never Actually Set

**File:** `app/models.py` and `app/routes/approver.py`

`TicketStatus.SENT_TO_FULFILMENT = 'Sent to Fulfilment'` exists in the enum, and the approval confirmation email says "approved and **sent to fulfilment**", but the route only sets status to `'Approved'`. The `Sent to Fulfilment` status is unreachable from any route in the app.

This creates a mismatch between what users see in the UI and what the email says. Either:
- Add a "Send to Fulfilment" action after approval, or
- Change the email body to not say "sent to fulfilment", or
- Auto-transition on approval: set status to `SENT_TO_FULFILMENT` instead of `APPROVED`

---

### 🟠 BUG-06 — Deactivation Doesn't Handle Approver's Assigned Tickets

**File:** `app/routes/admin.py` → `deactivate_user()` / `deactivate_user_check()`

```python
# Only checks tickets the user CREATED:
open_tickets = Ticket.query.filter(
    Ticket.created_by == user_id,   # ← wrong for approver deactivation
    ...
)
```

If an **approver** is deactivated, tickets **assigned to them** are never reassigned and remain orphaned — no one in the approver queue can see them. The deactivation check must also look at `assigned_to`:

```python
# Also check assigned tickets:
assigned_tickets = Ticket.query.filter(
    Ticket.assigned_to == user_id,
    Ticket.current_status.in_(['Pending', 'Under Review', 'Needs Clarification'])
).all()
```

---

### 🟠 BUG-07 — `datetime.utcnow()` Deprecated in Python 3.12+

**Files:** `app/models.py`, `app/routes/` (multiple)

The entire codebase uses `datetime.utcnow()`, which is deprecated in Python 3.12 and will show `DeprecationWarning` on every call. Since the deployment plan targets **Python 3.13**, this is a noise issue now and a potential break later.

**Fix — Replace all occurrences:**
```python
# Old:
from datetime import datetime
datetime.utcnow()

# New:
from datetime import datetime, timezone
datetime.now(timezone.utc)
```

---

## 2. Logic Issues

Issues that don't crash the app but produce wrong behavior.

---

### 🟠 LOGIC-01 — `Reassigned` Action Missing from Enum

**Files:** `app/routes/approver.py`, `app/routes/admin.py`

```python
# Hardcoded string — not in ApprovalAction enum:
log = ApprovalLog(action='Reassigned', ...)
```

`ApprovalAction` enum doesn't include `REASSIGNED`. The timeline will display it correctly but any code that checks `action == ApprovalAction.SUBMITTED.value` etc. won't match reassignment logs consistently.

**Fix:** Add to enum:
```python
class ApprovalAction(str, enum.Enum):
    ...
    REASSIGNED = 'Reassigned'
```

---

### 🟠 LOGIC-02 — `updated_at` Not Set on Status Changes

**File:** `app/models.py`

```python
updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
```

SQLAlchemy's `onupdate` only fires when an ORM attribute on the object is modified. It does **not** fire when you do bulk updates like:
```python
Notification.query.filter_by(...).update({'is_read': True})
```

For tickets, when status changes in `approve_ticket()`, `updated_at` should be set explicitly:
```python
ticket.current_status = TicketStatus.APPROVED.value
ticket.updated_at = datetime.utcnow()  # Force it
```

---

### 🟠 LOGIC-03 — Approver Can't View Their Resolved/Historical Tickets

The approver queue only shows `Pending` and `Under Review` tickets. Once a ticket is approved, rejected, or sent back, it disappears from the approver's view entirely. Approvers have no way to review their decision history or look up a past case.

**Fix:** Add a "Resolved" tab to the approver queue with search/filter for `Approved`, `Rejected`, `Sent to Fulfilment` tickets where `assigned_to == current_user.id`.

---

### 🟠 LOGIC-04 — Admin Has No "All Tickets" List View

The admin dashboard shows only the last 10 recent tickets and a KPI summary. There is no paginated, filterable "All Tickets" view for admins. To find a specific old ticket, the admin must export to Excel.

**Fix:** Add `/admin/tickets` route with full table + filters, similar to the approver queue.

---

### 🟠 LOGIC-05 — Single Attachment Limitation

```python
# Only ONE main attachment column:
attachment_name = db.Column(db.String(255), nullable=True)
attachment_path = db.Column(db.String(500), nullable=True)
```

Finance tickets often require multiple supporting documents (invoice, PO, email trail). Only one main attachment is supported at the model level. The `payload` field handles per-form-field files, but there's no UI for uploading multiple general attachments.

---

### 🟠 LOGIC-06 — Approver Fallback Assignment Is Too Naive

```python
# Fallback: find first active approver in DB:
approver = User.query.filter_by(role='approver', is_active=True).first()
```

If a user has no manager set, their ticket gets assigned to whichever approver happens to be first in the database. This could be:
- An unrelated approver
- An overloaded approver
- A completely wrong team member

**Fix:** At minimum, validate that every user has a manager assigned before they can submit tickets. Or implement a proper round-robin / workload-balanced assignment.

---

### 🟠 LOGIC-07 — Tailwind CSS CDN is Development-Only

```html
<script src="https://cdn.tailwindcss.com"></script>
```

This CDN version uses an in-browser JIT compiler (~350KB). It is explicitly [not recommended for production](https://tailwindcss.com/docs/installation/play-cdn) by Tailwind. It's slow, causes FOUC (flash of unstyled content), and the CDN may change behaviour.

**Fix:** Run `npx tailwindcss` CLI to generate a purged, minimal CSS file and serve it as a static asset.

---

### 🟠 LOGIC-08 — Lucide Icons Pinned to `@latest`

```html
<script src="https://unpkg.com/lucide@latest"></script>
```

`@latest` means a breaking change to the Lucide library could silently break your icons on any deployment. Pin to a specific version:
```html
<script src="https://unpkg.com/lucide@0.383.0/dist/umd/lucide.min.js"></script>
```

---

## 3. Security Vulnerabilities

Ordered by severity for a finance internal application.

---

### 🔴 SEC-01 — No CSRF Protection (Critical)

**Severity: HIGH**

There is no CSRF token in any form. `Flask-WTF` or `Flask-SeaSurf` is not in `requirements.txt`. Every state-changing form (login, ticket creation, approve, reject, reassign, user management) is vulnerable to Cross-Site Request Forgery.

A malicious email containing `<img src="https://accio.company.com/approver/ticket/42/approve">` could silently approve a ticket when an approver views it.

**Fix:**
```bash
pip install Flask-WTF
```
```python
# app/__init__.py:
from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect()
csrf.init_app(app)

# Every form template:
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>

# API JSON endpoints — exempt explicitly:
@csrf.exempt
@api_bp.route('/notifications/mark-read', methods=['POST'])
```

---

### 🔴 SEC-02 — No Security HTTP Headers (Clickjacking, XSS, MIME Sniffing)

**Severity: HIGH**

No HTTP security headers are set anywhere. For a finance application this is a significant gap:

| Missing Header | Risk |
|---|---|
| `X-Frame-Options: DENY` | Clickjacking — attacker can embed your app in an iframe |
| `X-Content-Type-Options: nosniff` | MIME-type confusion attacks |
| `Content-Security-Policy` | XSS via inline scripts or CDN compromise |
| `Strict-Transport-Security` | Forces HTTPS, prevents downgrade attacks |
| `Referrer-Policy: same-origin` | Leaks URLs in referer headers |

**Fix:**
```python
# app/__init__.py, after creating the app:
from flask_talisman import Talisman  # pip install flask-talisman

csp = {
    'default-src': "'self'",
    'script-src': ["'self'", 'cdn.tailwindcss.com', 'unpkg.com', 'fonts.googleapis.com'],
    'style-src': ["'self'", "'unsafe-inline'", 'fonts.googleapis.com'],
    'font-src': ["'self'", 'fonts.gstatic.com'],
}
Talisman(app, content_security_policy=csp, force_https=False)  # Set force_https=True in prod
```

---

### 🔴 SEC-03 — Hardcoded Default Admin Credentials

**Severity: HIGH**

```python
# seed_database():
password_hash=generate_password_hash('Admin@123'),
```
```
# User Guide section:
Default: admin@company.com / Admin@123
```

If deployed without rotating these credentials, any internal user who reads the docs can access the admin account. For a finance system, this is unacceptable.

**Fix:** Force password change on first login:
```python
# Add to User model:
must_change_password = db.Column(db.Boolean, default=False)

# In seed_database:
admin.must_change_password = True

# In load_user or a @before_request:
@app.before_request
def check_password_change():
    if current_user.is_authenticated and current_user.must_change_password:
        if request.endpoint not in ('auth.reset_password', 'auth.logout', 'static'):
            return redirect(url_for('auth.force_change_password'))
```

---

### 🔴 SEC-04 — Insecure Fallback SECRET_KEY

**Severity: HIGH**

```python
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')
```

If `SECRET_KEY` is missing from the environment (e.g., misconfigured deployment), the app silently runs with a known, public default key. All sessions are then forgeable.

**Fix — Fail loudly in production:**
```python
secret = os.getenv('SECRET_KEY')
if not secret:
    raise RuntimeError("SECRET_KEY environment variable must be set in production!")
app.config['SECRET_KEY'] = secret
```

---

### 🟠 SEC-05 — File Upload: No MIME Type Validation

**Severity: MEDIUM**

```python
ALLOWED_EXTENSIONS = {'txt', 'pdf', ..., 'zip'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
```

This checks only the **file extension**, not the actual content. A user can rename `malware.exe` to `malware.pdf` and upload it. Also, `zip` in the allowed list enables zip-bomb attacks.

**Fix:**
```python
import magic  # pip install python-magic

def allowed_file_with_mime(file):
    filename = file.filename
    if not ('.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS):
        return False
    # Read first 2KB for MIME detection
    header = file.read(2048)
    file.seek(0)  # Reset for actual save
    mime = magic.from_buffer(header, mime=True)
    ALLOWED_MIMES = {'application/pdf', 'image/jpeg', 'image/png', 'application/vnd.ms-excel', ...}
    return mime in ALLOWED_MIMES

# Also remove 'zip' from ALLOWED_EXTENSIONS or add zip bomb detection
```

---

### 🟠 SEC-06 — HTML Injection in Email Bodies

**Severity: MEDIUM**

User-controlled content is directly f-string interpolated into HTML email bodies without escaping:
```python
# email.py:
body_html = f"""
...{ticket.subject}...
{ticket.creator.display_name}...
{reason}...  # ← This is user input from the rejection comment form
"""
```

If `reason` is `<b>Click <a href="http://evil.com">here</a> for your prize</b>`, it renders as HTML in the email. While email clients don't execute scripts, this enables phishing via styled malicious links in official ACCIO emails.

**Fix:**
```python
from markupsafe import escape

def send_ticket_rejected(ticket, reason):
    safe_reason = escape(reason)  # HTML-encodes < > & etc.
    body_html = f"...{safe_reason}..."
```

---

### 🟠 SEC-07 — `debug=True` in Entry Point

**Severity: MEDIUM**

```python
# app.py:
if __name__ == '__main__':
    app.run(debug=True, port=5000)
```

While production will use Gunicorn (which ignores this), anyone who starts the app with `python app.py` in a staging or production environment gets a live Werkzeug debugger with a **Python REPL accessible over the network** — full server compromise.

**Fix:**
```python
import os
debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
app.run(debug=debug_mode, port=5000)
```

---

### 🟠 SEC-08 — No Rate Limiting on Any Endpoint

**Severity: MEDIUM**

No rate limiting exists on:
- `/auth/login` — brute-force beyond the lockout (e.g., attacking multiple accounts)
- `/auth/forgot-password` — email spam to any valid address
- `/api/notifications` — polled every 60s per user, can be abused to hammer the DB

**Fix:**
```bash
pip install Flask-Limiter
```
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login(): ...

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def forgot_password(): ...
```

---

### 🟡 SEC-09 — Weak Password Policy

**Severity: LOW–MEDIUM**

Current requirements: 8 characters, 1 uppercase, 1 number. No special character, no common-password check. For a finance approval system that handles billing and AR adjustments, NIST SP 800-63B recommends at least 12 characters and checking against known-breached password lists.

**Suggested minimum for finance:**
- 12+ characters
- At least 1 uppercase, 1 lowercase, 1 number, 1 special character
- Block obvious passwords (`Password1`, `Company@123`)

---

### 🟡 SEC-10 — Sensitive Filter Parameters Exposed in URL

**Severity: LOW**

```
GET /admin/export?from=2026-01-01&to=2026-06-15&status=Approved
```

Date ranges and status filters for financial data exports appear in URLs, which are logged in server access logs, browser history, and may appear in HTTP `Referer` headers. Use POST for export triggering or at least ensure access logs are protected.

---

## 4. Architecture & Scalability Threats

These won't hurt you today but will become serious as usage grows.

---

### ⚠️ ARCH-01 — Client-Side Pagination Won't Scale

**All** filtering, sorting, and pagination is done in the browser after loading the full dataset from the server:

```javascript
// dashboard.html:
document.querySelectorAll('#reqBody tr').forEach(function(row) {
    reqTickets.push({ html: row.outerHTML, ... });
});
```

This means **every page load fetches every ticket from the DB and renders every row to HTML**. At 100 tickets this is fine. At 10,000 tickets, the page will be unusable (5+ second load, 10MB+ HTML payload).

**Fix (Phased):**
1. Short-term: Add `.limit(500)` server-side as a safety cap
2. Medium-term: Convert to server-side pagination with AJAX — the `/api/` blueprint is already there, extend it:
   ```
   GET /api/tickets?page=1&per_page=20&status=Pending&search=ACC-20260615
   ```

---

### ⚠️ ARCH-02 — Notification Polling Creates Constant DB Load

```javascript
setInterval(loadNotifications, 60000);  // Every 60s, per user
```

For 50 concurrent users, this is 50 DB queries/minute just for notifications. For 200 users, that's over 3 queries/second doing nothing productive.

**Better approaches (in order of effort):**
1. **Server-Sent Events (SSE):** Push notifications from server to client — one persistent connection, no polling
2. **WebSockets (Flask-SocketIO):** Full duplex, better for real-time
3. **Increase polling interval to 5 minutes** — immediate fix with minimal code change

---

### ⚠️ ARCH-03 — Synchronous Email Sending Blocks Requests

```python
# requester.py:
send_ticket_created(ticket, approver.email)  # ← SMTP call blocks here
flash(f'Ticket {ticket_number} created successfully!', 'success')
```

If the Office 365 SMTP server is slow, times out, or is unavailable:
- The user's ticket creation request hangs for 30+ seconds
- Flask's built-in server will drop the request
- The ticket is saved but the user sees an error, possibly resubmitting (duplicate)

**Fix — Async email with a task queue:**
```python
# With Celery + Redis (or Azure Service Bus):
@celery.task
def async_send_email(to_email, subject, body_html):
    send_email(to_email, subject, body_html)

# In route:
async_send_email.delay(approver.email, subject, body_html)
flash('Ticket created!', 'success')  # Returns immediately
```

---

### ⚠️ ARCH-04 — No Audit Log for Admin Actions

`ApprovalLog` tracks ticket lifecycle events, but **no administrative action is logged**:
- User created, edited, deactivated
- Form enabled/disabled, fields changed
- Export triggered (who exported what data, when)

For a finance application, this is a compliance gap. If there's ever a dispute or an audit, you have no record of who changed what in the admin panel.

**Fix:** Create an `AdminAuditLog` model:
```python
class AdminAuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100))   # e.g., 'USER_DEACTIVATED'
    target_type = db.Column(db.String(50))  # 'user', 'form'
    target_id = db.Column(db.Integer)
    details = db.Column(db.JSON)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
```

---

### ⚠️ ARCH-05 — No Health Check Endpoint

There is no `/health` or `/ping` route. Azure App Service and load balancers need a health endpoint to determine if the app is alive. Without it, unhealthy instances won't be detected.

**Fix (add to `api.py`):**
```python
@api_bp.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok', 'db': 'connected'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'db': str(e)}), 503
```

---

### ⚠️ ARCH-06 — SQLite Concurrent Write Limitation

SQLite allows only one writer at a time. The moment you deploy to Azure App Service with >1 worker (or deploy even 1 worker and get concurrent requests), you risk `database is locked` errors on ticket creation (which does multiple writes in sequence). This is the primary reason the Azure migration to SQL Server is important — don't delay it.

**Until migration:** Run Gunicorn with `--workers 1` and `--threads 4`:
```bash
gunicorn --bind=0.0.0.0:8000 --workers=1 --threads=4 app:app
```

---

### ⚠️ ARCH-07 — No Data Retention / Archival Strategy

All tickets live in a single table forever. After 3–5 years of operation with potentially hundreds of tickets per month, query performance will degrade without indexes and archival.

**Recommended actions:**
1. Add composite indexes: `(assigned_to, current_status)`, `(created_by, current_status)`, `(created_at)`
2. Define a retention policy: e.g., archive tickets older than 2 years to cold storage
3. Consider soft-delete instead of hard-delete if any deletion is ever needed

---

### ⚠️ ARCH-08 — External CDN Dependencies (Corporate Network Risk)

Three external CDN resources are loaded on every page:
```html
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter...">
<script src="https://unpkg.com/lucide@latest"></script>
```

In a corporate environment (especially one that eventually moves to Azure with network security groups), these external calls may be blocked by firewall rules. The app would then render without any styling or icons.

**Fix:** Bundle all assets locally:
- Run Tailwind CLI to generate `static/css/tailwind.min.css`
- Download and serve Inter font from `static/fonts/`
- Download `lucide.min.js` to `static/js/`

---

## 5. Missing Features & UX Gaps

Features that would bring ACCIO to parity with market ticketing systems.

---

### Priority P1 (Core Workflow Gaps)

| ID | Feature | Why |
|---|---|---|
| F-01 | **Ticket Edit / Withdrawal** | Requester can't fix a typo or withdraw a wrong submission |
| F-02 | **Admin "All Tickets" View** | No way to browse all tickets without exporting to Excel |
| F-03 | **Approver History View** | Resolved tickets disappear from approver's view entirely |
| F-04 | **Multiple Attachments** | Finance tickets need several supporting documents |
| F-05 | **Priority Field** | No way to flag urgent tickets (Critical/High/Normal/Low) |
| F-06 | **SLA / Due Date** | No deadline tracking; no escalation alerts |
| F-07 | **Sent to Fulfilment Workflow** | Status exists in model but is never reachable |

---

### Priority P2 (UX & Collaboration)

| ID | Feature | Why |
|---|---|---|
| F-08 | **Ticket Comments / Thread** | Currently only approval actions; no general discussion space |
| F-09 | **Watchers / CC** | Can't add a colleague to follow a ticket |
| F-10 | **@Mentions in Comments** | Tag a specific person for input |
| F-11 | **Rich Text Description** | Plain textarea for financial issues is limiting; needs bold, lists, tables |
| F-12 | **Search by Payload Fields** | Can't filter by customer name, invoice number, or amount |
| F-13 | **Ticket Duplication** | Can't clone a similar previous ticket |
| F-14 | **Saved Filters** | Can't save "my pending invoices over $10k" as a filter preset |

---

### Priority P3 (Reporting & Analytics)

| ID | Feature | Why |
|---|---|---|
| F-15 | **Dashboard Charts** | KPI cards exist but no trend charts (tickets/week, approval rate) |
| F-16 | **Approver Workload View** | Admin can't see queue depth per approver |
| F-17 | **SLA Compliance Report** | What % of tickets resolved within X days |
| F-18 | **Amount-Based Analytics** | Total AR value pending approval, approved by period |
| F-19 | **Email Notification Preferences** | Users can't control which emails they receive |

---

### Priority P4 (System & Ops)

| ID | Feature | Why |
|---|---|---|
| F-20 | **Audit Log UI** | Expose admin audit log from ARCH-04 in the admin panel |
| F-21 | **Multi-level Approval** | Some finance approvals may need CFO sign-off above manager |
| F-22 | **Async Email Queue** | From ARCH-03 — prevents hanging requests |
| F-23 | **Server-Side Pagination API** | From ARCH-01 — scalability |
| F-24 | **PWA / Mobile Optimization** | Sidebar hides on mobile but no mobile-first layout exists |
| F-25 | **Dark Mode** | Modern internal apps offer this; reduces eye strain |

---

## 6. Quick-Win Fixes Summary

Things you can fix in under 2 hours with the highest impact:

| Priority | Fix | Effort |
|---|---|---|
| 🔴 CRITICAL | Fix email "Review Ticket" URL (BUG-01) | 15 min |
| 🔴 CRITICAL | Add `is_active` check to `load_user` (BUG-03) | 5 min |
| 🔴 CRITICAL | Add `send_ticket_approved/rejected` to bulk action (BUG-04) | 20 min |
| 🔴 HIGH | Add CSRF protection via Flask-WTF (SEC-01) | 1–2 hrs |
| 🔴 HIGH | Remove hardcoded `debug=True` fallback (SEC-07) | 5 min |
| 🔴 HIGH | Add SECRET_KEY validation on startup (SEC-04) | 10 min |
| 🟠 MEDIUM | Add `flask-talisman` security headers (SEC-02) | 30 min |
| 🟠 MEDIUM | Set explicit `ticket.updated_at` on status changes (LOGIC-02) | 30 min |
| 🟠 MEDIUM | Add `REASSIGNED` to `ApprovalAction` enum (LOGIC-01) | 5 min |
| 🟠 MEDIUM | Fix deactivation to also reassign approver's tickets (BUG-06) | 45 min |
| 🟡 QUICK | Add `/api/health` endpoint (ARCH-05) | 10 min |
| 🟡 QUICK | Pin Lucide to a specific version (LOGIC-08) | 2 min |
| 🟡 QUICK | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` (BUG-07) | 20 min |

---

*Report generated: 15 June 2026*
*Codebase: ACCIO v2, Finance AR Ticketing System (Flask 3.0.3, Python 3.13)*
