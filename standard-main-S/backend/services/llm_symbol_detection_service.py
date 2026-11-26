"""Vision-LLM tiled symbol detection — agentic replacement for YOLOv8.

Same tiling/blank-skip/NMS/merge geometry as detection_service.py (imported,
not duplicated); the only thing that changes is what reads each tile. Where
`process_detect_symbols` calls `model.predict(batch)`, this module makes one
`llm.complete_streaming(...)` vision call per tile against symbol_detect.md
and parses its JSON `detections` list.

Drop-in for services.detection_service.process_detect_symbols: same
signature, same return shape (`detections` entries carry `type`, `bbox`,
`score`, `editable`), so symbol_agent.py's `_call_detection` needs only an
import swap — nothing downstream (text/line agents, LLM A/B, cv_coordination)
changes.

Confidence is the LLM's own self-reported, calibration-guided number from
the prompt (see CONFIDENCE CALIBRATION in symbol_detect.md) — there is no
trained softmax score to fall back on, so the QC controller's confidence-
based metrics (low_conf_fraction, retry_lower_conf) now reflect prompted
self-assessment rather than a model's calibrated probability.

VISION-CAPABILITY GUARD, NO ML FALLBACK: this whole approach only works if
the configured provider/model can actually see the tile it's sent — some
providers (most notably Ollama pointed at a text-only local model) accept
an image parameter without complaint and just ignore it, producing
confident-looking but entirely hallucinated detections instead of an
error. Before doing any tile work, process_detect_symbols checks
`llm.supports_vision('fast')` and, if false, returns an error dict rather
than guessing — this pipeline is pure-agentic by design (no trained
detector anywhere in the loop) and intentionally does NOT fall back to
YOLOv8 when vision is unavailable. A commented-out fallback to
services.detection_service.process_detect_symbols is kept in place at
that check for future reference, in case a hybrid mode is wanted later.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from services.geometry.symbol_geometry import (
    _BLANK_DARK_THRESH,
    _BLANK_MIN_DARK_PX,
    _TILE_SIZE,
    _class_aware_nms,
    _merge_boxes,
    _tile_coords,
)

logger = logging.getLogger(__name__)

# Confidence floor mirrors the prompt's "below 0.50, don't output the box at
# all" instruction — kept here too as a hard backstop against a model that
# ignores the instruction and reports a low-confidence box anyway.
_MIN_CONFIDENCE = 0.50


def _studio_module():
    import main as _s
    return _s


def _encode_tile_png(tile: np.ndarray) -> str:
    ok, buf = cv2.imencode('.png', tile)
    if not ok:
        raise RuntimeError("Failed to encode tile as PNG")
    return base64.standard_b64encode(buf.tobytes()).decode()


def _parse_tile_response(raw_text: str) -> list[dict]:
    """Same JSON-armor priority order as extraction_cli/llm_verification.py:
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

    if not isinstance(parsed, dict):
        return []

    from agents.extraction.schemas import SymbolDetectResult
    compliant = SymbolDetectResult.ensure_compliant(parsed)
    return compliant.get('detections', [])


def _detect_tile(_s, tile: np.ndarray, tx1: int, ty1: int, tile_w: int, tile_h: int,
                  retry_note: str = '') -> list[dict]:
    from agents.extraction.prompts.catalog import SYMBOL_DETECT_V1
    from agents.prompts import fill_prompt
    from prompts import SYMBOL_DETECT_OUTPUT_SCHEMA

    prompt = fill_prompt(SYMBOL_DETECT_V1,
                         {"tile_w": tile_w, "tile_h": tile_h, "retry_note": retry_note})
    b64 = _encode_tile_png(tile)

    # Every tile is padded to _TILE_SIZE, so the filled instructions are the
    # same for every tile in a pass: send them as the system prompt, which
    # providers that support prompt caching can reuse across the whole page.
    resp = _s.llm.complete_streaming(
        "Detect the symbols in this tile, following the instructions.",
        system=prompt,
        image_b64=b64,
        media_type='image/png',
        max_tokens=8192,
        force_json=True,
        response_schema=SYMBOL_DETECT_OUTPUT_SCHEMA,
        tier='fast',
    )

    raw_detections = _parse_tile_response(resp.text)

    out = []
    for det in raw_detections:
        bbox = det.get('bbox')
        conf = float(det.get('confidence', 0.0) or 0.0)
        dtype = det.get('type')
        if not dtype or not bbox or len(bbox) != 4 or conf < _MIN_CONFIDENCE:
            continue
        bx1, by1, bx2, by2 = bbox
        # Clip to tile bounds, then translate to page coordinates.
        bx1 = max(0.0, min(float(bx1), tile_w))
        by1 = max(0.0, min(float(by1), tile_h))
        bx2 = max(0.0, min(float(bx2), tile_w))
        by2 = max(0.0, min(float(by2), tile_h))
        if bx2 <= bx1 or by2 <= by1:
            continue
        out.append({
            'type': dtype,
            'bbox': [int(bx1) + tx1, int(by1) + ty1,
                     int(bx2) + tx1, int(by2) + ty1],
            'score': conf,
            'editable': True,
        })
    return out


