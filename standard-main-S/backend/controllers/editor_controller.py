"""
controllers/editor_controller.py — editor state, autoconnect, arrange, describe endpoints

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

from flask_compat import jsonify, request, send_file
import json

def editor_page():
    import main as _m
    STUDIO_DIR = _m.STUDIO_DIR
    pid = request.args.get('pid', '')
    with open(STUDIO_DIR / 'templates' / 'editor.html', encoding='utf-8') as f:
        html = f.read()
    html = html.replace('const PID = ""', f'const PID = "{pid}"')
    return html


def get_editor_state(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _db_get_canvas = _m._db_get_canvas
    _db_get_project = _m._db_get_project
    _get_conventions = _m._get_conventions
    _merge_connectors = _m._merge_connectors
    load_manifest = _m.load_manifest
    normalize_kind = _m.normalize_kind
    skill_registry = _m.skill_registry
    """Return editor nodes (with pixel positions) and edges. DB-backed."""
    espx = _db_get_project(pid)
    if espx is None:
        return jsonify({'nodes': [], 'edges': []})
    canvas = _db_get_canvas(pid)
    canvas_exists = bool(canvas)
    CANVAS_W, CANVAS_H = 1400, 800
    from adapters.engine import classify_node as _classify_node, derive_bbox as _derive_bbox
    conv = _get_conventions(pid)
    layout_rules = skill_registry.get_layout_rules(load_manifest(pid).get('company'))
    excluded_counts = {'non_physical': 0, 'placeholder': 0}
    nodes = []
    for n in espx.get('nodes', []):
        node = dict(n)
        if n['id'] in canvas:
            node['x'] = canvas[n['id']].get('x', 100)
            node['y'] = canvas[n['id']].get('y', 100)
        elif n.get('x') is not None:
            node['x'] = round(float(n['x']) * CANVAS_W)
            node['y'] = round(float(n['y']) * CANVAS_H)
        else:
            node['x'] = 100
            node['y'] = 100
        node['tag'] = n.get('label', n['id'])
        palette, canonical = normalize_kind(n.get('kind', ''), n.get('kind_detail'))
        node['kind'] = palette           # editor uses palette kind for rendering
        node['kind_canonical'] = canonical  # available for reference; not used by editor JS
        clf = _classify_node(node['tag'], canonical, conventions=conv)
        # Server filter: non-physical (alarms, relays) and placeholder tags stay in
        # VIDS/YMPL exports but are excluded from the editor canvas.
        if not clf.get('physical', True):
            excluded_counts['non_physical'] += 1
            continue
        if clf.get('quality') in ('placeholder', 'incomplete'):
            excluded_counts['placeholder'] += 1
            continue
        node['pid_layer']        = clf['pid_layer']
        node['category']         = clf['category']
        node['measured_variable']= clf['measured_variable']
        node['quality']          = clf['quality']
        node['bbox'] = _derive_bbox(
            {'x': node['x'] / CANVAS_W, 'y': node['y'] / CANVAS_H, 'kind': canonical},
            CANVAS_W, CANVAS_H, layout_rules, dpi=300, company_profile=None,
        )
        nodes.append(node)
    # Collect edges from all three sources, dedup by (from, to) pair.
    # editor_state.edges is the authoritative round-trip store (set by POST).
    # espx['edges'] holds canonical edges from extraction.
    # studio.connections holds pipe-run data with from_tag/to_tag that needs ID resolution.
    # Cache pipes_pass3 files hold the richest pipe metadata.
    seen_pairs: set = set()
    edges: list = []
    edge_ctr = [0]

    def _make_edge(from_id, to_id, conn_type='process', line_id='',
                   fluid='', line_size='', line_class='', insulation='',
                   source=''):
        pair = f'{from_id}|{to_id}'
        rev  = f'{to_id}|{from_id}'
        if not from_id or not to_id or from_id == to_id or pair in seen_pairs or rev in seen_pairs:
            return
        seen_pairs.add(pair)
        seen_pairs.add(rev)
        edge_ctr[0] += 1
        e = {
            'id': f'e{edge_ctr[0]}',
            'from': from_id, 'to': to_id,
            'connType': conn_type,
            'line_id': line_id or '',
            'fluid': fluid or '', 'line_size': line_size or '',
            'line_class': line_class or '', 'insulation': insulation or '',
        }
        if source:
            e['source'] = source
        edges.append(e)

    # Build tag → node-id lookup for sources that reference tags.
    # Two levels: exact match first, then normalised (strip non-alphanumeric, uppercase)
    # so that 'R-101A' in node labels matches 'R101A' in studio.connections.
    import re as _re_es
    def _norm_tag(t): return _re_es.sub(r'[^A-Z0-9]', '', t.upper()) if t else ''
    tag_to_id: dict = {}
    norm_tag_to_id: dict = {}
    for n in espx.get('nodes', []):
        lbl = n.get('label', n['id'])
        tag_to_id[lbl] = n['id']
        nk = _norm_tag(lbl)
        if nk and nk not in norm_tag_to_id:
            norm_tag_to_id[nk] = n['id']

    def _resolve(tag: str) -> str:
        """Return node-id for tag; tries exact match then normalised fallback."""
        if not tag:
            return ''
        hit = tag_to_id.get(tag)
        if hit:
            return hit
        return norm_tag_to_id.get(_norm_tag(tag), '')

    KIND_TO_CONN = {'signal': 'signal', 'bypass': 'process', 'recycle': 'process'}

    # Source 1 — editor_state.edges (full round-trip format, already has node IDs)
    for e in espx.get('editor_state', {}).get('edges', []):
        _make_edge(e.get('from', ''), e.get('to', ''),
                   e.get('connType', 'process'), e.get('line_id', ''),
                   e.get('fluid', ''), e.get('line_size', ''),
                   e.get('line_class', ''), e.get('insulation', ''))

    # Source 2 — espx['edges'] (canonical extraction edges, node IDs)
    for e in espx.get('edges', []):
        _make_edge(e.get('from', ''), e.get('to', ''),
                   KIND_TO_CONN.get(e.get('kind', ''), 'process'),
                   e.get('label', ''))

    # Source 3 — studio.connections (pipe runs with from_tag/to_tag)
    for c in espx.get('studio', {}).get('connections', []):
        fid = _resolve(c.get('from_tag', ''))
        tid = _resolve(c.get('to_tag', ''))
        if fid and tid:
            _make_edge(fid, tid, 'process',
                       c.get('id', ''), c.get('fluid', ''),
                       c.get('line_size', ''), c.get('line_class', ''),
                       c.get('insulation', ''))

    # Source 4 — cache/*_pipes_pass3.json files
    cache_dir = PROJECTS_DIR / pid / 'cache'
    if cache_dir.exists():
        for pipe_file in cache_dir.glob('*_pipes_pass3.json'):
            try:
                pipe_data = json.loads(pipe_file.read_text(encoding='utf-8'))
                for c in pipe_data.get('connections', []):
                    fid = _resolve(c.get('from_tag', ''))
                    tid = _resolve(c.get('to_tag', ''))
                    if fid and tid:
                        _make_edge(fid, tid, 'process',
                                   c.get('id', ''), c.get('fluid', ''),
                                   c.get('line_size', ''), c.get('line_class', ''),
                                   c.get('insulation', ''))
            except Exception:
                pass

    nodes, edges = _merge_connectors(nodes, edges)

    # ── Post-extraction inference pass ────────────────────────────────────────
    # Fills in missing instrument-equipment links, infers Perry's companions,
    # annotates dual-service HX pairs, and adds sequential / cross-area pipes.
    from adapters.engine import infer_connections as _infer
    nodes, inferred_edges = _infer(nodes, edges, conv)
    for ie in inferred_edges:
        _make_edge(ie['from'], ie['to'], ie.get('connType', 'process'),
                   ie.get('label', ''), source='inferred')

    company_conventions = conv.client_maps() if conv else None
    return jsonify({'nodes': nodes, 'edges': edges,
                    'company_conventions': company_conventions,
                    'excluded': excluded_counts,
                    'needs_layout': not canvas_exists})


def editor_stream_graph(pid):
    import main as _m
    _apply_convention_overrides = _m._apply_convention_overrides
    _get_conventions = _m._get_conventions
    _load_layout_rules = _m._load_layout_rules
    load_espx = _m.load_espx
    """Build a stream-based topology layout for the editor canvas.

    Returns:
        {
          streams:   [{id, kind, nodes:[id...], y, label}],
          merges:    [{node_id, inputs:[id...]}],
          splits:    [{node_id, outputs:[id...]}],
          recycles:  [{from, to, label, inferred}],
          positions: {node_id: {x, y}}
        }

    The X positions are in canvas pixel-space; the Y positions are also in
    canvas pixel-space, with the primary process line landing on
    rules.backbone.y. Y offsets above/below are taken from
    pid-development-rules.md Part 5 (streams.parallel_feed_offset, recycle_y,
    vent_y, utility_y, safety_y).
    """
    from adapters.stream_graph import StreamGraph

    espx, _ = load_espx(pid)
    if espx is None:
        return jsonify({'streams': [], 'merges': [], 'splits': [],
                        'recycles': [], 'positions': {}})

    rules = _apply_convention_overrides(_load_layout_rules(), pid)
    conv  = _get_conventions(pid)
    sg = StreamGraph(espx.get('nodes', []), espx.get('edges', []),
                     conventions=conv).build()
    sg.assign_y_levels(rules)
    return jsonify(sg.to_dict(rules))


def editor_verify(pid):
    import main as _m
    _get_conventions = _m._get_conventions
    load_espx = _m.load_espx
    normalize_kind = _m.normalize_kind
    """Verify equipment completeness and sequence per Perry's standards.
    Pure Python computation — no LLM call. Fast enough to call before every layout."""
    from adapters.engine import verify_and_sequence, classify_node as _cn
    espx, _ = load_espx(pid)
    if espx is None:
        return jsonify({'sequences': {}, 'completeness': {}})

    conv = _get_conventions(pid)
    nodes_out = []
    for n in espx.get('nodes', []):
        node = dict(n)
        node['tag'] = n.get('label', n['id'])
        palette, canonical = normalize_kind(n.get('kind', ''), n.get('kind_detail'))
        node['kind'] = palette
        node['kind_canonical'] = canonical
        clf = _cn(node['tag'], canonical, conventions=conv)
        if not clf.get('physical', True):
            continue
        node['pid_layer'] = clf['pid_layer']
        node['category']  = clf['category']
        node['quality']   = clf['quality']
        nodes_out.append(node)

    edges_out = [
        {'from': e.get('from', ''), 'to': e.get('to', ''),
         'connType': 'signal' if e.get('kind') == 'signal' else 'process'}
        for e in espx.get('edges', [])
    ]
    result = verify_and_sequence(nodes_out, edges_out, conv)
    return jsonify(result)


def get_editor_background(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    file_hash = _m.file_hash
    """Render first page of first source PDF as PNG for canvas background overlay.
    Cached in cache/<hash>_bg.png so subsequent requests are instant."""
    import fitz  # PyMuPDF

    source_dir = PROJECTS_DIR / pid / 'source_docs'
    if not source_dir.exists():
        return jsonify({'error': 'No source docs directory'}), 404

    pdfs = sorted(p for p in source_dir.iterdir() if p.suffix.lower() == '.pdf')
    if not pdfs:
        return jsonify({'error': 'No PDF source found'}), 404

    pdf_path = pdfs[0]
    pdf_bytes = pdf_path.read_bytes()
    bg_hash = file_hash(pdf_bytes)
    cache_dir = PROJECTS_DIR / pid / 'cache'
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / f'{bg_hash}_bg.png'

    if not cache_file.exists():
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        page = doc[0]
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(cache_file))
        doc.close()

    return send_file(str(cache_file), mimetype='image/png')


def editor_autoconnect(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    infer_loops = _m.infer_loops
    load_espx = _m.load_espx
    """Return signal + process edges inferred from loop data, pipe runs, and equipment_ref.
    Does not modify the espx — the editor merges and saves these edges.
    Returns {edges: [{from, to, connType}], counts: {loop, ref, valve_pipe, valve_loop}}"""
    import re as _re

    espx, _ = load_espx(pid)
    if espx is None:
        return jsonify({'edges': [], 'counts': {'loop': 0, 'ref': 0, 'valve_pipe': 0, 'valve_loop': 0}})

    # Tag → node-ID lookup (label holds the ISA tag)
    tag_to_id = {n.get('label', n['id']): n['id'] for n in espx.get('nodes', [])}

    # Dedup: seed with ALL existing edge pairs (signal and process both)
    existing: set = set()
    for e in espx.get('edges', []):
        existing.add(f"{e['from']}|{e['to']}")
        existing.add(f"{e['to']}|{e['from']}")
    for e in espx.get('editor_state', {}).get('edges', []):
        existing.add(f"{e['from']}|{e['to']}")
        existing.add(f"{e['to']}|{e['from']}")

    new_edges: list = []

    def try_add(from_tag: str, to_tag: str, conn_type: str = 'signal') -> bool:
        fid = tag_to_id.get(from_tag)
        tid = tag_to_id.get(to_tag)
        if not fid or not tid or fid == tid:
            return False
        pair = f'{fid}|{tid}'
        if pair in existing:
            return False
        existing.add(pair)
        existing.add(f'{tid}|{fid}')
        new_edges.append({'from': fid, 'to': tid, 'connType': conn_type})
        return True

    count_loop = 0
    count_ref  = 0

    # Method 1 — loop inference: measurement → controller → final_element (signal)
    for loop in infer_loops(espx).values():
        meas  = loop.get('measurement')
        ctrl  = loop.get('controller')
        final = loop.get('final_element')
        if meas  and ctrl  and try_add(meas,  ctrl):  count_loop += 1
        if ctrl  and final and try_add(ctrl,  final): count_loop += 1

    # Method 2 — equipment_ref from studio.instruments (signal)
    for tag, data in espx.get('studio', {}).get('instruments', {}).items():
        if not isinstance(data, dict):
            continue
        ref = (data.get('equipment_ref') or '').strip()
        if ref and try_add(tag, ref):
            count_ref += 1

    # ── Valve process connections ─────────────────────────────────────────────
    _VALVE_PFX = ('FCV', 'LCV', 'PCV', 'TCV', 'HCV', 'XV', 'SV', 'FV', 'LV', 'TV', 'PV')

    def _is_valve(tag: str) -> bool:
        t = tag.upper()
        return any(t.startswith(p) for p in _VALVE_PFX)

    def _is_signal_conn(c: dict) -> bool:
        line_id = (c.get('id', '') or c.get('line_id', '')).lower()
        return 'signal' in line_id

    count_valve_pipe = 0

    # Method 3 — pipe runs: studio.connections and cache pass3 files
    def _all_pipe_conns():
        yield from espx.get('studio', {}).get('connections', [])
        cache_dir = PROJECTS_DIR / pid / 'cache'
        if cache_dir.exists():
            for pf in cache_dir.glob('*_pipes_pass3.json'):
                try:
                    pdata = json.loads(pf.read_text(encoding='utf-8'))
                    yield from pdata.get('connections', [])
                except Exception:
                    pass

    for conn in _all_pipe_conns():
        if _is_signal_conn(conn):
            continue
        ft = conn.get('from_tag', '')
        tt = conn.get('to_tag', '')
        if not ft or not tt:
            continue
        if _is_valve(ft) or _is_valve(tt):
            if try_add(ft, tt, 'process'):
                count_valve_pipe += 1

    # Method 4 — fallback: number-suffix match → controller's equipment_ref (process)
    # For valves that still have no process edge after methods 1-3, find a controller
    # with the same ISA number (FCV-1001 → FIC-1001) and wire valve → equipment_ref.
    count_valve_loop = 0
    _TAG_RE    = _re.compile(r'^([A-Za-z]{1,5})-?(\d+[A-Za-z]?)$')
    _CTRL_PFXS = frozenset({'FIC', 'PIC', 'LIC', 'TIC', 'AIC', 'FFC', 'FRC'})
    instr_store = espx.get('studio', {}).get('instruments', {})

    # Track which valve node IDs now have at least one process edge
    process_touched: set = set()
    for e in new_edges:
        if e['connType'] == 'process':
            process_touched.add(e['from'])
            process_touched.add(e['to'])
    for e in espx.get('edges', []):
        if e.get('kind', '') != 'signal':
            process_touched.add(e.get('from', ''))
            process_touched.add(e.get('to', ''))
    for e in espx.get('editor_state', {}).get('edges', []):
        if e.get('connType', '') != 'signal':
            process_touched.add(e.get('from', ''))
            process_touched.add(e.get('to', ''))

    for node in espx.get('nodes', []):
        vtag = node.get('label', '')
        if not _is_valve(vtag):
            continue
        vid = tag_to_id.get(vtag)
        if not vid or vid in process_touched:
            continue
        m_v = _TAG_RE.match(vtag)
        if not m_v:
            continue
        vnum = m_v.group(2)
        for ctag, cdata in instr_store.items():
            if not isinstance(cdata, dict):
                continue
            m_c = _TAG_RE.match(ctag)
            if not m_c or m_c.group(1).upper() not in _CTRL_PFXS:
                continue
            if m_c.group(2) == vnum:
                eqref = (cdata.get('equipment_ref') or '').strip()
                if eqref and try_add(vtag, eqref, 'process'):
                    count_valve_loop += 1
                break

    return jsonify({
        'edges':  new_edges,
        'counts': {
            'loop':       count_loop,
            'ref':        count_ref,
            'valve_pipe': count_valve_pipe,
            'valve_loop': count_valve_loop,
        },
    })


def editor_arrange_process(pid):
    import main as _m
    _editor_arrange_process_inner = _m._editor_arrange_process_inner
    """Use LLM to suggest process connections for dangling equipment.
    Loads process-reconstruction.md skill, builds structured prompt, validates response.
    Returns {connections, process_sections, warnings, counts}"""
    import re as _re
    import traceback as _tb

    def _log(msg):
        """Print msg, replacing non-ASCII to survive cp1252 consoles."""
        try:
            print(msg.encode('ascii', 'backslashreplace').decode('ascii'), flush=True)
        except Exception:
            print(repr(msg), flush=True)

    try:
        return _editor_arrange_process_inner(pid, _re, _tb, _log)
    except Exception:
        tb = _tb.format_exc()
        _log(f'[arrange-process] UNHANDLED EXCEPTION:\n{tb}')
        return jsonify({'error': 'Internal error', 'traceback': tb}), 500


def save_editor_state(pid):
    import main as _m
    CANONICAL_INSTR_KINDS = _m.CANONICAL_INSTR_KINDS
    _db_persist_espx = _m._db_persist_espx
    _db_write_canvas_positions = _m._db_write_canvas_positions
    load_espx = _m.load_espx
    normalize_kind = _m.normalize_kind
    """Save editor nodes + edges to espx and canvas.json."""
    data = request.json
    nodes = data.get('nodes', [])
    edges = data.get('edges', [])
    CANVAS_W, CANVAS_H = 1400, 800
    espx, espx_path = load_espx(pid)
    if espx is None:
        espx = {}
    id_to_tag = {n['id']: (n.get('tag') or n.get('label') or n['id']) for n in nodes}
    espx_nodes = []
    canvas_pos = {}
    for n in nodes:
        px, py = float(n.get('x', 0)), float(n.get('y', 0))
        canvas_pos[n['id']] = {'x': px, 'y': py}
        # Editor always sends palette kind; normalize_kind derives both directions
        palette_kind, canonical_kind = normalize_kind(n['kind'], n.get('kind_canonical'))
        en = {
            'id': n['id'],
            'label': id_to_tag[n['id']],
            'kind': canonical_kind,    # exporters (SVG/DXF/YMPL/VIDS) use this
            'kind_detail': palette_kind,  # editor round-trip
            'x': round(px / CANVAS_W, 4),
            'y': round(py / CANVAS_H, 4),
        }
        for f in ('description', 'area', 'equipment_ref', 'range_lo', 'range_hi',
                  'units', 'alarm_hi', 'alarm_hihi', 'alarm_lo', 'alarm_lolo',
                  'fail_position', 'drawing'):
            if n.get(f) is not None and n[f] != '':
                en[f] = n[f]
        espx_nodes.append(en)
    espx['nodes'] = espx_nodes

    # Write espx['edges'] so SVG / DXF / YMPL exporters see connections.
    # connType 'process' → kind 'stream'; 'signal' stays 'signal'.
    espx['edges'] = [
        {
            'from': e['from'], 'to': e['to'],
            'kind': 'signal' if e.get('connType') == 'signal' else 'stream',
            **(({'label': e['line_id']} if e.get('line_id') else {})),
        }
        for e in edges
    ]

    # Store full edge data for round-trip
    espx.setdefault('editor_state', {})['edges'] = edges

    # Build studio dicts so VIDS and Markdown exporters see tagged data
    studio = espx.setdefault('studio', {})
    instruments, equipment = {}, {}
    for n in nodes:
        tag = id_to_tag[n['id']]
        palette_kind, canonical_kind = normalize_kind(n['kind'], n.get('kind_canonical'))
        if canonical_kind in CANONICAL_INSTR_KINDS:
            rec = {'tag': tag, 'type': canonical_kind, 'kind_detail': palette_kind}
            for f in ('area', 'description', 'equipment_ref', 'units', 'fail_position'):
                if n.get(f):
                    rec[f] = n[f]
            for f in ('range_lo', 'range_hi', 'alarm_hi', 'alarm_hihi', 'alarm_lo', 'alarm_lolo'):
                if n.get(f) is not None:
                    rec[f] = n[f]
            instruments[tag] = rec
        else:
            rec = {'tag': tag, 'type': canonical_kind, 'kind_detail': palette_kind}
            for f in ('area', 'description'):
                if n.get(f):
                    rec[f] = n[f]
            equipment[tag] = rec
    studio['instruments'] = instruments
    studio['equipment'] = equipment

    # Pipe connections (process only) for VIDS and Markdown
    studio['connections'] = [
        {k: v for k, v in {
            'from_tag':   id_to_tag.get(e['from'], e['from']),
            'to_tag':     id_to_tag.get(e['to'],   e['to']),
            'id':         e.get('line_id', ''),
            'fluid':      e.get('fluid', ''),
            'line_size':  e.get('line_size', ''),
            'line_class': e.get('line_class', ''),
            'insulation': e.get('insulation', ''),
            'type':       'process',
        }.items() if v}
        for e in edges if e.get('connType') == 'process'
    ]

    # DB is now the only store for canvas positions + nodes/edges.
    try:
        _db_write_canvas_positions(pid, canvas_pos)
        _db_persist_espx(pid, espx)
    except Exception as e:
        print(f'editor save DB write failed for {pid}: {e}')
    return jsonify({'saved': len(nodes), 'edges': len(edges)})


def describe_to_canvas(pid):
    import main as _m
    _db_get_canvas = _m._db_get_canvas
    _get_conventions = _m._get_conventions
    extract_json = _m.extract_json
    llm = _m.llm
    load_espx = _m.load_espx
    """Context-aware canvas assistant: add, connect, modify, move, or answer."""
    body = request.get_json(force=True, silent=True) or {}
    text = body.get('text', '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    # Canvas state sent by the client (compact: id, tag, kind, area, x, y per node)
    canvas_nodes = body.get('canvas_nodes', [])
    canvas_edges = body.get('canvas_edges', [])   # [{from_tag, to_tag, connType}]
    selected     = body.get('selected')            # {id, tag, kind} | null
    area_filter  = (body.get('area_filter') or '').strip()

    espx, _ = load_espx(pid)
    if espx is None:
        espx = {}

    # Fall back to espx when client sent no canvas state (legacy callers)
    if not canvas_nodes:
        canvas = _db_get_canvas(pid)
        CANVAS_W, CANVAS_H = 1400, 800
        for n in espx.get('nodes', []):
            if n['id'] in canvas:
                px = canvas[n['id']].get('x', 100)
                py = canvas[n['id']].get('y', 100)
            elif n.get('x') is not None:
                px = round(float(n['x']) * CANVAS_W)
                py = round(float(n['y']) * CANVAS_H)
            else:
                px, py = 100, 100
            canvas_nodes.append({
                'id': n['id'], 'tag': n.get('label', n['id']),
                'kind': n.get('kind', ''), 'area': n.get('area', ''),
                'x': px, 'y': py,
            })

    # tag→id lookup (canvas takes priority; fill gaps from espx)
    tag_to_id: dict = {}
    for n in canvas_nodes:
        if n.get('tag') and n.get('id'):
            tag_to_id[n['tag']] = n['id']
    for n in espx.get('nodes', []):
        lbl = n.get('label', n['id'])
        if lbl not in tag_to_id:
            tag_to_id[lbl] = n['id']

    # Safe next IDs
    all_nids = [n.get('id','') for n in canvas_nodes] + [n['id'] for n in espx.get('nodes',[])]
    max_n = max((int(x[1:]) for x in all_nids if x.startswith('n') and x[1:].isdigit()), default=0)
    existing_eids = [e.get('id','') for e in espx.get('editor_state',{}).get('edges',[])]
    max_e = max((int(x[1:]) for x in existing_eids if x.startswith('e') and x[1:].isdigit()), default=0)
    start_x = int(max((n.get('x', 0) for n in canvas_nodes), default=0)) + 200 if canvas_nodes else 150

    # ── Build context string ──────────────────────────────────────────────────
    if canvas_nodes:
        equip_parts = []
        for n in canvas_nodes[:80]:
            s = f'{n["tag"]} ({n.get("kind","?")}' + (f', {n["area"]}' if n.get('area') else '') + ')'
            equip_parts.append(s)
        equip_ctx = f'Equipment on canvas ({len(canvas_nodes)}): ' + ', '.join(equip_parts)
    else:
        equip_ctx = 'Equipment on canvas: (none yet)'

    if canvas_edges:
        edge_ctx = 'Connections: ' + ', '.join(
            f'{e.get("from_tag","?")}→{e.get("to_tag","?")}({e.get("connType","process")})'
            for e in canvas_edges[:60]
        )
    else:
        edge_ctx = 'Connections: (none yet)'

    selected_ctx = (f'\nSelected node: {selected["tag"]} ({selected["kind"]})'
                    if selected and selected.get('tag') else '')
    area_ctx     = (f'\nCurrent area filter: {area_filter}' if area_filter else '')

    conv = _get_conventions(pid)
    conv_ctx = ''
    if conv:
        ct = conv.as_skill_text()
        if ct:
            conv_ctx = '\n\nCompany conventions (excerpt):\n' + ct[:1200]

    kind_vocab = (
        'vessel_v, vessel_h, flash_drum, knockout, accumulator, surge_drum, '
        'tank_atm, tank_cone, hopper, '
        'hx_st, hx_plate, condenser, reboiler_k, air_cooler, fired_heater, boiler, '
        'dist_tray, dist_packed, absorber, scrubber, stripper, '
        'cyclone, filter_pf, centrifuge, membrane, '
        'cstr, pfr, batch_reactor, fixed_bed, fluidized_bed, '
        'pump_cent, pump_pd, comp_cent, comp_recip, blower, mixer, '
        'cv_globe, cv_ball, cv_butterfly, cv_gate, checkvalve, psv, rupture_disc, '
        'ft, lt, pt, tt, at, fe, le, pe, te, '
        'fic, fi, fr, fsh, fsl, fy, dcs, plc, sis, hmi'
    )

    prompt = f"""CURRENT CANVAS STATE:
{equip_ctx}
{edge_ctx}{selected_ctx}{area_ctx}{conv_ctx}

