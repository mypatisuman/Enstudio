"""
controllers/project_controller.py — project CRUD, canvas, units, company, conventions endpoints

Extracted from main.py (Phase 8): request parsing, validation, service/repo
calls, and jsonify()/response construction for these routes -- moved
verbatim into per-function controller bodies. Flask route decorators,
function signatures, and endpoint names all remain in main.py unchanged;
each route body is now a one-line delegate to the matching function here.

Main.py-level names used by these bodies (module-level singletons like
PROJECTS_DIR/HUB/cache_store/llm/skill_registry, and the thin repository/
service wrapper functions established in Phases 2-7) are pulled in via a
function-local `import main as _m` -- mirroring the pre-existing lazy-import
pattern already used elsewhere in this codebase (api/detect.py, extract_cli.py)
to reach main.py without a module-level circular import (main.py imports
this controller module at startup).
"""
from __future__ import annotations

from flask_compat import jsonify, render_template, request, send_from_directory, g
import base64
import datetime
import json
import re

def list_projects():
    import main as _m
    _db_list_projects = _m._db_list_projects
    """Fast project list — DB-backed."""
    try:
        from flask_compat import g
        return jsonify(_db_list_projects(g.user['id']))
    except Exception as e:
        print(f'list_projects DB read failed: {e}')
        return jsonify([])


def create_project():
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db = _m._db
    _db_persist_espx = _m._db_persist_espx
    from security import safe_project_dir
    data = request.get_json(silent=True) or {}
    plant_name = (data.get('plant_name') or '').strip()
    if not plant_name:
        return jsonify({'error': 'plant_name is required'}), 400
    # The old slug only replaced spaces and hyphens, so a plant_name of
    # '../../evil' produced pid '../../evil' and mkdir'd outside the hub.
    # Strip every character that is not slug-safe, then validate.
    pid = re.sub(r'[^A-Za-z0-9_.\-]', '_', plant_name.lower().replace(' ', '_').replace('-', '_'))
    pid = pid.lstrip('.-_') or 'project'
    pdir = safe_project_dir(PROJECTS_DIR, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / 'source_docs').mkdir(exist_ok=True)
    (pdir / 'exports').mkdir(exist_ok=True)

    today = datetime.date.today().isoformat()
    espx = {
        'schema_version': 'ympl-1.0',
        'id': pid,
        'title': data['plant_name'],
        'nodes': [],
        'edges': [],
        'meta': {'confidence': 'none', 'mermaid': ''},
        'studio': {
            'metadata': {
                'plant_name': data['plant_name'],
                'process_type': data.get('process_type', 'generic'),
                'revision': 1,
                'date': today,
                'changelog': [
                    {'rev': 1, 'date': today, 'by': 'Engineer', 'change': 'Project created'}
                ]
            },
            'instruments': {},
            'equipment': {},
            'connections': [],
            'loops': {},
            'screens': [],
            'review': {}
        }
    }
    _db_persist_espx(pid, espx)
    
    from flask_compat import g
    if hasattr(g, 'user'):
        _db.get_db().execute('UPDATE projects SET user_id = ? WHERE id = ?', (g.user['id'], pid))
        
    return jsonify({'id': pid, 'name': data['plant_name']})


