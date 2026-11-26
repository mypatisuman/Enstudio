"""
migrate_to_sqlite.py — one-time migration of file-based projects → studio.db

Usage (from anywhere):
    python C:\\standard\\studio\\migrate_to_sqlite.py

Reads every project under <ENGINEERING_HUB>/projects/ and inserts the
contents of project.json, <pid>.espx, review.json, canvas.json, and
cache/*.json into the SQLite database created by adapters/db.py.

The script is idempotent: it uses INSERT OR REPLACE so re-running over an
already-populated DB safely overwrites with the latest disk content.
The original files are never modified or deleted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# yaml is used to parse .espx; project.json/review.json/canvas.json are pure JSON
import yaml

# Ensure adapters.db is importable when run as a script. Now lives in
# studio/tools/, so studio/ (parent) needs to be on sys.path.
_STUDIO = Path(__file__).resolve().parents[1]
if str(_STUDIO) not in sys.path:
    sys.path.insert(0, str(_STUDIO))

from adapters import db as _dbmod                            # noqa: E402
from utils.paths import resolve_hub                           # noqa: E402


# ── Default-location resolution ──────────────────────────────────────────────

def _hub_dir() -> Path:
    return resolve_hub(default=Path(r'C:\standard\EngineeringHub'))


# ── Helpers ──────────────────────────────────────────────────────────────────

_NODE_NATIVE_KEYS = {'id', 'kind', 'kind_detail', 'label', 'area', 'x', 'y'}
_EDGE_NATIVE_KEYS = {'from', 'to', 'kind', 'label'}
_INSTR_NATIVE_KEYS = {'tag', 'area', 'kind_detail', 'type', 'equipment_ref'}
_EQUIP_NATIVE_KEYS = {'tag', 'area', 'kind_detail', 'type'}
_CONN_NATIVE_KEYS  = {'id', 'from_tag', 'to_tag', 'type'}


def _read_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'  WARN  read json {path.name}: {e}')
        return None


def _read_yaml(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as e:
        print(f'  WARN  read yaml {path.name}: {e}')
        return None


def _extras(d: Dict[str, Any], native: set) -> Optional[str]:
    extra = {k: v for k, v in d.items() if k not in native}
    return json.dumps(extra, ensure_ascii=False) if extra else None


def _to_real(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ── Per-project ingestion ────────────────────────────────────────────────────

def _ingest_project_json(conn, pid: str, project_dir: Path) -> dict:
    """Insert into projects, sources, exports. Returns the loaded project dict
    (or a synthetic minimal one if project.json doesn't exist)."""
    proj = _read_json(project_dir / 'project.json') or {}

    extraction = proj.get('extraction') or {}
    stats = proj.get('stats') or {}
    metadata: dict = {}  # filled in below from espx (better source)

    conn.execute("""
        INSERT OR REPLACE INTO projects
        (id, title, company, process_type, created, plant_name, revision,
         extraction_locked, last_extraction, status, stats_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pid,
        proj.get('title') or pid,
        proj.get('company'),
        proj.get('process_type'),
        proj.get('created'),
        metadata.get('plant_name'),     # filled in by _ingest_espx if present
        _to_int(metadata.get('revision'), 0) or None,
        1 if metadata.get('extraction_locked') else 0,
        extraction.get('last_run'),
        extraction.get('status'),
        json.dumps(stats, ensure_ascii=False) if stats else None,
    ))

    conn.execute("DELETE FROM sources WHERE pid = ?", (pid,))
    for s in proj.get('sources') or []:
        conn.execute("""
            INSERT INTO sources (pid, filename, file_hash, uploaded, cached)
            VALUES (?, ?, ?, ?, ?)
        """, (
            pid,
            s.get('filename'),
            s.get('hash') or s.get('file_hash'),
            s.get('uploaded'),
            1 if s.get('cached') else 0,
        ))

    conn.execute("DELETE FROM exports WHERE pid = ?", (pid,))
    for e in proj.get('exports') or []:
        conn.execute("""
            INSERT INTO exports (pid, type, filename, exported)
            VALUES (?, ?, ?, ?)
        """, (
            pid,
            e.get('type'),
            e.get('filename'),
            e.get('exported'),
        ))
    return proj


def _refresh_project_metadata(conn, pid: str, espx: dict) -> None:
    """After espx is loaded, backfill plant_name / revision / extraction_locked
    from studio.metadata onto the projects row."""
    studio = espx.get('studio') or {}
    md = studio.get('metadata') or {}
    conn.execute("""
        UPDATE projects
           SET title             = COALESCE(?, title),
               plant_name        = COALESCE(?, plant_name),
               revision          = COALESCE(?, revision),
               extraction_locked = COALESCE(?, extraction_locked),
               process_type      = COALESCE(?, process_type)
         WHERE id = ?
    """, (
        espx.get('title'),
        md.get('plant_name'),
        _to_int(md.get('revision'), 0) or None,
        1 if md.get('extraction_locked') else 0,
        md.get('process_type'),
        pid,
    ))


def _ingest_espx(conn, pid: str, project_dir: Path) -> Tuple[dict, dict]:
    """Insert nodes, edges, instruments, equipment, connections, loops.
    Returns (counts, espx) for the per-project summary."""
    counts = {'nodes': 0, 'edges': 0, 'instruments': 0, 'equipment': 0,
              'connections': 0, 'loops': 0}
    espx_path = project_dir / f'{project_dir.name}.espx'
    espx = _read_yaml(espx_path) or {}
    if not isinstance(espx, dict):
        return counts, {}

    # --- nodes -----------------------------------------------------------------
    conn.execute("DELETE FROM nodes WHERE pid = ?", (pid,))
    for n in espx.get('nodes') or []:
        if not isinstance(n, dict) or not n.get('id'):
            continue
        conn.execute("""
            INSERT OR REPLACE INTO nodes
            (id, pid, kind, kind_detail, label, area, x, y, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            n['id'], pid,
            n.get('kind') or n.get('type'), n.get('kind_detail'),
            n.get('label'), n.get('area'),
            _to_real(n.get('x')), _to_real(n.get('y')),
            _extras(n, _NODE_NATIVE_KEYS),
        ))
        counts['nodes'] += 1

    # --- edges -----------------------------------------------------------------
    conn.execute("DELETE FROM edges WHERE pid = ?", (pid,))
    for e in espx.get('edges') or []:
        if not isinstance(e, dict):
            continue
        conn.execute("""
            INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            pid,
            e.get('from'), e.get('to'),
            e.get('kind'), e.get('label'),
            _extras(e, _EDGE_NATIVE_KEYS),
        ))
        counts['edges'] += 1

    studio = espx.get('studio') or {}

    # --- instruments -----------------------------------------------------------
    conn.execute("DELETE FROM instruments WHERE pid = ?", (pid,))
    for tag, data in (studio.get('instruments') or {}).items():
        if not isinstance(data, dict):
            data = {'value': data}
        conn.execute("""
            INSERT OR REPLACE INTO instruments
            (tag, pid, area, kind_detail, type, equipment_ref, extra_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            tag, pid,
            data.get('area'), data.get('kind_detail'),
            data.get('type'), data.get('equipment_ref'),
            _extras(data, _INSTR_NATIVE_KEYS),
        ))
        counts['instruments'] += 1

    # --- equipment -------------------------------------------------------------
    conn.execute("DELETE FROM equipment WHERE pid = ?", (pid,))
    for tag, data in (studio.get('equipment') or {}).items():
        if not isinstance(data, dict):
            data = {'value': data}
        conn.execute("""
            INSERT OR REPLACE INTO equipment
            (tag, pid, area, kind_detail, type, extra_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            tag, pid,
            data.get('area'), data.get('kind_detail'),
            data.get('type'),
            _extras(data, _EQUIP_NATIVE_KEYS),
        ))
        counts['equipment'] += 1

    # --- connections -----------------------------------------------------------
    conn.execute("DELETE FROM connections WHERE pid = ?", (pid,))
    for i, c in enumerate(studio.get('connections') or []):
        if not isinstance(c, dict):
            continue
        cid = c.get('id') or f'__auto_{i}'  # generate if missing — needed for PK
        conn.execute("""
            INSERT OR REPLACE INTO connections
            (id, pid, from_tag, to_tag, type, extra_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            cid, pid,
            c.get('from_tag'), c.get('to_tag'), c.get('type'),
            _extras(c, _CONN_NATIVE_KEYS),
        ))
        counts['connections'] += 1

    # --- loops -----------------------------------------------------------------
    conn.execute("DELETE FROM loops WHERE pid = ?", (pid,))
    for loop_id, loop in (studio.get('loops') or {}).items():
        conn.execute("""
            INSERT OR REPLACE INTO loops (loop_id, pid, loop_json)
            VALUES (?, ?, ?)
        """, (
            loop_id, pid,
            json.dumps(loop, ensure_ascii=False),
        ))
        counts['loops'] += 1

    # Backfill projects row from studio.metadata
    _refresh_project_metadata(conn, pid, espx)

    return counts, espx


def _ingest_review(conn, pid: str, project_dir: Path,
                    espx_review: Optional[dict] = None) -> int:
    """Insert review.json into review table. If review.json doesn't exist on
    disk, fall back to studio.review from the espx (same content shape)."""
    review = _read_json(project_dir / 'review.json')
    if review is None:
        review = espx_review or {}
    if not isinstance(review, dict):
        return 0
    conn.execute("DELETE FROM review WHERE pid = ?", (pid,))
    n = 0
    for key, state in review.items():
        conn.execute("""
            INSERT OR REPLACE INTO review (pid, key, state) VALUES (?, ?, ?)
        """, (pid, str(key), str(state)))
        n += 1
    return n


def _ingest_canvas(conn, pid: str, project_dir: Path) -> int:
    canvas = _read_json(project_dir / 'canvas.json')
    if not isinstance(canvas, dict):
        return 0
    conn.execute("DELETE FROM canvas_positions WHERE pid = ?", (pid,))
    n = 0
    for node_id, pos in canvas.items():
        if not isinstance(pos, dict):
            continue
        conn.execute("""
            INSERT OR REPLACE INTO canvas_positions
            (pid, node_id, x, y) VALUES (?, ?, ?, ?)
        """, (pid, node_id, _to_real(pos.get('x')), _to_real(pos.get('y'))))
        n += 1
    return n


def _ingest_cache(conn, pid: str, project_dir: Path) -> int:
    cache_dir = project_dir / 'cache'
    if not cache_dir.exists():
        return 0
    conn.execute("DELETE FROM cache_entries WHERE pid = ?", (pid,))
    n = 0
    for f in sorted(cache_dir.glob('*.json')):
        if f.name == 'cache_manifest.json':
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'  WARN  cache file {f.name}: {e}')
            continue
        conn.execute("""
            INSERT OR REPLACE INTO cache_entries
            (pid, cache_key, data_json) VALUES (?, ?, ?)
        """, (pid, f.stem, json.dumps(data, ensure_ascii=False)))
        n += 1

    # Cache manifest — single row per project per the schema
    manifest = _read_json(cache_dir / 'cache_manifest.json')
    conn.execute("DELETE FROM cache_manifest WHERE pid = ?", (pid,))
    if isinstance(manifest, dict):
        conn.execute("""
            INSERT OR REPLACE INTO cache_manifest
            (pid, scan_json, total_tokens, total_cost, last_scan)
            VALUES (?, ?, ?, ?, ?)
        """, (
            pid,
            json.dumps(manifest.get('scans') or [], ensure_ascii=False),
            _to_int(manifest.get('total_tokens'), 0),
            float(manifest.get('total_cost_usd') or manifest.get('total_cost') or 0.0),
            manifest.get('last_scan'),
        ))
    return n


