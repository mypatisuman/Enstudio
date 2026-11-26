"""Agent-based application layer (LangGraph).

Structure (reference-aligned): one package per workflow, each with
agents/ (node logic), workflows/ (graph wiring), prompts/ (co-located
.md files + catalog.py constants), state.py, plus shared infra at the
package root (toolkit, streaming, checkpoints).

Entry points:
    from agents.extraction.workflows.extraction_workflow import run_extraction_agentic
    from agents.describe.workflows.describe_workflow import run_describe_turn
"""
