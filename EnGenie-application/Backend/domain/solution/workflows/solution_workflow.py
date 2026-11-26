import logging
import os
from datetime import datetime
from langgraph.graph import END, StateGraph

from domain.orchestrator.state import AgenticSystemState
from domain.solution.agents.solution_agent import (
    project_intent_node,
    modification_node,
    standards_application_node,
    build_final_response_node,
    route_by_intent,
    route_after_modification,
    route_after_holistic,
)
from domain.solution.agents.holistic_agent import holistic_agent_node
from domain.solution.agents.episodic_recall_agent import episodic_recall_node, route_after_episodic_recall
from domain.solution.agents.expansion_agent import intelligent_standards_retrieval_node
from domain.solution.agents.infer_agent import infer_agent_node
from domain.solution.agents.format_results_agent import format_results_node
from domain.solution.agents.solution_build_agent import solution_build_node

logger = logging.getLogger(__name__)


def create_solution_agent() -> StateGraph:
    """
    Create the Solution workflow graph.

    Requirements flow:
        project_intent → holistic_agent → episodic_recall ─┬→ expansion → infer → format_results ─┐
             (gapped/error → final_response)  (offer → final_response) └→ solution_build ─────────────────→ final_response
        solution_build fans out from episodic_recall in PARALLEL with expansion —
        it runs only for confirmed-complete requirements with no saved-project offer.

    Modification flow:
        project_intent → modify_instruments → apply_standards → final_response

    All other intents (clarification, router_needed, reset, contextual_qna):
        project_intent → final_response
    """
    workflow = StateGraph(AgenticSystemState)

    # ── Episodic recall (post-gate saved-project "repeated request" offer) ────
    workflow.add_node("episodic_recall", episodic_recall_node)

    # ── Core intent node ──────────────────────────────────────────────────────
    workflow.add_node("project_intent", project_intent_node)

    # ── Holistic agent (merged holism gate + requirements extraction) ─────────
    workflow.add_node("holistic_agent", holistic_agent_node)

    # ── Requirements path (downstream of the merged agent) ────────────────────
    workflow.add_node("expansion", intelligent_standards_retrieval_node)
    workflow.add_node("infer", infer_agent_node)
    workflow.add_node("format_results", format_results_node)

    # ── Standalone parallel solution-build agent (runs alongside the BOM path) ─
    workflow.add_node("solution_build", solution_build_node)

    # ── Modification path ─────────────────────────────────────────────────────
    workflow.add_node("modify_instruments", modification_node)
    workflow.add_node("apply_standards", standards_application_node)

    # ── Final response ────────────────────────────────────────────────────────
    # defer=True makes this fan-in join wait for ALL incoming branches before
    # running exactly once. Without it, the uneven requirements branches (1-node
    # solution_build vs 4-node BOM chain) would fire final_response twice — once
    # prematurely when solution_build finishes, before the BOM is built.
    workflow.add_node("final_response", build_final_response_node, defer=True)

    # ── Entry point ───────────────────────────────────────────────────────────
    workflow.set_entry_point("project_intent")

    # ── Routing from intent ───────────────────────────────────────────────────
    workflow.add_conditional_edges(
        "project_intent",
        route_by_intent,
        {
            "holistic_agent": "holistic_agent",
            "modify_instruments": "modify_instruments",
            "final_response": "final_response",
        },
    )

    # ── Merged agent: proceed to episodic recall when extraction succeeded, or
    #    short-circuit to final_response (clarification questions / error) ─────
    workflow.add_conditional_edges(
        "holistic_agent",
        route_after_holistic,
        {
            "episodic_recall": "episodic_recall",
            "final_response": "final_response",
        },
    )

    # ── Episodic recall (post-gate): saved-project offer → final_response
    #    (modal resolves it), otherwise fan out to expansion + solution_build
    #    in parallel (design narrative only for CONFIRMED-complete requirements)
    workflow.add_conditional_edges(
        "episodic_recall",
        route_after_episodic_recall,
        {
            "expansion": "expansion",
            "solution_build": "solution_build",
            "final_response": "final_response",
        },
    )

    # ── Requirements path: linear BOM chain ───────────────────────────────────
    workflow.add_edge("expansion", "infer")
    workflow.add_edge("infer", "format_results")
    workflow.add_edge("format_results", "final_response")

    # ── Parallel branch: solution_build joins the BOM chain at final_response ──
    workflow.add_edge("solution_build", "final_response")

    # ── Modification path ─────────────────────────────────────────────────────
    workflow.add_conditional_edges(
        "modify_instruments",
        route_after_modification,
        {
            "apply_standards": "apply_standards",
            "final_response": "final_response",
        },
    )
    workflow.add_edge("apply_standards", "final_response")

    # ── End ───────────────────────────────────────────────────────────────────
    workflow.add_edge("final_response", END)

    return workflow.compile()


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def run_solution_agent(
    user_input: str,
    user_id: int = None,
    session_id: str = None,
    current_instruments: list = None,
    current_accessories: list = None,
    skip_standards: bool = False,
) -> dict:
    """Convenience function to run the solution agent."""
    agent = create_solution_agent()

    initial_state = {
        "user_input": user_input,
        "user_id": user_id,
        "session_id": session_id or "default",
        "current_page": "solution",
        "instruments": current_instruments or [],
        "accessories": current_accessories or [],
        "workflow_data": {},
        "agent_path": [],
        "timestamp": datetime.now(),
        "skip_standards": skip_standards,
    }

    final_state = agent.invoke(initial_state)
    return final_state.get("final_response", {})


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_solution_agent_health():
    """
    Health check for Solution Agent.
    Tests: graph compilation, LLM, MongoDB, prompts, conversation memory.
    """
    from common.utilization_tracker import (
        AgentHealthChecker,
        AgentHealthStatus,
        DependencyStatus,
        agent_metrics_tracker,
    )

    checker = AgentHealthChecker()
    dependencies = {}
    status = "healthy"
    error_msg = None

    try:
        try:
            create_solution_agent()
            dependencies["graph_compilation"] = DependencyStatus("graph", "available")
        except Exception as e:
            dependencies["graph_compilation"] = DependencyStatus("graph", "unavailable", str(e))
            status = "unhealthy"

        dependencies["llm"] = checker.check_llm_connectivity("deepinfra")
        if dependencies["llm"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_standards"] = checker.check_mongodb_collection("standards")
        if dependencies["mongodb_standards"].status == "unavailable":
            status = "unhealthy"

        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

        for prompt_key, prompt_file in [
            ("prompt_solution_agent", "solution_agent.md"),
            ("prompt_episodic_recall", "episodic_recall.md"),
            ("prompt_modification", "modification_processing.md"),
            ("prompt_holistic_agent", "holistic_agent.md"),
            ("prompt_infer_agent", "infer_agent.md"),
            ("prompt_solution_build", "solution_build.md"),
        ]:
            dependencies[prompt_key] = checker.check_prompt_file(
                os.path.join(prompt_dir, prompt_file)
            )
            if dependencies[prompt_key].status == "unavailable":
                status = "unhealthy"

        try:
            dependencies["conversation_memory"] = DependencyStatus("conversation_memory", "available")
        except Exception as e:
            dependencies["conversation_memory"] = DependencyStatus("conversation_memory", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logging.error(f"[AGENT_HEALTH] Solution agent health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="solution",
        status=status,
        dependencies=dependencies,
        metrics=agent_metrics_tracker.get_metrics("solution"),
        last_check=datetime.now(),
        error_message=error_msg,
    )
