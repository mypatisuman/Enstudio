"""
Search Summary Agent

Generates clean, organized summaries of search parameters collected from the user.
Shows what data has been collected, organized by category with completion status.

This is SEARCH WORKFLOW SPECIFIC - only summarizes search-related data.
"""

import json
from common.helpers.notifications import notify_failure as _notify_failure
import logging
import os
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from common.infra.repositories.interaction_log_repository import interaction_logger
from common.ai.memory import get_latest_search
from common.ai.llm import get_flash_llm

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

logger = logging.getLogger(__name__)




# ============================================================================
# SUMMARY GENERATION
# ============================================================================

def generate_summary(
    session_id: str,
    additional_context: dict[str, Any] = None,
    stream_id: str = None
) -> dict[str, Any]:
    """
    Generate a comprehensive summary of search parameters collected from user.

    Args:
        session_id: User session ID
        additional_context: Any additional context to include

    Returns:
        Dict with summary data in structured format (NO ICONS)
    """
    try:
        logger.info(f"[SEARCH_SUMMARY] Generating search summary for session {session_id}")

        # Emit streaming progress

        def _emit(message, progress):
            if stream_id:
                try:
                    from common.helpers.progress_tracker import progress_tracker
                    progress_tracker.emit(stream_id, "step", {"step": "summary_generation", "message": message, "progress": progress})
                except Exception:
                    pass

        _emit("Generating Summary", 50)

        # ================================================================
        # LOAD SEARCH DATA FROM MEMORY OR FRONTEND
        # ================================================================
        data = get_latest_search(session_id)
        search_params = data.get("search_params", {}) if data else {}

        if search_params and len(search_params) > 0:
            logger.info(f"[SEARCH_SUMMARY] Loaded {len(search_params)} fields from memory")
        else:
            logger.info("[SEARCH_SUMMARY] No data found in memory")

        # Flatten mapped_requirements if present - handle all possible data structures
        flattened_params = {}
        if search_params:
            if isinstance(search_params, dict):
                # Recursively flatten all nested structures
                def flatten_recursive(obj, parent_key=""):
                    items = []
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, dict):
                                # Check if it looks like a field object with label/value
                                if "label" in v and "value" in v:
                                    label = v.get("label", k)
                                    value = v.get("value")
                                    if value:  # Only add if has a value
                                        items.append((label, value))
                                        logger.debug(f"[SEARCH_SUMMARY] Found field: {label} = {value}")
                                else:
                                    # Recursively process nested dict
                                    items.extend(flatten_recursive(v, k))
                            elif isinstance(v, list):
                                # Skip lists for now
                                pass
                            else:
                                # Simple key-value pair
                                if v:  # Only add if has a value
                                    items.append((k, v))
                                    logger.debug(f"[SEARCH_SUMMARY] Found simple field: {k} = {v}")
                    return items

                flattened_list = flatten_recursive(search_params)
                flattened_params = dict(flattened_list)

                # ✨ EXPLICITLY ADD UNMAPPED SPECS (custom specs not in schema)
                # These should be displayed in summary alongside mapped specs
                unmapped_specs = search_params.get("unmapped_specs", {})
                if unmapped_specs:
                    for field, value in unmapped_specs.items():
                        if value:  # Only add if has a value
                            flattened_params[field] = value
                            logger.info(f"[SEARCH_SUMMARY] Added unmapped spec: {field} = {value}")

                user_data = json.dumps(flattened_params, indent=2)
                logger.info(f"[SEARCH_SUMMARY] Flattened structure: {len(flattened_params)} fields - {list(flattened_params.keys())}")
            else:
                user_data = json.dumps(search_params, indent=2)
        else:
            user_data = "No data collected yet"

        # Add additional context if provided
        context_str = ""
        if additional_context:
            context_str = json.dumps(additional_context, indent=2)

        # Get current workflow step
        workflow_step = data.get("workflow_step") if data else "initialInput"
        if not workflow_step:
            workflow_step = data.get("metadata", {}).get("workflow_step", "unknown") if data else "initialInput"

        logger.info(f"[SEARCH_SUMMARY] Using workflow_step: {workflow_step}, data fields: {len(flattened_params or search_params)}")

        # ================================================================
        # GENERATE SUMMARY USING LLM
        # ================================================================
        llm = get_flash_llm(temperature=0.1)

        # Load and format the prompt
        SUMMARY_GENERATION_PROMPT = open(os.path.join(_PROMPTS_DIR, "summary_generation_prompt.md"), encoding="utf-8").read()
        formatted_prompt = SUMMARY_GENERATION_PROMPT.format(
            context=context_str or "No additional context",
            user_data=user_data or "No data collected yet",
            workflow_step=workflow_step
        )

        messages = [
            SystemMessage(content="You are a data summarization expert."),
            HumanMessage(content=formatted_prompt)
        ]

        response = llm.invoke(messages)
        response_text = response.content.strip()

        # ================================================================
        # PARSE RESPONSE
        # ================================================================
        # Remove code fences if present
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        try:
            summary_data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"[SEARCH_SUMMARY] Failed to parse LLM response: {e}")
            # Return a basic fallback summary
            summary_data = create_fallback_summary(user_data)

        logger.info("[SEARCH_SUMMARY] Summary generated successfully")

        # Log agent interaction to MongoDB
        try:
            user_id = None  # user_id comes from caller context
            user_id_str = str(user_id) if user_id else 'anonymous'

            # Build response summary
            fields_count = len(flattened_params) if flattened_params else 0
            response_summary = f"Summary Generated: {fields_count} fields collected"

            metadata = {
                "agent_type": "summary",
                "parent_agent": "search",
                "session_id": session_id,
                "workflow_step": workflow_step,
                "fields_count": fields_count,
                "has_unmapped_specs": bool(search_params.get("unmapped_specs")) if search_params else False,
                "success": True
            }

            log_session_id = session_id or f"summary_{user_id_str}_{datetime.now().strftime('%Y%m%d')}"

            interaction_logger.log_interaction(
                user_id=user_id_str,
                session_id=log_session_id,
                user_input=f"Generate summary for workflow_step={workflow_step}",
                response=response_summary,
                metadata=metadata,
                interaction_type="agent_summary"
            )
        except Exception as log_error:
            logger.warning(f"[SEARCH_SUMMARY] Failed to log interaction: {log_error}")

        return summary_data

    except Exception as e:
        logger.exception(f"[SEARCH_SUMMARY] Error generating summary: {e}")

        # Notify admin of summary generation failure
        _notify_failure("Summary Agent - Generation",
            f"Summary generation failed: {str(e)}",
            session_id=session_id)

        return create_fallback_summary("Error loading data")