# ── Zoom-in refinement ───────────────────────────────────────────────────────
#
# A vision model localises poorly on a busy 640px tile: boxes drift, and faint
# or crowded symbols come back at low confidence. For every detection below
# _REFINE_BELOW this pass sends a tight, enlarged crop around the box and asks
# only "is this symbol here, and where exactly?". A confirmed box is tightened
# and its confidence raised; a confident "not present" halves the score so the
# symbol QC controller (low_conf_fraction) can act on it. Nothing is deleted
# here. Bounded by _REFINE_MAX per page, runs on the shared tile pool, and can
# be switched off with STUDIO_ZOOM_REFINE=off.

_REFINE_BELOW = 0.80
_REFINE_MAX = 60
_REFINE_MIN_CROP_PX = 96
_REFINE_UPSCALE_UNDER_PX = 160
_REFINE_MIN_IOU = 0.20


def _refine_enabled() -> bool:
    return (os.getenv("STUDIO_ZOOM_REFINE") or "on").strip().lower() not in ("off", "0", "false", "no")


def _crop_for(img: np.ndarray, bbox: list) -> tuple[np.ndarray, int, int, float]:
    """Padded, clipped, possibly enlarged crop: (crop, x0, y0, scale)."""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    pad = max(24, int(0.5 * max(x2 - x1, y2 - y1)))
    cx0, cy0 = max(0, x1 - pad), max(0, y1 - pad)
    cx1, cy1 = min(W, x2 + pad), min(H, y2 + pad)
    if cx1 - cx0 < _REFINE_MIN_CROP_PX:
        grow = (_REFINE_MIN_CROP_PX - (cx1 - cx0)) // 2 + 1
        cx0, cx1 = max(0, cx0 - grow), min(W, cx1 + grow)
    if cy1 - cy0 < _REFINE_MIN_CROP_PX:
        grow = (_REFINE_MIN_CROP_PX - (cy1 - cy0)) // 2 + 1
        cy0, cy1 = max(0, cy0 - grow), min(H, cy1 + grow)
    crop = img[cy0:cy1, cx0:cx1]
    scale = 1.0
    if max(crop.shape[:2]) < _REFINE_UPSCALE_UNDER_PX:
        scale = 2.0
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return crop, cx0, cy0, scale


