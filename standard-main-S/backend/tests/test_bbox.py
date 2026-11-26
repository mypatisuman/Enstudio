"""derive_bbox tests — pure-function, no I/O."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(_STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(_STUDIO_DIR))

from adapters.engine import derive_bbox  # noqa: E402


# ── Fixture mirroring Part 5 YAML ─────────────────────────────────────────────

LAYOUT_RULES = {
    'equipment': {
        'vessel_size': [80, 60],     'vessel_shape': 'rectangle',  'vessel_mask_padding': 12,
        'hx_size':     [100, 40],    'hx_shape':     'rectangle',  'hx_mask_padding':     10,
        'pump_size':   [50, 50],     'pump_shape':   'circle',     'pump_mask_padding':   8,
        'compressor_size': [60, 60], 'compressor_shape': 'circle', 'compressor_mask_padding': 10,
        'reactor_size': [80, 70],    'reactor_shape': 'rectangle', 'reactor_mask_padding': 15,
        'valve_size':   [40, 30],    'valve_shape':   'diamond',   'valve_mask_padding':   8,
        'filter_size':  [50, 50],    'filter_shape':  'rectangle', 'filter_mask_padding':  8,
    },
    'instruments': {
        'bubble_diameter':     30,
        'bubble_shape':        'circle',
        'bubble_mask_padding': 6,
    },
}

PAGE_W = 1400
PAGE_H = 800


def _bbox_dims(b: dict) -> tuple[float, float]:
    return b['x2'] - b['x1'], b['y2'] - b['y1']


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_vessel_node_returns_rectangle_bbox_correct_size():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'vessel'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'rectangle'
    assert bbox['source'] == 'rule_derived'
    w, h = _bbox_dims(bbox)
    assert w == 80 + 2 * 12  # vessel_size + 2 * mask_padding
    assert h == 60 + 2 * 12


def test_hx_node_rectangle_wider_than_tall():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'heat_exchanger'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'rectangle'
    w, h = _bbox_dims(bbox)
    assert w == 100 + 2 * 10
    assert h == 40 + 2 * 10
    assert w > h


def test_pump_node_returns_circle_bbox_square():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'pump'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'circle'
    w, h = _bbox_dims(bbox)
    assert w == h == 50 + 2 * 8  # pump_size + 2 * mask_padding


def test_transmitter_node_uses_bubble_diameter():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'transmitter'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'circle'
    w, h = _bbox_dims(bbox)
    assert w == h == 30 + 2 * 6  # bubble_diameter + 2 * bubble_mask_padding


def test_controller_node_uses_bubble_diameter():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'controller'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'circle'
    w, h = _bbox_dims(bbox)
    assert w == h == 30 + 2 * 6


def test_valve_node_diamond_shape():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'valve'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'diamond'
    w, h = _bbox_dims(bbox)
    assert w == 40 + 2 * 8
    assert h == 30 + 2 * 8


def test_filter_node_rectangle_bbox():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'filter'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'rectangle'
    w, h = _bbox_dims(bbox)
    assert w == h == 50 + 2 * 8


def test_unknown_kind_falls_back_to_vessel():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'mystery_widget'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    assert bbox['shape'] == 'rectangle'
    w, h = _bbox_dims(bbox)
    # Same extents as vessel
    assert w == 80 + 2 * 12
    assert h == 60 + 2 * 12


def test_dpi_150_scales_sizes_down_by_half():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'vessel'},
        PAGE_W, PAGE_H, LAYOUT_RULES, dpi=150,
    )
    w, h = _bbox_dims(bbox)
    # vessel 80x60 + 2*12 padding, all halved
    assert w == pytest.approx((80 + 2 * 12) * 0.5)
    assert h == pytest.approx((60 + 2 * 12) * 0.5)


def test_dpi_600_scales_sizes_up_by_two():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'vessel'},
        PAGE_W, PAGE_H, LAYOUT_RULES, dpi=600,
    )
    w, h = _bbox_dims(bbox)
    assert w == pytest.approx((80 + 2 * 12) * 2.0)
    assert h == pytest.approx((60 + 2 * 12) * 2.0)


def test_company_profile_overrides_size():
    company_profile = {
        'symbol_geometry': {
            'pump': {'size': [70, 70], 'shape': 'rectangle', 'mask_padding': 5},
        }
    }
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'pump'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
        company_profile=company_profile,
    )
    assert bbox['shape'] == 'rectangle'  # overridden, not the default 'circle'
    w, h = _bbox_dims(bbox)
    assert w == 70 + 2 * 5
    assert h == 70 + 2 * 5


def test_centroid_at_normalised_half_maps_to_page_centre():
    bbox = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'vessel'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    cx = (bbox['x1'] + bbox['x2']) / 2
    cy = (bbox['y1'] + bbox['y2']) / 2
    assert cx == 700  # 0.5 * 1400
    assert cy == 400  # 0.5 * 800


def test_mask_padding_is_included_in_bbox_extent():
    # Strip mask_padding by reading width with vs without it.
    rules_no_pad = {
        'equipment': {
            'vessel_size': [80, 60],
            'vessel_shape': 'rectangle',
            'vessel_mask_padding': 0,
        },
        'instruments': LAYOUT_RULES['instruments'],
    }
    bbox_padded = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'vessel'},
        PAGE_W, PAGE_H, LAYOUT_RULES,
    )
    bbox_bare = derive_bbox(
        {'x': 0.5, 'y': 0.5, 'kind': 'vessel'},
        PAGE_W, PAGE_H, rules_no_pad,
    )
    w_pad, _ = _bbox_dims(bbox_padded)
    w_bare, _ = _bbox_dims(bbox_bare)
    assert w_pad - w_bare == 2 * 12  # twice the vessel_mask_padding
