"""
Brownfield P&ID Agent - plant revamp, retrofit and tie-in integration as a
bounded tool loop.

Two entry points:
  generate_brownfield_pid  a new retrofit anchored on tie-in nozzles
                           (TP-01 / TP-02), binding the plant's installed
                           devices from the user's Assets Table;
  update_existing_pid      applies a modification to a P&ID that already
                           exists, preserving every node, tag and connection.

Both run the same specialist against a live PIDGraphStore: the model inspects
the drawing, checks what is already there, then builds with
add_instrument_package / add_control_tail / break_line. Destructive tools
(delete_nodes, delete_edges) are registered with requires_confirmation: during
a modification they are queued as the drawing's pending_action and applied
only when the engineer confirms through POST /api/pid/confirm.

When the model is unreachable or its drawing fails validation, pid_fallback
builds the same topology deterministically.

Asset binding: the user's `assets` and `asset_configurations` collections are
the only source of nameplate data. A retrofit binds a package role to an
installed device only when the device's ISA prefix fits that role (see
asset_specs.match_for_role). Everything else is "unspecified" -- never
invented.

Prompts: domain/solution/prompts/brownfield_pid.md, brownfield_update_pid.md
"""

from __future__ import annotations

import json
import logging
from typing import Any

from domain.solution.agents import pid_fallback
from domain.solution.agents.pid_tool_agent import (
    accept, build_tool_agent, components_json, confirm_delete_action,
    designed_json, fill_prompt, graph_result, solution_llm_complete)
from domain.solution.agents.shared import (
    BROWNFIELD_PID_PROMPT,
    BROWNFIELD_UPDATE_PID_PROMPT,
)
from domain.solution.services import asset_specs as SPECS
from domain.solution.services.isa_classifier import classify_node_kind
from domain.solution.services.pid_graph_store import PIDGraphStore

logger = logging.getLogger(__name__)

NAME = "brownfield_pid_agent"

# Kept for callers and tests that import the old alias.
_classify_kind_from_tag = classify_node_kind

TOOLS: dict[str, dict] = {
    # vision analysis & rebuild
    "analyze_uploaded_pid": {"method": "analyze_uploaded_pid"},
    "rebuild_digital_pid": {"method": "rebuild_digital_pid", "writes": True},
    # accuracy & prompt refinement
    "evaluate_pid_accuracy": {"method": "evaluate_pid_accuracy"},
    "get_accuracy_history": {"method": "get_accuracy_history"},
    "analyze_accuracy_metrics": {"method": "analyze_accuracy_metrics"},
    "refine_pid_drawing": {"method": "refine_pid_drawing", "writes": True},
    # inspect
    "search_graph": {"method": "search_graph"},
    "get_node": {"method": "get_node"},
    "get_connections": {"method": "get_connections"},
    "get_loops": {"method": "get_loops"},
    "digitisation_status": {"method": "digitisation_status"},
    "list_hierarchy": {"method": "list_hierarchy"},
    "get_subsystem": {"method": "get_subsystem"},
    "get_subsystem_contents": {"method": "get_subsystem_contents"},
    "search_assets": {"method": "search_assets"},
    "validate_drawing": {"method": "validate_drawing"},
    "next_tag": {"method": "next_tag"},
    # build
    "add_instrument_package": {"method": "add_instrument_package", "writes": True},
    "add_control_tail": {"method": "add_control_tail", "writes": True},
    "add_nodes": {"method": "add_nodes", "writes": True},
    "add_edges": {"method": "add_edges", "writes": True},
    "add_junction": {"method": "add_junction", "writes": True},
    "insert_between": {"method": "insert_between", "writes": True},
    "break_line": {"method": "break_line", "writes": True},
    # modify the existing plant
    "reroute_edge": {"method": "reroute_edge", "writes": True},
    "update_node": {"method": "update_node", "writes": True},
    "update_edge": {"method": "update_edge", "writes": True},
    # plant hierarchy
    "create_system": {"method": "create_system", "writes": True},
    "create_subsystem": {"method": "create_subsystem", "writes": True},
    "assign_to_subsystem": {"method": "assign_to_subsystem", "writes": True},
    "sync_hierarchy": {"method": "sync_hierarchy", "writes": True},
    # removal: refused until the engineer can confirm
    "delete_nodes": {"method": "delete_nodes", "writes": True,
                     "requires_confirmation": True},
    "delete_edges": {"method": "delete_edges", "writes": True,
                     "requires_confirmation": True},
}

