"""Vision-LLM tiled line tracing — agentic replacement for U-Net + Hough.

Unlike the symbol/text detectors, this task asks a vision model to output
DENSE, precise geometry (potentially 30-80+ pipe runs on a busy tile) rather
than discrete labeled objects — the weakest spot for an LLM among the three
detection modalities. Two design choices exist specifically to compensate:

  1. The driving prompt (line_trace.md) asks for RUNS — ordered polylines
     from one true endpoint to the next corner to the next, not independent
     Hough-style segments. A vision model traces a connected path far more
     reliably than it enumerates disconnected coordinate tuples; each run
     is decomposed into consecutive [x1,y1,x2,y2] segments locally, in
     _run_to_segments(), so the rest of the pipeline (and every downstream
     consumer) still sees the exact flat-segment shape it always has.
  2. A second full-page VERIFICATION pass (line_verify.md, mirroring the
     existing LLM-A/LLM-B self-correction pattern in harness_agent.py) reads
     the stitched candidate runs back against the whole image before
     anything is finalized — catching tile-boundary breaks, missed faint
     lines, and misclassified solid/dashed style that a single per-tile
     pass is prone to.

Every geometric refinement pass that already existed for the U-Net output
(_filter_leader_lines, _split_parallel_lines, _classify_line_style, the
group/merge stitching machinery) is reused UNCHANGED from
line_detection_service.py — those functions treat their input as "a list of
imperfect segments," which is exactly what this module produces, so nothing
about post-processing needed to be rewritten. classify_styles is redundant
here in the common case (line_trace.md already asks for solid/dashed
per-run) but is left available as a CV cross-check in line_agent.py's
qc_node, unchanged.

VISION-CAPABILITY GUARD, NO ML FALLBACK: same policy as
llm_symbol_detection_service.py / llm_text_detection_service.py —
detect_lines_from_bytes checks `llm.supports_vision('fast')` up front and,
if false, returns an error dict rather than guessing. This pipeline is
pure-agentic by design (no U-Net anywhere in the loop) and intentionally
does NOT fall back to the trained model. A commented-out fallback to
services.line_detection_service.detect_lines_from_bytes is kept in place
at that check for future reference, in case a hybrid mode is wanted later.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import time

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from services.geometry.line_geometry import (
    _TILE_SIZE,
    _STRIDE,
    _BLANK_DARK_THRESH,
    _BLANK_MIN_DARK_PX,
    _classify_direction,
    _classify_lines,
    _group_lines,
    _merge_groups,
    _dedup_merge,
    _filter_leader_lines,
    _split_parallel_lines,
)

logger = logging.getLogger(__name__)

_HEAL_MERGE_GAP = 35.0   # same constant name/value as line_detection_service
_MIN_CONFIDENCE = 0.50   # mirrors "below 0.50, don't report" in line_trace.md


def _studio_module():
    import main as _s
    return _s


def _encode_png(img: np.ndarray) -> str:
    ok, buf = cv2.imencode('.png', img)
    if not ok:
        raise RuntimeError("Failed to encode image as PNG")
    return base64.standard_b64encode(buf.tobytes()).decode()


def _parse_json_response(raw_text: str) -> dict:
    """Same JSON-armor priority order used across the extraction pipeline:
    fenced ```json``` block -> main.extract_json -> brace-scan fallback."""
    import re as _re

    parsed = None
    fence = _re.search(r'```json\s*(.*?)\s*```', raw_text, _re.DOTALL)
    if fence:
        try:
            parsed = json.loads(fence.group(1))
        except json.JSONDecodeError:
            parsed = None

    if not isinstance(parsed, dict):
        try:
            parsed = _studio_module().extract_json(raw_text)
        except Exception:
            parsed = None

    if not isinstance(parsed, dict):
        text = _re.sub(r'```[a-zA-Z]*\n?', '', raw_text).strip()
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                parsed = None

    return parsed if isinstance(parsed, dict) else {}


def _run_to_segments(points: list, tx1: int, ty1: int) -> list[list[int]]:
    """Decompose one ordered polyline into consecutive [x1,y1,x2,y2]
    segments, translating from tile-local to page coordinates."""
    segs = []
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        segs.append([int(round(x1)) + tx1, int(round(y1)) + ty1,
                     int(round(x2)) + tx1, int(round(y2)) + ty1])
    return segs


# ── Tiled tracing pass (primary) ──────────────────────────────────────────────

def _tile_coords(img_w: int, img_h: int) -> list[tuple[int, int, int, int]]:
    """Same sliding-window tiling as the U-Net path (_TILE_SIZE/_STRIDE)."""
    tiles = []
    y = 0
    while True:
        y2 = min(y + _TILE_SIZE, img_h)
        y1 = max(0, y2 - _TILE_SIZE)
        x = 0
        while True:
            x2 = min(x + _TILE_SIZE, img_w)
            x1 = max(0, x2 - _TILE_SIZE)
            tiles.append((x1, y1, x2, y2))
            if x2 == img_w:
                break
            x += _STRIDE
        if y2 == img_h:
            break
        y += _STRIDE
    return tiles


def _symbols_in_tile(symbol_boxes: list, tx1: int, ty1: int, tx2: int, ty2: int) -> list[dict]:
    out = []
    for s in symbol_boxes:
        bbox = s.get('bbox') or [0, 0, 0, 0]
        bx1, by1, bx2, by2 = bbox
        if bx2 < tx1 or bx1 > tx2 or by2 < ty1 or by1 > ty2:
            continue
        out.append({
            'type': s.get('type', 'unknown'),
            'bbox': [max(0, bx1 - tx1), max(0, by1 - ty1),
                     min(tx2 - tx1, bx2 - tx1), min(ty2 - ty1, by2 - ty1)],
        })
    return out


_RETRY_NOTE = (
    "RETRY NOTE — a prior pass on this page under-traced relative to how "
    "much ink is on it. Re-scan more conservatively: follow faint or thin "
    "lines further before giving up, treat a line partially occluded by "
    "text or a crossing pipe as still traceable if its path is inferable "
    "on both sides of the occlusion, and double-check EXCLUSIONS is not "
    "being over-applied to a real but unusual-looking pipe run."
)


def _trace_tile(_s, tile: np.ndarray, tx1: int, ty1: int, tile_w: int, tile_h: int,
                symbols_in_tile: list, reprompt: bool = False) -> list[dict]:
    from agents.extraction.prompts.catalog import LINE_TRACE_V1
    from agents.prompts import fill_prompt
    from prompts import LINE_TRACE_OUTPUT_SCHEMA

    if symbols_in_tile:
        sym_lines = [f"  - {s['type']} at box={s['bbox']}" for s in symbols_in_tile]
        symbol_list = "\n".join(sym_lines)
    else:
        symbol_list = "  (none detected in this tile)"

    prompt = fill_prompt(LINE_TRACE_V1, {
        "tile_w": tile_w, "tile_h": tile_h, "symbol_list": symbol_list,
        "retry_note": _RETRY_NOTE if reprompt else "",
    })
    b64 = _encode_png(tile)

    resp = _s.llm.complete_streaming(
        prompt,
        image_b64=b64,
        media_type='image/png',
        max_tokens=8192,
        force_json=True,
        response_schema=LINE_TRACE_OUTPUT_SCHEMA,
        tier='fast',
    )

    parsed = _parse_json_response(resp.text)
    from agents.extraction.schemas import LineTraceResult
    compliant = LineTraceResult.ensure_compliant(parsed)
    return compliant.get('runs', [])


def _trace_all_tiles(_s, img: np.ndarray, W: int, H: int, symbol_boxes: list,
                     reprompt: bool = False) -> list[list[int]]:
    """Runs the tiled tracing pass; returns a flat list of page-space
    [x1,y1,x2,y2] segments, decomposed from each tile's traced runs."""
    tiles = _tile_coords(W, H)
    gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    all_segments: list[list[int]] = []
    skipped_tiles = 0
    inferred_tiles = 0

    # Same split as the symbol detector: sequential blank-skip, concurrent
    # vision calls, aggregation in tile order (services/tile_runner.py).
    jobs = []
    for (tx1, ty1, tx2, ty2) in tiles:
        gray_tile = gray_full[ty1:ty2, tx1:tx2]
        _, dark_mask = cv2.threshold(gray_tile, _BLANK_DARK_THRESH, 255, cv2.THRESH_BINARY_INV)
        if cv2.countNonZero(dark_mask) < _BLANK_MIN_DARK_PX:
            skipped_tiles += 1
            continue
        tile = img[ty1:ty2, tx1:tx2]
        jobs.append((tx1, ty1, tile, _symbols_in_tile(symbol_boxes, tx1, ty1, tx2, ty2)))

    from services.tile_runner import run_ordered
    outcomes = run_ordered(
        lambda job: _trace_tile(_s, job[2], job[0], job[1], job[2].shape[1],
                                job[2].shape[0], job[3], reprompt=reprompt),
        jobs)
    for (tx1, ty1, _tile, _syms), (runs, err) in zip(jobs, outcomes):
        if err is not None:
            logger.error("Tile tracing failed at (%d,%d) — skipping tile", tx1, ty1,
                         exc_info=err)
            runs = []

        for run in runs or []:
            points = run.get('points') or []
            conf = float(run.get('confidence', 0.0) or 0.0)
            if len(points) < 2 or conf < _MIN_CONFIDENCE:
                continue
            all_segments.extend(_run_to_segments(points, tx1, ty1))

        inferred_tiles += 1

    logger.info("Line tracing | tiles=%d skipped=%d inferred=%d -> %d raw segments",
                len(tiles), skipped_tiles, inferred_tiles, len(all_segments))
    return all_segments


