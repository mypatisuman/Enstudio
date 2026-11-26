"""line_geometry.py — pure coordinate arithmetic, line snapping, and style classification.

Contains NO machine learning models or learned weights.
"""
from __future__ import annotations

import math
import logging
import numpy as np

logger = logging.getLogger(__name__)

# ── Tiling and geometry constants ─────────────────────────────────────────────
_TILE_SIZE        = 1024
_STRIDE           = 768
_OVERLAP          = 256
_BLANK_DARK_THRESH = 240
_BLANK_MIN_DARK_PX = 50

_DASH_FILL_THRESH = 0.78   # >= this fraction dark -> solid; below -> dashed
_DASH_DARK_VALUE  = 128    # pixel < this counts as "ink"
_DASH_PERP_TOL    = 2      # +/- perpendicular px window
_DASH_MIN_LEN     = 40     # shorter segments treat as solid

_SPLIT_SEARCH     = 14     # perpendicular half-window (px)
_SPLIT_MIN_SEP    = 5      # min distance for separate lines
_SPLIT_PRESENCE   = 0.30   # presence fraction across samples
_SPLIT_CLUSTER    = 3      # run-centers cluster radius
_SPLIT_MIN_LEN    = 60     # only split segments >= this length

_WELD_TOL         = 30
_BRIDGE_GAP       = 200
_BRIDGE_GAP_SYMBOL = 400
_BRIDGE_AXIS_TOL  = 6
_BOX_SNAP_TOL     = 25

_GAP_INK_THRESH   = 0.5
_HEAL_MERGE_GAP   = 35.0
_HOUGH_MIN_LINE   = 10
_HOUGH_GAP        = 5

_LEADER_MAX_LEN        = 120
_LEADER_TEXT_PROXIMITY = 40
_LEADER_ANCHOR_TOL     = 10


# ── Direction helpers ─────────────────────────────────────────────────────────

def _classify_direction(x1, y1, x2, y2) -> str:
    """Classify a segment as horizontal / vertical / diagonal / point."""
    dx, dy = abs(x2 - x1), abs(y2 - y1)
    if dx == 0 and dy == 0:
        return 'point'
    if dx >= dy and dy <= max(8.0, dx * 0.20):
        return 'horizontal'
    if dy > dx and dx <= max(8.0, dy * 0.20):
        return 'vertical'
    return 'diagonal'


def _is_hv(dx, dy, tol=8.0) -> tuple[bool, bool]:
    """Return (is_horizontal, is_vertical) for a displacement vector."""
    dx, dy = abs(dx), abs(dy)
    is_h = dx >= dy and dy <= max(tol, dx * 0.20)
    is_v = dy > dx and dx <= max(tol, dy * 0.20)
    return is_h, is_v


# ── Dashed vs solid classification ────────────────────────────────────────────

def _line_fill_ratio(gray: np.ndarray, x1, y1, x2, y2) -> float:
    """Fraction of sample points along the segment that hit ink."""
    H, W = gray.shape[:2]
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1:
        return 1.0
    n = min(200, int(round(length)) + 1)
    t = np.linspace(0.0, 1.0, n)
    pxs = np.clip(np.round(x1 + (x2 - x1) * t).astype(int), 0, W - 1)
    pys = np.clip(np.round(y1 + (y2 - y1) * t).astype(int), 0, H - 1)
    is_h, is_v = _is_hv(x2 - x1, y2 - y1)
    hit = np.zeros(n, dtype=bool)
    for d in range(-_DASH_PERP_TOL, _DASH_PERP_TOL + 1):
        if is_h:
            sxs = pxs
            sys_ = np.clip(pys + d, 0, H - 1)
        elif is_v:
            sxs = np.clip(pxs + d, 0, W - 1)
            sys_ = pys
        else:
            sxs, sys_ = pxs, pys
        hit |= gray[sys_, sxs] < _DASH_DARK_VALUE
    return float(hit.sum()) / n


