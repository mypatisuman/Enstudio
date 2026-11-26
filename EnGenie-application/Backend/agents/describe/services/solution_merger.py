"""Solution Merger — accumulates and synthesizes multi-turn engineering solutions.

Merges an active/previous solution design with a new incremental design turn:
1. Merges and deduplicates component_roles by ISA tag.
2. Re-calculates and stacks 5-corridor layout plans to prevent overlapping coordinates.
3. Combines optimizations, design considerations, and assumptions.
"""
from __future__ import annotations

import copy
from typing import Any


def merge_solution_designs(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None
) -> dict[str, Any]:
    """Merges an existing partial solution design with a new incoming turn."""
    if not existing:
        res = copy.deepcopy(incoming or {})
        if res:
            res["completeness"] = calculate_architecture_completeness(res)
        return res
    if not incoming:
        res = copy.deepcopy(existing or {})
        if res:
            res["completeness"] = calculate_architecture_completeness(res)
        return res

    merged = copy.deepcopy(existing)

    # 1. Merge Inferred Plant Type & Objective
    in_plant = incoming.get("inferred_plant_type", "").strip()
    ex_plant = existing.get("inferred_plant_type", "").strip()
    if in_plant and in_plant != ex_plant and ex_plant not in in_plant:
        if in_plant not in ex_plant:
            merged["inferred_plant_type"] = f"{ex_plant} & {in_plant}"
    elif in_plant:
        merged["inferred_plant_type"] = in_plant

    in_obj = incoming.get("project_objective", "").strip()
    ex_obj = existing.get("project_objective", "").strip()
    if in_obj and in_obj != ex_obj:
        merged["project_objective"] = f"{ex_obj} | {in_obj}" if ex_obj else in_obj

    in_ov = incoming.get("design_overview", "").strip()
    ex_ov = existing.get("design_overview", "").strip()
    if in_ov and in_ov != ex_ov:
        merged["design_overview"] = f"{ex_ov}\n\nAdditional Subsystem: {in_ov}" if ex_ov else in_ov

    # 2. Merge Unit Operations
    ex_ops = list(existing.get("unit_operations") or [])
    in_ops = list(incoming.get("unit_operations") or [])
    seen_ops = set(ex_ops)
    for op in in_ops:
        if op not in seen_ops:
            ex_ops.append(op)
            seen_ops.add(op)
    merged["unit_operations"] = ex_ops

    # 3. Merge Component Roles (deduplicate by tag/name)
    ex_roles = list(existing.get("component_roles") or [])
    in_roles = list(incoming.get("component_roles") or [])
    role_map: dict[str, dict] = {}
    for r in ex_roles:
        key = (r.get("tag") or r.get("name") or "").strip().upper()
        if key:
            if "name" not in r and "tag" in r:
                r["name"] = r["tag"]
            if "tag" not in r and "name" in r:
                r["tag"] = r["name"]
            role_map[key] = r

    for r in in_roles:
        key = (r.get("tag") or r.get("name") or "").strip().upper()
        if not key:
            continue
        if "name" not in r and "tag" in r:
            r["name"] = r["tag"]
        if key in role_map:
            # Update purpose / category / specifications / instrument_config if refined
            if r.get("purpose"):
                role_map[key]["purpose"] = r["purpose"]
            if r.get("category") and (not role_map[key].get("category") or role_map[key].get("category") == "Process Connection"):
                role_map[key]["category"] = r["category"]
            if r.get("specifications"):
                role_map[key].setdefault("specifications", {}).update(r["specifications"])
            if r.get("instrument_config"):
                role_map[key].setdefault("instrument_config", {}).update(r["instrument_config"])
        else:
            role_map[key] = r
    merged["component_roles"] = list(role_map.values())

    # 4. Merge 5-Corridor Layout Plan
    ex_plan = list(existing.get("layout_plan") or [])
    in_plan = list(incoming.get("layout_plan") or [])
    
    # Track existing tags and column offsets per corridor
    corridor_max_col: dict[str, int] = {}
    corridor_max_x: dict[str, int] = {}
    plan_map: dict[str, dict] = {}

    for item in ex_plan:
        tag = (item.get("tag") or "").strip().upper()
        if not tag:
            continue
        plan_map[tag] = item
        corridor = item.get("corridor") or "Channel 2: Ingress Feed Rail"
        col = int(item.get("col", 0))
        x = int(item.get("x", 100))
        corridor_max_col[corridor] = max(corridor_max_col.get(corridor, -1), col)
        corridor_max_x[corridor] = max(corridor_max_x.get(corridor, 0), x)

    for item in in_plan:
        tag = (item.get("tag") or "").strip().upper()
        if not tag:
            continue
        if tag in plan_map:
            # Keep or update anchor
            if item.get("anchor"):
                plan_map[tag]["anchor"] = item["anchor"]
        else:
            corridor = item.get("corridor") or "Channel 2: Ingress Feed Rail"
            next_col = corridor_max_col.get(corridor, -1) + 1
            base_x = corridor_max_x.get(corridor, 100)
            step_x = 180 if "Relief" in corridor or "Effluent" in corridor else 220
            next_x = base_x + step_x if base_x > 0 else 100

            new_item = copy.deepcopy(item)
            new_item["col"] = next_col
            new_item["x"] = next_x
            corridor_max_col[corridor] = next_col
            corridor_max_x[corridor] = next_x
            plan_map[tag] = new_item

    merged["layout_plan"] = list(plan_map.values())

    # 5. Merge Optimizations, Design Considerations, Assumptions
    for field in ("optimizations", "design_considerations", "assumptions"):
        ex_list = list(existing.get(field) or [])
        in_list = list(incoming.get(field) or [])
        seen_items = set(ex_list)
        for itm in in_list:
            if itm not in seen_items:
                ex_list.append(itm)
                seen_items.add(itm)
        merged[field] = ex_list

    # 6. Calculate Architecture Completeness (60% Threshold for Canvas Building)
    merged["completeness"] = calculate_architecture_completeness(merged)

    return merged


