"""Phase 5 — document identity and data-integrity regression tests.

The assertion that matters most, stated once here so it is not lost among the
others: extracting PDF B into a project must not change a single row belonging
to PDF A.

Everything runs against a temporary SQLite file, no LLM and no GPU. The
extraction pipeline itself is not invoked — these tests drive the persistence
layer directly, which is where the identity bug lived.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters import db as _db                                    # noqa: E402
from extraction_cli.commands import (                             # noqa: E402
    _fallback_drawing, _id_prefix, _page_prefix, _rows_from_other_sources,
)
from repositories.integrity import check_integrity                # noqa: E402
from repositories.project_repository import _db_persist_espx      # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh, fully-migrated database."""
    path = tmp_path / 'studio.db'
    _db.reset_for_path(path)
    _db.init_db()
    conn = _db.get_db()
    conn.execute("INSERT INTO projects (id, title, status) VALUES ('P','P','pending')")
    conn.commit()
    yield conn
    _db.close_db()


def add_source(conn, pid: str, filename: str, file_hash: str) -> int:
    cur = conn.execute(
        "INSERT INTO sources (pid, filename, file_hash, uploaded, cached) "
        "VALUES (?, ?, ?, datetime('now'), 1)", (pid, filename, file_hash))
    conn.commit()
    return cur.lastrowid


def espx_for(nodes, edges, instruments=None):
    return {
        'nodes': nodes, 'edges': edges,
        'meta': {},
        'studio': {'instruments': instruments or {}, 'equipment': {},
                   'connections': [], 'loops': {}, 'review': {}, 'screens': []},
    }


def doc_nodes(source_id: int, page: int, total: int, local_ids, drawing=None):
    """Nodes exactly as run_extraction would stamp them for one page."""
    prefix = _id_prefix(source_id, page, total)
    draw = drawing or _fallback_drawing(source_id, page, total)
    return [{
        'id': f'{prefix}{lid}', 'label': lid.upper(), 'kind': 'vessel',
        'x': 0.5, 'y': 0.5, 'page': page, 'drawing': draw,
        'source_id': source_id,
    } for lid in local_ids]


def doc_edges(source_id: int, page: int, total: int, pairs):
    prefix = _id_prefix(source_id, page, total)
    return [{'from': f'{prefix}{a}', 'to': f'{prefix}{b}',
             'kind': 'process', 'source_id': source_id} for a, b in pairs]


def persist_document(conn, pid, source_id, nodes, edges):
    """What _merge now does: carry other documents through, then rewrite."""
    kept_n, kept_e = _rows_from_other_sources(pid, source_id)
    _db_persist_espx(pid, espx_for(kept_n + nodes, kept_e + edges))


def rows(conn, sql, params=()):
    return [tuple(r) for r in conn.execute(sql, params).fetchall()]


# ── 1. two PDFs with identical local node IDs ───────────────────────────────

def test_identical_local_ids_across_documents_do_not_collide(db):
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    b = add_source(db, 'P', 'b.pdf', 'hash-b')

    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2']),
                     doc_edges(a, 1, 1, [('n1', 'n2')]))
    a_rows = rows(db, "SELECT id,label,x,y,source_id FROM nodes WHERE pid='P' ORDER BY id")
    assert len(a_rows) == 2

    persist_document(db, 'P', b, doc_nodes(b, 1, 1, ['n1', 'n2']),
                     doc_edges(b, 1, 1, [('n1', 'n2')]))

    # THE assertion: document A's rows are byte-identical afterwards.
    assert rows(db, "SELECT id,label,x,y,source_id FROM nodes "
                    "WHERE pid='P' AND source_id=? ORDER BY id", (a,)) == a_rows
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 4
    assert len(rows(db, "SELECT id FROM edges WHERE pid='P'")) == 2
    assert check_integrity('P')['cross_document_edges'] == []


def test_id_prefix_is_document_scoped_and_deterministic():
    assert _id_prefix(3, 1, 1) == 's3_'
    assert _id_prefix(3, 2, 5) == 's3_p2_'
    assert _id_prefix(3, 1, 1) == _id_prefix(3, 1, 1)        # stable
    assert _id_prefix(4, 1, 1) != _id_prefix(3, 1, 1)        # separates documents
    # No source identity -> exactly the Phase 1 behaviour, unchanged.
    assert _id_prefix(None, 1, 1) == _page_prefix(1, 1) == ''
    assert _id_prefix(None, 2, 5) == _page_prefix(2, 5) == 'p2_'


