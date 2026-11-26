"""
db.py — SQLite-backed persistence layer for EngineeringStudio.

Single file at <ENGINEERING_HUB>/studio.db (default
C:\\standard\\EngineeringHub\\studio.db). Module-level helpers:

    get_db()  -> sqlite3.Connection (row_factory = sqlite3.Row)
    init_db() -> create tables if missing

The connection is opened once and shared across threads
(`check_same_thread=False`) which is appropriate for the existing
Flask threaded-server setup. Pass ENGINEERING_HUB or STUDIO_DB env
vars to override the location (mostly useful for tests).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from utils.paths import resolve_hub


# ── Database location ────────────────────────────────────────────────────────

def _resolve_db_path() -> Path:
    explicit = os.environ.get('STUDIO_DB')
    if explicit:
        return Path(explicit)
    default_hub = Path(__file__).resolve().parent.parent.parent / 'EngineeringHub' / 'EngineeringHub'
    hub = resolve_hub(default=default_hub, treat_empty_as_unset=True)
    return hub / 'studio.db'


DB_PATH: Path = _resolve_db_path()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name     TEXT NOT NULL,
  username      TEXT UNIQUE,            -- login accepts username OR email
  email         TEXT NOT NULL UNIQUE,   -- UNIQUE already indexes email
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',
  status        TEXT NOT NULL DEFAULT 'active',
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  last_login    TEXT
  -- ponytail: dropped avatar/emailVerified/verificationToken/reset*/loginProvider.
  -- Add columns via ALTER TABLE when the feature that needs them (email verify,
  -- OAuth, password reset via email) actually ships. YAGNI until then.
);

CREATE TABLE IF NOT EXISTS projects (
  id           TEXT PRIMARY KEY,
  title        TEXT,
  company      TEXT,
  process_type TEXT,
  created      TEXT,
  plant_name   TEXT,
  revision     INTEGER,
  extraction_locked INTEGER DEFAULT 0,
  last_extraction  TEXT,
  status       TEXT,
  stats_json   TEXT,
  user_id      INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sources (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pid       TEXT REFERENCES projects(id),
  filename  TEXT,
  file_hash TEXT,
  uploaded  TEXT,
  cached    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS exports (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  pid       TEXT REFERENCES projects(id),
  type      TEXT,
  filename  TEXT,
  exported  TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
  id          TEXT,
  pid         TEXT REFERENCES projects(id),
  kind        TEXT,
  kind_detail TEXT,
  label       TEXT,
  area        TEXT,
  x           REAL,
  y           REAL,
  extra_json  TEXT,
  -- Phase 5: which uploaded document produced this node. NULL on rows written
  -- before the migration ("legacy / unattributed"), which is why it is
  -- nullable and NOT part of the primary key. Cross-document uniqueness comes
  -- from the id prefix (see extraction_cli._id_prefix), so the (id, pid) key
  -- is unchanged and no table rebuild is needed.
  source_id   INTEGER REFERENCES sources(id),
  -- 'authored' (engineer or Describe agent) or 'extracted'. Filled by the
  -- ORIGIN_SQL triggers, so no writer has to remember it.
  origin      TEXT,
  PRIMARY KEY (id, pid)
);

CREATE TABLE IF NOT EXISTS edges (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pid        TEXT REFERENCES projects(id),
  from_id    TEXT,
  to_id      TEXT,
  kind       TEXT,
  label      TEXT,
  extra_json TEXT,
  source_id  INTEGER REFERENCES sources(id),
  origin     TEXT
);

CREATE TABLE IF NOT EXISTS instruments (
  tag           TEXT,
  pid           TEXT REFERENCES projects(id),
  area          TEXT,
  kind_detail   TEXT,
  type          TEXT,
  equipment_ref TEXT,
  extra_json    TEXT,
  PRIMARY KEY (tag, pid)
);

CREATE TABLE IF NOT EXISTS equipment (
  tag         TEXT,
  pid         TEXT REFERENCES projects(id),
  area        TEXT,
  kind_detail TEXT,
  type        TEXT,
  extra_json  TEXT,
  PRIMARY KEY (tag, pid)
);

CREATE TABLE IF NOT EXISTS connections (
  id         TEXT,
  pid        TEXT REFERENCES projects(id),
  from_tag   TEXT,
  to_tag     TEXT,
  type       TEXT,
  extra_json TEXT,
  PRIMARY KEY (id, pid)
);

CREATE TABLE IF NOT EXISTS loops (
  loop_id   TEXT,
  pid       TEXT REFERENCES projects(id),
  loop_json TEXT,
  PRIMARY KEY (loop_id, pid)
);

CREATE TABLE IF NOT EXISTS review (
  pid    TEXT REFERENCES projects(id),
  key    TEXT,
  state  TEXT,
  PRIMARY KEY (pid, key)
);

CREATE TABLE IF NOT EXISTS canvas_positions (
  pid     TEXT REFERENCES projects(id),
  node_id TEXT,
  x       REAL,
  y       REAL,
  PRIMARY KEY (pid, node_id)
);

CREATE TABLE IF NOT EXISTS cache_entries (
  pid       TEXT REFERENCES projects(id),
  cache_key TEXT,
  data_json TEXT,
  PRIMARY KEY (pid, cache_key)
);

CREATE TABLE IF NOT EXISTS cache_manifest (
  pid          TEXT REFERENCES projects(id),
  scan_json    TEXT,
  total_tokens INTEGER DEFAULT 0,
  total_cost   REAL    DEFAULT 0.0,
  last_scan    TEXT,
  PRIMARY KEY (pid)
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
  pid          TEXT REFERENCES projects(id),
  node_id      TEXT,
  type         TEXT,
  original     TEXT,
  proposed     TEXT,
  confidence   REAL,
  method       TEXT,
  review_state TEXT,
  extra_json   TEXT,
  PRIMARY KEY (pid, node_id, type)
);

CREATE TABLE IF NOT EXISTS grid_positions (
  pid      TEXT REFERENCES projects(id),
  node_id  TEXT,
  row_idx  INTEGER,
  col_idx  INTEGER,
  PRIMARY KEY (pid, node_id)
);

CREATE TABLE IF NOT EXISTS describe_session_states (
  pid                  TEXT REFERENCES projects(id),
  session_id           TEXT,
  history_json         TEXT,
  active_solution_json TEXT,
  updated_at           TEXT,
  PRIMARY KEY (pid, session_id)
);

CREATE TABLE IF NOT EXISTS describe_pending (
  pid        TEXT REFERENCES projects(id),
  session_id TEXT,
  data_json  TEXT,
  PRIMARY KEY (pid, session_id)
);

-- Desktop-app tables, previously defined only in src-tauri schema.rs.
CREATE TABLE IF NOT EXISTS describe_sessions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pid        TEXT REFERENCES projects(id),
  title      TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS activity_log (
  pid         TEXT REFERENCES projects(id),
  stage       TEXT,
  label       TEXT,
  detail      TEXT,
  status      TEXT,
  started_at  INTEGER,
  duration_ms INTEGER,
  indent      INTEGER DEFAULT 0,
  updated_at  TEXT DEFAULT (datetime('now')),
  PRIMARY KEY (pid, stage)
);
CREATE TABLE IF NOT EXISTS describe_messages (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id        INTEGER REFERENCES describe_sessions(id),
  pid               TEXT REFERENCES projects(id),
  role              TEXT,
  display           TEXT,
  api_content       TEXT,
  nodes_added       INTEGER DEFAULT 0,
  edges_added       INTEGER DEFAULT 0,
  nodes_updated     INTEGER DEFAULT 0,
  pending_deletes   TEXT,
  delete_resolution TEXT,
  nodes_deleted     INTEGER DEFAULT 0,
  is_error          INTEGER DEFAULT 0,
  created_at        TEXT DEFAULT (datetime('now'))
);

-- Plant hierarchy (site > plant > unit > area > system > subsystem)
-- and persisted extraction geometry for the connectivity export.
-- Identical DDL lives in schema.rs; tests/test_schema_parity.py enforces it.
CREATE TABLE IF NOT EXISTS hierarchy (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pid        TEXT REFERENCES projects(id),
  parent_id  INTEGER NOT NULL DEFAULT 0,
  level      TEXT NOT NULL,
  name       TEXT NOT NULL,
  code       TEXT,
  extra_json TEXT,
  UNIQUE (pid, parent_id, level, name)
);
CREATE TABLE IF NOT EXISTS node_hierarchy (
  pid          TEXT REFERENCES projects(id),
  node_id      TEXT,
  hierarchy_id INTEGER REFERENCES hierarchy(id),
  PRIMARY KEY (pid, node_id)
);
CREATE TABLE IF NOT EXISTS geometry_pages (
  pid       TEXT REFERENCES projects(id),
  source_id INTEGER NOT NULL DEFAULT 0,
  page      INTEGER NOT NULL,
  width     INTEGER,
  height    INTEGER,
  PRIMARY KEY (pid, source_id, page)
);
CREATE TABLE IF NOT EXISTS geometry_lines (
  pid         TEXT REFERENCES projects(id),
  line_id     TEXT NOT NULL,
  source_id   INTEGER NOT NULL DEFAULT 0,
  page        INTEGER NOT NULL DEFAULT 1,
  type        TEXT,
  style       TEXT,
  direction   TEXT,
  points_json TEXT,
  PRIMARY KEY (pid, line_id)
);
CREATE TABLE IF NOT EXISTS geometry_junctions (
  pid         TEXT REFERENCES projects(id),
  junction_id TEXT NOT NULL,
  source_id   INTEGER NOT NULL DEFAULT 0,
  page        INTEGER NOT NULL DEFAULT 1,
  kind        TEXT,
  x           REAL,
  y           REAL,
  extra_json  TEXT,
  PRIMARY KEY (pid, junction_id)
);
"""