MAX_STEPS = 20

_run = build_tool_agent(NAME, TOOLS, max_steps=MAX_STEPS)

_DEFAULT_AREAS = ["Tie-In Supply Zone", "Retrofit Instrumentation & Control Station",
                  "Tie-In Return Zone"]


def _llm_complete(prompt: str, *, user_id: int | None = None) -> str:
    """One model call. Module-level so tests can replace it."""
    return solution_llm_complete(prompt, user_id=user_id, agent_type=NAME)


# ── the plant's Assets Table ────────────────────────────────────────────────

def _clean(value: Any) -> str:
    return str(value or "").strip()


def _load_detailed_asset_resources(user_id: int | None) -> list[dict[str, Any]]:
    """Load the user's installed devices from the `assets` and
    `asset_configurations` collections: tags, models, serials, calibrated
    ranges (LRV/URV) and connected DCS panels.

    Only recorded values are returned. The previous loader filled every gap
    with a default -- "Cabinet PNL-100" on every `assets` row regardless of its
    data, "4-20mA HART", "0 - 100%", "SN-PENDING", "Unit 100", and a synthetic
    TAG-n when the tag was missing -- and because these records are treated as
    real inventory, those defaults were presented as plant fact. A missing
    field is now simply absent.
    """
    if not user_id:
        return []
    try:
        from common.ai.rag.assets_rag import build_user_id_filter
        from common.infra.mongodb_config import Collections, get_mongodb_connection

        conn = get_mongodb_connection()
        if not conn:
            return []

        resources: list[dict[str, Any]] = []

        assets_col = conn["collections"].get(Collections.ASSETS)
        if assets_col is not None:
            for doc in assets_col.find(build_user_id_filter(user_id)):
                for row in doc.get("data", []):
                    record = {
                        "tag_number": _clean(row.get("tag_number") or row.get("tag")),
                        "asset_name": _clean(row.get("asset_name") or row.get("name")),
                        "asset_type": _clean(row.get("asset_type") or row.get("type")
                                             or row.get("category")),
                        "manufacturer": _clean(row.get("manufacturer") or row.get("vendor")),
                        "model": _clean(row.get("model")),
                        "serial_number": _clean(row.get("serial_number") or row.get("serial")),
                        "location": _clean(row.get("location") or row.get("site")),
                        "unit": _clean(row.get("unit")),
                        "area": _clean(row.get("area")),
                        "connected_system": _clean(row.get("connected_system")),
                        "protocol": _clean(row.get("protocol")),
                        "calibrated_range": _clean(row.get("calibrated_range")),
                    }
                    if record["tag_number"] or record["asset_name"] or record["asset_type"]:
                        resources.append({k: v for k, v in record.items() if v})

        cfg_col = conn["collections"].get(Collections.ASSET_CONFIGURATIONS)
        if cfg_col is not None:
            for doc in cfg_col.find(build_user_id_filter(user_id)):
                asset = doc.get("asset", {}) or {}
                loc = doc.get("location", {}) or {}
                conn_sys = doc.get("connected_system", {}) or {}
                pv_map = (doc.get("instrument_config", {}) or {}).get("pv_mapping", {}) or {}

                urv, lrv = _clean(pv_map.get("urv")), _clean(pv_map.get("lrv"))
                units = _clean(pv_map.get("pv_units"))
                record = {
                    "tag_number": _clean(asset.get("tag_number")),
                    "asset_name": _clean(asset.get("asset_name")),
                    "asset_type": _clean(asset.get("asset_type")),
                    "manufacturer": _clean(asset.get("manufacturer")),
                    "model": _clean(asset.get("model")),
                    "serial_number": _clean(asset.get("serial_number")),
                    "location": " ".join(x for x in (_clean(loc.get("plant")),
                                                     _clean(loc.get("site"))) if x),
                    "unit": _clean(loc.get("unit")),
                    "area": _clean(loc.get("area")),
                    "connected_system": _clean(conn_sys.get("name")),
                    "protocol": _clean(conn_sys.get("protocol")),
                    # A range needs both ends; a lone URV is not a range.
                    "calibrated_range": ("%s - %s %s" % (lrv, urv, units)).strip()
                                        if urv and lrv else "",
                    "urv": urv, "lrv": lrv, "pv_units": units,
                }
                if record["tag_number"] or record["asset_name"]:
                    resources.append({k: v for k, v in record.items() if v})

        logger.info("[%s] Loaded %d asset records for user %s",
                    NAME, len(resources), user_id)
        return resources
    except Exception as e:
        logger.warning("[%s] Could not load asset resources: %s", NAME, e)
        return []


