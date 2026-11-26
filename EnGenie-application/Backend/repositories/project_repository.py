"""
repositories/project_repository.py — SQLite-backed project CRUD.

Extracted from main.py (Phase 5): project listing/lookup, row-to-dict
mapping, and the bulk espx-to-DB writer, moved verbatim. Every SQL
statement, table, column, and query shape is unchanged — this module only
relocates the code, it does not touch schema, queries, or transaction
behavior (see adapters/db.py for the schema itself, untouched since Phase 2).

Depends only on `adapters.db` (the shared sqlite3 connection) and stdlib.
No Flask, no routes, no CV/LLM imports.
"""
from __future__ import annotations

import json

from adapters import db as _db


def _db_list_projects(user_id: int | None = None) -> list:
    """Replacement for the directory walk in GET /api/projects."""
    conn = _db.get_db()

    query = (
        'SELECT id, title, plant_name, revision, process_type, '
        '       extraction_locked, last_extraction, status, stats_json '
        '  FROM projects '
    )
    params = []
    if user_id is not None:
        query += ' WHERE user_id = ? '
        params.append(user_id)
    query += ' ORDER BY id'

    rows = conn.execute(query, params).fetchall()
    out = []
    for r in rows:
        try:
            stats = json.loads(r['stats_json']) if r['stats_json'] else {}
        except Exception:
            stats = {}
        # exports — most recent timestamp wins for last_export
        last_export_row = conn.execute(
            'SELECT exported FROM exports WHERE pid = ? '
            'ORDER BY exported DESC LIMIT 1', (r['id'],)
        ).fetchone()
        # latest export type presence flags (mimics has_vids / has_ympl)
        types_present = {row['type'] for row in conn.execute(
            'SELECT DISTINCT type FROM exports WHERE pid = ?', (r['id'],)
        ).fetchall()}
        sources_rows = conn.execute(
            'SELECT filename, file_hash, uploaded, cached '
            '  FROM sources WHERE pid = ? ORDER BY id', (r['id'],)
        ).fetchall()
        sources = [
            {'filename': sr['filename'], 'hash': sr['file_hash'],
             'uploaded': sr['uploaded'], 'cached': bool(sr['cached'])}
            for sr in sources_rows
        ]
        out.append({
            'id':                 r['id'],
            'name':               r['plant_name'] or r['title'] or r['id'],
            'revision':           r['revision'] or 1,
            'process_type':       r['process_type'] or '',
            'n_instruments':      stats.get('n_instruments',
                                            stats.get('instruments', 0)),
            'n_equipment':        stats.get('n_equipment',
                                            stats.get('equipment', 0)),
            'has_vids':           'vids' in types_present,
            'has_ympl':           'ympl' in types_present,
            'extraction_status':  r['status'] or 'none',
            'extraction_locked':  bool(r['extraction_locked']),
            'last_extract':       r['last_extraction'] or '',
            'last_export':        last_export_row['exported'] if last_export_row else '',
            'sources':            sources,
        })
    return out


def _db_get_project(pid: str) -> dict | None:
    """Reconstruct an espx-shaped dict from the DB for GET /api/projects/<pid>.
    Mirrors the response that the existing file-based code returned (top-level
    nodes/edges/meta/studio + metadata stamped from projects row)."""
    conn = _db.get_db()
    proj = conn.execute(
        'SELECT * FROM projects WHERE id = ?', (pid,)
    ).fetchone()
    if proj is None:
        return None
    nodes = [_row_to_node(r) for r in conn.execute(
        'SELECT * FROM nodes WHERE pid = ? ORDER BY id', (pid,)
    ).fetchall()]
    edges = [_row_to_edge(r) for r in conn.execute(
        'SELECT * FROM edges WHERE pid = ? ORDER BY id', (pid,)
    ).fetchall()]
    instruments = {}
    for r in conn.execute('SELECT * FROM instruments WHERE pid = ?', (pid,)).fetchall():
        instruments[r['tag']] = _row_to_instrument(r)
    equipment = {}
    for r in conn.execute('SELECT * FROM equipment WHERE pid = ?', (pid,)).fetchall():
        equipment[r['tag']] = _row_to_equipment(r)
    connections = []
    for r in conn.execute('SELECT * FROM connections WHERE pid = ?', (pid,)).fetchall():
        connections.append(_row_to_connection(r))
    loops = {}
    for r in conn.execute('SELECT * FROM loops WHERE pid = ?', (pid,)).fetchall():
        try:
            loops[r['loop_id']] = json.loads(r['loop_json'] or '{}')
        except Exception:
            loops[r['loop_id']] = {}
    review_state = {r['key']: r['state'] for r in conn.execute(
        'SELECT key, state FROM review WHERE pid = ?', (pid,)
    ).fetchall()}

    espx = {
        'schema_version': 'ympl-1.0',
        'id':             proj['id'],
        'title':          proj['title'] or proj['id'],
        'nodes':          nodes,
        'edges':          edges,
        'meta':           {'confidence': 'high', 'mermaid': '', 'source': 'sqlite'},
        'studio': {
            'metadata': {
                'plant_name':        proj['plant_name'] or proj['id'],
                'process_type':      proj['process_type'] or 'generic',
                'revision':          proj['revision'] or 1,
                'extraction_locked': bool(proj['extraction_locked']),
            },
            'instruments': instruments,
            'equipment':   equipment,
            'connections': connections,
            'loops':       loops,
            'screens':     [],
            'review':      review_state,
        },
    }
    return espx