# ============================================================================
# FALLBACK SUMMARY
# ============================================================================

def create_fallback_summary(user_data: str) -> dict[str, Any]:
    """
    Create a basic fallback summary when LLM fails.
    Uses new flat key-value pairs format.
    """
    return {
        "summary_title": "Summary of Your Search Requirements",
        "key_value_pairs": [
            {
                "label": "Collected Requirements",
                "value": user_data
            }
        ]
    }


# ============================================================================
# SUMMARY FORMATTING UTILITIES
# ============================================================================

def format_summary_for_display(summary_data: dict[str, Any]) -> str:
    """
    Format summary data into a human-readable text format.
    Useful for chat display or console output.
    NO ICONS - clean text only.
    Flat key-value pairs format (no section grouping).

    Args:
        summary_data: Summary data from generate_summary()

    Returns:
        Formatted string
    """
    lines = []
    lines.append(f"**{summary_data.get('summary_title', 'Summary')}**\n")

    # Handle new flat key-value pairs format
    key_value_pairs = summary_data.get('key_value_pairs', [])

    if key_value_pairs:
        for pair in key_value_pairs:
            label = pair.get('label', 'Field')
            value = str(pair.get('value', '')).strip()

            # Skip empty, "Not provided", or "None" values
            if value and value.lower() not in ['not provided', 'not specified', 'none', 'null', 'n/a', '']:
                # Skip "progress" or "status" fields completely
                if label.lower() not in ['progress', 'status', 'completion']:
                    lines.append(f"- **{label}:** {value}")
    else:
        # Fallback for old section format (backward compatibility)
        for section in summary_data.get('summary_sections', []):
            section_name = section.get('section_name', 'Section')

            # Filter fields to only those with valid values
            valid_fields = []
            for field in section.get('fields', []):
                label = field.get('label', 'Field')
                value = str(field.get('value', '')).strip()

                # Skip empty, "Not provided", or "None" values
                if value and value.lower() not in ['not provided', 'not specified', 'none', 'null', 'n/a', '']:
                    # Skip "progress" or "status" fields completely
                    if label.lower() in ['progress', 'status', 'completion']:
                        continue
                    valid_fields.append((label, value))

            # Only add section if it has valid fields
            if valid_fields and section_name.lower() not in ['progress', 'status', 'completion']:
                lines.append(f"\n**{section_name}:**")
                for label, value in valid_fields:
                    lines.append(f"  - **{label}:** {value}")

    return '\n'.join(lines)


def format_summary_for_frontend(summary_data: dict[str, Any]) -> dict[str, Any]:
    """
    Format summary data for frontend consumption.
    Returns the data in a structure ready for simple list display.
    NO ICONS - clean data only.
    Flat key-value pairs format (no section grouping).

    Args:
        summary_data: Summary data from generate_summary()

    Returns:
        Frontend-ready dict with flat items list
    """
    # Check if new flat key-value format
    key_value_pairs = summary_data.get("key_value_pairs", [])

    if key_value_pairs:
        # New format: return simple flat items list
        return {
            "title": summary_data.get("summary_title", "Summary"),
            "items": [
                {
                    "label": pair.get("label", "Field"),
                    "value": pair.get("value", "Not provided")
                }
                for pair in key_value_pairs
            ]
        }
    else:
        # Fallback for old section format (backward compatibility)
        return {
            "title": summary_data.get("summary_title", "Summary"),
            "sections": [
                {
                    "name": section.get("section_name", "Section"),
                    "items": [
                        {
                            "label": field.get("label", "Field"),
                            "value": field.get("value", "Not provided")
                        }
                        for field in section.get("fields", [])
                    ]
                }
                for section in summary_data.get("summary_sections", [])
            ]
        }


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_summary_agent_health():
    """
    Health check for Summary Agent
    Tests: LLM, prompt file

    Returns:
        AgentHealthStatus with detailed dependency status
    """
    import os
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

        # 2. Test prompt file
        prompt_path = os.path.join(os.path.dirname(__file__), "..", "prompts", "summary_generation_prompt.md")
        dependencies["prompt_summary"] = checker.check_prompt_file(prompt_path)
        if dependencies["prompt_summary"].status == "unavailable":
            status = "unhealthy"

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        import logging
        logging.getLogger(__name__).error(f"[AGENT_HEALTH] Summary agent health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="summary_agent",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg
    )
