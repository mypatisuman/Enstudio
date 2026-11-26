"""
security.py — Phase 0 security primitives for EngineeringStudio.

Two concerns, deliberately kept in one small module so there is exactly one
place to audit:

  1. `validate_pid` / `safe_project_dir` — project-id validation and safe
     path construction. Every filesystem operation keyed by a user-supplied
     project id must go through these.

  2. `install_api_auth_guard` — a fail-closed `before_request` hook that
     requires a valid Bearer token for every `/api/*` route except the auth
     blueprint itself. Reuses auth.py's existing JWT verification; this
     module deliberately does NOT implement any authentication of its own.

Why a blanket guard instead of ~40 `@require_auth` decorators: a decorator
has to be remembered on every new route, and the route table in main.py is
still growing. A default-deny hook cannot be forgotten, and the exemption
list is short enough to read in one screen.

WHY PID VALIDATION MATTERS (this is not theoretical)
----------------------------------------------------
`pathlib` and Rust's `Path::join` both DISCARD the left-hand side when the
right-hand component is absolute or drive-qualified. On Windows:

    Path('C:/hub/projects') / '..'          -> C:\\hub          (escapes)
    Path('C:/hub/projects') / 'C:/Windows'  -> C:\\Windows      (escapes)
    Path('C:/hub/projects') / r'\\\\srv\\shr'  -> \\\\srv\\shr  (escapes)

`DELETE /api/projects/<pid>` calls `shutil.rmtree` on exactly that join, so
an unvalidated pid is a remote directory-deletion primitive. Flask's default
string converter rejects `/` but happily accepts `..`, `.`, `C:`, and
backslashes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# A project id is a slug: ASCII letters, digits, underscore, hyphen, dot —
# but never a leading dot (blocks '.', '..', and dotfiles), never a bare
# drive letter, and bounded in length. This is an allowlist: anything not
# explicitly permitted is rejected, so new traversal tricks fail closed.
_PID_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$')

# Reserved Windows device names — a project directory called "CON" or "NUL"
# turns ordinary file I/O into device I/O.
_WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


class InvalidPid(ValueError):
    """Raised when a project id fails validation. Callers map this to HTTP 400."""


def validate_pid(pid: str) -> str:
    """Return `pid` unchanged if it is a safe project id, else raise InvalidPid.

    Rejects: empty, over-long, path separators, '..', leading dots, drive
    letters, UNC prefixes, NUL bytes, and Windows reserved device names.
    """
    if not isinstance(pid, str) or not pid:
        raise InvalidPid('project id must be a non-empty string')
    if '\x00' in pid:
        raise InvalidPid('project id contains a NUL byte')
    if not _PID_RE.match(pid):
        raise InvalidPid(
            f'invalid project id {pid[:64]!r} — allowed: letters, digits, '
            f'"_", "-", "."; must start with a letter, digit or "_"; max 64 chars'
        )
    if pid.upper().split('.')[0] in _WINDOWS_RESERVED:
        raise InvalidPid(f'{pid!r} is a reserved device name')
    return pid


def safe_project_dir(projects_dir: Path, pid: str) -> Path:
    """`<projects_dir>/<pid>`, validated and containment-checked.

    Belt and braces: `validate_pid` already makes an escape impossible, and
    then the resolved result is re-checked against the resolved parent. The
    second check is what protects against symlink/junction tricks, which no
    amount of string validation can see.
    """
    validate_pid(pid)
    root = Path(projects_dir).resolve()
    candidate = (root / pid).resolve()
    if candidate != root and root not in candidate.parents:
        raise InvalidPid(f'project path for {pid!r} escapes the projects directory')
    return candidate


def safe_child(base: Path, name: str) -> Path:
    """`<base>/<name>` for a single, non-traversing filename component.

    Used for source_docs/<filename> and cache/<file>. Rejects anything that
    is not a plain filename, then containment-checks the resolved result.
    """
    if not isinstance(name, str) or not name or '\x00' in name:
        raise InvalidPid('invalid filename')
    if name in ('.', '..') or '/' in name or '\\' in name:
        raise InvalidPid(f'invalid filename {name[:64]!r}')
    if Path(name).name != name or Path(name).is_absolute():
        raise InvalidPid(f'invalid filename {name[:64]!r}')
    root = Path(base).resolve()
    candidate = (root / name).resolve()
    if root not in candidate.parents:
        raise InvalidPid(f'{name[:64]!r} escapes {base}')
    return candidate


# ── API authentication guard ────────────────────────────────────────────────

# Endpoints reachable without a token. Everything else under /api/ is denied.
#   - the auth blueprint issues tokens, so it cannot require one
#   - the HTML shells are just markup; every datum they show comes from an
#     /api/ call that IS guarded
_PUBLIC_PATH_PREFIXES = ('/api/auth/', '/static/')
_PUBLIC_PATHS = frozenset({'/', '/ympl.js', '/editor', '/api/health', '/api/hub', '/docs', '/redoc', '/openapi.json'})


def _anonymous_allowed() -> bool:
    """Escape hatch for local development of the legacy Flask HTML UI.

    That UI has no login screen and sends no Authorization header, so it
    cannot work against a guarded API. Off by default — set
    STUDIO_ALLOW_ANONYMOUS=1 explicitly and accept that the API is then
    fully open to anything that can reach the port.
    """
    return os.getenv('STUDIO_ALLOW_ANONYMOUS', '').strip() in ('1', 'true', 'yes')


def install_pid_validator(app):
    """Reject a malformed `pid`/`project_id` URL parameter on ANY route.
    Supports both Flask and FastAPI.
    """
    if hasattr(app, 'before_request'):
        from flask import request

        @app.before_request
        def _validate_pid_param():
            args = request.view_args or {}
            for key in ('pid', 'project_id'):
                if key in args:
                    validate_pid(args[key])   # raises InvalidPid -> 400 errorhandler
            return None

        return app

    # FastAPI / Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from urllib.parse import unquote

    if hasattr(app, 'exception_handler'):
        @app.exception_handler(InvalidPid)
        async def _invalid_pid_handler(request: Request, exc: InvalidPid):
            return JSONResponse({'error': str(exc)}, status_code=400)

    @app.middleware("http")
    async def _validate_pid_middleware(request: Request, call_next):
        path = unquote(request.url.path)
        parts = [p for p in path.strip('/').split('/') if p]
        for idx, part in enumerate(parts):
            if part in ('projects', 'editor', 'canvas', 'agent') and idx + 1 < len(parts):
                candidate = parts[idx + 1]
                if part == 'agent' and candidate in ('health',):
                    continue
                if part == 'projects' and candidate in ('upload', 'detect-all', 'detection-files'):
                    continue
                try:
                    validate_pid(candidate)
                except InvalidPid as err:
                    return JSONResponse({'error': str(err)}, status_code=400)
        return await call_next(request)

    return app


def install_api_auth_guard(app, decode_token, get_db):
    """Register a default-deny hook for /api/* on `app`.
    Supports both Flask and FastAPI.
    """
    allow_anonymous = _anonymous_allowed()
    if allow_anonymous:
        print('[security] WARNING: STUDIO_ALLOW_ANONYMOUS is set — the /api '
              'surface is UNAUTHENTICATED. Never use this outside local dev.')

    if hasattr(app, 'before_request'):
        from flask import request, jsonify, g

        @app.before_request
        def _require_api_auth():
            path = request.path

            if request.method == 'OPTIONS':
                return None
            if path in _PUBLIC_PATHS or path.startswith('/canvas/'):
                return None
            if any(path.startswith(p) for p in _PUBLIC_PATH_PREFIXES):
                return None
            if not path.startswith('/api/'):
                return None
            if allow_anonymous:
                return None

            header = request.headers.get('Authorization', '')
            if not header.startswith('Bearer '):
                return jsonify({'success': False,
                                'error': 'Missing or malformed Authorization header.'}), 401
            payload = decode_token(header[7:].strip())
            if not payload:
                return jsonify({'success': False, 'error': 'Invalid or expired token.'}), 401

            row = get_db().execute(
                'SELECT * FROM users WHERE id = ?', (payload['userId'],)
            ).fetchone()
            if row is None or row['status'] != 'active':
                return jsonify({'success': False, 'error': 'User no longer active.'}), 401

            g.user = row
            return None

        return app

    # FastAPI / Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @app.middleware("http")
    async def _require_api_auth_fastapi(request: Request, call_next):
        path = request.url.path

        if request.method == 'OPTIONS':
            return await call_next(request)
        if path in _PUBLIC_PATHS or path.startswith('/canvas/'):
            return await call_next(request)
        if any(path.startswith(p) for p in _PUBLIC_PATH_PREFIXES):
            return await call_next(request)
        if not path.startswith('/api/'):
            return await call_next(request)
        if allow_anonymous:
            return await call_next(request)

        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return JSONResponse({'success': False,
                                 'error': 'Missing or malformed Authorization header.'}, status_code=401)
        payload = decode_token(header[7:].strip())
        if not payload:
            return JSONResponse({'success': False, 'error': 'Invalid or expired token.'}, status_code=401)

        row = get_db().execute(
            'SELECT * FROM users WHERE id = ?', (payload['userId'],)
        ).fetchone()
        if row is None or row['status'] != 'active':
            return JSONResponse({'success': False, 'error': 'User no longer active.'}, status_code=401)

        request.state.user = row
        return await call_next(request)

    return app


# ── Self-check ──────────────────────────────────────────────────────────────

def _demo():
    """Runnable check: every escape shape this module exists to stop."""
    import tempfile

    ok = ['daman', 'p-id-5', 'Project_1', 'a', 'x.y', 'a' * 64]
    for pid in ok:
        assert validate_pid(pid) == pid, pid

    bad = [
        '', '.', '..', '../x', 'a/b', 'a\\b', 'C:', 'C:/Windows', r'\\srv\share',
        '.hidden', '-leading', 'a' * 65, 'CON', 'nul.txt', 'x\x00y', 'a b',
    ]
    for pid in bad:
        try:
            validate_pid(pid)
        except InvalidPid:
            continue
        raise AssertionError(f'validate_pid accepted {pid!r}')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'projects'
        (root / 'good').mkdir(parents=True)
        assert safe_project_dir(root, 'good') == (root / 'good').resolve()
        for pid in ('..', 'C:/Windows', 'a/b'):
            try:
                safe_project_dir(root, pid)
            except InvalidPid:
                continue
            raise AssertionError(f'safe_project_dir accepted {pid!r}')

        assert safe_child(root, 'a.pdf') == (root / 'a.pdf').resolve()
        for name in ('..', '../x', 'a/b', 'C:/x', ''):
            try:
                safe_child(root, name)
            except InvalidPid:
                continue
            raise AssertionError(f'safe_child accepted {name!r}')

    print('security.py self-check passed')


if __name__ == '__main__':
    _demo()
