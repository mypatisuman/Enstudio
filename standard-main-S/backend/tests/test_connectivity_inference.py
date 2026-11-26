"""Pass 4 connectivity-inference tests."""

from __future__ import annotations

import sys
from pathlib import Path

_STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(_STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(_STUDIO_DIR))

from adapters.connectivity_inference import (   # noqa: E402
    infer_connections, run_connectivity_inference,
)


def _node(nid, kind, label='', area='', x=0.5, y=0.5, **extra):
    n = {'id': nid, 'kind': kind, 'label': label, 'area': area, 'x': x, 'y': y}
    n.update(extra)
    return n


# ── Priority 1: equipment_ref direct match (auto) ─────────────────────────────

def test_equipment_ref_direct_match_auto():
    nodes = [
        _node('e1', 'vessel',     label='V-101', area='REACTOR',
              x=0.5, y=0.5),
        # Unconnected transmitter explicitly references V-101
        _node('i1', 'transmitter', label='LT-101', area='REACTOR',
              x=0.5, y=0.6, equipment_ref='V-101'),
    ]
    proposals = infer_connections(nodes, [], studio={})
    assert len(proposals) == 1
    p = proposals[0]
    assert p['from']         == 'i1'
    assert p['to']           == 'e1'
    assert p['kind']         == 'signal'
    assert p['method']       == 'equipment_ref'
    assert p['review_state'] == 'auto'
    assert p['confidence']   >= 0.9


def test_equipment_ref_via_studio_instruments():
    """If equipment_ref isn't on the node, fall back to studio.instruments."""
    nodes = [
        _node('e1', 'vessel',      label='V-101', area='REACTOR'),
        _node('i1', 'transmitter', label='LT-101', area='REACTOR'),
    ]
    studio = {'instruments': {'LT-101': {'equipment_ref': 'V-101'}}}
    proposals = infer_connections(nodes, [], studio=studio)
    assert len(proposals) == 1
    assert proposals[0]['method']       == 'equipment_ref'
    assert proposals[0]['review_state'] == 'auto'


# ── Priority 2: loop number match (uncertain) ─────────────────────────────────

def test_loop_number_match_controller_to_transmitter_uncertain():
    """FTC-3503 (controller, unconnected) pairs with FT-3503 (transmitter)
    in the same area — same loop number 3503 → uncertain proposal."""
    nodes = [
        _node('t1', 'transmitter', label='FT-3503', area='REACTOR',
              x=0.5, y=0.5),
        _node('c1', 'controller',  label='FTC-3503', area='REACTOR',
              x=0.5, y=0.7),
    ]
    # FT-3503 is also unconnected, but its preferred pair role is "equipment".
    # There is no equipment in this scene, so it can't propose anything via
    # loop_number. We focus on the controller, which prefers a transmitter.
    proposals = infer_connections(nodes, [], studio={})
    by_src = {p['from']: p for p in proposals}
    assert 'c1' in by_src, 'controller should produce a loop_number proposal'
    cp = by_src['c1']
    assert cp['to']           == 't1'
    assert cp['method']       == 'loop_number'
    assert cp['review_state'] == 'uncertain'
    assert abs(cp['confidence'] - 0.85) < 1e-6


def test_loop_number_transmitter_pairs_with_equipment():
    """Transmitter rule: prefer equipment in same loop."""
    nodes = [
        _node('e1', 'vessel',      label='V-3503', area='REACTOR'),
        _node('c1', 'controller',  label='FTC-3503', area='REACTOR'),
        _node('t1', 'transmitter', label='FT-3503', area='REACTOR'),
    ]
    proposals = infer_connections(nodes, [], studio={})
    p = next(p for p in proposals if p['from'] == 't1')
    assert p['to']     == 'e1'
    assert p['method'] == 'loop_number'


# ── Priority 3: area + kind + proximity (inferred) ────────────────────────────

def test_area_kind_proximity_match_inferred():
    """No matching loop number, but only one piece of equipment in the same
    area within the proximity threshold."""
    nodes = [
        _node('e1', 'vessel',      label='V-201', area='SEPARATOR',
              x=0.5, y=0.5),
        _node('i1', 'transmitter', label='LT-999', area='SEPARATOR',
              x=0.55, y=0.55),  # ~0.07 away
    ]
    proposals = infer_connections(nodes, [], studio={})
    assert len(proposals) == 1
    p = proposals[0]
    assert p['from']         == 'i1'
    assert p['to']           == 'e1'
    assert p['method']       == 'area_kind'
    assert p['review_state'] == 'inferred'


