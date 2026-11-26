"""
EngineeringStudio — Flask server
Repository: github.com/jeyreddy/standard
Read CLAUDE.md and RULES.md before modifying this file.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from flask_compat import (
    FastAPICompat, request, jsonify, render_template, send_from_directory,
    Response, send_file,
)
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import io
import yaml
import json
import base64
import subprocess
import threading
import datetime

from adapters.cache_store import CacheStore
from adapters.llm_factory import get_provider
from adapters.skill_registry import SkillRegistry
from utils.paths import resolve_hub, resolve_projects_dir
from utils.json_utils import extract_json_object

from controllers import (
    health_controller, settings_controller, review_controller,
    export_controller, extraction_controller, editor_controller,
    project_controller,
)

# ── Detection services — resolved through services/detection_router.py ──────
# ONE switch for the whole app (STUDIO_DETECTION_ENGINE env var, or the
# `detection_engine` settings key: llm | cv | auto). This file used to prefer
# the vision-LLM services while api/detect.py and extraction_cli/image.py
# hardwired the CV ones, so the same drawing produced different results
# depending on which entry point you came through.
#
# Resolution is LAZY (first call, not import time) on purpose: resolve_backend()
# consults the configured LLM provider, which reads the settings table — and at
# module-import time adapters.db has not been pointed at the hub yet (that
# happens further down this file). Binding at import would read the wrong DB.
try:
    import services.detection_router as _detection_router
    _DETECTION_AVAILABLE = True
    _det_err = None
except ImportError as _det_err:          # pragma: no cover - import guard
    _detection_router = None
    _DETECTION_AVAILABLE = False
    print(f'[detection] router not importable: {_det_err}')

_detection_backend = None


def _detection():
    """Resolve (once) and cache the active detection backend."""
    global _detection_backend
    if _detection_backend is None:
        if _detection_router is None:
            raise RuntimeError('services.detection_router is not importable')
        _detection_backend = _detection_router.resolve_backend()
    return _detection_backend


def process_detect_symbols(*args, **kwargs):
    return _detection().detect_symbols(*args, **kwargs)


def detect_text_from_bytes(*args, **kwargs):
    return _detection().detect_text(*args, **kwargs)


def detect_lines_from_bytes(*args, **kwargs):
    return _detection().detect_lines(*args, **kwargs)


def _noop_init(*_args, **_kwargs):
    """Warm-up no-op.

    A vision LLM has no trained model to warm, so these three names now do
    nothing at all. They still EXIST because bootstrap/cv_bootstrap.py looks
    them up by name, and because an earlier build left them undefined on the
    LLM import branch — which made `_init_cv_models()` raise
    `AttributeError: module 'main' has no attribute 'initialize_yolo_model'`
    and crash the Flask server at boot.

    They deliberately no longer import services.detection_service /
    text_detection_service / line_detection_service: calling those would load
    YOLOv8, RapidOCR and U-Net, and detection in this application is pure LLM
    with no trained model anywhere in the loop.
    """
    return None


# Trained-model warm-up hooks, retained as no-ops. See _noop_init above.
initialize_yolo_model = _noop_init
initialize_ocr = _noop_init
initialize_unet_model = _noop_init

load_dotenv()
STUDIO_DIR = Path(__file__).parent
REPO_ROOT = STUDIO_DIR.parent
_mongo_env = REPO_ROOT / 'mongo.env'
if _mongo_env.exists():
    load_dotenv(_mongo_env)

# Windows: ProactorEventLoop (default since Py 3.8) breaks httpx async.
# Force SelectorEventLoop so asyncio.run() + to_thread() work correctly.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# LLM provider — swap via LLM_PROVIDER env var (anthropic | ollama)
# tier='smart' → Sonnet/llama3.1:70b   tier='fast' → Haiku/llama3.2
# Canonical SDK directory under sdk/ympl-sdk, fallback to local
YMPL_SDK_DIR = REPO_ROOT / 'sdk' / 'ympl-sdk'
if not YMPL_SDK_DIR.exists():
    YMPL_SDK_DIR = STUDIO_DIR / 'ympl-sdk'
YMPL_JS = YMPL_SDK_DIR / 'ympl.js'

app = FastAPICompat(
    title="EngineeringStudio API",
    description="EngineeringStudio backend API - 100% FastAPI ASGI server",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Enable CORS for Tauri desktop webview and local canvas frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for web UI assets
_templates_static = STUDIO_DIR / 'templates'
if _templates_static.exists():
    app.mount("/static", StaticFiles(directory=str(_templates_static)), name="static")

llm = get_provider()

# Hub location — EngineeringHub/EngineeringHub/ relative to the repo root
# Override with ENGINEERING_HUB env var or .env file for custom location
_default_hub = STUDIO_DIR.parent / 'EngineeringHub' / 'EngineeringHub'
HUB = resolve_hub(default=_default_hub)
PROJECTS_DIR = resolve_projects_dir(HUB)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
cache_store = CacheStore(HUB)
skill_registry = SkillRegistry(STUDIO_DIR / 'skills')

# ── SQLite persistence — dual-write alongside the existing flat-file store ──
from adapters import db as _db
_db.reset_for_path(HUB / 'studio.db')
_db.init_db()

# ── Authentication (isolated blueprint — see auth.py) ────────────────────────
from auth import auth_bp, require_auth, decode_token  # noqa: E402
app.register_blueprint(auth_bp)         # (require_auth re-exported for routes)

# ── Agentic Describe Blueprint (F2 pre-authorized) ───────────────────────────
try:
    from agents.describe.api import describe_agent_bp
    app.register_blueprint(describe_agent_bp)
except ImportError as _desc_err:
    print(f'[describe agent] blueprint not registered: {_desc_err}')

# ── Detection Pipeline Router (native FastAPI router) ────────────────────────
try:
    from api.detect import router as detect_router
    app.include_router(detect_router)
except Exception as _det_router_err:
    print(f'[detect router] router not registered: {_det_router_err}')

# Default-deny guard: every /api/* route except the auth blueprint now needs a
# valid Bearer token.
from security import (  # noqa: E402
    install_api_auth_guard, install_pid_validator, validate_pid, InvalidPid,
)
install_pid_validator(app)
install_api_auth_guard(app, decode_token, _db.get_db)


@app.errorhandler(InvalidPid)
def _handle_invalid_pid(err):
    """A rejected project id is a client error, not a 500 traceback."""
    return jsonify({'error': str(err)}), 400

# ── DB read helpers (Part A) ─────────────────────────────────────────────────
# Each helper returns the same shape the file-based code returned, so the
# call sites only swap a single function call.

from repositories.project_repository import (
    _db_list_projects, _db_get_project,
    _row_to_node, _row_to_edge, _row_to_instrument, _row_to_equipment, _row_to_connection,
    _db_get_review, _db_write_review,
    _extras_json, _to_real,
    _NODE_DB_NATIVE, _EDGE_DB_NATIVE, _INSTR_DB_NATIVE, _EQUIP_DB_NATIVE, _CONN_DB_NATIVE,
    _db_persist_espx,
)
from repositories.canvas_repository import _db_get_canvas, _db_write_canvas_positions


def _db_get_cache_manifest(pid: str) -> dict:
    """CacheStore is DB-native now; just delegate."""
    return cache_store.get_manifest(pid)



from domain.kind_mapping import (
    INSTRUMENT_KINDS, PROCESS_KINDS, MECHANICAL_KINDS, CONNECTOR_KINDS,
    PALETTE_TO_CANONICAL, CANONICAL_TO_PALETTE, CANONICAL_INSTR_KINDS,
    normalize_kind,
)


# ── ympl.js bridge ────────────────────────────────────────────────────────────

def ympl_render(text: str) -> dict:
    """Call ympl.js Tier 1 parser via Node.js. Returns {doc, mermaid, warnings}."""
    if not YMPL_JS.exists():
        return {'doc': None, 'mermaid': '', 'warnings': ['ympl.js not found']}

    # Write script to temp file to avoid Windows quoting issues
    import tempfile
    script = (
        f"const YMPL = require({json.dumps(str(YMPL_JS).replace(chr(92), '/'))});\n"
        f"const r = YMPL.render({json.dumps(text)});\n"
        "process.stdout.write(JSON.stringify({"
        "doc: r.doc, mermaid: r.mermaid || '', warnings: r.warnings || []"
        "}));"
    )
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js',
                                         delete=False, encoding='utf-8') as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        result = subprocess.run(
            ['node', tmp_path],
            capture_output=True, text=True, timeout=15
        )
        Path(tmp_path).unlink(missing_ok=True)

        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        return {'doc': None, 'mermaid': '', 'warnings': [result.stderr[:300]]}
    except Exception as e:
        return {'doc': None, 'mermaid': '', 'warnings': [str(e)]}


from domain.mermaid import generate_mermaid_python


def ympl_to_mermaid(ympl_doc: dict) -> str:
    """Generate Mermaid string from YMPL doc via ympl.js."""
    if not YMPL_JS.exists():
        return ''

    import tempfile
    ympl_path = str(YMPL_JS).replace('\\', '/')
    script = (
        f"const YMPL = require({json.dumps(ympl_path)});\n"
        f"const doc = {json.dumps(ympl_doc)};\n"
        "process.stdout.write(YMPL.toMermaid(doc));"
    )
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js',
                                         delete=False, encoding='utf-8') as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        result = subprocess.run(
            ['node', tmp_path],
            capture_output=True, text=True, timeout=10
        )
        Path(tmp_path).unlink(missing_ok=True)
        return result.stdout.strip()
    except:
        return ''


# ── Company conventions ───────────────────────────────────────────────────────

from services import convention_service as _convention_service


def _get_conventions(pid: str):
    """Return a loaded+parsed CompanyConventions for the project, or None."""
    return _convention_service._get_conventions(pid, HUB, PROJECTS_DIR)


# ── Layout rules ──────────────────────────────────────────────────────────────

def _load_layout_rules(company: str | None = None) -> dict:
    """Delegates to SkillRegistry — registry.yaml is the source of truth."""
    return _convention_service._load_layout_rules(skill_registry, company)


def _apply_convention_overrides(rules: dict, pid: str) -> dict:
    """Merge company-specific rendering preferences on top of skill-file defaults."""
    return _convention_service._apply_convention_overrides(rules, pid, HUB, PROJECTS_DIR)


@app.route('/api/layout-rules')
def get_layout_rules():
    return settings_controller.get_layout_rules()


# ── Skill loading / Claude API calls ─────────────────────────────────────────

from services import extraction_service as _extraction_service


def load_skills(drawing_type: str = 'p_and_id') -> str:
    """Load all skill markdown files for a drawing type (cached at startup)."""
    return _extraction_service.load_skills(drawing_type, STUDIO_DIR)


def claude_extract_text(text: str) -> dict:
    """Claude API for complex text that ympl.js Tier 1 could not handle."""
    return _extraction_service.claude_extract_text(text, llm, STUDIO_DIR)


from repositories import manifest_repository as _manifest_repo


def manifest_path(pid: str) -> Path:
    return _manifest_repo.manifest_path(pid, PROJECTS_DIR)


def load_manifest(pid: str) -> dict:
    return _manifest_repo.load_manifest(pid, PROJECTS_DIR)


def save_manifest(pid: str, manifest: dict):
    _manifest_repo.save_manifest(pid, manifest, PROJECTS_DIR)


from services import manifest_service as _manifest_service


def cache_espx_stats(pid: str, espx: dict):
    """Write instrument/equipment/node counts to manifest.stats for fast list reads."""
    _manifest_service.cache_espx_stats(pid, espx, PROJECTS_DIR)


def update_manifest_after_extract(pid: str, filename: str, fhash: str,
                                   n_nodes: int, n_instruments: int,
                                   n_equipment: int, n_edges: int,
                                   drawings: list = None):
    _manifest_service.update_manifest_after_extract(
        pid, filename, fhash, n_nodes, n_instruments, n_equipment, n_edges,
        PROJECTS_DIR, drawings=drawings,
    )


def update_manifest_after_export(pid: str, export_type: str, filename: str):
    _manifest_service.update_manifest_after_export(pid, export_type, filename, PROJECTS_DIR)


from services.extraction_service import file_hash, _cache_key


# ── Parallel Pass 2 + 2.5 (async) ────────────────────────────────────────────

from services.extraction_service import claude_extract_image as _svc_claude_extract_image


def claude_extract_image(image_bytes: bytes, media_type: str = 'image/png',
                         pid: str = None, conventions_text: str = '') -> dict:
    """
    Multi-pass extraction with caching.
    Pass 1 (Sonnet, streaming): topology + positions.
    Pass 2 + 2.5 (Haiku, parallel async): instrument params + pipe runs.
    Same file hash = instant return from combined cache.
    """
    return _svc_claude_extract_image(
        image_bytes, media_type, pid, conventions_text,
        llm=llm, cache_store=cache_store, studio_dir=STUDIO_DIR,
    )



# ── Internal model builder ────────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """Robustly extract JSON from Claude response. Handles fences and truncation."""
    result = extract_json_object(raw)
    if result is not None:
        return result
    print(f'JSON extraction failed')
    return {'nodes': [], 'edges': [], 'instruments': {}, 'equipment': {}, 'connections': []}


from services.extraction_service import build_internal, extract_pdf_page


# ── Project file helpers ──────────────────────────────────────────────────────

from repositories import canvas_repository as _canvas_repo


def load_espx(pid: str):
    """DB-backed espx load. Returns (espx_dict_or_None, dummy_path).

    The second tuple element is preserved for signature compatibility with
    legacy callers — the path is no longer written to. If the DB has no
    record of `pid`, returns ({}, dummy_path) so callers that mutate the
    dict before persisting still work.
    """
    return _canvas_repo.load_espx(pid, PROJECTS_DIR)


def save_espx(pid: str, espx: dict) -> None:
    """Write the espx dict to EngineeringHub/projects/<pid>/<pid>.espx YAML.

    The DB is the system of record (see _db_persist_espx), but the mcpserver
    package reads the YAML file directly. Call save_espx alongside _db_persist_espx on
    extraction completion so both stay in lockstep — otherwise MCP queries
    against newly-extracted projects return zero results.
    """
    _canvas_repo.save_espx(pid, espx, PROJECTS_DIR)


def _load_canvas_positions(pid: str, espx: dict = None) -> dict | None:
    """Return {node_id: (x, y)} from the DB.

    If no canvas_positions rows exist for `pid` yet, auto-seed from the
    normalised x/y on `espx` nodes and persist them so subsequent reads are
    cheap. canvas.json is no longer touched."""
    return _canvas_repo._load_canvas_positions(pid, espx)


# ── Cache-based espx rebuilder ────────────────────────────────────────────────

from services import cache_service as _cache_service


def rebuild_espx_from_cache(pid: str) -> dict:
    """Rebuild espx from scratch using all pass0 cache files."""
    return _cache_service.rebuild_espx_from_cache(pid, PROJECTS_DIR)



# ── Cross-source drawing linker ───────────────────────────────────────────────

from domain.drawing_linker import extract_drawing_number, _merge_connectors


def link_cross_source(espx: dict) -> dict:
    nodes = espx.get('nodes', [])
    edges = espx.get('edges', [])

    drawing_nodes = {}
    for n in nodes:
        if n.get('kind') == 'off_page_connector':
            continue
        d = n.get('drawing', '')
        if d:
            drawing_nodes.setdefault(d, []).append(n['id'])

    # Tally parseable vs unparseable connector references
    parseable = 0
    unparseable = 0
    for node in nodes:
        if node.get('kind') != 'off_page_connector':
            continue
        dest = extract_drawing_number(node.get('label', ''))
        if dest and dest in drawing_nodes:
            parseable += 1
        else:
            unparseable += 1

    print(f'Cross-drawing linking:')
    print(f'  Known drawings: {len(drawing_nodes)}')
    print(f'  Off-page connectors: {parseable + unparseable}')
    print(f'  Parseable refs: {parseable}')
    print(f'  Unparseable refs: {unparseable}')
    if unparseable > 0:
        print(f'  NOTE: off-page connectors use sequence numbers, not drawing numbers. Manual linking required.')

    existing = {(e['from'], e['to']) for e in edges}
    new_edges = []

    for node in nodes:
        if node.get('kind') != 'off_page_connector':
            continue
        label = node.get('label', '')

        dest_drawing = extract_drawing_number(label)
        if not dest_drawing:
            continue
        if dest_drawing not in drawing_nodes:
            continue

        src_drawing = node.get('drawing', '')
        dest_connector = next((
            n for n in nodes
            if n.get('kind') == 'off_page_connector'
            and n.get('drawing') == dest_drawing
            and src_drawing
            and src_drawing in n.get('label', '')
        ), None)

        dest_id = (dest_connector['id'] if dest_connector
                   else drawing_nodes[dest_drawing][0])

        pair = (node['id'], dest_id)
        if pair in existing:
            continue

        new_edges.append({
            'from':  node['id'],
            'to':    dest_id,
            'kind':  'inter_drawing',
            'label': f'{src_drawing}->{dest_drawing}'
        })
        existing.add(pair)
        print(f'Linked: {label} -> {dest_drawing}')

    espx['edges'].extend(new_edges)
    n_linked = len(new_edges)

    if n_linked > 0:
        message = f'{n_linked} cross-drawing connections made'
    elif unparseable > 0:
        message = (f'0 connections made — off-page connectors do not contain drawing numbers. '
                   f'{unparseable} connector(s) need manual linking.')
    else:
        message = '0 connections made — no matching drawing references found.'

    return {'linked': n_linked, 'parseable': parseable, 'unparseable': unparseable, 'message': message}


from domain.loop_inference import infer_loops


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return health_controller.index()


@app.route('/ympl.js')
def serve_ympl_js():
    return health_controller.serve_ympl_js()


@app.route('/api/projects')
@require_auth
def list_projects():
    return project_controller.list_projects()


@app.route('/api/projects', methods=['POST'])
@require_auth
def create_project():
    return project_controller.create_project()


@app.route('/api/projects/<pid>')
def get_project(pid):
    return project_controller.get_project(pid)


@app.route('/api/projects/<pid>/parse/text', methods=['POST'])
def parse_text_route(pid):
    return extraction_controller.parse_text_route(pid)


@app.route('/api/projects/<pid>/parse/image', methods=['POST'])
def parse_image_route(pid):
    return extraction_controller.parse_image_route(pid)


@app.route('/api/projects/<pid>', methods=['DELETE'])
def delete_project(pid):
    return project_controller.delete_project(pid)


@app.route('/api/projects/<pid>/review', methods=['GET'])
def get_review(pid):
    return review_controller.get_review(pid)


@app.route('/api/projects/<pid>/review/<tag>', methods=['POST'])
def update_review(pid, tag):
    return review_controller.update_review(pid, tag)


# ── Pass 3 / Pass 4 proposal review routes ──────────────────────────────────
# These expose `_tag_proposal` and `_connection_proposals` that
# rebuild_espx_from_cache attached during inference. The frontend renders
# them in the Review tab; accept writes the change into the espx, reject
# discards it. All four routes leave the canonical review-state machine
# (accepted/rejected/signoff/pending) untouched.
#
# Rejection persistence: rejected proposals are recorded under prefixed keys
# in the project's existing review state — `_tag_rejected:<node_id>` and
# `_conn_rejected:<node_id>`. rebuild_espx_from_cache consults these keys
# before re-attaching any proposal, so a rejection survives a full rebuild.

from services.review_service import _record_proposal_rejection

@app.route('/api/projects/<pid>/proposals/tags', methods=['GET'])
def get_tag_proposals(pid):
    return review_controller.get_tag_proposals(pid)


@app.route('/api/projects/<pid>/proposals/tags/<node_id>', methods=['POST'])
def update_tag_proposal(pid, node_id):
    return review_controller.update_tag_proposal(pid, node_id)


@app.route('/api/projects/<pid>/proposals/connections', methods=['GET'])
def get_connection_proposals(pid):
    return review_controller.get_connection_proposals(pid)


@app.route('/api/projects/<pid>/proposals/connections/<node_id>', methods=['POST'])
def update_connection_proposal(pid, node_id):
    return review_controller.update_connection_proposal(pid, node_id)


@app.route('/api/projects/<pid>/export/vids')
def export_vids_route(pid):
    return export_controller.export_vids_route(pid)


@app.route('/api/projects/<pid>/export/ympl')
def export_ympl_route(pid):
    return export_controller.export_ympl_route(pid)


@app.route('/api/projects/<pid>/export/connectivity')
def export_connectivity_route(pid):
    return export_controller.export_connectivity_route(pid)


@app.route('/api/projects/<pid>/export/svg')
def export_svg_route(pid):
    return export_controller.export_svg_route(pid)


from helpers.svg_helper import _svg_for_drawing


@app.route('/api/projects/<pid>/export/svg/<drawing>')
def export_svg_drawing_route(pid, drawing):
    return export_controller.export_svg_drawing_route(pid, drawing)


@app.route('/api/projects/<pid>/export/dxf')
def export_dxf_route(pid):
    return export_controller.export_dxf_route(pid)


@app.route('/api/projects/<pid>/export/markdown')
def export_markdown_route(pid):
    return export_controller.export_markdown_route(pid)


@app.route('/api/projects/<pid>/parse/notes', methods=['POST'])
def parse_notes_route(pid):
    return extraction_controller.parse_notes_route(pid)


@app.route('/api/projects/<pid>/reset-extraction', methods=['POST'])
def reset_extraction(pid):
    return project_controller.reset_extraction(pid)


@app.route('/editor')
def editor_page():
    return editor_controller.editor_page()


@app.route('/api/editor/<pid>', methods=['GET'])
def get_editor_state(pid):
    return editor_controller.get_editor_state(pid)


@app.route('/api/editor/<pid>/stream-graph')
def editor_stream_graph(pid):
    return editor_controller.editor_stream_graph(pid)


@app.route('/api/editor/<pid>/verify')
def editor_verify(pid):
    return editor_controller.editor_verify(pid)


@app.route('/api/editor/<pid>/background')
def get_editor_background(pid):
    return editor_controller.get_editor_background(pid)


@app.route('/api/editor/<pid>/autoconnect', methods=['POST'])
def editor_autoconnect(pid):
    return editor_controller.editor_autoconnect(pid)


@app.route('/api/editor/<pid>/arrange-process', methods=['POST'])
def editor_arrange_process(pid):
    return editor_controller.editor_arrange_process(pid)


from helpers.editor_helper import _editor_arrange_process_inner


@app.route('/api/editor/<pid>', methods=['POST'])
def save_editor_state(pid):
    return editor_controller.save_editor_state(pid)


@app.route('/api/editor/<pid>/describe', methods=['POST'])
def describe_to_canvas(pid):
    return editor_controller.describe_to_canvas(pid)



@app.route('/canvas/<pid>')
def canvas_page(pid):
    return project_controller.canvas_page(pid)


@app.route('/api/projects/<pid>/canvas', methods=['GET'])
def get_canvas(pid):
    return project_controller.get_canvas(pid)


@app.route('/api/projects/<pid>/canvas', methods=['POST'])
def save_canvas(pid):
    return project_controller.save_canvas(pid)


@app.route('/api/projects/<pid>/source/<filename>')
def serve_source(pid, filename):
    return project_controller.serve_source(pid, filename)


@app.route('/api/projects/<pid>/source/<filename>', methods=['DELETE'])
def delete_source_route(pid, filename):
    return project_controller.delete_source_route(pid, filename)


@app.route('/api/projects/<pid>/rebuild', methods=['POST'])
def rebuild_route(pid):
    return project_controller.rebuild_route(pid)


@app.route('/api/projects/<pid>/link', methods=['POST'])
def link_drawings_route(pid):
    return project_controller.link_drawings_route(pid)


@app.route('/api/projects/<pid>/infer_loops', methods=['POST'])
def infer_loops_route(pid):
    return project_controller.infer_loops_route(pid)


@app.route('/api/projects/<pid>/loops', methods=['GET'])
def get_loops_route(pid):
    return project_controller.get_loops_route(pid)


@app.route('/api/projects/<pid>/loops/<path:loop_id>', methods=['PUT'])
def update_loop_route(pid, loop_id):
    return project_controller.update_loop_route(pid, loop_id)


@app.route('/api/projects/<pid>/units', methods=['GET'])
def get_units(pid):
    return project_controller.get_units(pid)


@app.route('/api/projects/<pid>/units', methods=['POST'])
def create_unit(pid):
    return project_controller.create_unit(pid)


@app.route('/api/projects/<pid>/units/<uid>', methods=['PUT'])
def update_unit(pid, uid):
    return project_controller.update_unit(pid, uid)


@app.route('/api/projects/<pid>/units/<uid>', methods=['DELETE'])
def delete_unit(pid, uid):
    return project_controller.delete_unit(pid, uid)


@app.route('/api/projects/<pid>/manifest')
def get_manifest(pid):
    return project_controller.get_manifest(pid)


@app.route('/api/projects/<pid>/cache-stats')
def cache_stats_route(pid):
    return project_controller.cache_stats_route(pid)


@app.route('/api/settings', methods=['GET'])
def get_settings():
    return settings_controller.get_settings()


@app.route('/api/settings', methods=['POST'])
def save_settings():
    return settings_controller.save_settings()


@app.route('/api/settings/test-llm', methods=['POST'])
def test_llm_connection():
    return settings_controller.test_llm_connection()


from helpers import usage_helper as _usage_helper

_USAGE_FILE = HUB / 'usage.json'


def _load_usage() -> list:
    return _usage_helper._load_usage(_USAGE_FILE)


def _append_usage(record: dict) -> None:
    _usage_helper._append_usage(record, _USAGE_FILE)


@app.route('/api/usage', methods=['GET'])
def get_usage():
    return settings_controller.get_usage()


@app.route('/api/usage', methods=['POST'])
def log_usage():
    return settings_controller.log_usage()


@app.route('/api/usage', methods=['DELETE'])
def clear_usage():
    return settings_controller.clear_usage()


@app.route('/api/companies')
def list_companies():
    return project_controller.list_companies()


@app.route('/api/projects/<pid>/company', methods=['GET'])
def get_company(pid):
    return project_controller.get_company(pid)


@app.route('/api/projects/<pid>/company', methods=['POST'])
def set_company(pid):
    return project_controller.set_company(pid)


@app.route('/api/projects/<pid>/company', methods=['PUT'])
def update_company(pid):
    return project_controller.update_company(pid)


@app.route('/api/projects/<pid>/discover-conventions', methods=['POST'])
def discover_conventions(pid):
    return project_controller.discover_conventions(pid)


from helpers.conventions_helper import _build_conventions_md


@app.route('/api/projects/<pid>/save-discovered-conventions', methods=['POST'])
def save_discovered_conventions(pid):
    return project_controller.save_discovered_conventions(pid)


@app.route('/api/projects/<pid>/unknown-prefixes', methods=['GET'])
def get_unknown_prefixes(pid):
    return project_controller.get_unknown_prefixes(pid)


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'EngineeringStudio API', 'version': '2.0.0'})


@app.route('/api/hub')
def hub_info():
    return health_controller.hub_info()


# ── CV detection pipeline helper ─────────────────────────────────────────────

from helpers.cv_detection_helper import _run_cv_detection


# ── Startup ───────────────────────────────────────────────────────────────────

from bootstrap.browser import open_browser
from bootstrap.cv_bootstrap import _init_cv_models


if __name__ == '__main__':
    print('\nEngineeringStudio')
    print(f'Hub:      {HUB}')
    print(f'Projects: {PROJECTS_DIR}')
    print(f'ympl.js:  {YMPL_JS} ({"found" if YMPL_JS.exists() else "NOT FOUND"})')
    from adapters.config import load_config as _load_cfg
    print(f'API key:  {"set" if _load_cfg().get("anthropic_api_key") else "NOT SET — configure it in Settings"}')
    if _detection_router is not None:
        _det = _detection_router.describe_backend()
        if _det['resolved']:
            print(f'Detection: vision-LLM (no ML fallback) — {_det["reason"]}')
        else:
            print('Detection: UNAVAILABLE — ' + str(_det['reason']))
            print('           This application is pure LLM and has no trained-'
                  'model fallback. Point the')
            print('           fast tier at a vision-capable model in Settings '
                  'before extracting.')
    else:
        print('Detection: unavailable (services.detection_router not importable)')
    _init_cv_models()
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', 8000))
    print(f'\nStarting FastAPI server at http://{host}:{port} ...')
    print(f'OpenAPI Swagger documentation available at http://{host}:{port}/docs\n')
    threading.Timer(1.2, open_browser).start()
    import uvicorn
    uvicorn.run(app, host=host, port=port)
