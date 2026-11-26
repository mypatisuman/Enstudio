"""
ympl_parser/convert.py — VIDS → YMPL conversion
"""
from __future__ import annotations


KIND_TO_TYPE: dict[str, str] = {
    'vessel':       'flash_vessel',
    'reactor':      'reactor',
    'heat_exchanger': 'heat_exchanger',
    'compressor':   'compressor',
    'pump':         'pump',
    'column':       'distillation_column',
    'absorber':     'packed_absorber',
    'separator':    'flash_vessel',
    'filter':       'flash_vessel',
    'fired_heater': 'fired_heater',
    'meter':        'pipe_segment',
}


def vids_to_ympl(vids: dict) -> dict:
    """
    Convert VIDS (Engineering Studio native format) to YMPL.

    VIDS structure:
      equipment:   {tag: {type, area, description}}
      instruments: {tag: {type, equipment_ref, range_hi, units}}
      connections: [{from_tag, to_tag, id, type, fluid}]
      metadata:    {plant_name, revision, changelog, date}

    YMPL structure:
      schema_version, id, title, nodes, edges, meta, enable
    """
    equipment   = vids.get('equipment', {})
    instruments = vids.get('instruments', {})
    connections = vids.get('connections', [])
    metadata    = vids.get('metadata', {})

    process_tags = set(equipment.keys())

    # ── nodes from equipment ────────────────────────────────────────────────────
    nodes: list[dict] = []
    label_to_id: dict[str, str] = {}
    for i, (tag, eq) in enumerate(equipment.items(), 1):
        node_id = f'n{i}'
        label_to_id[tag] = node_id
        kind = eq.get('type', 'vessel')
        nodes.append({
            'id':    node_id,
            'label': tag,
            'kind':  kind,
            'area':  eq.get('area', ''),
        })

    # ── edges: process-equipment endpoints only ─────────────────────────────────
    edges: list[dict] = []
    seen: set[tuple] = set()
    for conn in connections:
        from_tag = conn.get('from_tag', '')
        to_tag   = conn.get('to_tag',   '')
        if from_tag not in process_tags or to_tag not in process_tags:
            continue
        from_id = label_to_id.get(from_tag)
        to_id   = label_to_id.get(to_tag)
        if not from_id or not to_id:
            continue
        key = (from_id, to_id)
        if key in seen:
            continue
        seen.add(key)
        edge: dict = {'from': from_id, 'to': to_id, 'kind': 'stream'}
        if conn.get('id'):
            edge['label'] = conn['id']
        if conn.get('fluid'):
            edge['fluid'] = conn['fluid']
        edges.append(edge)

    # ── enable.equipment ────────────────────────────────────────────────────────
    enable_equipment: dict = {}
    for tag, eq in equipment.items():
        eq_type = KIND_TO_TYPE.get(eq.get('type', 'vessel'), 'flash_vessel')
        enable_equipment[tag] = {
            'topology_ref': label_to_id[tag],
            'type':         eq_type,
            'area':         eq.get('area', ''),
        }

    # ── enable.instruments ──────────────────────────────────────────────────────
    enable_instruments: dict = {}
    for tag, inst in instruments.items():
        entry: dict = {
            'type':           inst.get('type', 'transmitter'),
            'equipment_ref':  inst.get('equipment_ref'),
            'state_index':    None,
            'state_variable': None,
            'fail_mode':      'last_value',
        }
        # range_lo matters as much as range_hi: a 4-20mA transmitter scaled
        # 50-250 degC is not the same instrument as one scaled 0-250, and
        # carrying only the top of the span silently makes them identical.
        if inst.get('range_lo') is not None:
            entry['range_lo'] = inst['range_lo']
        if inst.get('range_hi') is not None:
            entry['range_hi'] = inst['range_hi']
        if inst.get('units'):
            entry['units'] = inst['units']
        enable_instruments[tag] = entry

    # ── assemble output ─────────────────────────────────────────────────────────
    plant_name = metadata.get('plant_name', 'plant')
    return {
        'schema_version': 'ympl-1.0',
        'id':             plant_name.lower().replace(' ', '_'),
        'title':          plant_name,
        'nodes':          nodes,
        'edges':          edges,
        'meta': {
            'confidence':   'high',
            'source_text':  f'Converted from VIDS revision {metadata.get("revision", 1)}',
            'vids_date':    metadata.get('date', ''),
            'vids_revision': metadata.get('revision', 1),
        },
        'enable': {
            'equipment':   enable_equipment,
            'instruments': enable_instruments,
        },
    }