The user is looking at this diagram and says:
"{text}"

INSTRUCTIONS — choose whatever fits the user's intent:

A) ADD new nodes:
   {{"nodes":[{{"tag":"V-101","kind":"vessel_v","description":"feed drum","area":""}}],
     "edges":[{{"from_tag":"V-101","to_tag":"P-101","connType":"process"}}]}}
   Do NOT duplicate a tag already on the canvas.

B) CONNECT existing nodes (no new nodes):
   {{"edges":[{{"from_tag":"FT-101","to_tag":"FIC-101","connType":"signal"}}]}}

C) MODIFY existing nodes:
   {{"updates":[{{"id":"n15","field":"area","value":"REACTOR"}},
               {{"id":"n15","field":"description","value":"Reactor feed vessel"}}]}}
   Valid fields: tag, description, area, kind, units, range_lo, range_hi

D) MOVE nodes:
   {{"moves":[{{"id":"n15","x":400,"y":200}}]}}

E) ANSWER a question (no canvas change):
   {{"reply":"FT-101 measures the flow from P-101 to E-201..."}}

F) Any combination of the above fields.

Kind vocabulary: {kind_vocab}
connType: "process" for pipe, "signal" for instrument wiring.

Return ONLY valid JSON. No markdown fences. No text outside the JSON object."""

    try:
        resp = llm.complete(prompt, max_tokens=3000, tier='smart')
        raw  = resp.text
    except Exception as e:
        return jsonify({'error': f'LLM API error: {e}'}), 502

    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        return jsonify({'error': 'Claude returned invalid JSON', 'raw': raw[:500]}), 502

    # ── Nodes ─────────────────────────────────────────────────────────────────
    new_nodes = []
    for i, n in enumerate(parsed.get('nodes', [])):
        tag = n.get('tag', '').strip()
        if not tag or tag in tag_to_id:
            continue
        max_n += 1
        nid = f'n{max_n}'
        tag_to_id[tag] = nid
        new_nodes.append({
            'id': nid, 'kind': n.get('kind', 'vessel_v'),
            'tag': tag, 'label': n.get('description') or tag,
            'description': n.get('description', ''), 'area': n.get('area', ''),
            'x': start_x + (i // 4) * 180, 'y': 120 + (i % 4) * 140,
            'equipment_ref': '',
            'range_lo': None, 'range_hi': None, 'units': '',
            'alarm_hi': None, 'alarm_hihi': None, 'alarm_lo': None, 'alarm_lolo': None,
            'fail_position': '', 'pid_layer': None, 'category': '',
            'measured_variable': '', 'quality': 'ok',
        })

    # ── Edges ─────────────────────────────────────────────────────────────────
    new_edges = []
    for edge in parsed.get('edges', []):
        from_id = tag_to_id.get(edge.get('from_tag', ''))
        to_id   = tag_to_id.get(edge.get('to_tag', ''))
        if not from_id or not to_id or from_id == to_id:
            continue
        max_e += 1
        new_edges.append({
            'id': f'e{max_e}', 'from': from_id, 'to': to_id,
            'connType': edge.get('connType', 'process'),
            'line_id': '', 'fluid': '', 'line_size': '', 'line_class': '', 'insulation': '',
        })

    # updates, moves, reply pass through unchanged
    return jsonify({
        'nodes':   new_nodes,
        'edges':   new_edges,
        'updates': parsed.get('updates', []),
        'moves':   parsed.get('moves', []),
        'reply':   parsed.get('reply', ''),
    })