def _refine_one(_s, img: np.ndarray, det: dict) -> dict:
    """The refined copy of one detection. Raises on provider/parse failure."""
    from agents.extraction.prompts.catalog import SYMBOL_REFINE_V1
    from agents.toolkit import box_iou, parse_controller_json

    crop, x0, y0, scale = _crop_for(img, det["bbox"])
    ch, cw = crop.shape[:2]
    resp = _s.llm.complete_streaming(
        f"Candidate symbol type: {det.get('type')}. Crop size: {cw}x{ch} pixels.",
        system=SYMBOL_REFINE_V1,
        image_b64=_encode_tile_png(crop),
        media_type='image/png',
        max_tokens=512,
        force_json=True,
        tier='fast',
    )
    verdict = parse_controller_json(resp.text) or {}
    conf = float(verdict.get("confidence") or 0.0)
    out = dict(det)
    if verdict.get("present") and isinstance(verdict.get("bbox"), list) and len(verdict["bbox"]) == 4:
        bx1, by1, bx2, by2 = [float(v) for v in verdict["bbox"]]
        bx1, bx2 = sorted((max(0.0, min(bx1, cw)), max(0.0, min(bx2, cw))))
        by1, by2 = sorted((max(0.0, min(by1, ch)), max(0.0, min(by2, ch))))
        if bx2 - bx1 >= 4 and by2 - by1 >= 4:
            page_box = [int(x0 + bx1 / scale), int(y0 + by1 / scale),
                        int(x0 + bx2 / scale), int(y0 + by2 / scale)]
            # A refined box that barely overlaps the original is a different
            # object in the crop, not a better box for this one.
            if box_iou(page_box, det["bbox"]) >= _REFINE_MIN_IOU:
                out["bbox"] = page_box
        out["score"] = max(float(det.get("score", 0.0)), conf)
        out["refined"] = "confirmed"
    elif verdict.get("present") is False and conf >= 0.80:
        out["score"] = round(float(det.get("score", 0.0)) * 0.5, 3)
        out["refined"] = "doubted"
    else:
        out["refined"] = "inconclusive"
    return out


def _refine_detections(_s, img: np.ndarray, detections: list[dict]) -> tuple[list[dict], dict]:
    """Refine low-confidence detections; return (detections, stats)."""
    stats = {"candidates": 0, "confirmed": 0, "doubted": 0, "inconclusive": 0, "failed": 0}
    if not _refine_enabled() or not detections:
        return detections, stats
    order = sorted((i for i, d in enumerate(detections)
                    if float(d.get("score", 1.0)) < _REFINE_BELOW),
                   key=lambda i: float(detections[i].get("score", 0.0)))[:_REFINE_MAX]
    stats["candidates"] = len(order)
    if not order:
        return detections, stats
    from services.tile_runner import run_ordered
    outcomes = run_ordered(lambda i: _refine_one(_s, img, detections[i]), order)
    refined = list(detections)
    for idx, (result, err) in zip(order, outcomes):
        if err is not None or result is None:
            stats["failed"] += 1
            continue
        refined[idx] = result
        stats[result.get("refined", "inconclusive")] += 1
    return refined, stats


_RETRY_NOTE = (
    "RETRY NOTE — a prior pass on this page under-detected relative to how "
    "much ink is on it. Re-scan more conservatively: widen your definition "
    "of 'partially visible' at tile edges, treat any circle/bowtie/polygon "
    "with a pipe touching it as a candidate even if partially occluded by "
    "text or hatching, and re-read EXCLUSIONS to confirm you are not "
    "over-applying it to a real but unusual-looking symbol."
)


