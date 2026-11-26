"""
mcpserver/handlers.py -- protocol-independent business-logic helpers shared
by the tool implementations in tools.py: espx/manifest loading, company
conventions lookup, project listing, sqlite access, API-key resolution, and
the DB-to-espx sync used by the sync_project tool.

Extracted from mcp_server.py (Phase 12), moved verbatim. Contains no `mcp`
SDK types/imports -- pure data access and business logic, matching this
module's protocol-independence requirement.
"""
from __future__ import annotations

import json
import sqlite3

import yaml

from adapters.company import CompanyConventions

from .server import HUB, PROJECTS_DIR, SKILLS_DIR


def load_espx(pid: str) -> dict:
    path = PROJECTS_DIR / pid / f'{pid}.espx'
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except UnicodeDecodeError:
        text = path.read_text(encoding='latin-1')
        path.write_text(text, encoding='utf-8')
        return yaml.safe_load(text) or {}


def load_manifest(pid: str) -> dict:
    path = PROJECTS_DIR / pid / 'project.json'
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


_conventions_cache: dict = {}


def project_conventions(pid: str):
    """Load merged conventions (registry baseline + HUB override) for the
    project's company, or None if no company is set / no convention files
    exist. Cached per-pid for the lifetime of the MCP process."""
    if pid in _conventions_cache:
        return _conventions_cache[pid]
    company = load_manifest(pid).get('company')
    if not company:
        _conventions_cache[pid] = None
        return None
    conv = CompanyConventions(company, HUB, skills_dir=SKILLS_DIR)
    if not conv.exists():
        _conventions_cache[pid] = None
        return None
    conv.load(); conv.parse()
    _conventions_cache[pid] = conv
    return conv


def expects_controller(tag: str, conv) -> bool:
    """True unless the conventions explicitly mark the prefix as
    measurement-only / no-controller (HT, JE, JT, RT, ...)."""
    if not conv or not tag:
        return True
    cat = conv.get_instrument_category(tag)
    if cat is None:
        return True
    return cat.get('expects_controller', True)


def list_projects() -> list:
    if not PROJECTS_DIR.exists():
        return []
    projects = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = load_manifest(d.name)
        espx = load_espx(d.name)
        studio = espx.get('studio', {})
        n_instr = len(studio.get('instruments', {}))
        n_equip = len(studio.get('equipment', {}))
        projects.append({
            'id':          d.name,
            'name':        manifest.get('name', d.name),
            'instruments': n_instr,
            'equipment':   n_equip,
            'nodes':       len(espx.get('nodes', [])),
            'drawings':    len(set(
                n.get('drawing', '')
                for n in espx.get('nodes', [])
                if n.get('drawing')
            ))
        })
    return projects


DB_PATH = HUB / 'studio.db'


def _db_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f'studio.db not found at {DB_PATH}')
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def _get_api_key() -> str | None:
    # Reads the same `settings` table in studio.db the desktop app's Settings
    # screen writes to — no env var fallback (frontend-configured only).
    from adapters.config import load_config
    return load_config().get('anthropic_api_key') or None


_INSTR_KINDS_SQL = (
    "'transmitter','controller','indicator','recorder',"
    "'switch','analyzer','element','instrument','alarm'"
)


_INSTR_KINDS_PY = frozenset(
    ('transmitter','controller','indicator','recorder',
     'switch','analyzer','element','instrument','alarm')
)


def _sync_project_internal(pid: str) -> dict:
    """Read nodes/edges from DB, rebuild .espx, return counts."""
    conn = _db_conn()
    try:
        node_rows = conn.execute(
            """SELECT id, label, kind, kind_detail, area, x, y,
                      COALESCE(json_extract(extra_json,'$.drawing'),       '') AS drawing,
                      COALESCE(json_extract(extra_json,'$.equipment_ref'), '') AS equipment_ref,
                      COALESCE(json_extract(extra_json,'$.confidence'),  NULL) AS confidence
               FROM nodes WHERE pid=? ORDER BY id""",
            (pid,)
        ).fetchall()

        nodes, instruments, equipment = [], {}, {}
        drawings: set = set()

        for r in node_rows:
            drw  = r['drawing'] or ''
            tag  = r['label'] or ''
            kind = (r['kind'] or '').lower()
            node = {
                'id':      r['id'],
                'label':   tag,
                'kind':    r['kind'] or '',
                'area':    r['area'] or '',
                'drawing': drw,
                'x':       r['x'] or 0,
                'y':       r['y'] or 0,
            }
            nodes.append(node)
            if drw:
                drawings.add(drw)
            if not tag or tag.lower().startswith('off_page'):
                continue
            if kind in _INSTR_KINDS_PY:
                instruments[tag] = {
                    'type':          r['kind_detail'] or r['kind'] or '',
                    'equipment_ref': r['equipment_ref'] or '',
                    'drawing':       drw,
                    'confidence':    r['confidence'],
                }
            else:
                equipment[tag] = {
                    'kind':    r['kind'] or '',
                    'area':    r['area'] or '',
                    'drawing': drw,
                }

        edge_rows = conn.execute(
            """SELECT e.from_id, e.to_id, e.kind
               FROM edges e WHERE e.pid=? LIMIT 5000""",
            (pid,)
        ).fetchall()
        edges = [{'from': r['from_id'], 'to': r['to_id'], 'kind': r['kind'] or 'stream'}
                 for r in edge_rows]

        espx = {
            'nodes': nodes,
            'edges': edges,
            'studio': {
                'instruments': instruments,
                'equipment':   equipment,
                'loops':       {},
                'connections': [],
            }
        }
        espx_path = PROJECTS_DIR / pid / f'{pid}.espx'
        espx_path.parent.mkdir(parents=True, exist_ok=True)
        espx_path.write_text(
            yaml.dump(espx, default_flow_style=False, allow_unicode=True),
            encoding='utf-8'
        )
        return {
            'synced':      True,
            'nodes':       len(nodes),
            'edges':       len(edges),
            'drawings':    len(drawings),
            'instruments': len(instruments),
            'equipment':   len(equipment),
        }
    finally:
        conn.close()