# ── 2. two PDFs with identical page numbers ─────────────────────────────────

def test_same_page_number_in_two_documents_stays_separate(db):
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    b = add_source(db, 'P', 'b.pdf', 'hash-b')
    persist_document(db, 'P', a, doc_nodes(a, 1, 2, ['n1']) + doc_nodes(a, 2, 2, ['n1']), [])
    persist_document(db, 'P', b, doc_nodes(b, 1, 2, ['n1']) + doc_nodes(b, 2, 2, ['n1']), [])

    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 4
    # page 1 exists in both documents and is a distinct row in each
    page1 = rows(db, "SELECT source_id FROM nodes WHERE pid='P' "
                     "AND json_extract(extra_json,'$.page')=1 ORDER BY source_id")
    assert page1 == [(a,), (b,)]
    # ...and the two documents' page 1s are not merged into one drawing cell
    draws = {r[0] for r in rows(db, "SELECT json_extract(extra_json,'$.drawing') "
                                    "FROM nodes WHERE pid='P'")}
    assert len(draws) == 4


def test_fallback_drawing_is_unique_per_document_and_page():
    assert _fallback_drawing(1, 1, 1) != _fallback_drawing(2, 1, 1)
    assert _fallback_drawing(1, 1, 3) != _fallback_drawing(1, 2, 3)
    # Unchanged where there is no document identity.
    assert _fallback_drawing(None, 1, 1) == ''
    assert _fallback_drawing(None, 2, 3) == 'page_2'


def test_real_drawing_number_is_not_rewritten(db):
    """A title-block drawing number is engineering identity — leave it alone."""
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1'], drawing='PID-101'), [])
    assert rows(db, "SELECT json_extract(extra_json,'$.drawing') FROM nodes "
                    "WHERE pid='P'") == [('PID-101',)]


# ── 3. identical filenames ──────────────────────────────────────────────────

def test_identical_filenames_are_separate_documents(db):
    """Filename is not identity: two different drawings can share a name."""
    a = add_source(db, 'P', 'drawing.pdf', 'hash-a')
    b = add_source(db, 'P', 'drawing.pdf', 'hash-b')
    assert a != b
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    persist_document(db, 'P', b, doc_nodes(b, 1, 1, ['n1']), [])
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 2


# ── 4. identical node/edge structure ────────────────────────────────────────

def test_structurally_identical_documents_both_survive(db):
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    b = add_source(db, 'P', 'b.pdf', 'hash-b')
    for sid in (a, b):
        persist_document(db, 'P', sid, doc_nodes(sid, 1, 1, ['n1', 'n2', 'n3']),
                         doc_edges(sid, 1, 1, [('n1', 'n2'), ('n2', 'n3')]))
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 6
    assert len(rows(db, "SELECT id FROM edges WHERE pid='P'")) == 4
    for sid in (a, b):
        assert len(rows(db, "SELECT id FROM nodes WHERE pid='P' AND source_id=?", (sid,))) == 3


# ── 5. re-import / re-extract the same document ─────────────────────────────

def test_reextract_replaces_only_its_own_document(db):
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    b = add_source(db, 'P', 'b.pdf', 'hash-b')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2']), [])
    persist_document(db, 'P', b, doc_nodes(b, 1, 1, ['n1', 'n2']), [])
    b_before = rows(db, "SELECT id,label,x,y FROM nodes WHERE pid='P' AND source_id=? ORDER BY id", (b,))

    # Re-extraction of A finds 3 symbols this time.
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2', 'n3']), [])

    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P' AND source_id=?", (a,))) == 3
    assert rows(db, "SELECT id,label,x,y FROM nodes WHERE pid='P' AND source_id=? ORDER BY id", (b,)) == b_before


def test_reextract_removes_symbols_that_are_gone(db):
    """Replacement, not accumulation — a symbol dropped by re-extraction must
    not linger from the previous run."""
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2', 'n3']), [])
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 1


# ── 6/7. delete a document / a page ─────────────────────────────────────────