def _stitch_segments(segments: list[list[int]]) -> list[list[int]]:
    """Cross-tile stitching: classify H/V/diagonal, group collinear runs
    within tolerance, merge across small gaps. Same machinery
    (_classify_lines/_group_lines/_merge_groups) the U-Net path uses for
    its own tile-overlap healing — a from-scratch call here rather than a
    reuse of _merge_skeleton_lines, since there is no raster skeleton in
    this pipeline to re-vectorize."""
    h, v, diag = _classify_lines(segments)
    h_merged = _merge_groups(_group_lines(h, 2.5), _HEAL_MERGE_GAP)
    v_merged = _merge_groups(_group_lines(v, 2.5), _HEAL_MERGE_GAP)

    out = [[int(round(s)), int(round(y)), int(round(e)), int(round(y))] for y, s, e in h_merged]
    out += [[int(round(x)), int(round(s)), int(round(x)), int(round(e))] for x, s, e in v_merged]
    out += [[int(round(d[0])), int(round(d[1])), int(round(d[2])), int(round(d[3]))] for d in diag]

    # _dedup_merge collapses any remaining near-duplicate collinear segments
    # left by overlapping tiles tracing the same pipe twice.
    return _dedup_merge(out)


# ── Full-page verification pass ───────────────────────────────────────────────