def get_project(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db_get_project = _m._db_get_project
    _db_persist_espx = _m._db_persist_espx
    cache_espx_stats = _m.cache_espx_stats
    rebuild_espx_from_cache = _m.rebuild_espx_from_cache
    try:
        espx = _db_get_project(pid)
        if espx is None:
            return jsonify({'error': f'Project {pid} not found'}), 404
        n_instr = len(espx.get('studio', {}).get('instruments', {}) or {})
        cache_dir = PROJECTS_DIR / pid / 'cache'
        pass0_count = len(list(cache_dir.glob('*_pass0.json'))) if cache_dir.exists() else 0
        if n_instr == 0 and pass0_count > 0:
            print(f'Auto-rebuild: {pid} has {pass0_count} cache files but 0 instruments')
            espx_built = rebuild_espx_from_cache(pid)
            # DB is the system of record now — no .espx write here.
            cache_espx_stats(pid, espx_built)
            _db_persist_espx(pid, espx_built)
            espx = _db_get_project(pid) or espx_built
        return jsonify(espx)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def delete_project(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    import shutil
    from security import safe_project_dir
    # safe_project_dir validates the id AND containment-checks the resolved
    # path. Without it this rmtree took whatever the URL supplied: 'pid=..'
    # resolved to the hub root and 'pid=C:/Windows' left the hub entirely,
    # because Path.join discards the left side on an absolute component.
    pdir = safe_project_dir(PROJECTS_DIR, pid)
    if not pdir.exists():
        return jsonify({'error': 'Project not found'}), 404
    if not pdir.is_dir():
        return jsonify({'error': 'Project path is not a directory'}), 400
    shutil.rmtree(pdir)
    print(f'Deleted project: {pid}')
    return jsonify({'deleted': pid})


def canvas_page(pid):
    from flask_compat import render_template
    return render_template('canvas.html', pid=pid)


def get_canvas(pid):
    import main as _m
    _db_get_canvas = _m._db_get_canvas
    """Return saved canvas positions, DB-backed."""
    return jsonify(_db_get_canvas(pid))


def save_canvas(pid):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    _db_write_canvas_positions = _m._db_write_canvas_positions
    load_espx = _m.load_espx
    """Save canvas positions, verifications, node edits, and engineer-drawn edges.
    DB-only — canvas.json is no longer written."""
    data = request.json
    canvas = data.get('canvas', {})
    nodes  = data.get('nodes', None)
    edges  = data.get('edges', None)

    _db_write_canvas_positions(pid, canvas)

    if nodes is not None or edges is not None:
        espx, _ = load_espx(pid)
        if nodes is not None:
            espx['nodes'] = nodes
        if edges is not None:
            espx['edges'] = edges
        _db_persist_espx(pid, espx)

    return jsonify({'saved': len(canvas)})


def serve_source(pid, filename):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    """Serve source PDF/image for the canvas PDF viewer."""
    from flask_compat import send_from_directory
    from security import safe_project_dir, InvalidPid
    # send_from_directory already blocks traversal in `filename`; the added
    # value here is validating `pid`, which it never saw.
    source_dir = safe_project_dir(PROJECTS_DIR, pid) / 'source_docs'
    try:
        from security import safe_child
        safe_child(source_dir, filename)
    except InvalidPid as e:
        return jsonify({'error': str(e)}), 400
    return send_from_directory(str(source_dir), filename)


def delete_source_route(pid, filename):
    import main as _m
    CONNECTOR_KINDS = _m.CONNECTOR_KINDS
    INSTRUMENT_KINDS = _m.INSTRUMENT_KINDS
    MECHANICAL_KINDS = _m.MECHANICAL_KINDS
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db_persist_espx = _m._db_persist_espx
    generate_mermaid_python = _m.generate_mermaid_python
    load_espx = _m.load_espx
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    """Remove a source file and all nodes/instruments extracted from its drawings."""
    import urllib.parse
    filename = urllib.parse.unquote(filename)

    try:
        manifest = load_manifest(pid)
        source = next((s for s in manifest.get('sources', []) if s.get('filename') == filename), None)
        if not source:
            return jsonify({'error': f'Source not found: {filename}'}), 404

        source_hash     = source.get('hash', '')
        source_drawings = set(source.get('drawings', []))

        espx, espx_path = load_espx(pid)
        all_nodes = espx.get('nodes', [])

        # Identify removed nodes by drawing membership
        removed = [n for n in all_nodes if n.get('drawing', '') in source_drawings]
        removed_ids    = {n['id']    for n in removed}
        removed_instr  = {n['label'] for n in removed if n.get('kind') in INSTRUMENT_KINDS}
        removed_equip  = {n['label'] for n in removed
                          if n.get('kind') not in INSTRUMENT_KINDS | MECHANICAL_KINDS | CONNECTOR_KINDS}

        espx['nodes'] = [n for n in all_nodes if n['id'] not in removed_ids]
        espx['edges'] = [e for e in espx.get('edges', [])
                         if e.get('from') not in removed_ids and e.get('to') not in removed_ids]

        studio = espx.get('studio', {})
        studio['instruments'] = {t: d for t, d in studio.get('instruments', {}).items()
                                  if t not in removed_instr}
        studio['equipment']   = {t: d for t, d in studio.get('equipment', {}).items()
                                  if t not in removed_equip}

        remaining_labels = {n['label'] for n in espx['nodes']}
        studio['connections'] = [
            c for c in studio.get('connections', [])
            if c.get('from_tag') in remaining_labels and c.get('to_tag') in remaining_labels
        ]
        studio['review'] = {t: d for t, d in studio.get('review', {}).items()
                             if t not in removed_instr and t not in removed_equip}

        # Regenerate mermaid from remaining topology
        espx.setdefault('meta', {})['mermaid'] = generate_mermaid_python(
            {'nodes': espx['nodes'], 'edges': espx['edges']}
        )

        _db_persist_espx(pid, espx)

        # Delete cache files for this source hash
        from security import safe_project_dir, safe_child
        proj_dir = safe_project_dir(PROJECTS_DIR, pid)
        cache_dir = proj_dir / 'cache'
        deleted_cache = 0
        if cache_dir.exists() and source_hash:
            for cf in list(cache_dir.iterdir()):
                if cf.is_file() and source_hash in cf.name:
                    cf.unlink()
                    deleted_cache += 1

        # Remove source file from disk. `filename` is url-unquoted above and
        # only cross-checked against the manifest, so it is validated as a
        # plain, non-traversing filename before it reaches unlink().
        src_file = safe_child(proj_dir / 'source_docs', filename)
        if src_file.is_file():
            src_file.unlink()

        # Update manifest
        manifest['sources'] = [s for s in manifest.get('sources', [])
                                if s.get('filename') != filename]
        save_manifest(pid, manifest)

        n_removed_nodes = len(removed)
        n_removed_instr = len(removed_instr)
        print(f'Removed source {filename}: {n_removed_nodes} nodes, '
              f'{n_removed_instr} instruments, {deleted_cache} cache files')

        return jsonify({
            'removed_nodes':       n_removed_nodes,
            'removed_instruments': n_removed_instr,
            'removed_cache_files': deleted_cache,
        })

    except Exception as e:
        import traceback
        print(f'DELETE SOURCE ERROR: {e}')
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def rebuild_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db_persist_espx = _m._db_persist_espx
    cache_espx_stats = _m.cache_espx_stats
    rebuild_espx_from_cache = _m.rebuild_espx_from_cache
    try:
        espx = rebuild_espx_from_cache(pid)
        espx_path = PROJECTS_DIR / pid / f'{pid}.espx'
        _db_persist_espx(pid, espx)
        cache_espx_stats(pid, espx)
        n_instr = len(espx['studio']['instruments'])
        n_equip = len(espx['studio']['equipment'])
        n_nodes = len(espx['nodes'])
        return jsonify({
            'nodes': n_nodes,
            'instruments': n_instr,
            'equipment': n_equip,
            'message': f'Rebuilt: {n_nodes} nodes, {n_instr} instruments, {n_equip} equipment'
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def link_drawings_route(pid):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    link_cross_source = _m.link_cross_source
    load_espx = _m.load_espx
    try:
        espx, espx_path = load_espx(pid)
        result = link_cross_source(espx)
        _db_persist_espx(pid, espx)
        return jsonify(result)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def infer_loops_route(pid):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    infer_loops = _m.infer_loops
    load_espx = _m.load_espx
    try:
        espx, espx_path = load_espx(pid)
        if espx is None:
            return jsonify({'error': 'project not found'}), 404

        loops = infer_loops(espx)

        # Task 4: annotate each instrument with its loop_id
        instruments = espx.get('studio', {}).get('instruments', {})
        for loop_id, loop in loops.items():
            for role in ('controller', 'measurement', 'final_element'):
                tag = loop.get(role)
                if tag and tag in instruments:
                    instruments[tag]['loop_id'] = loop_id
            for tag in loop.get('indicators', []):
                if tag in instruments:
                    instruments[tag]['loop_id'] = loop_id
            for tag in loop.get('alarms', []):
                if tag in instruments:
                    instruments[tag]['loop_id'] = loop_id

        espx.setdefault('studio', {})['loops'] = loops
        _db_persist_espx(pid, espx)

        counts = {'complete': 0, 'incomplete': 0,
                  'controller_only': 0, 'no_controller': 0}
        for loop in loops.values():
            s = loop.get('status', 'incomplete')
            counts[s] = counts.get(s, 0) + 1

        return jsonify({
            'total':         len(loops),
            'complete':      counts['complete'],
            'incomplete':    counts['incomplete'] + counts.get('controller_only', 0),
            'no_controller': counts['no_controller'],
            'loops':         loops,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def get_loops_route(pid):
    import main as _m
    load_espx = _m.load_espx
    try:
        espx, _ = load_espx(pid)
        if espx is None:
            return jsonify({'error': 'project not found'}), 404
        return jsonify(espx.get('studio', {}).get('loops', {}))
    except Exception as e:
        print(f'get_loops error: {e}')
        return jsonify({'error': str(e)}), 500


def update_loop_route(pid, loop_id):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    load_espx = _m.load_espx
    try:
        espx, espx_path = load_espx(pid)
        if espx is None:
            return jsonify({'error': 'project not found'}), 404

        loops = espx.setdefault('studio', {}).setdefault('loops', {})
        if loop_id not in loops:
            return jsonify({'error': 'loop not found'}), 404

        body = request.get_json() or {}
        loop = loops[loop_id]
        for field in ('confirmed', 'loop_type', 'measurement',
                      'final_element', 'setpoint', 'setpoint_units', 'sil_level'):
            if field in body:
                loop[field] = body[field]

        _db_persist_espx(pid, espx)
        return jsonify(loop)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def get_units(pid):
    import main as _m
    load_manifest = _m.load_manifest
    try:
        return jsonify(load_manifest(pid).get('units', []))
    except Exception as e:
        print(f'get_units error: {e}')
        return jsonify({'error': str(e)}), 500


def create_unit(pid):
    import main as _m
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    try:
        body = request.get_json() or {}
        manifest = load_manifest(pid)
        units = manifest.setdefault('units', [])
        import time as _time
        unit = {
            'id':       'u' + str(int(_time.time())),
            'name':     body.get('name', 'Unit'),
            'drawings': body.get('drawings', []),
            'color':    body.get('color', '#4a8fd4'),
        }
        units.append(unit)
        save_manifest(pid, manifest)
        return jsonify(unit)
    except Exception as e:
        print(f'create_unit error: {e}')
        return jsonify({'error': str(e)}), 500


def update_unit(pid, uid):
    import main as _m
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    try:
        body = request.get_json() or {}
        manifest = load_manifest(pid)
        unit = next((u for u in manifest.get('units', []) if u['id'] == uid), None)
        if unit is None:
            return jsonify({'error': 'unit not found'}), 404
        for field in ('name', 'drawings', 'color'):
            if field in body:
                unit[field] = body[field]
        save_manifest(pid, manifest)
        return jsonify(unit)
    except Exception as e:
        print(f'update_unit error: {e}')
        return jsonify({'error': str(e)}), 500


def delete_unit(pid, uid):
    import main as _m
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    try:
        manifest = load_manifest(pid)
        manifest['units'] = [u for u in manifest.get('units', []) if u['id'] != uid]
        save_manifest(pid, manifest)
        return jsonify({'deleted': uid})
    except Exception as e:
        print(f'delete_unit error: {e}')
        return jsonify({'error': str(e)}), 500


def get_manifest(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    load_manifest = _m.load_manifest
    try:
        m = load_manifest(pid)
        # Auto-correct source filenames that don't match disk (sanitizer mismatch)
        source_dir = PROJECTS_DIR / pid / 'source_docs'
        for source in m.get('sources', []):
            stored = source.get('filename', '')
            if stored and not (source_dir / stored).exists():
                files = [f.name for f in source_dir.iterdir() if f.is_file()] if source_dir.exists() else []
                if files:
                    source['filename'] = files[0]
        return jsonify(m)
    except Exception:
        return jsonify({'id': pid, 'sources': [], 'exports': [], 'extraction': {}})


def cache_stats_route(pid):
    import main as _m
    _db_get_cache_manifest = _m._db_get_cache_manifest
    """Return extraction cost manifest for this project. DB-backed
    (falls back to the file-based manifest while the cache_manifest
    table is still being populated by new extractions)."""
    return jsonify(_db_get_cache_manifest(pid))


def list_companies():
    import main as _m
    HUB = _m.HUB
    """List all company names that have a conventions.md file."""
    companies_dir = HUB / 'companies'
    if not companies_dir.exists():
        return jsonify([])
    names = sorted(
        d.name for d in companies_dir.iterdir()
        if d.is_dir() and (d / 'conventions.md').exists()
    )
    return jsonify(names)


def get_company(pid):
    import main as _m
    HUB = _m.HUB
    load_manifest = _m.load_manifest
    """Return current company name and conventions content for a project."""
    from adapters.company import CompanyConventions
    m = load_manifest(pid)
    company = m.get('company')
    if not company:
        return jsonify({'name': None, 'content': ''})
    conv = CompanyConventions(company, HUB)
    content = conv.load() if conv.exists() else ''
    return jsonify({'name': company, 'content': content})


def set_company(pid):
    import main as _m
    HUB = _m.HUB
    STUDIO_DIR = _m.STUDIO_DIR
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    """Link a company to a project; create conventions.md from template if new."""
    from adapters.company import CompanyConventions
    body = request.get_json(force=True, silent=True) or {}
    company = (body.get('name') or '').strip()
    if not company:
        return jsonify({'error': 'name required'}), 400
    conv = CompanyConventions(company, HUB)
    if not conv.exists():
        template_path = STUDIO_DIR / 'skills' / 'company' / 'template.md'
        if template_path.exists():
            content = conv.create_from_template(template_path)
        else:
            content = f'# {company} — P&ID Conventions\n'
            conv.save(content)
    else:
        content = conv.load()
    m = load_manifest(pid)
    m['company'] = company
    save_manifest(pid, m)
    return jsonify({'name': company, 'content': content})


def update_company(pid):
    import main as _m
    HUB = _m.HUB
    load_manifest = _m.load_manifest
    """Save edited conventions.md content for the project's company."""
    from adapters.company import CompanyConventions
    body = request.get_json(force=True, silent=True) or {}
    content = body.get('content', '')
    m = load_manifest(pid)
    company = m.get('company')
    if not company:
        return jsonify({'error': 'no company set for this project'}), 400
    CompanyConventions(company, HUB).save(content)
    return jsonify({'ok': True})


def discover_conventions(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    extract_json = _m.extract_json
    file_hash = _m.file_hash
    llm = _m.llm
    """
    Render first page of uploaded (or existing) PDF as PNG and ask Claude to
    identify every tag prefix — company name, drawing format, prefix table.

    Accepts: multipart/form-data with 'file' field  (new upload)
             OR no file  (re-discover from existing source_docs)
    Returns: {company, drawing_format, prefixes:[...], tag_numbering, cached}
    """
    import fitz  # PyMuPDF

    # ── Get PDF bytes ─────────────────────────────────────────────────────────
    if 'file' in request.files:
        f = request.files['file']
        pdf_bytes = f.read()
        media_type = f.content_type or 'application/pdf'
    else:
        source_dir = PROJECTS_DIR / pid / 'source_docs'
        pdfs = sorted(p for p in (source_dir.iterdir() if source_dir.exists() else [])
                      if p.suffix.lower() == '.pdf')
        if not pdfs:
            return jsonify({'error': 'No PDF found. Upload a file first.'}), 400
        pdf_bytes = pdfs[0].read_bytes()
        media_type = 'application/pdf'

    # ── Cache check ───────────────────────────────────────────────────────────
    fhash = file_hash(pdf_bytes)
    cache_dir = PROJECTS_DIR / pid / 'cache'
    cache_dir.mkdir(exist_ok=True)
    cache_key = f'{fhash}_discovery.json'
    cache_file = cache_dir / cache_key
    if cache_file.exists():
        try:
            result = json.loads(cache_file.read_text(encoding='utf-8'))
            result['cached'] = True
            return jsonify(result)
        except Exception:
            pass

    # ── Render first page as PNG ──────────────────────────────────────────────
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        page = doc[0]
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png_bytes = pix.tobytes('png')
        doc.close()
    except Exception as e:
        return jsonify({'error': f'PDF render failed: {e}'}), 500

    image_b64 = base64.b64encode(png_bytes).decode()

    # ── Discovery prompt ──────────────────────────────────────────────────────
    prompt = """Scan this P&ID drawing. Do NOT extract equipment yet.
Instead, identify every UNIQUE tag prefix visible
(the letters before the dash and number).

For each prefix, report:
- prefix: the letter code (e.g., HE, QC, ADV)
- count: how many times it appears
- context: what it appears near or connected to
- suggested_type: your best guess (equipment type, valve type, instrument type)
- suggested_layer: 1 (process), 2 (control), 3 (mechanical), 4 (safety)
- confidence: high / medium / low

Also identify:
- Drawing number format (e.g., 157-2-xxx)
- Company name (from title block)
- Tag numbering pattern (what first digit means)

Return ONLY JSON:
{
  "company": "AIR COMPANY",
  "drawing_format": "157-2-XXX",
  "prefixes": [
    {"prefix": "HE", "count": 9, "context": "inline between vessels",
     "suggested_type": "heat_exchanger", "suggested_layer": 1,
     "confidence": "high"},
    ...
  ],
  "tag_numbering": {
    "first_digit": "area number",
    "example": "V-401 = area 4, sequence 01"
  }
}"""

    try:
        resp = llm.complete_with_image(prompt, image_b64, 'image/png',
                                        max_tokens=4000, tier='smart')
        result = extract_json(resp.text)
    except Exception as e:
        return jsonify({'error': f'Claude call failed: {e}'}), 500

    if not isinstance(result, dict) or 'prefixes' not in result:
        return jsonify({'error': 'Unexpected response format', 'raw': str(result)[:500]}), 500

    result['cached'] = False
    cache_file.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return jsonify(result)


def save_discovered_conventions(pid):
    import main as _m
    HUB = _m.HUB
    _build_conventions_md = _m._build_conventions_md
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    """
    Save the user-confirmed prefix table as conventions.md and link to project.
    Body: {company, prefixes, drawing_format, tag_numbering}
    Returns: {ok, company, content}
    """
    from adapters.company import CompanyConventions
    body = request.get_json(force=True, silent=True) or {}
    company  = (body.get('company') or '').strip()
    prefixes = body.get('prefixes') or []
    drawing_format = body.get('drawing_format') or ''
    tag_numbering  = body.get('tag_numbering') or {}

    if not company:
        return jsonify({'error': 'company name required'}), 400

    content = _build_conventions_md(company, prefixes, drawing_format, tag_numbering)
    conv = CompanyConventions(company, HUB)
    conv.save(content)
    m = load_manifest(pid)
    m['company'] = company
    save_manifest(pid, m)
    return jsonify({'ok': True, 'company': company, 'content': content})


def get_unknown_prefixes(pid):
    import main as _m
    _get_conventions = _m._get_conventions
    load_espx = _m.load_espx
    """
    After extraction: compare all tag prefixes in espx.nodes against
    the project's conventions file. Return prefixes not covered.
    """
    from adapters.engine import _extract_prefix, _check_tag_quality
    espx, _ = load_espx(pid)
    if espx is None:
        return jsonify({'unknown': []})
    conv = _get_conventions(pid)
    known_prefixes: set = set()
    if conv:
        maps = conv.client_maps()
        known_prefixes = (set(maps.get('valve_layers', {}).keys()) |
                          set(maps.get('equipment_kinds', {}).keys()))

    prefix_counts: dict = {}
    for n in espx.get('nodes', []):
        tag = n.get('label', '')
        if not tag or _check_tag_quality(tag) != 'ok':
            continue
        pfx = _extract_prefix(tag)
        if pfx and pfx not in known_prefixes:
            prefix_counts[pfx] = prefix_counts.get(pfx, 0) + 1

    unknown = [{'prefix': k, 'count': v}
               for k, v in sorted(prefix_counts.items(), key=lambda x: -x[1])]
    return jsonify({'unknown': unknown})


def reset_extraction(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db = _m._db
    _db_persist_espx = _m._db_persist_espx
    load_espx = _m.load_espx
    """
    Unlock extraction: clears pass0/pass1 cache and canvas positions.
    Preserves pass2 batch caches and review decisions (reconciled on next scan).
    """
    try:
        espx, espx_path = load_espx(pid)
        if espx.get('studio', {}).get('metadata'):
            espx['studio']['metadata']['extraction_locked'] = False
        _db_persist_espx(pid, espx)

        # Delete pass0 (combined) and pass1 (topology) caches — keep pass2 batches
        cache_dir = PROJECTS_DIR / pid / 'cache'
        deleted = 0
        if cache_dir.exists():
            for f in cache_dir.iterdir():
                if '_pass0.json' in f.name or '_pass1.json' in f.name:
                    f.unlink()
                    deleted += 1
        print(f'Reset extraction {pid}: cleared {deleted} cache files')

        # Clear canvas positions — new extraction will have different x,y
        try:
            _db.get_db().execute(
                'DELETE FROM canvas_positions WHERE pid = ?', (pid,))
            print(f'Reset extraction {pid}: cleared canvas_positions rows')
        except Exception as _e:
            print(f'Reset extraction {pid}: canvas_positions clear failed: {_e}')

        return jsonify({'reset': True, 'pid': pid, 'cache_cleared': deleted})
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