# ── Connection management ────────────────────────────────────────────────────
#
# A single shared connection is sufficient for the existing studio Flask
# server (threaded but not heavily concurrent). `check_same_thread=False`
# allows worker threads to use it; a single transaction lock serialises
# writes.

_conn: Optional[sqlite3.Connection] = None
_conn_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Return the process-wide SQLite connection. Opens it on first call
    and creates the parent directory if needed."""
    global _conn
    with _conn_lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(
                str(DB_PATH),
                check_same_thread=False,
                isolation_level=None,  # autocommit; explicit BEGIN/COMMIT in callers
            )
            _conn.row_factory = sqlite3.Row
            _conn.execute('PRAGMA journal_mode = WAL')
            _conn.execute('PRAGMA synchronous = NORMAL')
            _conn.execute('PRAGMA foreign_keys = OFF')
    return _conn


# Phase 5 additive migrations. Same convention the Rust side already uses for
# users.username / projects.user_id: try the ALTER, ignore "duplicate column".
# Additive only — no table is rebuilt, no row is rewritten, no primary key
# changes, so an interrupted run leaves the database usable and re-running is a
# no-op. Existing rows keep source_id NULL and stay exactly as they were.
_MIGRATIONS = (
    'ALTER TABLE nodes ADD COLUMN source_id INTEGER REFERENCES sources(id)',
    'ALTER TABLE edges ADD COLUMN source_id INTEGER REFERENCES sources(id)',
    'ALTER TABLE nodes ADD COLUMN origin TEXT',
    'ALTER TABLE edges ADD COLUMN origin TEXT',
)

# Row origin, kept by the database itself. Writers mark authored rows in
# extra_json (Python json.dumps writes `"origin": "authored"`, serde_json writes
# `"origin":"authored"`, older desktop edges carry `"drawing":"DESCRIBE"`). These
# triggers copy that marker into the `origin` column on every insert, from any
# writer, and the UPDATEs backfill rows written before the column existed.
# Identical text lives in frontend/src-tauri/src/database/schema.rs ORIGIN_SQL;
# tests/test_schema_parity.py fails if they differ.
ORIGIN_SQL = r"""
CREATE INDEX IF NOT EXISTS idx_nodes_pid_origin ON nodes(pid, origin);
CREATE INDEX IF NOT EXISTS idx_edges_pid_origin ON edges(pid, origin);
CREATE TRIGGER IF NOT EXISTS trg_nodes_origin AFTER INSERT ON nodes
WHEN NEW.origin IS NULL
BEGIN
  UPDATE nodes SET origin = CASE WHEN
      NEW.extra_json LIKE '%"origin": "authored"%' OR NEW.extra_json LIKE '%"origin":"authored"%'
      OR NEW.extra_json LIKE '%"source": "describe_agent"%' OR NEW.extra_json LIKE '%"source":"describe_agent"%'
    THEN 'authored' ELSE 'extracted' END
  WHERE rowid = NEW.rowid;
