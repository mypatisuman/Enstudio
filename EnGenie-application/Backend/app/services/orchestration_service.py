"""
Orchestration service — multi-agent control layer.

Delegates to domain/orchestrator/agents/router_classifier_agent.py.
Route handlers import from here to stay thin HTTP-only layers.
"""
import logging


def run_classifier(
    user_input: str,
    session_id: str,
    user_id=None,
    context_memory: list = None,
    **kwargs,
) -> dict:
    """
    Run the router/classifier agent to determine intent and route to the correct domain agent.

    Returns the classification result dict.
    """
    from domain.orchestrator.agents.router_classifier_agent import run_router_classifier

    result = run_router_classifier(
        user_input=user_input,
        session_id=session_id,
        user_id=user_id,
        context_memory=context_memory or [],
        **kwargs,
    )
    logging.info(f"[ORCHESTRATION_SERVICE] Classified intent={result.get('intent')} for session={session_id}")
    return result
