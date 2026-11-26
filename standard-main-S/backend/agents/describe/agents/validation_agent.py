"""Validation Agent — data-quality reporting on the diagram.

Read-only: it scores and explains issues, and directs the engineer to
the right agent for fixes. Prompt: agents/prompts/describe_validation.md
"""
from agents.describe.services import repository as R
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_VALIDATION_V1

NAME = "validation_agent"

TOOLS = {
    "validate_drawing": {"fn": R.validate_drawing, "writes": False},
    "search_graph": {"fn": R.search_graph, "writes": False},
    "check_loop_completeness": {"fn": R.check_loop_completeness, "writes": False},
    "list_proposals": {"fn": R.list_proposals, "writes": False},
}

_factory = build_tool_agent(NAME, DESCRIBE_VALIDATION_V1, TOOLS)


def build_validation_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
