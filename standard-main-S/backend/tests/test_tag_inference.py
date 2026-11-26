"""Pass 3 tag normalisation + inference tests.

Real CTP tags are used as the "known_tags" baseline so the gap-detection /
fuzzy-matching tests reflect production data shapes (FT-1052, V-151, etc.).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running these tests directly without packaging.
_STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(_STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(_STUDIO_DIR))

from adapters.tag_inference import (   # noqa: E402  — sys.path edited above
    normalize_tag, infer_tag, run_tag_inference,
)


# ── Fixtures (CTP-style tags / areas) ─────────────────────────────────────────

CTP_KNOWN_TAGS = {
    # H2 feed delivery / metering
    'TK-052', 'TK-053', 'V-151', 'V-152', 'V-153',
    'X-101', 'E-101', 'HV-1052', 'HV-1057',
    'FT-1052', 'FT-1054', 'PT-1051', 'TT-1051',
    'FIC-1052', 'PIC-1051', 'TIC-1051',
    'FCV-1052', 'PCV-1051',
    # CO2 feed delivery
    'TK-051', 'X-051', 'HV-1058',
    'FT-2051', 'PT-2051',
    # Reactor R-301
    'R-301', 'R-302', 'TE-3001', 'TT-3001', 'PT-3001',
}


# ── normalize_tag --------------------------------------------------------------

def test_ocr_substitution_letter_in_digits():
    """'FT-I052' (capital-I where 1 belongs) → 'FT-1052' via substitution."""
    out = normalize_tag('FT-I052', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is not None, 'expected a proposal'
    assert out['proposed']     == 'FT-1052'
    assert out['method']       == 'substitution'
    assert out['confidence']   >= 0.9
    assert out['review_state'] == 'auto'


def test_ocr_substitution_lowercase_l():
    """'FT-l052' (lowercase-L) → 'FT-1052'."""
    out = normalize_tag('FT-l052', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is not None
    assert out['proposed'] == 'FT-1052'
    assert out['method']   == 'substitution'


def test_structural_repair_missing_hyphen():
    """'FT1052' → 'FT-1052' via structural repair."""
    out = normalize_tag('FT1052', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is not None
    assert out['proposed']     == 'FT-1052'
    assert out['method']       == 'structural'
    assert out['review_state'] == 'auto'


def test_structural_repair_internal_hyphen():
    """'F-T1052' → 'FT-1052'."""
    out = normalize_tag('F-T1052', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is not None
    assert out['proposed'] == 'FT-1052'


def test_fuzzy_match_distance_one():
    """'FT-1O52' (letter-O instead of digit-0) — substitution catches it first
    (high confidence). Force-fuzzy is exercised in the next test."""
    out = normalize_tag('FT-1O52', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is not None
    assert out['proposed'] == 'FT-1052'


def test_fuzzy_only_path_when_substitution_fails():
    """'FT-1Q52' has a 'Q' that no substitution can repair, but Levenshtein 1
    away from the known 'FT-1052'."""
    out = normalize_tag('FT-1Q52', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is not None
    assert out['proposed'] == 'FT-1052'
    assert out['method']   == 'fuzzy'
    # distance == 1 → confidence 0.85, which is below auto threshold
    assert out['review_state'] == 'uncertain'


def test_already_valid_returns_none():
    """Valid tags are pass-through."""
    out = normalize_tag('FT-1052', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is None


def test_unrecoverable_garbage_returns_none():
    """No substitution / structural / fuzzy match can recover this — None."""
    out = normalize_tag('@#$%!!', area='H2 FEED GAS METERING', kind='transmitter',
                        known_tags=CTP_KNOWN_TAGS)
    assert out is None


# ── infer_tag ------------------------------------------------------------------

def _make_node(nid, kind, area='', label='', **extra):
    n = {'id': nid, 'kind': kind, 'area': area, 'label': label}
    n.update(extra)
    return n


def test_infer_transmitter_fills_gap():
    """Unnamed flow transmitter alongside FT-1052 and FT-1054 → propose FT-1053."""
    nodes = [
        _make_node('n1', 'transmitter', area='H2 FEED GAS METERING',
                   label='FT-1052'),
        _make_node('n2', 'transmitter', area='H2 FEED GAS METERING',
                   label='FT-1054'),
        # The unnamed transmitter — measured_variable hints flow
        _make_node('n3', 'transmitter', area='H2 FEED GAS METERING',
                   label='', measured_variable='flow'),
    ]
    edges: list = []
    known = {'FT-1052', 'FT-1054'}

    out = infer_tag(nodes[2], nodes, edges, known)
    assert out is not None, 'expected a proposal for the unnamed transmitter'
    assert out['proposed']     == 'FT-1053'
    assert out['method']       == 'inferred'
    assert out['review_state'] == 'inferred'
    assert out['confidence']   <= 0.75


def test_infer_vessel_uses_area_prefix():
    """Unnamed vessel in H2 FEED area where existing tags use 10xx pattern
    → propose V-1xxx with the dominant area-prefix (10)."""
    nodes = [
        _make_node('n1', 'transmitter', area='H2 FEED GAS DELIVERY',
                   label='FT-1052'),
        _make_node('n2', 'transmitter', area='H2 FEED GAS DELIVERY',
                   label='PT-1051'),
        _make_node('n3', 'controller', area='H2 FEED GAS DELIVERY',
                   label='FIC-1052'),
        # The unnamed vessel
        _make_node('n4', 'vessel', area='H2 FEED GAS DELIVERY', label=''),
    ]
    edges: list = []
    known = {'FT-1052', 'PT-1051', 'FIC-1052'}

    out = infer_tag(nodes[3], nodes, edges, known)
    assert out is not None
    # Must start with V- and use the 10xx area prefix derived from neighbours
    assert out['proposed'].startswith('V-')
    digits = out['proposed'].split('-', 1)[1]
    assert digits.isdigit() and digits.startswith('10'), \
        f'expected a V-10xx tag, got {out["proposed"]!r}'
    assert out['review_state'] == 'inferred'
    assert out['confidence']   <= 0.75


def test_infer_unknown_kind_no_proposal():
    """If we cannot resolve a function letter we must not invent one."""
    nodes = [_make_node('n1', kind='', area='UNKNOWN', label='')]
    out = infer_tag(nodes[0], nodes, [], known_tags=set())
    assert out is None


# ── run_tag_inference (end-to-end) --------------------------------------------

def test_run_tag_inference_skips_valid_tags():
    nodes = [
        _make_node('n1', 'transmitter', area='A', label='FT-1052'),
        _make_node('n2', 'vessel',      area='A', label='V-151'),
    ]
    proposals = run_tag_inference(nodes, [])
    assert proposals == []


def test_run_tag_inference_mixed_repair_and_infer():
    """A bad tag gets normalised; an empty tag gets inferred. Loop numbers
    don't have to match a specific value — we just check the categories."""
    nodes = [
        _make_node('n1', 'transmitter', area='H2 FEED', label='FT-1052'),
        _make_node('n2', 'transmitter', area='H2 FEED', label='FT-1054'),
        _make_node('n3', 'transmitter', area='H2 FEED', label='FT1056'),  # missing hyphen
        _make_node('n4', 'transmitter', area='H2 FEED', label='',         # unnamed
                   measured_variable='flow'),
    ]
    proposals = {p['node_id']: p for p in run_tag_inference(nodes, [])}

    assert 'n1' not in proposals and 'n2' not in proposals  # already valid
    assert proposals['n3']['proposed_tag'] == 'FT-1056'
    assert proposals['n3']['method']       == 'structural'
    assert proposals['n3']['review_state'] == 'auto'

    # Inferred tag — first gap in {1052, 1054} is 1053
    assert proposals['n4']['proposed_tag'] == 'FT-1053'
    assert proposals['n4']['review_state'] == 'inferred'


# ── Local CLI runner ----------------------------------------------------------

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
