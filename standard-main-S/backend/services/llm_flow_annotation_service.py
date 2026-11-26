"""
services/llm_flow_annotation_service.py — flow arrows and electric heat tracing.

The line tracer records pipe and signal runs with a solid/dashed style and
nothing else, and its stitching step merges runs, so any per-run annotation
would be lost on the way to the saved geometry. Two things the connectivity
graph needs are therefore read here, in a separate pass over the same page
raster:

  arrows       arrowheads drawn on pipe runs: {"tail": [x, y], "tip": [x, y]}.
               The exporter orients a connection from its arrow before falling
               back to reachability from the plant's inlets.
  heat_trace   electric heat-tracing runs: {"points": [[x, y], ...]}. Exported
               as `electric_heat_trace`, keyed by the item each run follows.

Pure vision LLM, like every detector here. The page is cut into overlapping
crops no larger than a model's native input (so reported pixels are real
pixels), sent concurrently on the shared tile pool, and mapped back to page
pixels. A failed crop is skipped, never fatal. Disable with
STUDIO_FLOW_ANNOTATIONS=off.
"""
from __future__ import annotations

import base64
import logging
import math
import os

import numpy as np

try:
    import cv2
except ImportError:                                # pragma: no cover
    cv2 = None

logger = logging.getLogger(__name__)

_CROP = 1500            # page pixels per crop edge
_OVERLAP = 150
_MAX_EDGE = 1568        # longest edge sent to the model
_MIN_CONFIDENCE = 0.5
_ARROW_MERGE_PX = 18
_TRACE_MERGE_PX = 20


def enabled() -> bool:
    return (os.getenv("STUDIO_FLOW_ANNOTATIONS") or "on").strip().lower() not in ("off", "0", "false", "no")


def crops(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Overlapping (x0, y0, x1, y1) windows covering the page."""
    def _starts(total: int) -> list[int]:
        if total <= _CROP:
            return [0]
        step = _CROP - _OVERLAP
        out = list(range(0, total - _CROP, step))
        out.append(total - _CROP)
        return out
    return [(x, y, min(width, x + _CROP), min(height, y + _CROP))
            for y in _starts(height) for x in _starts(width)]


def _point(v, scale: float, x0: int, y0: int) -> list[float] | None:
    try:
        return [round(x0 + float(v[0]) / scale, 1), round(y0 + float(v[1]) / scale, 1)]
    except (TypeError, ValueError, IndexError):
        return None


def _annotate_crop(_s, crop: np.ndarray, x0: int, y0: int) -> tuple[list, list, object]:
    from agents.extraction.prompts.catalog import FLOW_ANNOTATIONS_V1
    from agents.toolkit import parse_controller_json

    h, w = crop.shape[:2]
    scale = min(1.0, _MAX_EDGE / max(h, w))
    if scale < 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("could not encode crop")
    ch, cw = crop.shape[:2]
    resp = _s.llm.complete_streaming(
        f"Crop size: {cw}x{ch} pixels. Report flow arrows and electric heat tracing.",
        system=FLOW_ANNOTATIONS_V1,
        image_b64=base64.standard_b64encode(buf.tobytes()).decode(),
        media_type="image/png",
        max_tokens=2048,
        force_json=True,
        tier="fast",
    )
    data = parse_controller_json(resp.text) or {}
    arrows, traces = [], []
    for a in data.get("arrows") or []:
        if not isinstance(a, dict) or float(a.get("confidence") or 0) < _MIN_CONFIDENCE:
            continue
        tip, tail = _point(a.get("tip"), scale, x0, y0), _point(a.get("tail"), scale, x0, y0)
        if tip and tail and tip != tail:
            arrows.append({"tip": tip, "tail": tail, "confidence": float(a["confidence"])})
    for t in data.get("heat_trace") or []:
        if not isinstance(t, dict) or float(t.get("confidence") or 0) < _MIN_CONFIDENCE:
            continue
        pts = [p for p in (_point(v, scale, x0, y0) for v in t.get("points") or []) if p]
        if len(pts) >= 2:
            traces.append({"points": pts, "confidence": float(t["confidence"])})
    return arrows, traces, resp


def _dedupe_arrows(arrows: list[dict]) -> list[dict]:
    """Overlapping crops report the same arrowhead twice: keep the surest."""
    kept: list[dict] = []
    for a in sorted(arrows, key=lambda a: -a["confidence"]):
        ax, ay = a["tip"][0] - a["tail"][0], a["tip"][1] - a["tail"][1]
        dup = False
        for k in kept:
            kx, ky = k["tip"][0] - k["tail"][0], k["tip"][1] - k["tail"][1]
            if math.dist(a["tip"], k["tip"]) <= _ARROW_MERGE_PX and ax * kx + ay * ky > 0:
                dup = True
                break
        if not dup:
            kept.append(a)
    return kept


def _dedupe_segments(traces: list[dict]) -> list[list[float]]:
    """Heat-trace runs as [x1, y1, x2, y2] segments, duplicates removed."""
    segs: list[list[float]] = []
    for t in sorted(traces, key=lambda t: -t["confidence"]):
        pts = t["points"]
        for p, q in zip(pts, pts[1:]):
            seg = [p[0], p[1], q[0], q[1]]
            if any((math.dist(p, s[:2]) <= _TRACE_MERGE_PX and math.dist(q, s[2:]) <= _TRACE_MERGE_PX)
                   or (math.dist(p, s[2:]) <= _TRACE_MERGE_PX and math.dist(q, s[:2]) <= _TRACE_MERGE_PX)
                   for s in segs):
                continue
            segs.append(seg)
    return segs


def detect_flow_annotations(_s, image_bytes: bytes) -> dict:
    """{"arrows": [...], "heat_trace": [[x1,y1,x2,y2], ...], "usage": [LLMResponse],
    "crops": n, "failed": k} in the pixel space of `image_bytes`."""
    empty = {"arrows": [], "heat_trace": [], "usage": [], "crops": 0, "failed": 0}
    if cv2 is None or not image_bytes:
        return empty
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return empty
    H, W = img.shape[:2]
    windows = crops(W, H)
    from services.tile_runner import run_ordered
    outcomes = run_ordered(lambda win: _annotate_crop(_s, img[win[1]:win[3], win[0]:win[2]],
                                                      win[0], win[1]), windows)
    arrows, traces, usage, failed = [], [], [], 0
    for win, (result, err) in zip(windows, outcomes):
        if err is not None:
            failed += 1
            logger.warning("Flow annotation crop at (%d,%d) failed: %s", win[0], win[1], err)
            continue
        a, t, resp = result
        arrows.extend(a)
        traces.extend(t)
        usage.append(resp)
    return {"arrows": _dedupe_arrows(arrows), "heat_trace": _dedupe_segments(traces),
            "usage": usage, "crops": len(windows), "failed": failed}
