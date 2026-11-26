"""
adapters/engine/exporter.py -- internal-model -> VIDS YAML export.

Extracted from adapters/engine.py (Phase 10), moved verbatim.
"""
from __future__ import annotations

from .parser import load_schema


def export_vids(internal: dict) -> dict:
    """Convert internal model → VIDS YAML dict using schema mapping."""
    schema = load_schema('vids')
    output = {
        'metadata': {},
        'instruments': {},
        'equipment': {},
        'connections': [],
        'screens': []
    }

    # Metadata
    meta = internal.get('metadata', {})
    for field in schema['sections']['metadata']['fields']:
        val = meta.get(field['internal'])
        if val is not None:
            output['metadata'][field['target']] = val

    # Instruments
    for tag, data in internal.get('instruments', {}).items():
        entry = {}
        for field in schema['sections']['instruments']['fields']:
            val = data.get(field['internal'])
            if val is not None:
                entry[field['target']] = val
                if field.get('annotation'):
                    entry[f"_review_{field['target']}"] = field['annotation']
        if entry:
            output['instruments'][tag] = entry

    # Equipment
    for tag, data in internal.get('equipment', {}).items():
        entry = {}
        for field in schema['sections']['equipment']['fields']:
            val = data.get(field['internal'])
            if val is not None:
                entry[field['target']] = val
        if entry:
            output['equipment'][tag] = entry

    # Connections
    for conn in internal.get('connections', []):
        entry = {}
        for field in schema['sections']['connections']['fields']:
            val = conn.get(field['internal'])
            if val is not None:
                entry[field['target']] = val
        if entry:
            output['connections'].append(entry)

    # Screens
    output['screens'] = internal.get('screens', [])

    return output