def delete_source_rows(conn, pid, source_id):
    """Mirror of the Rust delete_source cascade, exercised here in Python."""
    conn.execute(
        "DELETE FROM edges WHERE pid=? AND (source_id=? "
        " OR from_id IN (SELECT id FROM nodes WHERE pid=? AND source_id=?)"
        " OR to_id   IN (SELECT id FROM nodes WHERE pid=? AND source_id=?))",
        (pid, source_id, pid, source_id, pid, source_id))
    conn.execute("DELETE FROM canvas_positions WHERE pid=? AND node_id IN "
                 "(SELECT id FROM nodes WHERE pid=? AND source_id=?)", (pid, pid, source_id))
    conn.execute("DELETE FROM nodes WHERE pid=? AND source_id=?", (pid, source_id))
    conn.execute("DELETE FROM sources WHERE pid=? AND id=?", (pid, source_id))
    conn.commit()


def test_deleting_a_document_leaves_the_other_intact_and_no_orphans(db):
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    b = add_source(db, 'P', 'b.pdf', 'hash-b')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2']), doc_edges(a, 1, 1, [('n1', 'n2')]))
    persist_document(db, 'P', b, doc_nodes(b, 1, 1, ['n1', 'n2']), doc_edges(b, 1, 1, [('n1', 'n2')]))
    db.execute("INSERT INTO canvas_positions (pid,node_id,x,y) VALUES ('P',?,1,1)",
               (f'{_id_prefix(a, 1, 1)}n1',))
    db.commit()

    b_before = rows(db, "SELECT id,label FROM nodes WHERE pid='P' AND source_id=? ORDER BY id", (b,))
    delete_source_rows(db, 'P', a)

    assert rows(db, "SELECT id FROM nodes WHERE pid='P' AND source_id=?", (a,)) == []
    assert rows(db, "SELECT id FROM edges WHERE pid='P' AND source_id=?", (a,)) == []
    assert rows(db, "SELECT id,label FROM nodes WHERE pid='P' AND source_id=? ORDER BY id", (b,)) == b_before
    report = check_integrity('P')
    assert report['orphan_edges'] == []
    assert report['stale_canvas_positions'] == []


def test_deleting_a_page_of_a_document_keeps_the_other_pages(db):
    a = add_source(db, 'P', 'a.pdf', 'hash-a')
    persist_document(db, 'P', a,
                     doc_nodes(a, 1, 2, ['n1']) + doc_nodes(a, 2, 2, ['n1']), [])
    db.execute("DELETE FROM nodes WHERE pid='P' AND json_extract(extra_json,'$.page')=1")
    db.commit()
    left = rows(db, "SELECT id FROM nodes WHERE pid='P'")
    assert left == [(f'{_id_prefix(a, 2, 2)}n1',)]
    assert check_integrity('P')['orphan_edges'] == []


# ── 8. two projects with the same PDF ───────────────────────────────────────

def test_two_projects_with_the_same_pdf_are_isolated(db):
    db.execute("INSERT INTO projects (id,title,status) VALUES ('Q','Q','pending')")
    db.commit()
    a = add_source(db, 'P', 'same.pdf', 'same-hash')
    b = add_source(db, 'Q', 'same.pdf', 'same-hash')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2']), doc_edges(a, 1, 1, [('n1', 'n2')]))
    p_before = rows(db, "SELECT id,label FROM nodes WHERE pid='P' ORDER BY id")

    persist_document(db, 'Q', b, doc_nodes(b, 1, 1, ['n1', 'n2']), doc_edges(b, 1, 1, [('n1', 'n2')]))

    assert rows(db, "SELECT id,label FROM nodes WHERE pid='P' ORDER BY id") == p_before
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='Q'")) == 2
    # Re-extracting Q must not reach into P either.
    persist_document(db, 'Q', b, doc_nodes(b, 1, 1, ['n1']), [])
    assert rows(db, "SELECT id,label FROM nodes WHERE pid='P' ORDER BY id") == p_before


def test_persist_never_touches_another_project(db):
    db.execute("INSERT INTO projects (id,title,status) VALUES ('Q','Q','pending')")
    db.commit()
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'Q', 'b.pdf', 'hb')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    persist_document(db, 'Q', b, doc_nodes(b, 1, 1, ['n1']), [])
    # _rows_from_other_sources must be project-scoped, or Q's write would drag
    # P's rows into Q.
    kept, _ = _rows_from_other_sources('Q', b)
    assert all(n['id'].startswith(_id_prefix(b, 1, 1)) or n.get('source_id') is None
               for n in kept)
    assert rows(db, "SELECT COUNT(*) FROM nodes WHERE pid='Q'") == [(1,)]
    assert rows(db, "SELECT COUNT(*) FROM nodes WHERE pid='P'") == [(1,)]