def process_detect_symbols(
    contents: bytes,
    original_filename: str = None,
    diagram_type: str = None,
    output_dir: str = None,
    reprompt: bool = False,
) -> dict:
    """Run vision-LLM tiled symbol detection on raw image bytes.

    Signature and return shape match services.detection_service's function
    of the same name (`detections`, `image_path`, `json_path`, `image_size`,
    `error` on failure) — `diagram_type` is accepted for call-site parity
    but has no effect here (there is no separate trained pid/pfd model to
    select between). `reprompt=True` is the agentic equivalent of "try a
    different model": it appends a stricter re-scan instruction to the
    prompt instead of swapping weights — see retry_reprompt in
    symbol_agent.py.
    """
    if not contents:
        return {'error': 'No image data provided', 'detections': []}

    if cv2 is None:
        return {'error': 'opencv-python not installed', 'detections': []}

    _s = _studio_module()
    if not getattr(_s, 'llm', None):
        return {'error': 'LLM provider not available', 'detections': []}

    if not _s.llm.supports_vision('fast'):
        # No ML fallback — this pipeline is pure-agentic by design (no
        # trained detector in the loop). A model that can't see must fail
        # loudly here rather than silently detouring through YOLOv8, so
        # the caller finds out immediately instead of unknowingly running
        # on the ML path. Point llm_provider / the fast-tier model at a
        # vision-capable model (Anthropic/Gemini/OpenAI, or an Ollama
        # vision family — see _OLLAMA_VISION_FAMILIES in adapters/llm_ollama.py)
        # to use this detector.
        return {
            'error': (
                "Configured LLM provider/model has no vision support for "
                "the 'fast' tier — agentic symbol detection requires a "
                "vision-capable model and has no ML fallback by design."
            ),
            'detections': [],
        }

        # No ML fallback exists. Detection in this application is pure LLM;
        # a non-vision model is a misconfiguration to fix, not a condition to
        # route around. See services/detection_router.py.

    npimg = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img is None:
        return {'error': 'Failed to decode image', 'detections': []}

    H, W = img.shape[:2]
    tiles = _tile_coords(W, H)
    gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    all_detections: list[dict] = []
    annotated = img.copy()
    skipped_tiles = 0
    inferred_tiles = 0

    # Blank-skip and padding are cheap and stay sequential; the vision calls
    # run concurrently (services/tile_runner.py) and are aggregated in tile
    # order, so the result is identical to the former one-at-a-time loop.
    jobs = []
    for (tx1, ty1, tx2, ty2) in tiles:
        gray_tile = gray_full[ty1:ty2, tx1:tx2]
        _, dark_mask = cv2.threshold(gray_tile, _BLANK_DARK_THRESH, 255, cv2.THRESH_BINARY_INV)
        if cv2.countNonZero(dark_mask) < _BLANK_MIN_DARK_PX:
            skipped_tiles += 1
            continue

        tile = img[ty1:ty2, tx1:tx2]
        ph = _TILE_SIZE - tile.shape[0]
        pw = _TILE_SIZE - tile.shape[1]
        if ph > 0 or pw > 0:
            tile = cv2.copyMakeBorder(tile, 0, ph, 0, pw,
                                      cv2.BORDER_CONSTANT, value=(255, 255, 255))
        jobs.append((tx1, ty1, tile))

    from services.tile_runner import run_ordered
    retry_note = _RETRY_NOTE if reprompt else ''
    outcomes = run_ordered(
        lambda job: _detect_tile(_s, job[2], job[0], job[1], job[2].shape[1],
                                 job[2].shape[0], retry_note=retry_note),
        jobs)
    for (tx1, ty1, _tile), (tile_detections, err) in zip(jobs, outcomes):
        if err is not None:
            logger.error("Tile detection failed at (%d,%d) — skipping tile", tx1, ty1,
                         exc_info=err)
            tile_detections = []
        all_detections.extend(tile_detections or [])
        inferred_tiles += 1

    logger.info("LLM tiling | tiles=%d skipped=%d inferred=%d",
                len(tiles), skipped_tiles, inferred_tiles)

    # Same post-processing as the YOLO path: same-class NMS across the whole
    # page, then merge same-class overlaps left by adjacent-tile overlap.
    # Cross-class NMS is skipped here too — resolved by the downstream LLM
    # verification pass (llm_a_node), same division of labor as before.
    after_nms = _class_aware_nms(all_detections)
    final = _merge_boxes(after_nms)
    final, refine_stats = _refine_detections(_s, img, final)
    if refine_stats["candidates"]:
        logger.info("Zoom-in refinement | %s", refine_stats)

    for det in final:
        x1, y1, x2, y2 = det['bbox']
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 160, 220), 2)
        cv2.putText(annotated, f"{det['type']} {det['score']:.2f}",
                    (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 160, 220), 1)

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'detections')
    os.makedirs(output_dir, exist_ok=True)

    base = os.path.splitext(original_filename)[0] if original_filename else f'symbol_{int(time.time())}'
    json_path = os.path.join(output_dir, f'{base}_symbol.json')
    image_path = os.path.join(output_dir, f'{base}_symbol.png')

    with open(json_path, 'w', encoding='utf-8') as fp:
        json.dump({'detections': final, 'image_size': {'width': W, 'height': H}}, fp, indent=2)
    cv2.imwrite(image_path, annotated)

    return {
        'detections': final,
        'count': len(final),
        'image_path': image_path,
        'json_path': json_path,
        'image_size': {'width': W, 'height': H},
    }
