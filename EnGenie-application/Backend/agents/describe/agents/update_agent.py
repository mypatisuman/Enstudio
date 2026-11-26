"""Update Agent — renames, re-classifies, and relocates existing nodes.

Owns update_node plus the read tools needed to verify what it is
changing. It cannot create or delete. Prompt:
agents/prompts/describe_update.md
"""
from agents.describe.services import repository as R
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_UPDATE_V1

NAME = "update_agent"

TOOLS = {
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_node": {"fn": R.get_node, "writes": False},
    "list_hierarchy": {"fn": R.list_hierarchy, "writes": False},
    "update_node": {"fn": R.update_node, "writes": True},
    "update_edge": {"fn": R.update_edge, "writes": True},
    "reroute_edge": {"fn": R.reroute_edge, "writes": True},
    "assign_to_subsystem": {"fn": R.assign_to_subsystem, "writes": True},
    "list_proposals": {"fn": R.list_proposals, "writes": False},
    "review_proposal": {"fn": R.review_proposal, "writes": True},
}

_factory = build_tool_agent(NAME, DESCRIBE_UPDATE_V1, TOOLS, max_steps=10)


def build_update_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
