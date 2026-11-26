"""The database schema is defined twice: `adapters/db.py` (Python backend) and
`frontend/src-tauri/src/database/schema.rs` (desktop app). Whichever process
first touches a hub creates its tables, so the two must agree.

They had already drifted. schema.rs lacked `grid_positions`, `describe_pending`
and `describe_session_states`, so on a hub the desktop app created, the Describe
agents failed with "no such table". db.py lacked the desktop's session, message
and activity tables. These tests make any future drift fail the suite.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

STUDIO = Path(__file__).resolve().parent.parent
RUST_SCHEMA = STUDIO.parent / "frontend" / "src-tauri" / "src" / "database" / "schema.rs"

_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+)\s*\(", re.I)

# Tables introduced for the brownfield work: their DDL must be column-identical.
_SHARED_NEW = ("hierarchy", "node_hierarchy", "geometry_pages",
               "geometry_lines", "geometry_junctions", "grid_positions",
               "describe_pending", "describe_session_states")


def _rust_sql() -> str:
    text = RUST_SCHEMA.read_text(encoding="utf-8")
    start = text.index('SCHEMA_SQL: &str = "') + len('SCHEMA_SQL: &str = "')
    return text[start:text.index('";', start)]


def _python_sql() -> str:
    from adapters import db
    return db.SCHEMA


def _tables(sql: str) -> set[str]:
    return {m.group(1).lower() for m in _TABLE_RE.finditer(sql)}


def _columns(sql: str, table: str) -> list[tuple]:
    conn = sqlite3.connect(":memory:")
    conn.executescript(sql)
    cols = [(r[1], r[2].upper(), r[3], r[5])            # name, type, notnull, pk
            for r in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


def test_both_schemas_define_the_same_tables():
    rust, python = _tables(_rust_sql()), _tables(_python_sql())
    # The desktop creates `settings` in config/mod.rs as well; it is also in
    # SCHEMA_SQL now, so no exceptions are needed.
    assert rust == python, (
        f"schema drift - only in schema.rs: {sorted(rust - python)}; "
        f"only in db.py: {sorted(python - rust)}")


def test_shared_tables_have_identical_columns():
    rust, python = _rust_sql(), _python_sql()
    for table in _SHARED_NEW:
        assert _columns(rust, table) == _columns(python, table), \
            f"{table} columns differ between schema.rs and db.py"


def test_both_schemas_execute_cleanly():
    for sql in (_rust_sql(), _python_sql()):
        conn = sqlite3.connect(":memory:")
        conn.executescript(sql)
        conn.close()


def test_agent_clis_initialise_the_database():
    for script in ("run_describe.py", "run_agentic.py"):
        src = (STUDIO / script).read_text(encoding="utf-8")
        assert "init_db()" in src, f"{script} must call init_db()"


def _rust_origin_sql() -> str:
    text = RUST_SCHEMA.read_text(encoding="utf-8")
    start = text.index('ORIGIN_SQL: &str = r#"') + len('ORIGIN_SQL: &str = r#"')
    return text[start:text.index('"#;', start)]


def test_origin_sql_is_identical_in_both_schemas():
    from adapters import db
    assert _rust_origin_sql() == db.ORIGIN_SQL


def _origin_db(schema: str, origin_sql: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema)
    conn.executescript(origin_sql)
    return conn


def test_origin_is_stamped_for_every_writer_style():
    from adapters import db
    for schema, origin_sql in ((_python_sql(), db.ORIGIN_SQL), (_rust_sql(), _rust_origin_sql())):
        conn = _origin_db(schema, origin_sql)
        rows = {
            "py_authored": '{"origin": "authored", "drawing": "PID-1"}',
            "rs_authored": '{"drawing":"DESCRIBE","origin":"authored"}',
            "legacy_agent": '{"source": "describe_agent"}',
            "extracted": '{"drawing": "PID-1", "page": 1}',
            "no_extra": None,
        }
        for nid, extra in rows.items():
            conn.execute("INSERT INTO nodes (id, pid, extra_json) VALUES (?, 'P', ?)", (nid, extra))
        conn.execute("INSERT OR REPLACE INTO nodes (id, pid, extra_json) VALUES "
                     "('extracted', 'P', '{\"origin\": \"authored\"}')")
        got = dict(conn.execute("SELECT id, origin FROM nodes").fetchall())
        assert got == {"py_authored": "authored", "rs_authored": "authored",
                       "legacy_agent": "authored", "extracted": "authored",
                       "no_extra": "extracted"}
        conn.execute("INSERT INTO edges (pid, from_id, to_id, extra_json) VALUES "
                     "('P', 'a', 'b', '{\"drawing\":\"DESCRIBE\"}'), ('P', 'b', 'c', '{}')")
        assert [r[0] for r in conn.execute("SELECT origin FROM edges ORDER BY id")] == \
            ["authored", "extracted"]
        conn.close()


def test_origin_migration_backfills_an_old_database(tmp_path):
    from adapters import db
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE nodes (id TEXT, pid TEXT, kind TEXT, kind_detail TEXT, label TEXT, "
        "area TEXT, x REAL, y REAL, extra_json TEXT, PRIMARY KEY (id, pid));"
        "CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, from_id TEXT, "
        "to_id TEXT, kind TEXT, label TEXT, extra_json TEXT);"
        "INSERT INTO nodes (id, pid, extra_json) VALUES ('a', 'P', '{\"origin\": \"authored\"}'),"
        " ('b', 'P', '{}');")
    old.commit()
    old.close()
    db.reset_for_path(path)
    try:
        db.init_db()
        db.init_db()                                    # idempotent
        got = dict(db.get_db().execute("SELECT id, origin FROM nodes").fetchall())
        assert got == {"a": "authored", "b": "extracted"}
    finally:
        db.close_db()
