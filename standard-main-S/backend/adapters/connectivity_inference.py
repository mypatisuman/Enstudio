"""
connectivity_inference.py — Pass 4 signal-edge inference

Many extracted instrument nodes have no signal edges (in CTP: 23 / 358).
Without signals the editor cannot place them on a parent equipment spoke
and the loop-completeness QA flags them as orphans. This module proposes
the missing signal edges from four progressively-weaker signals:

    Priority 1  equipment_ref   (auto,      0.95)
    Priority 2  loop number     (uncertain, 0.85)
    Priority 3  area + kind     (inferred,  0.70)
    Priority 4  proximity only  (inferred,  0.50)

A separate pass also handles control valves via loop-number matching only
(``loop_number_valve``, 0.85). Proximity / area fallbacks are intentionally
NOT used for valves — valve placement is too sensitive for those weaker
signals.

Public API:
    infer_connections(nodes, edges, studio)        -> list[dict]
    run_connectivity_inference(nodes, edges, studio) -> dict

The functions never mutate their inputs.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Optional, Tuple

from adapters.engine import INSTRUMENT_KINDS, PROCESS_KINDS


# Only true instruments participate in the main signal-source pass. Control
# valves are handled by a dedicated pass below (loop-number-only matching).
_SIGNAL_SOURCES = set(INSTRUMENT_KINDS)

# Control-valve-like kinds. The extractor produces both bare 'valve' and the
# normalised 'control_valve' label depending on whether ISA decoding fired.
_VALVE_LIKE_KINDS = {'valve', 'control_valve'}

# Thresholds (in normalised 0–1 coords as stored in the espx)
_AREA_PROX_MAX_DIST  = 0.30
_GLOBAL_PROX_MAX_DIST = 0.20

# Proposals with confidence below this are dropped from the returned list
# and counted under stats['below_threshold'] instead. The proximity tier
# (0.50) lives below this line — too weak to be acted on by an engineer
# without further evidence, but still useful as a stat.
_PROPOSAL_MIN_CONFIDENCE = 0.70


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kind(node: dict) -> str:
    return (node.get('kind') or '').lower()


def _is_signal_source(node: dict) -> bool:
    return _kind(node) in _SIGNAL_SOURCES


def _is_equipment(node: dict) -> bool:
    return _kind(node) in PROCESS_KINDS


def _is_signal_edge(edge: dict) -> bool:
    return (edge.get('kind') or edge.get('connType') or '').lower() == 'signal'


def _loop_number(label: str) -> Optional[str]:
    m = re.search(r'(\d+)', label or '')
    return m.group(1) if m else None


def _xy(node: dict) -> Tuple[float, float]:
    """Best-effort numeric (x, y); falls back to (0, 0) for None / non-numeric."""
    try:
        return float(node.get('x', 0) or 0), float(node.get('y', 0) or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0


def _dist(a: dict, b: dict) -> float:
    ax, ay = _xy(a)
    bx, by = _xy(b)
    return math.hypot(ax - bx, ay - by)


def _index_signal_endpoints(edges: List[dict]) -> set:
    seen: set = set()
    for e in edges:
        if _is_signal_edge(e):
            if e.get('from'): seen.add(e['from'])
            if e.get('to'):   seen.add(e['to'])
    return seen


def _equipment_ref_for(node: dict, studio: dict) -> str:
    """Read equipment_ref directly from the node, falling back to
    studio.instruments[<tag>]."""
    if node.get('equipment_ref'):
        return str(node['equipment_ref']).strip()
    tag = node.get('tag') or node.get('label') or ''
    if not tag:
        return ''
    instr = ((studio or {}).get('instruments') or {}).get(tag) or {}
    return str(instr.get('equipment_ref') or '').strip()


def _build_label_to_node(nodes: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for n in nodes:
        lbl = (n.get('label') or n.get('tag') or '').strip().upper()
        if lbl and lbl not in out:
            out[lbl] = n
    return out


# ── Per-priority resolvers ────────────────────────────────────────────────────

def _try_equipment_ref(node: dict, label_index: Dict[str, dict],
                       studio: dict) -> Optional[dict]:
    ref = _equipment_ref_for(node, studio)
    if not ref:
        return None
    target = label_index.get(ref.upper())
    if target is None or not _is_equipment(target):
        return None
    if target['id'] == node['id']:
        return None
    return {
        'from':         node['id'],
        'to':           target['id'],
        'kind':         'signal',
        'confidence':   0.95,
        'method':       'equipment_ref',
        'review_state': 'auto',
    }


# ISA pairing rules used for priority 2 — same loop number, same area, listed
# in preference order. Unknown kinds fall back to "any equipment".
_LOOP_PAIR_PREFERENCES = {
    'transmitter': ('equipment',),
    'controller':  ('transmitter', 'equipment'),
    'indicator':   ('transmitter', 'equipment'),
    'recorder':    ('transmitter', 'equipment'),
    'switch':      ('equipment',),
    'analyzer':    ('equipment',),
    'element':     ('equipment',),
    'valve':       ('controller', 'equipment'),
}


def _try_loop_number(node: dict, nodes: List[dict]) -> Optional[dict]:
    loop = _loop_number(node.get('label') or node.get('tag') or '')
    if not loop:
        return None
    area = node.get('area') or ''
    same_loop = [n for n in nodes
                 if n.get('id') != node['id']
                 and (n.get('area') or '') == area
                 and _loop_number(n.get('label') or n.get('tag') or '') == loop]
    if not same_loop:
        return None

    prefs = _LOOP_PAIR_PREFERENCES.get(_kind(node), ('equipment',))

    def _matches(role: str, n: dict) -> bool:
        if role == 'equipment':
            return _is_equipment(n)
        return _kind(n) == role

    target = None
    for role in prefs:
        # Within a role, pick the closest by xy so we don't randomly snap to
        # an instrument across the sheet.
        candidates = [n for n in same_loop if _matches(role, n)]
        if not candidates:
            continue
        candidates.sort(key=lambda n: _dist(node, n))
        target = candidates[0]
        break

    if target is None:
        return None
    return {
        'from':         node['id'],
        'to':           target['id'],
        'kind':         'signal',
        'confidence':   0.85,
        'method':       'loop_number',
        'review_state': 'uncertain',
    }


def _try_area_kind(node: dict, nodes: List[dict]) -> Optional[dict]:
    area = node.get('area') or ''
    if not area:
        return None
    candidates = [n for n in nodes
                  if _is_equipment(n) and (n.get('area') or '') == area]
    if not candidates:
        return None
    candidates.sort(key=lambda n: _dist(node, n))
    target = candidates[0]
    if _dist(node, target) > _AREA_PROX_MAX_DIST:
        return None
    return {
        'from':         node['id'],
        'to':           target['id'],
        'kind':         'signal',
        'confidence':   0.70,
        'method':       'area_kind',
        'review_state': 'inferred',
    }


def _try_proximity(node: dict, nodes: List[dict]) -> Optional[dict]:
    candidates = [n for n in nodes if _is_equipment(n) and n['id'] != node['id']]
    if not candidates:
        return None
    candidates.sort(key=lambda n: _dist(node, n))
    target = candidates[0]
    if _dist(node, target) > _GLOBAL_PROX_MAX_DIST:
        return None
    return {
        'from':         node['id'],
        'to':           target['id'],
        'kind':         'signal',
        'confidence':   0.50,
        'method':       'proximity',
        'review_state': 'inferred',
    }


def _try_loop_number_valve(cv_node: dict,
                           nodes: List[dict]) -> Optional[dict]:
    """Connect a control valve to its loop's controller (or transmitter as a
    fallback) via shared loop number. Signal edge: cv → controller, encoding
    the setpoint that drives the valve.

    Priority within the resolver:
      1. Controller in the same loop.
      2. Transmitter in the same loop.
    Same-area candidates are preferred; ties broken by closest xy.
    Confidence 0.85, ``review_state='uncertain'``.
    """
    loop = _loop_number(cv_node.get('label') or cv_node.get('tag') or '')
    if not loop:
        return None

    area = cv_node.get('area') or ''

    def _same_loop(target_kind: str) -> List[dict]:
        return [n for n in nodes
                if n.get('id') != cv_node['id']
                and _kind(n) == target_kind
                and _loop_number(n.get('label') or n.get('tag') or '') == loop]

    candidates = _same_loop('controller') or _same_loop('transmitter')
    if not candidates:
        return None

    same_area = [n for n in candidates if (n.get('area') or '') == area]
    pool = same_area if same_area else candidates
    pool.sort(key=lambda n: _dist(cv_node, n))
    target = pool[0]

    return {
        'from':         cv_node['id'],
        'to':           target['id'],
        'kind':         'signal',
        'confidence':   0.85,
        'method':       'loop_number_valve',
        'review_state': 'uncertain',
    }


# ── Public API ────────────────────────────────────────────────────────────────

def infer_connections(nodes: List[dict],
                      edges: List[dict],
                      studio: Optional[dict] = None) -> List[dict]:
    """Walk every signal-source node that has zero existing signal edges and
    return one proposal per node (the first priority that fires).

    A second pass handles control valves via loop-number matching only.
    """
    studio = studio or {}
    signal_endpoints = _index_signal_endpoints(edges)
    label_index = _build_label_to_node(nodes)

    proposals: List[dict] = []
    for node in nodes:
        if not _is_signal_source(node):
            continue
        if node.get('id') in signal_endpoints:
            continue  # already has a signal edge — nothing to do

        for resolver in (
            lambda n: _try_equipment_ref(n, label_index, studio),
            lambda n: _try_loop_number(n, nodes),
            lambda n: _try_area_kind(n, nodes),
            lambda n: _try_proximity(n, nodes),
        ):
            result = resolver(node)
            if result:
                proposals.append(result)
                break

    # ── Valve pass: loop-number matching only ─────────────────────────────
    for node in nodes:
        if _kind(node) not in _VALVE_LIKE_KINDS:
            continue
        if node.get('id') in signal_endpoints:
            continue
        result = _try_loop_number_valve(node, nodes)
        if result:
            proposals.append(result)

    return proposals


def run_connectivity_inference(nodes: List[dict],
                               edges: List[dict],
                               studio: Optional[dict] = None) -> dict:
    """Top-level entry. Returns a stats-bearing dict. Read-only — never
    mutates `nodes` or `edges`.

    Proposals with confidence below ``_PROPOSAL_MIN_CONFIDENCE`` (0.70) are
    excluded from the returned ``proposals`` list and rolled up under
    ``stats['below_threshold']`` instead.
    """
    raw = infer_connections(nodes, edges, studio)

    proposals = [p for p in raw if p['confidence'] >= _PROPOSAL_MIN_CONFIDENCE]
    below_threshold = len(raw) - len(proposals)

    by_method = {'equipment_ref': 0, 'loop_number': 0,
                 'area_kind': 0, 'proximity': 0,
                 'loop_number_valve': 0}
    for p in proposals:
        if p['method'] in by_method:
            by_method[p['method']] += 1

    signal_endpoints = _index_signal_endpoints(edges)
    unconnected_signal_sources = [
        n for n in nodes
        if _is_signal_source(n) and n.get('id') not in signal_endpoints
    ]
    n_unconnected = len(unconnected_signal_sources)

    # ── Valve roll-up (separate from instrument count) ────────────────────
    unconnected_valves = [
        n for n in nodes
        if _kind(n) in _VALVE_LIKE_KINDS and n.get('id') not in signal_endpoints
    ]
    n_unconn_valves = len(unconnected_valves)
    proposed_valves = sum(1 for p in proposals
                           if p['method'] == 'loop_number_valve')
    proposed_instruments = len(proposals) - proposed_valves

    return {
        'proposals': proposals,
        'stats': {
            'unconnected_instruments': n_unconnected,
            'unconnected_valves':      n_unconn_valves,
            'proposed':                len(proposals),
            'proposed_valves':         proposed_valves,
            'by_method':               by_method,
            'below_threshold':         below_threshold,
            # spec spelling preserved
            'unproposeble':            n_unconnected - proposed_instruments - below_threshold,
        },
    }
