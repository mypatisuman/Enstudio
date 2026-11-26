"""Brownfield Agent — designs and executes plant revamps, retrofits, tie-in nozzle
integration (TP-01, TP-02), existing tag preservation, and 4-way retrofit connection topology.

Owns inspection tools and graph authoring tools.
Prompt: agents/describe/prompts/describe_brownfield.md
"""
from agents.describe.services import repository as R
from agents.describe.services.grid_service import get_grid_summary
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_BROWNFIELD_V1

NAME = "brownfield_agent"

TOOLS = {
    # vision analysis & rebuild
    "digitise_uploaded_pid": {"fn": R.digitise_uploaded_pid, "writes": True, "doc": "Read the uploaded drawing with the vision model, rebuild it as the digital P&ID and score it, in one call. Use this to digitise."},
    "analyze_uploaded_pid": {"fn": R.analyze_uploaded_pid, "writes": False, "doc": "Read the uploaded drawing with the vision model WITHOUT writing; returns a summary (the reading is cached for rebuild_digital_pid)."},
    "rebuild_digital_pid": {"fn": R.rebuild_digital_pid, "writes": True, "doc": "Persist the (cached) drawing reading as the interactive digital P&ID graph in SQLite and MongoDB."},
    # accuracy & prompt refinement
    "evaluate_pid_accuracy": {"fn": R.evaluate_pid_accuracy, "writes": False, "doc": "Evaluate engineering accuracy score (0-100), ISA-5.1 compliance, loop completeness, orphan rates, and prompt refinement guidance."},
    "get_accuracy_history": {"fn": R.get_accuracy_history, "writes": False, "doc": "Retrieve stored historical accuracy evaluations from local files."},
    "analyze_accuracy_history": {"fn": R.analyze_accuracy_history, "writes": False, "doc": "Read and analyze all stored local accuracy metrics to detect recurring gaps and recommend improvements."},
    "refine_pid_drawing": {"fn": R.refine_pid_drawing, "writes": True, "doc": "Re-read the drawing and ADD nodes/connections the first read missed (never removes or renames)."},
    # inspect
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_node": {"fn": R.get_node, "writes": False},
    "get_connections": {"fn": R.get_connections, "writes": False},
    "get_loops": {"fn": R.get_loops, "writes": False},
    "get_grid": {"fn": lambda pid: get_grid_summary(pid), "writes": False, "doc": "Row/column tile layout of the drawing."},
    "digitisation_status": {"fn": R.digitisation_status, "writes": False},
    "list_hierarchy": {"fn": R.list_hierarchy, "writes": False},
    "get_subsystem": {"fn": R.get_subsystem, "writes": False},
    "get_subsystem_contents": {"fn": R.get_subsystem_contents, "writes": False},
    "next_tag": {"fn": R.next_tag, "writes": False},
    # build
    "add_instrument_package": {"fn": R.add_instrument_package, "writes": True},
    "add_nodes": {"fn": R.add_nodes, "writes": True},
    "add_edges": {"fn": R.add_edges, "writes": True},
    "add_junction": {"fn": R.add_junction, "writes": True},
    "insert_between": {"fn": R.insert_between, "writes": True},
    "break_line": {"fn": R.break_line, "writes": True},
    # modify existing plant
    "reroute_edge": {"fn": R.reroute_edge, "writes": True},
    "update_node": {"fn": R.update_node, "writes": True},
    "update_edge": {"fn": R.update_edge, "writes": True},
    # plant hierarchy
    "create_system": {"fn": R.create_system, "writes": True},
    "create_subsystem": {"fn": R.create_subsystem, "writes": True},
    "assign_to_subsystem": {"fn": R.assign_to_subsystem, "writes": True},
    "sync_hierarchy": {"fn": R.sync_hierarchy, "writes": True},
    # removal: the engineer confirms through the checkpointed interrupt
    "delete_nodes": {"fn": R.delete_nodes, "writes": True, "requires_confirmation": True},
    "delete_edges": {"fn": R.delete_edges, "writes": True, "requires_confirmation": True},
}

_factory = build_tool_agent(NAME, DESCRIBE_BROWNFIELD_V1, TOOLS, max_steps=20)


def build_brownfield_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
