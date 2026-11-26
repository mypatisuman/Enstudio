"""Vision-LLM text reading — agentic replacement for RapidOCR.

Same crop geometry / zone-radius / tiling scaffolding as
text_detection_service.py (imported, not duplicated); the only thing that
changes is what reads each crop or tile. Where the original calls
`_ocr_engine(crop)` / `_ocr_engine(tile)`, this module makes one
`llm.complete_streaming(...)` vision call per crop/tile against text_read.md
(symbol-crop path) or text_read_tile.md (full-image tiling fallback).

Drop-in for services.text_detection_service.detect_text_from_bytes: same
signature, same return shape (`texts` entries carry `text`, `bbox`, `score`,
`nearest_symbol`, `editable`), so text_agent.py's `_call_ocr` needs only an
import swap.

ocr_corrector.py's regex-based digit substitution (O->0, I->1, ...) is
deliberately NOT used here — those are corrections for classifier-style OCR
character confusions, and a vision LLM reading tag shapes directly is not
prone to that same failure mode. There is no ML/CV step anywhere in this
module — every read is a vision-LLM call, including the fallback path's
title-block/legend filtering, which is done by prompt instruction
(text_read_tile.md EXCLUSIONS) rather than post-hoc keyword-zone geometry.

VISION-CAPABILITY GUARD, NO ML FALLBACK: this only works if the configured
provider/model can actually see the crop/tile it's sent — see the matching
note in services/llm_symbol_detection_service.py for why that's not
guaranteed (Ollama pointed at a text-only model is the concrete failure
case in this codebase). detect_text_from_bytes checks
`llm.supports_vision('fast')` up front and, if false, returns an error
dict rather than guessing — this pipeline is pure-agentic by design (no
OCR engine anywhere in the loop) and intentionally does NOT fall back to
RapidOCR when vision is unavailable. A commented-out fallback to
services.text_detection_service.detect_text_from_bytes is kept in place
at that check for future reference, in case a hybrid mode is wanted later.
"""
from __future__ import annotations

import base64
import json
import logging
import os

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from services.geometry.text_geometry import (
    _CONNECTOR_TYPES,
    _EQUIPMENT_TYPES,
    _TAG_ZONE_PX,
    _TAG_ZONE_PX_CONN,
    _TAG_ZONE_PX_EQUIP,
    _TILE_SIZE,
    _OVERLAP,
    _REQUIRES_ISA_TAG,
    _clean_leading_symbols,
    _compute_iom,
    _dedup_text_boxes,
    _is_valid_text,
    _merge_vertical_boxes,
)

logger = logging.getLogger(__name__)

# Overridable module constants — text_agent.py's retry_bigger_crops action
# monkeypatches these directly for the duration of a retry call, same
# mechanism the original RapidOCR-based service used.
_CROP_UPSCALE = 2.0
_CROP_PAD = 50

# Confidence floor — mirrors "below 0.50, don't report" in both prompts.
_MIN_CONFIDENCE = 0.50


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


# ── Symbol-crop path (primary) ────────────────────────────────────────────────

def _read_crop(_s, crop: np.ndarray, symbol_type: str) -> dict:
    from agents.extraction.prompts.catalog import TEXT_READ_V1
    from agents.prompts import fill_prompt
    from prompts import TEXT_READ_OUTPUT_SCHEMA

    stype_key = symbol_type.lower().replace(' ', '_')
    tag_note = (
        "This symbol type requires a structured ISA tag — a plain word or "
        "fragment that doesn't match that structure is still worth "
        "reporting exactly as read; do not force it into tag shape."
        if stype_key in _REQUIRES_ISA_TAG else
        "This symbol type does not strictly require an ISA-format tag — "
        "equipment names, service descriptions, or plain labels are normal."
    )
    prompt = fill_prompt(TEXT_READ_V1,
                         {"symbol_type": symbol_type, "tag_required_note": tag_note})
    b64 = _encode_png(crop)

    resp = _s.llm.complete_streaming(
        prompt,
        image_b64=b64,
        media_type='image/png',
        max_tokens=1024,
        force_json=True,
        response_schema=TEXT_READ_OUTPUT_SCHEMA,
        tier='fast',
    )

    parsed = _parse_json_response(resp.text)
    from agents.extraction.schemas import TextReadResult
    return TextReadResult.ensure_compliant(parsed)


