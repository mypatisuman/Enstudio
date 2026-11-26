"""Deletion Agent — the only agent that can remove graph elements.

delete_nodes declares requires_confirmation, so the shared engine pauses
on a checkpointed interrupt before executing; the engineer's confirm or
cancel resumes it. get_connections lets the agent state the blast radius
in its confirmation reason. Prompt: agents/prompts/describe_deletion.md
"""
from agents.describe.services import repository as R
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_DELETION_V1

NAME = "deletion_agent"

TOOLS = {
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_connections": {"fn": R.get_connections, "writes": False},
    "delete_nodes": {"fn": R.delete_nodes, "writes": True,
                     "requires_confirmation": True},
    "delete_edges": {"fn": R.delete_edges, "writes": True,
                     "requires_confirmation": True},
}

_factory = build_tool_agent(NAME, DESCRIBE_DELETION_V1, TOOLS)


def build_deletion_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
