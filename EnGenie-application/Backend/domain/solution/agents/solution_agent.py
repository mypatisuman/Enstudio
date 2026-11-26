"""
Solution Agent

Handles the complete Solution page workflow for instrument identification and vendor search.

This agent:
1. Classifies project intent (inline LLM classification - requirements vs modification vs clarification)
2. Routes to instrument identification or modification or clarification
3. Returns identified instruments/accessories or asks for clarification
"""

import ast
import json
from common.helpers.notifications import notify_failure as _notify_failure
import logging
import os
import sys
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from typing import Literal

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
from common.helpers.node_retry import retryable_node
from domain.orchestrator.state import AgenticSystemState
from domain.solution.schemas import SolutionResponse
from common.ai.llm import SOLUTION_LLM_PROVIDER, get_solution_flash_llm, get_solution_pro_llm, with_json_mode
from common.ai.prompts.response import SOLUTION_MODIFICATION_APPLIED_PROMPT

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

def _load_prompt(filename: str) -> str:
    try:
        with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"Prompt file not found: {filename}")
        return ""

SOLUTION_AGENT_PROMPT = _load_prompt('solution_agent.md')
MODIFICATION_PROCESSING_PROMPT = _load_prompt('modification_processing.md')
from common.ai.memory import (
    clear_all_session_data,
    format_conversation_for_prompt,
    get_full_conversation_history,
    get_latest_instruments_and_accessories,
)
from domain.solution.memory import (
    build_looped_conversation_context,
    append_node_execution_context,
)
from common.helpers.progress_tracker import progress_tracker

# ============================================================================
# SHARED LLM INSTANCE - Reused across all nodes in solution agent
# ============================================================================

# Flash model for intent classification and other operations
# Uses SOLUTION_LLM_PROVIDER (e.g. openai/gpt-4.1-mini) independently of the
# global LLM_PROVIDER so the rest of the app (chat, router) is unaffected.
llm_flash = get_solution_flash_llm(temperature=0.1)

# Pro model for modification processing (complex BOM edits require stronger reasoning)
llm_pro = get_solution_pro_llm(temperature=0.1)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def escape_newlines_in_json(s: str) -> str:
    """Escapes literal newlines, carriage returns, and tabs inside JSON string values."""
    result = []
    in_string = False
    escaped = False
    for char in s:
        if char == '"' and not escaped:
            in_string = not in_string
            result.append(char)
        elif char == '\\' and in_string:
            escaped = not escaped
            result.append(char)
        else:
            if escaped:
                escaped = False
            if in_string and char in ('\n', '\r', '\t'):
                if char == '\n':
                    result.append('\\n')
                elif char == '\r':
                    result.append('\\r')
                elif char == '\t':
                    result.append('\\t')
            else:
                result.append(char)
    return "".join(result)




# ============================================================================
# PROJECT INTENT NODE
# ============================================================================

