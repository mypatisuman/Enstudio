import yaml
from pathlib import Path
from adapters.engine import load_schema, INSTRUMENT_KINDS, MECHANICAL_KINDS, CONNECTOR_KINDS

# Issue 1: only these kinds are valid connection endpoints in enableSim
PROCESS_CONN_KINDS = {
    'vessel', 'reactor', 'heat_exchanger', 'compressor', 'pump',
    'column', 'absorber', 'separator', 'filter', 'fired_heater',
    'storage_tank', 'flash_vessel', 'pressure_vessel',
    'pipe_segment', 'mixer'
}

# Issue 2: map YMPL kinds to enableSim equipment types
ENABLESIM_TYPE_MAP = {
    'meter':        'pipe_segment',
    'separator':    'flash_vessel',
    'storage_tank': 'storage_tank',
    'vessel':       'storage_tank',
}

# Issue 2: skip these from enable.equipment entirely
ENABLESIM_SKIP_KINDS = {
    'checkvalve', 'indicator', 'transmitter', 'controller',
    'switch', 'analyzer', 'element', 'recorder',
    'off_page_connector', 'valve', 'relief'
}


def to_enablesim_ympl(ympl_doc: dict, mermaid: str = '',
                      instruments: dict | None = None) -> dict:
    """
    Enrich YMPL topology for enableSim.
    Adds topology_ref, port assumptions, default instrument wiring.
    NEVER writes Perry physics params or enable.matrix (D-021, D-022).

    `instruments` is the studio instrument detail keyed by tag. Nodes carry
    only topology (label/kind/x/y), so calibrated range and units have to be
    passed in separately or they never reach enableSim. Ranges are measurement
    calibration read off the drawing, not Perry physics, so D-021/D-022 do not
    apply to them.
    """
    schema = load_schema('ympl')
    port_rules     = schema.get('port_rules', {})
    instr_defaults = schema.get('instrument_defaults', {})
    default_ports  = port_rules.get('default', {'default_in': 'inlet', 'default_out': 'outlet'})

    nodes = ympl_doc.get('nodes', [])
    node_map  = {n['id']: n for n in nodes}
    node_kind = {n['id']: n.get('kind', '') for n in nodes}
    # Issue 3: label → node_id for unique topology_ref lookup
    label_to_node = {n['label']: n['id'] for n in nodes}

    output = {
        'schema_version': 'ympl-1.0',
        'id': ympl_doc.get('id', 'plant'),
        'title': ympl_doc.get('title', 'Plant'),
        'nodes': nodes,
        'edges': ympl_doc.get('edges', []),
        'meta': {
            **ympl_doc.get('meta', {}),
            'mermaid': mermaid
        },
        'enable': {
            'equipment': {},
            'connections': {},
            'instruments': {}
        }
    }

    for node in nodes:
        tag  = node['label']
        kind = node['kind']

        if kind in INSTRUMENT_KINDS:
            entry = {
                'type':           kind,
                'state_variable': instr_defaults.get('state_variable', 'x'),
                'state_index':    instr_defaults.get('state_index', 0),
                'fail_mode':      instr_defaults.get('fail_mode', 'last')
            }
            # Measurement range + units, when the drawing gave us any. Omitted
            # rather than written as null so enableSim can tell "not on the
            # drawing" from "calibrated to zero".
            detail = (instruments or {}).get(tag) or {}
            for field in ('range_lo', 'range_hi', 'units'):
                if detail.get(field) is not None:
                    entry[field] = detail[field]
            output['enable']['instruments'][tag] = entry
        elif kind in ENABLESIM_SKIP_KINDS | MECHANICAL_KINDS | CONNECTOR_KINDS:
            pass  # topology only — not in enableSim equipment or instruments
        else:
            # Issue 3: resolve topology_ref via label lookup; skip duplicates
            correct_node_id = label_to_node.get(tag)
            if not correct_node_id:
                print(f'WARN: no node found for equipment tag {tag}')
                continue
            if tag in output['enable']['equipment']:
                print(f'WARN: duplicate equipment tag {tag}, skipping')
                continue
            mapped_type = ENABLESIM_TYPE_MAP.get(kind, kind)
            output['enable']['equipment'][tag] = {
                'topology_ref': correct_node_id,
                'type': mapped_type
                # Perry defaults injected by enable build (D-022)
            }

    # Issue 1: connections only between process equipment endpoints
    for edge in ympl_doc.get('edges', []):
        if edge.get('kind') == 'signal':
            continue

        from_kind = node_kind.get(edge['from'], '')
        to_kind   = node_kind.get(edge['to'],   '')

        if from_kind not in PROCESS_CONN_KINDS:
            continue
        if to_kind not in PROCESS_CONN_KINDS:
            continue

        from_node  = node_map.get(edge['from'], {})
        to_node    = node_map.get(edge['to'],   {})
        from_label = from_node.get('label', edge['from'])
        to_label   = to_node.get('label',   edge['to'])

        from_rules = port_rules.get(from_kind, default_ports)
        to_rules   = port_rules.get(to_kind,   default_ports)

        stream_id = edge.get('label') or f'{from_label}-{to_label}'

        output['enable']['connections'][stream_id] = {
            'from': f"{from_label}.{from_rules.get('default_out', 'outlet')}",
            'to':   f"{to_label}.{to_rules.get('default_in', 'inlet')}",
            'type': edge.get('kind', 'stream'),
            'flow': 0.0  # engineer fills after enable build
        }

    # Issue 4: validate unique topology_refs before returning
    used_refs = {}
    for tag, eq in output['enable']['equipment'].items():
        ref = eq.get('topology_ref')
        if ref in used_refs:
            print(f'WARN: topology_ref {ref} collision: {used_refs[ref]} and {tag}')
        else:
            used_refs[ref] = tag

    return output
