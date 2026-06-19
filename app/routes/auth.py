from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
import secrets

from app import db
from app.models import User

auth_bp = Blueprint('auth', __name__, url_prefix='/auth', template_folder='../templates/auth')


def role_required(*roles):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def validate_password_strength(password):
    errors = []
    if len(password) < 8:
        errors.append('Password must be at least 8 characters.')
    if not any(c.isupper() for c in password):
        errors.append('Password must contain at least one uppercase letter.')
    if not any(c.isdigit() for c in password):
        errors.append('Password must contain at least one number.')
    return errors


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect_to_dashboard()

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter your email and password.', 'error')
            return render_template('auth/login.html')

        user = User.query.filter_by(email=email).first()

        if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
            remaining = (user.locked_until - datetime.now(timezone.utc)).seconds // 60
            flash(f'Your account is locked due to too many failed attempts. Try again in {remaining} minutes, or contact your administrator.', 'error')
            return render_template('auth/login.html')

        if user and user.is_active and check_password_hash(user.password_hash, password):
            user.failed_attempts = 0
            user.locked_until = None
            db.session.commit()
            login_user(user)
            if user.must_change_password:
                return redirect(url_for('auth.force_change_password'))
            return redirect_to_dashboard()
        else:
            if user:
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= 5:
                    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=30)
                    db.session.commit()
                    flash('Your account has been locked due to too many failed login attempts. Try again in 30 minutes, or contact your administrator.', 'error')
                    return render_template('auth/login.html')
                db.session.commit()
                remaining = 5 - user.failed_attempts
                if remaining <= 3:
                    flash(f'{remaining} attempts remaining before account lockout.', 'warning')
                else:
                    flash('Invalid email or password.', 'error')
            else:
                flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Please enter your email address.', 'error')
            return render_template('auth/forgot_password.html')

        user = User.query.filter_by(email=email).first()
        if user:
            import hashlib
            token = secrets.token_urlsafe(48)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            user.reset_token = token_hash
            user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()

            from app.utils.email import send_email
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            subject = 'ACCIO — Password Reset Request'
            body_html = f"""
            <div style="font-family:'Inter',Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
                <div style="border-bottom:2px solid #01696f;padding-bottom:12px;margin-bottom:24px;">
                    <h1 style="color:#01696f;font-size:24px;margin:0;">ACCIO</h1>
                    <p style="color:#6b6a68;font-size:14px;margin:4px 0 0;">Finance AR Ticketing System</p>
                </div>
                <h2 style="color:#1a1917;font-size:18px;">Password Reset Request</h2>
                <p style="color:#6b6a68;font-size:14px;">Click the button below to reset your password. This link expires in 1 hour.</p>
                <p style="margin:24px 0;text-align:center;">
                    <a href="{reset_url}" style="display:inline-block;background:#01696f;color:white;text-decoration:none;padding:12px 32px;border-radius:8px;font-size:14px;font-weight:600;">Reset Password</a>
                </p>
                <p style="color:#b0afa9;font-size:12px;margin-top:32px;border-top:1px solid #e0e0e0;padding-top:16px;">If you did not request this, please ignore this email.</p>
            </div>
            """
            send_email(email, subject, body_html)

        flash('If an account exists with that email, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    import hashlib
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user = User.query.filter_by(reset_token=token_hash).first()

    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.now(timezone.utc):
        flash('This reset link is invalid or has expired.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        errors = validate_password_strength(password)
        if password != confirm:
            errors.append('Passwords do not match.')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('auth/reset_password.html', token=token)

        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expiry = None
        user.failed_attempts = 0
        user.locked_until = None
        user.must_change_password = False
        db.session.commit()

        flash('Password has been reset successfully. Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def force_change_password():
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        errors = validate_password_strength(new_password)
        if new_password != confirm:
            errors.append('Passwords do not match.')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('auth/force_change_password.html')

        current_user.password_hash = generate_password_hash(new_password)
        current_user.must_change_password = False
        db.session.commit()
        flash('Password updated successfully. Welcome to ACCIO!', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/force_change_password.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


def redirect_to_dashboard():
    role_redirects = {
        'user': 'req.dashboard',
        'approver': 'appr.queue',
        'admin': 'admin.dashboard'
    }
    target = role_redirects.get(current_user.role, 'req.dashboard')
    return redirect(url_for(target))