@retryable_node(max_attempts=2, label="project_intent")
def project_intent_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Classify project intent (inline LLM classification - requirements vs modification vs confirm_search).

    Args:
        state: Current agentic system state

    Returns:
        Updated state with intent classification
    """
    # NO PROGRESS EVENT HERE - Frontend shows bouncing dots during intent detection
    # Streaming starts AFTER intent is detected in the workflow nodes

    logging.info(f"[SOLUTION_AGENT] Classifying project intent for: {state.get('user_input', '')[:100]}...")

    # Track agent path
    if not state.get("agent_path"):
        state["agent_path"] = []
    state["agent_path"].append("solution_workflow.project_intent")

    # Initialize workflow_data
    if not state.get("workflow_data"):
        state["workflow_data"] = {}

    # Get context from state
    user_input = state.get("user_input", "")
    current_instruments = state.get("instruments", [])
    current_accessories = state.get("accessories", [])
    state["workflow_data"].get("awaiting_single_item_confirmation", False)
    session_id = state.get("session_id", "default")

    # Validate input
    if not user_input or not user_input.strip():
        state["workflow_data"]["project_intent"] = "error"
        state["workflow_data"]["response_message"] = "Please provide a valid input."
        state["error"] = "Empty user input"
        return state

    # Build rich multi-turn context via chronological looping
    conversation_context = build_looped_conversation_context(state, session_id=session_id)

    # ========================================================================
    # INTENT CLASSIFICATION
    # ========================================================================
    # Router classifier handles routing to Search page.
    # Solution agent only handles: requirements, modification, clarification, reset
    try:
        # Escape curly braces in conversation context for ChatPromptTemplate
        escaped_context = conversation_context.replace("{", "{{").replace("}", "}}") if conversation_context else "No previous conversation."

        # Build classification chain with formatted prompt using shared Flash LLM
        classification_chain = (
            ChatPromptTemplate.from_template(SOLUTION_AGENT_PROMPT)
            | with_json_mode(llm_flash, SOLUTION_LLM_PROVIDER)  # forces JSON output on OpenAI; no-op on other providers
            | StrOutputParser()
        )

        # Get classification
        classification_response = classification_chain.invoke({
            "user_input": user_input,
            "conversation_context": escaped_context
        })

        # Clean and parse JSON
        cleaned_response = classification_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        elif cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        # Log what we're trying to parse (for debugging)
        logging.info(f"[SOLUTION_AGENT] Intent response to parse: {cleaned_response[:200]}...")

        # Preprocess JSON to handle literal control characters inside string values
        cleaned_response = escape_newlines_in_json(cleaned_response)

        try:
            intent_result = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            logging.warning(f"[SOLUTION_AGENT] JSON parse error: {e}. Trying ast.literal_eval...")
            try:
                intent_result = ast.literal_eval(cleaned_response)
                if not isinstance(intent_result, dict):
                    raise ValueError("Parsed content is not a dictionary")
            except Exception as e2:
                logging.error(f"[SOLUTION_AGENT] Failed to parse response with both json and ast: {e2}. Response: {cleaned_response[:500]}")
                raise e

        # Get intent type
        intent_type = intent_result.get("type", "requirements")
        input_range = intent_result.get("input_range", "mid")

        # Store intent classification
        state["workflow_data"]["project_intent"] = intent_type
        state["workflow_data"]["intent_confidence"] = intent_result.get("confidence", "medium")
        state["workflow_data"]["intent_reasoning"] = intent_result.get("reasoning", "")

        state["workflow_data"]["input_range"] = input_range

        # Append to node-to-node context memory trail
        append_node_execution_context(
            state,
            "project_intent",
            f"Classified user intent as '{intent_type}' (confidence: {state['workflow_data'].get('intent_confidence')}, range: {input_range})",
            {"intent": intent_type, "confidence": state["workflow_data"].get("intent_confidence"), "reasoning": state["workflow_data"].get("intent_reasoning")},
        )


        # ================================================================
        # HANDLE ROUTER_NEEDED INTENT - Call router classifier
        # ================================================================
        if intent_type == "router_needed":
            logging.info("[SOLUTION_AGENT] Input is not solution-related - calling router classifier")

            # Import router classifier
            from domain.orchestrator.agents.router_classifier_agent import router_classifier_node

            # Call router classifier with current state
            router_state = router_classifier_node(state)

            # Copy router results to workflow_data
            state["workflow_data"]["response_type"] = "router_redirect"
            state["workflow_data"]["router_category"] = router_state.get("route_category")
            state["workflow_data"]["router_target_page"] = router_state.get("target_page")
            state["workflow_data"]["router_requires_routing"] = router_state.get("requires_routing")
            state["workflow_data"]["router_url"] = router_state.get("routing_url", "")
            state["workflow_data"]["router_message"] = router_state.get("routing_message") or router_state.get("direct_response", "")
            state["workflow_data"]["response_message"] = router_state.get("routing_message") or router_state.get("direct_response", "")

            logging.info(f"[SOLUTION_AGENT] Router classified as: {router_state.get('route_category')} → {router_state.get('target_page')}")

        # ================================================================
        # HANDLE RESET INTENT - Ask for confirmation
        # ================================================================
        elif intent_type == "reset":
            logging.info("[SOLUTION_AGENT] Intent is RESET - asking user for confirmation")

            # Set response message from LLM
            state["workflow_data"]["response_message"] = intent_result.get("message")
            state["workflow_data"]["response_type"] = "reset_confirmation"

            logging.info("[SOLUTION_AGENT] Sent reset confirmation request to user")

        # ================================================================
        # HANDLE RESET CONFIRMED - Clear everything
        # ================================================================
        elif intent_type == "reset_confirmed":
            logging.info("[SOLUTION_AGENT] User confirmed reset - clearing session")

            # Clear conversation memory for this session
            clear_all_session_data(session_id)

            # Set response message from LLM
            state["workflow_data"]["response_message"] = intent_result.get("message")
            state["workflow_data"]["response_type"] = "reset_confirmed"

            # Clear instruments and accessories
            state["instruments"] = []
            state["accessories"] = []

            logging.info(f"[SOLUTION_AGENT] Session reset complete for: {session_id}")

        # ================================================================
        # HANDLE RESET CANCELLED
        # ================================================================
        elif intent_type == "reset_cancelled":
            logging.info("[SOLUTION_AGENT] User cancelled reset - keeping data")

            # Set response message from LLM
            state["workflow_data"]["response_message"] = intent_result.get("message")
            state["workflow_data"]["response_type"] = "reset_cancelled"

            logging.info("[SOLUTION_AGENT] Reset cancelled, data preserved")

        # ================================================================
        # HANDLE CLARIFICATION INTENT
        # ================================================================
        elif intent_type == "clarification":
            logging.info("[SOLUTION_AGENT] Intent is CLARIFICATION - asking user for more details")

            # Extract clarification data
            state["workflow_data"]["clarification_questions"] = intent_result.get("clarification_questions", [])
            state["workflow_data"]["missing_information"] = intent_result.get("missing_information", "")
            state["workflow_data"]["response_message"] = intent_result.get("message", "I need more information to help you.")
            state["workflow_data"]["response_type"] = "clarification"

            # Set state for direct response (skip instrument identification)
            state["clarification_needed"] = True
            state["clarification_questions"] = intent_result.get("clarification_questions", [])
            state["clarification_context"] = {
                "missing_information": intent_result.get("missing_information", ""),
                "reason": intent_result.get("reasoning", "")
            }

            logging.info(f"[SOLUTION_AGENT] Clarification questions: {state['clarification_questions']}")

        # ================================================================
        # HANDLE CONTEXTUAL QNA INTENT
        # ================================================================
        elif intent_type == "contextual_qna":
            logging.info("[SOLUTION_AGENT] Intent is CONTEXTUAL QNA - answering question directly")

            # Set response message directly from LLM
            state["workflow_data"]["response_message"] = intent_result.get("message")
            state["workflow_data"]["response_type"] = "qna"

        logging.info(f"[SOLUTION_AGENT] Intent classified as: {state['workflow_data']['project_intent']}")

        return state

    except Exception as e:
        logging.exception(f"[SOLUTION_AGENT] Intent classification failed: {e}")
        state["error"] = f"Failed to classify intent: {str(e)}"
        state["workflow_data"]["project_intent"] = "error"
        state["workflow_data"]["response_message"] = "I'm having trouble processing your request. Please try again."

        # Notify admin
        _notify_failure("Solution Intent Classification",
            f"Intent classification failed: {str(e)}",
            state=state,
            page="solution",
            user_input=state.get("user_input", ""))

        return state


# ============================================================================
# MODIFICATION NODE
# ============================================================================

@retryable_node(max_attempts=2, label="modification")
def modification_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Handle modification of existing instruments and accessories.

    Args:
        state: Current agentic system state

    Returns:
        Updated state with modified instruments/accessories
    """
    # Emit progress event
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "modify_instruments",
            "message": "Processing Modifications",
            "progress": 40
        })

    logging.info("[SOLUTION_AGENT] Processing modification request...")

    # Track agent path
    state["agent_path"].append("solution_workflow.modification")

    # Get modification request and current data
    modification_request = state.get("user_input", "")
    session_id = state.get("session_id", "default")

    # Get current instruments/accessories from state OR auto-load from memory
    current_instruments = state.get("instruments", [])
    current_accessories = state.get("accessories", [])

    # If state doesn't have instruments/accessories, try loading from conversation memory
    if not current_instruments and not current_accessories:
        logging.info("[SOLUTION_AGENT] No instruments/accessories in state, loading from conversation memory...")
        memory_data = get_latest_instruments_and_accessories(session_id)
        current_instruments = memory_data.get("instruments", [])
        current_accessories = memory_data.get("accessories", [])

        # Update state with loaded data
        if current_instruments or current_accessories:
            state["instruments"] = current_instruments
            state["accessories"] = current_accessories
            logging.info(f"[SOLUTION_AGENT] ✓ Loaded {len(current_instruments)} instruments and {len(current_accessories)} accessories from memory")

    # Validate that we have something to modify
    if not current_instruments and not current_accessories:
        logging.warning("[SOLUTION_AGENT] No existing instruments/accessories to modify")
        state["workflow_data"]["response_type"] = "error"
        state["workflow_data"]["response_message"] = "You don't have any instruments or accessories yet. Please provide requirements first."
        state["error"] = "Nothing to modify"
        return state

    # Build conversation-enriched modification request using chronological loop
    looped_context = build_looped_conversation_context(state, session_id=session_id)
    enriched_request = f"{looped_context}\n\nCurrent User Modification Request: {modification_request}"

    # Process modification using shared LLM (no separate tool needed!)
    try:
        # Internal metadata fields added by Node 2/3 of the deep agent.
        # The modification LLM only needs the BOM fields (category, specs, qty, etc.).
        # Sending taxonomy/standards metadata bloats the input and can hit Flash token limits.
        _INTERNAL_ONLY_FIELDS = {
            "original_category", "db_category", "category_mapped", "taxonomy_found",
            "use_db_category_only", "semantic_match", "semantic_confidence",
            "spec_field_mappings", "mapped_specifications",
            "standards_specs", "applicable_standards", "applicable_standards_titles",
            "standards_summary", "standards_source",
            "sample_input",  # regenerated after modification anyway
            "_newly_added",
        }

        def _strip_internal_fields(item: dict) -> dict:
            return {k: v for k, v in item.items() if k not in _INTERNAL_ONLY_FIELDS}

        # Prepare current state JSON — only BOM-relevant fields for the LLM
        current_state = {
            "instruments": [_strip_internal_fields(i) for i in current_instruments],
            "accessories": [_strip_internal_fields(a) for a in current_accessories],
        }
        current_state_json = json.dumps(current_state, indent=2)

        # Build modification chain using Pro LLM (complex BOM edits require stronger reasoning)
        modification_prompt = ChatPromptTemplate.from_template(MODIFICATION_PROCESSING_PROMPT)
        modification_chain = modification_prompt | with_json_mode(llm_pro, SOLUTION_LLM_PROVIDER) | StrOutputParser()  # JSON mode for OpenAI

        # Execute modification
        llm_response = modification_chain.invoke({
            "current_state": current_state_json,
            "modification_request": enriched_request
        })

        # Clean and parse JSON
        cleaned_response = llm_response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        elif cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        # Preprocess JSON to handle literal control characters inside string values
        cleaned_response = escape_newlines_in_json(cleaned_response)

        modification_result = json.loads(cleaned_response)

        # Ensure all required fields exist in instruments
        for instrument in modification_result.get("instruments", []):
            instrument.setdefault("strategy", "")
            instrument.setdefault("quantity", 1)
            instrument.setdefault("specified_vendors", [])
            instrument.setdefault("specified_model_families", [])
            instrument.setdefault("user_specified_standards", [])
            instrument.setdefault("skip_standards", False)

        # Ensure all required fields exist in accessories
        for accessory in modification_result.get("accessories", []):
            accessory.setdefault("strategy", "")
            accessory.setdefault("quantity", 1)
            accessory.setdefault("specified_vendors", [])
            accessory.setdefault("specified_model_families", [])
            accessory.setdefault("user_specified_standards", [])
            accessory.setdefault("skip_standards", False)

        # Mark newly added items and preserve standards + taxonomy fields
        standards_fields = ['standards_specs', 'applicable_standards', 'applicable_standards_titles', 'standards_summary', 'standards_source']
        taxonomy_fields = [
            'original_category', 'db_category', 'category_mapped', 'taxonomy_found',
            'use_db_category_only', 'semantic_match', 'semantic_confidence',
            'spec_field_mappings', 'mapped_specifications'
        ]
        preserve_fields = standards_fields + taxonomy_fields

        # Build lookup maps
        original_instruments_by_category = {
            (inst.get('category') or '').strip().lower(): inst
            for inst in current_instruments if inst.get('category')
        }
        original_accessories_by_category = {
            (acc.get('category') or '').strip().lower(): acc
            for acc in current_accessories if acc.get('category')
        }

        # Re-attach standards + taxonomy fields and flag new items
        for instrument in modification_result.get("instruments", []):
            cat = (instrument.get('category') or '').strip().lower()
            original = original_instruments_by_category.get(cat)
            if original:
                for field in preserve_fields:
                    if field in original and field not in instrument:
                        instrument[field] = original[field]
                instrument['_newly_added'] = False
            else:
                instrument['_newly_added'] = True

        for accessory in modification_result.get("accessories", []):
            cat = (accessory.get('category') or '').strip().lower()
            original = original_accessories_by_category.get(cat)
            if original:
                for field in preserve_fields:
                    if field in original and field not in accessory:
                        accessory[field] = original[field]
                accessory['_newly_added'] = False
            else:
                accessory['_newly_added'] = True

        # Convert to expected format
        modification_result = {
            "success": True,
            "instruments": modification_result.get("instruments", current_instruments),
            "accessories": modification_result.get("accessories", current_accessories),
            "changes_made": modification_result.get("changes_made", []),
            "summary": modification_result.get("summary", "Modifications applied successfully."),
            "message": modification_result.get("summary", "Modifications applied successfully.")
        }

        if modification_result.get("success"):
            logging.info(f"[SOLUTION_AGENT] Modification successful. Changes: {len(modification_result.get('changes_made', []))}")

            # Update state with modified lists
            state["instruments"] = modification_result.get("instruments", [])
            state["accessories"] = modification_result.get("accessories", [])

            # Detect if new items were added
            has_new_items = any(
                inst.get('_newly_added', False)
                for inst in modification_result.get("instruments", [])
            ) or any(
                acc.get('_newly_added', False)
                for acc in modification_result.get("accessories", [])
            )

            # Emit different progress message based on modification type
            if stream_id and state.get("enable_streaming"):
                if has_new_items:
                    progress_tracker.emit(stream_id, "step", {
                        "step": "modification_complete",
                        "message": "New items added, searching standards...",
                        "progress": 60
                    })
                else:
                    progress_tracker.emit(stream_id, "step", {
                        "step": "modification_complete",
                        "message": "Modifications applied successfully.",
                        "progress": 60
                    })

            # Store flag for standards node
            state["has_new_items_from_modification"] = has_new_items

            # Generate chat response using SOLUTION_MODIFICATION_APPLIED_PROMPT
            try:
                changes = modification_result.get("changes_made", [])
                changes_str = "\n".join([f"- {change}" for change in changes])
                prompt = ChatPromptTemplate.from_template(SOLUTION_MODIFICATION_APPLIED_PROMPT)
                chain = prompt | llm_flash | StrOutputParser()
                message = chain.invoke({"changes_list": changes_str}).strip()
            except Exception as e:
                logging.exception(f"[SOLUTION_AGENT] Failed to generate modification response message: {e}")
                message = modification_result.get("message", "Modifications applied successfully.")

            # Store results in workflow_data
            state["workflow_data"]["response_type"] = "modification"
            state["workflow_data"]["is_modification"] = True  # Flag for standards node
            state["workflow_data"]["summary"] = modification_result.get("summary", "")
            state["workflow_data"]["response_message"] = message

            # Append to node-to-node context memory trail
            append_node_execution_context(
                state,
                "modify_instruments",
                f"Applied modifications: {modification_result.get('summary', 'Modifications applied')}. Project state: {len(state.get('instruments', []))} instruments, {len(state.get('accessories', []))} accessories",
                {"changes_made": modification_result.get("changes_made", []), "summary": modification_result.get("summary", "")},
            )

        else:
            logging.error(f"[SOLUTION_AGENT] Modification failed: {modification_result.get('message')}")
            state["workflow_data"]["response_type"] = "error"
            state["workflow_data"]["response_message"] = modification_result.get("message", "Failed to process modifications.")
            state["error"] = "Modification processing failed"

            # Send notification for modification validation failure
            _notify_failure("Solution Modification Validation",
                f"Modification validation failed: {modification_result.get('message', 'Unknown error')}",
                state=state,
                page="solution",
                modification_request=state.get("user_input", ""))

        return state

    except Exception as e:
        logging.exception(f"[SOLUTION_AGENT] Modification node failed: {e}")
        state["error"] = f"Failed to process modification: {str(e)}"
        state["workflow_data"]["response_type"] = "error"
        state["workflow_data"]["response_message"] = "An error occurred while processing your modifications. Please try again."

        # Notify admin
        _notify_failure("Solution Modification",
            f"Modification failed: {str(e)}",
            state=state,
            page="solution",
            modification_request=state.get("user_input", ""))

        return state


