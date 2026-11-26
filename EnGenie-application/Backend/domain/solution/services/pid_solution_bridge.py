"""
pid_solution_bridge.py — Bridge service linking Describe P&ID Graph output
with the Solution Agent Workflow to identify Instruments and deduce required Accessories.

Connects:
  Describe Agent / CAD Graph (Nodes, Connections, ISA Tags, Process Parameters)
    ↓
  Solution Agent Workflow (Taxonomy Mapping, Standards RAG, Parallel Pro Inference)
    ↓
  Hierarchical Instruments & Accessories BOM decorated back onto P&ID Nodes.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from domain.kind_mapping import INSTRUMENT_KINDS

logger = logging.getLogger(__name__)

_ISA_INSTRUMENT_PREFIXES = (
    "PT", "PIT", "PI", "PDT", "TT", "TIT", "TI", "TE", "FT", "FIT", "FE", "LT", "LIT",
    "LI", "LG", "AT", "AIT", "AI", "PCV", "FCV", "TCV", "LCV", "PSV", "PRV", "XV",
    "FV", "PV", "TV", "LV", "ZT", "ZIT", "SOV", "SV"
)

_VALVE_CONTROL_KINDS = {
    "valve", "control_valve", "cv_globe", "cv_ball", "cv_butterfly",
    "cv_gate", "cv_plug", "cv_diaphragm"
}


def _is_instrument_node(node: dict[str, Any]) -> bool:
    """Check if node represents an instrument or actuated control valve."""
    kind = str(node.get("kind") or "").lower().strip()
    kind_detail = str(node.get("kind_detail") or "").lower().strip()
    tag = str(node.get("tag") or node.get("label") or node.get("id") or "").upper().strip()

    if kind in INSTRUMENT_KINDS or kind_detail in INSTRUMENT_KINDS:
        return True
    if kind in _VALVE_CONTROL_KINDS or kind_detail in _VALVE_CONTROL_KINDS:
        # Actuated control valves participate in instrument BOM
        if any(tag.startswith(pfx) for pfx in ("FCV", "PCV", "TCV", "LCV", "XV", "CV")):
            return True

    # Check ISA tag pattern
    for pfx in _ISA_INSTRUMENT_PREFIXES:
        if tag.startswith(f"{pfx}-") or tag.startswith(f"{pfx}_") or tag == pfx:
            return True

    return False


def load_active_pid_graph(session_id: str, user_id: Any = None) -> dict[str, Any] | None:
    """Load the P&ID graph from MongoDB repository or Describe SQLite."""
    # 1. Try MongoDB pid_graph_repository
    try:
        from common.infra.repositories.pid_graph_repository import pid_graph_repository
        graph = pid_graph_repository.load_graph(user_id, session_id)
        if graph and (graph.get("nodes") or graph.get("edges")):
            logger.info(f"[PID_BRIDGE] Loaded P&ID graph from MongoDB for session {session_id} ({len(graph.get('nodes', []))} nodes)")
            return graph
    except Exception as e:
        logger.warning(f"[PID_BRIDGE] MongoDB graph load skipped or failed: {e}")

    # 2. Fallback to Describe SQLite
    try:
        from agents.describe.services import repository as R
        raw_nodes = R.search_graph(session_id)
        if raw_nodes:
            nodes = []
            for n in raw_nodes:
                detail = R.get_node(session_id, n.get("tag") or n.get("id"))
                extra = {}
                try:
                    extra = json.loads(detail.get("extra_json") or "{}") if detail.get("extra_json") else {}
                except Exception:
                    extra = {}
                nodes.append({
                    "id": detail.get("id"),
                    "tag": detail.get("tag"),
                    "label": detail.get("tag"),
                    "kind": detail.get("kind"),
                    "kind_detail": detail.get("kind_detail"),
                    "area": detail.get("area"),
                    "specifications": extra.get("specifications", {}),
                    "extra_json": extra,
                    "connections": detail.get("connections", []),
                })
            logger.info(f"[PID_BRIDGE] Loaded P&ID graph from SQLite for session {session_id} ({len(nodes)} nodes)")
            return {
                "session_id": session_id,
                "nodes": nodes,
                "edges": [],
            }
    except Exception as e:
        logger.warning(f"[PID_BRIDGE] SQLite graph load skipped or failed: {e}")

    return None


def build_engineering_requirements_prompt(
    graph: dict[str, Any],
    target_tags: list[str] | None = None
) -> str:
    """
    Construct a dense, structured engineering specification prompt from P&ID graph
    topology and operating constraints to feed into the Solution Agent workflow.
    """
    nodes = graph.get("nodes") or []
    target_set = set(t.upper() for t in target_tags) if target_tags else None

    instruments: list[dict[str, Any]] = []
    equipment: list[dict[str, Any]] = []

    for n in nodes:
        tag = (n.get("tag") or n.get("label") or n.get("id") or "").upper()
        if target_set and tag not in target_set:
            continue
        if _is_instrument_node(n):
            instruments.append(n)
        else:
            equipment.append(n)

    # If target_tags were provided but filtered too restrictively, include all detected instruments
    if not instruments and not target_set:
        instruments = [n for n in nodes if _is_instrument_node(n)]

    equip_summary = ", ".join(
        f"{e.get('tag') or e.get('label')} ({e.get('kind_detail') or e.get('kind') or 'equipment'})"
        for e in equipment[:15]
    ) or "Process Plant Unit"

    inst_descriptions = []
    for inst in instruments:
        tag = inst.get("tag") or inst.get("label") or inst.get("id")
        kind = inst.get("kind_detail") or inst.get("kind") or "Instrument"
        area = inst.get("area") or "Process Area"
        specs = inst.get("specifications") or inst.get("extra_json", {}).get("specifications", {})
        
        fluid = specs.get("fluid") or specs.get("medium") or specs.get("service") or "Process Fluid"
        press = specs.get("pressure") or specs.get("operating_pressure") or specs.get("design_pressure") or "Operating Pressure"
        temp = specs.get("temperature") or specs.get("operating_temp") or specs.get("design_temp") or "Operating Temperature"
        line_ref = inst.get("equipment_ref") or specs.get("line_ref") or "Process Line"

        desc = (
            f"- Instrument Tag: {tag} ({kind})\n"
            f"  Service/Line: {line_ref}, Fluid: {fluid}, Area: {area}\n"
            f"  Operating Conditions: Pressure: {press}, Temperature: {temp}"
        )
        inst_descriptions.append(desc)

    inst_block = "\n".join(inst_descriptions) if inst_descriptions else "- Identify standard instruments and accessories for process unit."

    prompt = (
        f"Detailed P&ID Engineering Equipment & Instrument Scope:\n"
        f"Plant Equipment in Scope: {equip_summary}\n\n"
        f"Identified P&ID Instruments:\n"
        f"{inst_block}\n\n"
        f"Task:\n"
        f"For each instrument listed above from the P&ID drawing, apply relevant engineering standards "
        f"(API 551, ISA-5.1, ASME B16.5, IEC 61511), infer complete physical and electrical specifications, "
        f"and identify all mandatory and optional ACCESSORIES (e.g., 2-valve/5-valve manifolds, flanged thermowells, "
        f"mounting brackets, air filter regulators, smart digital positioners, sunshades, and cable glands). "
        f"Provide the complete procurement Bill of Materials."
    )
    return prompt


def enrich_pid_with_solution_bom(
    session_id: str,
    user_id: Any = None,
    target_tags: list[str] | None = None,
    stream_id: str | None = None,
) -> dict[str, Any]:
    """
    Core bridge execution:
      1. Loads P&ID graph
      2. Formulates engineering prompt
      3. Invokes Solution Agent Workflow
      4. Decorates accessories and specifications back onto the P&ID nodes
      5. Saves the updated P&ID graph
    """
    logger.info(f"[PID_BRIDGE] Starting P&ID solution enrichment for session {session_id}")

    graph = load_active_pid_graph(session_id, user_id)
    if not graph or not graph.get("nodes"):
        return {
            "success": False,
            "error": f"No P&ID graph found for session '{session_id}'. Please author or ingest a drawing first.",
            "instruments": [],
            "accessories": [],
        }

    prompt = build_engineering_requirements_prompt(graph, target_tags)

    from common.services.agentic_integration import run_project_intent
    
    # Run the Solution Agent workflow with holistic bypass enabled (already engineered P&ID drawing)
    solution_result = run_project_intent(
        user_input=prompt,
        user_id=user_id,
        search_session_id=session_id,
        awaiting_holistic_confirmation=True,
        stream_id=stream_id,
    )

    instruments = solution_result.get("instruments") or []
    accessories = solution_result.get("accessories") or []
    summary = solution_result.get("summary") or solution_result.get("response_message") or ""

    # Group accessories by instrument tag or product
    accessories_by_tag: dict[str, list[dict[str, Any]]] = {}
    for acc in accessories:
        parent_tag = (acc.get("instrument_tag") or acc.get("parent_tag") or acc.get("instrumentTag") or "").upper().strip()
        if parent_tag:
            accessories_by_tag.setdefault(parent_tag, []).append(acc)

    # Decorate P&ID nodes in the graph
    nodes = graph.get("nodes") or []
    nodes_updated = 0

    for node in nodes:
        node_tag = (node.get("tag") or node.get("label") or node.get("id") or "").upper().strip()
        
        # Match instrument specifications
        matched_instr = next((i for i in instruments if (i.get("tag") or i.get("productName") or "").upper().strip() == node_tag), None)
        if matched_instr:
            node["specifications"] = matched_instr.get("specifications") or node.get("specifications", {})
            node["category"] = matched_instr.get("category") or node.get("category")
            node["standards"] = matched_instr.get("standards") or []
            nodes_updated += 1

        # Match paired accessories
        if node_tag in accessories_by_tag:
            node["accessories"] = accessories_by_tag[node_tag]
            if "extra_json" not in node or not isinstance(node["extra_json"], dict):
                node["extra_json"] = {}
            node["extra_json"]["accessories"] = accessories_by_tag[node_tag]
            nodes_updated += 1
        elif matched_instr and matched_instr.get("accessories"):
            node["accessories"] = matched_instr.get("accessories")
            if "extra_json" not in node or not isinstance(node["extra_json"], dict):
                node["extra_json"] = {}
            node["extra_json"]["accessories"] = matched_instr.get("accessories")
            nodes_updated += 1

    # Persist updated graph back to storage
    try:
        from common.infra.repositories.pid_graph_repository import pid_graph_repository
        pid_graph_repository.save(user_id, session_id, graph)
        logger.info(f"[PID_BRIDGE] Persisted enriched P&ID graph to MongoDB for session {session_id} ({nodes_updated} nodes updated)")
    except Exception as e:
        logger.warning(f"[PID_BRIDGE] Could not persist enriched graph to MongoDB: {e}")

    # Also persist to Describe SQLite if applicable
    try:
        from adapters.db import get_db
        db = get_db()
        for node in nodes:
            accs = node.get("accessories")
            if accs:
                tag = node.get("tag") or node.get("label") or node.get("id")
                row = db.execute("SELECT extra_json FROM nodes WHERE pid=? AND (label=? OR id=?)", (session_id, tag, tag)).fetchone()
                if row:
                    try:
                        cur_extra = json.loads(row[0] or "{}") if row[0] else {}
                    except Exception:
                        cur_extra = {}
                    cur_extra["accessories"] = accs
                    cur_extra["specifications"] = node.get("specifications", {})
                    db.execute("UPDATE nodes SET extra_json=? WHERE pid=? AND (label=? OR id=?)", (json.dumps(cur_extra), session_id, tag, tag))
        db.commit()
        logger.info(f"[PID_BRIDGE] Updated Describe SQLite nodes with accessories for session {session_id}")
    except Exception as e:
        logger.warning(f"[PID_BRIDGE] SQLite update skipped or failed: {e}")

    return {
        "success": True,
        "session_id": session_id,
        "instruments": instruments,
        "accessories": accessories,
        "summary": summary,
        "nodes_updated": nodes_updated,
        "pid_graph": graph,
    }