END;
CREATE TRIGGER IF NOT EXISTS trg_edges_origin AFTER INSERT ON edges
WHEN NEW.origin IS NULL
BEGIN
  UPDATE edges SET origin = CASE WHEN
      NEW.extra_json LIKE '%"origin": "authored"%' OR NEW.extra_json LIKE '%"origin":"authored"%'
      OR NEW.extra_json LIKE '%"drawing": "DESCRIBE"%' OR NEW.extra_json LIKE '%"drawing":"DESCRIBE"%'
    THEN 'authored' ELSE 'extracted' END
  WHERE rowid = NEW.rowid;
END;
UPDATE nodes SET origin = CASE WHEN
    extra_json LIKE '%"origin": "authored"%' OR extra_json LIKE '%"origin":"authored"%'
    OR extra_json LIKE '%"source": "describe_agent"%' OR extra_json LIKE '%"source":"describe_agent"%'
  THEN 'authored' ELSE 'extracted' END
WHERE origin IS NULL;
UPDATE edges SET origin = CASE WHEN
    extra_json LIKE '%"origin": "authored"%' OR extra_json LIKE '%"origin":"authored"%'
    OR extra_json LIKE '%"drawing": "DESCRIBE"%' OR extra_json LIKE '%"drawing":"DESCRIBE"%'
  THEN 'authored' ELSE 'extracted' END