def calculate_architecture_completeness(solution_design: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluates whether the accumulated solution design has reached >=60% maturity
    across the 5 foundational engineering process pillars."""
    if not solution_design:
        return {"score": 0, "can_build_canvas": False, "status": "empty", "pillars": {}}

    roles = solution_design.get("component_roles") or []
    layout = solution_design.get("layout_plan") or []
    tags = [((r.get("name") or r.get("tag") or "")).upper() for r in roles] + \
           [(item.get("tag") or "").upper() for item in layout]
    
    pillars = {
        "feed_ingress": {
            "name": "Ingress Feed & Blending",
            "weight": 20,
            "met": any("FEED" in t or "HDR" in t or "MIX" in t or t.startswith("M-") for t in tags),
        },
        "core_processing": {
            "name": "Core Reaction & Equipment",
            "weight": 25,
            "met": any(t.startswith("R-") or t.startswith("V-") or t.startswith("C-") or t.startswith("TK-") or "REACTOR" in t or "COLUMN" in t for t in tags),
        },
        "safety_relief": {
            "name": "Overpressure Relief & Vent",
            "weight": 20,
            "met": any("PSV" in t or "PRV" in t or "VENT" in t or "FLARE" in t or "RELIEF" in t for t in tags),
        },
        "downstream_separation": {
            "name": "Separation, Bypass & Effluent",
            "weight": 15,
            "met": any("HE-" in t or t.startswith("E-") or "KO" in t or "BYPASS" in t or "EFFLUENT" in t or "DRAIN" in t or "ANALYTICS" in t for t in tags),
        },
        "instrumentation_control": {
            "name": "Instrumentation & Control Tap",
            "weight": 20,
            "met": any(t.startswith("PI") or t.startswith("PT") or t.startswith("TI") or t.startswith("TT") or t.startswith("TE") or t.startswith("XY") or t.startswith("HV") or t.startswith("CV") for t in tags),
        },
    }

    # Minimum base score if at least 2 components exist
    score = sum(p["weight"] for p in pillars.values() if p["met"])
    if len(tags) >= 15 and score < 60:
        score = min(100, score + 15)  # bonus for high component count
    if len(tags) >= 25 and score < 75:
        score = min(100, score + 15)

    can_build = score >= 60

    status = "ready_for_canvas" if can_build else "draft_in_progress"
    return {
        "score": score,
        "can_build_canvas": can_build,
        "status": status,
        "pillars": pillars,
        "components_count": len(set(tags)),
    }

