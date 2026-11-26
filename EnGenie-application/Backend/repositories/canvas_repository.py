"""
repositories/canvas_repository.py — canvas-position SQL and espx file/DB I/O.

Extracted from main.py (Phase 5): _db_get_canvas(), _db_write_canvas_positions(),
_load_canvas_positions(), load_espx(), save_espx() — moved verbatim, grouped
here because all five own "canvas" as a business resource (raw canvas_positions
SQL, the higher-level auto-seeding read, and the espx read/write that
canvas-adjacent routes drive). No graph reconstruction, connector merging, or
drawing-linking logic moved — that stays in main.py/domain per the phase rules.

load_espx()/save_espx() need `projects_dir` (main.py's PROJECTS_DIR) and
load_espx() also needs the project repository's `_db_get_project()` — both
passed/imported explicitly rather than reaching back into main.py. main.py
keeps thin wrappers with the original signatures (see Step 7).

Depends on adapters.db (shared sqlite3 connection), repositories.project_repository
(for _db_get_project), and stdlib (pathlib, yaml). No Flask, no CV/LLM imports.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from adapters import db as _db
from repositories.project_repository import _db_get_project


def _db_get_canvas(pid: str) -> dict:
    """Replacement for canvas.json read."""
    conn = _db.get_db()
    rows = conn.execute(
        'SELECT node_id, x, y FROM canvas_positions WHERE pid = ?', (pid,)
    ).fetchall()
    return {r['node_id']: {'x': r['x'], 'y': r['y']} for r in rows}


def _db_write_canvas_positions(pid: str, positions: dict) -> None:
    """positions: {node_id: {x, y}}."""
    conn = _db.get_db()
    conn.execute('BEGIN')
    try:
        conn.execute('DELETE FROM canvas_positions WHERE pid = ?', (pid,))
        for nid, p in positions.items():
            if not isinstance(p, dict):
                continue
            try:
                xv = float(p.get('x'))
                yv = float(p.get('y'))
            except (TypeError, ValueError):
                continue
            conn.execute(
                'INSERT INTO canvas_positions (pid, node_id, x, y) '
                'VALUES (?, ?, ?, ?)',
                (pid, nid, xv, yv),
            )
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise


def _load_canvas_positions(pid: str, espx: dict = None) -> dict | None:
    """Return {node_id: (x, y)} from the DB.

    If no canvas_positions rows exist for `pid` yet, auto-seed from the
    normalised x/y on `espx` nodes and persist them so subsequent reads are
    cheap. canvas.json is no longer touched."""
    conn = _db.get_db()
    rows = conn.execute(
        'SELECT node_id, x, y FROM canvas_positions WHERE pid = ?', (pid,)
    ).fetchall()
    if rows:
        # x/y are NOT NULL for every row written via _db_write_canvas_positions
        # (it already skips unconvertible values before inserting), but the
        # one-time tools/migrate_to_sqlite.py ingest path can insert NULL for
        # a malformed legacy canvas.json entry — skip those instead of
        # crashing on float(None).
        return {
            r['node_id']: (float(r['x']), float(r['y']))
            for r in rows if r['x'] is not None and r['y'] is not None
        }

    if espx:
        CANVAS_W, CANVAS_H = 1400, 800
        seeded = {}
        for n in espx.get('nodes') or []:
            x, y = n.get('x', 0), n.get('y', 0)
            if 0 < x <= 1 and 0 < y <= 1:
                seeded[n['id']] = (round(x * CANVAS_W), round(y * CANVAS_H))
        if seeded:
            try:
                _db_write_canvas_positions(
                    pid, {nid: {'x': v[0], 'y': v[1]} for nid, v in seeded.items()}
                )
            except Exception as e:
                print(f'_load_canvas_positions DB seed failed for {pid}: {e}')
            return seeded
    return None


def load_espx(pid: str, projects_dir: Path):
    """DB-backed espx load. Returns (espx_dict_or_None, dummy_path).

    The second tuple element is preserved for signature compatibility with
    legacy callers — the path is no longer written to. If the DB has no
    record of `pid`, returns ({}, dummy_path) so callers that mutate the
    dict before persisting still work.
    """
    dummy_path = projects_dir / pid / f'{pid}.espx'
    espx = _db_get_project(pid)
    if espx is None:
        return {}, dummy_path
    return espx, dummy_path


def save_espx(pid: str, espx: dict, projects_dir: Path) -> None:
    """Write the espx dict to EngineeringHub/projects/<pid>/<pid>.espx YAML.

    The DB is the system of record (see _db_persist_espx), but the mcpserver
    package reads the YAML file directly. Call save_espx alongside _db_persist_espx on
    extraction completion so both stay in lockstep — otherwise MCP queries
    against newly-extracted projects return zero results.
    """
    if not isinstance(espx, dict):
        return
    pdir = projects_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f'{pid}.espx').write_text(
        yaml.safe_dump(espx, allow_unicode=True,
                       default_flow_style=False, sort_keys=False),
        encoding='utf-8',
    )
