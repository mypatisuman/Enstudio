"""Describe workflow — description-based P&ID creation and updating,
built as DEDICATED agents.

A supervisor routes each engineer message to one of five specialists
(query, authoring, update, deletion, validation), each owning its own
prompt file and tool subset over the shared repository data layer. Only
the Deletion agent can remove elements, and only behind a checkpointed
confirmation interrupt.

Entry points:
    from agents.describe.workflows.describe_workflow import run_describe_turn, resolve_describe_turn
"""