def _format_candidate_runs(segments: list[list[int]]) -> tuple[str, dict]:
    """Each stitched segment becomes its own single-span 'run' for the
    verifier — the verify prompt is free to merge/delete/extend these, but
    doesn't need to know about the tile-tracing internals that produced
    them, matching the candidate-list convention CV_CONNECTIONS_PROMPT
    already uses for edges."""
    lines = []
    run_lookup: dict[str, list[int]] = {}
    for i, seg in enumerate(segments, 1):
        rid = f"run{i}"
        run_lookup[rid] = seg
        d = _classify_direction(*seg)
        lines.append(f"  {rid} ({seg[0]},{seg[1]})->({seg[2]},{seg[3]})  {d}")
    return "\n".join(lines) if lines else "  (no candidate runs)", run_lookup


def _verify_runs(_s, image_bytes: bytes, segments: list[list[int]]) -> list[dict]:
    from agents.extraction.prompts.catalog import LINE_VERIFY_V1
    from agents.prompts import fill_prompt
    from prompts import LINE_VERIFY_OUTPUT_SCHEMA

    candidate_text, run_lookup = _format_candidate_runs(segments)
    prompt = fill_prompt(LINE_VERIFY_V1, {"candidate_runs": candidate_text})
    b64 = base64.standard_b64encode(image_bytes).decode()

    resp = _s.llm.complete_streaming(
        prompt,
        image_b64=b64,
        media_type='image/png',
        max_tokens=16384,
        force_json=True,
        response_schema=LINE_VERIFY_OUTPUT_SCHEMA,
        tier='smart',
    )

    parsed = _parse_json_response(resp.text)
    from agents.extraction.schemas import LineVerifyResult
    compliant = LineVerifyResult.ensure_compliant(parsed)
    return compliant.get('runs', [])


