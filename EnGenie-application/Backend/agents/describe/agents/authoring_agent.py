"""Authoring Agent — creates new graph elements from descriptions.

Owns creation tools plus search (to check for duplicates before adding).
It cannot update, delete, or rename anything — those belong to the
Update and Deletion agents. Prompt: agents/prompts/describe_authoring.md
"""
from agents.describe.services import repository as R
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_AUTHORING_V1

NAME = "authoring_agent"

TOOLS = {
    "search_graph": {"fn": R.search_graph, "writes": False},
    "list_hierarchy": {"fn": R.list_hierarchy, "writes": False},
    "next_tag": {"fn": R.next_tag, "writes": False},
    "add_instrument_package": {"fn": R.add_instrument_package, "writes": True},
    "add_nodes": {"fn": R.add_nodes, "writes": True},
    "add_edges": {"fn": R.add_edges, "writes": True},
    "add_junction": {"fn": R.add_junction, "writes": True},
    "insert_between": {"fn": R.insert_between, "writes": True},
}

_factory = build_tool_agent(NAME, DESCRIBE_AUTHORING_V1, TOOLS, max_steps=12)


def build_authoring_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
