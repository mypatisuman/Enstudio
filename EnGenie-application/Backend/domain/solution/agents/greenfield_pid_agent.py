"""
Greenfield P&ID Agent - clean-sheet P&ID synthesis as a bounded tool loop.

Designs battery limits (INLET_FEED, OUTLET_HEADER), the equipment train, and a
complete four-way instrument-to-accessory topology by building it on a live
PIDGraphStore one tool call at a time, instead of asking the model to emit the
whole graph in a single JSON object.

The model decides WHAT to build (which measurements, on which equipment, with
or without control); services.instrument_packages decides HOW each loop is
wired, identically every run. When the model is unreachable or its drawing
fails validation, pid_fallback builds the same topology deterministically.

A clean sheet is new equipment: the user's Assets Table is deliberately NOT
consulted here, so a fresh PT-101 never inherits the nameplate of an installed
PT-101 in some other unit. Specifications are what the engineer or the Bill of
Materials stated, or "unspecified" -- never invented.

Prompt: domain/solution/prompts/greenfield_pid.md
"""

from __future__ import annotations

import json
import logging
from typing import Any

from domain.solution.agents import pid_fallback
from domain.solution.agents.pid_tool_agent import (
    accept, build_tool_agent, components_json, designed_json, fill_prompt,
    graph_result, solution_llm_complete)
from domain.solution.agents.shared import GREENFIELD_PID_PROMPT
from domain.solution.services.isa_classifier import classify_node_kind
from domain.solution.services.pid_graph_store import PIDGraphStore

logger = logging.getLogger(__name__)

NAME = "greenfield_pid_agent"

# Kept for callers and tests that import the old alias.
_classify_kind_from_tag = classify_node_kind

TOOLS: dict[str, dict] = {
    # inspect
    "search_graph": {"method": "search_graph"},
    "get_node": {"method": "get_node"},
    "get_connections": {"method": "get_connections"},
    "get_loops": {"method": "get_loops"},
    "list_hierarchy": {"method": "list_hierarchy"},
    "validate_drawing": {"method": "validate_drawing"},
    "next_tag": {"method": "next_tag"},
    # author
    "add_instrument_package": {"method": "add_instrument_package", "writes": True},
    "add_nodes": {"method": "add_nodes", "writes": True},
    "add_edges": {"method": "add_edges", "writes": True},
    "add_junction": {"method": "add_junction", "writes": True},
    "insert_between": {"method": "insert_between", "writes": True},
    "create_subsystem": {"method": "create_subsystem", "writes": True},
    "assign_to_subsystem": {"method": "assign_to_subsystem", "writes": True},
}

#: A clean sheet is a handful of calls: the process run, its connections, one
#: package per measurement, a relief valve or two, and the reply.
MAX_STEPS = 18

_run = build_tool_agent(NAME, TOOLS, max_steps=MAX_STEPS)

_DEFAULT_AREAS = ["Feed Preparation", "Primary Process Unit",
                  "Product Discharge & Safety"]


def _llm_complete(prompt: str, *, user_id: int | None = None) -> str:
    """One model call. Module-level so tests can replace it."""
    return solution_llm_complete(prompt, user_id=user_id, agent_type=NAME)


def _build_fallback_greenfield_graph(
    requirements: str,
    designed_solution: dict[str, Any] | None,
    instruments: list[dict[str, Any]],
    accessories: list[dict[str, Any]],
    sub_systems: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic clean-sheet build: the same package templates the tool
    loop uses, between battery limits."""
    store = PIDGraphStore(project_type="greenfield")
    areas = pid_fallback.area_names(sub_systems, _DEFAULT_AREAS)
    pid_fallback.build_graph(
        store,
        entry={"tag": "INLET_FEED", "kind": "off_page_connector",
               "description": "Battery limit feed supply"},
        exit_={"tag": "OUTLET_HEADER", "kind": "off_page_connector",
               "description": "Process discharge header to downstream unit"},
        areas=areas,
        designed_solution=designed_solution,
        instruments=instruments,
        accessories=accessories,
        isolation_tag="HV-101",
        check_valve_tag="NRV-101",
        line_label='3"-PROC-1001',
    )
    summary = ("GREENFIELD: clean-sheet P&ID across %d sub-system(s) with the "
               "four-way instrument and accessory topology. %s"
               % (len(areas), store.graph_summary()))
    return graph_result(store, reply=summary, path="fallback")


class GreenfieldPIDAgent:
    """Clean-sheet P&ID synthesis with four-way connectivity."""

    @staticmethod
    def generate_greenfield_pid(
        requirements: str,
        designed_solution: dict[str, Any] | None,
        instruments: list[dict[str, Any]],
        accessories: list[dict[str, Any]],
        sub_systems: list[dict[str, Any]] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        store = PIDGraphStore(project_type="greenfield")
        areas = pid_fallback.area_names(sub_systems, _DEFAULT_AREAS)
        system_prompt = fill_prompt(GREENFIELD_PID_PROMPT, {
            "requirements": requirements or "",
            "sub_systems": json.dumps(areas),
            "designed_solution": designed_json(designed_solution),
            "components": components_json(instruments, accessories),
            "graph_summary": store.graph_summary(),
        })

        try:
            result = _run(store, system_prompt,
                          requirements or "Design the clean-sheet P&ID.",
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

        return _build_fallback_greenfield_graph(
            requirements, designed_solution, instruments, accessories, sub_systems)
