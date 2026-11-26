"""
benchmarks/scoring.py — compare an extracted drawing with its ground truth.

Both sides are connectivity-graph documents (schema 2.x): the truth file, and
the export of what extraction produced. Scoring is deliberately tag-centred,
because tags are what an engineer checks first and what every downstream export
keys on.

Metrics
-------
tags          precision / recall / F1 over normalised tag labels
              (upper-case, spaces and hyphens removed: "R-110 B" == "R110B").
              Only ISA-style tags count; descriptive labels such as "Filter 1"
              are reported but not scored, since no extractor can be expected
              to reproduce free text exactly.
types         share of matched tags whose node type agrees.
boxes         for matched tags with a box on both sides: mean IoU and the share
              at IoU >= 0.5, after scaling the prediction to the truth image.
connections   precision / recall / F1 over unordered tag pairs, after
              collapsing junction chains so "A -> T-junction -> B" and a direct
              "A -> B" count the same. Reported twice: over all tags, and over
              tags both sides found, which separates "missed the symbol" from
              "wired it wrong".
"""

from __future__ import annotations

import re
from collections import deque

JUNCTION_TYPES = {"t_junction", "endpoint_share", "crossover", "open_endpoint"}
_TAG_RE = re.compile(r"^[A-Z]{1,5}[- ]?\d{1,6}[A-Z]{0,2}(\s?[A-Z])?$")


def normalise(label: str | None) -> str:
    return re.sub(r"[\s\-_]+", "", (label or "").upper())


def is_tag(label: str | None) -> bool:
    return bool(_TAG_RE.match((label or "").strip().upper()))


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4),
            "tp": tp, "fp": fp, "fn": fn}


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def tagged_nodes(doc: dict) -> dict[str, dict]:
    """normalised tag -> node entry (first occurrence wins)."""
    out: dict[str, dict] = {}
    for key, node in (doc.get("nodes") or {}).items():
        if node.get("type") in JUNCTION_TYPES or not is_tag(node.get("label")):
            continue
        out.setdefault(normalise(node["label"]), {**node, "_key": key})
    return out


def tag_pairs(doc: dict) -> set[frozenset]:
    """Unordered pairs of tags connected directly or through junction chains."""
    nodes = doc.get("nodes") or {}
    adj: dict[str, set] = {}
    for e in doc.get("edges") or []:
        a, b = e.get("from"), e.get("to")
        if a in nodes and b in nodes and a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    tag_of = {k: normalise(n.get("label")) for k, n in nodes.items()
              if n.get("type") not in JUNCTION_TYPES and is_tag(n.get("label"))}
    pairs: set[frozenset] = set()
    for start, tag in tag_of.items():
        seen, queue = {start}, deque([start])
        while queue:
            cur = queue.popleft()
            for nxt in adj.get(cur, ()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if nxt in tag_of:
                    if tag_of[nxt] != tag:
                        pairs.add(frozenset((tag, tag_of[nxt])))
                elif nodes[nxt].get("type") in JUNCTION_TYPES:
                    queue.append(nxt)          # walk through junctions only
    return pairs


def score(prediction: dict, truth: dict, prediction_scale: float = 1.0) -> dict:
    pred_tags, true_tags = tagged_nodes(prediction), tagged_nodes(truth)
    matched = sorted(set(pred_tags) & set(true_tags))
    tags = _prf(len(matched), len(set(pred_tags) - set(true_tags)),
                len(set(true_tags) - set(pred_tags)))

    type_hits = sum(1 for t in matched if pred_tags[t].get("type") == true_tags[t].get("type"))
    ious = []
    for t in matched:
        pb, tb = pred_tags[t].get("bbox"), true_tags[t].get("bbox")
        if pb and tb and len(pb) == 4 and len(tb) == 4:
            ious.append(_iou([v * prediction_scale for v in pb], tb))

    pred_pairs, true_pairs = tag_pairs(prediction), tag_pairs(truth)
    both = set(matched)
    restricted_pred = {p for p in pred_pairs if p <= both}
    restricted_true = {p for p in true_pairs if p <= both}
    return {
        "tags": tags,
        "untagged_truth_symbols": sum(1 for n in (truth.get("nodes") or {}).values()
                                      if n.get("type") not in JUNCTION_TYPES
                                      and not is_tag(n.get("label"))),
        "types": {"matched": len(matched),
                  "accuracy": round(type_hits / len(matched), 4) if matched else 0.0},
        "boxes": {"compared": len(ious),
                  "mean_iou": round(sum(ious) / len(ious), 4) if ious else 0.0,
                  "iou_at_0_5": round(sum(1 for i in ious if i >= 0.5) / len(ious), 4) if ious else 0.0},
        "connections": _prf(len(pred_pairs & true_pairs), len(pred_pairs - true_pairs),
                            len(true_pairs - pred_pairs)),
        "connections_among_found_tags": _prf(len(restricted_pred & restricted_true),
                                             len(restricted_pred - restricted_true),
                                             len(restricted_true - restricted_pred)),
        "missed_tags": sorted(set(true_tags) - set(pred_tags))[:50],
        "extra_tags": sorted(set(pred_tags) - set(true_tags))[:50],
    }


def aggregate(results: list[dict]) -> dict:
    """Micro-averaged totals across drawings."""
    out = {}
    for section in ("tags", "connections", "connections_among_found_tags"):
        tp = sum(r["score"][section]["tp"] for r in results)
        fp = sum(r["score"][section]["fp"] for r in results)
        fn = sum(r["score"][section]["fn"] for r in results)
        out[section] = _prf(tp, fp, fn)
    timed = [r for r in results if r.get("seconds") is not None]
    out["seconds_per_drawing"] = round(sum(r["seconds"] for r in timed) / len(timed), 1) if timed else None
    out["tokens_in"] = sum(r.get("tokens_in", 0) for r in results)
    out["tokens_out"] = sum(r.get("tokens_out", 0) for r in results)
    out["cost_usd"] = round(sum(r.get("cost_usd", 0.0) for r in results), 4)
    return out