def _format_asset_resources_text(resources: list[dict[str, Any]]) -> str:
    """The Assets Table as a compact table for the prompt. Fields a record
    does not have are left out rather than filled."""
    if not resources:
        return ("(No Assets Table records for this user. Mint new tags with "
                "add_instrument_package or next_tag, and leave specifications "
                "unspecified.)")
    lines = []
    for i, r in enumerate(resources[:40]):
        fields = [("TAG", "[%s]" % (r.get("tag_number") or "untagged"))]
        for label, key in (("Name", "asset_name"), ("Type", "asset_type"),
                           ("Mfr", "manufacturer"), ("Model", "model"),
                           ("Serial", "serial_number"), ("Range", "calibrated_range"),
                           ("Panel", "connected_system")):
            if r.get(key):
                fields.append((label, r[key]))
        loc = " ".join(x for x in (r.get("unit"), r.get("area")) if x)
        if loc:
            fields.append(("Location", loc))
        lines.append("  %d. %s" % (i + 1, " | ".join("%s: %s" % f for f in fields)))
    header = "Total Assets Table records: %d" % len(resources)
    if len(resources) > 40:
        header += " (showing first 40; use search_assets for the rest)"
    return header + "\n" + "\n".join(lines)


# ── deterministic builds ────────────────────────────────────────────────────

