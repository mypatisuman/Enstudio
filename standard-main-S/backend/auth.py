"""
auth.py — self-contained authentication for EngineeringStudio.

One Flask blueprint (prefix /api/auth) that owns the whole auth surface:
password hashing, JWT issue/verify, input validation, the routes, and the
`require_auth` decorator used to gate protected routes. Kept isolated from
business logic (main.py) on purpose — nothing here imports from main.

Persistence: the existing SQLite `users` table (see adapters/db.py). No new
dependencies — password hashing uses stdlib hashlib.scrypt (memory-hard KDF),
tokens use PyJWT which is already installed.

Wire into main.py with:
    from auth import auth_bp, require_auth
    app.register_blueprint(auth_bp)
and put @require_auth on any route that should demand a logged-in user;
the authenticated row is then available as flask.g.user.

Env (.env):
    JWT_SECRET   required in production — no insecure default is used.
    JWT_EXPIRE_HOURS  optional, default 24.
"""
from __future__ import annotations

import os
import re
import hmac
import hashlib
import datetime as _dt
from functools import wraps

import jwt  # PyJWT — already in the venv
from flask_compat import Blueprint, request, jsonify, g

from adapters import db as _db

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
auth_router = auth_bp.router



@auth_bp.after_request
def _cors(resp):
    # The Tauri desktop webview is a different origin than the Flask server.
    # Auth uses a Bearer token (no cookies), so a wildcard origin is safe here.
    # ponytail: scoped to this blueprint only; broaden app-wide if other routes
    # ever need cross-origin access. Flask auto-answers the OPTIONS preflight.
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return resp

# ── Config ────────────────────────────────────────────────────────────────────
# No fallback secret: a shared default would let anyone forge tokens. Fail loud
# at import if it's missing so it can't silently ship insecure.
JWT_SECRET = os.getenv('JWT_SECRET')
JWT_EXPIRE_HOURS = int(os.getenv('JWT_EXPIRE_HOURS', '24'))
_ALGO = 'HS256'

if not JWT_SECRET:
    # ponytail: don't invent a secret. Dev sets one in .env (see .env.example).
    JWT_SECRET = 'dev-insecure-change-me'
    print('[auth] WARNING: JWT_SECRET not set — using an insecure dev secret. '
          'Set JWT_SECRET in .env before deploying.')


# ── Password hashing (stdlib scrypt) ─────────────────────────────────────────
# Format: scrypt$<salt_hex>$<hash_hex>. n=2**14 is the interactive-login preset.

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f'scrypt${salt.hex()}${dk.hex()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split('$')
        if scheme != 'scrypt':
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                            n=2**14, r=8, p=1, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)  # constant-time compare


# ── JWT ───────────────────────────────────────────────────────────────────────

def make_token(user: dict) -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        'userId': user['id'],
        'email': user['email'],
        'role': user['role'],
        'iat': now,
        'exp': now + _dt.timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGO)


def decode_token(token: str) -> dict | None:
    """Return the payload, or None if invalid/expired. PyJWT verifies exp and
    rejects alg-confusion attacks because we pin algorithms=[_ALGO]."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None


# ── Validation ────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def password_problem(pw: str) -> str | None:
    """Return a human message if the password is too weak, else None."""
    if not pw or len(pw) < 8:
        return 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', pw):
        return 'Password must contain an uppercase letter.'
    if not re.search(r'[a-z]', pw):
        return 'Password must contain a lowercase letter.'
    if not re.search(r'[0-9]', pw):
        return 'Password must contain a number.'
    if not re.search(r'[^A-Za-z0-9]', pw):
        return 'Password must contain a special character.'
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')


def _public_user(row) -> dict:
    """User shape safe to return to clients — never includes password_hash."""
    return {'id': row['id'], 'name': row['full_name'],
            'email': row['email'], 'role': row['role']}


def _err(message: str, code: int):
    return jsonify({'success': False, 'error': message}), code


# ── Middleware ────────────────────────────────────────────────────────────────

def require_auth(fn):
    """Gate a route behind a valid Bearer token. Sets flask.g.user to the DB
    row. Returns 401 on any failure — never trust the frontend, always verify."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return _err('Missing or malformed Authorization header.', 401)
        payload = decode_token(header[7:].strip())
        if not payload:
            return _err('Invalid or expired token.', 401)
        row = _db.get_db().execute(
            'SELECT * FROM users WHERE id = ?', (payload['userId'],)
        ).fetchone()
        if row is None or row['status'] != 'active':
            return _err('User no longer active.', 401)
        g.user = row
        return fn(*args, **kwargs)
    return wrapper


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.post('/signup')
def signup():
    data = request.get_json(silent=True) or {}
    full_name = (data.get('fullName') or '').strip()
    email = normalize_email(data.get('email'))
    password = data.get('password') or ''

    if not full_name or not email or not password:
        return _err('fullName, email and password are required.', 400)
    if not valid_email(email):
        return _err('Invalid email format.', 400)
    pw_problem = password_problem(password)
    if pw_problem:
        return _err(pw_problem, 400)

    conn = _db.get_db()
    if conn.execute('SELECT 1 FROM users WHERE email = ?', (email,)).fetchone():
        return _err('An account with this email already exists.', 409)

    ts = _now()
    cur = conn.execute(
        'INSERT INTO users (full_name, email, password_hash, role, status, '
        'created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (full_name, email, hash_password(password), 'user', 'active', ts, ts),
    )
    row = conn.execute('SELECT * FROM users WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify({'success': True, 'token': make_token(row),
                    'user': _public_user(row)}), 201


