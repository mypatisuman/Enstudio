"""Phase 0 regression tests for studio/security.py.

Two things must hold and keep holding:
  1. No project id that escapes the projects directory is ever accepted.
  2. The /api surface is default-deny — a route added later without a
     decorator is still guarded.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from security import (  # noqa: E402
    InvalidPid, validate_pid, safe_project_dir, safe_child,
    install_api_auth_guard, install_pid_validator,
)


# ── pid validation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('pid', [
    'daman', 'p-id-5', 'Project_1', 'a', 'x.y', '9lives', 'a' * 64,
])
def test_accepts_ordinary_project_ids(pid):
    assert validate_pid(pid) == pid


@pytest.mark.parametrize('pid', [
    '',            # empty
    '.', '..',     # the classic traversal pair
    '../x', 'a/b', 'a\\b',
    'C:', 'C:/Windows',            # Windows drive-qualified — Path.join drops the left side
    r'\\server\share',             # UNC
    '.hidden', '-flag',            # leading dot / dash
    'a' * 65,                      # over the length cap
    'CON', 'nul.txt', 'LPT1',      # Windows device names
    'a b', 'a;b', 'a|b', 'a\x00b',
])
def test_rejects_every_escape_shape(pid):
    with pytest.raises(InvalidPid):
        validate_pid(pid)


def test_safe_project_dir_contains_result(tmp_path):
    root = tmp_path / 'projects'
    (root / 'good').mkdir(parents=True)
    assert safe_project_dir(root, 'good') == (root / 'good').resolve()


@pytest.mark.parametrize('pid', ['..', 'C:/Windows', 'a/b', '.'])
def test_safe_project_dir_refuses_escape(tmp_path, pid):
    root = tmp_path / 'projects'
    root.mkdir(parents=True)
    with pytest.raises(InvalidPid):
        safe_project_dir(root, pid)


@pytest.mark.parametrize('name', ['..', '../x', 'a/b', 'a\\b', '', '.'])
def test_safe_child_refuses_traversal(tmp_path, name):
    with pytest.raises(InvalidPid):
        safe_child(tmp_path, name)


def test_safe_child_allows_plain_filename(tmp_path):
    assert safe_child(tmp_path, 'sheet.pdf') == (tmp_path / 'sheet.pdf').resolve()


# ── API auth guard ──────────────────────────────────────────────────────────

def _app(monkeypatch, *, token_valid: bool):
    """Minimal Flask app wired to the same guard main.py installs."""
    from flask import Flask, jsonify

    monkeypatch.delenv('STUDIO_ALLOW_ANONYMOUS', raising=False)

    app = Flask(__name__)

    @app.errorhandler(InvalidPid)
    def _bad_pid(err):
        return jsonify({'error': str(err)}), 400

    @app.get('/')
    def index():
        return 'ok'

    @app.post('/api/auth/login')
    def login():
        return jsonify({'token': 'x'})

    @app.get('/api/projects')
    def projects():
        return jsonify([])

    @app.delete('/api/projects/<pid>')
    def delete(pid):
        return jsonify({'deleted': pid})

    class _Row(dict):
        def __getitem__(self, k):
            return dict.__getitem__(self, k)

    class _Cur:
        def fetchone(self):
            return _Row(id=1, status='active')

    class _Conn:
        def execute(self, *_a, **_k):
            return _Cur()

    install_pid_validator(app)
    install_api_auth_guard(
        app,
        decode_token=lambda t: {'userId': 1} if token_valid else None,
        get_db=lambda: _Conn(),
    )
    return app


def test_api_requires_a_token(monkeypatch):
    c = _app(monkeypatch, token_valid=True).test_client()
    assert c.get('/api/projects').status_code == 401
    assert c.delete('/api/projects/demo').status_code == 401


def test_valid_token_passes(monkeypatch):
    c = _app(monkeypatch, token_valid=True).test_client()
    h = {'Authorization': 'Bearer good'}
    assert c.get('/api/projects', headers=h).status_code == 200
    assert c.delete('/api/projects/demo', headers=h).status_code == 200


def test_bad_token_rejected(monkeypatch):
    c = _app(monkeypatch, token_valid=False).test_client()
    assert c.get('/api/projects', headers={'Authorization': 'Bearer nope'}).status_code == 401


def test_auth_blueprint_and_pages_stay_open(monkeypatch):
    c = _app(monkeypatch, token_valid=True).test_client()
    assert c.post('/api/auth/login').status_code == 200
    assert c.get('/').status_code == 200


def test_traversal_pid_is_400_not_a_filesystem_op(monkeypatch):
    """A bad pid must fail validation BEFORE any handler runs, even with a
    valid token — this is the check standing in front of shutil.rmtree."""
    c = _app(monkeypatch, token_valid=True).test_client()
    h = {'Authorization': 'Bearer good'}
    for pid in ('..', 'C:', 'CON', '.hidden', 'a b'):
        r = c.delete(f'/api/projects/{pid}', headers=h)
        assert r.status_code == 400, f'{pid!r} returned {r.status_code}'


def test_anonymous_escape_hatch_is_opt_in(monkeypatch):
    monkeypatch.setenv('STUDIO_ALLOW_ANONYMOUS', '1')
    from flask import Flask, jsonify
    app = Flask(__name__)

    @app.get('/api/projects')
    def projects():
        return jsonify([])

    install_api_auth_guard(app, decode_token=lambda t: None, get_db=lambda: None)
    assert app.test_client().get('/api/projects').status_code == 200


def test_fastapi_security_guard(monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    class _Row(dict):
        def __getitem__(self, k):
            return dict.__getitem__(self, k)

    class _Cur:
        def fetchone(self):
            return _Row(id=1, status='active')

    class _Conn:
        def execute(self, *_a, **_k):
            return _Cur()

    app = FastAPI()
    install_pid_validator(app)
    install_api_auth_guard(
        app,
        decode_token=lambda t: {'userId': 1} if t == 'good' else None,
        get_db=lambda: _Conn(),
    )

    @app.get('/api/projects/{pid}')
    def get_proj(pid: str):
        return {'pid': pid}

    c = TestClient(app)
    assert c.get('/api/projects/proj1').status_code == 401
    assert c.get('/api/projects/proj1', headers={'Authorization': 'Bearer bad'}).status_code == 401
    assert c.get('/api/projects/proj1', headers={'Authorization': 'Bearer good'}).status_code == 200
    # Invalid pid rejected with 400
    assert c.get('/api/projects/CON', headers={'Authorization': 'Bearer good'}).status_code == 400
    assert c.get('/api/projects/.hidden', headers={'Authorization': 'Bearer good'}).status_code == 400