def test_area_kind_skipped_when_too_far():
    """Same area but distance exceeds the area threshold → no area_kind
    proposal. (Falls through to proximity, which has a stricter 0.20 cap and
    so will also fail in this case.)"""
    nodes = [
        _node('e1', 'vessel',      label='V-201', area='SEPARATOR',
              x=0.0, y=0.0),
        _node('i1', 'transmitter', label='LT-999', area='SEPARATOR',
              x=0.9, y=0.9),  # ~1.27 away
    ]
    proposals = infer_connections(nodes, [], studio={})
    assert proposals == []


# ── Priority 4: pure proximity (inferred, below threshold) ───────────────────

def test_pure_proximity_excluded_from_run_proposals():
    """`infer_connections` still surfaces a proximity match (0.50) but
    `run_connectivity_inference` drops it from the returned list because
    its confidence is below the 0.70 publication threshold; instead it is
    counted under stats['below_threshold']."""
    nodes = [
        _node('e1', 'vessel',      label='V-201', area='SEPARATOR',
              x=0.50, y=0.50),
        _node('i1', 'transmitter', label='LT-999', area='SOMEWHERE_ELSE',
              x=0.55, y=0.52),  # well under 0.20
    ]
    raw = infer_connections(nodes, [], studio={})
    assert len(raw) == 1
    assert raw[0]['method']     == 'proximity'
    assert raw[0]['confidence'] == 0.50

    out = run_connectivity_inference(nodes, [], studio={})
    assert out['proposals'] == []
    assert out['stats']['proposed']         == 0
    assert out['stats']['below_threshold']  == 1
    assert out['stats']['unproposeble']     == 0
    assert out['stats']['by_method']['proximity'] == 0


# ── Already-connected instruments are skipped ────────────────────────────────

def test_already_connected_instrument_skipped():
    nodes = [
        _node('e1', 'vessel',      label='V-101', area='REACTOR'),
        _node('i1', 'transmitter', label='LT-101', area='REACTOR',
              equipment_ref='V-101'),
    ]
    edges = [{'from': 'i1', 'to': 'e1', 'kind': 'signal'}]
    proposals = infer_connections(nodes, edges, studio={})
    assert proposals == [], 'connected instruments must not produce proposals'


def test_non_signal_edges_do_not_count_as_connected():
    """A process pipe touching the instrument doesn't satisfy the
    "has a signal edge" requirement."""
    nodes = [
        _node('e1', 'vessel',      label='V-101', area='REACTOR'),
        _node('i1', 'transmitter', label='LT-101', area='REACTOR',
              equipment_ref='V-101'),
    ]
    edges = [{'from': 'e1', 'to': 'i1', 'kind': 'stream'}]
    proposals = infer_connections(nodes, edges, studio={})
    assert len(proposals) == 1
    assert proposals[0]['method'] == 'equipment_ref'


# ── No match possible → counted as unproposeble ──────────────────────────────

def test_unproposeble_counted_in_stats():
    """An instrument with no equipment_ref, no loop neighbours, no nearby
    equipment must end up in the unproposeble bucket."""
    nodes = [
        _node('i1', 'transmitter', label='LT-999', area='ISLAND',
              x=0.50, y=0.50),
        # Far-away equipment in another area; both proximity tiers fail
        _node('e1', 'vessel', label='V-001', area='OTHER',
              x=0.99, y=0.99),
    ]
    out = run_connectivity_inference(nodes, [], studio={})
    s = out['stats']
    assert s['unconnected_instruments'] == 1
    assert s['proposed']                == 0
    assert s['unproposeble']            == 1
    assert s['by_method'] == {
        'equipment_ref': 0, 'loop_number': 0,
        'area_kind': 0,    'proximity': 0,
        'loop_number_valve': 0,
    }
    assert out['proposals'] == []


# ── run_connectivity_inference: full stats roll-up ───────────────────────────

