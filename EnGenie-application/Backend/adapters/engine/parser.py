"""
adapters/engine/parser.py -- YMPL-schema loading and YMPL-doc -> internal
model conversion (instrument/equipment/connection assembly, loop inference).

Extracted from adapters/engine.py (Phase 10), moved verbatim.
"""
from __future__ import annotations

import re
import yaml

from .constants import SCHEMA_DIR, INSTRUMENT_KINDS, PROCESS_KINDS, MECHANICAL_KINDS, CONNECTOR_KINDS
from .tag_normalizer import is_garbage_tag, normalize_instrument_type
from .node_builder import _merge_instrument


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f'{name}_schema.yaml'
    with open(path) as f:
        return yaml.safe_load(f)


def ympl_to_internal(ympl_doc: dict, claude_enrichment: dict = None) -> dict:
    """
    Convert YMPL doc (nodes/edges) + optional Claude enrichment
    into EngineeringStudio internal model.
    Claude enrichment carries instrument parameters not in YMPL topology.
    """
    enrich = claude_enrichment or {}
    if enrich.get('instruments'):
        sample = list(enrich['instruments'].items())[:2]
        print(f'Sample instr enrich: {sample}')
    internal = {
        'metadata': enrich.get('metadata', {}),
        'instruments': {},
        'equipment': {},
        'connections': [],
        'screens': []
    }

    node_id_to_label = {n['id']: n['label'] for n in ympl_doc.get('nodes', [])}

    for node in ympl_doc.get('nodes', []):
        tag = node['label']
        kind = node['kind']

        # Filter annotation text masquerading as instrument/equipment tags
        if kind in INSTRUMENT_KINDS | PROCESS_KINDS:
            if is_garbage_tag(tag, kind=kind):
                print(f'Filtered garbage tag: {tag!r} (kind={kind})')
                continue

        if kind in INSTRUMENT_KINDS:
            enriched = enrich.get('instruments', {}).get(tag, {})
            norm_type = normalize_instrument_type(enriched.get('type', kind))
            inst = {
                'tag': tag,
                'type': norm_type,
                **{k: v for k, v in enriched.items() if k not in ('tag', 'type')}
            }
            if 'drawing' not in inst and node.get('drawing'):
                inst['drawing'] = node['drawing']
            if 'area' not in inst and node.get('area'):
                inst['area'] = node['area']
            if tag in internal['instruments']:
                internal['instruments'][tag] = _merge_instrument(internal['instruments'][tag], inst)
            else:
                internal['instruments'][tag] = inst
        elif kind in PROCESS_KINDS:
            enriched = enrich.get('equipment', {}).get(tag, {})
            equip = {
                'tag': tag,
                'type': kind,
                **{k: v for k, v in enriched.items() if k != 'tag'}
            }
            if 'drawing' not in equip and node.get('drawing'):
                equip['drawing'] = node['drawing']
            if 'area' not in equip and node.get('area'):
                equip['area'] = node['area']
            if tag in internal['equipment']:
                internal['equipment'][tag] = _merge_instrument(internal['equipment'][tag], equip)
            else:
                internal['equipment'][tag] = equip
        elif kind in MECHANICAL_KINDS:
            internal.setdefault('mechanical', {})[tag] = {
                'tag': tag,
                'type': kind,
                'drawing': node.get('drawing', '')
            }
        elif kind in CONNECTOR_KINDS:
            internal.setdefault('connectors', {})[tag] = {
                'tag': tag,
                'kind': kind,
                'drawing': node.get('drawing', '')
            }

    # Map edges to connections, merging Pass 2.5 pipe data where available
    # Build pipe lookup: (from_tag, to_tag) → enriched connection dict
    pipe_lookup: dict = {}
    for c in enrich.get('connections', []):
        key = (c.get('from_tag', ''), c.get('to_tag', ''))
        pipe_lookup[key] = c

    for i, edge in enumerate(ympl_doc.get('edges', [])):
        from_tag = node_id_to_label.get(edge['from'], edge['from'])
        to_tag   = node_id_to_label.get(edge['to'],   edge['to'])
        edge_kind = edge.get('kind', 'stream')

        if edge_kind == 'signal':
            # Signal edges stored separately — not physical pipe connections
            continue

        # Merge Pass 2.5 pipe data (from_nozzle, to_nozzle, fluid, line_size, etc.)
        enriched_conn = {k: v for k, v in pipe_lookup.get((from_tag, to_tag), {}).items()
                         if k not in ('from_tag', 'to_tag')}

        # H5: carry to_drawing for off-page edges
        if edge.get('to_drawing'):
            enriched_conn['to_drawing'] = edge['to_drawing']

        # Line designation: prefer Pass 2.5 id, fall back to edge label
        line_id = enriched_conn.pop('id', None) or edge.get('label') or f'S-{i+1:03d}'

        internal['connections'].append({
            'id': line_id,
            'from_tag': from_tag,
            'to_tag': to_tag,
            'type': 'process' if edge_kind == 'stream' else edge_kind,
            **enriched_conn
        })

    # H6: infer control/safety loops from signal edges
    internal['loops'] = _infer_loops(ympl_doc, internal)

    return internal


