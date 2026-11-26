"""
extraction_cli/llm_verification.py -- Phase 3 of the pipeline: LLM
verification of CV detections (symbol types, tags, instrument/equipment
grouping) and LLM-based pipe-connection identification.

Extracted from extract_cli.py (Phase 11), moved verbatim.
"""
from __future__ import annotations

import base64
import json
import math
import re

from prompts import (CV_VERIFY_PROMPT as _VERIFY_PROMPT,
                     CV_CONNECTIONS_PROMPT as _CONN_PROMPT,
                     CV_VERIFY_OUTPUT_SCHEMA as _OUTPUT_SCHEMA,
                     CV_CONNECTIONS_OUTPUT_SCHEMA as _CONN_SCHEMA)
from connectivity_graph import build_geometric_connectivity

from .output import emit


class LlmStageError(RuntimeError):
    """An LLM stage did not produce usable output after its retries.

    Raised instead of returning an empty result. Phase 1: `_call_llm_connections`
    used to swallow every parse failure into `{'edges': []}`, so a truncated or
    fence-less LLM-B reply produced a drawing with all its symbols and none of
    its pipes — and the run still reported success. The caller decides what an
    LLM stage failure means for the run (see extraction_cli/status.py); this
    layer's job is only to refuse to invent an empty answer.
    """

    def __init__(self, stage: str, message: str):
        super().__init__(f'{stage}: {message}')
        self.stage = stage


# Bounded retries. Transient 429/500/timeout is the common case and one retry
# clears most of them; an unparseable reply is usually deterministic, so this
# stays small on purpose. Never a loop without a bound.
_LLM_MAX_ATTEMPTS = 3
_LLM_BACKOFF_S = (2.0, 5.0)   # sleep before attempt 2, then before attempt 3


