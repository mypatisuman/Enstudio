"""Two fixes pinned here.

1. CREDENTIALS. adapters/mongodb.py and scripts/init_enstudio_db.py each
   carried a live MongoDB connection string -- username, password and cluster
   host -- as the default value for MONGODB_URI. The credential shipped inside
   the source tree, so any checkout could reach the production cluster without
   configuring anything. There is now no default: an unset URI raises at CALL
   time (never at import time, so tooling can still import the module).

2. RESOLVE WITH NOTHING PENDING. resolve_describe_turn() resumed a LangGraph
   thread unconditionally. With no checkpointed interrupt, LangGraph starts the
   graph from empty state, the first node raises KeyError('project_id'), and
   @retryable_node's on_exhausted handler reports "I could not reach the
   language model" -- blaming the provider for what is really "there is
   nothing to confirm". The UI hits this whenever confirm/cancel is sent twice.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
REPO = STUDIO.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))


# ── 1. No credential may live in the source tree ────────────────────────────

# Fragments of the credentials that were previously committed. Matching any of
# them means a real secret is back in a source file.
_LEAKED_FRAGMENTS = (
    "Nellore", "Ensar2026", "sk_test_", "pk_test_", "whsec_", "AccountKey=",
    "hf_oKm", "lsv2_pt", "sDxXvahu", "gKZWCbhC", "cNz8Q~",
)

_SCANNED_SUFFIXES = (".py", ".ts", ".tsx", ".rs", ".md", ".yml", ".yaml",
                     ".json", ".example")
_SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "target",
              ".venv", "venv", ".pytest_cache", "EngineeringHub"}


def _scanned_files():
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        # This test file necessarily contains the fragments it searches for.
        if path.name == Path(__file__).name:
            continue
        yield path


def test_no_committed_secret_in_any_source_file():
    offenders = []
    for path in _scanned_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for fragment in _LEAKED_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.relative_to(REPO)} contains {fragment!r}")
    assert not offenders, "credentials found in source:\n" + "\n".join(offenders)


def test_mongo_adapter_has_no_hardcoded_uri():
    src = (STUDIO / "adapters" / "mongodb.py").read_text(encoding="utf-8")
    assert "mongodb+srv://" not in src, \
        "adapters/mongodb.py must not embed a connection string"


def test_seeder_has_no_hardcoded_uri():
    src = (STUDIO / "scripts" / "init_enstudio_db.py").read_text(encoding="utf-8")
    assert "mongodb+srv://" not in src, \
        "the seeder WRITES to the database; it must never default to a cluster"


def test_mongo_calls_raise_a_clear_error_when_unconfigured(monkeypatch):
    from adapters import mongodb as M
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("RESTRUCTURED_DB_URI", raising=False)
    with pytest.raises(M.MissingMongoCredentials) as exc:
        M.get_mongo_client()
    message = str(exc.value)
    assert "MONGODB_URI" in message and "mongo.env.example" in message


def test_importing_the_mongo_adapter_never_raises():
    """Import-time failure would break unrelated tooling on a machine with no
    Mongo configured, so the check belongs at call time."""
    import importlib
    from adapters import mongodb as M
    importlib.reload(M)


def test_gitignore_covers_every_env_file():
    rules = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "*.env" in rules, (
        "mongo.env held ~30 live secrets and was not ignored: the '.env' and "
        "'**/.env' patterns only match a file named exactly '.env'"
    )
    assert "!*.env.example" in rules or "!**/*.env.example" in rules, \
        "templates must stay committable"


def test_mongo_env_template_exists_and_is_blank():
    template = REPO / "mongo.env.example"
    assert template.exists(), "mongo.env.example must document the keys"
    text = template.read_text(encoding="utf-8")
    for fragment in _LEAKED_FRAGMENTS:
        assert fragment not in text
    # Every non-comment assignment must have an empty value.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        _key, _, value = stripped.partition("=")
        assert value in ('""', "''", ""), f"template carries a value: {line}"


def test_template_comments_carry_no_values_either():
    """The first template draft left real credentials on commented-out lines."""
    text = (REPO / "mongo.env.example").read_text(encoding="utf-8")
    pattern = re.compile(r'^\s*#\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+)$')
    for line in text.splitlines():
        m = pattern.match(line)
        if m and m.group(2).strip() not in ('""', "''"):
            pytest.fail(f"commented key still carries a value: {line}")


# ── 2. Resolving with nothing pending ───────────────────────────────────────

class _FakeSnapshot:
    def __init__(self, next_=(), values=None):
        self.next = next_
        self.values = values or {}


class _FakeGraph:
    """Stands in for a compiled LangGraph."""

    def __init__(self, snapshot=None, raises=False):
        self._snapshot = snapshot
        self._raises = raises
        self.invoked = False

    def get_state(self, _config):
        if self._raises:
            raise RuntimeError("no checkpointer configured")
        return self._snapshot

    def invoke(self, *_a, **_k):
        self.invoked = True
        return {"reply": "deleted", "ops": [{"tool": "delete_nodes"}]}


def _workflow():
    from agents.describe.workflows import describe_workflow as W
    return W


def test_no_pending_interrupt_when_thread_never_ran():
    W = _workflow()
    assert W._has_pending_interrupt(_FakeGraph(_FakeSnapshot()), {}) is False


def test_no_pending_interrupt_when_get_state_raises():
    W = _workflow()
    assert W._has_pending_interrupt(_FakeGraph(raises=True), {}) is False


def test_pending_interrupt_detected():
    W = _workflow()
    snap = _FakeSnapshot(next_=("confirm",), values={"project_id": "p"})
    assert W._has_pending_interrupt(_FakeGraph(snap), {}) is True


def test_checkpoint_without_state_is_not_pending():
    W = _workflow()
    snap = _FakeSnapshot(next_=("confirm",), values={})
    assert W._has_pending_interrupt(_FakeGraph(snap), {}) is False


def test_resolve_without_pending_does_not_blame_the_provider():
    W = _workflow()
    graph = _FakeGraph(_FakeSnapshot())
    out = W.resolve_describe_turn("p", "s", True, graphs={"deletion": graph})
    assert graph.invoked is False, "must not resume a thread with no interrupt"
    assert out["status"] == "no_pending"
    assert "language model" not in out["reply"].lower()
    assert "no deletion awaiting confirmation" in out["reply"].lower()


def test_resolve_with_pending_still_resumes():
    W = _workflow()
    snap = _FakeSnapshot(next_=("confirm",), values={"project_id": "p"})
    graph = _FakeGraph(snap)
    out = W.resolve_describe_turn("p", "s", True, graphs={"deletion": graph})
    assert graph.invoked is True
    assert out["agent"] == "deletion"


# ── 3. The Describe CLI's machine-readable contract ─────────────────────────

def test_cli_exposes_json_mode_and_sentinel():
    src = (STUDIO / "run_describe.py").read_text(encoding="utf-8")
    assert "--json" in src
    assert "RESULT_SENTINEL" in src


def test_rust_parses_the_same_sentinel():
    """The Rust side scans stdout for this exact prefix; the agents stream
    NDJSON on the same stream, so the two must not drift."""
    import run_describe
    rust = (REPO / "frontend" / "src-tauri" / "src" / "commands"
            / "describe.rs").read_text(encoding="utf-8")
    assert run_describe.RESULT_SENTINEL.strip() in rust
