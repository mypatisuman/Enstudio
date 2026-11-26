"""Concurrent tile calls and the zoom-in refinement pass, with the LLM stubbed.

The concurrency tests prove the two properties that make parallelism safe to
turn on by default: results aggregate in tile order exactly as the sequential
loop did, and one failing tile never takes the page down.
"""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from services import tile_runner as TR  # noqa: E402
import services.llm_symbol_detection_service as SYM  # noqa: E402


# ── tile runner ──────────────────────────────────────────────────────────────

def test_results_come_back_in_input_order_despite_uneven_latency():
    def slow(i):
        time.sleep(random.uniform(0, 0.02))
        return i * i
    out = TR.run_ordered(slow, range(40), workers=8)
    assert [r for r, _ in out] == [i * i for i in range(40)]


def test_calls_really_overlap():
    active, peak, lock = [0], [0], threading.Lock()

    def track(_):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.03)
        with lock:
            active[0] -= 1
    TR.run_ordered(track, range(12), workers=4)
    assert peak[0] >= 2


def test_one_failure_is_isolated():
    def maybe(i):
        if i == 3:
            raise RuntimeError("provider 500")
        return i
    out = TR.run_ordered(maybe, range(6), workers=3)
    assert isinstance(out[3][1], RuntimeError)
    assert [r for r, e in out if e is None] == [0, 1, 2, 4, 5]


@pytest.mark.parametrize("raw, expected", [("", 4), ("1", 1), ("99", 16), ("0", 1), ("abc", 4)])
def test_concurrency_setting_is_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv("STUDIO_TILE_CONCURRENCY", raw)
    monkeypatch.setattr("adapters.config.load_config", lambda: {})
    assert TR.tile_concurrency() == expected


# ── symbol loop keeps its aggregation contract ───────────────────────────────

def _page(width=1400, height=1000):
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    for x in range(40, width - 40, 150):              # ink on every tile
        cv2.rectangle(img, (x, 60), (x + 60, height - 60), (0, 0, 0), 3)
    return img


def _fake_studio(monkeypatch):
    fake = SimpleNamespace(llm=SimpleNamespace(supports_vision=lambda tier="fast": True))
    monkeypatch.setattr(SYM, "_studio_module", lambda: fake)
    return fake


def test_symbol_detection_is_identical_sequential_and_concurrent(monkeypatch, tmp_path):
    _fake_studio(monkeypatch)
    monkeypatch.setenv("STUDIO_ZOOM_REFINE", "off")

    def fake_tile(_s, tile, tx1, ty1, w, h, retry_note=""):
        time.sleep(random.uniform(0, 0.01))
        return [{"type": "Valve", "bbox": [tx1 + 10, ty1 + 10, tx1 + 40, ty1 + 40],
                 "score": 0.9, "editable": True}]

    monkeypatch.setattr(SYM, "_detect_tile", fake_tile)
    ok, buf = cv2.imencode(".png", _page())
    results = {}
    for workers in ("1", "8"):
        monkeypatch.setenv("STUDIO_TILE_CONCURRENCY", workers)
        out = SYM.process_detect_symbols(buf.tobytes(), original_filename="p.png",
                                         output_dir=str(tmp_path))
        results[workers] = out["detections"]
    assert results["1"] == results["8"] and results["1"], "concurrency changed the output"


def test_a_failing_tile_is_skipped_not_fatal(monkeypatch, tmp_path):
    _fake_studio(monkeypatch)
    monkeypatch.setenv("STUDIO_ZOOM_REFINE", "off")
    calls = {"n": 0}

    def flaky(_s, tile, tx1, ty1, w, h, retry_note=""):
        calls["n"] += 1
        if tx1 == 0 and ty1 == 0:
            raise RuntimeError("timeout")
        return [{"type": "Valve", "bbox": [tx1 + 5, ty1 + 5, tx1 + 30, ty1 + 30],
                 "score": 0.9, "editable": True}]

    monkeypatch.setattr(SYM, "_detect_tile", flaky)
    ok, buf = cv2.imencode(".png", _page())
    out = SYM.process_detect_symbols(buf.tobytes(), original_filename="p.png",
                                     output_dir=str(tmp_path))
    assert out["detections"] and calls["n"] > 1


# ── zoom-in refinement ───────────────────────────────────────────────────────

def _llm_answer(payload):
    return SimpleNamespace(llm=SimpleNamespace(
        complete_streaming=lambda *a, **k: SimpleNamespace(text=json.dumps(payload))))


def test_confirmed_symbol_gets_a_tighter_box_and_higher_score():
    img = _page()
    det = {"type": "Valve", "bbox": [100, 100, 180, 180], "score": 0.55}
    # The crop starts at (60, 60) with 40px padding; the model reports a box
    # inside the original one, in crop pixels.
    fake = _llm_answer({"present": True, "bbox": [50, 50, 110, 110], "confidence": 0.93})
    out = SYM._refine_one(fake, img, det)
    assert out["refined"] == "confirmed" and out["score"] == 0.93
    assert out["bbox"] == [110, 110, 170, 170]


def test_confident_absence_halves_the_score_without_deleting():
    fake = _llm_answer({"present": False, "bbox": None, "confidence": 0.9})
    out = SYM._refine_one(fake, _page(), {"type": "Valve", "bbox": [100, 100, 180, 180], "score": 0.6})
    assert out["refined"] == "doubted" and out["score"] == 0.3


def test_a_box_for_a_different_object_is_ignored():
    fake = _llm_answer({"present": True, "bbox": [0, 0, 8, 8], "confidence": 0.9})
    det = {"type": "Valve", "bbox": [100, 100, 180, 180], "score": 0.5}
    out = SYM._refine_one(fake, _page(), det)
    assert out["bbox"] == det["bbox"]


def test_only_low_confidence_detections_are_refined(monkeypatch):
    monkeypatch.setenv("STUDIO_ZOOM_REFINE", "on")
    seen = []
    monkeypatch.setattr(SYM, "_refine_one",
                        lambda _s, img, det: (seen.append(det["score"]), {**det, "refined": "confirmed"})[1])
    dets = [{"type": "V", "bbox": [0, 0, 10, 10], "score": s} for s in (0.95, 0.6, 0.81, 0.51)]
    out, stats = SYM._refine_detections(None, _page(), dets)
    assert sorted(seen) == [0.51, 0.6]
    assert stats["candidates"] == 2 and stats["confirmed"] == 2
    assert out[0] is dets[0]


def test_refinement_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("STUDIO_ZOOM_REFINE", "off")
    dets = [{"type": "V", "bbox": [0, 0, 10, 10], "score": 0.1}]
    assert SYM._refine_detections(None, _page(), dets) == (dets, {
        "candidates": 0, "confirmed": 0, "doubted": 0, "inconclusive": 0, "failed": 0})
