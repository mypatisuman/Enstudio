"""text_geometry.py — pure string heuristics and box geometry for text and tags.

Contains NO machine learning models or learned weights.
"""
from __future__ import annotations

import re
import numpy as np

# ── Tiling config ─────────────────────────────────────────────────────────────
_TILE_SIZE  = 2000   # px
_OVERLAP    = 400    # px

# ── Confidence threshold ──────────────────────────────────────────────────────
_SCORE_THRESH = 0.50

# ── Tag-zone: only keep hits whose CENTER is within this many px of symbol bbox ───
_TAG_ZONE_PX        = 20   # instruments / valves
_TAG_ZONE_PX_EQUIP  = 25   # equipment — label may be printed outside bbox
_TAG_ZONE_PX_CONN   = 5    # connectors — header text is fully inside bbox

# ── Symbol type sets (controls zone + scale behaviour) ────────────────────────
_EQUIPMENT_TYPES = {
    'vessel', 'tank', 'reactor', 'equipment',
    'heat_exchanger', 'compressor', 'pump', 'separator',
}
_CONNECTOR_TYPES = {'inlet', 'outlet'}

# ── ISA tag validation ────────────────────────────────────────────────────────
_ISA_TAG_VALID_RE = re.compile(
    r'^[A-Z]{1,5}([\s\-][A-Z0-9]{2,}[A-Z0-9\-]*)?$', re.IGNORECASE
)

# Valve/instrument types that must have a valid ISA tag
_REQUIRES_ISA_TAG = {
    'ball_valve', 'needle_valve', 'check_valve', 'gate_valve', 'butterfly_valve',
    '3_way_valve', '2_way_valve', '3_way_solenoid_valve', 'pneumatic_actuated_valve',
    'pressure_indicator', 'temperature_indicator', 'temperature_element',
    'temperature_controller', 'mass_flow_meter', 'differential_temperature',
    'filter', 'regulator', 'level_gauge',
}

# ── Title-block keywords ──────────────────────────────────────────────────────
_TITLE_BLOCK_KW = {
    'REV', 'REVISION', 'DRAWN', 'CHECKED', 'APP', 'APPROVED',
    'SCALE', 'NTS', 'DWG', 'CLIENT', 'PROJECT', 'DATE',
    'COMPANY', 'TITLE', 'SHEET',
}


def _clean_leading_symbols(text: str) -> str:
    """Strip leading non-alphanumeric characters."""
    return re.sub(r'^[^A-Za-z0-9]+', '', text)


def _looks_like_process_tag(text: str) -> bool:
    """Heuristic: preserve real ISA tags near page borders."""
    t = str(text or '').strip().upper()
    if not t:
        return False
    return bool(
        re.search(r'[A-Z]{1,5}[\s_\-]?\d{2,5}[A-Z]?', t) or
        re.search(r'\d+\s*["\']\s*[-/ ]?\s*\d{2,5}', t)
    )


def _is_valid_text(text: str) -> bool:
    """Check if string is a candidate valid tag/label — allows single uppercase letters and digits."""
    t = text.strip()
    if len(t) == 1 and t.isupper():
        return True
    if len(t) == 1 and t.isdigit():
        return True
    if len(t) < 2:
        return False
    if not re.search(r'[A-Za-z0-9]', t):
        return False
    return True


def _merge_vertical_boxes(results: list, vertical_thresh: int = 40,
                          min_x_overlap_ratio: float = 0.2) -> list:
    """Merge vertically-adjacent text boxes — uses x-overlap ratio + centre distance."""
    merged = []
    used = set()
    results = sorted(results, key=lambda x: (x['bbox'][1], x['bbox'][0]))
    n = len(results)
    for i in range(n):
        if i in used:
            continue
        b1 = results[i]['bbox']
        x1_min, y1_min, x1_max, y1_max = b1
        c1_x = (x1_min + x1_max) / 2
        text1, score1 = results[i]['text'], results[i].get('score', 0)
        found = False
        for j in range(i + 1, n):
            if j in used:
                continue
            b2 = results[j]['bbox']
            x2_min, y2_min, x2_max, y2_max = b2
            c2_x = (x2_min + x2_max) / 2
            v_gap = y2_min - y1_max
            v_overlap = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
            if not (-vertical_thresh <= v_gap <= vertical_thresh or v_overlap > 0):
                continue
            x_overlap = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
            min_w = max(1, min(x1_max - x1_min, x2_max - x2_min))
            centre_dist = abs(c1_x - c2_x)
            if (x_overlap / min_w >= min_x_overlap_ratio) or centre_dist < (min_w * 0.8):
                merged_box = [min(x1_min, x2_min), min(y1_min, y2_min),
                              max(x1_max, x2_max), max(y1_max, y2_max)]
                if y1_min <= y2_min:
                    merged_text = text1 + ' ' + results[j]['text']
                else:
                    merged_text = results[j]['text'] + ' ' + text1
                score2 = results[j].get('score', 0)
                merged.append({
                    'text':  merged_text,
                    'bbox':  merged_box,
                    'score': float(np.mean([score1, score2])),
                    'source': results[i].get('source') or results[j].get('source') or 'page',
                })
                used.add(i)
                used.add(j)
                found = True
                break
        if not found:
            merged.append(results[i])
            used.add(i)
    return merged


def _compute_iom(a: list, b: list) -> float:
    """Intersection over Minimum area — better than IoU for nested text boxes."""
    xA, yA = max(a[0], b[0]), max(a[1], b[1])
    xB, yB = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, xB - xA) * max(0, yB - yA)
    if inter == 0:
        return 0.0
    min_area = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
    return inter / float(min_area) if min_area > 0 else 0.0


def _dedup_text_boxes(results: list, iom_thresh: float = 0.3) -> list:
    """Remove tile-overlap duplicates using IoM NMS."""
    results = sorted(results, key=lambda x: x.get('score', 0), reverse=True)
    keep = []
    for cur in results:
        if any(_compute_iom(cur['bbox'], k['bbox']) > iom_thresh for k in keep):
            continue
        keep.append(cur)
    return keep
