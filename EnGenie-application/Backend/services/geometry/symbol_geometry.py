"""symbol_geometry.py — pure coordinate arithmetic and box geometry for symbols.

Contains NO machine learning models or learned weights.
"""
from __future__ import annotations

# ── Tiling constants ──────────────────────────────────────────────────────────
_TILE_SIZE = 640
_OVERLAP   = 128
_STRIDE    = _TILE_SIZE - _OVERLAP   # 512

_CONF_THRESH  = 0.35
_NMS_IOU      = 0.3
_BLANK_DARK_THRESH  = 240
_BLANK_MIN_DARK_PX  = 50


def _tile_coords(img_w: int, img_h: int) -> list[tuple[int, int, int, int]]:
    """Compute overlapping tile coordinate bounds (x1, y1, x2, y2) for an image."""
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


def _iou(a, b) -> float:
    """Intersection-over-Union between two [x1, y1, x2, y2] bounding boxes."""
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if not inter:
        return 0.0
    aa = (a[2] - a[0]) * (a[3] - a[1])
    ba = (b[2] - b[0]) * (b[3] - b[1])
    denom = aa + ba - inter
    if denom <= 0:
        return 0.0
    return inter / denom


def _class_aware_nms(detections: list, iou_thresh: float = _NMS_IOU) -> list:
    """Non-max suppression that only suppresses within the same detected class."""
    if not detections:
        return []
    detections = sorted(detections, key=lambda d: d.get('score', 0), reverse=True)
    kept = []
    while detections:
        best = detections.pop(0)
        kept.append(best)
        detections = [
            d for d in detections
            if d.get('type') != best.get('type') or _iou(best['bbox'], d['bbox']) < iou_thresh
        ]
    return kept


def _cross_class_nms(detections: list, iou_thresh: float = 0.45) -> list:
    """Suppress lower-confidence detections that heavily overlap a higher-confidence
    detection of a DIFFERENT class."""
    if not detections:
        return []
    detections = sorted(detections, key=lambda d: d.get('score', 0), reverse=True)
    kept = []
    while detections:
        best = detections.pop(0)
        kept.append(best)
        detections = [
            d for d in detections
            if _iou(best['bbox'], d['bbox']) < iou_thresh
        ]
    return kept


def _merge_boxes(detections: list) -> list:
    """Merge overlapping boxes of the same class."""
    MERGE_IOU = 0.15
    changed = True
    while changed:
        changed = False
        merged = []
        used = [False] * len(detections)
        for i, a in enumerate(detections):
            if used[i]:
                continue
            cur = a
            for j, b in enumerate(detections):
                if i == j or used[j]:
                    continue
                if cur.get('type') == b.get('type') and _iou(cur['bbox'], b['bbox']) > MERGE_IOU:
                    bx1 = min(cur['bbox'][0], b['bbox'][0])
                    by1 = min(cur['bbox'][1], b['bbox'][1])
                    bx2 = max(cur['bbox'][2], b['bbox'][2])
                    by2 = max(cur['bbox'][3], b['bbox'][3])
                    cur = {
                        'type': cur.get('type'),
                        'bbox': [bx1, by1, bx2, by2],
                        'score': max(cur.get('score', 0), b.get('score', 0)),
                        'editable': cur.get('editable', True),
                    }
                    used[j] = True
                    changed = True
            merged.append(cur)
            used[i] = True
        detections = merged
    return detections