def _classify_line_style(gray: np.ndarray, seg: list | tuple) -> str:
    """Return 'solid' or 'dashed' for a segment based on original-image fill ratio."""
    x1, y1, x2, y2 = seg
    if math.hypot(x2 - x1, y2 - y1) < _DASH_MIN_LEN:
        return 'solid'
    return 'solid' if _line_fill_ratio(gray, x1, y1, x2, y2) >= _DASH_FILL_THRESH else 'dashed'


# ── Parallel line splitting ───────────────────────────────────────────────────

def _dark_run_centers(profile: np.ndarray, base: int) -> list[float]:
    """Centers of consecutive dark runs (< _DASH_DARK_VALUE) in a 1-D profile."""
    centers, i, n = [], 0, len(profile)
    while i < n:
        if profile[i] < _DASH_DARK_VALUE:
            j = i
            while j < n and profile[j] < _DASH_DARK_VALUE:
                j += 1
            centers.append(base + (i + j - 1) / 2.0)
            i = j
        else:
            i += 1
    return centers


def _segment_intersects_box(x1, y1, x2, y2, bx1, by1, bx2, by2) -> bool:
    """Check if line segment intersects a box."""
    if max(x1, x2) < bx1 or min(x1, x2) > bx2 or max(y1, y2) < by1 or min(y1, y2) > by2:
        return False
    dx, dy = x2 - x1, y2 - y1
    p = [-dx, dx, -dy, dy]
    q = [x1 - bx1, bx2 - x1, y1 - by1, by2 - y1]
    t0, t1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return False
        elif pi < 0:
            t0 = max(t0, qi / pi)
        else:
            t1 = min(t1, qi / pi)
    return t0 <= t1


def _split_parallel_lines(gray: np.ndarray, segments: list, skip_boxes=None) -> list:
    """Split detected H/V lines that cover 2+ parallel lines in the original drawing."""
    H, W = gray.shape[:2]
    out = []
    for seg in segments:
        x1, y1, x2, y2 = seg
        is_h, is_v = _is_hv(x2 - x1, y2 - y1)
        length = math.hypot(x2 - x1, y2 - y1)
        if (not is_h and not is_v) or length < _SPLIT_MIN_LEN:
            out.append(seg)
            continue
        if skip_boxes and any(_segment_intersects_box(x1, y1, x2, y2, *b) for b in skip_boxes):
            out.append(seg)
            continue

        n_samples = min(20, max(6, int(length / 40)))
        samples = []
        ts = np.linspace(0.0, 1.0, n_samples + 1)
        pxs = np.clip(np.round(x1 + (x2 - x1) * ts).astype(int), 0, W - 1)
        pys = np.clip(np.round(y1 + (y2 - y1) * ts).astype(int), 0, H - 1)
        for px, py in zip(pxs.tolist(), pys.tolist()):
            if is_v:
                lo = max(0, px - _SPLIT_SEARCH)
                hi = min(W, px + _SPLIT_SEARCH + 1)
                samples.append(_dark_run_centers(gray[py, lo:hi], lo))
            else:
                lo = max(0, py - _SPLIT_SEARCH)
                hi = min(H, py + _SPLIT_SEARCH + 1)
                samples.append(_dark_run_centers(gray[lo:hi, px], lo))

        flat = sorted(c for cs in samples for c in cs)
        if not samples or not flat:
            out.append(seg)
            continue

        clusters = [[flat[0]]]
        for c in flat[1:]:
            if c - clusters[-1][-1] <= _SPLIT_CLUSTER:
                clusters[-1].append(c)
            else:
                clusters.append([c])

        n = len(samples)
        positions = []
        for cl in clusters:
            lo_c, hi_c = cl[0] - _SPLIT_CLUSTER, cl[-1] + _SPLIT_CLUSTER
            present = sum(1 for cs in samples if any(lo_c <= c <= hi_c for c in cs))
            if present / n >= _SPLIT_PRESENCE:
                positions.append(sum(cl) / len(cl))

        merged = []
        for p in positions:
            if merged and p - merged[-1] < _SPLIT_MIN_SEP:
                merged[-1] = (merged[-1] + p) / 2.0
            else:
                merged.append(p)

        if len(merged) < 2:
            out.append(seg)
            continue

        for p in merged:
            ip = int(round(p))
            out.append([ip, y1, ip, y2] if is_v else [x1, ip, x2, ip])
    return out


