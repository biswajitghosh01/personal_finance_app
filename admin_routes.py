import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from argon2 import PasswordHasher
from flask import Blueprint, abort, current_app, flash, has_app_context, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / 'instance' / 'finance.db'
admin_bp = Blueprint('admin', __name__)
password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def _db_path():
    if has_app_context():
        configured = current_app.config.get('FINANCE_DB_PATH')
        if configured:
            return Path(configured)
        return Path(current_app.root_path) / 'instance' / 'finance.db'
    return DEFAULT_DB_PATH


def _connect():
    connection = sqlite3.connect(_db_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    return connection


def _now():
    return datetime.now(timezone.utc).isoformat()


def ensure_admin_schema():
    with _connect() as connection:
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)').fetchall()}
        if not columns:
            raise RuntimeError('The users table is missing. Run init_db() before ensure_admin_schema().')
        if 'role' not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'USER'")
        if 'active' not in columns:
            connection.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
        if 'last_login' not in columns:
            connection.execute('ALTER TABLE users ADD COLUMN last_login TEXT')
        connection.execute("UPDATE users SET role='ADMIN',active=1 WHERE username=?", (os.getenv('DEFAULT_USER', 'admin'),))
        connection.commit()


def _current_user():
    username = session.get('username')
    if not username:
        return None
    ensure_admin_schema()
    with _connect() as connection:
        return connection.execute('SELECT id,username,role,active,created_at,last_login FROM users WHERE username=?', (username,)).fetchone()


def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if not user or not user['active']:
            session.clear()
            return redirect(url_for('login'))
        if user['role'] != 'ADMIN':
            abort(403)
        return function(*args, **kwargs)
    return wrapper


@admin_bp.app_context_processor
def admin_template_context():
    user = _current_user() if session.get('username') else None
    return {'current_portal_user': user, 'is_admin': bool(user and user['role'] == 'ADMIN' and user['active'])}


@admin_bp.get('/profile')
def profile():
    user = _current_user()
    if not user:
        return redirect(url_for('login'))
    return render_template('user_profile.html', user=user)


@admin_bp.get('/admin')
@admin_required
def dashboard():
    with _connect() as connection:
        users = connection.execute('SELECT id,username,role,active,created_at,last_login FROM users ORDER BY username').fetchall()
    return render_template('admin.html', users=users)


@admin_bp.post('/admin/users/add')
@admin_required
def add_user():
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    confirm = request.form.get('confirm') or ''
    role = request.form.get('role', 'USER')
    if not username or len(username) > 80:
        flash('Enter a valid username.', 'error')
    elif role not in {'ADMIN', 'USER'}:
        flash('Select a valid role.', 'error')
    elif password != confirm or len(password) < 14:
        flash('Passwords must match and contain at least 14 characters.', 'error')
    else:
        try:
            with _connect() as connection:
                connection.execute('INSERT INTO users(username,password_hash,must_change,failed,locked_until,created_at,role,active) VALUES(?,?,1,0,NULL,?,?,1)', (username, password_hasher.hash(password), _now(), role))
                connection.commit()
            flash('User created. A password change is required at next sign-in.', 'success')
        except sqlite3.IntegrityError:
            flash('That username already exists.', 'error')
    return redirect(url_for('admin.dashboard'))


@admin_bp.post('/admin/users/<int:user_id>/password')
@admin_required
def edit_password(user_id):
    password = request.form.get('password') or ''
    confirm = request.form.get('confirm') or ''
    if password != confirm or len(password) < 14:
        flash('Passwords must match and contain at least 14 characters.', 'error')
    else:
        with _connect() as connection:
            cursor = connection.execute('UPDATE users SET password_hash=?,must_change=1,failed=0,locked_until=NULL WHERE id=?', (password_hasher.hash(password), user_id))
            connection.commit()
        if not cursor.rowcount:
            abort(404)
        flash('Password reset. A password change is required at next sign-in.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.post('/admin/users/<int:user_id>/delete')
@admin_required
def delete_user(user_id):
    current = _current_user()
    if current['id'] == user_id:
        flash('You cannot delete the account currently signed in.', 'error')
        return redirect(url_for('admin.dashboard'))
    with _connect() as connection:
        target = connection.execute('SELECT id,role FROM users WHERE id=?', (user_id,)).fetchone()
        if not target:
            abort(404)
        if target['role'] == 'ADMIN':
            count = connection.execute("SELECT COUNT(*) FROM users WHERE role='ADMIN' AND active=1").fetchone()[0]
            if count <= 1:
                flash('The final active administrator cannot be deleted.', 'error')
                return redirect(url_for('admin.dashboard'))
        connection.execute('DELETE FROM users WHERE id=?', (user_id,))
        connection.commit()
    flash('User deleted.', 'success')
    return redirect(url_for('admin.dashboard'))


@admin_bp.get('/admin/health')
@admin_required
def health():
    status, integrity, counts = 'Healthy', 'Unknown', {}
    try:
        with _connect() as connection:
            connection.execute('SELECT 1').fetchone()
            integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
            tables = ('users', 'assets', 'bank_accounts', 'fixed_deposits', 'stocks', 'mutual_funds', 'metals', 'transactions', 'audit_log')
            existing = {row['name'] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                counts[table] = connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] if table in existing else None
    except sqlite3.Error:
        status = 'Unhealthy'
    encryption = 'Healthy'
    try:
        cipher = current_app.extensions.get('finance_cipher')
        if cipher:
            token = cipher.encrypt(b'health-check')
            if cipher.decrypt(token) != b'health-check':
                encryption = 'Unhealthy'
        else:
            encryption = 'Unavailable'
    except Exception:
        encryption = 'Unhealthy'
    db_path = _db_path()
    disk = shutil.disk_usage(db_path.parent)
    audit_logs = []
    try:
        with _connect() as connection:
            audit_logs = connection.execute(
                '''SELECT audit_log.event_time, audit_log.action, audit_log.entity_id,
                          audit_log.remote_addr, COALESCE(users.username, 'System') AS username
                   FROM audit_log
                   LEFT JOIN users ON users.id = audit_log.user_id
                   ORDER BY audit_log.id DESC
                   LIMIT 250'''
            ).fetchall()
    except sqlite3.Error:
        audit_logs = []

    file_logs = []
    log_path = Path(current_app.root_path) / 'logs' / 'finance.log'
    if log_path.exists() and log_path.is_file():
        try:
            with log_path.open('r', encoding='utf-8', errors='replace') as handle:
                file_logs = handle.readlines()[-250:]
        except OSError:
            file_logs = []

    data = {
        'database_status': status,
        'integrity': integrity,
        'encryption_status': encryption,
        'database_path': str(db_path),
        'database_size': db_path.stat().st_size if db_path.exists() else 0,
        'free_disk': disk.free,
        'python_version': sys.version.split()[0],
        'sqlite_version': sqlite3.sqlite_version,
        'session_timeout_minutes': int(current_app.permanent_session_lifetime.total_seconds() // 60),
        'counts': counts,
        'log_path': str(log_path),
    }
    return render_template(
        'admin_health.html',
        health=data,
        audit_logs=audit_logs,
        file_logs=file_logs,
    )