def _row_to_node(r) -> dict:
    n = {'id': r['id'], 'kind': r['kind'], 'label': r['label']}
    if r['kind_detail']:        n['kind_detail'] = r['kind_detail']
    if r['area']:               n['area']        = r['area']
    if r['x'] is not None:      n['x']           = r['x']
    if r['y'] is not None:      n['y']           = r['y']
    if r['extra_json']:
        try:
            n.update(json.loads(r['extra_json']))
        except Exception:
            pass
    return n


def _row_to_edge(r) -> dict:
    e = {'from': r['from_id'], 'to': r['to_id']}
    if r['kind']:  e['kind']  = r['kind']
    if r['label']: e['label'] = r['label']
    if r['extra_json']:
        try:
            e.update(json.loads(r['extra_json']))
        except Exception:
            pass
    return e


def _row_to_instrument(r) -> dict:
    d = {'tag': r['tag']}
    if r['type']:          d['type']          = r['type']
    if r['kind_detail']:   d['kind_detail']   = r['kind_detail']
    if r['area']:          d['area']          = r['area']
    if r['equipment_ref']: d['equipment_ref'] = r['equipment_ref']
    if r['extra_json']:
        try: d.update(json.loads(r['extra_json']))
        except Exception: pass
    return d


def _row_to_equipment(r) -> dict:
    d = {'tag': r['tag']}
    if r['type']:        d['type']        = r['type']
    if r['kind_detail']: d['kind_detail'] = r['kind_detail']
    if r['area']:        d['area']        = r['area']
    if r['extra_json']:
        try: d.update(json.loads(r['extra_json']))
        except Exception: pass
    return d


def _row_to_connection(r) -> dict:
    c = {'id': r['id']}
    if r['from_tag']: c['from_tag'] = r['from_tag']
    if r['to_tag']:   c['to_tag']   = r['to_tag']
    if r['type']:     c['type']     = r['type']
    if r['extra_json']:
        try: c.update(json.loads(r['extra_json']))
        except Exception: pass
    return c


def _db_get_review(pid: str) -> dict:
    conn = _db.get_db()
    rows = conn.execute(
        'SELECT key, state FROM review WHERE pid = ?', (pid,)
    ).fetchall()
    return {r['key']: r['state'] for r in rows}


def _db_write_review(pid: str, key: str, state: str) -> None:
    conn = _db.get_db()
    conn.execute(
        'INSERT OR REPLACE INTO review (pid, key, state) VALUES (?, ?, ?)',
        (pid, key, state),
    )


# source_id is a real column now (Phase 5), so keep it out of extra_json —
# storing it in both places lets the two copies disagree.
_NODE_DB_NATIVE = {'id', 'kind', 'kind_detail', 'label', 'area', 'x', 'y', 'source_id'}
_EDGE_DB_NATIVE = {'from', 'to', 'kind', 'label', 'source_id'}
_INSTR_DB_NATIVE = {'tag', 'area', 'kind_detail', 'type', 'equipment_ref'}
_EQUIP_DB_NATIVE = {'tag', 'area', 'kind_detail', 'type'}
_CONN_DB_NATIVE = {'id', 'from_tag', 'to_tag', 'type'}


def _extras_json(d: dict, native: set) -> str | None:
    extra = {k: v for k, v in (d or {}).items() if k not in native}
    return json.dumps(extra, ensure_ascii=False) if extra else None


def _to_source_id(v):
    """sources.id or None. Anything unparseable is stored as NULL rather than
    guessed at — a wrong document attribution is worse than an absent one."""
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _to_real(v):
    try: return float(v) if v is not None else None
    except (TypeError, ValueError): return None


