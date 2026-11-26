"""
Search service layer implementing the core orchestration for search AI workflows.
"""
import logging
from datetime import datetime

from common.infra.repositories.interaction_log_repository import interaction_logger

def check_search_params_completeness(search_params: dict, schema: dict) -> dict:
    import re as _re

    missing_fields: list[str] = []
    missing_friendly: list[str] = []
    EMPTY_VALUES = {"", "null", "not specified", "n/a", "none", "unknown", "[to_be_specified]"}

    def _find_value_recursive(d, target_key):
        if not isinstance(d, dict):
            return None
        norm_target = target_key.lower().replace("_", "").replace(" ", "")
        for k, v in d.items():
            norm_k = k.lower().replace("_", "").replace(" ", "")
            if norm_k == norm_target:
                if v is None:
                    return None
                if isinstance(v, dict):
                    return v if any(_find_value_recursive(v, ck) is not None for ck in v) else None
                if str(v).strip().lower() in EMPTY_VALUES:
                    return None
                return v
            if isinstance(v, dict):
                result = _find_value_recursive(v, target_key)
                if result is not None:
                    return result
        return None

    try:
        mandatory_reqs = schema.get("mandatoryRequirements", {})
        mapped_reqs = search_params.get("mapped_requirements", {})
        for category, fields in mandatory_reqs.items():
            if isinstance(fields, dict):
                for field_name in fields:
                    found_value = _find_value_recursive(mapped_reqs, field_name)
                    if found_value is None:
                        missing_fields.append(f"{category}.{field_name}")
                        friendly = _re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', field_name)
                        friendly = friendly.replace("_", " ").title()
                        missing_friendly.append(friendly)
        return {
            "is_complete": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "missing_fields_friendly": missing_friendly,
        }
    except Exception as e:
        logging.error(f"[COMPLETENESS_CHECK] Error: {e}")
        return {"is_complete": True, "missing_fields": [], "missing_fields_friendly": []}


def finish_search_agent(
    response: dict,
    search_session_id: str,
    classified_intent: str,
    user_id=None,
    user_session_id=None,
    user_input: str = "",
    request=None,
):
    """Core finalisation logic detached from FastAPI Response generation."""
    from common.ai.memory import add_conversation_turn

    next_step = response.get("nextStep")

    if request is not None:
        from common.helpers.azure_session import get_session
        session = get_session(request)
        if next_step:
            session[f'current_step_{search_session_id}'] = next_step
        session[f'current_intent_{search_session_id}'] = classified_intent

    # Record assistant turn for conversational memory (structured context commits separately).
    add_conversation_turn(
        session_id=search_session_id,
        role="assistant",
        content=response.get("message", ""),
        metadata={
            "intent": classified_intent,
            "next_step": next_step,
            "timestamp": datetime.now().isoformat(),
            "context_version": response.get("contextVersion"),
        },
    )

    if 'streamId' not in response:
        if request is not None:
            from common.helpers.azure_session import get_session
            session = get_session(request)
            response["streamId"] = session.get(f'stream_id_{search_session_id}', None)
        else:
            response["streamId"] = None

    logging.info(f"[SEARCH_AGENT] → intent={classified_intent}, nextStep={next_step}")

    try:
        user_id_str = str(user_id) if user_id else 'anonymous'
        search_executed = response.get('searchExecuted', False)
        product_type = response.get('productType', '')
        response_summary = f"Intent: {classified_intent}"
        if product_type:
            response_summary += f" | Product: {product_type}"
        if search_executed:
            response_summary += f" | {len(response.get('searchResults', []))} products found"

        interaction_logger.log_interaction(
            user_id=user_id_str,
            session_id=search_session_id,
            user_input=user_input,
            response=response_summary,
            metadata={
                "agent_type": "search",
                "search_session_id": search_session_id,
                "intent": classified_intent,
                "next_step": next_step,
                "product_type": product_type,
                "search_executed": search_executed,
                "results_count": len(response.get('searchResults', [])) if search_executed else 0,
                "success": response.get('success', True),
            },
            interaction_type="search",
        )
    except Exception as log_error:
        logging.warning(f"[SEARCH_AGENT] Failed to log interaction: {log_error}")

    # Trigger long term memory preference reflection in the background
    if user_id:
        try:
            import threading
            from common.ai.memory import run_hybrid_memory_reflection
            threading.Thread(
                target=run_hybrid_memory_reflection,
                args=(user_id, search_session_id),
                daemon=True
            ).start()
            logging.info(f"[SEARCH_AGENT] Spawning hybrid memory reflection thread for user_id={user_id}")
        except Exception as e:
            logging.warning(f"[SEARCH_AGENT] Failed to start hybrid memory reflection thread: {e}")

    # NOTE: episodic memory is prepared only from SAVED projects (see
    # MongoProjectManager.save_project), not from every completed search.

    return response