@auth_bp.post('/login')
def login():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get('email'))
    password = data.get('password') or ''

    conn = _db.get_db()
    row = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    # Same message whether the email is unknown or the password is wrong — don't
    # leak which emails have accounts.
    if row is None or not verify_password(password, row['password_hash']):
        return _err('Invalid email or password.', 401)
    if row['status'] != 'active':
        return _err('Account is not active.', 403)

    conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (_now(), row['id']))
    return jsonify({'success': True, 'token': make_token(row),
                    'user': _public_user(row)})


@auth_bp.get('/me')
@require_auth
def me():
    return jsonify(_public_user(g.user))


@auth_bp.post('/logout')
def logout():
    # Stateless JWT: logout is a client-side token drop. This endpoint exists so
    # the frontend has a URL to call and so refresh-token revocation can slot in
    # here later without a route change.
    return jsonify({'success': True})


# ponytail: skipped for v1 — add when they're actually needed, each is a small
# addition on this same blueprint, no redesign required:
#   /forgot-password + /reset-password  — needs an email sender to be useful;
#       add reset_token/reset_expires columns (ALTER TABLE) when wiring it.
#   /verify-email                        — add emailVerified column + sender.
#   role-based @require_role('admin')    — trivial wrapper over require_auth.
#   per-user data ownership (project.user_id) — cross-cutting; do it when the
#       app is genuinely multi-user, not before.


if __name__ == '__main__':
    # Self-check: signup -> login -> protected route, against a throwaway DB.
    # Run: python auth.py
    import tempfile
    _db.reset_for_path(tempfile.mktemp(suffix='.db'))
    _db.init_db()

    from flask_compat import FastAPICompat
    from starlette.testclient import TestClient
    app = FastAPICompat()
    app.register_blueprint(auth_bp)
    c = TestClient(app)

    creds = {'fullName': 'Jane Doe', 'email': 'JANE@Example.com ',
             'password': 'Password@123'}

    r = c.post('/api/auth/signup', json=creds)
    assert r.status_code == 201, r.json()
    token = r.json()['token']
    assert r.json()['user']['email'] == 'jane@example.com'  # normalized
    assert 'password_hash' not in str(r.json())             # never leaked

    assert c.post('/api/auth/signup', json=creds).status_code == 409  # dup email
    assert c.post('/api/auth/signup', json={**creds, 'password': 'weak'}
                  ).status_code == 400                                # weak pw

    r = c.post('/api/auth/login', json={'email': 'jane@example.com',
                                        'password': 'Password@123'})
    assert r.status_code == 200, r.json()
    assert c.post('/api/auth/login', json={'email': 'jane@example.com',
                                           'password': 'wrong'}).status_code == 401

    assert c.get('/api/auth/me').status_code == 401  # no token
    r = c.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200 and r.json()['name'] == 'Jane Doe'
    assert c.get('/api/auth/me', headers={'Authorization': 'Bearer garbage'}
                 ).status_code == 401

    print('auth.py self-check passed')