def _infer_loops(ympl_doc: dict, internal: dict) -> dict:
    """
    Infer control/safety loops from instrument tags (primary) and signal edges (fallback).

    Pass A — ISA-5.1 tag naming: FIC-101 → FT-101 (transmitter) + FCV-101 (valve).
             Same loop number suffix = same loop. Finds loops even when signal edges absent.
    Pass B — Signal edges: catches non-standard naming when edges are present.
    Pass C — Safety loops: switch/transmitter → valve with no DCS controller.
    """
    import re as _re

    instruments = internal.get('instruments', {})
    all_tags    = list(instruments.keys())
    nodes_by_id = {n['id']: n for n in ympl_doc.get('nodes', [])}
    label_to_id = {n['label']: n['id'] for n in ympl_doc.get('nodes', [])}

    def get_drawing(tag: str) -> str:
        n = nodes_by_id.get(label_to_id.get(tag, ''), {})
        return n.get('drawing', instruments.get(tag, {}).get('drawing', ''))

    def get_kind(tag: str) -> str:
        n = nodes_by_id.get(label_to_id.get(tag, ''), {})
        return n.get('kind', instruments.get(tag, {}).get('type', ''))

    loops: dict = {}
    _ctrl_re = _re.compile(r'^([A-Z])[A-Z]*[-_]?(\d+)[A-Z]?$')

    # ── Pass A: ISA-5.1 tag naming ─────────────────────────────────────────────
    for tag, data in instruments.items():
        if data.get('type') != 'controller':
            continue
        m = _ctrl_re.match(tag)
        if not m:
            continue
        var, num = m.group(1), m.group(2)

        # Transmitter: {var}T-{num}, {var}IT-{num}, {var}E-{num} (element)
        meas = next(
            (t for t in all_tags
             if _re.match(rf'^{var}[A-Z]?[TE][-_]?{num}[A-Z]?$', t)),
            None
        )
        # Final element: {var}V-{num}, {var}CV-{num}, {var}PV-{num}, {var}HV-{num}
        fe = next(
            (t for t in all_tags
             if _re.match(rf'^{var}[A-Z]{{0,2}}V[-_]?{num}[A-Z]?$', t)),
            None
        )
        if meas or fe:
            loops[tag] = {
                'type': 'feedback',
                'measurement': meas,
                'controller': tag,
                'final_element': fe,
                'drawing': get_drawing(tag),
                'setpoint': None, 'setpoint_units': None, 'sil_level': None,
            }

    # ── Pass B: signal edges (fallback for non-standard tag naming) ────────────
    signal_targets: dict = {}
    signal_sources: dict = {}
    for e in ympl_doc.get('edges', []):
        if e.get('kind') != 'signal':
            continue
        fl = nodes_by_id.get(e['from'], {}).get('label', '')
        tl = nodes_by_id.get(e['to'],   {}).get('label', '')
        if fl and tl:
            signal_targets.setdefault(fl, []).append(tl)
            signal_sources.setdefault(tl, []).append(fl)

    for tag, data in instruments.items():
        if data.get('type') != 'controller' or tag in loops:
            continue
        measurements = [s for s in signal_sources.get(tag, [])
                        if get_kind(s) in ('transmitter', 'element', 'analyzer')]
        final_elements = [t for t in signal_targets.get(tag, [])
                          if get_kind(t) in ('valve', 'checkvalve')]
        if not final_elements:
            continue
        loops[tag] = {
            'type': 'feedback',
            'measurement': measurements[0] if measurements else None,
            'controller': tag,
            'final_element': final_elements[0],
            'drawing': get_drawing(tag),
            'setpoint': None, 'setpoint_units': None, 'sil_level': None,
        }

    # ── Pass C: safety loops (switch/transmitter → valve, no DCS controller) ───
    for tag, data in instruments.items():
        if data.get('type') not in ('switch', 'transmitter') or tag in loops:
            continue
        for target in signal_targets.get(tag, []):
            if get_kind(target) not in ('valve', 'checkvalve'):
                continue
            if any(get_kind(s) == 'controller' for s in signal_sources.get(target, [])):
                continue
            loops[tag] = {
                'type': 'safety',
                'measurement': tag,
                'controller': None,
                'final_element': target,
                'drawing': get_drawing(tag),
                'setpoint': None, 'setpoint_units': None, 'sil_level': None,
            }
            break

    return loops