# ── Collinear grouping and merging ────────────────────────────────────────────

def _seg_axis(s):
    """Return ('h', y, xlo, xhi) or ('v', x, ylo, yhi) or ('o', ...) for a segment."""
    is_h, is_v = _is_hv(s[2] - s[0], s[3] - s[1])
    if is_h:
        return ('h', (s[1] + s[3]) / 2.0, min(s[0], s[2]), max(s[0], s[2]))
    if is_v:
        return ('v', (s[0] + s[2]) / 2.0, min(s[1], s[3]), max(s[1], s[3]))
    return ('o', 0, 0, 0)


def _symbol_in_span(boxes, axis: str, pos: float, lo: float, hi: float) -> bool:
    """True if any symbol box sits within the [lo, hi] span along the axis at perp position pos."""
    for bx1, by1, bx2, by2 in boxes:
        if axis == 'h':
            if by1 - 8 <= pos <= by2 + 8 and not (bx2 < lo or bx1 > hi):
                return True
        else:
            if bx1 - 8 <= pos <= bx2 + 8 and not (by2 < lo or by1 > hi):
                return True
    return False


def _hough_segments(raw) -> list:
    """Normalise cv2.HoughLinesP output to a list of [x1, y1, x2, y2]."""
    if raw is None:
        return []
    out = []
    for s in raw:
        seg = s.tolist() if hasattr(s, 'tolist') else list(s)
        if len(seg) == 1 and isinstance(seg[0], (list, tuple)):
            seg = list(seg[0])
        if len(seg) == 4 and not any(isinstance(v, (list, tuple)) for v in seg):
            out.append([int(seg[0]), int(seg[1]), int(seg[2]), int(seg[3])])
    return out


def _classify_lines(lines, ortho_tol=8.0):
    """Split [x1, y1, x2, y2] list into (horiz, vert, other)."""
    horiz, vert, other = [], [], []
    for x1, y1, x2, y2 in lines:
        is_h, is_v = _is_hv(x2 - x1, y2 - y1, tol=ortho_tol)
        if is_h:
            horiz.append(((y1 + y2) / 2.0, min(x1, x2), max(x1, x2)))
        elif is_v:
            vert.append(((x1 + x2) / 2.0, min(y1, y2), max(y1, y2)))
        else:
            other.append([x1, y1, x2, y2])
    return horiz, vert, other


def _group_lines(norm_lines: list, group_tol=2.5) -> list:
    """Group by axis position (y for H, x for V) within tolerance."""
    if not norm_lines:
        return []
    norm_lines.sort(key=lambda i: i[0])
    groups, cur = [], [norm_lines[0]]
    for item in norm_lines[1:]:
        if abs(item[0] - cur[0][0]) <= group_tol:
            cur.append(item)
        else:
            groups.append(cur)
            cur = [item]
    groups.append(cur)
    return groups


def _merge_groups(groups: list, gap_threshold: float, gap_ok=None) -> list:
    """Length-weighted merge of grouped segments."""
    merged = []
    for grp in groups:
        grp.sort(key=lambda i: i[1])
        run: list = [grp[0]]
        cs, ce = grp[0][1], grp[0][2]

        def _flush(run_items, start, end):
            tl = sum(max(1, x[2] - x[1]) for x in run_items)
            axis = sum(x[0] * max(1, x[2] - x[1]) for x in run_items) / (tl + 1e-6)
            merged.append((axis, start, end))

        for item in grp[1:]:
            gap_lo, gap_hi = ce, item[1]
            close_enough = item[1] <= ce + gap_threshold
            overlapping = gap_hi <= gap_lo
            if close_enough and (overlapping or gap_ok is None or gap_ok(grp[0][0], gap_lo, gap_hi)):
                run.append(item)
                cs, ce = min(cs, item[1]), max(ce, item[2])
            else:
                _flush(run, cs, ce)
                run = [item]
                cs, ce = item[1], item[2]
        _flush(run, cs, ce)
    return merged