def _ocr_crop_llm(_s, img: np.ndarray, sym: dict, W: int, H: int) -> dict | None:
    """Vision-LLM equivalent of the original _ocr_crop closure: one symbol
    in, one assembled tag entry out (or None if nothing legible)."""
    sb = sym.get('bbox', [])
    stype = sym.get('type', 'unknown')
    if len(sb) < 4:
        return None
    sx1, sy1, sx2, sy2 = int(sb[0]), int(sb[1]), int(sb[2]), int(sb[3])
    cx1 = max(0, sx1 - _CROP_PAD)
    cy1 = max(0, sy1 - _CROP_PAD)
    cx2 = min(W, sx2 + _CROP_PAD)
    cy2 = min(H, sy2 + _CROP_PAD)
    crop = img[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None

    sym_w, sym_h = sx2 - sx1, sy2 - sy1
    max_dim = max(sym_w, sym_h)
    stype_key = stype.lower().replace(' ', '_')
    is_equip = stype_key in _EQUIPMENT_TYPES or stype_key in _CONNECTOR_TYPES
    if is_equip:
        scale = 1.0
    elif max_dim >= 150:
        scale = 0.75
    elif max_dim >= 80:
        scale = 2.0
    else:
        scale = _CROP_UPSCALE

    try:
        crop_up = cv2.resize(crop, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)
        reading = _read_crop(_s, crop_up, stype)
    except Exception as exc:
        logger.warning("Symbol crop read failed (%s): %s", stype, exc)
        return None

    if not reading.get('legible'):
        return None
    text = _clean_leading_symbols(str(reading.get('text', '')).strip())
    if not _is_valid_text(text):
        return None
    conf = float(reading.get('confidence', 0.0) or 0.0)
    if conf < _MIN_CONFIDENCE:
        return None

    if stype_key in _REQUIRES_ISA_TAG and reading.get('kind') == 'destination_text':
        text = stype

    return {
        'text': text,
        'bbox': [sx1, sy1, sx2, sy2],
        'score': round(conf, 4),
        'nearest_symbol': stype,
        'editable': True,
    }


# ── Full-image tiling fallback path ───────────────────────────────────────────

def _read_tile(_s, tile_img: np.ndarray, tile_w: int, tile_h: int) -> list[dict]:
    from agents.extraction.prompts.catalog import TEXT_READ_TILE_V1
    from agents.prompts import fill_prompt
    from prompts import TEXT_READ_TILE_OUTPUT_SCHEMA

    prompt = fill_prompt(TEXT_READ_TILE_V1, {"tile_w": tile_w, "tile_h": tile_h})
    b64 = _encode_png(tile_img)

    resp = _s.llm.complete_streaming(
        prompt,
        image_b64=b64,
        media_type='image/png',
        max_tokens=8192,
        force_json=True,
        response_schema=TEXT_READ_TILE_OUTPUT_SCHEMA,
        tier='fast',
    )

    parsed = _parse_json_response(resp.text)
    from agents.extraction.schemas import TextReadTileResult
    compliant = TextReadTileResult.ensure_compliant(parsed)
    return compliant.get('detections', [])


def _tile_coords_for_ocr(W: int, H: int) -> list[dict]:
    """Same grid-walk as the original fallback path (kept local since the
    original builds tiles inline rather than exposing a helper)."""
    tiles = []
    if H <= _TILE_SIZE and W <= _TILE_SIZE:
        return [{'ox': 0, 'oy': 0, 'x2': W, 'y2': H}]
    stride = _TILE_SIZE - _OVERLAP
    y = 0
    while True:
        y2 = min(y + _TILE_SIZE, H)
        x = 0
        while True:
            x2 = min(x + _TILE_SIZE, W)
            ry = y if (y2 - y) >= _TILE_SIZE // 2 else max(0, y2 - _TILE_SIZE)
            rx = x if (x2 - x) >= _TILE_SIZE // 2 else max(0, x2 - _TILE_SIZE)
            if not any(t['ox'] == rx and t['oy'] == ry for t in tiles):
                tiles.append({'ox': rx, 'oy': ry, 'x2': x2, 'y2': y2})
            if x2 == W:
                break
            x += stride
        if y2 == H:
            break
        y += stride
    return tiles


def _detect_tiles_fallback(_s, img: np.ndarray, W: int, H: int) -> list[dict]:
    tiles = _tile_coords_for_ocr(W, H)
    logger.info("Text: LLM tiling fallback — %d tiles (%dx%d)", len(tiles), W, H)

    raw_results = []
    for tile_meta in tiles:
        ox, oy, x2, y2 = tile_meta['ox'], tile_meta['oy'], tile_meta['x2'], tile_meta['y2']
        tile_img = img[oy:y2, ox:x2]
        try:
            tile_detections = _read_tile(_s, tile_img, tile_img.shape[1], tile_img.shape[0])
        except Exception as exc:
            logger.warning("Text tile read failed at (%d,%d): %s", ox, oy, exc)
            continue

        for det in tile_detections:
            bbox = det.get('bbox')
            conf = float(det.get('confidence', 0.0) or 0.0)
            text = det.get('text')
            if not text or not bbox or len(bbox) != 4 or conf < _MIN_CONFIDENCE:
                continue
            bx1, by1, bx2, by2 = bbox
            bx1 = max(0.0, min(float(bx1), tile_img.shape[1]))
            by1 = max(0.0, min(float(by1), tile_img.shape[0]))
            bx2 = max(0.0, min(float(bx2), tile_img.shape[1]))
            by2 = max(0.0, min(float(by2), tile_img.shape[0]))
            if bx2 <= bx1 or by2 <= by1:
                continue
            text_clean = _clean_leading_symbols(str(text).strip())
            abs_cx = (bx1 + bx2) / 2 + ox
            abs_cy = (by1 + by2) / 2 + oy
            is_edge = (abs_cx < W * 0.04 or abs_cx > W * 0.96
                      or abs_cy < H * 0.04 or abs_cy > H * 0.96)
            if is_edge and len(text_clean) <= 3:
                continue
            if not _is_valid_text(text_clean):
                continue
            raw_results.append({
                'text': text_clean,
                'bbox': [int(bx1) + ox, int(by1) + oy, int(bx2) + ox, int(by2) + oy],
                'score': round(conf, 4),
            })

    if not raw_results:
        return []

    # Same post-processing as the RapidOCR fallback path, minus the
    # title-block/bottom-strip filters — those are now applied by the
    # tile prompt's own EXCLUSIONS instruction — and minus ocr_corrector
    # (see module docstring).
    raw_results = _dedup_text_boxes(raw_results, iom_thresh=0.3)
    raw_results = _merge_vertical_boxes(raw_results, vertical_thresh=40)
    return raw_results


# ── Main entry point ──────────────────────────────────────────────────────────

def detect_text_from_bytes(image_bytes: bytes, symbol_boxes: list = None,
                           output_dir: str = None, base_name: str = None) -> dict:
    """Vision-LLM text reading on raw image bytes.

    Signature and return shape match services.text_detection_service's
    function of the same name.
    """
    if cv2 is None:
        return {'error': 'opencv-python not installed', 'texts': []}

    _s = _studio_module()
    if not getattr(_s, 'llm', None):
        return {'error': 'LLM provider not available', 'texts': []}

    if not _s.llm.supports_vision('fast'):
        # No ML fallback — this pipeline is pure-agentic by design (no OCR
        # engine in the loop). A model that can't see must fail loudly
        # here rather than silently detouring through RapidOCR, so the
        # caller finds out immediately instead of unknowingly running on
        # the ML path. Point llm_provider / the fast-tier model at a
        # vision-capable model (Anthropic/Gemini/OpenAI, or an Ollama
        # vision family — see _OLLAMA_VISION_FAMILIES in adapters/llm_ollama.py)
        # to use this detector.
        return {
            'error': (
                "Configured LLM provider/model has no vision support for "
                "the 'fast' tier — agentic text detection requires a "
                "vision-capable model and has no ML fallback by design."
            ),
            'texts': [],
        }

        # No ML fallback exists. Detection in this application is pure LLM;
        # a non-vision model is a misconfiguration to fix, not a condition to
        # route around. See services/detection_router.py.

    npimg = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    if img is None:
        return {'error': 'Failed to decode image for text reading', 'texts': []}

    H, W = img.shape[:2]

    if symbol_boxes:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        raw_results = []
        with ThreadPoolExecutor(max_workers=min(8, len(symbol_boxes))) as pool:
            futures = {pool.submit(_ocr_crop_llm, _s, img, sym, W, H): sym
                      for sym in symbol_boxes}
            for fut in as_completed(futures):
                entry = fut.result()
                if entry is not None:
                    raw_results.append(entry)
        logger.info("Text: symbol-crop pass (%d crops parallel) -> %d assembled tags",
                    len(symbol_boxes), len(raw_results))
        texts = raw_results
    else:
        texts = _detect_tiles_fallback(_s, img, W, H)

    if not texts:
        return {'texts': [], 'count': 0}

    image_path = None
    if output_dir and base_name:
        try:
            annotated = img.copy()
            for t in texts:
                x1, y1, x2, y2 = t['bbox']
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 140, 255), 2)
                cv2.putText(annotated, t['text'], (x1, y1 - 4),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)
            os.makedirs(output_dir, exist_ok=True)
            image_path = os.path.join(output_dir, f'{base_name}_text.png')
            cv2.imwrite(image_path, annotated)
            json_path = os.path.join(output_dir, f'{base_name}_text.json')
            with open(json_path, 'w', encoding='utf-8') as fp:
                json.dump({'texts': texts, 'count': len(texts)}, fp, indent=2)
        except Exception as exc:
            logger.warning("Could not save text annotation files: %s", exc)

    return {'texts': texts, 'count': len(texts), 'image_path': image_path}
