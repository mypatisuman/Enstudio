"""
adapters/engine/node_builder.py -- P&ID node classification (ISA layer,
category, measured variable) and bounding-box derivation.

Extracted from adapters/engine.py (Phase 10), moved verbatim.
"""
from __future__ import annotations

import re

from .constants import INSTRUMENT_KINDS, PROCESS_KINDS, _KIND_TO_CLASS
from .tag_normalizer import _check_tag_quality, _extract_prefix, _is_physical, _isa_decode


def derive_bbox(node: dict,
                page_w_px: int,
                page_h_px: int,
                layout_rules: dict,
                dpi: int = 300,
                company_profile: dict | None = None) -> dict:
    """Derive a pixel bounding box for a node from its centroid + kind, using
    symbol sizes/shapes/mask padding declared in Part 5 of the layout YAML.

    The function is pure: it never reads files. ``layout_rules`` must already
    be the merged dict produced by SkillRegistry.get_layout_rules().

    Lookup priority for size/shape/mask_padding:
      1. ``company_profile['symbol_geometry'][kind]`` if present
      2. ``layout_rules['equipment']`` keys keyed by kind match
      3. ``layout_rules['instruments']`` bubble fields (instrument kinds)

    Returns ``{x1, y1, x2, y2, shape, source: 'rule_derived'}``.
    """
    kind = (node.get('kind') or '').lower()
    eq = (layout_rules or {}).get('equipment') or {}
    inst_block = (layout_rules or {}).get('instruments') or {}

    # ── Resolve kind → equipment-key (matches Part 5 prefix names) ─────────
    if 'vessel' in kind or 'tank' in kind:
        kind_key = 'vessel'
    elif 'hx' in kind or 'exchanger' in kind or 'heat' in kind:
        kind_key = 'hx'
    elif 'pump' in kind:
        kind_key = 'pump'
    elif 'comp' in kind:
        kind_key = 'compressor'
    elif 'reactor' in kind or 'cstr' in kind:
        kind_key = 'reactor'
    elif 'filter' in kind:
        kind_key = 'filter'
    elif kind in INSTRUMENT_KINDS:
        kind_key = '__instrument__'
    elif 'valve' in kind:
        kind_key = 'valve'
    else:
        kind_key = 'vessel'  # default fallback

    # ── Resolve geometry: company override → instrument bubble → equipment ─
    sym_geom = ((company_profile or {}).get('symbol_geometry') or {}).get(kind)
    if sym_geom:
        size  = sym_geom.get('size', [80, 60])
        shape = sym_geom.get('shape', 'rectangle')
        mask_padding = sym_geom.get('mask_padding', 12)
    elif kind_key == '__instrument__':
        diam  = inst_block.get('bubble_diameter', 30)
        size  = [diam, diam]
        shape = inst_block.get('bubble_shape', 'circle')
        mask_padding = inst_block.get('bubble_mask_padding', 6)
    else:
        size  = eq.get(f'{kind_key}_size', [80, 60])
        shape = eq.get(f'{kind_key}_shape', 'rectangle')
        mask_padding = eq.get(f'{kind_key}_mask_padding', 12)

    w, h = size[0], size[1]

    # ── Apply DPI scale and compute extents ───────────────────────────────
    scale = dpi / 300.0
    cx = float(node.get('x', 0.5)) * page_w_px
    cy = float(node.get('y', 0.5)) * page_h_px

    if shape == 'circle' and kind_key == '__instrument__':
        diam = inst_block.get('bubble_diameter', 30)
        hw = hh = (diam * scale) / 2.0
    elif shape == 'circle':
        hw = hh = (w * scale) / 2.0
    else:  # rectangle, diamond
        hw = (w * scale) / 2.0
        hh = (h * scale) / 2.0

    pad = mask_padding * scale
    return {
        'x1': cx - hw - pad,
        'y1': cy - hh - pad,
        'x2': cx + hw + pad,
        'y2': cy + hh + pad,
        'shape': shape,
        'source': 'rule_derived',
    }


def classify_node(tag: str, kind: str, conventions=None,
                  node: dict | None = None,
                  layout_rules: dict | None = None,
                  page_w_px: int = 1400,
                  page_h_px: int = 800,
                  dpi: int = 300,
                  company_profile: dict | None = None) -> dict:
    """Classify a P&ID node and optionally attach a derived bbox.

    When both ``node`` and ``layout_rules`` are provided, the result also
    carries ``bbox`` derived via :func:`derive_bbox`. Backward compatible:
    callers that omit them get the same dict shape as before.
    """
    result = _classify_node_core(tag, kind, conventions)
    if node is not None and layout_rules is not None:
        result['bbox'] = derive_bbox(
            node, page_w_px, page_h_px, layout_rules,
            dpi=dpi, company_profile=company_profile,
        )
    return result


