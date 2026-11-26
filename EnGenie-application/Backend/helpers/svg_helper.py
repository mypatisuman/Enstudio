"""
helpers/svg_helper.py — single-drawing SVG generation.

Extracted from main.py (Phase 9): _svg_for_drawing(), moved verbatim. Fully
self-contained (only lazy adapter imports + its own parameters) — no
main.py globals referenced.
"""
from __future__ import annotations


def _svg_for_drawing(espx: dict, drawing: str, pid: str,
                     layers=None, canvas_positions: dict | None = None,
                     view_preset: str = 'control',
                     background: str = 'dark') -> str:
    """Generate SVG filtered to nodes/edges on a single drawing number."""
    from adapters.svg_pid import generate_svg_pid
    from adapters.engine import infer_connections as _infer
    all_nodes = espx.get('nodes', [])
    all_edges = espx.get('edges', [])
    nodes = [n for n in all_nodes if n.get('drawing', '') == drawing]
    node_ids = {n['id'] for n in nodes}
    edges = [e for e in all_edges
             if e.get('from') in node_ids and e.get('to') in node_ids]
    # Run inference on the drawing-scoped subset so signals and process
    # pipes are complete even for drawings that weren't fully connected.
    nodes, inf_edges = _infer(nodes, edges)
    edges = edges + [e for e in inf_edges
                     if e.get('from') in node_ids and e.get('to') in node_ids]
    project_name = espx.get('studio', {}).get('metadata', {}).get('plant_name', pid) \
                   if espx.get('studio') else pid
    return generate_svg_pid({'nodes': nodes, 'edges': edges},
                             f'{project_name} — {drawing}',
                             layers=layers,
                             canvas_positions=canvas_positions,
                             view_preset=view_preset,
                             background=background)