# ── 9. parallel edges ───────────────────────────────────────────────────────

def test_parallel_edges_are_preserved(db):
    """Two distinct pipe runs between the same pair of symbols are two rows."""
    a = add_source(db, 'P', 'a.pdf', 'ha')
    nodes = doc_nodes(a, 1, 1, ['n1', 'n2'])
    pfx = _id_prefix(a, 1, 1)
    edges = [
        {'from': f'{pfx}n1', 'to': f'{pfx}n2', 'kind': 'process', 'label': 'line-1', 'source_id': a},
        {'from': f'{pfx}n1', 'to': f'{pfx}n2', 'kind': 'process', 'label': 'line-2', 'source_id': a},
    ]
    persist_document(db, 'P', a, nodes, edges)
    got = rows(db, "SELECT from_id,to_id,label FROM edges WHERE pid='P' ORDER BY label")
    assert len(got) == 2
    assert {g[2] for g in got} == {'line-1', 'line-2'}
    # Distinct primary keys — the schema supports parallel edges natively.
    assert len({r[0] for r in rows(db, "SELECT id FROM edges WHERE pid='P'")}) == 2


# ── 10/11. cross-document and cross-project edges ───────────────────────────

def test_cross_document_edge_is_detected(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'P', 'b.pdf', 'hb')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    persist_document(db, 'P', b, doc_nodes(b, 1, 1, ['n1']), [])
    assert check_integrity('P')['cross_document_edges'] == []

    db.execute("INSERT INTO edges (pid,from_id,to_id,kind,source_id) VALUES ('P',?,?,'process',?)",
               (f'{_id_prefix(a, 1, 1)}n1', f'{_id_prefix(b, 1, 1)}n1', a))
    db.commit()
    assert len(check_integrity('P')['cross_document_edges']) == 1


def test_cross_project_edge_cannot_resolve(db):
    """An edge in P naming a node that only exists in Q is an orphan, not a
    silent link — the endpoint lookup is pid-scoped."""
    db.execute("INSERT INTO projects (id,title,status) VALUES ('Q','Q','pending')")
    db.commit()
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'Q', 'b.pdf', 'hb')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    persist_document(db, 'Q', b, doc_nodes(b, 1, 1, ['n1']), [])
    db.execute("INSERT INTO edges (pid,from_id,to_id,kind) VALUES ('P',?,?,'process')",
               (f'{_id_prefix(a, 1, 1)}n1', f'{_id_prefix(b, 1, 1)}n1'))
    db.commit()
    assert len(check_integrity('P')['orphan_edges']) == 1
    assert check_integrity('Q')['orphan_edges'] == []


def test_foreign_source_attribution_is_detected(db):
    db.execute("INSERT INTO projects (id,title,status) VALUES ('Q','Q','pending')")
    db.commit()
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'Q', 'b.pdf', 'hb')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    db.execute("UPDATE nodes SET source_id=? WHERE pid='P'", (b,))
    db.commit()
    assert len(check_integrity('P')['nodes_with_foreign_source']) == 1


# ── 12/13. migration: legacy database, new database ─────────────────────────

def test_migration_of_a_legacy_database_preserves_every_row(tmp_path):
    """Old schema -> migrate -> same rows, plus a NULL source_id column."""
    path = tmp_path / 'legacy.db'
    raw = sqlite3.connect(path)
    raw.executescript("""
        CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT, status TEXT);
        CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT,
                              filename TEXT, file_hash TEXT, uploaded TEXT, cached INTEGER);
        CREATE TABLE nodes (id TEXT, pid TEXT, kind TEXT, kind_detail TEXT, label TEXT,
                            area TEXT, x REAL, y REAL, extra_json TEXT, PRIMARY KEY (id,pid));
        CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, pid TEXT, from_id TEXT,
                            to_id TEXT, kind TEXT, label TEXT, extra_json TEXT);
        INSERT INTO projects VALUES ('old','old','done');
        INSERT INTO nodes (id,pid,label,x,y) VALUES ('n1','old','V-1',0.1,0.2),
                                                    ('n2','old','V-2',0.3,0.4);
        INSERT INTO edges (pid,from_id,to_id,kind) VALUES ('old','n1','n2','process');
    """)
    raw.commit()
    before_n = raw.execute("SELECT id,pid,label,x,y FROM nodes ORDER BY id").fetchall()
    before_e = raw.execute("SELECT from_id,to_id,kind FROM edges").fetchall()
    raw.close()

    _db.reset_for_path(path)
    _db.init_db()            # runs migrate_db()
    conn = _db.get_db()
    try:
        assert rows(conn, "SELECT id,pid,label,x,y FROM nodes ORDER BY id") == before_n
        assert rows(conn, "SELECT from_id,to_id,kind FROM edges") == before_e
        assert {r[1] for r in conn.execute("PRAGMA table_info(nodes)")} >= {'source_id'}
        assert conn.execute("SELECT COUNT(*) FROM nodes WHERE source_id IS NULL").fetchone()[0] == 2
        # Old node stays addressable by its original bare id.
        assert conn.execute("SELECT label FROM nodes WHERE id='n1' AND pid='old'").fetchone()[0] == 'V-1'
        _db.migrate_db()     # idempotent
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 2
    finally:
        _db.close_db()


