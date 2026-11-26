"""
md_export.py — Markdown + Mermaid export for EngineeringStudio

Groups ESPX data by drawing number, generates one .md per drawing with:
  - Equipment / instruments / connections / loops tables
  - Mermaid flowchart LR with classDef ISA-consistent colours

Entry point: to_markdown(espx) → dict[drawing_num → md_str, '_index' → index_str]
"""
from __future__ import annotations
import re as _re
from typing import Dict, List, Tuple

# ISA-consistent colours (mirrors svg_pid.py COLORS)
KIND_TO_CLASS: Dict[str, str] = {
    'vessel':             'vessel',
    'separator':          'separator',
    'heat_exchanger':     'heatExchanger',
    'pump':               'pump',
    'compressor':         'compressor',
    'column':             'column',
    'reactor':            'reactor',
    'absorber':           'absorber',
    'adsorption':         'absorber',
    'filter':             'filter',
    'meter':              'meter',
    'transmitter':        'transmitter',
    'controller':         'controller',
    'indicator':          'indicator',
    'recorder':           'recorder',
    'switch':             'switch',
    'analyzer':           'analyzer',
    'element':            'element',
    'valve':              'valve',
    'checkvalve':         'checkvalve',
    'relief':             'relief',
    'off_page_connector': 'offPageConn',
}

CLASS_DEFS: List[str] = [
    'classDef vessel fill:#E8F4FD,stroke:#2E6DA4',
    'classDef separator fill:#E8F4FD,stroke:#2E6DA4',
    'classDef heatExchanger fill:#FEF3E2,stroke:#C07A00',
    'classDef pump fill:#E8F6E8,stroke:#2E7D32',
    'classDef compressor fill:#E8F6E8,stroke:#2E7D32',
    'classDef reactor fill:#FCE8E8,stroke:#C0392B',
    'classDef column fill:#F0E8FC,stroke:#6B2E9A',
    'classDef absorber fill:#F0E8FC,stroke:#6B2E9A',
    'classDef filter fill:#F5F5F5,stroke:#666666',
    'classDef meter fill:#F5F5F5,stroke:#666666',
    'classDef transmitter fill:#E3F2FD,stroke:#1565C0',
    'classDef controller fill:#E8F5E9,stroke:#2E7D32',
    'classDef indicator fill:#FFFFFF,stroke:#555555',
    'classDef recorder fill:#FFF8E1,stroke:#F57F17',
    'classDef switch fill:#FFF3E0,stroke:#E65100',
    'classDef analyzer fill:#F3E5F5,stroke:#6A1B9A',
    'classDef element fill:#E8EAF6,stroke:#283593',
    'classDef valve fill:#F5F5F5,stroke:#424242',
    'classDef checkvalve fill:#F5F5F5,stroke:#424242',
    'classDef relief fill:#FCE8E8,stroke:#C0392B',
    'classDef offPageConn fill:#E8E8E8,stroke:#888888',
]

INSTRUMENT_KINDS = frozenset({
    'transmitter', 'controller', 'indicator',
    'recorder', 'switch', 'analyzer', 'element'
})
EQUIPMENT_KINDS = frozenset({
    'vessel', 'separator', 'heat_exchanger', 'pump',
    'compressor', 'column', 'reactor', 'absorber',
    'adsorption', 'filter', 'meter'
})

# Mermaid node shapes per kind
SHAPES: Dict[str, str] = {
    **{k: '(("{label}"))' for k in INSTRUMENT_KINDS},
    'heat_exchanger': '("{label}")',
    'pump':           '("{label}")',
    'compressor':     '("{label}")',
    'off_page_connector': '>"{label}"]',
}


def _mermaid_id(node: dict) -> str:
    return 'n_' + node['id'].replace('-', '_').replace('.', '_').replace('/', '_')


def _drawing_mermaid(dnodes: list, all_edges: list, node_id_set: set) -> str:
    lines = ['flowchart LR', '']
    lines.extend(CLASS_DEFS)
    lines.append('')

    nid_map: Dict[str, str] = {}
    for node in dnodes:
        mid = _mermaid_id(node)
        nid_map[node['id']] = mid
        label = node.get('label', node['id']).replace('"', "'")
        kind  = node.get('kind', 'default')
        shape_tmpl = SHAPES.get(kind, '["{label}"]')
        shape = shape_tmpl.replace('{label}', label)
        cls   = KIND_TO_CLASS.get(kind, '')
        suffix = f':::{cls}' if cls else ''
        lines.append(f'  {mid}{shape}{suffix}')

    lines.append('')
    for edge in all_edges:
        if edge['from'] not in node_id_set or edge['to'] not in node_id_set:
            continue
        fid = nid_map.get(edge['from'], 'n_' + edge['from'])
        tid = nid_map.get(edge['to'],   'n_' + edge['to'])
        kind = edge.get('kind', 'stream')
        arrow = '-.->' if kind in ('signal', 'bypass') else '==>' if kind == 'recycle' else '-->'
        lbl = (edge.get('label') or '').replace('"', "'")[:20]
        if lbl:
            lines.append(f'  {fid} {arrow}|"{lbl}"| {tid}')
        else:
            lines.append(f'  {fid} {arrow} {tid}')

    return '\n'.join(lines)


def _md_table(headers: list, rows: list) -> List[str]:
    sep = '|' + '|'.join('---' for _ in headers) + '|'
    return [
        '| ' + ' | '.join(headers) + ' |',
        sep,
        *('| ' + ' | '.join(str(c) for c in row) + ' |' for row in rows),
        '',
    ]


