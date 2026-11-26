"""
Advanced Specs Discovery Sub-Agent

A self-contained agent that runs IN PARALLEL with validation_agent from the
search orchestrator. No human-in-the-loop: results are auto-included and the
caller never waits for user confirmation.

This agent:
  Step 1 — Fetch latest/advanced specifications from MongoDB based on product type
  Step 2 — Return the specs so the orchestrator can merge them into the search state

No LangChain tools are used. All logic lives here.
"""

import logging
from common.helpers.notifications import notify_failure as _notify_failure
from datetime import datetime
from typing import Any

from common.infra.repositories.interaction_log_repository import interaction_logger

logger = logging.getLogger(__name__)


# ============================================================================
# MONGODB ADVANCED SPECS RETRIEVAL
# ============================================================================

def _fetch_advanced_specs_from_mongodb(product_type: str) -> list[dict[str, Any]] | None:
    """
    Fetch advanced/LATEST specifications for a product type from the Restructured
    5-tier hierarchy (the `latestRequirements` tier of the bidirectional band cascade,
    L0 ↑ + L1 + L2 ↓ around the matched node).

    This is the F3 retrieval. The legacy `advanced_specifications` collection is no
    longer consulted — the single source of truth for advanced/latest parameters is
    the 5-tier `parameters.latestRequirements`.

    Maps each latest field to the shape the agent's response formatter expects:
      {"category": "Advanced", "field": <name>, "options": [], "description": "", "unit": ...}
    Returns the list, or None if the band has no latest tier for this product type.
    """
    try:
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
        logger.info(
            f"[5TIER_AUDIT][advanced_specs_agent] LATEST_SPECS attempting "
            f"source=Restructured DB method=get_latest_by_name "
            f"traversal=L0/L1/L2-band-cascade tier=latestRequirements "
            f"product_type={product_type!r}"
        )
        latest = (ProductHierarchyRepository.get_latest_by_name(product_type) or {}).get("latest") or {}
        if not latest:
            logger.warning(
                f"[5TIER_AUDIT][advanced_specs_agent] LATEST_SPECS=EMPTY "
                f"db=Restructured product_type={product_type!r} "
                f"result=no latestRequirements in band cascade"
            )
            _notify_failure("Advanced Specs Agent - DB Fetch",
                f"No latest parameters found in 5-tier band for product type: {product_type}",
                product_type=product_type)
            return None
        specs = [{
            "category": "Advanced",
            "field": name,
            "options": [],
            "description": "",
            "value": "",
            "unit": "",
        } for name in latest.keys()]
        logger.info(
            f"[5TIER_AUDIT][advanced_specs_agent] LATEST_SPECS=SUCCESS "
            f"db=Restructured collection=L0/L1/L2 tier=latestRequirements "
            f"product_type={product_type!r} "
            f"latest_fields={len(specs)} fields={[s['field'] for s in specs]}"
        )
        return specs
    except Exception as e:
        logger.exception(f"[ADVANCED_SPECS_AGENT] Error fetching latest specs from 5-tier: {e}")
        _notify_failure("Advanced Specs Agent - DB Fetch Error",
            f"Error fetching latest specs: {str(e)}",
            product_type=product_type)
        return None


# ============================================================================
# MAIN ADVANCED SPECS DISCOVERY FUNCTION
# ============================================================================

