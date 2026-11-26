"""
Solution Build Agent — Standalone parallel engineering-solution designer.

Runs IN PARALLEL with the BOM pipeline tail (expansion → infer →
format_results), fanned out from episodic_recall ONLY after the
comprehensiveness gate confirmed the requirements are complete. It performs its OWN deep analysis of
the user's requirement plus the project's current instruments/accessories and
produces an optimized engineering *solution* (project objective, per-component
purpose, design narrative, optimizations) — NOT a Bill of Materials.

Output is written to a dedicated state key ``designed_solution`` and surfaced to
the UI via SolutionResponse alongside the right-side BOM.

Concurrency contract: this node writes ONLY ``state["designed_solution"]``. It
must never write ``agent_path`` / ``deep_analysis`` / ``workflow_data`` /
``instruments`` / ``accessories`` — those are written by the BOM-pipeline nodes
running in the same LangGraph superstep, and a concurrent write to the same channel
(which has no reducer) would raise InvalidUpdateError.

Failure isolation: a failure here must never break the BOM response. The
``on_exhausted`` degrade hook returns the (partial) state with
``designed_solution=None`` instead of re-raising, and the node never sets
``state["error"]``.
"""

import json
import logging
import os
import sys

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from domain.orchestrator.state import AgenticSystemState
from domain.solution.schemas import DesignedSolution
from domain.solution.agents.shared import (
    SOLUTION_BUILD_PROMPT,
    llm_pro,
    _parse_llm_json,
)
from common.ai.llm import SOLUTION_LLM_PROVIDER, with_json_mode
from domain.solution.memory import build_looped_conversation_context
from common.helpers.node_retry import retryable_node
from common.helpers.progress_tracker import progress_tracker

logger = logging.getLogger(__name__)

def _build_conversation_context(state: AgenticSystemState, session_id: str) -> str:
    """Build a conversation-context blob using chronological multi-turn loop."""
    return build_looped_conversation_context(state, session_id=session_id)


def _serialize_components(state: AgenticSystemState) -> str:
    """Build a lean view of the project's current instruments/accessories for the prompt."""
    def _trim(item: dict, name_key: str) -> dict:
        return {
            "name": item.get("product_name") or item.get(name_key) or item.get("category", ""),
            "category": item.get("category", ""),
            "quantity": item.get("quantity", 1),
            "specifications": item.get("specifications", {}),
        }

    instruments = [_trim(i, "category") for i in state.get("instruments", []) or []]
    accessories = [_trim(a, "accessory_name") for a in state.get("accessories", []) or []]

    if not instruments and not accessories:
        return "None provided yet — derive the components implied by the requirement."

    return json.dumps({"instruments": instruments, "accessories": accessories}, indent=2, default=str)


def _on_design_failed(state: AgenticSystemState, exc: BaseException) -> dict:
    """Graceful-degradation hook: never raise, never poison the BOM response.

    Returns a PARTIAL update writing only the ``designed_solution`` and ``pid_graph`` channels
    (None). It must not return the full state or any other channel — in the
    parallel superstep that would collide with the BOM pipeline's writes.
    """
    logging.error(f"[SOLUTION_BUILD] Design generation failed — returning no designed_solution: {exc}")
    return {"designed_solution": None, "pid_graph": None}


@retryable_node(
    max_attempts=2,
    label="solution_build",
    on_exhausted=_on_design_failed,
)
def solution_build_node(state: AgenticSystemState) -> dict:
    """
    Solution Build Agent — designs an optimized engineering solution in parallel
    with the BOM pipeline and synthesizes the ISA-5.1 P&ID topological graph.

    Returns a PARTIAL state update containing ONLY ``designed_solution`` and ``pid_graph`` so it
    never collides with the BOM pipeline's channel writes in the same
    LangGraph superstep. Transient LLM errors are retried by ``@retryable_node``; any
    terminal failure degrades gracefully via ``_on_design_failed`` (returns
    ``{"designed_solution": None, "pid_graph": None}``) and never aborts the graph.
    """
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "solution_design",
            "message": "Designing Engineering Solution & P&ID",
            "progress": 20,
        })

    logging.info("[SOLUTION_BUILD] Standalone parallel solution-build & P&ID agent")

    user_input = state.get("user_input", "")
    session_id = state.get("session_id", "default")
    user_id = state.get("user_id")

    conversation_context = _build_conversation_context(state, session_id)
    current_components = _serialize_components(state)

    prompt = ChatPromptTemplate.from_template(SOLUTION_BUILD_PROMPT)
    chain = prompt | with_json_mode(llm_pro, SOLUTION_LLM_PROVIDER) | StrOutputParser()

    raw_response = chain.invoke(
        {
            "requirements": user_input,
            "conversation_context": conversation_context,
            "current_components": current_components,
        },
        config={"metadata": {"user_id": user_id, "agent_type": "solution"}},
    )

    parsed = _parse_llm_json(raw_response)

    # Normalize through the schema so the stored value always has the expected
    # shape and defaults (unknown keys dropped, missing keys defaulted).
    designed = DesignedSolution.model_validate(parsed).model_dump()

    # Synthesize ISA-5.1 P&ID topological graph, sub-system areas, 2D layout, and SVG preview
    try:
        from domain.solution.services.pid_builder_service import build_pid_from_solution
        sub_systems = state.get("deep_analysis", {}).get("sub_systems") or state.get("workflow_data", {}).get("sub_systems", [])
        active_pid_graph = state.get("active_pid_graph") or state.get("pid_graph") or (state.get("designed_solution") or {}).get("pid_graph")
        pid_project_type = state.get("pid_project_type")
        pid_graph = build_pid_from_solution(
            requirements=user_input,
            designed_solution=designed,
            instruments=state.get("instruments", []) or [],
            accessories=state.get("accessories", []) or [],
            sub_systems=sub_systems,
            project_type=pid_project_type,
            active_pid_graph=active_pid_graph,
            user_id=user_id,
        )
        designed["pid_graph"] = pid_graph
    except Exception as pid_err:
        logger.warning(f"[SOLUTION_BUILD] P&ID synthesis encountered an error: {pid_err}")
        pid_graph = None

    logging.info(
        f"[SOLUTION_BUILD] ✓ Designed solution: objective set={bool(designed.get('project_objective'))}, "
        f"{len(designed.get('component_roles', []))} component roles, "
        f"{len(designed.get('optimizations', []))} optimizations, "
        f"PID graph generated={bool(pid_graph)}"
    )

    # Return a PARTIAL update — only the channels this node owns.
    return {"designed_solution": designed, "pid_graph": pid_graph}