# ── Top-level migration driver ───────────────────────────────────────────────

def migrate_all(hub: Optional[Path] = None) -> None:
    hub = hub or _hub_dir()
    projects_root = hub / 'projects'
    if not projects_root.exists():
        print(f'No projects directory at {projects_root}; nothing to do.')
        return

    # Force the db module to write into the desired location
    db_target = hub / 'studio.db'
    _dbmod.reset_for_path(db_target)
    _dbmod.init_db()
    conn = _dbmod.get_db()

    pids = sorted(p.name for p in projects_root.iterdir() if p.is_dir())
    print(f'Migrating {len(pids)} project(s) into {db_target}')
    print(f'  hub: {hub}')
    print()

    grand: Dict[str, int] = {
        'projects': 0, 'sources': 0, 'exports': 0,
        'nodes': 0, 'edges': 0, 'instruments': 0, 'equipment': 0,
        'connections': 0, 'loops': 0, 'review': 0, 'canvas_positions': 0,
        'cache_entries': 0, 'cache_manifest': 0, 'proposals': 0,
    }

    for pid in pids:
        project_dir = projects_root / pid
        try:
            conn.execute('BEGIN')
            _ingest_project_json(conn, pid, project_dir)
            counts, espx = _ingest_espx(conn, pid, project_dir)
            review_count = _ingest_review(
                conn, pid, project_dir,
                espx_review=(espx.get('studio') or {}).get('review'),
            )
            canvas_count = _ingest_canvas(conn, pid, project_dir)
            cache_count  = _ingest_cache(conn, pid, project_dir)
            conn.execute('COMMIT')
        except Exception as e:
            conn.execute('ROLLBACK')
            print(f'  {pid}: FAILED — {e}')
            continue

        print(
            f'  {pid:6s}: {counts["nodes"]:>4} nodes, '
            f'{counts["edges"]:>4} edges, '
            f'{counts["instruments"]:>4} instruments, '
            f'{counts["equipment"]:>4} equipment, '
            f'{counts["connections"]:>4} connections, '
            f'{counts["loops"]:>3} loops, '
            f'{review_count:>3} review, '
            f'{canvas_count:>4} canvas positions, '
            f'{cache_count:>3} cache entries'
        )

    # Final totals — query each table once for ground truth
    print()
    print('=== Totals across all tables ===')
    for tbl in (
        'projects', 'sources', 'exports',
        'nodes', 'edges', 'instruments', 'equipment',
        'connections', 'loops', 'review',
        'canvas_positions', 'cache_entries', 'cache_manifest',
        'proposals',
    ):
        n = conn.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
        print(f'  {tbl:18s} : {n}')
    print()
    print(f'Done — DB at {db_target} ({db_target.stat().st_size:,} bytes)')


if __name__ == '__main__':
    migrate_all()
