"""
domain/mermaid.py — pure Mermaid diagram-text generation.

Extracted from main.py (Phase 4). Builds a Mermaid string from an
already-in-memory YMPL/espx doc — no subprocess, no filesystem.
(main.py's `ympl_render()` / `ympl_to_mermaid()` are the Node.js-bridge
counterparts and stay in main.py — they shell out to ympl.js.)

Pure stdlib, no Flask/DB/adapters/services imports.
"""
from __future__ import annotations


def generate_mermaid_python(ympl_doc: dict) -> str:
    """Generate Mermaid from YMPL using Python — handles all special chars via backtick quoting."""
    nodes = ympl_doc.get('nodes', [])
    edges = ympl_doc.get('edges', [])

    shapes = {
        'heat_exchanger': '("{label}")',
        'reactor': '["{label}"]',
        'vessel': '["{label}"]',
        'separator': '["{label}"]',
        'pump': '("{label}")',
        'compressor': '("{label}")',
        'column': '["{label}"]',
        'transmitter': '(("{label}"))',
        'controller': '["{label}"]',
        'valve': '["{label}"]',
        'checkvalve': '["{label}"]',
        'default': '["{label}"]',
    }

    lines = ['graph LR']

    for node in nodes:
        nid = 'n_' + node['id'].replace('-','_').replace('.','_')
        label = node.get('label', node.get('type', node['id'])).replace('"', "'")
        shape_tmpl = shapes.get(node.get('kind', ''), shapes['default'])
        lines.append(f'  {nid}{shape_tmpl.replace("{label}", label)}')

    for edge in edges:
        from_id = 'n_' + edge['from'].replace('-','_').replace('.','_')
        to_id   = 'n_' + edge['to'].replace('-','_').replace('.','_')
        kind = edge.get('kind', 'stream')
        arrow = '-.->' if kind in ('signal','bypass') else '==>' if kind == 'recycle' else '-->'
        elabel = edge.get('label', '')
        if elabel:
            elabel = elabel.replace('"',"'")[:20]
            lines.append(f'  {from_id} {arrow}|"{elabel}"| {to_id}')
        else:
            lines.append(f'  {from_id} {arrow} {to_id}')

    return '\n'.join(lines)
