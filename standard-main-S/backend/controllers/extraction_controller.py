"""
controllers/extraction_controller.py — text/image/notes extraction upload endpoints

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

from flask_compat import jsonify, request
import base64
import datetime

def parse_text_route(pid):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    build_internal = _m.build_internal
    claude_extract_text = _m.claude_extract_text
    generate_mermaid_python = _m.generate_mermaid_python
    load_espx = _m.load_espx
    ympl_render = _m.ympl_render
    text = request.json.get('text', '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    # Tier 1: ympl.js
    tier1 = ympl_render(text)
    ympl_doc = tier1.get('doc') or {
        'schema_version': 'ympl-1.0', 'id': pid, 'title': pid,
        'nodes': [], 'edges': [], 'meta': {'confidence': 'none'}
    }
    warnings = tier1.get('warnings', [])
    used_claude = False
    claude_data = {}

    # Tier 2: Claude if ympl.js struggled
    confidence = ympl_doc.get('meta', {}).get('confidence', 'none')
    if warnings or confidence not in ('high', 'medium') or not ympl_doc.get('nodes'):
        claude_data = claude_extract_text(text)
        used_claude = True
        # Use Claude topology if it found more nodes
        if claude_data.get('nodes') and \
           len(claude_data['nodes']) >= len(ympl_doc.get('nodes', [])):
            ympl_doc['nodes'] = claude_data['nodes']
            ympl_doc['edges'] = claude_data.get('edges', [])
            ympl_doc['meta']['confidence'] = 'high'

    # Always generate Mermaid via ympl.js
    mermaid = generate_mermaid_python(ympl_doc)
    ympl_doc['meta']['mermaid'] = mermaid

    # Build internal model
    internal = build_internal(ympl_doc, claude_data)

    # Save to project
    espx, espx_path = load_espx(pid)
    espx['nodes'] = ympl_doc['nodes']
    espx['edges'] = ympl_doc['edges']
    espx['meta'] = ympl_doc['meta']
    espx['studio']['instruments'].update(internal.get('instruments', {}))
    espx['studio']['equipment'].update(internal.get('equipment', {}))
    espx['studio']['connections'] = internal.get('connections', [])
    espx['studio']['loops'] = internal.get('loops', {})
    _db_persist_espx(pid, espx)

    return jsonify({
        'ympl_doc': ympl_doc,
        'mermaid': mermaid,
        'instruments': internal.get('instruments', {}),
        'equipment': internal.get('equipment', {}),
        'connections': internal.get('connections', []),
        'loops': internal.get('loops', {}),
        'warnings': warnings,
        'used_claude': used_claude
    })


def parse_image_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _append_usage = _m._append_usage
    _cache_key = _m._cache_key
    _db = _m._db
    _db_persist_espx = _m._db_persist_espx
    _get_conventions = _m._get_conventions
    _run_cv_detection = _m._run_cv_detection
    build_internal = _m.build_internal
    cache_store = _m.cache_store
    claude_extract_image = _m.claude_extract_image
    file_hash = _m.file_hash
    generate_mermaid_python = _m.generate_mermaid_python
    load_espx = _m.load_espx
    load_manifest = _m.load_manifest
    save_espx = _m.save_espx
    update_manifest_after_extract = _m.update_manifest_after_extract
    import re as _re
    print(f'parse_image_route: pid={pid} file={request.files.get("file")}')
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    try:
        f = request.files['file']
        image_bytes = f.read()
        media_type = f.content_type or 'image/png'
        filename   = f.filename or 'source.pdf'
        print(f'File read: {len(image_bytes)} bytes, type={media_type}, name={filename}')

        safe_filename = _re.sub(r'[^\w\-_. ]', '_', filename).strip() or 'source.pdf'

        source_dir = PROJECTS_DIR / pid / 'source_docs'
        # parents=True so first-upload of a new project creates the project
        # dir + source_docs/ + cache/ chain, instead of WinError 3 on Windows
        # when only PROJECTS_DIR exists.
        source_dir.mkdir(parents=True, exist_ok=True)
        (PROJECTS_DIR / pid / 'cache').mkdir(parents=True, exist_ok=True)
        (source_dir / safe_filename).write_bytes(image_bytes)
        print(f'Saved to source_docs: {safe_filename}')

        fhash = file_hash(image_bytes)
        print(f'File hash: {fhash}')

        # ── CV detection pipeline (YOLO → OCR+UNet in parallel) ──────────────
        # Runs regardless of LLM cache state — detection outputs are separate
        # artefacts (bounding boxes, line segments, OCR text) stored in cache/.
        # For PDFs, render first page to PNG for CV models.
        detection_dir = str(PROJECTS_DIR / pid / 'cache')
        base_name = _re.sub(r'\.[^.]+$', '', safe_filename)  # strip extension
        is_pdf = 'pdf' in media_type.lower() or safe_filename.lower().endswith('.pdf')

        if is_pdf:
            # Render first page to PNG for CV detection
            try:
                import fitz as _fitz
                _doc  = _fitz.open(stream=image_bytes, filetype='pdf')
                _pix  = _doc[0].get_pixmap(matrix=_fitz.Matrix(2.0, 2.0), alpha=False)
                _png  = _pix.tobytes('png')
                _doc.close()
                cv_image_bytes = _png
            except Exception as _fe:
                print(f'[detection] PDF→PNG render failed: {_fe} — skipping CV detection')
                cv_image_bytes = None
        else:
            cv_image_bytes = image_bytes

        if cv_image_bytes:
            detection_result = _run_cv_detection(
                cv_image_bytes, base_name, detection_dir,
                diagram_type='pid',
            )
        else:
            detection_result = {'available': False, 'symbols': [], 'texts': [], 'lines': []}

        # ── Per-source hash check — same file already extracted → merge from cache ──
        manifest = load_manifest(pid)
        already_done = any(s.get('hash') == fhash for s in manifest.get('sources', []))
        if already_done:
            print(f'Source already extracted: {fhash} — merging from cache')
            combined = cache_store.get(pid, _cache_key(fhash, 0))
            if combined:
                espx, espx_path = load_espx(pid)
                if espx is None:
                    espx = {
                        'nodes': [], 'edges': [],
                        'meta': {'mermaid': ''},
                        'studio': {
                            'metadata': {'plant_name': pid, 'process_type': 'generic'},
                            'instruments': {}, 'equipment': {},
                            'connections': [], 'screens': [], 'review': {}
                        }
                    }
                existing_drawings = {
                    n.get('drawing', '') for n in espx.get('nodes', [])
                    if n.get('drawing')
                }
                new_nodes_raw = [
                    n for n in combined.get('nodes', [])
                    if n.get('drawing', '') not in existing_drawings
                ]
                if new_nodes_raw:
                    existing_ids = {n['id'] for n in espx['nodes']}
                    max_n = max(
                        (int(nid[1:]) for nid in existing_ids
                         if nid.startswith('n') and nid[1:].isdigit()),
                        default=0
                    )
                    counter = max_n + 1
                    new_nodes = []
                    for node in new_nodes_raw:
                        old_id = node['id']
                        new_id = old_id if old_id not in existing_ids else f'n{counter}'
                        if new_id != old_id:
                            counter += 1
                        n_copy = dict(node)
                        n_copy['id'] = new_id
                        new_nodes.append(n_copy)
                        existing_ids.add(new_id)
                    espx['nodes'].extend(new_nodes)
                    studio = espx.setdefault('studio', {})
                    existing_instr = studio.setdefault('instruments', {})
                    existing_equip = studio.setdefault('equipment', {})
                    for tag, data in combined.get('instruments', {}).items():
                        if tag not in existing_instr:
                            existing_instr[tag] = data
                    for tag, data in combined.get('equipment', {}).items():
                        if tag not in existing_equip:
                            existing_equip[tag] = data
                    _db_persist_espx(pid, espx)
                    save_espx(pid, espx)
                    print(f'Cache hit merge: {len(new_nodes)} nodes added from {fhash}')
                else:
                    print(f'Cache hit: drawings already in espx, skipping merge')
                studio = espx.get('studio', {})
                return jsonify({
                    'ympl_doc': {'nodes': espx.get('nodes', []),
                                 'edges': espx.get('edges', [])},
                    'mermaid':     espx.get('meta', {}).get('mermaid', ''),
                    'instruments': studio.get('instruments', {}),
                    'equipment':   studio.get('equipment', {}),
                    'connections': studio.get('connections', []),
                    'warnings':    ['Source already extracted — merged from cache.'],
                    'used_claude': False,
                    'cached':      True,
                    'detection':   {
                        'available':    detection_result.get('available', False),
                        'symbol_count': len(detection_result.get('symbols', [])),
                        'text_count':   len(detection_result.get('texts', [])),
                        'line_count':   len(detection_result.get('lines', [])),
                        'symbol_image': detection_result.get('symbol_image', ''),
                        'line_image':   detection_result.get('line_image', ''),
                    },
                })
            # No pass0 cache on disk — fall through to re-extract
            print(f'Cache entry missing for {fhash} — re-extracting')

        print(f'Starting Claude extraction: hash={fhash}')
        conv = _get_conventions(pid)
        conv_text = conv.as_skill_text() if conv else ''
        claude_data = claude_extract_image(image_bytes, media_type, pid=pid,
                                           conventions_text=conv_text)

        if claude_data.get('error'):
            print(f'Claude error: {claude_data["error"]}')
            return jsonify({'error': claude_data['error']}), 500

        espx, espx_path = load_espx(pid)
        if espx is None:
            espx = {
                'nodes': [], 'edges': [],
                'meta': {'mermaid': ''},
                'studio': {
                    'metadata': {'plant_name': pid, 'process_type': 'generic'},
                    'instruments': {}, 'equipment': {},
                    'connections': [], 'screens': [], 'review': {}
                }
            }

        # ── Determine drawings already captured ────────────────────────────────
        existing_drawings = {
            n.get('drawing', '') for n in espx.get('nodes', [])
            if n.get('drawing')
        }

        # ── Filter to nodes from new drawings only ──────────────────────────────
        new_nodes_raw = [
            n for n in claude_data.get('nodes', [])
            if n.get('drawing', '') not in existing_drawings
        ]

        # ── Rebase node IDs to avoid collision with existing espx nodes ─────────
        existing_ids = {n['id'] for n in espx['nodes']}
        max_n = max(
            (int(nid[1:]) for nid in existing_ids
             if nid.startswith('n') and nid[1:].isdigit()),
            default=0
        )
        id_remap: dict = {}
        counter = max_n + 1
        new_nodes: list = []
        for node in new_nodes_raw:
            old_id = node['id']
            if old_id in existing_ids or old_id in id_remap.values():
                new_id = f'n{counter}'
                counter += 1
            else:
                new_id = old_id
            id_remap[old_id] = new_id
            n_copy = dict(node)
            n_copy['id'] = new_id
            new_nodes.append(n_copy)

        new_node_ids = {n['id'] for n in new_nodes}

        # ── Filter edges to those between new nodes only ────────────────────────
        new_edges: list = []
        for e in claude_data.get('edges', []):
            new_from = id_remap.get(e.get('from', ''), e.get('from', ''))
            new_to   = id_remap.get(e.get('to',   ''), e.get('to',   ''))
            if new_from in new_node_ids and new_to in new_node_ids:
                e_copy = dict(e)
                e_copy['from'] = new_from
                e_copy['to']   = new_to
                new_edges.append(e_copy)

        new_drawings = sorted({n.get('drawing', '') for n in new_nodes if n.get('drawing')})
        print(f'Additive merge: {len(new_nodes)} new nodes, {len(new_edges)} new edges, '
              f'{len(new_drawings)} new drawings')

        if not new_nodes:
            print('No new drawings — all already in espx')
            studio = espx.get('studio', {})
            update_manifest_after_extract(
                pid, safe_filename, fhash,
                len(espx['nodes']), len(studio.get('instruments', {})),
                len(studio.get('equipment', {})), len(espx['edges']),
                drawings=[]
            )
            return jsonify({
                'ympl_doc': {'nodes': espx['nodes'], 'edges': espx['edges']},
                'mermaid':     espx.get('meta', {}).get('mermaid', ''),
                'instruments': studio.get('instruments', {}),
                'equipment':   studio.get('equipment', {}),
                'connections': studio.get('connections', []),
                'warnings':    ['All drawings already extracted — no new data added.'],
                'used_claude': True,
                'cached':      False,
                'detection':   {
                    'available':    detection_result.get('available', False),
                    'symbol_count': len(detection_result.get('symbols', [])),
                    'text_count':   len(detection_result.get('texts', [])),
                    'line_count':   len(detection_result.get('lines', [])),
                    'symbol_image': detection_result.get('symbol_image', ''),
                    'line_image':   detection_result.get('line_image', ''),
                },
            })

        # ── Build internal model for new nodes only ─────────────────────────────
        new_ympl_doc = {
            'schema_version': 'ympl-1.0',
            'id': pid,
            'title': pid.replace('_', ' ').title(),
            'nodes': new_nodes,
            'edges': new_edges,
            'meta': {'confidence': 'high', 'source': 'claude_vision'}
        }
        internal = build_internal(new_ympl_doc, claude_data)

        # ── Additive merge into espx ────────────────────────────────────────────
        studio = espx.setdefault('studio', {
            'metadata':    {'plant_name': pid, 'process_type': 'generic'},
            'instruments': {}, 'equipment': {},
            'connections': [], 'screens': [], 'review': {}, 'loops': {}
        })
        existing_instr = studio.setdefault('instruments', {})
        existing_equip = studio.setdefault('equipment', {})
        existing_conns = studio.setdefault('connections', [])

        espx['nodes'].extend(new_nodes)
        espx['edges'].extend(new_edges)

        for tag, data in internal.get('instruments', {}).items():
            if tag not in existing_instr:
                existing_instr[tag] = data

        for tag, data in internal.get('equipment', {}).items():
            if tag not in existing_equip:
                existing_equip[tag] = data

        existing_conn_ids = {c.get('id') for c in existing_conns}
        for conn in internal.get('connections', []):
            if conn.get('id') not in existing_conn_ids:
                existing_conns.append(conn)
                existing_conn_ids.add(conn.get('id'))

        studio.setdefault('loops', {}).update(internal.get('loops', {}))

        # Regenerate mermaid from merged topology
        mermaid = generate_mermaid_python({'nodes': espx['nodes'], 'edges': espx['edges']})
        espx.setdefault('meta', {})['mermaid'] = mermaid
        espx['meta']['confidence'] = 'high'

        # Reconcile review: keep decisions for tags still present
        all_tags = set(existing_instr) | set(existing_equip)
        studio['review'] = {tag: dec for tag, dec in studio.get('review', {}).items()
                            if tag in all_tags}

        _db_persist_espx(pid, espx)
        save_espx(pid, espx)
        # Reconcile the `review` table: drop rows for tags that no longer
        # exist after this extraction. Preserve `_tag_rejected:*` /
        # `_conn_rejected:*` keys so the engineer's rejection ledger
        # survives a re-extraction (Pass 3/4 rebuild reads them).
        try:
            _conn_rev = _db.get_db()
            for _row in _conn_rev.execute(
                'SELECT key FROM review WHERE pid = ?', (pid,)
            ).fetchall():
                _k = _row['key']
                if _k.startswith('_'):
                    continue
                if _k not in all_tags:
                    _conn_rev.execute(
                        'DELETE FROM review WHERE pid = ? AND key = ?',
                        (pid, _k))
        except Exception as _e:
            print(f'review reconcile failed for {pid}: {_e}')

        update_manifest_after_extract(
            pid, safe_filename, fhash,
            len(espx['nodes']), len(existing_instr),
            len(existing_equip), len(espx['edges']),
            drawings=new_drawings
        )

        # Log usage record
        try:
            from adapters.config import load_config as _lc
            _cfg = _lc()
            _append_usage({
                'timestamp':  datetime.datetime.utcnow().isoformat(),
                'pid':        pid,
                'provider':   _cfg.get('llm_provider', 'anthropic'),
                'model':      _cfg.get('anthropic_model_smart') or _cfg.get('gemini_model_smart') or _cfg.get('openai_model_smart') or '',
                'tokens_in':  claude_data.get('_tokens_in', 0),
                'tokens_out': claude_data.get('_tokens_out', 0),
                'cost_usd':   claude_data.get('_cost_usd', 0.0),
                'nodes':      len(espx['nodes']),
                'filename':   safe_filename,
            })
        except Exception:
            pass

        return jsonify({
            'ympl_doc':    {'nodes': espx['nodes'], 'edges': espx['edges']},
            'mermaid':     mermaid,
            'instruments': existing_instr,
            'equipment':   existing_equip,
            'connections': existing_conns,
            'warnings':    [],
            'used_claude': True,
            'cached':      False,
            'detection':   {
                'available':     detection_result.get('available', False),
                'symbol_count':  len(detection_result.get('symbols', [])),
                'text_count':    len(detection_result.get('texts', [])),
                'line_count':    len(detection_result.get('lines', [])),
                'symbol_image':  detection_result.get('symbol_image', ''),
                'line_image':    detection_result.get('line_image', ''),
            },
        })

    except Exception as e:
        import traceback
        print(f'PARSE ERROR: {e}')
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def parse_notes_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db_persist_espx = _m._db_persist_espx
    cache_store = _m.cache_store
    extract_json = _m.extract_json
    extract_pdf_page = _m.extract_pdf_page
    file_hash = _m.file_hash
    llm = _m.llm
    load_espx = _m.load_espx
    load_manifest = _m.load_manifest
    save_manifest = _m.save_manifest
    """
    Extract legend, notes, and tag list from a notes/legend page of the source PDF.
    Body: {"page": 1, "filename": "source.pdf"}
    Cached per source-file hash × page number.
    """
    data     = request.json or {}
    page_num = int(data.get('page', 1))
    filename = data.get('filename', '')

    source_path = PROJECTS_DIR / pid / 'source_docs' / filename
    if not source_path.exists():
        return jsonify({'error': f'Source file not found: {filename}'}), 404

    pdf_bytes  = source_path.read_bytes()
    fhash      = file_hash(pdf_bytes)
    cache_key  = f'{fhash}_notes_p{page_num}'

    notes_ck = f'{cache_key}_pass4'
    cached = cache_store.get(pid, notes_ck)
    if cached:
        return jsonify({**cached, 'cached': True})

    try:
        page_bytes = extract_pdf_page(pdf_bytes, page_num)
    except Exception as e:
        return jsonify({'error': f'Page extraction failed: {e}'}), 500

    b64 = base64.standard_b64encode(page_bytes).decode()

    notes_prompt = (
        'This is a P&ID notes or legend page. Extract all structured information.\n'
        'Return ONLY JSON — no markdown:\n'
        '{\n'
        '  "tags": [{"tag": "FT-101", "description": "Feed flow transmitter", "service": ""}],\n'
        '  "legend": [{"symbol": "dashed line", "meaning": "signal wire"}],\n'
        '  "notes": ["Design pressure: 150 psig"],\n'
        '  "abbreviations": {"CW": "cooling water"},\n'
        '  "drawings_referenced": ["157-2-130"]\n'
        '}'
    )

    try:
        notes_resp = llm.complete_with_image(
            notes_prompt, b64, 'application/pdf', max_tokens=4000, tier='fast',
        )
        notes_data = extract_json(notes_resp.text)
    except Exception as e:
        return jsonify({'error': f'Notes extraction failed: {e}'}), 500

    cache_store.put(pid, notes_ck, notes_data, notes_resp,
                    file_hash=fhash, filename=filename, pass_num=4)

    # Store in espx.meta.legend
    try:
        espx, espx_path = load_espx(pid)
        legends = espx.setdefault('meta', {}).setdefault('legend', [])
        legends = [l for l in legends
                   if not (l.get('page') == page_num and l.get('filename') == filename)]
        legends.append({'page': page_num, 'filename': filename, **notes_data})
        espx['meta']['legend'] = legends
        _db_persist_espx(pid, espx)
    except Exception as ex:
        print(f'Warning: could not save legend to espx: {ex}')

    # Store summary in project.json
    try:
        manifest = load_manifest(pid)
        manifest.setdefault('metadata', {})['legend'] = {
            'page': page_num, 'filename': filename,
            'tags_found': len(notes_data.get('tags', [])),
            'extracted': datetime.datetime.now().isoformat(timespec='seconds')
        }
        save_manifest(pid, manifest)
    except Exception as ex:
        print(f'Warning: could not save legend to manifest: {ex}')

    return jsonify({**notes_data, 'cached': False})