def run_advanced_specs_discovery(product_type: str, stream_id: str = None) -> dict[str, Any]:
    """
    Run advanced specs discovery for a product type.

    HITL removed: the caller never waits for user confirmation. `action` is
    always `"auto_include"` and `requires_confirmation` is always False.

    Args:
        product_type: Detected product type

    Returns:
        Dict with keys:
          - success (bool)
          - has_advanced_specs (bool)
          - advanced_specs (list)  List of available advanced specs
          - response_message (str)  Always empty — chat uses SEARCH_ALL_SPECS_* via search_messages
          - action (str)  Always "auto_include"
          - requires_confirmation (bool)  Always False
    """
    logger.info(f"[ADVANCED_SPECS_AGENT] Starting advanced specs discovery for: {product_type}")

    # Emit streaming progress helper

    # ------------------------------------------------------------------ #
    # STEP 1 — Fetch advanced specs from MongoDB
    # ------------------------------------------------------------------ #
    def _emit(message, progress):
        if stream_id:
            try:
                from common.helpers.progress_tracker import progress_tracker
                progress_tracker.emit(stream_id, "step", {"step": "advanced_specs_discovery", "message": message, "progress": progress})
            except Exception:
                pass
    
    _emit("Loading Advanced Spec", 20)
    try:
        advanced_specs = _fetch_advanced_specs_from_mongodb(product_type)
        has_specs = advanced_specs is not None and len(advanced_specs) > 0

        logger.info(f"[ADVANCED_SPECS_AGENT] Step 1 complete — has_specs={has_specs}, count={len(advanced_specs) if advanced_specs else 0}")

    except Exception as e:
        logger.exception(f"[ADVANCED_SPECS_AGENT] Step 1 (fetch specs) failed: {e}")
        has_specs = False
        advanced_specs = []

    # ------------------------------------------------------------------ #
    # STEP 2 — Specs only (no separate chat message; sidebar flow owns UX)
    # ------------------------------------------------------------------ #
    action = "auto_include"
    requires_confirmation = False
    response_message = ""

    # ------------------------------------------------------------------ #
    # STEP 3 — Return result
    # ------------------------------------------------------------------ #
    result = {
        "success": True,
        "has_advanced_specs": has_specs,
        "advanced_specs": advanced_specs if has_specs else [],
        "response_message": response_message,
        "action": action,
        "requires_confirmation": requires_confirmation,
        "product_type": product_type
    }

    logger.info(f"[ADVANCED_SPECS_AGENT] Discovery complete — action={action}, has_specs={has_specs}, requires_confirmation={requires_confirmation}")

    # Log agent interaction to MongoDB
    try:
        user_id = None  # user_id comes from caller context
        user_id_str = str(user_id) if user_id else 'anonymous'

        # Build response summary
        response_summary = f"Advanced Specs Discovery: product_type={product_type}, has_specs={has_specs}"
        if has_specs:
            response_summary += f", specs_count={len(advanced_specs)}"

        metadata = {
            "agent_type": "advanced_specs",
            "parent_agent": "search",
            "product_type": product_type,
            "has_advanced_specs": has_specs,
            "specs_count": len(advanced_specs) if has_specs else 0,
            "requires_confirmation": requires_confirmation,
            "action": action,
            "success": True
        }

        session_id = f"advanced_specs_{user_id_str}_{datetime.now().strftime('%Y%m%d')}"

        interaction_logger.log_interaction(
            user_id=user_id_str,
            session_id=session_id,
            user_input=f"Advanced specs discovery for {product_type}",
            response=response_summary,
            metadata=metadata,
            interaction_type="agent_advanced_specs"
        )
    except Exception as log_error:
        logger.warning(f"[ADVANCED_SPECS_AGENT] Failed to log interaction: {log_error}")

    return result


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_advanced_specs_agent_health():
    """
    Health check for Advanced Specs Agent
    Tests: LLM, Restructured 5-tier hierarchy (latest params source), prompt file

    Returns:
        AgentHealthStatus with detailed dependency status
    """
    from datetime import datetime

    from common.monitoring.health import (
        AgentHealthChecker,
        AgentHealthStatus,
    )

    checker = AgentHealthChecker()
    dependencies = {}
    status = "healthy"
    error_msg = None

    try:
        # 1. Test LLM connectivity (checks API key only, no actual call)
        dependencies["llm_flash"] = checker.check_llm_connectivity("deepinfra")
        if dependencies["llm_flash"].status == "unavailable":
            status = "unhealthy"

        # 2. Test Restructured 5-tier hierarchy (latest params source) is reachable
        from common.monitoring.health import DependencyStatus
        try:
            from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
            ProductHierarchyRepository.get_categories()  # cheap reachability probe
            dependencies["restructured_5tier"] = DependencyStatus("restructured_5tier", "available")
        except Exception as e:
            dependencies["restructured_5tier"] = DependencyStatus("restructured_5tier", "unavailable", str(e))
            status = "unhealthy"

        # 3. Test prompt file (DISABLED - legacy prompt file removed)
        # prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "advanced_specs_discovery.md")
        # dependencies["prompt_advanced_specs"] = checker.check_prompt_file(prompt_path)
        # if dependencies["prompt_advanced_specs"].status == "unavailable":
        #     status = "unhealthy"

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[AGENT_HEALTH] Advanced specs agent health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="advanced_specs_agent",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg
    )
