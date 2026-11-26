"""Session-wide test isolation: point adapters.db at a private, temp
SQLite file instead of the real ENGINEERING_HUB/studio.db.
Also sets up sys.path for backend and sdk packages.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# The flow-annotation pass adds vision calls to every extracted page. Tests
# that script an LLM count on the calls they scripted, so it is off unless a
# test turns it on (tests/test_flow_annotations.py does).
os.environ.setdefault("STUDIO_FLOW_ANNOTATIONS", "off")

# Ensure backend and sdk are importable during test runs
TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
REPO_ROOT = BACKEND_DIR.parent

for p in [BACKEND_DIR, REPO_ROOT / 'sdk', REPO_ROOT / 'sdk' / 'ympl-parser']:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "own_db: test module manages its own studio.db; skip the autouse "
        "per-test isolation fixture.")


@pytest.fixture(autouse=True, scope="function")
def _isolated_studio_db(request):
    """Point adapters.db at a private temp SQLite file for each test.

    Modules marked `own_db` opt out. They set up a module-scoped hub and seed
    the settings table once; because module-scoped fixtures are created BEFORE
    function-scoped autouse ones, this fixture used to re-point adapters.db
    immediately afterwards and silently discard that seeded state -- which is
    why the end-to-end extraction tests died on "Anthropic API key not set"
    despite seeding a dummy key.
    """
    import adapters.db as db
    if request.node.get_closest_marker("own_db"):
        yield
        return
    tmp_dir = tempfile.mkdtemp(prefix="studio_test_db_")
    db.reset_for_path(Path(tmp_dir) / "studio.db")
    db.init_db()
    yield
    db.close_db()


@pytest.fixture(autouse=True)
def _emit_through_sys_stdout(monkeypatch):
    """extraction_cli.output caches sys.stdout.buffer at import time, so under
    pytest's capture that handle is already closed. Point emit() at the
    text-mode sys.stdout instead — the real emit() code path still runs, we
    just take the branch capsys can see."""
    try:
        import extraction_cli.output as out
        monkeypatch.setattr(out, '_stdout_buf', None)
    except Exception:
        pass
