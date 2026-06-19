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