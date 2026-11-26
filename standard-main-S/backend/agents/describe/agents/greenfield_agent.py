"""Greenfield Agent — designs and synthesizes clean-sheet P&ID architectures,
battery limits (INLET_FEED, OUTLET_HEADER), equipment trains, 100-series loop numbering,
and full 4-way instrument-to-accessory connection topology.

Owns inspection tools and graph authoring tools.
Prompt: agents/describe/prompts/describe_greenfield.md
"""
from agents.describe.services import repository as R
from agents.describe.services.grid_service import get_grid_summary
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_GREENFIELD_V1

NAME = "greenfield_agent"

TOOLS = {
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_node": {"fn": R.get_node, "writes": False},
    "get_connections": {"fn": R.get_connections, "writes": False},
    "get_loops": {"fn": R.get_loops, "writes": False},
    "get_grid": {"fn": lambda pid: get_grid_summary(pid), "writes": False, "doc": "Row/column tile layout of the drawing."},
    "list_hierarchy": {"fn": R.list_hierarchy, "writes": False},
    "next_tag": {"fn": R.next_tag, "writes": False},
    "add_instrument_package": {"fn": R.add_instrument_package, "writes": True},
    "add_nodes": {"fn": R.add_nodes, "writes": True},
    "add_edges": {"fn": R.add_edges, "writes": True},
    "add_junction": {"fn": R.add_junction, "writes": True},
    "insert_between": {"fn": R.insert_between, "writes": True},
    "create_subsystem": {"fn": R.create_subsystem, "writes": True},
    "assign_to_subsystem": {"fn": R.assign_to_subsystem, "writes": True},
}

_factory = build_tool_agent(NAME, DESCRIBE_GREENFIELD_V1, TOOLS, max_steps=20)


def build_greenfield_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