def _build_fallback_brownfield_graph(
    requirements: str,
    designed_solution: dict[str, Any] | None,
    instruments: list[dict[str, Any]],
    accessories: list[dict[str, Any]],
    sub_systems: list[dict[str, Any]] | None = None,
    asset_resources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic retrofit between tie-in nozzles TP-01 and TP-02, binding
    installed devices from the Assets Table where their tags fit."""
    store = PIDGraphStore(asset_index=SPECS.build_index(asset_resources),
                          project_type="brownfield")
    areas = pid_fallback.area_names(sub_systems, _DEFAULT_AREAS)
    pid_fallback.build_graph(
        store,
        entry={"tag": "TP-01", "kind": "tie_in",
               "description": "Tie-in point 01 on the existing supply header"},
        exit_={"tag": "TP-02", "kind": "tie_in",
               "description": "Tie-in point 02 on the existing return header"},
        areas=areas,
        designed_solution=designed_solution,
        instruments=instruments,
        accessories=accessories,
        check_valve_tag="NRV-201",
        line_label='4"-PG-2001-A1B',
        bind_assets=True,
    )
    counts = SPECS.summarize(store.nodes)
    summary = ("BROWNFIELD: retrofit between tie-ins TP-01 and TP-02 with the "
               "four-way topology; %d node(s) bound to Assets Table records. %s"
               % (counts.get(SPECS.INVENTORY, 0), store.graph_summary()))
    return graph_result(store, reply=summary, path="fallback")


def _mutate_fallback_brownfield_graph(
    existing_graph: dict[str, Any],
    modification_prompt: str,
    instruments: list[dict[str, Any]],
    accessories: list[dict[str, Any]],
    sub_systems: list[dict[str, Any]] | None = None,
    *,
    asset_resources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic in-place modification: preserves every existing node and
    tag, and adds only what the drawing does not already have."""
    store = PIDGraphStore(existing_graph,
                          asset_index=SPECS.build_index(asset_resources),
                          project_type="brownfield")
    before = len(store.nodes)
    area = pid_fallback.area_names(sub_systems, [""])[0]
    notes = pid_fallback.mutate_graph(
        store, instruments=instruments, accessories=accessories, area=area,
        modification_prompt=modification_prompt)
    added = [store._tag_of(n) for n in store.nodes[before:]]
    summary = ("Modified the P&ID: added %d component(s)%s. %s" % (
        len(added), (": " + ", ".join(added)) if added else "",
        ("Left alone: " + "; ".join(notes) + ".") if notes else ""))
    return graph_result(store, reply=summary.strip(), path="fallback", notes=notes)


# ── the agent ───────────────────────────────────────────────────────────────

class BrownfieldPIDAgent:
    """Retrofit and in-place modification with Assets Table binding."""

    @staticmethod
    def generate_brownfield_pid(
        requirements: str,
        designed_solution: dict[str, Any] | None,
        instruments: list[dict[str, Any]],
        accessories: list[dict[str, Any]],
        sub_systems: list[dict[str, Any]] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        resources = _load_detailed_asset_resources(user_id)
        store = PIDGraphStore(asset_index=SPECS.build_index(resources),
                              project_type="brownfield")
        areas = pid_fallback.area_names(sub_systems, _DEFAULT_AREAS)
        system_prompt = fill_prompt(BROWNFIELD_PID_PROMPT, {
            "requirements": requirements or "",
            "asset_resources": _format_asset_resources_text(resources),
            "sub_systems": json.dumps(areas),
            "designed_solution": designed_json(designed_solution),
            "components": components_json(instruments, accessories),
            "graph_summary": store.graph_summary(),
        })

        try:
            result = _run(store, system_prompt,
                          requirements or "Design the retrofit.",
                          lambda p: _llm_complete(p, user_id=user_id))
        except Exception as exc:
            logger.warning("[%s] tool loop unavailable (%s); using the "
                           "deterministic build.", NAME, exc)
        else:
            ok, why = accept(result)
            if ok:
                logger.info("[%s] tool loop built %d nodes in %d steps",
                            NAME, len(store.nodes), result.steps)
                return graph_result(store, reply=result.reply, path="tool_loop")
            logger.warning("[%s] tool loop result rejected (%s); using the "
                           "deterministic build.", NAME, why)

        return _build_fallback_brownfield_graph(
            requirements, designed_solution, instruments, accessories,
            sub_systems, asset_resources=resources)

    @classmethod
    def update_existing_pid(
        cls,
        existing_graph: dict[str, Any],
        modification_prompt: str,
        instruments: list[dict[str, Any]] | None = None,
        accessories: list[dict[str, Any]] | None = None,
        sub_systems: list[dict[str, Any]] | None = None,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Apply a modification to an existing P&ID in place. Every existing
        node, tag and connection is preserved unless the engineer names it."""
        resources = _load_detailed_asset_resources(user_id)
        store = PIDGraphStore(existing_graph,
                              asset_index=SPECS.build_index(resources),
                              project_type="brownfield")
        preexisting = {store._tag_of(n) for n in store.nodes}
        system_prompt = fill_prompt(BROWNFIELD_UPDATE_PID_PROMPT, {
            "modification_prompt": modification_prompt or "",
            "graph_summary": store.graph_summary(),
            "asset_resources": _format_asset_resources_text(resources),
            "sub_systems": json.dumps(pid_fallback.area_names(sub_systems, [])),
            "components": components_json(instruments, accessories),
        })

        # Deletions the model asks for are queued, not executed: they become
        # the drawing's pending_action and run only when the engineer confirms.
        deferred: list[dict] = []
        try:
            result = _run(store, system_prompt, modification_prompt or "",
                          lambda p: _llm_complete(p, user_id=user_id),
                          deferred=deferred)
        except Exception as exc:
            logger.warning("[%s] tool loop unavailable (%s); using the "
                           "deterministic modification.", NAME, exc)
        else:
            ok, why = accept(result)
            # A modification must never lose part of the plant. Deletions are
            # queued rather than executed, so this only trips on a bug -- but
            # it is the invariant the whole path exists to keep.
            lost = preexisting - {store._tag_of(n) for n in store.nodes}
            if ok and not lost:
                return graph_result(store, reply=result.reply, path="tool_loop",
                                    pending_action=confirm_delete_action(deferred))
            logger.warning("[%s] tool loop result rejected (%s); using the "
                           "deterministic modification.", NAME,
                           why or "existing tags lost: %s" % sorted(lost))

        return _mutate_fallback_brownfield_graph(
            existing_graph, modification_prompt, instruments or [],
            accessories or [], sub_systems, asset_resources=resources)
