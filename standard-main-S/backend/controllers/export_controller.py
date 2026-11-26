"""
controllers/export_controller.py — VIDS/YMPL/SVG/DXF/Markdown export endpoints

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

from flask_compat import jsonify, request, Response
import io
import yaml

def export_vids_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    load_espx = _m.load_espx
    update_manifest_after_export = _m.update_manifest_after_export
    from adapters.vids import to_yaml_string
    espx, _ = load_espx(pid)
    studio = espx['studio']
    review = studio.get('review', {})
    # Exclude rejected tags — engineer has confirmed they are bad reads
    filtered = dict(studio)
    filtered['instruments'] = {
        tag: data for tag, data in studio.get('instruments', {}).items()
        if review.get(tag) != 'rejected'
    }
    filtered['equipment'] = {
        tag: data for tag, data in studio.get('equipment', {}).items()
        if review.get(tag) != 'rejected'
    }
    rejected_count = len(studio.get('instruments', {})) + len(studio.get('equipment', {})) \
                   - len(filtered['instruments']) - len(filtered['equipment'])
    if rejected_count:
        print(f'VIDS export: excluded {rejected_count} rejected tag(s)')

    # Stamp each tag's position from its node. Nodes hold normalised 0-1 x/y —
    # the unit the desktop app writes on drag and both its exporters emit — so
    # VIDS carries the same coordinates whichever exporter produced it. Not
    # canvas_positions: those are 1400x800 pixels from the legacy Flask canvas.
    node_pos = {
        n.get('label'): (n.get('x'), n.get('y'))
        for n in espx.get('nodes', [])
        if n.get('x') is not None and n.get('y') is not None
    }
    for section in ('equipment', 'instruments'):
        for tag, data in filtered[section].items():
            pos = node_pos.get(tag)
            if pos:
                filtered[section][tag] = {**data, 'x': pos[0], 'y': pos[1]}

    vids_yaml = to_yaml_string(filtered)
    out = PROJECTS_DIR / pid / 'exports' / f'{pid}_vids.yaml'
    out.write_text(vids_yaml, encoding='utf-8')
    update_manifest_after_export(pid, 'vids', out.name)
    return jsonify({'yaml': vids_yaml, 'path': str(out), 'filename': out.name})


def export_ympl_route(pid):
    """YMPL through the one shared writer (adapters/ympl_export.py), the same
    one the desktop app spawns, so both surfaces export identical YMPL.
    ?topology_only=1 returns the topology-only shape the desktop used to build."""
    import main as _m
    from adapters.ympl_export import write_ympl
    topology_only = (request.args.get('topology_only') or '').lower() in ('1', 'true', 'yes')
    try:
        out = write_ympl(pid, _m.PROJECTS_DIR / pid / 'exports', topology_only)
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    _m.update_manifest_after_export(pid, 'ympl', out.name)
    return jsonify({'ympl': out.read_text(encoding='utf-8'), 'path': str(out),
                    'filename': out.name})


def export_connectivity_route(pid):
    """Connectivity graph JSON. ?schema=2.0.0 (default) or 2.1.0 (adds systems
    and subsystems). The response carries the document and its schema check."""
    import json as _json
    import main as _m
    from adapters.connectivity_export import SUPPORTED, validate, write_export
    schema = request.args.get('schema') or '2.0.0'
    if schema not in SUPPORTED:
        return jsonify({'error': f'schema must be one of {list(SUPPORTED)}'}), 400
    out = write_export(pid, _m.PROJECTS_DIR / pid / 'exports', schema)
    document = _json.loads(out.read_text(encoding='utf-8'))
    _m.update_manifest_after_export(pid, 'connectivity', out.name)
    return jsonify({'connectivity': document, 'path': str(out), 'filename': out.name,
                    'validation_errors': validate(document)})


def export_svg_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _load_canvas_positions = _m._load_canvas_positions
    load_espx = _m.load_espx
    update_manifest_after_export = _m.update_manifest_after_export
    from adapters.svg_pid import generate_svg_pid, ALL_LAYERS
    from adapters.engine import infer_connections as _infer
    espx, _ = load_espx(pid)
    _nodes = list(espx.get('nodes', []))
    _edges = list(espx.get('edges', []))
    _nodes, _inf = _infer(_nodes, _edges)
    ympl_doc = {'nodes': _nodes, 'edges': _edges + _inf}
    project_name = espx.get('studio', {}).get('metadata', {}).get('plant_name', pid) \
                   if espx.get('studio') else pid
    view_preset = request.args.get('view', 'control')
    layers = ALL_LAYERS if view_preset == 'full' else None
    # ?bg=light gives the print/engineering palette; default keeps the Canvas
    # dark theme so the export matches what the screen shows.
    background = 'light' if request.args.get('bg') == 'light' else 'dark'
    canvas_pos = _load_canvas_positions(pid, espx)
    svg = generate_svg_pid(ympl_doc, project_name, layers=layers,
                           canvas_positions=canvas_pos, view_preset=view_preset,
                           background=background)
    out = PROJECTS_DIR / pid / 'exports' / f'{pid}_pid.svg'
    out.write_text(svg, encoding='utf-8')
    update_manifest_after_export(pid, 'svg', out.name)
    return Response(svg, mimetype='image/svg+xml',
                    headers={'Content-Disposition': f'attachment; filename="{out.name}"'})


def export_svg_drawing_route(pid, drawing):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    _load_canvas_positions = _m._load_canvas_positions
    _svg_for_drawing = _m._svg_for_drawing
    load_espx = _m.load_espx
    update_manifest_after_export = _m.update_manifest_after_export
    """Per-drawing SVG export.  drawing='zip' → zip of all drawings."""
    import urllib.parse
    import zipfile as _zip
    from adapters.svg_pid import ALL_LAYERS
    espx, _ = load_espx(pid)
    view_preset = request.args.get('view', 'control')
    svg_layers  = ALL_LAYERS if view_preset == 'full' else None
    canvas_pos  = _load_canvas_positions(pid, espx)

    # ── zip of all drawings ────────────────────────────────────────────────────
    if drawing == 'zip':
        all_nodes = espx.get('nodes', [])
        drawings = sorted({n.get('drawing', '') for n in all_nodes} - {''})
        if not drawings:
            return jsonify({'error': 'No drawing numbers found in nodes'}), 404

        buf = io.BytesIO()
        with _zip.ZipFile(buf, 'w', _zip.ZIP_DEFLATED) as zf:
            cards = []
            for drw in drawings:
                svg = _svg_for_drawing(espx, drw, pid, layers=svg_layers,
                                       canvas_positions=canvas_pos, view_preset=view_preset)
                fname = drw.replace('/', '-') + '.svg'
                zf.writestr(fname, svg)
                cards.append(
                    f'<div class="card"><a href="{fname}" target="_blank">'
                    f'<img src="{fname}" alt="{drw}"/>'
                    f'<div class="label">{drw}</div></a></div>'
                )
            index_html = (
                '<!DOCTYPE html><html><head><meta charset="UTF-8">'
                f'<title>{pid} — P&ID drawings</title>'
                '<style>body{font-family:sans-serif;background:#f5f5f0;padding:20px}'
                'h1{font-size:16px;margin-bottom:16px}'
                '.grid{display:flex;flex-wrap:wrap;gap:16px}'
                '.card{background:#fff;border:1px solid #ddd;border-radius:6px;'
                'overflow:hidden;width:200px;text-align:center}'
                '.card img{width:100%;height:140px;object-fit:contain;padding:4px}'
                '.card .label{font-size:11px;padding:6px;border-top:1px solid #eee;'
                'color:#444}</style></head><body>'
                f'<h1>{pid} — {len(drawings)} drawings</h1>'
                '<div class="grid">' + ''.join(cards) + '</div>'
                '</body></html>'
            )
            zf.writestr('index.html', index_html)

        zip_bytes = buf.getvalue()
        zip_name = f'{pid}_svgs.zip'
        out = PROJECTS_DIR / pid / 'exports' / zip_name
        out.write_bytes(zip_bytes)
        update_manifest_after_export(pid, 'svg_zip', zip_name)
        print(f'SVG zip: {len(drawings)} drawings -> {zip_name}')
        return Response(zip_bytes, mimetype='application/zip',
                        headers={'Content-Disposition': f'attachment; filename="{zip_name}"'})

    # ── all drawings (alias) ───────────────────────────────────────────────────
    if drawing == 'all':
        return export_svg_route(pid)

    # ── single drawing ─────────────────────────────────────────────────────────
    drawing = urllib.parse.unquote(drawing)
    svg = _svg_for_drawing(espx, drawing, pid, layers=svg_layers,
                           canvas_positions=canvas_pos, view_preset=view_preset)
    safe = drawing.replace('/', '-')
    fname = f'{pid}_{safe}.svg'
    out = PROJECTS_DIR / pid / 'exports' / fname
    out.write_text(svg, encoding='utf-8')
    update_manifest_after_export(pid, 'svg', fname)
    return Response(svg, mimetype='image/svg+xml',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})


def export_dxf_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    load_espx = _m.load_espx
    update_manifest_after_export = _m.update_manifest_after_export
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        return jsonify({'error': 'ezdxf not installed — run: pip install ezdxf>=1.3'}), 500
    from adapters.dxf import generate_dxf
    espx, _ = load_espx(pid)
    project_name = espx.get('studio', {}).get('metadata', {}).get('plant_name', pid) \
                   if espx.get('studio') else pid
    ympl_doc = {'nodes': espx.get('nodes', []), 'edges': espx.get('edges', [])}
    dxf_bytes = generate_dxf(ympl_doc, project_name)
    out = PROJECTS_DIR / pid / 'exports' / f'{pid}_pid.dxf'
    out.write_bytes(dxf_bytes)
    update_manifest_after_export(pid, 'dxf', out.name)
    return Response(dxf_bytes, mimetype='application/dxf',
                    headers={'Content-Disposition': f'attachment; filename="{out.name}"'})


def export_markdown_route(pid):
    import main as _m
    PROJECTS_DIR = _m.PROJECTS_DIR
    load_espx = _m.load_espx
    load_manifest = _m.load_manifest
    update_manifest_after_export = _m.update_manifest_after_export
    import zipfile as _zip
    from adapters.md_export import to_markdown
    espx, _ = load_espx(pid)
    loops = espx.get('studio', {}).get('loops', {})
    print(f'Total loops in espx: {len(loops)}')
    manifest = load_manifest(pid)
    result = to_markdown(espx, manifest=manifest)
    export_dir = PROJECTS_DIR / pid / 'exports'
    drawings = {k: v for k, v in result.items() if not k.startswith('_')}

    if len(drawings) <= 1:
        drawing_num = next(iter(drawings), '_index')
        md_str = result.get(drawing_num, result.get('_index', ''))
        fname = f'{pid}_{drawing_num.replace("/", "-").replace(" ", "_")}.md'
        (export_dir / fname).write_text(md_str, encoding='utf-8')
        update_manifest_after_export(pid, 'markdown', fname)
        return Response(md_str, mimetype='text/markdown',
                        headers={'Content-Disposition': f'attachment; filename="{fname}"'})

    buf = io.BytesIO()
    with _zip.ZipFile(buf, 'w', _zip.ZIP_DEFLATED) as zf:
        for key, md_str in result.items():
            fname = 'index.md' if key == '_index' \
                    else key.replace('/', '-').replace(' ', '_') + '.md'
            zf.writestr(fname, md_str)
    zip_bytes = buf.getvalue()
    zip_name = f'{pid}_pid_docs.zip'
    (export_dir / zip_name).write_bytes(zip_bytes)
    update_manifest_after_export(pid, 'markdown', zip_name)
    return Response(zip_bytes, mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{zip_name}"'})