def _db_persist_espx(pid: str, espx: dict) -> None:
    """Bulk-write espx contents to nodes/edges/instruments/equipment/
    connections/loops tables. Used by rebuild_espx_from_cache and the editor
    POST so the DB stays in lockstep with the .espx file.

    This deletes the whole project before re-inserting, so the espx handed in
    must be the COMPLETE project — every document, not just the one that was
    last extracted. That contract was previously implicit and violated by the
    extraction path, which passed only the current run's nodes and so wiped
    every other PDF in the project (Phase 5). `_merge` now carries the other
    documents' rows through; see extraction_cli.commands._rows_from_other_sources.

    Each row keeps the `source_id` its node/edge carries, so document identity
    survives the round-trip. A node with no source_id (legacy data, or the
    Flask path which has no sources row) is stored with NULL, which reads as
    "belongs to the project, document unknown"."""
    if not isinstance(espx, dict):
        return
    conn = _db.get_db()
    conn.execute('BEGIN')
    try:
        conn.execute('DELETE FROM nodes        WHERE pid = ?', (pid,))
        conn.execute('DELETE FROM edges        WHERE pid = ?', (pid,))
        conn.execute('DELETE FROM instruments  WHERE pid = ?', (pid,))
        conn.execute('DELETE FROM equipment    WHERE pid = ?', (pid,))
        conn.execute('DELETE FROM connections  WHERE pid = ?', (pid,))
        conn.execute('DELETE FROM loops        WHERE pid = ?', (pid,))

        for n in espx.get('nodes') or []:
            if not isinstance(n, dict) or not n.get('id'):
                continue
            conn.execute(
                'INSERT OR REPLACE INTO nodes '
                '(id, pid, kind, kind_detail, label, area, x, y, extra_json, source_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (n['id'], pid, n.get('kind') or n.get('type'), n.get('kind_detail'),
                 n.get('label'), n.get('area'),
                 _to_real(n.get('x')), _to_real(n.get('y')),
                 _extras_json(n, _NODE_DB_NATIVE), _to_source_id(n.get('source_id'))),
            )

        for e in espx.get('edges') or []:
            if not isinstance(e, dict):
                continue
            conn.execute(
                'INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json, source_id) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (pid, e.get('from'), e.get('to'),
                 e.get('kind'), e.get('label'),
                 _extras_json(e, _EDGE_DB_NATIVE), _to_source_id(e.get('source_id'))),
            )

        studio = espx.get('studio') or {}
        for tag, data in (studio.get('instruments') or {}).items():
            if not isinstance(data, dict):
                data = {'value': data}
            conn.execute(
                'INSERT OR REPLACE INTO instruments '
                '(tag, pid, area, kind_detail, type, equipment_ref, extra_json) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (tag, pid, data.get('area'), data.get('kind_detail'),
                 data.get('type'), data.get('equipment_ref'),
                 _extras_json(data, _INSTR_DB_NATIVE)),
            )
        for tag, data in (studio.get('equipment') or {}).items():
            if not isinstance(data, dict):
                data = {'value': data}
            conn.execute(
                'INSERT OR REPLACE INTO equipment '
                '(tag, pid, area, kind_detail, type, extra_json) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (tag, pid, data.get('area'), data.get('kind_detail'),
                 data.get('type'),
                 _extras_json(data, _EQUIP_DB_NATIVE)),
            )
        for i, c in enumerate(studio.get('connections') or []):
            if not isinstance(c, dict):
                continue
            cid = c.get('id') or f'__auto_{i}'
            conn.execute(
                'INSERT OR REPLACE INTO connections '
                '(id, pid, from_tag, to_tag, type, extra_json) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (cid, pid, c.get('from_tag'), c.get('to_tag'), c.get('type'),
                 _extras_json(c, _CONN_DB_NATIVE)),
            )
        for loop_id, loop in (studio.get('loops') or {}).items():
            conn.execute(
                'INSERT OR REPLACE INTO loops (loop_id, pid, loop_json) '
                'VALUES (?, ?, ?)',
                (loop_id, pid, json.dumps(loop, ensure_ascii=False)),
            )

        # Keep the projects row metadata fresh — this is the only place we
        # learn plant_name / revision from rebuild output.
        md = studio.get('metadata') or {}
        conn.execute(
            'INSERT OR IGNORE INTO projects (id, title) VALUES (?, ?)',
            (pid, espx.get('title') or pid),
        )
        conn.execute(
            'UPDATE projects SET '
            '  title             = COALESCE(?, title), '
            '  plant_name        = COALESCE(?, plant_name), '
            '  process_type      = COALESCE(?, process_type), '
            '  revision          = COALESCE(?, revision), '
            '  extraction_locked = COALESCE(?, extraction_locked) '
            'WHERE id = ?',
            (espx.get('title'),
             md.get('plant_name'),
             md.get('process_type'),
             int(md['revision']) if md.get('revision') else None,
             1 if md.get('extraction_locked') else None,
             pid),
        )
        conn.execute('COMMIT')
    except Exception as _e:
        conn.execute('ROLLBACK')
        print(f'_db_persist_espx({pid}) failed: {_e}')