def to_markdown(espx: dict) -> Dict[str, str]:
    """
    Convert ESPX to per-drawing Markdown + Mermaid documents.
    Returns {drawing_num: md_str, ..., '_index': index_md_str}
    """
    nodes       = espx.get('nodes', [])
    edges       = espx.get('edges', [])
    studio      = espx.get('studio', {})
    instruments = studio.get('instruments', {})
    equipment   = studio.get('equipment', {})
    connections = studio.get('connections', [])
    loops       = studio.get('loops', {})
    project     = studio.get('metadata', {}).get('plant_name', espx.get('id', 'plant'))
    drawings_map: Dict[str, dict] = {
        d['number']: d for d in studio.get('drawings', []) if d.get('number')
    }

    # Group nodes by drawing (fall back to 'main')
    drawings: Dict[str, list] = {}
    for node in nodes:
        d = node.get('drawing') or node.get('area') or 'main'
        drawings.setdefault(d, []).append(node)
    if not drawings:
        drawings = {'main': nodes}

    result: Dict[str, str] = {}
    index_rows: List[Tuple] = []

    for drawing_num in sorted(drawings):
        dnodes   = drawings[drawing_num]
        node_ids = {n['id'] for n in dnodes}

        # Equipment table
        eq_rows = [
            (n['label'], n['kind'],
             equipment.get(n['label'], {}).get('description', ''),
             equipment.get(n['label'], {}).get('area', ''))
            for n in dnodes if n.get('kind') in EQUIPMENT_KINDS
        ]

        # Instruments table
        instr_rows = []
        for n in dnodes:
            if n.get('kind') not in INSTRUMENT_KINDS:
                continue
            i = instruments.get(n['label'], {})
            lo = i.get('range_lo')
            hi = i.get('range_hi')
            units = i.get('units', '')
            rng = f"{lo}–{hi} {units}".strip() if (lo is not None or hi is not None) else ''
            instr_rows.append((
                n['label'],
                i.get('type', n['kind']),
                i.get('equipment_ref', '') or '',
                rng,
                ', '.join(i.get('also_on', [])),
                i.get('alarm_hihi') or '',
                i.get('alarm_lolo') or '',
            ))

        # Connections that originate from this drawing
        conn_rows = []
        dnode_labels = {n['label'] for n in dnodes}
        for c in connections:
            if c.get('from_tag') in dnode_labels:
                conn_rows.append((
                    c.get('id', ''),
                    c.get('from_tag', ''),
                    c.get('to_tag', ''),
                    c.get('fluid', ''),
                    c.get('line_size', ''),
                ))

        # Loops with controller on this drawing
        loop_rows = []
        for lkey, loop in loops.items():
            ctrl = loop.get('controller') or lkey
            if ctrl in dnode_labels:
                loop_rows.append((
                    lkey,
                    loop.get('type', ''),
                    loop.get('measurement', ''),
                    loop.get('final_element', ''),
                ))

        mermaid = _drawing_mermaid(dnodes, edges, node_ids)

        drawing_title = drawings_map.get(drawing_num, {}).get('title', '')
        heading = f'# {drawing_num}: {drawing_title}' if drawing_title else f'# {drawing_num}'
        lines: List[str] = [heading, f'**Project:** {project}', '']

        # Process Context
        opc_nodes = {n['id']: n for n in dnodes if n.get('kind') == 'off_page_connector'}
        feeds_from = [opc_nodes[e['from']]['label']
                      for e in edges if e['from'] in opc_nodes and e['to'] in node_ids]
        produces_to = [opc_nodes[e['to']]['label']
                       for e in edges if e['to'] in opc_nodes and e['from'] in node_ids]
        safety_tags = [n['label'] for n in dnodes
                       if _re.search(r'PSV|ESD|PAHH|TSHH|LSHH|FSLL|PSLL|LSLL', n['label'], _re.I)]
        key_equip = [n['label'] for n in dnodes if n.get('kind') in EQUIPMENT_KINDS]
        ctx = []
        if key_equip:   ctx.append(f'**Key equipment:** {", ".join(key_equip)}')
        if feeds_from:  ctx.append(f'**Feeds from:** {", ".join(feeds_from)}')
        if produces_to: ctx.append(f'**Produces to:** {", ".join(produces_to)}')
        if safety_tags: ctx.append(f'**Safety devices:** {", ".join(safety_tags)}')
        if ctx:
            lines += ['## Process Context', ''] + ctx + ['']

        if eq_rows:
            lines += ['## Equipment', '']
            lines += _md_table(
                ['Tag', 'Kind', 'Description', 'Area'], eq_rows)

        if instr_rows:
            lines += ['## Instruments', '']
            lines += _md_table(
                ['Tag', 'Type', 'Equipment Ref', 'Range', 'Also On', 'HiHi', 'LoLo'], instr_rows)

        if conn_rows:
            lines += ['## Connections', '']
            lines += _md_table(
                ['Line ID', 'From', 'To', 'Fluid', 'Size'], conn_rows)

        if loop_rows:
            lines += ['## Control Loops', '']
            lines += _md_table(
                ['Loop', 'Type', 'Measurement', 'Final Element'], loop_rows)

        lines += ['## P&ID Diagram', '', '```mermaid', mermaid, '```', '']

        result[drawing_num] = '\n'.join(lines)
        index_rows.append((drawing_num, len(eq_rows), len(instr_rows), len(conn_rows)))

    # Index file
    idx_lines = [f'# {project} — Drawing Index', '']
    idx_lines += _md_table(
        ['Drawing', 'Equipment', 'Instruments', 'Connections'],
        [(f'[{d}]({d}.md)', eq, ins, cn) for d, eq, ins, cn in index_rows])

    result['_index'] = '\n'.join(idx_lines)
    return result
