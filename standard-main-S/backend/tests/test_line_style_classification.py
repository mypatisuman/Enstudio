"""Phase 1: the one reconnected line-processing function.

`_classify_line_style` existed, was tested by nothing, and was called by
nothing — so `signal_lines` was hardcoded `[]` and every dashed instrument
signal line was published as a process pipe.

The safety property that made it the only safe reconnection: it PARTITIONS
segments, it never adds or removes one. These tests pin that invariant along
with the classification itself, using synthetic rasters (no UNet, no weights,
no GPU).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

np = pytest.importorskip('numpy')
cv2 = pytest.importorskip('cv2')

from services.geometry.line_geometry import (          # noqa: E402
    _classify_line_style, _line_fill_ratio, _DASH_MIN_LEN, _DASH_FILL_THRESH,
)


def _canvas(w=400, h=200):
    """White page."""
    return np.full((h, w), 255, dtype=np.uint8)


def _solid(gray, y=100, x0=20, x1=380):
    cv2.line(gray, (x0, y), (x1, y), 0, 2)
    return [x0, y, x1, y]


def _dashed(gray, y=100, x0=20, x1=380, on=8, off=8):
    x = x0
    while x < x1:
        cv2.line(gray, (x, y), (min(x + on, x1), y), 0, 2)
        x += on + off
    return [x0, y, x1, y]


# -- classification ----------------------------------------------------------

def test_solid_line_reads_as_solid():
    g = _canvas()
    seg = _solid(g)
    assert _classify_line_style(g, seg) == 'solid'


def test_dashed_line_reads_as_dashed():
    g = _canvas()
    seg = _dashed(g)
    assert _classify_line_style(g, seg) == 'dashed'


def test_vertical_dashed_line_reads_as_dashed():
    g = _canvas(200, 400)
    x = 100
    y = 20
    while y < 380:
        cv2.line(g, (x, y), (x, min(y + 8, 380)), 0, 2)
        y += 16
    assert _classify_line_style(g, [x, 20, x, 380]) == 'dashed'


def test_short_segments_are_never_called_dashed():
    """Below _DASH_MIN_LEN there is not enough run to judge, and a wrong
    'dashed' verdict would drop a real short pipe stub out of the piping
    connections. The function must stay conservative."""
    g = _canvas()
    short = [10, 50, 10 + _DASH_MIN_LEN - 5, 50]
    assert _classify_line_style(g, short) == 'solid'


def test_fill_ratio_orders_solid_above_dashed():
    g1, g2 = _canvas(), _canvas()
    s = _solid(g1)
    d = _dashed(g2)
    r_solid = _line_fill_ratio(g1, *s)
    r_dash = _line_fill_ratio(g2, *d)
    assert r_solid > r_dash
    assert r_solid >= _DASH_FILL_THRESH
    assert r_dash < _DASH_FILL_THRESH


def test_blank_region_is_not_solid():
    """A segment over white paper has no ink and must not be reported as a
    confident solid pipe."""
    g = _canvas()
    assert _line_fill_ratio(g, 20, 100, 380, 100) == 0.0


# -- the invariant that justified reconnecting this one ----------------------

def test_classification_partitions_and_never_changes_segment_count():
    """Every input segment lands in exactly one output bucket. This is why
    this function was safe to reconnect while the delete/add helpers were
    not — see the module docstring in line_detection_service.py."""
    g = _canvas(600, 400)
    segs = [
        _solid(g, y=50, x0=20, x1=580),
        _dashed(g, y=120, x0=20, x1=580),
        _solid(g, y=200, x0=20, x1=60),        # short solid
        _dashed(g, y=300, x0=20, x1=580, on=6, off=10),
    ]

    long_lines, connected_lines, signal_lines = [], [], []
    import math
    for x1, y1, x2, y2 in segs:
        seg = [x1, y1, x2, y2]
        if _classify_line_style(g, seg) == 'dashed':
            signal_lines.append(seg)
        elif math.hypot(x2 - x1, y2 - y1) >= 35:
            long_lines.append(seg)
        else:
            connected_lines.append(seg)

    total_out = len(long_lines) + len(connected_lines) + len(signal_lines)
    assert total_out == len(segs), 'classification must not add or drop segments'
    assert len(signal_lines) == 2
    # No segment may appear in two buckets.
    seen = [tuple(s) for s in long_lines + connected_lines + signal_lines]
    assert len(seen) == len(set(seen))


def test_signal_segments_become_signal_kind_downstream():
    """The bucket only matters because _segs_to_dicts maps it to kind='signal',
    which connectivity_graph propagates and _derive_studio_tables then excludes
    from the piping connections table."""
    from extraction_cli.image import _segs_to_dicts
    out = _segs_to_dicts([[0, 0, 100, 0]], [], [[0, 50, 100, 50]])
    kinds = {d['kind'] for d in out}
    assert kinds == {'process', 'signal'}

    from extraction_cli.commands import _derive_studio_tables
    nodes = [{'id': 'a', 'label': 'A', 'category': 'equipment'},
             {'id': 'b', 'label': 'B', 'category': 'instrument'}]
    edges = [{'from': 'a', 'to': 'b', 'kind': 'signal'}]
    _, _, conns = _derive_studio_tables(nodes, edges)
    assert conns == [], 'a signal line is not a pipe'
