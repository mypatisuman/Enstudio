"""ponytail self-check for _snap_segments_to_symbols' two-tier fallback radius."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from extract_cli import _snap_segments_to_symbols


def _sym(sid, bbox):
    return {"id": sid, "bbox": bbox}


def test_unambiguous_long_stub_snaps_via_far_fallback():
    # Vertical segment endpoint sits 30px below GCV's bbox bottom (>18px snap_px,
    # <40px fallback) with no competing symbol nearby -> should snap.
    gcv = _sym("GCV-XXXX", [400, 100, 500, 200])
    seg = {"x1": 450, "y1": 230, "x2": 450, "y2": 400, "direction": "vertical"}
    out = _snap_segments_to_symbols([seg], [gcv])
    assert out[0]["y1"] == 200, out[0]


def test_ambiguous_endpoint_stays_unsnapped():
    # Point sits 25px from A's bottom edge (200) and 25px from B's top edge
    # (250) -> both outside snap_px=18 but within the 40px fallback, and two
    # distinct symbols qualify -> ambiguous, must NOT snap.
    a = _sym("A", [400, 100, 500, 200])
    b = _sym("B", [400, 250, 500, 350])
    seg = {"x1": 450, "y1": 225, "x2": 450, "y2": 400, "direction": "vertical"}
    out = _snap_segments_to_symbols([seg], [a, b])
    assert out[0]["y1"] == 225, out[0]


def test_within_snap_px_still_works_as_before():
    gcv = _sym("GCV-XXXX", [400, 100, 500, 200])
    seg = {"x1": 450, "y1": 210, "x2": 450, "y2": 400, "direction": "vertical"}
    out = _snap_segments_to_symbols([seg], [gcv])
    assert out[0]["y1"] == 200, out[0]


if __name__ == "__main__":
    test_unambiguous_long_stub_snaps_via_far_fallback()
    test_ambiguous_endpoint_stays_unsnapped()
    test_within_snap_px_still_works_as_before()
    print("ok")
