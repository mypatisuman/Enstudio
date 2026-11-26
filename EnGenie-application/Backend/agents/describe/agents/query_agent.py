"""Query Agent — read-only, retrieval-augmented Q&A about the built P&ID.

Owns no write tools at all: it can retrieve, search, inspect, trace and
explain, never change. Answers are grounded in the drawing's knowledge cards
(domain/pid_rag) and the live graph, cite tags as [TAG], and are checked
against the drawing before they reach the engineer (describe_workflow).
Prompt: agents/describe/prompts/describe_query.md
"""
from agents.describe.services import repository as R
from agents.describe.services.grid_service import get_grid_summary
from agents.describe.base import build_tool_agent
from agents.describe.prompts.catalog import DESCRIBE_QUERY_V1
from domain.pid_rag import retriever as RAG

NAME = "query_agent"

TOOLS = {
    "retrieve_pid_context": {"fn": RAG.retrieve_pid_context, "writes": False, "max_chars": 9500},
    "trace_path": {"fn": RAG.trace_path, "writes": False},
    "count_elements": {"fn": RAG.count_elements, "writes": False},
    "search_graph": {"fn": R.search_graph, "writes": False},
    "get_node": {"fn": R.get_node, "writes": False},
    "get_connections": {"fn": R.get_connections, "writes": False},
    "get_grid": {"fn": lambda pid: get_grid_summary(pid), "writes": False,
                 "doc": "Row/column tile layout of the drawing."},
    "get_loops": {"fn": R.get_loops, "writes": False},
}

_factory = build_tool_agent(NAME, DESCRIBE_QUERY_V1, TOOLS, max_steps=6)


def build_query_agent(checkpointer=None):
    return _factory(checkpointer=checkpointer)