# ============================================================================
# STANDARDS APPLICATION NODE
# ============================================================================

@retryable_node(max_attempts=2, label="standards_application")
def standards_application_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Apply engineering standards from user's documents to instruments/accessories.

    This node:
    1. Checks if user has uploaded standards documents
    2. Calls get_standards_for_category directly for each instrument/accessory
    3. Enriches instruments/accessories with standards_specs

    Args:
        state: Current agentic system state

    Returns:
        Updated state with standards applied to instruments/accessories
    """
    # Track agent path
    state["agent_path"].append("solution_workflow.standards_application")

    # Ensure workflow_data exists
    if not state.get("workflow_data"):
        state["workflow_data"] = {}

    # CHECK: Skip if Deep Agent already applied standards
    if state.get("deep_analysis", {}).get("enhanced_instruments"):
        logging.info("[SOLUTION_AGENT] Standards already applied by Deep Agent. Skipping redundant application.")
        state["workflow_data"]["standards_applied"] = True  # Mark as applied (by deep agent)
        return state

    # CHECK: Skip if user toggled standards OFF from the frontend
    if state.get("skip_standards", False):
        logging.info("[SOLUTION_AGENT] Standards disabled by user toggle. Skipping standards application.")
        state["workflow_data"]["standards_applied"] = False
        return state

    logging.info("[SOLUTION_AGENT] Applying engineering standards...")

    # Get user_id from state
    user_id = state.get("user_id")

    if not user_id:
        logging.warning("[SOLUTION_AGENT] No user_id provided, skipping standards application")
        state["workflow_data"]["standards_applied"] = False
        return state

    # Get instruments and accessories
    instruments = state.get("instruments", [])
    accessories = state.get("accessories", [])

    # Check if we have anything to apply standards to
    if not instruments and not accessories:
        logging.info("[SOLUTION_AGENT] No instruments or accessories to apply standards to")
        state["workflow_data"]["standards_applied"] = False
        return state

    # Check if this is a modification flow
    is_modification = state.get("workflow_data", {}).get("is_modification", False)

    # Process each instrument and accessory directly using RAG
    try:
        # Emit initial progress with context-aware message
        stream_id = state.get("stream_id")
        has_new_items = state.get("has_new_items_from_modification", False)

        if stream_id and state.get("enable_streaming"):
            if is_modification:
                if has_new_items:
                    progress_tracker.emit(stream_id, "step", {
                        "step": "apply_standards",
                        "message": "Searching standards for new items...",
                        "progress": 85
                    })
                else:
                    # No new items in modification, skip showing this step
                    pass
            else:
                # New requirements flow
                progress_tracker.emit(stream_id, "step", {
                    "step": "apply_standards",
                    "message": "Searching Standards",
                    "progress": 85
                })

        # Helper: regenerate sample_input from merged specs, tags stripped
        def _rebuild_sample_input(specifications: dict, category: str = "") -> str:
            if not specifications:
                return ""
            parts = []
            for key, value in specifications.items():
                clean_val = str(value).replace("[INFERRED]", "").replace("[STANDARD]", "").strip()
                parts.append(f"{key}: {clean_val}")
            specs_str = ", ".join(parts)
            prefix_parts = []
            if category:
                prefix_parts.append(category)
            prefix = ", ".join(prefix_parts)
            return f"{prefix}, {specs_str}" if prefix and specs_str else (prefix or specs_str)

        def _apply_standards_to_item(item: dict) -> int:
            """
            Fetch standards for one item (instrument or accessory) and merge specs in-place.
            Returns 1 if standards were applied, 0 otherwise.
            """
            category = item.get('category', '')
            if not category:
                return 0
            try:
                standards_result = ProductHierarchyRepository.get_standards_for_category(user_id, category)
                if standards_result and standards_result.get('found'):
                    from domain.solution.agents.harness_agent import harness_evaluate_standards_grounding
                    standards_result = harness_evaluate_standards_grounding(standards_result, category)
                    standards_specs = standards_result.get('specifications', {})

                    original_specs = item.get('specifications', {})

                    merged_specs = dict(original_specs)

                    user_mentioned_standards = item.get('user_specified_standards', [])
                    if user_mentioned_standards:
                        merged_specs["Applicable Standards"] = ", ".join(user_mentioned_standards)

                    def _norm(k: str) -> str:
                        return k.lower().replace("_", "").replace(" ", "")

                    normalized_merged = {_norm(k) for k in merged_specs}
                    for std_key, std_value in standards_specs.items():
                        if _norm(std_key) not in normalized_merged:
                            merged_specs[std_key] = f"{std_value} [STANDARD]"

                    item['specifications'] = merged_specs
                    item['standards_specs'] = standards_specs
                    item['applicable_standards'] = standards_result.get('applicable_standards', [])
                    item['standards_summary'] = standards_result.get('requirements_summary', '')
                    item['standards_source'] = 'document'
                    item['sample_input'] = _rebuild_sample_input(
                        merged_specs,
                        category=item.get('category', ''),
                    )

                    logging.info(f"[SOLUTION_AGENT] ✓ Applied standards to '{category}'")
                    return 1
            except Exception as e:
                logging.error(f"[SOLUTION_AGENT] Failed to apply standards to '{category}': {e}")
            return 0

        # Collect items that actually need standards fetched
        items_needing_standards: list[dict] = []
        for instrument in instruments:
            if instrument.get('standards_specs') or instrument.get('skip_standards', False):
                continue
            if is_modification and not instrument.get('_newly_added', False):
                logging.info(f"[SOLUTION_AGENT] Skipping standards for existing instrument: {instrument.get('category')} (not newly added)")
                continue
            if instrument.get('category'):
                items_needing_standards.append(instrument)

        for accessory in accessories:
            if accessory.get('standards_specs') or accessory.get('skip_standards', False):
                continue
            if is_modification and not accessory.get('_newly_added', False):
                logging.info(f"[SOLUTION_AGENT] Skipping standards for existing accessory: {accessory.get('category')} (not newly added)")
                continue
            if accessory.get('category'):
                items_needing_standards.append(accessory)

        standards_applied_count = 0
        total_items = len(items_needing_standards)

        if items_needing_standards:
            logging.info(f"[SOLUTION_AGENT] 🚀 Fetching standards in PARALLEL for {total_items} items")

            # P3.2 FIX: Increased parallel RAG timeout to 1800s (30 min) for complex requirements
            # FIX: Reduced max_workers from 20 to 10 to avoid resource exhaustion
            from concurrent.futures import TimeoutError as FuturesTimeoutError
            with ThreadPoolExecutor(max_workers=min(total_items, 10)) as executor:
                future_to_item = {
                    executor.submit(_apply_standards_to_item, item): item
                    for item in items_needing_standards
                }

                completed = 0
                # P3.2: Cap at 540s (9 min) to stay within Consumption plan 10 min limit
                try:
                    for future in as_completed(future_to_item, timeout=540):
                        try:
                            standards_applied_count += future.result()
                            completed += 1
                            if stream_id and state.get("enable_streaming"):
                                sub_progress = (completed / total_items) * 100
                                msg_prefix = "Adding Standards" if is_modification else "Fetching Standards"
                                progress_tracker.emit(stream_id, "sub_step", {
                                    "message": f"{msg_prefix} ({completed}/{total_items})",
                                    "sub_progress": sub_progress,
                                })
                        except Exception as inner_e:
                            logging.error(f"[SOLUTION_AGENT] Individual standards task failed: {inner_e}")
                            completed += 1 # Still count as attempted
                except FuturesTimeoutError:
                    logging.warning("[SOLUTION_AGENT] Standards application timed out after 1800s (30 min). Proceeding with partial results.")
                    if "warnings" not in state:
                        state["warnings"] = []
                    state.get("warnings", []).append("Could not retrieve all engineering standards after 30 minutes. Some specifications may be missing.")

            logging.info(f"[SOLUTION_AGENT] ✓ Parallel standards fetch complete. Applied to {standards_applied_count}/{total_items} items")

        # Clean up _newly_added flags before setting state (don't leak internal flags to API)
        for instrument in instruments:
            instrument.pop('_newly_added', None)
        for accessory in accessories:
            accessory.pop('_newly_added', None)

        # Update state
        state["instruments"] = instruments
        state["accessories"] = accessories
        state["workflow_data"]["standards_applied"] = standards_applied_count > 0

        if standards_applied_count > 0:
            logging.info(f"[SOLUTION_AGENT] ✓ Successfully applied standards to {standards_applied_count} items")
        else:
            logging.info("[SOLUTION_AGENT] No applicable standards found")

        # If this was a modification and an active P&ID graph exists, trigger evolutionary P&ID update
        if is_modification or state.get("has_new_items_from_modification"):
            try:
                active_pid = state.get("pid_graph") or state.get("active_pid_graph") or (state.get("designed_solution") or {}).get("pid_graph")
                if active_pid:
                    from domain.solution.services.pid_builder_service import build_pid_from_solution
                    updated_pid = build_pid_from_solution(
                        requirements=state.get("user_input", "Apply modifications"),
                        designed_solution=state.get("designed_solution"),
                        instruments=instruments,
                        accessories=accessories,
                        sub_systems=state.get("workflow_data", {}).get("sub_systems"),
                        active_pid_graph=active_pid,
                        user_id=user_id,
                    )
                    state["pid_graph"] = updated_pid
                    if state.get("designed_solution") and isinstance(state["designed_solution"], dict):
                        state["designed_solution"]["pid_graph"] = updated_pid
                    logging.info(f"[SOLUTION_AGENT] ✓ Updated active P&ID graph with modifications ({len(updated_pid.get('nodes', []))} nodes)")
            except Exception as pid_mod_err:
                logging.warning(f"[SOLUTION_AGENT] Evolutionary P&ID update encountered an issue: {pid_mod_err}")

        return state

    except Exception as e:
        logging.exception(f"[SOLUTION_AGENT] Standards application node failed: {e}")
        # Don't fail the entire workflow, just continue without standards
        state["workflow_data"]["standards_applied"] = False
        if "warnings" not in state:
            state["warnings"] = []
        state["warnings"].append(f"Standards application failed: {str(e)}")

        # Notify admin
        _notify_failure("Solution Standards Application",
            f"Standards application failed: {str(e)}",
            state=state,
            page="solution")

        return state



# ============================================================================
# FINAL RESPONSE NODE
# ============================================================================

def build_final_response_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Build final response to return to user.

    Args:
        state: Current agentic system state

    Returns:
        Updated state with final_response
    """
    # Emit progress event
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "final_response",
            "message": "Finalizing Response",
            "progress": 95
        })

    logging.info("[SOLUTION_AGENT] Building final response...")

    # Track agent path
    state["agent_path"].append("solution_workflow.final_response")

    # Build response from workflow_data
    workflow_data = state.get("workflow_data", {})

    # Episodic recall short-circuit: emit the exact legacy cache_confirmation
    # contract the frontend modal depends on. Deliberately NO harness repair —
    # SolutionResponse(extra="ignore") would strip matched_projects /
    # requires_confirmation / type and break the modal.
    recall_offer = workflow_data.get("recall_offer")
    if recall_offer:
        state["final_response"] = {
            "type": "cache_confirmation",
            "intent": "cache_confirmation",
            "message": recall_offer.get("message", ""),
            "requires_confirmation": True,
            "matched_projects": recall_offer.get("matched_projects", []),
        }
        logging.info("[SOLUTION_AGENT] Final response = episodic recall offer (cache_confirmation).")
        return state

    # Check for errors
    if state.get("error"):
        state["final_response"] = SolutionResponse.ensure_compliant({
            "success": False,
            "error": state.get("error"),
            "input_range": workflow_data.get("input_range", "mid"),
            "message": workflow_data.get("response_message", "An error occurred")
        })
        return state

    # Handle router_needed responses specially
    if workflow_data.get("project_intent") == "router_needed":
        response = {
            "success": True,
            "intent": "router_needed",
            "input_range": workflow_data.get("input_range", "mid"),
            "response_type": "router_redirect",
            "message": workflow_data.get("router_message", ""),
            "router_category": workflow_data.get("router_category"),
            "router_target_page": workflow_data.get("router_target_page"),
            "router_requires_routing": workflow_data.get("router_requires_routing", False),
            "router_url": workflow_data.get("router_url", ""),
            "instruments": state.get("instruments", []),
            "accessories": state.get("accessories", []),
            "agent_path": state.get("agent_path", [])
        }
    else:
        # Build standard success response
        response = {
            "success": True,
            "intent": workflow_data.get("project_intent"),
            "input_range": workflow_data.get("input_range", "mid"),
            "response_type": workflow_data.get("response_type"),
            "project_name": workflow_data.get("project_name", ""),
            "sub_systems": workflow_data.get("sub_systems", []),
            "instruments": state.get("instruments", []),
            "accessories": state.get("accessories", []),
            "summary": workflow_data.get("summary", ""),
            "message": workflow_data.get("response_message", ""),
            "awaiting_confirmation": workflow_data.get("awaiting_single_item_confirmation", False),
            "awaiting_holistic_confirmation": workflow_data.get("awaiting_holistic_confirmation", False),
            "refinement_applied": workflow_data.get("refinement_applied", False),
            "engineering_completeness": workflow_data.get("engineering_completeness"),
            # The gate-consolidated requirement (original + chat-supplied answers) —
            # persisted into conversation metadata so save_project can embed the
            # FULL requirement for episodic recall, not the frontend's stale field.
            "consolidated_requirements": (state.get("user_input", "")
                                          if workflow_data.get("original_user_input") else None),

            # P0.5 FIX: Add explicit metadata for empty results
            "is_empty_result": not (state.get("instruments") or state.get("accessories")),
            "identification_warning": "No instruments or accessories were identified from your request. Please ensure the requirements are clear and technical." if not (state.get("instruments") or state.get("accessories")) else None,

            # Clarification fields
            "clarification_needed": state.get("clarification_needed", False),
            "clarification_questions": state.get("clarification_questions", []),
            "clarification_context": state.get("clarification_context", {}),
            "awaiting_pid_clarification": state.get("awaiting_pid_clarification", False),
            "pid_clarification_question": state.get("pid_clarification_question"),
            "pid_clarification_options": state.get("pid_clarification_options"),

            "open_dashboard": workflow_data.get("open_dashboard", False),
            "sample_input": workflow_data.get("sample_input", ""),
            "standards_applied": workflow_data.get("standards_applied", False),
            # Optimized engineering solution from the parallel solution-build agent (may be None)
            "designed_solution": state.get("designed_solution"),
            "pid_graph": state.get("pid_graph") or (state.get("designed_solution") or {}).get("pid_graph"),
            "agent_path": state.get("agent_path", [])
        }

    # Add changes_made if this was a modification
    if workflow_data.get("changes_made"):
        response["changes_made"] = workflow_data.get("changes_made")

    # Add warnings if any
    if state.get("warnings"):
        response["warnings"] = state.get("warnings")

    # Enforce compliance by calling the standalone HarnessAgent repair function
    from domain.solution.agents.harness_agent import harness_repair_final_response
    state["final_response"] = harness_repair_final_response(response)

    logging.info(f"[SOLUTION_AGENT] Final response built. Intent: {response.get('intent')}, Success: {response.get('success')}")

    return state