def _make_gap_evidence_gate(gray: np.ndarray | None, axis: str, boxes):
    """Build the `gap_ok` predicate for _merge_groups."""
    def gap_ok(axis_pos, gap_lo, gap_hi):
        if gap_hi <= gap_lo:
            return True
        if boxes and _symbol_in_span(boxes, axis, axis_pos, gap_lo, gap_hi):
            return False
        if gray is None:
            return True
        if axis == 'h':
            x1, y1, x2, y2 = gap_lo, axis_pos, gap_hi, axis_pos
        else:
            x1, y1, x2, y2 = axis_pos, gap_lo, axis_pos, gap_hi
        return _line_fill_ratio(gray, x1, y1, x2, y2) >= _GAP_INK_THRESH
    return gap_ok


def _dedup_merge(segments: list, diag_min=30) -> list:
    """Collapse near-parallel collinear duplicate H/V segments."""
    h, v, o = _classify_lines(segments)
    h_m = _merge_groups(_group_lines(h, 3.0), _HEAL_MERGE_GAP)
    v_m = _merge_groups(_group_lines(v, 3.0), _HEAL_MERGE_GAP)
    out = [[int(round(s)), int(round(y)), int(round(e)), int(round(y))] for y, s, e in h_m]
    out += [[int(round(x)), int(round(s)), int(round(x)), int(round(e))] for x, s, e in v_m]
    out += [[int(round(d[0])), int(round(d[1])), int(round(d[2])), int(round(d[3]))]
            for d in o if math.hypot(d[2] - d[0], d[3] - d[1]) >= diag_min]
    return [s for s in out if (s[0] != s[2] or s[1] != s[3])]


# ── Clipping, snapping, and leader-line filtering ─────────────────────────────

def _clip_segments_to_symbols(segments: list, sym_box_tuples: list) -> list:
    """Clip each segment at symbol box boundaries -> endpoints sit at symbol edges."""
    if not sym_box_tuples:
        return segments
    res = []
    for s in segments:
        blocking = [b for b in sym_box_tuples
                    if _segment_intersects_box(s[0], s[1], s[2], s[3], *b)]
        if not blocking:
            res.append(s)
            continue
        is_h, is_v = _is_hv(s[2] - s[0], s[3] - s[1])
        if is_h:
            y = int(round((s[1] + s[3]) / 2.0))
            xs, xe = min(s[0], s[2]), max(s[0], s[2])
            bx = sorted([(max(b[0], xs), min(b[2], xe))
                         for b in blocking if b[1] - 12 <= y <= b[3] + 12])
            curr, mb = xs, []
            for lo, hi in bx:
                if mb and lo <= mb[-1][1]:
                    mb[-1] = (mb[-1][0], max(mb[-1][1], hi))
                else:
                    mb.append((lo, hi))
            for lo, hi in mb:
                if curr < lo:
                    res.append([int(round(curr)), y, int(round(lo)), y])
                curr = max(curr, hi)
            if curr < xe:
                res.append([int(round(curr)), y, int(round(xe)), y])
        elif is_v:
            x = int(round((s[0] + s[2]) / 2.0))
            ys, ye = min(s[1], s[3]), max(s[1], s[3])
            by = sorted([(max(b[1], ys), min(b[3], ye))
                         for b in blocking if b[0] - 12 <= x <= b[2] + 12])
            curr, mb = ys, []
            for lo, hi in by:
                if mb and lo <= mb[-1][1]:
                    mb[-1] = (mb[-1][0], max(mb[-1][1], hi))
                else:
                    mb.append((lo, hi))
            for lo, hi in mb:
                if curr < lo:
                    res.append([x, int(round(curr)), x, int(round(lo))])
                curr = max(curr, hi)
            if curr < ye:
                res.append([x, int(round(curr)), x, int(round(ye))])
        else:
            res.append(s)
    return res


