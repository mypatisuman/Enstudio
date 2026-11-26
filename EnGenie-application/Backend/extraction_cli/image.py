"""
extraction_cli/image.py -- CV detection pipeline (YOLO symbols, OCR text,
UNet lines) operating on raster image bytes, plus resize/segment helpers.

Extracted from extract_cli.py (Phase 11), moved verbatim.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .output import emit
from .llm_verification import _cv_seg_touches


_MAX_IMAGE_PX = 4096   # cap longest side after render — keeps tile count manageable


def _resize_image_bytes(image_bytes: bytes, max_px: int = 3000) -> bytes:
    """Resize image so the longest side <= max_px and return PNG bytes.

    Gemini processes up to ~3072px; Claude caps at 1568px regardless.
    Sending at 3000px gives Gemini near-max detail with no internal downsampling,
    while costing nothing extra for Claude (it still sees 1568px either way).
    """
    from PIL import Image as _PILImage
    import io as _io
    img = _PILImage.open(_io.BytesIO(image_bytes))
    long_side = max(img.width, img.height)
    if long_side > max_px:
        scale = max_px / long_side
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         _PILImage.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _run_cv_phase1(image_bytes: bytes, base_name: str, cache_dir: str) -> dict:
    """Phase 1: YOLO symbol detection (must finish before Phase 2)."""
    try:
        # Resolved through the shared router, which only ever returns the
        # vision-LLM detectors. This module is what the desktop app's
        # extract_cli.py path runs, and it used to be hardwired to YOLOv8 —
        # the last place where the classic pipeline could still load a trained
        # model even though detection here is pure LLM.
        from services.detection_router import resolve_backend
        _backend = resolve_backend()
        emit({"stage": "debug",
              "message": f"symbol detection engine: llm ({_backend.reason})",
              "detection_engine": "llm"})
        process_detect_symbols = _backend.detect_symbols
        return process_detect_symbols(
            image_bytes,
            original_filename=base_name,
            diagram_type='pid',
            output_dir=cache_dir,
        )
    except Exception as exc:
        return {'error': str(exc), 'detections': []}


def _check_ultralytics() -> bool:
    """Always False: this application does not use ultralytics.

    Retained only because extraction_cli/__init__.py and extract_cli.py
    re-export the name. Detection is pure LLM -- no YOLOv8 -- so there is
    nothing to probe, and the import itself is deliberately gone: merely
    importing ultralytics pulls in torch, which is exactly the trained-model
    dependency this pipeline is meant not to have.
    """
    return False


def _run_cv_phase2(image_bytes: bytes, symbol_detections: list,
                   cache_dir: str, base_name: str,
                   on_text_done=None) -> tuple[dict, dict, float, float]:
    """Phase 2: OCR text + UNet line detection in parallel.
    on_text_done(text_result): optional callback fired as soon as text OCR
    completes so callers can start LLM A while UNet continues running.
    The callback must be non-blocking (start a thread internally).
    """
    import time
    # phase2 engine — same router as phase 1, so text/lines can never come
    # from a different backend than the symbols they are matched against.
    try:
        from services.detection_router import resolve_backend
        _backend = resolve_backend()
        detect_text_from_bytes = _backend.detect_text
    except Exception as exc:
        return {'error': str(exc), 'texts': []}, {}, 0.0, 0.0

    t_start = time.perf_counter()
    # No OCR engine to initialise: text is read by the vision LLM.

    def _timed(fn, *args):
        r = fn(*args)
        return r, time.perf_counter()

    text_result: dict = {}
    line_result: dict = {}
    text_secs = line_secs = 0.0

    emit({"stage": "cv_text", "status": "running"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        text_fut = pool.submit(_timed, detect_text_from_bytes, image_bytes,
                               symbol_detections, cache_dir, base_name)
        line_fut = None
        try:
            detect_lines_from_bytes = _backend.detect_lines
            # No U-Net to initialise: pipe runs are traced by the vision LLM.
            emit({"stage": "cv_lines", "status": "running",
                  "detection_engine": _backend.engine})
            line_fut = pool.submit(_timed, detect_lines_from_bytes, image_bytes,
                                   symbol_detections, cache_dir, base_name)
        except Exception as line_err:
            emit({"stage": "cv_lines", "status": "complete", "line_count": 0,
                  "line_error": str(line_err), "elapsed_s": 0})

        active = {text_fut: 'text'}
        if line_fut:
            active[line_fut] = 'lines'

        for fut in as_completed(active):
            label = active[fut]
            try:
                res, end = fut.result()
            except Exception as e:
                res, end = {'error': str(e)}, time.perf_counter()
            secs = round(end - t_start, 1)
            if label == 'text':
                text_result, text_secs = res, secs
                emit({"stage": "cv_text", "status": "complete",
                      "text_count": len(res.get('texts', [])),
                      "elapsed_s": secs, "text_error": res.get('error')})
                if on_text_done:
                    on_text_done(text_result)  # non-blocking: starts LLM A in a thread
            else:
                line_result, line_secs = res, secs
                total = (len(res.get('long_lines', [])) +
                         len(res.get('connected_lines', [])) +
                         len(res.get('signal_lines', [])))
                emit({"stage": "cv_lines", "status": "complete",
                      "line_count": total, "elapsed_s": secs,
                      "line_error": res.get('error')})

    return text_result, line_result, text_secs, line_secs


def _segs_to_dicts(long_lines, connected_lines, signal_lines):
    """Convert flat [x1,y1,x2,y2] line lists to the dict format _build_cv_summary expects."""
    def _dir(x1, y1, x2, y2):
        if abs(x2 - x1) > abs(y2 - y1) * 2:
            return 'horizontal'
        if abs(y2 - y1) > abs(x2 - x1) * 2:
            return 'vertical'
        return 'diagonal'

    result = []
    for seg_list, kind in ((long_lines, 'process'), (connected_lines, 'process'), (signal_lines, 'signal')):
        for seg in seg_list:
            x1, y1, x2, y2 = seg[0], seg[1], seg[2], seg[3]
            result.append({'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                           'direction': _dir(x1, y1, x2, y2), 'kind': kind})
    return result


def _filter_degenerate_segments(segments: list, symbols: list,
                                 img_w: int, img_h: int) -> tuple[list, int]:
    """Remove point/zero-length segments and bus-intersection stubs before LLM B.

    Point segments (start ≈ end, length < 0.002 normalised) are line-detector
    artifacts that fired on a junction node, not a real pipe run.
    Bus-intersection stubs (length < 0.005 AND touching > 4 symbols) are manifold
    crossing artifacts.  Both overwhelm the connections model with noise.

    Returns (filtered_segments, n_removed).
    """
    import math
    W = max(img_w, 1)
    H = max(img_h, 1)

    raw_touches = _cv_seg_touches(symbols, segments, W, H)

    clean: list = []
    removed = 0
    for idx, seg in enumerate(segments):
        x1, y1 = seg.get('x1', 0), seg.get('y1', 0)
        x2, y2 = seg.get('x2', 0), seg.get('y2', 0)
        dx = (x2 - x1) / W
        dy = (y2 - y1) / H
        length = math.hypot(dx, dy)
        touch_count = len(raw_touches[idx]) if idx < len(raw_touches) else 0

        if length < 0.002:          # point segment — start ≈ end
            removed += 1
            continue
        if length < 0.005 and touch_count > 4:   # bus-intersection stub
            removed += 1
            continue
        clean.append(seg)

    return clean, removed


def _snap_segments_to_symbols(segments: list, symbols: list, snap_px: int = 18) -> list:
    """Snap segment endpoints to the nearest symbol bbox edge when within snap_px.

    Direction-aware: horizontal segments only snap to left/right edges,
    vertical segments only snap to top/bottom edges. This prevents the
    diagonal-waypoint artifact caused by snapping H-segments to top/bottom bbox edges.

    snap_px was 45 — a flat, generous radius applied to every segment
    regardless of type or length. Engram-Main's connectivity.py learned this
    lesson already: it tightened its own T-junction match from 25px to 10px
    specifically "to avoid false matches with nearby lines", and reserves any
    tolerance bigger than ~15-20px for cases with independent corroborating
    evidence (its crossover/bridge match, gated by a detector-provided
    is_bridged flag) — never a blind nearest-symbol guess. 45px was proven
    wide enough to swallow an entire real instrument-tap stub (25-38px long)
    into one wrong symbol, and even 35px let a stub mis-snap across to the
    wrong neighboring instrument instead of stopping at the pipe between
    them. 18px matches ENDPOINT_CLUSTER_TOL_PX's own precision tier
    (connectivity_graph.py) instead of introducing a second magic number.
    """
    import math

    _TOL = 14  # axis tolerance: point must be within this many px of the bbox on the other axis
    _FAR_PX = 40  # wider fallback radius, only used when exactly one symbol qualifies (no ambiguity)

    def _candidates_within(px, py, is_h, radius):
        """All (symbol_index, snap_point, distance) within radius, nearest first."""
        found = []
        for sidx, sym in enumerate(symbols):
            bx1, by1, bx2, by2 = sym.get('bbox', [0, 0, 0, 0])
            if is_h:
                if not (by1 - _TOL <= py <= by2 + _TOL):
                    continue
                pts = [(bx1, py), (bx2, py)]
            else:
                if not (bx1 - _TOL <= px <= bx2 + _TOL):
                    continue
                pts = [(px, by1), (px, by2)]
            for cx, cy in pts:
                d = math.hypot(px - cx, py - cy)
                if d <= radius:
                    found.append((sidx, (cx, cy), d))
        found.sort(key=lambda t: t[2])
        return found

    def _best_match(px, py, is_h):
        """Nearest (symbol_index, snap_point, distance) for one endpoint, or
        (None, None, None) if nothing is within snap_px.

        Falls back to a wider _FAR_PX radius only when exactly one distinct
        symbol qualifies there — an unambiguous long stub (e.g. a real
        instrument tap >18px away) — since the false-merge failure mode this
        radius guards against only happens when candidates compete.
        """
        near = _candidates_within(px, py, is_h, snap_px)
        if near:
            return near[0]
        far = _candidates_within(px, py, is_h, _FAR_PX)
        distinct_syms = {sidx for sidx, _, _ in far}
        if len(distinct_syms) == 1:
            return far[0]
        return None, None, None

    snapped = []
    for seg in segments:
        x1, y1 = seg['x1'], seg['y1']
        x2, y2 = seg['x2'], seg['y2']
        is_h = seg.get('direction') == 'horizontal'
        is_v = seg.get('direction') == 'vertical'

        if is_h or is_v:
            sym1, snap1, d1 = _best_match(x1, y1, is_h)
            sym2, snap2, d2 = _best_match(x2, y2, is_h)

            # Guard against collapsing a short segment to a point: a stub
            # shorter than snap_px (a real, short instrument tap is often
            # only ~25-40px) has BOTH raw ends within range of the SAME
            # nearby symbol whenever its true far target (the main pipe, or
            # another symbol a bit further off) sits just outside snap_px.
            # Snapping each end independently then drags BOTH onto that one
            # symbol's edge, destroying the tap's real extent entirely once
            # the near-zero-length result gets filtered as noise. When both
            # ends resolve to the SAME symbol, only the genuinely closer one
            # is a real touch — snap that one and leave the other at its raw
            # position, so the segment keeps its real length and can still
            # be resolved as a stub/near-miss candidate downstream.
            if sym1 is not None and sym1 == sym2:
                if d1 <= d2:
                    x1, y1 = snap1
                else:
                    x2, y2 = snap2
            else:
                if snap1 is not None:
                    x1, y1 = snap1
                if snap2 is not None:
                    x2, y2 = snap2

        snapped.append({**seg, 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2})
    return snapped


def _run_full_cv(image_bytes: bytes, base_name: str, cache_dir: str,
                 img_w: int = 0, img_h: int = 0,
                 on_text_done=None) -> dict:
    """Run YOLO symbol detection + OCR text + UNet line detection.

    All three outputs are passed to the LLM:
      - YOLO symbols: positions and types
      - OCR text: engineering tags assigned to each symbol
      - UNet line segments: exact pixel coordinates used by LLM as waypoints
    """
    import time

    emit({"stage": "cv_extracting", "status": "running"})
    t_extract = time.perf_counter()

    # Phase 1 — YOLO symbols
    emit({"stage": "cv_symbols", "status": "running"})
    t0 = time.perf_counter()
    sym_result = _run_cv_phase1(image_bytes, base_name, cache_dir)
    symbol_detections = sym_result.get('detections', [])
    emit({"stage": "cv_symbols", "status": "complete",
          "symbol_count": len(symbol_detections),
          "elapsed_s": round(time.perf_counter() - t0, 1),
          "sym_error": sym_result.get('error')})

    if not img_w or not img_h:
        sz = sym_result.get('image_size', {})
        img_w = sz.get('width', 1)
        img_h = sz.get('height', 1)

    # Phase 2 — OCR text + UNet line detection (parallel)
    # Wrap callback so it receives image dimensions resolved from Phase 1
    _cb = None
    if on_text_done:
        _cb = lambda td: on_text_done(td, symbol_detections, img_w, img_h)
    text_result, line_result, _, _ = _run_cv_phase2(
        image_bytes, symbol_detections, cache_dir, base_name, on_text_done=_cb
    )

    # Convert UNet output to normalised snapped segment dicts
    raw_lines: list = []
    if not line_result.get('error') and (
        line_result.get('long_lines') or line_result.get('connected_lines') or line_result.get('signal_lines')
    ):
        long_l = line_result.get('long_lines', [])
        conn_l = line_result.get('connected_lines', [])
        sig_l  = line_result.get('signal_lines', [])

        # Phase 2: annotation-leader removal happens HERE and not inside
        # detect_lines_from_bytes, because it needs OCR text boxes and OCR runs
        # in parallel with UNet — this is the first point where symbols, text
        # and lines all exist. See line_detection_service._filter_leader_lines
        # for why text is required rather than length alone.
        _text_boxes = [t['bbox'] for t in text_result.get('texts', [])
                       if isinstance(t.get('bbox'), (list, tuple)) and len(t['bbox']) >= 4]
        if _text_boxes and symbol_detections:
            try:
                from services.geometry.line_geometry import _filter_leader_lines
                _sym_boxes = [tuple(s['bbox']) for s in symbol_detections
                              if len(s.get('bbox', [])) >= 4]
                _before = len(long_l) + len(conn_l) + len(sig_l)
                long_l = _filter_leader_lines(long_l, _sym_boxes, _text_boxes)
                conn_l = _filter_leader_lines(conn_l, _sym_boxes, _text_boxes)
                # Signal lines are deliberately NOT leader-filtered: a dashed
                # run from an instrument to its controller has exactly the
                # geometry of a leader, and losing it would delete real signal
                # topology.
                _after = len(long_l) + len(conn_l) + len(sig_l)
                if _after != _before:
                    # line_count, not just `remaining`: this event is the last
                    # cv_lines row the UI sees, and it renders any non-running
                    # cv_lines status as `${line_count} lines`. Emitting only
                    # `remaining` left that field undefined, so a run that
                    # detected 87 lines and leader-filtered a few of them
                    # reported "0 lines" while the cached result was correct.
                    emit({"stage": "cv_lines", "status": "filtered",
                          "line_count": _after,
                          "removed_leaders": _before - _after,
                          "remaining": _after})
            except Exception as _lf_err:
                emit({"stage": "debug",
                      "message": f"Leader filtering skipped: {_lf_err}"})

        raw_lines = _segs_to_dicts(long_l, conn_l, sig_l)
        raw_lines = _snap_segments_to_symbols(raw_lines, symbol_detections)

    emit({"stage": "cv_extracting", "status": "complete",
          "elapsed_s": round(time.perf_counter() - t_extract, 1)})

    return {
        'symbols':      symbol_detections,
        'texts':        text_result.get('texts', []),
        'lines':        raw_lines,
        'image_size':   {'width': img_w, 'height': img_h},
        'symbol_image': sym_result.get('image_path', ''),
        'sym_error':    sym_result.get('error'),
        'text_error':   text_result.get('error'),
        'line_error':   line_result.get('error'),
    }
