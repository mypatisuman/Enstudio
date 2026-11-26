"""
PID Accuracy Service — Intrinsic evaluation, ground-truth benchmarking,
diagnostic gap detection, and accuracy-guided prompt refinement.

Enables the Brownfield Agent and validation workflows to:
1. Quantify digital P&ID accuracy (ISA-5.1 compliance, loop completeness, orphan rates).
2. Benchmark against ground-truth reference data (Precision, Recall, F1).
3. Generate targeted prompt refinement directives to eliminate omissions.
4. Execute diagnostic-guided re-analysis with Qwen3-VL to iteratively improve diagram quality.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Standard ISA-5.1 instrument tag pattern:
# Variables: P (Pressure), T (Temperature), F (Flow), L (Level), A (Analysis), PD (Diff Pressure)
# Functions: T (Transmitter), I (Indicator), C (Controller), V (Valve), SV (Safety Valve), S (Switch)
_ISA_INSTRUMENT_PATTERN = re.compile(
    r"^(P|T|F|L|A|PD|DP|PI|TI|FI|LI|AI|PT|TT|FT|LT|FTC|FE|PIC|TIC|FIC|LIC|AIC|PV|TV|FV|LV|PSV|PRV|HV|XV|SOV|ZV|EV|SV|FCV|PCV|TCV|LCV|CK|NRV|CV|BPR|TW|RO|FO)"
    r"[-_ ]?(\d{1,4}[A-Z]?)$",
    re.IGNORECASE
)

# Standard equipment tag pattern: C (Column), V (Vessel), P (Pump), E/HE (Exchanger/Cooler), M/MX (Mixer), TK (Tank), K (Compressor), F/H (Furnace/Heater)
_EQUIPMENT_PATTERN = re.compile(
    r"^(C|T|V|P|E|HE|M|MX|TK|K|F|H|D|R|S|B|HEX|PUMP|VESSEL|COL|SP|FL|BL|ST|CY|SKID|TUBE)"
    r"[-_ ]?(\d{1,4}[A-Z]?)$",
    re.IGNORECASE
)


def evaluate_intrinsic_accuracy(
    pid: str,
    save_local: bool = True,
    agent_type: str = "general",
    user_message: str = "",
) -> dict[str, Any]:
    """Calculate intrinsic engineering accuracy for a digitized P&ID graph in SQLite.

    Evaluates:
      1. ISA-5.1 tag syntax compliance
      2. Control loop completeness (transmitter -> controller -> valve)
      3. Topology & orphan connectivity
      4. Plant hierarchy & subsystem assignment


    Returns:
      Dict with composite accuracy score (0-100), sub-scores, and diagnostic issues.
    """
    from adapters.db import get_db
    db = get_db()

    # 1. Fetch nodes and edges
    nodes_rows = db.execute(
        "SELECT id, label, kind, kind_detail, area, origin FROM nodes WHERE pid=?",
        (pid,)
    ).fetchall()
    edges_rows = db.execute(
        "SELECT from_id, to_id, kind, label FROM edges WHERE pid=?",
        (pid,)
    ).fetchall()
    loops_rows = db.execute(
        "SELECT loop_id, loop_json FROM loops WHERE pid=?",
        (pid,)
    ).fetchall()
    hierarchy_rows = db.execute(
        "SELECT h.id, h.name, h.level FROM hierarchy h WHERE h.pid=?",
        (pid,)
    ).fetchall()

    total_nodes = len(nodes_rows)
    total_edges = len(edges_rows)

    if total_nodes == 0:
        return {
            "pid": pid,
            "accuracy_score": 0.0,
            "rating": "EMPTY",
            "digitised": False,
            "total_nodes": 0,
            "total_edges": 0,
            "issues": ["Project holds no nodes; drawing has not been digitized."],
            "prompt_refinements": ["Initial drawing digitization required."]
        }

    issues: list[str] = []
    node_ids = {r[0] for r in nodes_rows}
    connected_ids: set[str] = set()
    for e in edges_rows:
        connected_ids.add(e[0])
        connected_ids.add(e[1])

    # ── A. Topology & Orphan Connectivity ─────────────────────────────────────
    orphans = [nid for nid in node_ids if nid not in connected_ids]
    orphan_count = len(orphans)
    connectivity_score = max(0.0, 100.0 * (1.0 - (orphan_count / total_nodes)))
    if orphan_count > 0:
        issues.append(f"{orphan_count} orphan node(s) with no piping or signal connections: {orphans[:5]}")

    # Check for dangling edges
    dangling_edges = 0
    for e in edges_rows:
        if e[0] not in node_ids or e[1] not in node_ids:
            dangling_edges += 1
    if dangling_edges > 0:
        issues.append(f"{dangling_edges} edge(s) reference non-existent nodes.")
        connectivity_score = max(0.0, connectivity_score - (5.0 * dangling_edges))

    # ── B. ISA-5.1 Tag Syntax Compliance ──────────────────────────────────────
    valid_tags = 0
    invalid_tags: list[str] = []
    for r in nodes_rows:
        tag = (r[1] or r[0]).strip()
        kind = (r[2] or "").lower()
        if "tie_in" in kind or tag.startswith("TP-") or "-HEADER" in tag.upper() or "HEADER" in tag.upper() or tag.startswith(("HDR-", "BL-")):
            valid_tags += 1
        elif _ISA_INSTRUMENT_PATTERN.match(tag):
            valid_tags += 1
        elif _EQUIPMENT_PATTERN.match(tag):
            valid_tags += 1
        elif any(tag.startswith(pfx) for pfx in ("FE-", "RO-", "FO-", "MNF-", "SYP-", "HV-", "CK-", "BPR-")):
            valid_tags += 1
        else:
            invalid_tags.append(tag)

    tag_compliance_score = (valid_tags / total_nodes) * 100.0 if total_nodes else 0.0
    if invalid_tags:
        issues.append(f"{len(invalid_tags)} non-standard or unclassified tag(s): {invalid_tags[:6]}")

    # ── C. Control Loop Completeness ──────────────────────────────────────────
    # Check loops recorded in loops table or infer from tags
    loop_records = []
    for lr in loops_rows:
        try:
            data = json.loads(lr[1]) if lr[1] else {}
            loop_records.append(data)
        except Exception:
            pass

    # Also infer loops from instrument numbering
    detected_loops: dict[str, dict[str, list[str]]] = {}
    for r in nodes_rows:
        tag = (r[1] or r[0]).strip()
        m = _ISA_INSTRUMENT_PATTERN.match(tag)
        if m:
            prefix, loop_num = m.group(1).upper(), m.group(2)
            detected_loops.setdefault(loop_num, {"transmitters": [], "controllers": [], "valves": [], "others": []})
            # Controllers and valves are tested before transmitters/indicators:
            # checking "FI" first filed every FIC under transmitters, so a
            # complete FE/FT/FIC loop was reported as "missing controller".
            if prefix in ("PIC", "TIC", "FIC", "LIC", "AIC", "PC", "TC", "FC", "LC", "FTC", "PTC", "TTC", "LTC"):
                detected_loops[loop_num]["controllers"].append(tag)
            elif any(prefix.startswith(v) for v in ("PV", "TV", "FV", "LV", "PSV", "PRV", "FCV", "PCV", "TCV", "LCV", "BPR", "CK")):
                detected_loops[loop_num]["valves"].append(tag)
            elif any(prefix.startswith(t) for t in ("PT", "TT", "FT", "LT", "AI", "PI", "TI", "FI", "LI", "FE", "TE", "LE", "PE")):
                detected_loops[loop_num]["transmitters"].append(tag)
            else:
                detected_loops[loop_num]["others"].append(tag)

    declared_loop_ids = {str(lr[0]).strip() for lr in loops_rows if lr[0]}

    # Filter detected loops to only those that represent actual feedback/feedforward control loops
    control_loops: dict[str, dict[str, list[str]]] = {}
    for l_num, members in detected_loops.items():
        is_declared = l_num in declared_loop_ids
        has_controller = len(members["controllers"]) > 0
        has_control_valve = any(v.upper().startswith(("PV-", "TV-", "FV-", "LV-", "FCV-", "PCV-", "TCV-", "LCV-")) for v in members["valves"])
        has_active_tx = any(t.upper().startswith(("PT-", "TT-", "FT-", "LT-", "FTC-", "FE-")) for t in members["transmitters"])

        # In ISA-5.1, standalone hand valves (HV), check valves (CK), or local indicators (PI)
        # are not closed control loops and do not require controllers or automated valves
        if is_declared or has_controller or (has_active_tx and has_control_valve):
            control_loops[l_num] = members

    complete_loops = 0
    total_evaluated_loops = len(control_loops)
    for l_num, members in control_loops.items():
        has_tx = len(members["transmitters"]) > 0
        has_ctrl = len(members["controllers"]) > 0
        has_valve = len(members["valves"]) > 0
        if has_tx and (has_ctrl or has_valve):
            complete_loops += 1
        else:
            missing = []
            if not has_tx:
                missing.append("transmitter/element")
            if not has_ctrl:
                missing.append("controller")
            if not has_valve:
                missing.append("control valve")
            issues.append(f"Control Loop {l_num} is incomplete: missing {', '.join(missing)}")

    # No control loops means there is nothing to score, not a perfect score:
    # a drawing whose loops were never read used to get 100% here.
    loop_completeness_score = (complete_loops / total_evaluated_loops) * 100.0 if total_evaluated_loops else None

    # ── D. Hierarchy & Subsystem Coverage ─────────────────────────────────────
    assigned_count = db.execute(
        "SELECT COUNT(DISTINCT node_id) FROM node_hierarchy WHERE pid=?",
        (pid,)
    ).fetchone()[0]
    hierarchy_score = (assigned_count / total_nodes) * 100.0 if total_nodes else 0.0
    if assigned_count < total_nodes:
        unassigned_count = total_nodes - assigned_count
        issues.append(f"{unassigned_count} node(s) not yet mapped into a plant subsystem.")

    # ── Composite Accuracy Score Calculation ──────────────────────────────────
    # Weighted: Topology (35%), Tag Compliance (30%), Loop Completeness (25%), Hierarchy (10%).
    # When there are no loops to score, the remaining weights are renormalised.
    weighted = [(0.35, connectivity_score), (0.30, tag_compliance_score),
                (0.25, loop_completeness_score), (0.10, hierarchy_score)]
    weighted = [(w, s) for w, s in weighted if s is not None]
    accuracy = round(sum(w * s for w, s in weighted) / sum(w for w, _ in weighted), 1)
    accuracy = max(0.0, min(100.0, accuracy))

    rating = "EXCELLENT" if accuracy >= 90 else ("GOOD" if accuracy >= 75 else ("FAIR" if accuracy >= 60 else "NEEDS_IMPROVEMENT"))

    refinements = generate_prompt_refinements({
        "pid": pid,
        "accuracy_score": accuracy,
        "orphans": orphans,
        "invalid_tags": invalid_tags,
        "detected_loops": detected_loops,
        "issues": issues,
    })

    res = {
        "pid": pid,
        "accuracy_score": accuracy,
        "rating": rating,
        "digitised": True,
        "metrics": {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "total_loops": total_evaluated_loops,
            "connectivity_score": round(connectivity_score, 1),
            "tag_compliance_score": round(tag_compliance_score, 1),
            "loop_completeness_score": (round(loop_completeness_score, 1)
                                        if loop_completeness_score is not None else None),
            "hierarchy_score": round(hierarchy_score, 1),
        },
        "issues": issues,
        "prompt_refinements": refinements.get("focused_directives", []),
    }

    if save_local:
        try:
            _write_metric_files(pid, res, agent_type=agent_type, user_message=user_message)
        except Exception as exc:
            logger.debug(f"[AccuracyService] Could not auto-save to disk: {exc}")

    return res



def _gt_tag(item: Any) -> str:
    """A ground-truth entry as a tag: plain strings or {'tag': ...} dicts."""
    if isinstance(item, dict):
        item = item.get("tag") or item.get("id") or ""
    return str(item).strip().upper()


def _gt_edge(item: Any) -> tuple[str, str] | None:
    """A ground-truth line as an unordered tag pair: [a, b] or {'from_tag', 'to_tag'}."""
    if isinstance(item, dict):
        a, b = item.get("from_tag") or item.get("from"), item.get("to_tag") or item.get("to")
    elif isinstance(item, (list, tuple)) and len(item) >= 2:
        a, b = item[0], item[1]
    else:
        return None
    if not a or not b:
        return None
    a, b = str(a).strip().upper(), str(b).strip().upper()
    return (a, b) if a < b else (b, a)


def _prf(pred_set: set, true_set: set) -> tuple[float, float, float]:
    if not true_set and not pred_set:
        return 100.0, 100.0, 100.0
    tp = len(pred_set & true_set)
    fp = len(pred_set - true_set)
    fn = len(true_set - pred_set)
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
    return round(prec * 100, 1), round(rec * 100, 1), round(f1 * 100, 1)


def benchmark_against_ground_truth(
    pid: str,
    ground_truth: dict[str, Any]
) -> dict[str, Any]:
    """Precision, recall and F1 of the project's graph against ground truth.

    Accepts both ground-truth shapes in use:
      {"equipment": ["V-101", ...], "instruments": [...], "lines": [["A", "B"], ...]}
      the fixtures/ground_truth/*.json format, where entries are dicts
      ({"tag": ...}, {"from_tag": ..., "to_tag": ...}) and tie_ins are listed.
    Nodes are matched by tag (label), edges as unordered tag pairs. The old
    version crashed on the dict format with KeyError: 0.
    """
    from adapters.db import get_db
    db = get_db()

    nodes_rows = db.execute("SELECT id, label, kind FROM nodes WHERE pid=?", (pid,)).fetchall()
    edges_rows = db.execute("SELECT from_id, to_id FROM edges WHERE pid=?", (pid,)).fetchall()
    tag_of = {r[0]: (r[1] or r[0]).strip().upper() for r in nodes_rows}

    equip_kinds = {"column", "vessel", "pump", "heat_exchanger", "tank", "compressor", "furnace", "equipment"}
    gt_equip = {_gt_tag(x) for x in ground_truth.get("equipment", [])} - {""}
    gt_inst = {_gt_tag(x) for x in ground_truth.get("instruments", [])} - {""}
    gt_tie = {_gt_tag(x) for x in ground_truth.get("tie_ins", [])} - {""}
    gt_lines = {e for e in (_gt_edge(x) for x in ground_truth.get("lines", [])) if e}

    detected_equip, detected_inst, detected_tie = set(), set(), set()
    for nid, _label, kind in nodes_rows:
        tag = tag_of[nid]
        kind = (kind or "").lower()
        if kind == "tie_in" or tag in gt_tie:
            detected_tie.add(tag)
        elif kind in equip_kinds or tag in gt_equip or _EQUIPMENT_PATTERN.match(tag):
            detected_equip.add(tag)
        else:
            detected_inst.add(tag)
    detected_lines = set()
    for a, b in edges_rows:
        ta, tb = tag_of.get(a, str(a).upper()), tag_of.get(b, str(b).upper())
        detected_lines.add((ta, tb) if ta < tb else (tb, ta))

    eq_p, eq_r, eq_f1 = _prf(detected_equip, gt_equip)
    in_p, in_r, in_f1 = _prf(detected_inst, gt_inst)
    ln_p, ln_r, ln_f1 = _prf(detected_lines, gt_lines)
    macro_f1 = round((eq_f1 + in_f1 + ln_f1) / 3.0, 1)

    res = {
        "pid": pid,
        "benchmark_f1": macro_f1,
        "equipment": {"precision": eq_p, "recall": eq_r, "f1": eq_f1, "ground_truth": len(gt_equip)},
        "instruments": {"precision": in_p, "recall": in_r, "f1": in_f1, "ground_truth": len(gt_inst),
                        "missed": sorted(gt_inst - detected_inst)[:50],
                        "extra": sorted(detected_inst - gt_inst)[:50]},
        "lines": {"precision": ln_p, "recall": ln_r, "f1": ln_f1, "ground_truth": len(gt_lines)},
        "summary": f"Benchmark Macro F1: {macro_f1}% (Equipment: {eq_f1}%, Instruments: {in_f1}%, Lines: {ln_f1}%)"
    }
    if gt_tie:
        tp, tr, tf = _prf(detected_tie, gt_tie)
        res["tie_ins"] = {"precision": tp, "recall": tr, "f1": tf, "ground_truth": len(gt_tie)}
    return res


def generate_prompt_refinements(accuracy_report: dict[str, Any]) -> dict[str, Any]:
    """Generate targeted prompt directives and focus instructions based on detected gaps."""
    directives = []
    orphans = accuracy_report.get("orphans") or []
    invalid_tags = accuracy_report.get("invalid_tags") or []
    issues = accuracy_report.get("issues") or []

    # 1. Orphan directives
    if orphans:
        directives.append(
            f"DIAGNOSTIC FOCUS - DISCONNECTED PIPING: The following equipment nodes appear disconnected: {orphans[:4]}. "
            "Examine all suction, discharge, inlet, and outlet nozzles connecting these items to adjacent equipment."
        )

    # 2. Tag syntax directives
    if invalid_tags:
        directives.append(
            f"DIAGNOSTIC FOCUS - TAG OCR CONVENTIONS: Non-standard tags detected ({invalid_tags[:4]}). "
            "Ensure ISA-5.1 standard tagging: 2-3 letter variable+function code followed by loop number (e.g. PT-101, PIC-101, PV-101)."
        )

    # 3. Incomplete loop directives
    loop_issues = [iss for iss in issues if "Loop" in iss and "missing" in iss]
    if loop_issues:
        for li in loop_issues[:3]:
            directives.append(f"DIAGNOSTIC FOCUS - CONTROL LOOPS: {li}. Look for inline valves or field transmitters near the pipe run.")

    # 4. General quality prompt refinement
    if not directives:
        directives.append("DIAGNOSTIC FOCUS: Verify all utility streams (steam, CW, flare, vent) and battery limit tie-in points.")

    return {
        "focused_directives": directives,
        "suggested_system_prompt_addendum": "\n".join(f"- {d}" for d in directives)
    }


def refine_and_reanalyze(pid: str, user_id: int | None = 1) -> dict[str, Any]:
    """Second read of the drawing that ADDS what the first read missed.

    1. Evaluates current accuracy.
    2. Re-reads the drawing with the tiled vision pipeline (cache bypassed).
    3. Adds only nodes whose tags are not already in the graph, and
       connections between nodes that exist; never removes or renames.
    4. Re-evaluates accuracy.

    If the model cannot be reached the result is an error and nothing is
    written. (The old version inserted a hard-coded PV-101 / P-101A -> C-101
    patch into whatever drawing it was refining.)
    """
    initial_eval = evaluate_intrinsic_accuracy(pid)
    if initial_eval.get("rating") == "EMPTY":
        return {"error": f"ERROR: '{pid}' has not been digitised yet; rebuild it before refining."}
    # Only gaps a second read can close justify one: disconnected nodes and
    # incomplete loops. A misspelled tag is not one of them, and each re-read
    # costs minutes and adds its own noise.
    gaps = [i for i in initial_eval.get("issues") or []
            if "orphan" in i or "incomplete" in i or "non-existent" in i]
    if not gaps:
        return {
            "status": "noop",
            "summary": f"NOOP: '{pid}' has no disconnected nodes or incomplete loops; "
                       "a second read would not improve it.",
            "accuracy": initial_eval.get("accuracy_score"),
        }

    from domain.solution.services.brownfield_vision_service import analyze_uploaded_pid
    analysis = analyze_uploaded_pid(pid, use_cache=False)
    if analysis.get("error"):
        return {"error": analysis["error"]}

    from adapters.db import get_db
    db = get_db()
    existing = {str(r[0]).upper() for r in db.execute("SELECT COALESCE(label, id) FROM nodes WHERE pid=?", (pid,))}
    added_nodes = 0
    added_edges = 0

    for group, default_kind in ((analysis.get("equipment") or [], "vessel"),
                                (analysis.get("instruments") or [], "instrument"),
                                (analysis.get("tie_ins") or [], "tie_in")):
        for n in group:
            tag = str(n.get("tag") or "").strip()
            if not tag or tag.upper() in existing:
                continue
            kind = "tie_in" if default_kind == "tie_in" else (n.get("kind") or default_kind)
            db.execute(
                "INSERT INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json, origin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted')",
                (tag, pid, kind, n.get("kind_detail") or kind.title(), tag, n.get("area") or "",
                 float(n.get("x") or 0.0), float(n.get("y") or 0.0),
                 json.dumps({"loop": n.get("loop", ""), "origin": "extracted",
                             "source": "accuracy_refinement"})))
            existing.add(tag.upper())
            added_nodes += 1

    node_ids = {r[0] for r in db.execute("SELECT id FROM nodes WHERE pid=?", (pid,))}
    edge_pairs = {tuple(sorted(r)) for r in db.execute("SELECT from_id, to_id FROM edges WHERE pid=?", (pid,))}
    for line in analysis.get("lines") or []:
        f, t = str(line.get("from_tag") or "").strip(), str(line.get("to_tag") or "").strip()
        if not f or not t or f not in node_ids or t not in node_ids:
            continue
        if tuple(sorted((f, t))) in edge_pairs:
            continue
        db.execute(
            "INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json, origin) VALUES (?, ?, ?, ?, ?, ?, 'extracted')",
            (pid, f, t, line.get("kind", "process"), line.get("line_id", "REF-L"),
             json.dumps({"origin": "extracted", "source": "accuracy_refinement"})))
        edge_pairs.add(tuple(sorted((f, t))))
        added_edges += 1

    existing_loops = {r[0] for r in db.execute("SELECT loop_id FROM loops WHERE pid=?", (pid,))}
    for lp in analysis.get("loops") or []:
        lid = str(lp.get("loop_id") or "").strip()
        if lid and lid not in existing_loops and all(m in node_ids for m in lp.get("members") or []):
            db.execute("INSERT INTO loops (loop_id, pid, loop_json) VALUES (?, ?, ?)",
                       (lid, pid, json.dumps(lp)))
    db.commit()

    updated_eval = evaluate_intrinsic_accuracy(pid)
    before_score = initial_eval.get("accuracy_score", 0.0)
    after_score = updated_eval.get("accuracy_score", 0.0)
    delta = round(after_score - before_score, 1)
    summary_msg = (
        f"Refinement read of '{pid}' complete. Added {added_nodes} node(s) and {added_edges} "
        f"connection(s) the first read missed. Accuracy score {before_score}% -> {after_score}% "
        f"({'+' if delta >= 0 else ''}{delta}%)."
    )
    logger.info(f"[AccuracyService] {summary_msg}")
    return {
        "status": "success",
        "pid": pid,
        "before_score": before_score,
        "after_score": after_score,
        "delta": delta,
        "added_nodes": added_nodes,
        "added_edges": added_edges,
        "summary": summary_msg,
        "updated_issues": updated_eval.get("issues", []),
    }


# ── Local File Metrics Persistence & Historical Analytics ───────────────────

def resolve_metrics_storage_dir() -> Path:
    """Return local directory for persistent accuracy metrics files."""
    base_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "accuracy_metrics"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _write_metric_files(
    pid: str,
    eval_res: dict[str, Any],
    agent_type: str = "general",
    user_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storage_dir = resolve_metrics_storage_dir()
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "pid": pid,
        "agent_type": agent_type,
        "user_message": (user_message or "")[:300],
        "accuracy_score": eval_res.get("accuracy_score", 0.0),
        "rating": eval_res.get("rating", "UNKNOWN"),
        "metrics": eval_res.get("metrics", {}),
        "issues": eval_res.get("issues", []),
        "prompt_refinement_hints": eval_res.get("prompt_refinements", []),
        "metadata": metadata or {},
    }

    # 1. Write latest project snapshot
    latest_file = storage_dir / f"{pid}_latest.json"
    try:
        latest_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"[AccuracyService] Could not write {latest_file}: {exc}")

    # 2. Append to chronological history log
    history_file = storage_dir / "accuracy_history.jsonl"
    try:
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning(f"[AccuracyService] Could not append to {history_file}: {exc}")

    logger.info(f"[AccuracyService] Saved accuracy record for {pid} ({record['accuracy_score']}%) to local file.")
    return record


def save_accuracy_evaluation(
    pid: str,
    agent_type: str = "general",
    user_message: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate diagram accuracy (0 LLM credits) and persist locally to JSON and JSONL.

    Writes:
      1. <storage_dir>/<pid>_latest.json
      2. <storage_dir>/accuracy_history.jsonl
    """
    eval_res = evaluate_intrinsic_accuracy(pid, save_local=False)
    return _write_metric_files(pid, eval_res, agent_type=agent_type, user_message=user_message, metadata=metadata)



def get_accuracy_history(
    pid: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Load historical evaluation records from local JSONL storage."""
    history_file = resolve_metrics_storage_dir() / "accuracy_history.jsonl"
    if not history_file.is_file():
        return []

    records = []
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if pid is None or data.get("pid") == pid:
                        records.append(data)
                except Exception:
                    continue
    except Exception as exc:
        logger.warning(f"[AccuracyService] Error reading {history_file}: {exc}")

    return records[-limit:]


def analyze_stored_accuracy_metrics() -> dict[str, Any]:
    """Read all historical local metrics files and perform cross-project pattern analysis.

    Produces diagnostic failure distributions and concrete improvement recommendations
    for Greenfield and Brownfield agents without consuming any LLM credits.
    """
    storage_dir = resolve_metrics_storage_dir()
    history = get_accuracy_history(limit=500)

    if not history:
        return {
            "total_evaluations": 0,
            "message": "No historical accuracy records found. Run evaluations first to populate metrics."
        }

    total_runs = len(history)
    scores = [r.get("accuracy_score", 0.0) for r in history]
    avg_score = round(sum(scores) / total_runs, 1) if total_runs else 0.0

    # Categorize by agent type
    by_agent: dict[str, list[dict]] = {}
    for r in history:
        agent = r.get("agent_type") or "general"
        by_agent.setdefault(agent, []).append(r)

    agent_summary = {}
    for agent, runs in by_agent.items():
        agent_scores = [x.get("accuracy_score", 0.0) for x in runs]
        agent_summary[agent] = {
            "total_runs": len(runs),
            "avg_accuracy": round(sum(agent_scores) / len(runs), 1),
            "min_accuracy": min(agent_scores) if agent_scores else 0.0,
            "max_accuracy": max(agent_scores) if agent_scores else 0.0,
        }

    # Aggregate common failure issues
    issue_counts: dict[str, int] = {}
    orphan_tags: list[str] = []
    incomplete_loops: list[str] = []
    invalid_tags: list[str] = []

    for r in history:
        for iss in r.get("issues") or []:
            # Normalize issue message for frequency counting
            clean_iss = re.sub(r"\[.*?\]", "[...]", iss)
            clean_iss = re.sub(r"\d+", "N", clean_iss)
            issue_counts[clean_iss] = issue_counts.get(clean_iss, 0) + 1

            if "orphan" in iss.lower():
                orphan_tags.append(iss)
            elif "loop" in iss.lower() and "incomplete" in iss.lower():
                incomplete_loops.append(iss)
            elif "non-standard" in iss.lower() or "unclassified" in iss.lower():
                invalid_tags.append(iss)

    top_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Generate actionable prompt and logic recommendations
    greenfield_recs = [
        "Ensure all synthesized instrument packages include explicit valve_between=[tag_a, tag_b] so control valves are inserted inline without becoming orphan nodes.",
        "Always call create_subsystem / assign_to_subsystem immediately after synthesizing equipment trains to maintain 100% hierarchy coverage.",
        "Verify suction and discharge line connectivity on all synthesized pumps (e.g. P-101A/B) to eliminate orphan pump ratings.",
    ]

    brownfield_recs = [
        "When tying into existing header nozzles (TP-01 / TP-02), confirm line continuity with break_line rather than creating isolated branches.",
        "Preserve existing digitised tag numbers; do not rename existing transmitters during retrofit passes.",
        "In Qwen3-VL visual digitisation passes, prompt explicitly for field control valves (PV/TV/FV/LV) inline with process headers.",
    ]

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_evaluations": total_runs,
        "overall_avg_accuracy": avg_score,
        "performance_by_agent": agent_summary,
        "top_recurring_issues": [{"pattern": p, "occurrences": count} for p, count in top_issues],
        "diagnostics": {
            "orphan_incidents": len(orphan_tags),
            "incomplete_loop_incidents": len(incomplete_loops),
            "unclassified_tag_incidents": len(invalid_tags),
        },
        "recommendations": {
            "greenfield_agent": greenfield_recs,
            "brownfield_agent": brownfield_recs,
        }
    }

    # Save analytics report to file
    try:
        (storage_dir / "accuracy_analytics_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        # Also generate markdown version
        md_content = f"""# P&ID Accuracy & Agent Diagnostic Analytics Report
Generated: {report['timestamp']}

## 1. Overall Performance
- **Total Evaluations Logged:** {total_runs}
- **Average Accuracy Score:** {avg_score}%

## 2. Performance by Agent Type
| Agent / Workflow | Total Runs | Avg Accuracy | Min | Max |
| :--- | :--- | :--- | :--- | :--- |
"""
        for ag, d in agent_summary.items():
            md_content += f"| `{ag}` | {d['total_runs']} | **{d['avg_accuracy']}%** | {d['min_accuracy']}% | {d['max_accuracy']}% |\n"

        md_content += """
## 3. Top Recurring Structural Gaps
"""
        for item in report['top_recurring_issues']:
            md_content += f"- **({item['occurrences']}x)** {item['pattern']}\n"

        md_content += """
## 4. Greenfield Agent Functionality & Prompt Improvements
"""
        for rec in greenfield_recs:
            md_content += f"- [ ] {rec}\n"

        md_content += """
## 5. Brownfield Agent Functionality & Prompt Improvements
"""
        for rec in brownfield_recs:
            md_content += f"- [ ] {rec}\n"

        (storage_dir / "accuracy_analytics_report.md").write_text(md_content, encoding="utf-8")
    except Exception as exc:
        logger.warning(f"[AccuracyService] Could not save analytics report files: {exc}")

    return report