WHERE origin IS NULL;
"""

_INDEXES = (
    'CREATE INDEX IF NOT EXISTS idx_nodes_pid_source ON nodes(pid, source_id)',
    'CREATE INDEX IF NOT EXISTS idx_edges_pid_source ON edges(pid, source_id)',
    'CREATE INDEX IF NOT EXISTS idx_edges_pid ON edges(pid)',
    'CREATE INDEX IF NOT EXISTS idx_sources_pid ON sources(pid)',
)


def migrate_db() -> None:
    """Bring an existing database up to the current schema.

    Idempotent and non-destructive: a column that is already there raises
    "duplicate column name" and is skipped. Safe to call on an empty database,
    a legacy single-document database, or an already-migrated one.
    """
    conn = get_db()
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if 'duplicate column' not in str(e).lower():
                raise
    for stmt in _INDEXES:
        conn.execute(stmt)
    conn.commit()
    conn.executescript(ORIGIN_SQL)


def init_db() -> None:
    """Create every table from SCHEMA if it doesn't already exist."""
    conn = get_db()
    conn.executescript(SCHEMA)
    migrate_db()


def close_db() -> None:
    """Close the shared connection. Mostly useful for tests / migration."""
    global _conn
    with _conn_lock:
        if _conn is not None:
            try:
                _conn.close()
            finally:
                _conn = None


def reset_for_path(path: Path) -> None:
    """Force the module to use a different DB path (tests / migration).
    Safe to call multiple times."""
    global DB_PATH
    close_db()
    DB_PATH = Path(path)