def _with_retries(stage: str, fn):
    """Call `fn()` up to _LLM_MAX_ATTEMPTS times, returning its first success.

    Raises LlmStageError carrying the last error once the attempts run out.
    Emits one NDJSON line per retry so a slow run is explicable from the log
    rather than looking like a hang.
    """
    import time

    last = None
    for attempt in range(1, _LLM_MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:            # noqa: BLE001 — re-raised below
            last = exc
            if attempt < _LLM_MAX_ATTEMPTS:
                delay = _LLM_BACKOFF_S[min(attempt - 1, len(_LLM_BACKOFF_S) - 1)]
                emit({'stage': 'llm_retry', 'llm_stage': stage,
                      'attempt': attempt, 'of': _LLM_MAX_ATTEMPTS,
                      'retry_in_s': delay, 'error': str(exc)[:300]})
                time.sleep(delay)
    raise LlmStageError(stage, f'failed after {_LLM_MAX_ATTEMPTS} attempts: {last}')


def _parse_llm_json(_s, raw: str, label: str) -> dict:
    """Extract a JSON object from an LLM reply, or raise.

    One implementation for both stages. LLM A and LLM B each carried their
    own near-identical three-priority parser; they disagreed only in that A
    raised on failure while B returned `{'edges': []}` — which is precisely
    the bug. Consolidated so the two stages cannot drift apart again.

    Priority 1: a ```json fence (what most providers emit).
    Priority 2: the studio's tolerant extractor (handles truncation).
    Priority 3: strip fences/thinking, take the outermost { ... }.
    """
    result = None

    fence = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
    if fence:
        try:
            result = json.loads(fence.group(1))
        except json.JSONDecodeError:
            result = None

    if not isinstance(result, dict):
        try:
            result = _s.extract_json(raw)
        except Exception:
            result = None

    if not isinstance(result, dict):
        text = re.sub(r'<thinking>.*?</thinking>', '', raw, flags=re.DOTALL).strip()
        text = re.sub(r'```[a-zA-Z]*\n?', '', text).strip()
        start, end = text.find('{'), text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                result = json.loads(text[start:end + 1])
            except json.JSONDecodeError as e:
                raise ValueError(
                    f'{label} returned unparseable JSON: {e}. Raw: {text[:300]}')
        else:
            raise ValueError(
                f'{label} returned no JSON object. Raw: {text[:300]}')

    if not isinstance(result, dict):
        raise ValueError(f'{label} returned non-dict after parsing: {type(result)}')
    return result


def _cv_shared_header(W: int, H: int) -> list:
    return [
        f"IMAGE SIZE: {W}x{H} pixels (original). All pos=(x,y) coordinates below",
        f"are normalised 0.0–1.0 relative to this size.",
        f"To get pixel position: px = x * {W},  py = y * {H}",
        f"",
    ]


def _cv_seg_touches(symbols: list, lines: list, W: int, H: int) -> list[list[str]]:
    """Pre-compute which symbol bbox edge each segment endpoint touches."""
    _EDGE_THRESH_N = 0.015
    _PERP_THRESH_N = 0.008
    seg_touches: list[list[str]] = []
    for l in lines:
        lx1 = l.get('x1', 0) / W;  ly1 = l.get('y1', 0) / H
        lx2 = l.get('x2', 0) / W;  ly2 = l.get('y2', 0) / H
        touches = []
        for si, s in enumerate(symbols):
            sx1, sy1, sx2, sy2 = s.get('bbox', [0, 0, 0, 0])
            sbx1 = sx1/W; sby1 = sy1/H; sbx2 = sx2/W; sby2 = sy2/H
            for (ex, ey) in [(lx1, ly1), (lx2, ly2)]:
                if abs(ex - sbx1) < _EDGE_THRESH_N and sby1 - _PERP_THRESH_N <= ey <= sby2 + _PERP_THRESH_N:
                    touches.append(f'[{si+1}]-left')
                elif abs(ex - sbx2) < _EDGE_THRESH_N and sby1 - _PERP_THRESH_N <= ey <= sby2 + _PERP_THRESH_N:
                    touches.append(f'[{si+1}]-right')
                elif abs(ey - sby1) < _EDGE_THRESH_N and sbx1 - _PERP_THRESH_N <= ex <= sbx2 + _PERP_THRESH_N:
                    touches.append(f'[{si+1}]-top')
                elif abs(ey - sby2) < _EDGE_THRESH_N and sbx1 - _PERP_THRESH_N <= ex <= sbx2 + _PERP_THRESH_N:
                    touches.append(f'[{si+1}]-bot')
        seg_touches.append(touches)
    return seg_touches


def _build_symbol_summary(symbols: list, texts: list, img_w: int, img_h: int) -> str:
    """LLM A prompt data — symbols + OCR text only. No line segments."""
    W = max(img_w, 1)
    H = max(img_h, 1)

    sym_cx: list[float] = []
    sym_cy: list[float] = []
    for s in symbols:
        x1, y1, x2, y2 = s.get('bbox', [0, 0, 0, 0])
        sym_cx.append((x1 + x2) / 2 / W)
        sym_cy.append((y1 + y2) / 2 / H)

    _SENSOR_ELEMENT_TYPES = {
        'Temperature_Element', 'Thermocouple_Element',
        'Analyser_Element', 'Analyzer_Element',
        'Flow_Element', 'Pressure_Element', 'Level_Element',
    }

    def _iou(b1, b2):
        ix1 = max(b1[0], b2[0]); iy1 = max(b1[1], b2[1])
        ix2 = min(b1[2], b2[2]); iy2 = min(b1[3], b2[3])
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        if inter == 0:
            return 0.0
        a1 = max(0.0, b1[2] - b1[0]) * max(0.0, b1[3] - b1[1])
        a2 = max(0.0, b2[2] - b2[0]) * max(0.0, b2[3] - b2[1])
        union = a1 + a2 - inter
        return inter / union if union > 0 else 0.0

    _IOU_THRESH = 0.40
    overlap_pairs: list[tuple[int, int, float]] = []
    overlap_flagged: set[int] = set()
    raw_bboxes = [s.get('bbox', [0, 0, 0, 0]) for s in symbols]
    for i in range(len(symbols)):
        ti = symbols[i].get('type', '')
        ci = symbols[i].get('score', 0)
        for j in range(i + 1, len(symbols)):
            if j in overlap_flagged:
                continue
            tj = symbols[j].get('type', '')
            cj = symbols[j].get('score', 0)
            if ti in _SENSOR_ELEMENT_TYPES and tj in _SENSOR_ELEMENT_TYPES:
                continue
            iou = _iou(raw_bboxes[i], raw_bboxes[j])
            if iou < _IOU_THRESH:
                continue
            keep, dup = (i, j) if ci >= cj else (j, i)
            overlap_pairs.append((keep, dup, round(iou, 2)))
            overlap_flagged.add(dup)

    active = list(range(len(symbols)))
    sym_ocr: dict[int, list] = {i: [] for i in range(len(symbols))}
    unassigned_ocr = []
    for t in texts:
        bbox = t.get('bbox', [0, 0, 0, 0])
        tcx = (bbox[0] + bbox[2]) / 2 / W
        tcy = (bbox[1] + bbox[3]) / 2 / H
        best_i, best_d = -1, float('inf')
        for i in active:
            d = ((tcx - sym_cx[i]) ** 2 + (tcy - sym_cy[i]) ** 2) ** 0.5
            if d < best_d:
                best_d = d
                best_i = i
        if best_d < 0.05:
            sym_ocr[best_i].append((t, round(best_d, 3)))
        else:
            unassigned_ocr.append(t)

    parts = _cv_shared_header(W, H)
    parts.append(
        f"SYMBOLS detected ({len(symbols)} total — all sent for verification)"
        f"  [OCR entries shown indented under their nearest symbol]:"
    )

    if overlap_pairs:
        parts.append(
            f"\n*** BOUNDING BOX OVERLAP DOUBLES ({len(overlap_pairs)} pairs) ***\n"
            f"  These boxes share >40% of their pixel area — almost certainly ONE\n"
            f"  physical symbol that YOLO detected twice with different class labels.\n"
            f"  CHECK THESE FIRST using your vision before processing any other symbol.\n"
            f"  Look at the image at that position: if ONE symbol -> MERGE into one node.\n"
            f"  Only keep both if you can clearly see TWO separate ISA symbols there."
        )
        for keep, dup, iou in overlap_pairs:
            d = ((sym_cx[keep]-sym_cx[dup])**2+(sym_cy[keep]-sym_cy[dup])**2)**0.5
            parts.append(
                f"  OVERLAP [{keep+1:3d}] {symbols[keep].get('type','?'):22s}"
                f"conf={symbols[keep].get('score',0):.2f}"
                f"  <=IoU={iou:.2f}=>  "
                f"[{dup+1:3d}] {symbols[dup].get('type','?'):22s}"
                f"conf={symbols[dup].get('score',0):.2f}  dist={d:.3f}"
            )
        parts.append('')

    for i, s in enumerate(symbols):
        cx    = round(sym_cx[i], 3)
        cy    = round(sym_cy[i], 3)
        score = round(s.get('score', 0), 2)
        llm_note = ''
        if i in overlap_flagged:
            keep_idx = next(k for k, d, _ in overlap_pairs if d == i)
            iou_val  = next(v for k, d, v in overlap_pairs if d == i)
            llm_note = f'  *** OVERLAP IoU={iou_val:.2f} with [{keep_idx+1}] — VISION CHECK REQUIRED ***'
        parts.append(
            f"  [{i+1:3d}] type={s.get('type','?'):22s}  "
            f"pos=({cx:.3f},{cy:.3f})  conf={score}{llm_note}"
        )
        for t, dist in sym_ocr[i]:
            parts.append(
                f"         OCR \"{t.get('text','')}\"  "
                f"dist={dist}  conf={round(t.get('score', 0), 2)}"
            )

    if unassigned_ocr:
        parts.append(f"\nOCR TEXT unassigned (dist ≥ 0.05 from all symbols — {len(unassigned_ocr)} items):")
        for t in unassigned_ocr:
            bbox = t.get('bbox', [0, 0, 0, 0])
            tcx = round((bbox[0] + bbox[2]) / 2 / W, 3)
            tcy = round((bbox[1] + bbox[3]) / 2 / H, 3)
            parts.append(
                f"  \"{t.get('text','')}\"  pos=({tcx:.3f},{tcy:.3f})  "
                f"conf={round(t.get('score', 0), 2)}"
            )

    parts.append(f"\nSYMBOL BOUNDING BOXES (normalised 0-1, same scale as pos above):")
    for i, s in enumerate(symbols):
        x1, y1, x2, y2 = s.get('bbox', [0, 0, 0, 0])
        bx1 = round(x1 / W, 4); by1 = round(y1 / H, 4)
        bx2 = round(x2 / W, 4); by2 = round(y2 / H, 4)
        parts.append(f"  [{i+1:3d}] box=({bx1},{by1})→({bx2},{by2})")

    return '\n'.join(parts)


def _build_connection_summary(symbols: list, img_w: int, img_h: int,
                              lines: list | None = None,
                              llm_a_nodes: list | None = None) -> str:
    """LLM B prompt data — symbol list + all detected line segments.

    When llm_a_nodes is provided (verified output from LLM A), the symbol table
    is built from LLM A's nodes (correct types, labels, merged duplicates removed).
    YOLO bboxes are used for segment-touch spatial calculations (more accurate than
    estimating from normalised x,y). Touch labels use node IDs directly (e.g. n5-left).

    When llm_a_nodes is None, falls back to raw YOLO symbols as before.
    """
    W = max(img_w, 1)
    H = max(img_h, 1)

    if llm_a_nodes is not None:
        # ── LLM A nodes path ──────────────────────────────────────────────────
        # Build YOLO bbox lookup by node ID: n1 → yolo[0].bbox, n2 → yolo[1].bbox …
        yolo_bbox: dict[str, list] = {}
        for i, s in enumerate(symbols):
            yolo_bbox[f'n{i+1}'] = s.get('bbox', [0, 0, 0, 0])

        # For each LLM A node get bbox; estimate from x,y if not in YOLO
        def _node_bbox(n: dict) -> list:
            bbox = yolo_bbox.get(n.get('id', ''))
            if bbox:
                return bbox
            px = n.get('x', 0) * W;  py = n.get('y', 0) * H
            half = 20
            return [px - half, py - half, px + half, py + half]

        # Sort by position top-left → bottom-right
        sorted_nodes = sorted(
            llm_a_nodes,
            key=lambda n: (round(n.get('y', 0) * 20), round(n.get('x', 0) * 20))
        )

        parts = _cv_shared_header(W, H)
        parts.append(f"SYMBOLS ({len(llm_a_nodes)} verified nodes) sorted top-left to bottom-right:")
        for n in sorted_nodes:
            nid  = n.get('id', '?')
            cx   = round(n.get('x', 0), 3)
            cy   = round(n.get('y', 0), 3)
            bbox = _node_bbox(n)
            bx1  = round(bbox[0] / W, 4); by1 = round(bbox[1] / H, 4)
            bx2  = round(bbox[2] / W, 4); by2 = round(bbox[3] / H, 4)
            lbl  = n.get('label', '')
            lbl_str = f'  label="{lbl}"' if lbl else ''
            parts.append(
                f"  node={nid}  type={n.get('type', '?'):22s}"
                f"  pos=({cx},{cy})  box=({bx1},{by1})→({bx2},{by2}){lbl_str}"
            )

        if lines:
            # Touch calculation: synthetic symbol list preserving node ID ordering
            synth = [{'bbox': _node_bbox(n), '_nid': n.get('id', f'n{i+1}')}
                     for i, n in enumerate(llm_a_nodes)]
            raw_touches = _cv_seg_touches(synth, lines, W, H)

            # Re-label [N]-side → nID-side so LLM B gets node IDs directly
            nids = [n.get('id', f'n{i+1}') for i, n in enumerate(llm_a_nodes)]

            def _relabel(touches: list[str]) -> list[str]:
                out = []
                for t in touches:
                    if t.startswith('['):
                        close = t.index(']')
                        idx = int(t[1:close]) - 1
                        side = t[close + 1:]
                        out.append(f'{nids[idx]}{side}' if 0 <= idx < len(nids) else t)
                    else:
                        out.append(t)
                return out

            parts.append(f"\nDETECTED LINE SEGMENTS — {len(lines)} pipe segments:")
            parts.append(
                "  Format: segNNN (x1,y1)→(x2,y2) direction  [touches: nodeID-side]"
            )
            for idx, l in enumerate(lines):
                lx1 = round(l.get('x1', 0) / W, 4); ly1 = round(l.get('y1', 0) / H, 4)
                lx2 = round(l.get('x2', 0) / W, 4); ly2 = round(l.get('y2', 0) / H, 4)
                direction = l.get('direction', 'horizontal')
                touches   = _relabel(raw_touches[idx]) if idx < len(raw_touches) else []
                touch_str = f"  touches: {', '.join(touches)}" if touches else ""
                parts.append(
                    f"  seg{idx+1:03d} ({lx1},{ly1})→({lx2},{ly2}) {direction}{touch_str}"
                )

        return '\n'.join(parts)

    # ── Raw YOLO fallback path (no LLM A nodes) ───────────────────────────────
    indexed = []
    for i, s in enumerate(symbols):
        x1, y1, x2, y2 = s.get('bbox', [0, 0, 0, 0])
        cx = (x1 + x2) / 2 / W
        cy = (y1 + y2) / 2 / H
        indexed.append((i, s, cx, cy))

    sorted_syms = sorted(indexed, key=lambda t: (round(t[3] * 20), round(t[2] * 20)))

    parts = _cv_shared_header(W, H)
    parts.append(f"SYMBOLS ({len(symbols)} total) sorted top-left to bottom-right:")
    for orig_i, s, cx, cy in sorted_syms:
        x1, y1, x2, y2 = s.get('bbox', [0, 0, 0, 0])
        bx1 = round(x1 / W, 4); by1 = round(y1 / H, 4)
        bx2 = round(x2 / W, 4); by2 = round(y2 / H, 4)
        parts.append(
            f"  node=n{orig_i+1:3d}  type={s.get('type','?'):22s}  "
            f"pos=({cx:.3f},{cy:.3f})  box=({bx1},{by1})→({bx2},{by2})"
        )

    if lines:
        seg_touches = _cv_seg_touches(symbols, lines, W, H)
        parts.append(f"\nDETECTED LINE SEGMENTS — {len(lines)} pipe segments:")
        parts.append(
            "  Use pos=(x,y) as the symbol center for all coordinate math.\n"
            "  Format: segNNN (x1,y1)→(x2,y2) direction [touches: node-side]"
        )
        for idx, l in enumerate(lines):
            lx1 = round(l.get('x1', 0) / W, 4); ly1 = round(l.get('y1', 0) / H, 4)
            lx2 = round(l.get('x2', 0) / W, 4); ly2 = round(l.get('y2', 0) / H, 4)
            direction = l.get('direction', 'horizontal')
            touches = seg_touches[idx] if idx < len(seg_touches) else []
            touch_str = f"  touches: {', '.join(touches)}" if touches else ""
            parts.append(
                f"  seg{idx+1:03d} ({lx1},{ly1})→({lx2},{ly2}) {direction}{touch_str}"
            )

    return '\n'.join(parts)


def _call_llm_verification(
    _s,
    image_bytes: bytes,
    media_type: str,
    cv_summary_text: str,
    img_w: int,
    img_h: int,
    raw_lines: list,
) -> tuple[dict, object]:
    """Send image + CV summary to LLM A and return (parsed_json, response).

    Raises LlmStageError if the model never returns parseable JSON with a
    `nodes` array within the retry budget. Never returns an empty stand-in:
    nodes are the foundation every later stage attaches to, so an empty one
    is a failed page, not a page with no symbols.
    """
    # ponytail: LLM A gets ONE full image, not tiles — it has to CALCULATE
    # normalised x,y for newly-added symbols (tile offset + local position),
    # and that arithmetic is unreliable from a cropped view. LLM B only needs
    # to reference existing node ids/positions, so tiling stays there — see
    # _call_llm_connections.
    prompt = _VERIFY_PROMPT.replace('{cv_summary}', cv_summary_text)

    skills = _s.load_skills('p_and_id')
    b64 = base64.standard_b64encode(image_bytes).decode()

    def _attempt():
        resp = _s.llm.complete_streaming(
            prompt,
            system=skills,
            image_b64=b64,
            media_type=media_type,
            max_tokens=65536,
            force_json=True,
            response_schema=_OUTPUT_SCHEMA,
            tier='smart',
        )
        parsed = _parse_llm_json(_s, resp.text, 'LLM A (symbols)')
        if not isinstance(parsed.get('nodes'), list):
            raise ValueError("response has no 'nodes' array")
        return parsed, resp

    verified, resp = _with_retries('llm_a_symbols', _attempt)

    # ── Post-process: Convert LLM segment IDs → waypoint coordinates ────────
    # The LLM outputs "segments": ["seg012","seg034",...] for each edge.
    # We look up those segNNN entries from raw_lines and chain their endpoints
    # into the waypoints array. This gives accurate pipe routing without asking
    # the LLM to output coordinate values (saves tokens → more connections found).
    import math

    # Build a lookup: "seg001" → {x1,y1,x2,y2} in normalised 0-1 coords
    seg_lookup = {}
    for idx, l in enumerate(raw_lines, 1):
        try:
            x1, y1 = l['x1']/img_w, l['y1']/img_h
            x2, y2 = l['x2']/img_w, l['y2']/img_h
        except TypeError:
            x1, y1 = l.get('x1', 0), l.get('y1', 0)
            x2, y2 = l.get('x2', 0), l.get('y2', 0)
        seg_lookup[f'seg{idx:03d}'] = (round(x1,4), round(y1,4), round(x2,4), round(y2,4))

    nodes_dict = {n['id']: n for n in verified.get('nodes', [])}

    def _chain_segments(seg_ids, sx, sy, dx, dy):
        """Chain segment endpoints into an ordered waypoint list from (sx,sy) to (dx,dy)."""
        segs = []
        for sid in seg_ids:
            if sid in seg_lookup:
                segs.append(seg_lookup[sid])
        if not segs:
            return [[round(sx,4), round(sy,4)], [round(dx,4), round(dy,4)]]

        # Order segments by proximity: greedily pick the next segment whose
        # endpoint is closest to the current position
        ordered_pts = [[round(sx,4), round(sy,4)]]
        remaining = list(segs)
        cx, cy = sx, sy

        while remaining:
            best_i, best_d, best_flip = 0, float('inf'), False
            for i, (ax1, ay1, ax2, ay2) in enumerate(remaining):
                d1 = math.hypot(ax1-cx, ay1-cy)
                d2 = math.hypot(ax2-cx, ay2-cy)
                if d1 < best_d: best_i, best_d, best_flip = i, d1, False
                if d2 < best_d: best_i, best_d, best_flip = i, d2, True
            ax1, ay1, ax2, ay2 = remaining.pop(best_i)
            if best_flip:
                ax1, ay1, ax2, ay2 = ax2, ay2, ax1, ay1
            ordered_pts.append([round(ax2,4), round(ay2,4)])
            cx, cy = ax2, ay2

        ordered_pts.append([round(dx,4), round(dy,4)])

        # Remove duplicate consecutive points
        clean = [ordered_pts[0]]
        for pt in ordered_pts[1:]:
            if pt != clean[-1]:
                clean.append(pt)
        return clean

    # Convert segment IDs to waypoints for every edge
    for edge in verified.get('edges', []):
        seg_ids = edge.pop('segments', []) or []
        src = nodes_dict.get(edge.get('from'))
        dst = nodes_dict.get(edge.get('to'))
        if src and dst:
            sx, sy = src.get('x', 0), src.get('y', 0)
            dx, dy = dst.get('x', 0), dst.get('y', 0)
            edge['waypoints'] = _chain_segments(seg_ids, sx, sy, dx, dy)

    return verified, resp


def _chain_pixel_segments(line_indices: list, raw_lines: list, img_w: int, img_h: int,
                          sx: float, sy: float, dx: float, dy: float) -> list:
    """Chain the real detected pixel segments (by index into raw_lines) into
    an ordered, normalised (0-1) waypoint list from (sx,sy) to (dx,dy).

    Used to make a KEPT/geometry-backed edge render along the ACTUAL drawn
    pipe path (matching the source diagram) instead of a straight line
    between the two node centres — the routing is code-computed from the
    same detected geometry the connectivity graph was built from, no LLM
    involvement needed for this part.
    """
    segs = []
    for i in line_indices:
        if 0 <= i < len(raw_lines):
            l = raw_lines[i]
            segs.append((l['x1'] / img_w, l['y1'] / img_h, l['x2'] / img_w, l['y2'] / img_h))
    if not segs:
        return [[round(sx, 4), round(sy, 4)], [round(dx, 4), round(dy, 4)]]

    ordered_pts = [[round(sx, 4), round(sy, 4)]]
    remaining = list(segs)
    cx, cy = sx, sy
    while remaining:
        best_i, best_d, best_flip = 0, float('inf'), False
        for i, (ax1, ay1, ax2, ay2) in enumerate(remaining):
            d1 = math.hypot(ax1 - cx, ay1 - cy)
            d2 = math.hypot(ax2 - cx, ay2 - cy)
            if d1 < best_d: best_i, best_d, best_flip = i, d1, False
            if d2 < best_d: best_i, best_d, best_flip = i, d2, True
        ax1, ay1, ax2, ay2 = remaining.pop(best_i)
        if best_flip:
            ax1, ay1, ax2, ay2 = ax2, ay2, ax1, ay1
        ordered_pts.append([round(ax2, 4), round(ay2, 4)])
        cx, cy = ax2, ay2
    ordered_pts.append([round(dx, 4), round(dy, 4)])

    clean = [ordered_pts[0]]
    for pt in ordered_pts[1:]:
        if pt != clean[-1]:
            clean.append(pt)

    # Straighten a small, spurious jog: YOLO (symbols) and UNet (lines) are
    # two independent detectors that don't calibrate to the exact same
    # sub-pixel reference point for a component's stem centerline — a clean,
    # perfectly straight real pipe can come back with its interior waypoint
    # offset ~30-40px sideways from where the two endpoint symbols actually
    # sit. If both endpoints already share (nearly) the same x (a vertical
    # run) or y (a horizontal run), snap any interior point's small
    # perpendicular offset from that shared axis onto it — this only nudges
    # points already belonging to THIS edge's own polyline; it can't merge
    # or otherwise affect any other edge.
    _JOG_TOL = 0.01  # ~50px on a 5100px-wide sheet
    if len(clean) > 2:
        dx_end = abs(clean[0][0] - clean[-1][0])
        dy_end = abs(clean[0][1] - clean[-1][1])
        if dx_end < _JOG_TOL and dx_end < dy_end:
            shared_x = (clean[0][0] + clean[-1][0]) / 2
            for pt in clean[1:-1]:
                if abs(pt[0] - shared_x) < _JOG_TOL:
                    pt[0] = round(shared_x, 4)
        elif dy_end < _JOG_TOL and dy_end < dx_end:
            shared_y = (clean[0][1] + clean[-1][1]) / 2
            for pt in clean[1:-1]:
                if abs(pt[1] - shared_y) < _JOG_TOL:
                    pt[1] = round(shared_y, 4)

    return clean


def _format_proposed_graph(geo: dict, llm_a_nodes: list) -> str:
    """Render the geometrically-built candidate graph as text for the
    connections-audit prompt. Node ids are resolved against LLM A's verified
    node list so the LLM sees readable type/label context, not bare ids."""
    node_lookup = {n['id']: n for n in llm_a_nodes}

    def _lbl(nid: str) -> str:
        n = node_lookup.get(nid)
        if not n:
            return nid
        lbl = n.get('label', '')
        return f"{nid}({n.get('type', '?')}{'/' + lbl if lbl else ''})"

    parts = []
    edges = geo.get('edges', [])
    parts.append(f"PROPOSED EDGES ({len(edges)} candidates, built from detected line geometry):")
    for i, e in enumerate(edges):
        nseg = len(e.get('line_indices', []))
        parts.append(f"  [{i}] {_lbl(e['from'])} -- {_lbl(e['to'])}  ({nseg} segment(s) support this)")
    if not edges:
        parts.append("  (none)")

    stubs = geo.get('open_stubs', [])
    if stubs:
        # Split: salvaged stubs have geometric backing (UNet + geometry both
        # confirmed the line); regular stubs are just unresolved line ends.
        salvaged_stubs = [s for s in stubs if '_salvaged_orphan_id' in s]
        regular_stubs  = [s for s in stubs if '_salvaged_orphan_id' not in s]

        if salvaged_stubs:
            parts.append(
                f"\nGEOMETRY-CONFIRMED STUBS ({len(salvaged_stubs)} — "
                f"UNet detected the pipe AND geometry built a full edge, but one "
                f"endpoint was a symbol the node-verification step discarded without "
                f"recording. The pipe IS real — the geometry says so. Look at the "
                f"image at each pixel position: if you can see the pipe reaching the "
                f"candidate symbol (or another symbol), you MUST ADD that edge. "
                f"Only leave unresolved if the image is genuinely ambiguous):"
            )
            for i, s in enumerate(salvaged_stubs):
                cand = s.get('candidate_symbol')
                frm  = s.get('from', '?')
                cand_txt = f" → likely target: {_lbl(cand)}" if cand else " (no candidate — scan image)"
                parts.append(
                    f"  [GC-{i}] pipe from {_lbl(frm)} at pixel "
                    f"({s['x']:.0f},{s['y']:.0f}){cand_txt}"
                )

        if regular_stubs:
            parts.append(
                f"\nCANDIDATE STUBS ({len(regular_stubs)} — detected line ends "
                f"geometry couldn't confirm; ADD only if 100% certain from the image):"
            )
            for i, s in enumerate(regular_stubs):
                cand = s.get('candidate_symbol')
                frm  = s.get('from', '?')
                cand_txt = f" nearest symbol within range: {_lbl(cand)}" if cand else " (no symbol nearby)"
                parts.append(
                    f"  [{i}] stub from {_lbl(frm)} at pixel ({s['x']:.0f},{s['y']:.0f}) —{cand_txt}"
                )


    junctions = geo.get('junctions', [])
    if junctions:
        parts.append(f"\nPROPOSED JUNCTIONS ({len(junctions)}):")
        for j in junctions:
            parts.append(f"  {j['id']} at pixel ({j['x']:.0f},{j['y']:.0f})  degree={j['degree']}")

    ambiguous = geo.get('ambiguous_crossings', [])
    if ambiguous:
        parts.append(f"\nAMBIGUOUS CROSSINGS ({len(ambiguous)} — two lines cross with no shared "
                     f"endpoint; NOT auto-connected here, verify if there's really a junction dot):")
        for a in ambiguous:
            parts.append(f"  at pixel ({a['x']:.0f},{a['y']:.0f})")

    unreached = geo.get('unreached_segments', [])
    if unreached:
        parts.append(
            f"\nDETECTED BUT UNRESOLVED SEGMENTS ({len(unreached)} — UNet detected "
            f"these lines and geometry is confident they are real, but NEITHER end "
            f"landed on a symbol or a junction, so no edge could be built. The line "
            f"IS on the drawing. Look at the image along each one: if you can see it "
            f"running between two symbols, ADD that edge. The nearest symbol to each "
            f"end is given as a starting point, not an answer — the true endpoint may "
            f"be a different symbol, or the segment may be one leg of a longer run "
            f"that turns a corner):"
        )
        for i, u in enumerate(unreached):
            frm = u.get('candidate_from')
            to  = u.get('candidate_to')
            parts.append(
                f"  [U-{i}] {u.get('kind', 'process')} line "
                f"({u['x1']:.0f},{u['y1']:.0f}) → ({u['x2']:.0f},{u['y2']:.0f})  "
                f"nearest at each end: {_lbl(frm) if frm else '(none)'} .. "
                f"{_lbl(to) if to else '(none)'}"
            )

    unmatched = geo.get('unmatched_symbols', [])
    if unmatched:
        parts.append(f"\nUNMATCHED SYMBOLS ({len(unmatched)} — geometry found NO detected line "
                     f"anywhere near these; a common gap on crowded drawings where the line "
                     f"detector missed a stub entirely. The nearest other symbol and its "
                     f"distance are given: a few pixels between two symbols usually means a "
                     f"short nozzle the line detector could not resolve, NOT an isolated "
                     f"item. Check each pair in the image and ADD the edge when you can see "
                     f"they are joined):")
        detail = {d['id']: d for d in geo.get('unmatched_symbols_detail', [])}
        if detail:
            for nid in unmatched:
                d = detail.get(nid, {})
                near = d.get('nearest')
                if near:
                    parts.append(f"  {_lbl(nid)} — nearest: {_lbl(near)} "
                                 f"at {d.get('distance_px', '?')} px")
                else:
                    parts.append(f"  {_lbl(nid)} — no other symbol nearby")
        else:
            parts.append("  " + ", ".join(_lbl(nid) for nid in unmatched))

    return '\n'.join(parts)


def _call_llm_connections(
    _s,
    image_bytes: bytes,
    media_type: str,
    conn_summary_text: str,
    proposed_graph_text: str = '',
) -> tuple[dict, object]:
    """LLM B — connections AUDIT. Returns ({'edges': [...], 'junctions': [...]}, response).

    A deterministic geometric pass (connectivity_graph.py) already built a
    candidate graph from detected line segments; the LLM's job is to confirm,
    correct, delete, or (only when 100% certain) add to that candidate list —
    never to trace the whole sheet from a blank slate.

    Raises LlmStageError once the retry budget is exhausted. It used to
    return `{'edges': []}` on any parse failure, which is indistinguishable
    from "the auditor deleted every candidate" — the run then persisted a
    drawing with symbols and no pipes and reported success. An EMPTY but
    well-formed `edges: []` from the model is still honoured: that is a real
    audit verdict, not a failure.
    """
    if not proposed_graph_text:
        # UNet found no usable line segments at all — nothing to audit.
        proposed_graph_text = ("(no candidate graph — geometry produced no line "
                               "segments to audit. Only ADD an edge if 100% certain "
                               "from the image; otherwise output empty edges/junctions.)")

    prompt = (_CONN_PROMPT
              .replace('{cv_summary}', conn_summary_text)
              .replace('{proposed_graph}', proposed_graph_text))
    skills = (
        "You are a P&ID pipe connection AUDITOR. A deterministic geometric "
        "pass already built a candidate connectivity graph from detected "
        "line segments. Check each candidate against the image: "
        "100% sure it's a real pipe → KEEP. "
        "100% sure it's NOT a real pipe (e.g. a nameplate leader line) → DELETE. "
        "Any doubt on a proposed edge → KEEP (never delete on uncertainty). "
        "GEOMETRY-CONFIRMED STUBS have real UNet + geometric backing — the pipe "
        "was detected and confirmed; one endpoint was lost in node-verification. "
        "For these, look at the image: if you can see the pipe reaching the "
        "candidate symbol, you MUST ADD that edge. Default is ADD, not leave. "
        "Regular CANDIDATE STUBS → ADD only if 100% certain from the image; any doubt → leave unresolved. "
        "A candidate stub or unmatched symbol → ADD only if 100% certain it "
        "reaches the image; any doubt → leave it unresolved. "
        "Never invent an edge with no grounds in the candidate data. "
        "Output junctions (id, x, y) and edges (from, to, kind)."
    )

    b64 = base64.standard_b64encode(image_bytes).decode()

    def _attempt():
        resp = _s.llm.complete_streaming(
            prompt,
            system=skills,
            image_b64=b64,
            media_type=media_type,
            max_tokens=65536,
            force_json=False,
            response_schema=_CONN_SCHEMA,
            tier='smart',
        )
        parsed = _parse_llm_json(_s, resp.text, 'LLM B (connections)')
        # A reply with no `edges` key at all is malformed — distinct from one
        # that deliberately audits every candidate away with `"edges": []`.
        if 'edges' not in parsed:
            raise ValueError("response has no 'edges' key")
        if not isinstance(parsed['edges'], list):
            raise ValueError(f"'edges' is {type(parsed['edges']).__name__}, expected list")
        parsed.setdefault('junctions', [])
        return parsed, resp

    return _with_retries('llm_b_connections', _attempt)