def _classify_node_core(tag: str, kind: str, conventions=None) -> dict:
    """
    Classify a P&ID node per pid-digitization-framework.md §4.

    Priority: tag quality → company conventions → ISA decode → kind fallback → default.
    Returns fields added to every editor node: pid_layer, category,
    measured_variable, function, valve_layer, quality, loop_number.
    """
    result: dict = {
        'pid_layer': 1,
        'category': 'equipment',
        'measured_variable': None,
        'function': None,
        'valve_layer': None,
        'quality': 'ok',
        'loop_number': None,
        'physical': True,
    }

    # Quality gate — all non-ok qualities produce non-physical flagged nodes
    quality = _check_tag_quality(tag)
    result['quality'] = quality
    if quality != 'ok':
        result['pid_layer'] = 0
        result['category'] = 'flagged'
        result['physical'] = False
        return result

    # Loop number
    lm = re.search(r'(\d+)', tag)
    if lm:
        result['loop_number'] = lm.group(1)

    prefix = _extract_prefix(tag)

    # Physical check — alarms, relays, and operator outputs have no P&ID symbol
    if not _is_physical(prefix):
        result['physical'] = False
        result['pid_layer'] = 0
        return result

    # Gas cylinder utility supply (N2-cyl, O2-cyl, etc.) — physical but utility category
    if re.match(r'^[A-Z]\d[-_]?CYL', tag.upper()):
        result['category'] = 'utility_supply'
        result['pid_layer'] = 1
        return result

    # Automation notes (HE-AUTO, AUTO-xxx) — appear on drawings but have no P&ID symbol
    if re.search(r'[-_]AUTO\b', tag.upper()) or re.match(r'^AUTO[-_]', tag.upper()):
        result['physical'] = False
        result['pid_layer'] = 0
        return result

    # Step 1: Company conventions (instrument kind = layer 2; equipment/valve via kind_map)
    if conventions:
        # Valve layer from conventions (returns default 'ctrl_valves' if unknown)
        conv_valve_layer = conventions.get_valve_layer(tag)
        # Only trust conventions valve classification when prefix is in the conventions map
        conv_maps = conventions.client_maps()
        valve_layers = conv_maps.get('valve_layers', {})
        equip_kinds  = conv_maps.get('equipment_kinds', {})

        if prefix in valve_layers:
            vl = valve_layers[prefix]
            layer_to_pid = {
                'ctrl_valves': 1, 'hand_valves': 3,
                'check_valves': 3, 'relief_valves': 4, 'isolation': 3,
            }
            result['pid_layer'] = layer_to_pid.get(vl, 1)
            result['category'] = (
                'control_valve' if vl == 'ctrl_valves' else
                'check_valve'   if vl == 'check_valves' else
                'relief_valve'  if vl == 'relief_valves' else
                'isolation_valve'
            )
            result['valve_layer'] = vl
            return result

        if prefix in equip_kinds:
            # Equipment kind known from conventions — layer 1 equipment
            result['pid_layer'] = 1
            result['category'] = 'equipment'
            return result

        # Step 1c: Company-specific instrument prefix (HT, JE, JT, RT, ...)
        # Conventions return {category, variable, expects_controller}; missing
        # → fall through to ISA decode.
        instr_cat = conventions.get_instrument_category(tag)
        if instr_cat:
            result['pid_layer']         = 2
            result['category']          = instr_cat['category']
            result['measured_variable'] = instr_cat.get('variable') or result['measured_variable']
            result['expects_controller']= instr_cat.get('expects_controller', True)
            return result

    # Step 2: ISA decode
    isa = _isa_decode(prefix)
    if isa:
        result.update(isa)
        # Instrument kinds in extraction override ISA if extraction says transmitter/controller
        if kind in INSTRUMENT_KINDS and isa.get('pid_layer') != 2:
            kc = _KIND_TO_CLASS.get(kind)
            if kc:
                result['pid_layer'] = kc[1]
                result['category']  = kc[0]
        return result

    # Step 3: Kind field from extraction
    if kind:
        kc = _KIND_TO_CLASS.get(kind)
        if kc:
            result['pid_layer'] = kc[1]
            result['category']  = kc[0]
            if kc[1] == 1 and kc[0] == 'control_valve':
                result['valve_layer'] = 'ctrl_valves'
            return result
        if kind in INSTRUMENT_KINDS:
            result['pid_layer'] = 2
            result['category']  = kind
            return result
        if kind in PROCESS_KINDS:
            result['pid_layer'] = 1
            result['category']  = 'equipment'
            return result

    # Step 4: Default — unrecognised = equipment layer 1
    return result


def _merge_instrument(existing: dict, new: dict) -> dict:
    """Keep whichever dict has more non-null fields; record cross-sheet appearances."""
    existing_score = sum(1 for v in existing.values() if v is not None and v != '')
    new_score      = sum(1 for v in new.values()      if v is not None and v != '')
    winner = new if new_score > existing_score else existing
    loser  = existing if winner is new else new
    all_drawings = {d for d in [winner.get('drawing', ''), loser.get('drawing', '')] if d}
    winner['also_on'] = sorted(all_drawings - {winner.get('drawing', '')})
    return winner
