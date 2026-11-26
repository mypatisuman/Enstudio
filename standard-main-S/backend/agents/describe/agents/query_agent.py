"""Query Agent — read-only Q&A about the diagram.

Owns no write tools at all: it can search, inspect, and explain, never
change. Prompt: agents/prompts/describe_query.md
"""
from agents.describe.services import repository as R
from agents.describe.services.grid_service import get_grid_summary
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_QUERY_V1

NAME = "query_agent"

TOOLS = {
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_node": {"fn": R.get_node, "writes": False},
    "get_connections": {"fn": R.get_connections, "writes": False},
    "get_grid": {"fn": lambda pid: get_grid_summary(pid), "writes": False},
    "get_loops": {"fn": R.get_loops, "writes": False},
}

_factory = build_tool_agent(NAME, DESCRIBE_QUERY_V1, TOOLS)


def build_query_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