def _verified_runs_to_segments(verified_runs: list[dict]) -> tuple[list[list[int]], list[str]]:
    segments = []
    styles = []
    for run in verified_runs:
        points = run.get('points') or []
        if len(points) < 2:
            continue
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            segments.append([int(round(x1)), int(round(y1)),
                             int(round(x2)), int(round(y2))])
            styles.append(run.get('style', 'solid'))
    return segments, styles


# ── Main entry point ──────────────────────────────────────────────────────────

def detect_lines_from_bytes(image_bytes: bytes, symbol_boxes: list = None,
                            output_dir: str = None, base_name: str = None,
                            reprompt: bool = False) -> dict:
    """Vision-LLM line tracing on raw image bytes.

    Signature and return shape match services.line_detection_service's
    function of the same name: {'long_lines', 'connected_lines',
    'signal_lines', 'count', 'json_path', 'image_path'} (or {'error', ...}
    on failure) — line_agent.py's `_call_lines` needs only an import swap.
    `reprompt=True` is the agentic equivalent of "lower the binarization
    threshold": it appends a stricter re-scan instruction to the tracing
    prompt instead of adjusting a CV parameter — see retry_reprompt in
    line_agent.py.
    """
    if not image_bytes:
        return {'error': 'No image data provided',
                'long_lines': [], 'connected_lines': [], 'signal_lines': []}

    if cv2 is None:
        return {'error': 'opencv-python not installed',
                'long_lines': [], 'connected_lines': [], 'signal_lines': []}

    _s = _studio_module()
    if not getattr(_s, 'llm', None):
        return {'error': 'LLM provider not available',
                'long_lines': [], 'connected_lines': [], 'signal_lines': []}

    if not _s.llm.supports_vision('fast'):
        # No ML fallback — this pipeline is pure-agentic by design (no
        # U-Net anywhere in the loop). A model that can't see must fail
        # loudly here rather than silently detouring through the trained
        # segmentation model, so the caller finds out immediately instead
        # of unknowingly running on the ML path. Point llm_provider / the
        # fast-tier model at a vision-capable model (Anthropic/Gemini/
        # OpenAI, or an Ollama vision family — see _OLLAMA_VISION_FAMILIES
        # in adapters/llm_ollama.py) to use this detector.
        return {
            'error': (
                "Configured LLM provider/model has no vision support for "
                "the 'fast' tier — agentic line detection requires a "
                "vision-capable model and has no ML fallback by design."
            ),
            'long_lines': [], 'connected_lines': [], 'signal_lines': [],
        }

        # No ML fallback exists. Detection in this application is pure LLM;
        # a non-vision model is a misconfiguration to fix, not a condition to
        # route around. See services/detection_router.py.

    npimg = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img_bgr is None:
        return {'error': 'Failed to decode image',
                'long_lines': [], 'connected_lines': [], 'signal_lines': []}

    H, W = img_bgr.shape[:2]
    symbol_boxes = symbol_boxes or []

    try:
        # Pass 1: tiled tracing -> raw page-space segments.
        raw_segments = _trace_all_tiles(_s, img_bgr, W, H, symbol_boxes, reprompt=reprompt)

        # Pass 2: cross-tile stitching (collinear group/merge + dedup).
        stitched = _stitch_segments(raw_segments)

        # Pass 3: full-page verification against the whole image.
        verified_runs = _verify_runs(_s, image_bytes, stitched)
        verified_segments, verified_styles = _verified_runs_to_segments(verified_runs)
        if not verified_segments:
            # Verification returned nothing usable — degrade to the
            # stitched candidate list rather than losing everything.
            verified_segments = stitched
            verified_styles = ['solid'] * len(stitched)

        # Pass 4: symbol-aware geometric refinement — the SAME functions
        # line_agent.py's qc_node already applies to U-Net output.
        sym_box_tuples = [tuple(s['bbox']) for s in symbol_boxes if s.get('bbox')]
        if sym_box_tuples:
            verified_segments = _filter_leader_lines(verified_segments, sym_box_tuples)

        # Split by style (already known from the verify pass) into
        # long/connected/signal buckets, matching the U-Net path's
        # length-threshold split, plus style-based signal_lines routing.
        long_lines, connected_lines, signal_lines = [], [], []
        style_by_seg = {tuple(s): st for s, st in zip(verified_segments, verified_styles)}
        for seg in verified_segments:
            x1, y1, x2, y2 = seg
            if x1 == x2 and y1 == y2:
                continue   # zero-length artifact
            length = math.hypot(x2 - x1, y2 - y1)
            style = style_by_seg.get(tuple(seg), 'solid')
            if style == 'dashed' and length >= 35:
                signal_lines.append(seg)
            elif length >= 35:
                long_lines.append(seg)
            else:
                connected_lines.append(seg)

    except Exception as exc:
        logger.exception("Agentic line detection failed: %s", exc)
        return {'error': f'Line detection error: {exc}',
                'long_lines': [], 'connected_lines': [], 'signal_lines': []}

    # Save outputs — same JSON/PNG shape as the U-Net path.
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'detections')
    os.makedirs(output_dir, exist_ok=True)
    ts = base_name or f'lines_{int(time.time())}'
    json_path = os.path.join(output_dir, f'{ts}_line.json')
    image_path = os.path.join(output_dir, f'{ts}_line.png')

    with open(json_path, 'w', encoding='utf-8') as fp:
        json.dump({'long_lines': long_lines, 'connected_lines': connected_lines,
                   'signal_lines': signal_lines}, fp, indent=2)

    try:
        annotated = img_bgr.copy()
        for x1, y1, x2, y2 in long_lines:
            d = _classify_direction(x1, y1, x2, y2)
            color = (255, 0, 0) if d == 'horizontal' else (0, 0, 255) if d == 'vertical' else (0, 180, 0)
            cv2.line(annotated, (x1, y1), (x2, y2), color, 2)
        for x1, y1, x2, y2 in connected_lines:
            cv2.line(annotated, (x1, y1), (x2, y2), (0, 200, 100), 1)
        for x1, y1, x2, y2 in signal_lines:
            cv2.line(annotated, (x1, y1), (x2, y2), (0, 165, 255), 2, lineType=cv2.LINE_AA)
        cv2.imwrite(image_path, annotated)
    except Exception:
        pass

    total = len(long_lines) + len(connected_lines)
    logger.info("Agentic line detection complete: %d long + %d connected + %d signal = %d total",
               len(long_lines), len(connected_lines), len(signal_lines),
               total + len(signal_lines))
    return {
        'long_lines': long_lines,
        'connected_lines': connected_lines,
        'signal_lines': signal_lines,
        'count': total,
        'json_path': json_path,
        'image_path': image_path,
    }
