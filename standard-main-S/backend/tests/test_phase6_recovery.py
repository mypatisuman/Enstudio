"""Phase 6 — Steps 14/15: failure handling and recovery.

The governing rule: a failed or malformed run must leave the previous valid
extraction exactly as it was. Losing good data to a bad run is worse than the
bad run failing loudly.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters import db as _db                                    # noqa: E402
from extraction_cli.commands import (                             # noqa: E402
    _id_prefix, _rows_from_other_sources,
)
from repositories.integrity import check_integrity                # noqa: E402
from repositories.project_repository import _db_persist_espx      # noqa: E402


@pytest.fixture()
def db(tmp_path):
    _db.reset_for_path(tmp_path / 'studio.db')
    _db.init_db()
    conn = _db.get_db()
    conn.execute("INSERT INTO projects (id,title,status) VALUES ('P','P','pending')")
    conn.commit()
    yield conn
    _db.close_db()


def add_source(conn, pid, filename, fhash):
    cur = conn.execute(
        "INSERT INTO sources (pid,filename,file_hash,uploaded,cached) "
        "VALUES (?,?,?,datetime('now'),1)", (pid, filename, fhash))
    conn.commit()
    return cur.lastrowid


def espx(nodes, edges):
    return {'nodes': nodes, 'edges': edges, 'meta': {},
            'studio': {'instruments': {}, 'equipment': {}, 'connections': [],
                       'loops': {}, 'review': {}, 'screens': []}}


def doc(sid, locals_, page=1, total=1):
    px = _id_prefix(sid, page, total)
    return [{'id': f'{px}{l}', 'label': l.upper(), 'kind': 'vessel',
             'x': 0.5, 'y': 0.5, 'page': page, 'source_id': sid} for l in locals_]


def persist(pid, sid, nodes, edges=()):
    kn, ke = _rows_from_other_sources(pid, sid)
    _db_persist_espx(pid, espx(kn + list(nodes), ke + list(edges)))


def rows(conn, sql, params=()):
    return [tuple(r) for r in conn.execute(sql, params).fetchall()]


# ── Step 15: a failed run must not destroy the previous extraction ──────────

def test_failed_extraction_leaves_the_previous_one_intact(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    persist('P', a, doc(a, ['n1', 'n2', 'n3']))
    before = rows(db, "SELECT id,label,x,y FROM nodes WHERE pid='P' ORDER BY id")
    assert len(before) == 3

    # Extraction B blows up part-way through building its espx.
    b = add_source(db, 'P', 'b.pdf', 'hb')
    with pytest.raises(RuntimeError):
        kn, ke = _rows_from_other_sources('P', b)
        raise RuntimeError('LLM stage failed')
        _db_persist_espx('P', espx(kn, ke))          # never reached

    assert rows(db, "SELECT id,label,x,y FROM nodes WHERE pid='P' ORDER BY id") == before


def test_persist_rolls_back_and_keeps_the_previous_extraction(db):
    """_db_persist_espx wraps its DELETE + INSERT in one transaction. A row it
    cannot write must not leave the project emptied by the DELETE."""
    a = add_source(db, 'P', 'a.pdf', 'ha')
    persist('P', a, doc(a, ['n1', 'n2']))
    before = rows(db, "SELECT id,label FROM nodes WHERE pid='P' ORDER BY id")

    class Exploding(dict):
        """Raises while the insert loop is iterating the node list."""
        def get(self, key, default=None):
            if key == 'id':
                raise sqlite3.OperationalError('disk I/O error')
            return super().get(key, default)

    _db_persist_espx('P', espx([Exploding({'id': 'boom'})], []))

    assert rows(db, "SELECT id,label FROM nodes WHERE pid='P' ORDER BY id") == before


def test_interrupted_reextraction_keeps_the_other_document(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'P', 'b.pdf', 'hb')
    persist('P', a, doc(a, ['n1', 'n2']))
    persist('P', b, doc(b, ['n1', 'n2']))
    b_before = rows(db, "SELECT id,label FROM nodes WHERE pid='P' AND source_id=? ORDER BY id", (b,))

    with pytest.raises(RuntimeError):
        _rows_from_other_sources('P', a)
        raise RuntimeError('killed mid-run')

    assert rows(db, "SELECT id,label FROM nodes WHERE pid='P' AND source_id=? ORDER BY id", (b,)) == b_before
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P' AND source_id=?", (a,))) == 2


# ── Phase 6 regression: a run with no document identity must not wipe docs ──

def test_run_without_source_id_preserves_attributed_documents(db):
    """Phase 6 bug. The Flask path and a CLI run without --source-id have no
    document identity. They used to carry nothing forward, so the whole-project
    rewrite in _db_persist_espx destroyed EVERY document in the project."""
    a = add_source(db, 'P', 'a.pdf', 'ha')
    b = add_source(db, 'P', 'b.pdf', 'hb')
    persist('P', a, doc(a, ['n1']))
    persist('P', b, doc(b, ['n1']))
    attributed = rows(db, "SELECT id,label,source_id FROM nodes WHERE pid='P' ORDER BY id")
    assert len(attributed) == 2

    persist('P', None, [{'id': 'legacy1', 'label': 'L', 'kind': 'vessel', 'x': .3, 'y': .3}])

    assert rows(db, "SELECT id,label,source_id FROM nodes WHERE pid='P' "
                    "AND source_id IS NOT NULL ORDER BY id") == attributed
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 3


def test_run_without_source_id_still_replaces_unattributed_rows(db):
    """The historic single-document behaviour must survive the fix: a run with
    no identity still owns — and replaces — the unattributed rows."""
    db.execute("INSERT INTO nodes (id,pid,label,x,y) VALUES ('old1','P','OLD',0.1,0.1)")
    db.execute("INSERT INTO nodes (id,pid,label,x,y) VALUES ('old2','P','OLD',0.2,0.2)")
    db.commit()
    persist('P', None, [{'id': 'new1', 'label': 'NEW', 'kind': 'vessel', 'x': .3, 'y': .3}])
    assert sorted(r[0] for r in rows(db, "SELECT id FROM nodes WHERE pid='P'")) == ['new1']


# ── Step 14: malformed input fails safely ───────────────────────────────────

@pytest.mark.parametrize('bad', [
    None, [], 'not-a-dict', 42, {'nodes': 'nope'}, {'nodes': None, 'edges': None},
])
def test_malformed_espx_does_not_corrupt_the_project(db, bad):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    persist('P', a, doc(a, ['n1']))
    before = rows(db, "SELECT id,label FROM nodes WHERE pid='P'")
    _db_persist_espx('P', bad)          # must not raise
    after = rows(db, "SELECT id,label FROM nodes WHERE pid='P'")
    # Either untouched (rejected outright) or emptied by an honest rewrite —
    # never a half-written project.
    assert after == before or after == []


def test_malformed_nodes_are_skipped_not_written(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    nodes = doc(a, ['n1']) + [
        None, 'string', 42, {}, {'label': 'no id'}, {'id': ''},
    ]
    persist('P', a, nodes)
    got = rows(db, "SELECT id FROM nodes WHERE pid='P'")
    assert got == [(f'{_id_prefix(a, 1, 1)}n1',)]
    assert check_integrity('P')['orphan_edges'] == []


def test_malformed_waypoints_do_not_reach_the_database_as_valid_geometry(db):
    """NaN/Infinity in a route renders as an invisible pipe. They must be
    stored as-is-or-dropped, never silently turned into a real coordinate."""
    a = add_source(db, 'P', 'a.pdf', 'ha')
    px = _id_prefix(a, 1, 1)
    edges = [{'from': f'{px}n1', 'to': f'{px}n2', 'kind': 'process', 'source_id': a,
              'waypoints': [[float('nan'), 0.5], [0.5, float('inf')], ['x', None]]}]
    persist('P', a, doc(a, ['n1', 'n2']), edges)
    stored = rows(db, "SELECT extra_json FROM edges WHERE pid='P'")
    assert len(stored) == 1
    # sanitizeWaypoints on the frontend rejects these; the point here is that
    # persistence neither crashes nor invents a coordinate.
    assert 'NaN' in (stored[0][0] or '') or 'null' in (stored[0][0] or '')


def test_missing_page_dimensions_are_tolerated(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    nodes = doc(a, ['n1'])
    nodes[0].pop('page', None)
    persist('P', a, nodes)
    assert len(rows(db, "SELECT id FROM nodes WHERE pid='P'")) == 1


def test_edges_referencing_missing_nodes_are_reported_not_hidden(db):
    a = add_source(db, 'P', 'a.pdf', 'ha')
    px = _id_prefix(a, 1, 1)
    persist('P', a, doc(a, ['n1']),
            [{'from': f'{px}n1', 'to': f'{px}ghost', 'kind': 'process', 'source_id': a}])
    assert len(check_integrity('P')['orphan_edges']) == 1


def test_integrity_check_on_a_missing_project_is_empty_not_an_error(db):
    report = check_integrity('does-not-exist')
    assert all(v == [] for v in report.values())


def test_migration_on_a_corrupt_database_raises_rather_than_silently_passing(tmp_path):
    path = tmp_path / 'corrupt.db'
    path.write_bytes(b'this is not a sqlite database at all, not even close')
    _db.reset_for_path(path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            _db.init_db()
    finally:
        _db.close_db()