def _snap_point(px, py, sym_box_tuples, snap_dist, is_h):
    """Snap a point to the nearest symbol box edge if within snap_dist."""
    tol = 14
    best, bg = None, snap_dist + 1
    for bx1, by1, bx2, by2 in sym_box_tuples:
        if is_h:
            if not (by1 - tol <= py <= by2 + tol):
                continue
            if bx1 <= px <= bx2:
                l, r = abs(px - bx1), abs(px - bx2)
                if l < r and l < bg: best, bg = (bx1, py), l
                elif r < bg:         best, bg = (bx2, py), r
            elif 0 < bx1 - px <= snap_dist and bx1 - px < bg: best, bg = (bx1, py), bx1 - px
            elif 0 < px - bx2 <= snap_dist and px - bx2 < bg: best, bg = (bx2, py), px - bx2
        else:
            if not (bx1 - tol <= px <= bx2 + tol):
                continue
            if by1 <= py <= by2:
                t, bo = abs(py - by1), abs(py - by2)
                if t < bo and t < bg: best, bg = (px, by1), t
                elif bo < bg:         best, bg = (px, by2), bo
            elif 0 < by1 - py <= snap_dist and by1 - py < bg: best, bg = (px, by1), by1 - py
            elif 0 < py - by2 <= snap_dist and py - by2 < bg: best, bg = (px, by2), py - by2
    return best if best else (px, py)


def _snap_endpoints_to_symbols(segments: list, sym_box_tuples: list, snap_dist: int) -> list:
    """Snap segment endpoints to the nearest symbol box edge."""
    if not sym_box_tuples:
        return segments
    res = []
    for s in segments:
        is_h, is_v = _is_hv(s[2] - s[0], s[3] - s[1])
        if not is_h and not is_v:
            res.append(s)
            continue
        x1, y1 = _snap_point(s[0], s[1], sym_box_tuples, snap_dist, is_h)
        x2, y2 = _snap_point(s[2], s[3], sym_box_tuples, snap_dist, is_h)
        res.append([int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))])
    return res


def _filter_leader_lines(segments: list, sym_box_tuples: list, text_boxes: list = None,
                         anchor_tol=_LEADER_ANCHOR_TOL) -> list:
    """Remove annotation leaders / callouts while keeping real pipe stubs."""
    if not sym_box_tuples or not text_boxes:
        return segments

    def _near_any_symbol(px, py):
        for bx1, by1, bx2, by2 in sym_box_tuples:
            cx = min(max(px, bx1), bx2)
            cy = min(max(py, by1), by2)
            if math.hypot(px - cx, py - cy) <= anchor_tol:
                return True
        return False

    def _near_any_text(px, py):
        for tb in text_boxes:
            bx1, by1, bx2, by2 = tb[0], tb[1], tb[2], tb[3]
            cx = min(max(px, bx1), bx2)
            cy = min(max(py, by1), by2)
            if math.hypot(px - cx, py - cy) <= _LEADER_TEXT_PROXIMITY:
                return True
        return False

    result, dropped = [], 0
    for s in segments:
        x1, y1, x2, y2 = s[0], s[1], s[2], s[3]
        if math.hypot(x2 - x1, y2 - y1) >= _LEADER_MAX_LEN:
            result.append(s)
            continue

        p1_sym, p2_sym = _near_any_symbol(x1, y1), _near_any_symbol(x2, y2)
        if p1_sym == p2_sym:
            result.append(s)
            continue

        tip = (x2, y2) if p1_sym else (x1, y1)
        if _near_any_text(*tip):
            dropped += 1
            continue
        result.append(s)

    if dropped:
        logger.info("Leader filter removed %d annotation line(s) pointing at text", dropped)
    return result