def test_run_returns_stats_and_proposals():
    """Mixed scene: one auto via equipment_ref, one uncertain via loop number,
    and one orphan transmitter that no resolver can place. Coordinates are
    pushed to opposite corners so the proximity-fallback can't bail the
    orphan out."""
    nodes = [
        _node('e1', 'vessel',      label='V-101',  area='REACTOR',
              x=0.05, y=0.05),
        _node('i1', 'transmitter', label='LT-101', area='REACTOR',
              x=0.10, y=0.05, equipment_ref='V-101'),                # auto
        _node('t1', 'transmitter', label='FT-3503', area='OTHER',
              x=0.95, y=0.95),                                       # unproposeble
        _node('c1', 'controller',  label='FTC-3503', area='OTHER',
              x=0.95, y=0.98),                                       # uncertain
    ]
    out = run_connectivity_inference(nodes, [], studio={})
    s = out['stats']
    assert s['unconnected_instruments'] == 3
    assert s['proposed']                == 2
    assert s['by_method']['equipment_ref'] == 1
    assert s['by_method']['loop_number']   == 1
    assert s['unproposeble']            == 1


# ── Valve loop-number pass ────────────────────────────────────────────────────

def test_valve_loop_number_pairs_with_controller_uncertain():
    """FCV-1012 with FIC-1012 in the same area → uncertain proposal,
    method='loop_number_valve', signal edge cv → controller."""
    nodes = [
        _node('c1', 'controller',   label='FIC-1012', area='METERING',
              x=0.50, y=0.30),
        _node('v1', 'control_valve', label='FCV-1012', area='METERING',
              x=0.50, y=0.40),
    ]
    proposals = infer_connections(nodes, [], studio={})
    valve_props = [p for p in proposals if p['from'] == 'v1']
    assert len(valve_props) == 1
    p = valve_props[0]
    assert p['to']           == 'c1'
    assert p['kind']         == 'signal'
    assert p['method']       == 'loop_number_valve'
    assert p['review_state'] == 'uncertain'
    assert abs(p['confidence'] - 0.85) < 1e-6


def test_valve_loop_number_falls_back_to_transmitter():
    """No controller in loop, but transmitter present → still uncertain."""
    nodes = [
        _node('t1', 'transmitter', label='FT-1012', area='METERING'),
        _node('v1', 'control_valve', label='FCV-1012', area='METERING'),
    ]
    proposals = infer_connections(nodes, [], studio={})
    valve_props = [p for p in proposals if p['from'] == 'v1']
    assert len(valve_props) == 1
    p = valve_props[0]
    assert p['to']           == 't1'
    assert p['method']       == 'loop_number_valve'
    assert p['review_state'] == 'uncertain'


def test_valve_no_matching_loop_no_proposal():
    """FCV-1012 with no other loop-1012 nodes in scene → silent skip.
    The valve does not contribute to any unproposeble bucket — it is
    counted under unconnected_valves instead."""
    nodes = [
        _node('e1', 'vessel', label='V-201',  area='SEPARATOR'),
        _node('v1', 'control_valve', label='FCV-1012', area='METERING'),
    ]
    proposals = infer_connections(nodes, [], studio={})
    valve_props = [p for p in proposals if p['from'] == 'v1']
    assert valve_props == []

    out = run_connectivity_inference(nodes, [], studio={})
    s = out['stats']
    assert s['unconnected_valves'] == 1
    assert s['proposed_valves']    == 0
    # Valve absence does not bump unproposeble (which counts instruments only)
    assert s['unproposeble']       == 0


def test_valve_already_connected_skipped():
    nodes = [
        _node('c1', 'controller',    label='FIC-1012', area='METERING'),
        _node('v1', 'control_valve', label='FCV-1012', area='METERING'),
    ]
    edges = [{'from': 'v1', 'to': 'c1', 'kind': 'signal'}]
    proposals = infer_connections(nodes, edges, studio={})
    assert [p for p in proposals if p['from'] == 'v1'] == []


def test_valve_with_no_loop_number_no_proposal():
    """Valve label without digits (e.g. hand valve 'HV-IN') yields nothing."""
    nodes = [
        _node('c1', 'controller',    label='FIC-1012', area='METERING'),
        _node('v1', 'control_valve', label='HV-IN',    area='METERING'),
    ]
    proposals = infer_connections(nodes, [], studio={})
    assert [p for p in proposals if p['from'] == 'v1'] == []


# ── Local CLI runner ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    import inspect
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith('test_') or not callable(fn):
            continue
        if inspect.signature(fn).parameters:
            continue
        try:
            fn()
            print(f'  OK   {name}')
        except AssertionError as e:
            failures += 1
            print(f'  FAIL {name}: {e}')
        except Exception as e:
            failures += 1
            print(f'  ERR  {name}: {e!r}')
    print()
    print(f'{"PASS" if failures == 0 else f"FAIL ({failures})"}')
    sys.exit(0 if failures == 0 else 1)