# ============================================================================
# CONDITIONAL ROUTING
# ============================================================================

def route_by_intent(state: AgenticSystemState):
    """Route to the correct node(s) based on classified project intent.

    The requirements path routes to the merged comprehensiveness agent (holism
    gate + extraction). ``solution_build`` is gated behind it — it fans out in
    parallel with ``expansion`` only after the gate passes and no saved-project
    offer fired (see ``route_after_episodic_recall``), so no design is ever
    built from unconfirmed/incomplete requirements.
    """
    intent = state.get("workflow_data", {}).get("project_intent", "")
    logging.info(f"[SOLUTION_AGENT] Routing based on intent: {intent}")

    if state.get("error") or intent == "error":
        return "final_response"

    # A pending holistic confirmation owns the next turn: the reply
    # ("go ahead", answers to the gap questions) must reach the holistic
    # agent even when the intent LLM classifies it as clarification/qna — the
    # classifier has no reliable way to recognize a gate reply. Reset and router
    # intents still win so the user can always escape the gate.
    if intent not in ("reset", "reset_confirmed", "reset_cancelled", "router_needed"):
        pending = state.get("workflow_data", {}).get("awaiting_holistic_confirmation", False)
        if not pending:
            try:
                from common.ai.memory import get_holistic_context
                pending = bool(get_holistic_context(
                    state.get("session_id", "default"), user_id=state.get("user_id")
                ).get("stage"))
            except Exception:
                pending = False
        if pending:
            logging.info("[SOLUTION_AGENT] Pending holistic confirmation — overriding intent routing to holistic_agent")
            return "holistic_agent"

    if intent in ("router_needed", "clarification", "reset", "reset_confirmed",
                  "reset_cancelled", "confirm_search", "add_more", "question",
                  "unrelated", "contextual_qna"):
        logging.info(f"[SOLUTION_AGENT] Routing to final_response ({intent})")
        return "final_response"
    if intent == "modification":
        return "modify_instruments"

    # requirements or unknown → run the merged holistic agent (holism
    # gate + extraction). solution_build is deliberately NOT fanned out here:
    # designing a solution from unconfirmed/incomplete requirements contradicts
    # the gate — it fires after the gate passes (see route_after_episodic_recall).
    if intent != "requirements":
        logging.warning(f"[SOLUTION_AGENT] Unknown intent '{intent}', defaulting to requirements flow")
    return "holistic_agent"


