"""Phase 7 -- cv2.HoughLinesP return-shape compatibility.

Found by running a real extraction: OpenCV 5 returns (N, 4) where OpenCV 4
returned (N, 1, 4). The old parser assumed the 4.x shape, so on 5.x it built a
list of ints, the next unpack raised "cannot unpack non-iterable int object",
the whole post-processing block was swallowed by its own `except`, and line
detection returned ZERO lines -- silently, with extraction still reporting
success for the other stages.

requirements.txt allows opencv-contrib-python >= 4.9 with no upper bound, so
this is what a fresh install gets today.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.geometry.line_geometry import (            # noqa: E402
    _classify_lines, _hough_segments,
)


def test_opencv4_shape_n_1_4():
    """The historic shape must still parse."""
    raw = np.array([[[10, 50, 90, 50]], [[20, 10, 20, 80]]], dtype=np.int32)
    assert raw.shape == (2, 1, 4)
    assert _hough_segments(raw) == [[10, 50, 90, 50], [20, 10, 20, 80]]


def test_opencv5_shape_n_4():
    """The shape that broke line detection."""
    raw = np.array([[10, 50, 90, 50], [20, 10, 20, 80]], dtype=np.int32)
    assert raw.shape == (2, 4)
    assert _hough_segments(raw) == [[10, 50, 90, 50], [20, 10, 20, 80]]


def test_none_and_empty_are_empty_not_a_crash():
    assert _hough_segments(None) == []
    assert _hough_segments(np.empty((0, 4), dtype=np.int32)) == []


def test_plain_python_sequences_are_accepted():
    assert _hough_segments([[1, 2, 3, 4]]) == [[1, 2, 3, 4]]
    assert _hough_segments([[[1, 2, 3, 4]]]) == [[1, 2, 3, 4]]


@pytest.mark.parametrize('raw', [
    np.array([[[10, 50, 90, 50]]], dtype=np.int32),      # 4.x
    np.array([[10, 50, 90, 50]], dtype=np.int32),        # 5.x
])
def test_classify_lines_consumes_either_shape(raw):
    """The end-to-end symptom: _classify_lines must not raise on either shape.

    This is the exact unpack that failed -- it is asserted here rather than
    only on the helper, because the helper existing is not the same as the
    pipeline using it.
    """
    horiz, vert, other = _classify_lines(_hough_segments(raw))
    assert len(horiz) + len(vert) + len(other) == 1
    assert horiz, 'a horizontal segment should classify as horizontal'


def test_real_opencv_output_parses():
    """Run the actual installed OpenCV, whatever major version that is.

    A hand-built array proves the parser; only calling the real function proves
    the assumption about the installed library.
    """
    cv2 = pytest.importorskip('cv2')
    img = np.zeros((100, 100), np.uint8)
    cv2.line(img, (10, 50), (90, 50), 255, 2)
    raw = cv2.HoughLinesP(img, rho=1, theta=np.pi / 180,
                          threshold=3, minLineLength=3, maxLineGap=12)
    segs = _hough_segments(raw)
    assert segs, f'no segments parsed from OpenCV {cv2.__version__}'
    assert all(len(s) == 4 for s in segs), f'bad shape from OpenCV {cv2.__version__}'
    horiz, _, _ = _classify_lines(segs)
    assert horiz, 'a drawn horizontal line must be detected as horizontal'