def test_migration_on_empty_database_and_indexes_created(tmp_path):
    _db.reset_for_path(tmp_path / 'empty.db')
    _db.init_db()
    conn = _db.get_db()
    try:
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert {'idx_nodes_pid_source', 'idx_edges_pid_source'} <= idx
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0
    finally:
        _db.close_db()


def test_legacy_rows_survive_a_new_document_being_added(db):
    """A pre-migration project gains a second PDF: the legacy rows must stay."""
    db.execute("INSERT INTO nodes (id,pid,label,x,y) VALUES ('n1','P','LEGACY',0.1,0.2)")
    db.commit()
    b = add_source(db, 'P', 'b.pdf', 'hb')
    persist_document(db, 'P', b, doc_nodes(b, 1, 1, ['n1']), [])

    ids = sorted(r[0] for r in rows(db, "SELECT id FROM nodes WHERE pid='P'"))
    assert ids == ['n1', f'{_id_prefix(b, 1, 1)}n1']
    assert rows(db, "SELECT label FROM nodes WHERE id='n1' AND pid='P'") == [('LEGACY',)]


# ── 14. React Flow id uniqueness ────────────────────────────────────────────

def test_node_ids_are_globally_unique_so_react_flow_ids_are(db):
    """React Flow keys nodes by id across the whole canvas. Two documents in
    one project therefore must not produce the same node id."""
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'P', 'b.pdf', 'hb')
    persist_document(db, 'P', a, doc_nodes(a, 1, 2, ['n1', 'gj_0']) + doc_nodes(a, 2, 2, ['n1']), [])
    persist_document(db, 'P', b, doc_nodes(b, 1, 2, ['n1', 'gj_0']) + doc_nodes(b, 2, 2, ['n1']), [])
    ids = [r[0] for r in rows(db, "SELECT id FROM nodes WHERE pid='P'")]
    assert len(ids) == len(set(ids)) == 6


# ── 15. document identity survives the round-trip ───────────────────────────

def test_source_id_is_a_column_not_buried_in_extra_json(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), doc_edges(a, 1, 1, []))
    row = db.execute("SELECT source_id, extra_json FROM nodes WHERE pid='P'").fetchone()
    assert row[0] == a
    assert 'source_id' not in json.loads(row[1] or '{}')


def test_edges_carry_document_identity(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1', 'n2']),
                     doc_edges(a, 1, 1, [('n1', 'n2')]))
    assert rows(db, "SELECT source_id FROM edges WHERE pid='P'") == [(a,)]


def test_rows_from_other_sources_without_identity_keeps_attributed_rows(db):
    """A run with no document identity owns only the UNATTRIBUTED rows.

    This test originally asserted ([], []) — that such a run carried nothing
    forward. Phase 6 found that was the Phase 5 data-loss bug returning by
    another route: _db_persist_espx wipes the whole project first, so carrying
    nothing forward destroyed every document. See
    test_phase6_recovery.test_run_without_source_id_preserves_attributed_documents.
    """
    a = add_source(db, 'P', 'a.pdf', 'ha')
    persist_document(db, 'P', a, doc_nodes(a, 1, 1, ['n1']), [])
    db.execute("INSERT INTO nodes (id,pid,label,x,y) VALUES ('legacy','P','L',0.1,0.1)")
    db.commit()

    kept_n, _ = _rows_from_other_sources('P', None)
    kept_ids = {n['id'] for n in kept_n}
    assert kept_ids == {f'{_id_prefix(a, 1, 1)}n1'}, 'attributed rows must be carried forward'
    assert 'legacy' not in kept_ids, 'the unattributed row is the one this run replaces'