def route_after_holistic(state: AgenticSystemState) -> Literal["episodic_recall", "final_response"]:
    """
    Route to the episodic recall check when the merged holistic agent
    produced an extraction (holistic, or user confirmed proceeding despite
    gaps) -- the saved-project offer only fires for COMPLETE requirements --
    otherwise to final_response (clarification questions / confirm prompt /
    error already set on state by holistic_agent_node).
    """
    if state.get("error"):
        logging.info("[SOLUTION_AGENT] Holistic analysis errored -- routing to final_response.")
        return "final_response"
    if state.get("clarification_needed", False):
        logging.info("[SOLUTION_AGENT] Holistic gate triggered -- routing to final_response.")
        return "final_response"
    logging.info("[SOLUTION_AGENT] Holistic analysis complete -- routing to episodic recall check.")
    return "episodic_recall"


def route_after_modification(state: AgenticSystemState) -> Literal["apply_standards", "final_response"]:
    """
    Route to standards application or final response based on skip_standards flag
    after modification processing.

    Args:
        state: Current agentic system state

    Returns:
        Next node name to execute
    """
    skip_standards = state.get("skip_standards", False)

    if skip_standards:
        logging.info("[SOLUTION_AGENT] Skipping standards application after modification (skip_standards=True)")
        return "final_response"
    else:
        logging.info("[SOLUTION_AGENT] Applying standards after modification (skip_standards=False)")
        return "apply_standards"


# ============================================================================
# BUILD LANGGRAPH WORKFLOW
# ============================================================================

