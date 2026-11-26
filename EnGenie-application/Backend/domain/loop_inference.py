"""
domain/loop_inference.py — control-loop inference from ISA tag matching.

Extracted from main.py (Phase 4). infer_loops() is pure: given an espx dict
already in memory, it returns a new dict of loop_id -> loop record with no
side effects (no print, no mutation of the input).

Pure stdlib, no Flask/DB/adapters/services imports.
"""
from __future__ import annotations

import re


def infer_loops(espx: dict) -> dict:
    """
    Infer control loops from ISA tag number matching.
    Returns dict of loop_id -> loop record.
    Does NOT require signal edges — pure tag name matching.
    """
    instruments = espx.get('studio', {}).get('instruments', {})
    nodes       = espx.get('nodes', [])

    CONTROLLER_SUFFIXES  = {'IC', 'C', 'RC', 'AC', 'SC'}
    TRANSMITTER_SUFFIXES = {'T', 'IT', 'E'}
    VALVE_SUFFIXES       = {'CV', 'V', 'RV'}
    INDICATOR_SUFFIXES   = {'I', 'IR', 'IQ', 'G'}
    ALARM_SUFFIXES       = {'AH', 'AL', 'AHH', 'ALL',
                            'SH', 'SL', 'SHH', 'SLL'}

    def parse_tag(tag: str):
        """
        Parse ISA tag into (variable_letter, suffix, number, trailing_letter).
        ISA-5.1: first letter = measured variable; remaining = function suffix.
        e.g. FIC-047A -> ('F', 'IC', '047', 'A')
             TC-2003A -> ('T', 'C',  '2003','A')
             TCV-2003 -> ('T', 'CV', '2003','')
             PSHH-021 -> ('P', 'SHH','021', '')
        Single-letter variable group is required so that TC-2003A and TCV-2003
        both yield key (T, 2003) — trailing letter stripped from group key.
        """
        m = re.match(r'^([A-Z])([A-Z]{1,4})-(\d+)([A-Z]?)$', tag.strip())
        if not m:
            return None
        return m.group(1), m.group(2), m.group(3), m.group(4)

    # Build valve index from nodes — kind=valve, CV pattern only.
    # Control valves live in espx.nodes[], not in studio.instruments{}.
    # HV/SDV/MOV excluded — only XCV-\d+ pattern (flow-variable control valves).
    valve_nodes: dict = {}
    for node in nodes:
        # Digitised drawings and authored packages store control valves as
        # kind "control_valve"; only accepting "valve" meant no real control
        # loop could ever be reported complete.
        if node.get('kind') not in ('valve', 'control_valve'):
            continue
        label = node.get('label', '')
        if not re.match(r'^[A-Z]CV-\d+', label):
            continue
        parsed = parse_tag(label)
        if parsed:
            v, _s, num, _l = parsed
            valve_nodes[(v, num)] = label

    # Build index: (variable, number) -> {role: tag/[tags]}
    # Key uses numeric part only — trailing letter stripped so that
    # TC-2003A (number='2003', letter='A') and TCV-2003 (number='2003')
    # land in the same group.
    index = {}
    for tag in instruments:
        parsed = parse_tag(tag)
        if not parsed:
            continue
        var, suffix, number, _letter = parsed
        key = (var, number)   # trailing letter intentionally excluded
        entry = index.setdefault(key, {})

        if suffix in CONTROLLER_SUFFIXES:
            entry['controller'] = tag
        elif suffix in TRANSMITTER_SUFFIXES:
            entry['measurement'] = tag
        elif suffix in VALVE_SUFFIXES:
            entry['final_element'] = tag
        elif suffix in INDICATOR_SUFFIXES:
            entry.setdefault('indicators', []).append(tag)
        elif suffix in ALARM_SUFFIXES:
            entry.setdefault('alarms', []).append(tag)
        else:
            entry.setdefault('other', []).append(tag)

    loops = {}

    # Groups with a controller → feedback loops
    for (var, number), members in index.items():
        if 'controller' not in members:
            continue
        controller = members['controller']
        # Final element: prefer instrument dict entry, fall back to valve node
        final_el  = members.get('final_element') or valve_nodes.get((var, number))
        has_meas  = 'measurement' in members
        has_valve = final_el is not None
        if has_meas and has_valve:
            status = 'complete'
        elif has_meas or has_valve:
            status = 'incomplete'
        else:
            status = 'controller_only'

        loops[controller] = {
            'loop_id':       controller,
            'variable':      var,
            'number':        number,
            'controller':    controller,
            'measurement':   members.get('measurement'),
            'final_element': final_el,
            'indicators':    members.get('indicators', []),
            'alarms':        members.get('alarms', []),
            'other':         members.get('other', []),
            'status':        status,
            'confirmed':     False,
            'loop_type':     'feedback',
            'setpoint':      None,
            'setpoint_units': None,
            'sil_level':     None,
            'drawing':       instruments.get(controller, {}).get('drawing', ''),
        }

    # Groups with a transmitter but no controller → orphan
    for (var, number), members in index.items():
        if 'controller' in members:
            continue
        if 'measurement' not in members:
            continue
        meas     = members['measurement']
        loop_id  = f'ORPHAN-{var}{number}'
        final_el = members.get('final_element') or valve_nodes.get((var, number))
        loops[loop_id] = {
            'loop_id':       loop_id,
            'variable':      var,
            'number':        number,
            'controller':    None,
            'measurement':   meas,
            'final_element': final_el,
            'indicators':    members.get('indicators', []),
            'alarms':        members.get('alarms', []),
            'other':         members.get('other', []),
            'status':        'no_controller',
            'confirmed':     False,
            'loop_type':     None,
            'setpoint':      None,
            'setpoint_units': None,
            'sil_level':     None,
            'drawing':       instruments.get(meas, {}).get('drawing', ''),
        }

    return loops
