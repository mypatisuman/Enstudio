"""
Search Agent

Handles the complete product search and analysis workflow for procurement recommendations.

This agent:
1. Classifies search intent (new requirements vs workflow continuation)
2. Extracts structured requirements from user input
3. Detects and validates product type
4. Retrieves schema and maps requirements to schema structure
5. Identifies missing mandatory fields and generates validation alerts
6. Searches for products in MongoDB
7. Discovers advanced specifications
8. Performs vendor analysis and matching
9. Generates comprehensive response with validation alerts

Flow:
User Input → Intent Classification → Requirements Extraction → Product Type Detection →
Schema Retrieval & Mapping → Product Search → Specs Discovery → Vendor Analysis → Response
"""

import ast
import json
from common.helpers.json_text import escape_newlines_in_json
from common.helpers.notifications import notify_failure as _notify_failure
import logging
import os
import re
import threading

# Import state and tools
import sys
import traceback
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
# StateGraph moved to domain.search.workflows.search_workflow

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from common.ai.rag import search_vendors_rag  # Direct RAG - much faster!
from common.helpers.node_retry import retryable_node
from domain.orchestrator.state import AgenticSystemState
from common.helpers.response_formatter import (
    standardize_and_convert_response,
)
# Advanced specs discovery now handled by agent
from domain.search.agents.advanced_specs_agent import run_advanced_specs_discovery

# Import deep_analysis_agent functions for product loading
from domain.search.services.product_service import _load_products_from_mongodb_direct, load_pdfs_from_database, load_pdfs_from_urls

# vendor_matcher_tool functionality now handled by deep_analysis_agent
# Import validation agent (replaces deleted tools)
from domain.search.agents.validation_agent import run_validation_agent

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

import logging
logger = logging.getLogger(__name__)

def _load_prompt(filename: str) -> str:
    """Load a prompt file from the prompts directory with graceful fallback."""
    try:
        with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"[SEARCH_AGENT] Prompt file not found: {filename}")
        return ""

# Cached at module import — not re-read on every function call
_SEARCH_AGENT_PROMPT = _load_prompt("search_agent.md")
_SEARCH_MODIFICATION_PROMPT = _load_prompt("update_agent.md")

from common.ai.prompts.response import (
    DISCOVER_MODEL_FAMILIES_PROMPT,
    DISCOVER_TOP_VENDORS_PROMPT,
    SEARCH_FINAL_RESULTS_PROMPT,
    VENDOR_MATCHING_PROMPT,
)
from common.ai.memory import format_conversation_for_prompt, get_search_params_summary
from common.helpers.progress_tracker import progress_tracker
from domain.search.agents.vendor_analysis_agent import run_vendor_analysis
from domain.search.agents.summary_agent import format_summary_for_display, format_summary_for_frontend, generate_summary

logger = logging.getLogger(__name__)


# ============================================================================
# SHARED LLM INSTANCE - Reused across nodes (same as solution agent)
# ============================================================================

from common.ai.llm import get_flash_llm, get_lite_llm

llm_flash = get_flash_llm(temperature=0.1)
llm_flash_lite = get_lite_llm(temperature=0.1)  # Flash-lite for fast, simple tasks

# ============================================================================
# PDF BYTES CACHE — keeps raw binary out of LangGraph serializable state
# Keyed PER WORKFLOW RUN (stream_id, falling back to session_id); populated by
# load_pdf_content, consumed by perform_vendor_analysis.
# THREAD-SAFE: guarded by _pdf_bytes_cache_lock to prevent cross-instance data
# corruption when multiple search agent instances run concurrently.
# ============================================================================
_pdf_bytes_cache: dict = {}
_pdf_bytes_cache_lock = threading.Lock()


def _pdf_cache_key(state: AgenticSystemState) -> str:
    """Cache key for THIS run's PDF bytes.

    stream_id is unique per workflow run, so concurrent instances can never
    collide on it. session_id alone was unsafe: a missing session_id collapsed
    every concurrent instance onto the shared "default" key, letting one
    instance's perform_vendor_analysis steal (pop) another's PDF bytes.
    """
    return state.get("stream_id") or state.get("session_id") or "default"

# ============================================================================
# AGENT NODE FUNCTIONS
# ============================================================================


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _friendly_name(field: str) -> str:
    """camelCase → 'Title Case With Spaces'."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    return spaced.replace("_", " ").title()

def _extract_json(text: str) -> str:
    """Extract first JSON object/array from text"""
    match = re.search(r'(\[.*\]|\{.*\})', text, re.DOTALL)
    if match: return match.group(1)
    return text


# Very common product-type keywords the search catalog supports. Used as a fast
# heuristic so we can launch `run_advanced_specs_discovery` IN PARALLEL with
# validation_agent instead of waiting for validation to canonicalize the type.
# If none match, we skip the parallel call and let the post-validation fallback
# make one advanced-specs request with the canonical product_type.
_QUICK_PRODUCT_HINTS = (
    "pressure gauge", "pressure transmitter", "pressure switch", "pressure relief valve",
    "temperature transmitter", "temperature gauge", "temperature switch", "thermocouple",
    "flow meter", "flow transmitter", "flowmeter", "coriolis", "orifice",
    "level transmitter", "level gauge", "level switch",
    "control valve", "check valve", "ball valve", "gate valve", "globe valve", "butterfly valve",
    "actuator", "positioner", "regulator",
    "instrument stand", "pipe stand",
    "rtd", "sensor", "transmitter", "transducer",
)


def _quick_extract_product_type(user_input: str) -> str:
    """Fast keyword-based product-type guess. Returns '' when unsure.

    This is intentionally best-effort: any miss is corrected by the canonical
    `run_advanced_specs_discovery` fallback call the orchestrator makes after
    validation_agent resolves the true product_type.
    """
    if not user_input:
        return ""
    text = user_input.lower()
    for hint in _QUICK_PRODUCT_HINTS:
        if hint in text:
            return hint.title()
    return ""

def restore_state_from_memory(state: AgenticSystemState) -> AgenticSystemState:
    """
    Seed LangGraph state from unified SearchSessionContext (post-schema retrieval).
    """
    session_id = state.get("session_id")
    if not session_id:
        return state

    workflow_step = state.get("workflow_step", "initialInput")
    if workflow_step == "initialInput":
        return state

    try:
        from domain.search.services.search_session_context import load_search_context

        ctx = load_search_context(session_id, langgraph_state=state if state.get("mapped_requirements") else None)
        if not ctx.mapped_requirements and not ctx.product_type:
            return state

        hydrated = ctx.to_langgraph_state()
        hydrated["change_log"] = ctx.change_log
        hydrated["context_version"] = ctx.version
        for key, val in hydrated.items():
            if val or not state.get(key):
                state[key] = val

        logger.info(
            "[SEARCH_AGENT] Restored search context for session %s (step=%s, version=%s)",
            session_id,
            ctx.workflow_step,
            ctx.version,
        )
    except Exception as e:
        logger.warning(f"[SEARCH_AGENT] restore_state_from_memory failed (non-fatal): {e}")

    return state


@retryable_node(max_attempts=2, label="extract_requirements")
def extract_requirements(state: AgenticSystemState) -> AgenticSystemState:
    """
    Orchestrator node: runs validation_agent and advanced_specs_agent IN PARALLEL,
    then merges their results into the search state.

    HITL removed — this node never pauses the pipeline. Missing mandatory fields
    are still reported (informational) but the workflow always continues.

    Parallel design:
      * Fork 1: `run_validation_agent`  — product type + schema + mapping + standards
      * Fork 2: `run_advanced_specs_discovery` — needs product_type, so it runs a
                short pre-pass (LLM extract) inline via validation? To keep both
                truly parallel, we pass user_input to advanced_specs and let it
                fetch by best-effort product-type extraction. In this codebase
                advanced_specs is keyed by product_type, so we launch it as soon
                as validation resolves the product_type (fast Step 1 of validation).
    """
    if state.get("router_needed"):
        logger.info("[SEARCH_AGENT] extract_requirements skipped — router_needed is set")
        state["skip_full_workflow"] = True
        return state

    state.setdefault("agent_path", []).append("extract_requirements")
    state["agent_path"].append("validation_agent")
    state["agent_path"].append("advanced_specs_agent")

    try:
        stream_id = state.get("stream_id")
        if stream_id:
            progress_tracker.emit(stream_id, "step", {
                "step": "extract_requirements",
                "message": "Parsing Requirements",
                "progress": 10
            })

        user_input = state.get("user_input", "")
        skip_reextract = bool(state.get("skip_reextract"))

        if skip_reextract and state.get("mapped_requirements") and state.get("detected_product_type"):
            logger.info(
                "[SEARCH_AGENT] skip_reextract — reusing stored mapped requirements for finalAnalysis"
            )
            from domain.search.agents.advanced_specs_agent import run_advanced_specs_discovery
            from domain.search.services.schema_merge import (
                apply_merged_extraction_to_state,
                merge_validation_and_advanced,
            )

            pt = state.get("detected_product_type", "")
            advanced_result = None
            try:
                advanced_result = run_advanced_specs_discovery(pt, stream_id=stream_id)
            except Exception as adv_err:
                logger.warning("[SEARCH_AGENT] Advanced specs refresh on proceed failed: %s", adv_err)

            synthetic = {
                "success": True,
                "product_type": pt,
                "detected_schema": state.get("detected_schema", {}),
                "mapped_requirements": state.get("mapped_requirements", {}),
                "provided_requirements": state.get("provided_requirements", {}),
                "unmapped_specs": state.get("unmapped_specs", {}),
                "specified_vendors": state.get("specified_vendors", []),
                "specified_model_families": state.get("specified_model_families", []),
                "applicable_standards": state.get("applicable_standards", []),
                "schema_source": state.get("schema_source", ""),
                "validation_alert": state.get("validation_alert"),
                "input_range": state.get("input_range", "mid"),
            }
            merged = merge_validation_and_advanced(synthetic, advanced_result)
            apply_merged_extraction_to_state(state, merged)
            return state

        logger.info(f"[SEARCH_AGENT] Running validation + advanced_specs agents in parallel for: {user_input[:100]}...")

        # ── PARALLEL EXECUTION ─────────────────────────────────────────────
        # Both agents are launched concurrently. Advanced specs needs a
        # product_type; we pre-detect it with a cheap heuristic (first noun
        # phrase / product hint) so both can truly run in parallel. If the
        # heuristic misses, we fall back to a second advanced_specs call after
        # validation resolves the canonical product_type below.
        skip_standard_rag = state.get("skip_standards", False)
        user_id = state.get("user_id")

        from domain.search.services.schema_merge import (
            apply_merged_extraction_to_state,
            run_parallel_requirements_extraction,
        )

        pre_product_type = state.get("detected_product_type") or state.get("product_type") or _quick_extract_product_type(user_input)
        logger.info(f"[SEARCH_AGENT] Pre-extracted product_type for parallel advanced-specs fetch: {pre_product_type!r}")

        result = run_parallel_requirements_extraction(
            user_input,
            pre_product_type=pre_product_type,
            skip_standard_rag=skip_standard_rag,
            user_id=user_id,
            stream_id=stream_id,
        )

        logger.info(
            f"[5TIER_AUDIT][extract_requirements] schema_source={result.get('schema_source')!r} "
            f"product_type={result.get('product_type')!r} "
            f"mandatory_fields={len(result.get('mapped_requirements', {}).get('mandatoryRequirements', {}))} "
            f"optional_fields={len(result.get('mapped_requirements', {}).get('optionalRequirements', {}))} "
            f"advanced_fields={len(result.get('mapped_requirements', {}).get('advancedRequirements', {}))} "
            f"standards_count={len(result.get('applicable_standards', []))} "
            f"advanced_specs_count={len(result.get('advanced_specs', []))} "
            f"source={'5-tier Restructured DB' if result.get('schema_source') not in ('not_found', 'none', 'error') else 'NOT from 5-tier'}"
        )

        if not state.get("workflow_data"):
            state["workflow_data"] = {}
        state["workflow_data"]["input_range"] = result.get("input_range", "mid")
        apply_merged_extraction_to_state(state, result)

        if result.get("success") and state.get("workflow_step") != "finalAnalysis":
            from domain.search.services.schema_merge import commit_context_after_extraction
            commit_context_after_extraction(
                state.get("session_id", ""),
                result,
                workflow_step="awaitAllSpecs",
                user_input=user_input,
            )

        if result.get("success"):
            logger.info(f"[SEARCH_AGENT] Validation complete. Product type: {state['detected_product_type']}")
            logger.info(f"[SEARCH_AGENT] Missing fields: {state['missing_mandatory_fields']}")
        else:
            # Check if it's a product not found scenario
            if result.get("schema_source") == "not_found":
                logger.warning(f"[SEARCH_AGENT] Product type not found: {state['detected_product_type']}")
                state["error_message"] = f"Product type '{state['detected_product_type']}' not found in database"
                state["product_not_found"] = True  # Flag for workflow routing

                # Notify admin of "product not found" scenario
                _notify_failure("Product Not Found",
                    f"User searched for '{state['detected_product_type']}' which does not exist in the schema database.",
                    state, user_input=user_input)
            else:
                logger.error(f"[SEARCH_AGENT] Validation failed: {result.get('error')}")
                state["error_message"] = result.get('error', 'Validation failed')

                # Notify admin of validation failure
                _notify_failure("Validation Agent Failed",
                    f"Validation failed: {state['error_message']}",
                    state, user_input=user_input)

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Error in validation: {e}")
        state["error_message"] = f"Validation error: {str(e)}"

        # Send notification for validation processing error
        _notify_failure("Validation Processing",
            f"Validation processing error: {str(e)}",
            state, input=state.get("user_input", "N/A"), error=str(e))

    return state


@retryable_node(max_attempts=2, label="detect_product_type")
def detect_product_type(state: AgenticSystemState) -> AgenticSystemState:
    """
    Detect and validate product type from user input using validation agent.
    This node runs validation agent which handles:
    - Product type detection and normalization
    - Schema retrieval and mapping
    - Missing field identification
    - Standards integration
    """
    state.setdefault("agent_path", []).append("detect_product_type")
    
    detected_product_type = state.get('detected_product_type')
    
    # Run standard validation check
    if not state.get("schema_validated"):
        if not detected_product_type:
            logger.error("[SEARCH_AGENT] No product type detected - cannot proceed with search")
            state["error_message"] = "Product type detection failed - cannot proceed with search"
            return state
        logger.info(f"[SEARCH_AGENT] Product type detected: {detected_product_type}")
    else:
        if not detected_product_type:
            logger.error("[SEARCH_AGENT] Schema validated but no product_type found - this should not happen")
            state["error_message"] = "Product type detection failed - cannot proceed with search"
            return state
        logger.info(f"[SEARCH_AGENT] Schema already validated for: {detected_product_type}")
        
    # Hook: vendor-data presence check (best-effort self-healing — must never
    # break the search flow). Counts vendor products in the 5-tier hierarchy;
    # only when that is zero checks the flat vendors collection AND datasheet
    # PDFs in documents. When the flat count is 0 OR no PDFs exist, records the
    # miss for auditing and triggers the category scraper (which enforces the
    # failed-cooldown circuit breaker and a per-type indexing lock itself).
    if detected_product_type:
        try:
            from domain.search.services.category_scraper import (
                assess_vendor_data_presence,
                scrape_and_ingest_category_data,
            )
            from common.infra.repositories.missing_product_type_repository import MissingProductTypeRepository

            logger.info(
                f"[AUTO_INDEX] ===== Vendor-data presence check (detect_product_type) "
                f"for '{detected_product_type}' ====="
            )
            presence = assess_vendor_data_presence(detected_product_type)
            logger.info(
                f"[AUTO_INDEX] Presence counts for '{detected_product_type}': "
                f"hierarchy_products={presence['hierarchy_count']} "
                f"flat_vendor_products={presence['flat_vendor_count']} "
                f"datasheet_pdfs={presence['pdf_count']}"
            )

            if not presence["should_scrape"]:
                logger.info(
                    f"[AUTO_INDEX] NOT TRIGGERED (vendor level) for '{detected_product_type}' — "
                    f"vendor data already present in the database"
                )
            else:
                logger.info(
                    f"[AUTO_INDEX] Miss recorded in missing_product_types for "
                    f"'{detected_product_type}' — {presence['reason']}"
                )
                MissingProductTypeRepository.record_missing_product_type(
                    detected_product_type,
                    reason=presence["reason"],
                    user_query=state.get("user_input"),
                    details={
                        "has_schema": bool(state.get("schema_validated")),
                        "has_pdfs": bool(presence["pdf_count"]),
                        "has_vendor_models": bool(presence["flat_vendor_count"]),
                    },
                )
                if MissingProductTypeRepository.is_in_failed_cooldown(detected_product_type):
                    logger.info(
                        f"[AUTO_INDEX] SKIPPED (vendor level) for '{detected_product_type}' — "
                        f"last indexing attempt failed, 24h cooldown active"
                    )
                else:
                    logger.info(
                        f"[AUTO_INDEX] TRIGGERED (vendor level) for '{detected_product_type}' — "
                        f"starting category scrape (max_pdfs=2)..."
                    )
                    scrape_result = scrape_and_ingest_category_data(detected_product_type, max_pdfs=2)
                    logger.info(
                        f"[AUTO_INDEX] Vendor scrape finished for '{detected_product_type}': "
                        f"success={scrape_result.get('success')} "
                        f"models_inserted={scrape_result.get('total_models_inserted', 0)} "
                        f"message={scrape_result.get('message')!r}"
                    )
        except Exception as scrape_err:
            logger.error(
                f"[AUTO_INDEX] Vendor-data hook ERROR for '{detected_product_type}' "
                f"(non-fatal, search continues): {scrape_err}"
            )

    return state


@retryable_node(max_attempts=2, label="validate_and_map_schema")
def validate_and_map_schema(state: AgenticSystemState) -> AgenticSystemState:
    """
    Schema validation and mapping is now handled by validation_agent in extract_requirements.
    This node is kept for workflow compatibility but does no additional work.
    """
    state.setdefault("agent_path", []).append("validate_and_map_schema")
    logger.info(f"[SEARCH_AGENT] Schema already validated for: {state.get('detected_product_type', 'N/A')}")
    logger.info(f"[SEARCH_AGENT] Missing mandatory fields: {len(state.get('missing_mandatory_fields', []))}")
    return state


@retryable_node(max_attempts=2, label="classify_search_intent")
def classify_search_intent(state: AgenticSystemState) -> AgenticSystemState:
    """
    Classify the user's search intent for workflow step management.
    Determines if user is providing new requirements or continuing workflow.
    Uses inline LLM classification (same pattern as solution agent).

    This is the ORCHESTRATOR that decides:
    - What type of intent (productRequirements, modification, workflow, clarification, etc.)
    - What the next workflow step should be
    - Whether to route to different agents or continue
    """
    try:
        state.setdefault("agent_path", []).append("search_intent")

        # Emit progress event whenever we have a stream_id
        stream_id = state.get("stream_id")
        if stream_id:
            progress_tracker.emit(stream_id, "step", {
                "step": "classify_search_intent",
                "message": "Classifying Intent",
                "progress": 5
            })

        # ── DETERMINISTIC FAST-PATH: dispatcher-resolved finalAnalysis ──────
        # The /api/search-agent proceed gate already confirmed the user's
        # intent and dispatched this run with proceed_confirmed=True and
        # workflow_step=finalAnalysis. Re-classifying the composed
        # requirements payload with the LLM is non-deterministic: it sometimes
        # reads the spec dump as a "modification", which ends the workflow at
        # the sidebar edit loop WITHOUT running vendor analysis and returns
        # "no products found" to the user. The dispatcher's decision is
        # authoritative — skip the LLM entirely.
        if state.get("proceed_confirmed") and state.get("workflow_step") == "finalAnalysis":
            logger.info(
                "[SEARCH_AGENT] finalAnalysis dispatch with proceed_confirmed — "
                "skipping LLM intent classification (deterministic workflow intent)"
            )
            state["search_intent"] = "workflow"
            state["next_workflow_step"] = "finalAnalysis"
            state["resume_workflow"] = True
            state["stay_at_step"] = False
            state["intent_confidence"] = "high"
            state["intent_reasoning"] = "Deterministic: dispatcher resolved proceed → finalAnalysis"
            state["has_prior_search"] = True
            return state

        logger.info("[SEARCH_AGENT] Classifying search intent...")

        user_input = state.get("user_input", "")
        current_step = state.get("workflow_step", "") or "initialInput"
        current_intent = state.get("current_intent", "") or "productRequirements"

        # Log current workflow context
        logger.info(f"[SEARCH_AGENT] Current workflow step: {current_step}")
        logger.info(f"[SEARCH_AGENT] Current intent: {current_intent}")

        # Use module-level cached prompt (loaded once at import, not on every call)
        SEARCH_AGENT_PROMPT = _SEARCH_AGENT_PROMPT

        # Build classification chain using shared Flash LLM
        classification_chain = (
            ChatPromptTemplate.from_template(SEARCH_AGENT_PROMPT)
            | llm_flash
            | StrOutputParser()
        )

        # Load user dynamic memory profile
        user_id = state.get("user_id")
        pref_context = ""
        if user_id:
            try:
                from common.ai.memory.hybrid_memory_manager import load_hybrid_memory, format_profile_for_injection
                profile = load_hybrid_memory(user_id)
                state["user_interest_description"] = profile.get("generated_description", "")
                pref_context = format_profile_for_injection(user_id)
                if pref_context:
                    logger.info(f"[SEARCH_AGENT] Loaded user dynamic memory profile for user {user_id}")
            except Exception as e:
                logger.warning(f"[SEARCH_AGENT] Error loading user dynamic memory profile in classify_search_intent: {e}")

        # Get conversation history for context
        session_id = state.get("session_id")
        conversation_history = format_conversation_for_prompt(session_id, include_metadata=True) if session_id else "None"
        search_history_summary = get_search_params_summary(session_id, max_searches=3) if session_id else "None"

        # Construct Explicit Metadata about current search state
        from domain.search.services.search_session_context import load_search_context

        ctx = load_search_context(session_id, langgraph_state=state) if session_id else None
        # Deterministic "does a real prior search already exist for this session"
        # signal — used below (and by route_after_intent) to stop the classifier's
        # own text-pattern guess from routing a fresh, no-prior-search turn into
        # the modification/update_agent path (which then fails with "I don't have
        # a previous search to modify" once it discovers there's nothing to update).
        has_prior_search = bool(ctx and (ctx.mapped_requirements or ctx.product_type))
        state["has_prior_search"] = has_prior_search
        active_product_type = state.get("detected_product_type", "") or (ctx.product_type if ctx else "")
        active_missing = state.get("missing_mandatory_fields", []) or (ctx.missing_mandatory_fields if ctx else [])
        active_reqs = state.get("structured_requirements", {})
        active_results = state.get("ranked_products", [])

        state_metadata = "[METADATA] Current Search State:\n"
        if pref_context:
            state_metadata = f"{pref_context}\n\n{state_metadata}"
        if ctx and ctx.mapped_requirements:
            state_metadata += ctx.summary_for_intent() + "\n"
        elif active_product_type:
            state_metadata += f"- Product Type: {active_product_type}\n"
        if active_reqs and not ctx:
            state_metadata += f"- Requirements: {len(active_reqs)} gathered\n"
        if active_missing and not ctx:
            state_metadata += f"- Missing Fields: {', '.join(active_missing)}\n"
        if active_results:
            state_metadata += f"- Search Results: {len(active_results)} products ranked\n"

        # Append state metadata to conversation history
        if conversation_history != "None":
            conversation_history += f"\n\n{state_metadata}"
        else:
            conversation_history = state_metadata

        # Cap the history fed to the intent classifier. Long parallel sessions
        # were feeding 500KB+ of history into every classification — enormous
        # token cost/latency and a major driver of misclassification. Keep the
        # TAIL (most recent turns + the state metadata appended above).
        _max_hist = int(os.getenv("INTENT_HISTORY_MAX_CHARS", "12000"))
        if len(conversation_history) > _max_hist:
            logger.info(
                f"[SEARCH_AGENT] Truncating classifier history: {len(conversation_history)} → {_max_hist} chars"
            )
            conversation_history = (
                "[...earlier conversation truncated...]\n" + conversation_history[-_max_hist:]
            )

        # Escape curly braces for ChatPromptTemplate
        conversation_history = conversation_history.replace("{", "{{").replace("}", "}}")
        search_history_summary = search_history_summary.replace("{", "{{").replace("}", "}}")

        logger.info(f"[SEARCH_AGENT] Using conversation history: {len(conversation_history)} chars")

        # Execute classification
        classification_response = classification_chain.invoke({
            "user_input": user_input,
            "current_step": current_step or "initialInput",
            "current_intent": current_intent or "productRequirements",
            "search_history_summary": search_history_summary,
            "conversation_history": conversation_history
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

        logger.info(f"[SEARCH_AGENT] Intent response to parse: {cleaned_response[:200]}...")

        # Preprocess JSON to handle literal control characters inside string values
        cleaned_response = escape_newlines_in_json(cleaned_response)

        try:
            result = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            logger.warning(f"[SEARCH_AGENT] JSON parse error: {e}. Trying ast.literal_eval...")
            try:
                result = ast.literal_eval(cleaned_response)
                if not isinstance(result, dict):
                    raise ValueError("Parsed content is not a dictionary")
            except Exception as e2:
                logger.error(f"[SEARCH_AGENT] Failed to parse response with both json and ast: {e2}")
                raise e

        # Store classification results
        intent_type = result.get("type", result.get("intent", "productRequirements"))
        state["search_intent"] = intent_type
        state["next_workflow_step"] = result.get("next_step")
        state["resume_workflow"] = result.get("resume_workflow", True)
        state["stay_at_step"] = result.get("stay_at_step", False)
        state["intent_confidence"] = result.get("confidence", "medium")
        state["intent_reasoning"] = result.get("reasoning", "")

        logger.info(f"[SEARCH_AGENT] Intent: {state['search_intent']}, Next step: {state['next_workflow_step']}, Confidence: {state['intent_confidence']}")
        logger.info(f"[SEARCH_AGENT] Reasoning: {state['intent_reasoning']}")

        # Deterministic proceed vs spec-edit routing (overrides LLM at sidebar steps).
        from domain.search.services.proceed_gate import resolve_sidebar_chat_action

        sidebar_action = resolve_sidebar_chat_action(user_input, current_step or "")
        if sidebar_action == "proceed":
            logger.info("[SEARCH_AGENT] Proceed gate → workflow/finalAnalysis")
            state["search_intent"] = "workflow"
            state["next_workflow_step"] = "finalAnalysis"
            state["workflow_step"] = "finalAnalysis"
            state["proceed_confirmed"] = True
        elif sidebar_action == "spec_edit" and has_prior_search:
            logger.info("[SEARCH_AGENT] Spec-edit gate → modification/awaitAllSpecs")
            state["search_intent"] = "modification"
            state["next_workflow_step"] = "awaitAllSpecs"
            state["proceed_confirmed"] = False
        elif sidebar_action == "spec_edit" and not has_prior_search:
            logger.info("[SEARCH_AGENT] Spec-edit gate suppressed — no prior search exists, treating as fresh productRequirements")
            intent_type = "productRequirements"
            state["search_intent"] = "productRequirements"
            state["next_workflow_step"] = "initialInput"
            state["proceed_confirmed"] = False
        elif (current_step or "") == "awaitAllSpecs" and intent_type == "productRequirements" and has_prior_search:
            logger.info("[SEARCH_AGENT] productRequirements at awaitAllSpecs → treating as modification")
            intent_type = "modification"
            state["search_intent"] = "modification"
            state["proceed_confirmed"] = False

        # Safety net: the LLM classifier judges new-vs-modify purely from input
        # text/conversation-history reading, with no guaranteed access to a hard
        # existence check. If it (or a stale current_step) still landed on
        # "modification" with no real prior search in this session, there is
        # nothing to modify — treat it as a fresh request instead of letting it
        # reach update_agent, which would otherwise fail with a generic
        # "I don't have a previous search to modify" message.
        if intent_type == "modification" and not has_prior_search:
            logger.info("[SEARCH_AGENT] Modification intent with no prior search — downgrading to productRequirements")
            intent_type = "productRequirements"
            state["search_intent"] = "productRequirements"

        # ================================================================
        # HANDLE RESET INTENTS
        # ================================================================
        if intent_type in ["reset", "reset_confirmed", "reset_cancelled"]:
            logger.info(f"[SEARCH_AGENT] Reset intent detected: {intent_type}")
            state["reset_intent"] = intent_type
            state["response_message"] = result.get("message", "")
            return state

        # ================================================================
        # HANDLE CLARIFICATION INTENT — HITL removed
        # Instead of pausing to ask the user, we treat it as productRequirements
        # and let the parallel validation + advanced_specs pipeline run with
        # whatever data was extracted.
        # ================================================================
        if intent_type == "clarification":
            logger.info("[SEARCH_AGENT] Clarification intent — HITL disabled, proceeding as productRequirements")
            intent_type = "productRequirements"
            state["search_intent"] = "productRequirements"
            state["clarification_needed"] = False

        # ================================================================
        # HANDLE CONTEXTUAL QNA INTENT
        # ================================================================
        if intent_type == "contextual_qna":
            logger.info("[SEARCH_AGENT] Contextual QNA - answering question directly from LLM")
            state["response_message"] = result.get("message", "I'm checking the current search results for you.")
            return state

        # ================================================================
        # HANDLE ROUTER_NEEDED INTENT - Call router classifier
        # ================================================================
        if intent_type == "router_needed":
            logger.info("[SEARCH_AGENT] Input is not search-related - calling router classifier")

            # Import router classifier
            from domain.orchestrator.agents.router_classifier_agent import router_classifier_node

            # Call router classifier with current state
            router_state = router_classifier_node(state)

            # Store router results for response generation
            state["router_needed"] = True
            state["router_category"] = router_state.get("route_category")
            state["router_target_page"] = router_state.get("target_page")
            state["router_requires_routing"] = router_state.get("requires_routing")
            state["router_url"] = router_state.get("routing_url", "")
            state["router_message"] = router_state.get("routing_message") or router_state.get("direct_response", "")
            state["response_message"] = state["router_message"]

            # Store confirmation fields
            state["router_requires_confirmation"] = router_state.get("requires_confirmation", True)
            state["router_confirmation_message"] = router_state.get("confirmation_message", "")
            state["router_opening_message"] = router_state.get("opening_message", "")
            state["router_decline_message"] = router_state.get("decline_message", "")
            state["router_popup_blocked_message"] = router_state.get("popup_blocked_message", "")

            logger.info(f"[SEARCH_AGENT] Router classified as: {router_state.get('route_category')} → {router_state.get('target_page')}")

    except Exception as e:
        error_str = str(e)
        # Azure content filter false-positives: retry classification with neutral framing
        # so the LLM prompt can still determine the correct intent dynamically.
        is_content_filter = (
            "content_filter" in error_str or
            "ResponsibleAIPolicyViolation" in error_str or
            "jailbreak" in error_str
        )
        if is_content_filter:
            logger.warning(f"[SEARCH_AGENT] Azure content filter triggered — retrying with neutral framing")
            try:
                neutral_input = (
                    f"A user in an industrial automation search application sent the following message "
                    f"(classify their intent): \"{state.get('user_input', '')}\""
                )
                neutral_chain = (
                    ChatPromptTemplate.from_template(_SEARCH_AGENT_PROMPT)
                    | llm_flash
                    | StrOutputParser()
                )
                neutral_response = neutral_chain.invoke({
                    "user_input": neutral_input,
                    "current_step": state.get("workflow_step", "initialInput") or "initialInput",
                    "current_intent": state.get("current_intent", "productRequirements") or "productRequirements",
                    "search_history_summary": "None",
                    "conversation_history": f"[METADATA] Current workflow step: {state.get('workflow_step', 'initialInput')}"
                })
                cleaned = neutral_response.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                cleaned = escape_newlines_in_json(cleaned)
                result = json.loads(cleaned)
                intent_type = result.get("type", result.get("intent", "productRequirements"))
                state["search_intent"] = intent_type
                state["next_workflow_step"] = result.get("next_step")
                state["resume_workflow"] = result.get("resume_workflow", True)
                state["stay_at_step"] = result.get("stay_at_step", False)
                state["intent_confidence"] = result.get("confidence", "medium")
                state["intent_reasoning"] = result.get("reasoning", "")
                if intent_type in ["reset", "reset_confirmed", "reset_cancelled"]:
                    state["reset_intent"] = intent_type
                    state["response_message"] = result.get("message", "")
                elif intent_type == "clarification":
                    logger.info("[SEARCH_AGENT] Neutral retry classified as clarification — HITL disabled, proceeding")
                    state["search_intent"] = "productRequirements"
                    state["clarification_needed"] = False
                elif intent_type == "contextual_qna":
                    state["contextual_qna"] = True
                    state["response_message"] = result.get("message", "")
                logger.info(f"[SEARCH_AGENT] Neutral retry succeeded — intent: {intent_type}")
                return state
            except Exception as retry_err:
                logger.error(f"[SEARCH_AGENT] Neutral retry also failed: {retry_err}")

        logger.exception(f"[SEARCH_AGENT] Error in intent classification: {e}")
        # Default to product requirements intent
        state["search_intent"] = "productRequirements"
        state["next_workflow_step"] = "initialInput"
        state["resume_workflow"] = True
        state["intent_confidence"] = "low"

        # Send notification for intent classification error
        _notify_failure("Intent Classification",
            f"Search intent classification failed: {str(e)}",
            state, input=state.get("user_input", "N/A"), error=str(e))

    # HITL removed: we no longer set awaitAllSpecs / showSummary / finalAnalysis
    # triggers here. Every productRequirements / workflow / modification intent
    # flows straight into the full parallel pipeline in extract_requirements.
    return state


@retryable_node(max_attempts=2, label="load_pdf_content")
def load_pdf_content(state: AgenticSystemState) -> AgenticSystemState:
    """
    Load PDF content from Azure Blob Storage (via MongoDB documents collection) for filtered vendors.
    This provides datasheet content for vendor analysis.
    """
    state.setdefault("agent_path", []).append("load_pdf_content")
    session_id = state.get("session_id", "default")
    stream_id = state.get("stream_id")

    logger.info(
        f"[SEARCH_AGENT][load_pdf_content] ENTER — session_id={session_id!r} "
        f"stream_id={stream_id!r} "
        f"thread={threading.current_thread().name} "
        f"cache_keys_before={list(_pdf_bytes_cache.keys())}"
    )

    try:
        # Emit progress
        if stream_id:
            progress_tracker.emit(stream_id, "step", {
                "step": "load_pdf_content",
                "message": "Loading Datasheets",
                "progress": 50
            })

        logger.info("[SEARCH_AGENT] Loading PDF content for filtered vendors...")

        # Get vendors to load PDFs for
        vendors_to_load = state.get("filtered_vendors") or state.get("specified_vendors") or []

        logger.info(
            f"[SEARCH_AGENT][load_pdf_content] vendors_to_load={vendors_to_load} "
            f"product_type={state.get('detected_product_type')!r}"
        )

        if not vendors_to_load:
            logger.warning("[SEARCH_AGENT][load_pdf_content] No vendors specified for PDF loading — skipping")
            state["pdf_content_json"] = "{}"
            state["pdf_content"] = {}
            state["vendors_with_pdfs"] = []
            state["vendors_without_pdfs"] = []
            return state

        logger.info(
            f"[5TIER_AUDIT][load_pdf_content] products_json_present={bool(state.get('products_json'))} "
            f"products_count={len(json.loads(state['products_json'])) if state.get('products_json') else 0} "
            f"vendors_to_load={vendors_to_load}"
        )

        # Build vendor→[url] map from 5-tier products already loaded by identify_vendors_agent
        _tier_vendor_urls: dict[str, list[str]] = {}
        _products_json = state.get("products_json")
        if _products_json:
            try:
                for _p in json.loads(_products_json):
                    _v = _p.get("vendor") or _p.get("vendor_name", "")
                    _u = _p.get("datasheet_url", "")
                    if _v and _u and _v in vendors_to_load:
                        _tier_vendor_urls.setdefault(_v, []).append(_u)
            except Exception as _parse_err:
                logger.warning(f"[SEARCH_AGENT][load_pdf_content] Could not parse products_json for URL map: {_parse_err}")

        if _tier_vendor_urls:
            logger.info(
                f"[5TIER_AUDIT][load_pdf_content] PDF_SOURCE=5-tier-L4-datasheet_url "
                f"vendors={list(_tier_vendor_urls.keys())} "
                f"total_urls={sum(len(v) for v in _tier_vendor_urls.values())} "
                f"db=Restructured collection=L4 field=datasheet_url"
            )
            result = load_pdfs_from_urls(_tier_vendor_urls)
            if not result.get("pdf_content") and not result.get("pdf_bytes"):
                logger.warning(
                    f"[5TIER_AUDIT][load_pdf_content] PDF_SOURCE=FALLBACK-flat-documents "
                    f"reason=5-tier URLs returned no PDFs "
                    f"db=product-recommender collection=documents"
                )
                result = load_pdfs_from_database(
                    product_type=state.get("detected_product_type"),
                    filtered_vendors=vendors_to_load
                )
            else:
                logger.info(
                    f"[5TIER_AUDIT][load_pdf_content] PDF_SOURCE=5-tier-L4 SUCCESS "
                    f"vendors_with_pdfs={result.get('vendors_with_pdfs', [])} "
                    f"total_loaded={result.get('total_loaded', 0)}"
                )
        else:
            logger.warning(
                f"[5TIER_AUDIT][load_pdf_content] PDF_SOURCE=FALLBACK-flat-documents "
                f"reason=no datasheet_url in L4 products "
                f"db=product-recommender collection=documents"
            )
            result = load_pdfs_from_database(
                product_type=state.get("detected_product_type"),
                filtered_vendors=vendors_to_load
            )

        if result.get("success"):
            pdf_bytes = result.get("pdf_bytes", {})
            logger.info(
                f"[SEARCH_AGENT][load_pdf_content] PDF load SUCCESS — "
                f"total_loaded={result.get('total_loaded', 0)} "
                f"vendors_with_pdfs={result.get('vendors_with_pdfs', [])} "
                f"raw_bytes_vendors={list(pdf_bytes.keys())}"
            )
            state["pdf_content_json"] = result.get("pdf_content_json", "{}")
            state["pdf_content"] = result.get("pdf_content", {})        # extracted text per vendor
            state["vendors_with_pdfs"] = result.get("vendors_with_pdfs", [])
            state["vendors_without_pdfs"] = result.get("vendors_without_pdfs", [])
            # Store raw bytes in module cache — NOT in state (prevents binary flooding logs)
            # THREAD-SAFE: lock prevents two concurrent runs overwriting each other.
            # Keyed per run (stream_id) so parallel instances can never collide.
            cache_key = _pdf_cache_key(state)
            with _pdf_bytes_cache_lock:
                existing_keys = list(_pdf_bytes_cache.keys())
                if cache_key in _pdf_bytes_cache:
                    logger.warning(
                        f"[SEARCH_AGENT][load_pdf_content] CONCURRENT COLLISION — "
                        f"cache_key={cache_key!r} already present in cache. "
                        f"This means two load_pdf_content calls are running for the same run. "
                        f"Existing cache will be OVERWRITTEN. Existing keys: {existing_keys}"
                    )
                _pdf_bytes_cache[cache_key] = pdf_bytes
                logger.info(
                    f"[SEARCH_AGENT][load_pdf_content] cache WRITE — "
                    f"cache_key={cache_key!r} session_id={session_id!r} "
                    f"bytes_vendors={list(pdf_bytes.keys())} "
                    f"all_cache_keys={list(_pdf_bytes_cache.keys())}"
                )
        else:
            logger.warning(
                f"[SEARCH_AGENT][load_pdf_content] PDF loading FAILED: {result.get('message')} — "
                f"continuing without PDFs (vendor text-based analysis only)"
            )
            state["pdf_content_json"] = "{}"
            state["pdf_content"] = {}
            state["vendors_with_pdfs"] = []
            state["vendors_without_pdfs"] = []

    except Exception as e:
        logger.exception(
            f"[SEARCH_AGENT][load_pdf_content] EXCEPTION — "
            f"session_id={session_id!r} error={e!r} "
            f"type={type(e).__name__}"
        )
        state["pdf_content_json"] = "{}"
        state["pdf_content"] = {}
        state["vendors_with_pdfs"] = []
        state["vendors_without_pdfs"] = []

    logger.info(
        f"[SEARCH_AGENT][load_pdf_content] EXIT — "
        f"session_id={session_id!r} "
        f"pdf_content_vendors={list(state.get('pdf_content', {}).keys())} "
        f"cache_keys_after={list(_pdf_bytes_cache.keys())}"
    )
    # Return full state — returning a partial dict here drops all other state keys
    # (e.g. agent_path, session_id, products_json) and corrupts downstream nodes.
    return state


def discover_specs(state: AgenticSystemState) -> AgenticSystemState:
    """
    Discover advanced specifications using agent.
    Fetches optional fields from MongoDB schema only.
    """
    state.setdefault("agent_path", []).append("discover_specs")
    state["agent_path"].append("advanced_specs_agent")
    try:
        # Emit progress
        stream_id = state.get("stream_id")
        if stream_id:
            progress_tracker.emit(stream_id, "step", {
                "step": "discover_specs",
                "message": "Discovering Specs",
                "progress": 50
            })

        logger.info("[SEARCH_AGENT] Discovering advanced specifications...")

        product_type = state.get("detected_product_type")
        result = run_advanced_specs_discovery(product_type, stream_id=stream_id)

        if result.get("has_advanced_specs"):
            state["advanced_specs"] = result.get("advanced_specs", [])
            state["advanced_specs_message"] = result.get("response_message", "")
            state["advanced_specs_action"] = result.get("action", "show_specs")
            logger.info(f"[SEARCH_AGENT] Found {len(result['advanced_specs'])} advanced specs")
        else:
            state["advanced_specs"] = []
            state["advanced_specs_message"] = result.get("response_message", "")
            state["advanced_specs_action"] = result.get("action", "proceed_to_search")
            logger.info("[SEARCH_AGENT] No advanced specs available")

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Error in specs discovery: {e}")
        state["advanced_specs"] = []
        state["advanced_specs_message"] = "Could not retrieve advanced specifications."
        state["advanced_specs_action"] = "proceed_to_search"

        # Notify admin of the error in specs discovery
        _notify_failure("Discover Advanced Specs",
            f"Error in specs discovery: {str(e)}",
            state, detected_product_type=state.get("detected_product_type"))

    return {
        "advanced_specs": state.get("advanced_specs", []),
        "advanced_specs_message": state.get("advanced_specs_message", ""),
        "advanced_specs_action": state.get("advanced_specs_action", "proceed_to_search")
    }


def format_requirements(state: AgenticSystemState) -> AgenticSystemState:
    """
    Format collected requirements into human-readable summary.
    This provides a clear, structured summary before product search and analysis.
    """
    try:
        logger.info("[SEARCH_AGENT] Formatting requirements summary...")

        # Compose requirements string from all collected data
        requirements_parts = []

        # Add mapped requirements
        mapped_requirements = state.get("mapped_requirements")
        if mapped_requirements:
            for field, value in mapped_requirements.items():
                if value:
                    field_friendly = field.replace('_', ' ').title()
                    requirements_parts.append(f"{field_friendly}: {value}")

        # Add advanced specs if discovered
        advanced_specs = state.get("advanced_specs")
        if advanced_specs and isinstance(advanced_specs, list):
            if advanced_specs:
                requirements_parts.append("\nAdvanced Specifications:")
                for spec in advanced_specs:
                    if isinstance(spec, dict):
                        spec_name = spec.get('field', spec.get('name', spec.get('key', '')))
                        requirements_parts.append(f"{spec_name}")

        # Combine all requirements into string
        requirements_text = "\n".join(requirements_parts)

        if not requirements_text.strip():
            logger.warning("[SEARCH_AGENT] No requirements to format")
            state["formatted_requirements_summary"] = "No requirements collected yet."
            return state

        # Format requirements inline (replaces requirements_formatter_tool)
        state["formatted_requirements_summary"] = requirements_text
        logger.info("[SEARCH_AGENT] Requirements formatted successfully (inline)")

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Error formatting requirements: {e}")
        # Not critical - use raw requirements as fallback
        state["formatted_requirements_summary"] = "Error formatting requirements."

    return state


def generate_search_summary(state: AgenticSystemState) -> AgenticSystemState:
    """
    Generate a comprehensive summary of all search parameters collected so far.
    This can be triggered at any point in the workflow to show the user what data has been collected.
    """
    try:
        logger.info("[SEARCH_AGENT] Generating search summary...")

        session_id = state.get("session_id", "")
        stream_id = state.get("stream_id")  # FIX: was referencing undefined outer `stream_id`

        # Generate summary using summary agent
        # Only pass workflow_step - show ONLY user-provided specs, no metadata
        summary_data = generate_summary(
            session_id=session_id,
            additional_context={
                "workflow_step": state.get("workflow_step", "unknown")
            },
            stream_id=stream_id
        )

        # Store summary in state
        state["summary_data"] = summary_data
        state["summary_display"] = format_summary_for_display(summary_data)
        state["summary_frontend"] = format_summary_for_frontend(summary_data)

        # Set response message
        state["llm_generated_response"] = state["summary_display"]
        state["skip_full_workflow"] = True  # Stop after showing summary

        logger.info("[SEARCH_AGENT] Summary generated successfully")
        return state

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Error generating summary: {e}")
        state["error_message"] = f"Failed to generate summary: {str(e)}"
        return state


def _degrade_vendor_analysis(state: AgenticSystemState, exc: BaseException) -> AgenticSystemState:
    """Graceful degradation for vendor analysis: once retries are exhausted (or on a
    non-transient failure), continue the pipeline with no matched products plus a
    user-visible warning, instead of aborting the whole search."""
    logger.error(f"[SEARCH_AGENT] Vendor analysis degraded after retries: {exc}")
    # Retries are over — free this run's PDF bytes so the per-run cache
    # entry doesn't leak (success path cleans up in perform_vendor_analysis).
    with _pdf_bytes_cache_lock:
        _pdf_bytes_cache.pop(_pdf_cache_key(state), None)
    _notify_failure("Search Agent - Deep Analysis",
                    f"Deep analysis failed: {exc}",
                    state, session_id=state.get("session_id"))
    state["error_message"] = f"Deep analysis failed: {exc}"
    state["ranked_products"] = []
    state["deep_analysis_complete"] = False
    state.setdefault("warnings", []).append(
        "Vendor analysis could not be completed; no matched products to show. Please try again."
    )
    return state


@retryable_node(max_attempts=2, label="perform_vendor_analysis", on_exhausted=_degrade_vendor_analysis)
def perform_vendor_analysis(state: AgenticSystemState) -> AgenticSystemState:
    """
    Perform vendor analysis on filtered vendors using the vendor analysis agent.

    This uses the new 7-step analysis chain matching the old API exactly:
    1. ProductDataLoading (from MongoDB)
    2. VendorListLoading & Filtering
    3. FilteredPDFLoading (Azure Blob)
    4. ParallelVendorAnalysis (ThreadPoolExecutor)
    5. FinalRanking
    """
    state.setdefault("agent_path", []).append("perform_vendor_analysis")
    state["agent_path"].append("vendor_analysis_agent")

    # CRITICAL FIX: Clear trigger_search IMMEDIATELY so that generate_final_response
    # (which is the next node in the graph) does not invoke perform_vendor_analysis a
    # SECOND time.  Previously the flag survived until generate_final_response checked
    # it, causing the entire vendor analysis pipeline to run twice.
    state["trigger_search"] = False

    try:
        # Emit progress — fires whenever stream_id is present
        stream_id = state.get("stream_id")

        # Get required parameters from state
        user_input = state.get("user_input", "")
        structured_requirements = state.get("structured_requirements", "")
        session_id = state.get("session_id", "")

        # Extract vendor preferences if user specified any
        specified_vendors = None
        if state.get("filtered_vendors"):
            specified_vendors = state["filtered_vendors"]

        applicable_standards = state.get("applicable_standards")
        if isinstance(applicable_standards, str):
            applicable_standards = [applicable_standards] if applicable_standards else None

        standards_specs = state.get("standards_specs")
        detected_product_type = state.get("detected_product_type")

        user_id = state.get("user_id")

        from domain.search.agents.vendor_analysis_agent import run_vendor_analysis, flatten_schema_leaf_keys

        comparison_spec_keys = flatten_schema_leaf_keys(
            state.get("detected_schema") or state.get("mapped_requirements") or {}
        )
        state["comparison_spec_keys"] = comparison_spec_keys

        # Read pdf_bytes from module cache (not from state — binary data stays out of graph).
        # NON-DESTRUCTIVE read (was .pop): @retryable_node may re-run this node
        # after a transient failure, and a destructive first read left the retry
        # attempt with no PDF bytes. The entry is removed on SUCCESS below, and
        # in _degrade_vendor_analysis when retries are exhausted (no leak).
        pdf_cache_key = _pdf_cache_key(state)
        with _pdf_bytes_cache_lock:
            cache_keys_snapshot = list(_pdf_bytes_cache.keys())
            session_pdf_bytes = _pdf_bytes_cache.get(pdf_cache_key, {})

        logger.info(
            f"[SEARCH_AGENT][perform_vendor_analysis] ENTER — "
            f"session_id={session_id!r} "
            f"stream_id={stream_id!r} "
            f"product_type={detected_product_type!r} "
            f"thread={threading.current_thread().name} "
            f"has_products_json={bool(state.get('products_json'))} "
            f"has_pdf_content={bool(state.get('pdf_content'))} "
            f"filtered_vendors={state.get('filtered_vendors', [])}"
        )
        logger.info("[SEARCH_AGENT] Starting vendor analysis with new 7-step chain...")

        logger.info(
            f"[SEARCH_AGENT][perform_vendor_analysis] pdf_bytes_cache READ — "
            f"cache_key={pdf_cache_key!r} "
            f"bytes_vendors_retrieved={list(session_pdf_bytes.keys())} "
            f"cache_keys={cache_keys_snapshot} "
            f"thread={threading.current_thread().name}"
        )
        if not session_pdf_bytes:
            logger.warning(
                f"[SEARCH_AGENT][perform_vendor_analysis] No PDF bytes found in cache for "
                f"cache_key={pdf_cache_key!r}. "
                f"Possible causes: (1) load_pdf_content was skipped or failed, "
                f"(2) stream_id/session_id mismatch between load_pdf_content and perform_vendor_analysis."
            )

        # ── DATA-FLOW AUDIT: everything the final vendor analysis depends on ──
        # One greppable line that explains WHY an analysis came back empty or
        # degraded: any input listed here as missing forces a fallback path
        # (LLM-only discovery, no-PDF text analysis, re-query of MongoDB, ...).
        _missing_inputs = [
            name for name, present in (
                ("products_json", bool(state.get("products_json"))),
                ("pdf_content", bool(state.get("pdf_content"))),
                ("pdf_bytes", bool(session_pdf_bytes)),
                ("structured_requirements", bool(structured_requirements)),
                ("detected_product_type", bool(detected_product_type)),
            ) if not present
        ]
        if _missing_inputs:
            logger.warning(
                f"[VENDOR_ANALYSIS_AUDIT] session={session_id!r} stream={stream_id!r} "
                f"MISSING INPUTS at final vendor analysis: {_missing_inputs} — "
                f"analysis will use fallback paths for these."
            )
        else:
            logger.info(
                f"[VENDOR_ANALYSIS_AUDIT] session={session_id!r} stream={stream_id!r} "
                f"all vendor-analysis inputs present."
            )

        logger.info(
            f"[SEARCH_AGENT][perform_vendor_analysis] Calling run_vendor_analysis — "
            f"user_input_len={len(user_input)} "
            f"structured_requirements_len={len(structured_requirements)} "
            f"session_id={session_id!r} "
            f"specified_vendors={specified_vendors} "
            f"applicable_standards={applicable_standards} "
            f"product_type={detected_product_type!r} "
            f"preloaded_pdf_vendors={list(state.get('pdf_content', {}).keys())} "
            f"preloaded_pdf_bytes_vendors={list(session_pdf_bytes.keys())}"
        )

        analysis_result = run_vendor_analysis(
            user_input=user_input,
            structured_requirements=structured_requirements,
            search_session_id=session_id,
            specified_vendors=specified_vendors,
            applicable_standards=applicable_standards,
            standards_specs=standards_specs,
            product_type=detected_product_type,
            stream_id=stream_id,
            user_id=user_id,
            products_json=state.get("products_json"),  # reuse already-loaded products, skip DB re-query
            preloaded_pdf_content=state.get("pdf_content"),  # reuse already-downloaded PDF text, skip Azure re-download
            preloaded_pdf_bytes=session_pdf_bytes,      # reuse already-downloaded raw PDF bytes (Spatial AI)
            comparison_spec_keys=comparison_spec_keys,  # requested spec keys for the vendor comparison table
        )

        logger.info(
            f"[SEARCH_AGENT][perform_vendor_analysis] run_vendor_analysis RETURNED — "
            f"type={type(analysis_result).__name__} "
            f"keys={list(analysis_result.keys()) if isinstance(analysis_result, dict) else 'not a dict'} "
            f"has_error={'error' in analysis_result if isinstance(analysis_result, dict) else 'N/A'} "
            f"vendor_matches_count={len(analysis_result.get('vendor_analysis', {}).get('vendor_matches', [])) if isinstance(analysis_result, dict) else 0}"
        )

        # Only treat as a fatal error when the result carries no ranked products AT ALL
        # (the LLM-only fallback path now returns results without an "error" key)
        error_msg = analysis_result.get("error")
        if error_msg:
            overall_ranking_check = analysis_result.get("overall_ranking", {})
            fallback_ranked = overall_ranking_check.get("ranked_products", [])
            if not fallback_ranked:
                raise Exception(f"Vendor analysis returned error with no ranked products: {error_msg}")
            logger.warning(
                f"[SEARCH_AGENT] Vendor analysis had error ('{error_msg}') but still "
                f"returned {len(fallback_ranked)} ranked products — using them."
            )

        # Extract results from new API format
        overall_ranking = analysis_result.get("overall_ranking", {})
        ranked_products = overall_ranking.get("ranked_products", [])
        
        # ✅ FIX: Extract RAW matches so vendor_ranking_agent can rank them
        vendor_analysis_data = analysis_result.get("vendor_analysis", {})
        vendor_matches = vendor_analysis_data.get("vendor_matches", [])

        logger.info(f"[SEARCH_AGENT] Extracted {len(ranked_products)} ranked products and {len(vendor_matches)} raw matches from analysis_result")

        # Update state with analysis results (matching old API format for compatibility)
        state["ranked_products"] = ranked_products
        state["vendor_matches"] = vendor_matches
        state["best_match"] = ranked_products[0] if ranked_products else None
        state["analysis_metadata"] = analysis_result.get("analysis_metadata", {})
        state["deep_analysis_complete"] = True

        # SUCCESS: this run's PDF bytes are consumed — free them now. (Kept in
        # the cache until success so a retryable_node re-attempt still has them.)
        with _pdf_bytes_cache_lock:
            _pdf_bytes_cache.pop(pdf_cache_key, None)

        logger.info(f"[SEARCH_AGENT] Deep analysis complete. Found {len(ranked_products)} ranked products")

        return state

    except Exception as e:
        # Log rich context, then re-raise so @retryable_node can classify and
        # retry transient failures (timeouts / rate-limits / 5xx). Persistent or
        # deterministic failures fall through to _degrade_vendor_analysis, which
        # degrades gracefully with a warning instead of crashing the search.
        logger.exception(f"[SEARCH_AGENT] Error in deep analysis: {e}")
        logger.error(f"[SEARCH_AGENT] Exception type: {type(e).__name__}")
        logger.error(f"[SEARCH_AGENT] Deep analysis input - user_input: {user_input}")
        logger.error(f"[SEARCH_AGENT] Deep analysis input - structured_requirements: {structured_requirements}")
        logger.error(f"[SEARCH_AGENT] Deep analysis input - session_id: {session_id}")
        raise


# ORPHANED FUNCTION - REMOVED
# This function was replaced by perform_deep_analysis() which uses deep_analysis_agent
# The analyze_vendors node was defined but never called in the workflow


# _get_final_ranking has been moved to vendor_ranking_agent.py

def generate_llm_response(state: AgenticSystemState) -> AgenticSystemState:
    """
    Generate the assistant chat message that accompanies the search response.

    HITL removed: this node NEVER pauses the pipeline for missing/optional/advanced
    specs. It only short-circuits for legitimate non-search cases:
      * `reset_intent`             — user asked to reset the session
      * `router_needed`            — non-search redirect (page routing)
      * `contextual_qna`           — LLM-answerable Q about existing state

    For every other case (productRequirements, workflow, modification, etc.) it
    generates a brief acknowledgement and lets the full search pipeline run.
    """
    try:
        logger.info("[SEARCH_AGENT] Generating LLM response message (HITL disabled)...")

        intent_type = state.get("search_intent", "productRequirements")

        # ── Non-search short-circuits (unchanged from HITL removal perspective) ──
        if state.get("reset_intent"):
            reset_type = state.get("reset_intent")
            logger.info(f"[SEARCH_AGENT] Reset response: {reset_type}")
            state["llm_generated_response"] = state.get("response_message", "")
            state["skip_full_workflow"] = True
            return state

        if state.get("router_needed"):
            logger.info(f"[SEARCH_AGENT] Router response: {state.get('router_message', '')}")
            state["llm_generated_response"] = state.get("router_message", "")
            state["skip_full_workflow"] = True
            return state

        if intent_type == "contextual_qna":
            message = state.get("response_message", "Let me check that for you.")
            logger.info(f"[SEARCH_AGENT] Contextual QnA response: {message}")
            state["llm_generated_response"] = message
            state["skip_full_workflow"] = True
            return state

        # ── Product-search / modification path: always continue the pipeline ──
        product_type = state.get("detected_product_type", "product")
        session_id = state.get("session_id")
        is_modification = bool(state.get("modification_applied"))

        try:
            from domain.search.services.search_messages import generate_sidebar_specs_message
            sidebar_message = generate_sidebar_specs_message(
                product_type,
                session_id,
                is_modification=is_modification,
            )
        except Exception as msg_err:
            logger.warning(f"[SEARCH_AGENT] Sidebar message helper failed: {msg_err}")
            sidebar_message = (
                f"I've updated your **{product_type}** specifications in the left panel."
                if is_modification
                else f"I've loaded **{product_type}** specifications in the left panel."
            )

        if is_modification:
            state["llm_generated_response"] = sidebar_message
            logger.info("[SEARCH_AGENT] Modification acknowledged with sidebar-first message")
            state["skip_full_workflow"] = True
            state["workflow_step"] = "awaitAllSpecs"
            state["trigger_search"] = False
            state["trigger_summary"] = False
            state["proceed_confirmed"] = False
            return state

        proceed_confirmed = bool(state.get("proceed_confirmed"))
        if not proceed_confirmed:
            from domain.search.services.proceed_gate import is_proceed_command
            proceed_confirmed = is_proceed_command(state.get("user_input", ""))
            if proceed_confirmed:
                state["proceed_confirmed"] = True

        if proceed_confirmed and intent_type in ("workflow", "analyze", "search"):
            state["skip_full_workflow"] = False
            state["trigger_search"] = False
            state["trigger_summary"] = False
            state["workflow_step"] = "finalAnalysis"
            if not state.get("llm_generated_response"):
                state["llm_generated_response"] = sidebar_message
            logger.info(
                f"[SEARCH_AGENT] Proceed confirmed — running full vendor pipeline for intent='{intent_type}'",
            )
            return state

        # Default: sidebar loaded / updated — wait for explicit proceed before vendor search.
        state["skip_full_workflow"] = True
        state["trigger_search"] = False
        state["trigger_summary"] = False
        state["workflow_step"] = "awaitAllSpecs"
        state["proceed_confirmed"] = False
        if not state.get("llm_generated_response"):
            state["llm_generated_response"] = sidebar_message
        logger.info(
            f"[SEARCH_AGENT] Sidebar ready at awaitAllSpecs for intent='{intent_type}' — awaiting proceed",
        )
        return state

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Error generating LLM response: {e}")
        state["llm_generated_response"] = "Running search now."
        # Even on error, don't pause — proceed to search with whatever data we have.
        state["skip_full_workflow"] = False

        _notify_failure("LLM Response Generation",
            f"Failed to generate LLM response: {str(e)}",
            state, input=state.get("user_input", "N/A"), error=str(e))

    return state


@retryable_node(max_attempts=2, label="generate_final_response")
def generate_final_response(state: AgenticSystemState) -> AgenticSystemState:
    """
    Generate the final response with all analysis results.
    Includes:
    - Final ranking sorted by match_score
    - Standardization of vendor names
    - camelCase conversion for API compatibility
    """
    state.setdefault("agent_path", []).append("generate_final_response")
    state["agent_path"].append("summary_agent")
    try:
        # Emit progress event
        stream_id = state.get("stream_id")
        if stream_id and state.get("enable_streaming"):
            progress_tracker.emit(stream_id, "step", {
                "step": "generate_final_response",
                "message": "Finalizing Results",
                "progress": 95
            })

        logger.info("[SEARCH_AGENT] Generating final response...")

        # ================================================================
        # HANDLE PRODUCT NOT FOUND RESPONSE
        # ================================================================
        if state.get("product_not_found"):
            logger.info("[SEARCH_AGENT] Generating product not found response")

            validation_alert = state.get("validation_alert", {})

            response_data = {
                "search_intent": "productRequirements",
                "product_not_found": True,
                "detected_product_type": state.get("detected_product_type", ""),
                "validation_alert": validation_alert,
                "message": validation_alert.get("message", "Product type not found in database"),
                "timestamp": datetime.now().isoformat(),
                "success": False,
                "agent_path": state.get("agent_path", [])
            }

            standardized_response = standardize_and_convert_response(response_data)
            state["agent_response"] = response_data
            state["agent_response_standardized"] = standardized_response
            state["current_agent"] = "search_agent"
            state["agent_status"] = "completed"

            logger.info(f"[SEARCH_AGENT] Product not found response generated for: {state.get('detected_product_type')}")
            return state

        # ================================================================
        # HANDLE ROUTER_NEEDED RESPONSE
        # ================================================================
        if state.get("router_needed"):
            logger.info("[SEARCH_AGENT] Generating router redirect response")

            response_data = {
                "search_intent": "router_needed",
                "router_category": state.get("router_category"),
                "router_target_page": state.get("router_target_page"),
                "router_requires_routing": state.get("router_requires_routing", False),
                "router_url": state.get("router_url", ""),
                "router_message": state.get("router_message", ""),
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "agent_path": state.get("agent_path", [])
            }

            standardized_response = standardize_and_convert_response(response_data)
            state["agent_response"] = response_data
            state["agent_response_standardized"] = standardized_response
            state["current_agent"] = "search_agent"
            state["agent_status"] = "completed"

            logger.info(f"[SEARCH_AGENT] Router redirect response generated: {state.get('router_category')} → {state.get('router_target_page')}")
            return state

        # ================================================================
        # MODIFICATION / SIDEBAR-ONLY RESPONSE (awaitAllSpecs edit loop)
        # ================================================================
        if state.get("modification_applied") or state.get("skip_full_workflow"):
            from domain.search.services.schema_merge import build_api_schema_payload

            message = state.get("llm_generated_response") or state.get("modification_summary", "")
            merged_payload = {
                "product_type": state.get("detected_product_type", ""),
                "detected_schema": state.get("detected_schema", {}),
                "mapped_requirements": state.get("mapped_requirements", {}),
                "missing_mandatory_fields": state.get("missing_mandatory_fields", []),
                "missing_optional_fields": state.get("missing_optional_fields", []),
                "missing_fields_friendly": state.get("missing_fields_friendly", []),
                "missing_advanced_fields": state.get("missing_advanced_fields", []),
                "missing_advanced_fields_friendly": state.get("missing_advanced_fields_friendly", []),
                "validation_alert": state.get("validation_alert"),
                "specified_vendors": state.get("specified_vendors", []),
                "specified_model_families": state.get("specified_model_families", []),
                "schema_source": state.get("schema_source", ""),
                "advanced_specs": state.get("advanced_specs", []),
            }
            response_data = {
                "search_intent": "modification",
                "intent": "modification",
                "message": message,
                "nextStep": "awaitAllSpecs",
                "workflow_step": "awaitAllSpecs",
                "changes_made": state.get("changes_made", []),
                "timestamp": datetime.now().isoformat(),
                "success": True,
                "agent_path": state.get("agent_path", []),
                **build_api_schema_payload(merged_payload),
            }
            standardized_response = standardize_and_convert_response(response_data)
            state["agent_response"] = response_data
            state["agent_response_standardized"] = standardized_response
            state["current_agent"] = "search_agent"
            state["agent_status"] = "completed"
            logger.info("[SEARCH_AGENT] Modification response generated (awaitAllSpecs)")
            try:
                from domain.search.services.search_session_context import (
                    commit_search_context_from_langgraph_state,
                    ContextEvent,
                )
                sid = state.get("session_id") or state.get("search_session_id")
                if sid:
                    commit_search_context_from_langgraph_state(
                        sid,
                        state,
                        ContextEvent.MODIFICATION,
                        user_input=state.get("user_input", ""),
                        assistant_message=message,
                    )
            except Exception as ctx_exc:
                logger.warning("[SEARCH_AGENT] Modification context commit failed: %s", ctx_exc)
            return state

        # ================================================================
        # NORMAL SEARCH RESPONSE
        # ================================================================
        # Get ranked products directly from deep analysis state
        ranked_products = state.get("ranked_products") or []
        
        # ✅ NEW: Update total_found to match ranked count if we have deep analysis results
        total_found = len(ranked_products) if ranked_products else state.get("total_found", 0)

        # Keep empty overall_ranking object to not break existing frontend structure initially
        overall_ranking = state.get("overall_ranking") or {"ranked_products": ranked_products}

        logger.info(f"[SEARCH_AGENT] Finalizing Response: {len(ranked_products)} ranked products found. Total count: {total_found}")
        logger.debug(f"[SEARCH_AGENT] Result Keys: ranked_products={bool(ranked_products)}, overall_ranking={bool(overall_ranking)}")

        # For intermediate workflow steps (no products yet), reuse the message already
        # generated by generate_llm_response so we don't overwrite it with a misleading
        # "0 products found" message from SEARCH_FINAL_RESULTS_PROMPT.
        llm_generated = state.get("llm_generated_response", "")
        workflow_step = state.get("workflow_step", "")
        if llm_generated and not ranked_products and workflow_step != "finalAnalysis":
            final_message = llm_generated
        else:
            # Dynamically generate the message for the frontend (real analysis results)
            exact_matches = [p for p in ranked_products if p.get("requirements_match") is True]
            approximate_matches = [p for p in ranked_products if p.get("requirements_match") is False and p.get("overall_score", 0) >= 50]
            display_count = len(exact_matches) if len(exact_matches) > 0 else len(approximate_matches)

            response_chain = (
                ChatPromptTemplate.from_template(SEARCH_FINAL_RESULTS_PROMPT)
                | llm_flash
                | StrOutputParser()
            )
            final_message = response_chain.invoke({"display_count": display_count}).strip()

        # Create comprehensive response (snake_case - internal format)
        response_data = {
            # Intent Classification
            "search_intent": state.get("search_intent", "productRequirements"),
            "next_workflow_step": state.get("next_workflow_step"),
            "intent_confidence": state.get("intent_confidence", "low"),
            "current_workflow_step": state.get("workflow_step", "initialInput"),

            # Product Type Detection
            "detected_product_type": state.get("detected_product_type"),
            "validation_result": state.get("validation_result", {}),

            # Schema and Mapping — three parallel tiers for the left-side panel
            #   detected_schema.mandatoryRequirements  (validation_agent)
            #   detected_schema.optionalRequirements   (validation_agent)
            #   detected_schema.advancedRequirements   (advanced_specs_agent)
            "detected_schema": state.get("detected_schema", {}),
            "schema_source": state.get("schema_source", "unknown"),
            "mapped_requirements": state.get("mapped_requirements", {}),
            "missing_mandatory_fields": state.get("missing_mandatory_fields", []),
            "missing_optional_fields": state.get("missing_optional_fields", []),
            "missing_advanced_fields": state.get("missing_advanced_fields", []),
            "missing_fields_friendly": state.get("missing_fields_friendly", []),
            "missing_advanced_fields_friendly": state.get("missing_advanced_fields_friendly", []),
            "has_missing_fields": state.get("has_missing_fields", False),
            "validation_alert": state.get("validation_alert"),

            # Requirements
            "structured_requirements": state.get("structured_requirements"),
            "provided_requirements": state.get("provided_requirements"),
            "formatted_requirements_summary": state.get("formatted_requirements_summary", ""),
            "specified_vendors": state.get("specified_vendors"),
            "specified_model_families": state.get("specified_model_families"),
            "applicable_standards": state.get("applicable_standards", []),
            "skip_standards": state.get("skip_standards", False),
            "strategy": state.get("strategy"),

            # Search Results
            "total_products_found": total_found,
            "count": total_found, # Explicitly for frontend polling logic
            "search_categories": state.get("search_categories"),
            "vendor_matches": ranked_products, # For backward compatibility
            "vendor_analysis": {
                "vendor_matches": ranked_products
            },
            "vendor_run_details": state.get("vendor_run_details", []),
            "overall_ranking": overall_ranking,
            "comparison_table": state.get("comparison_table", {}),
            "advanced_specs": state.get("advanced_specs", {}),

            # PDF Loading Results
            "vendors_with_pdfs": state.get("vendors_with_pdfs", []),
            "vendors_without_pdfs": state.get("vendors_without_pdfs", []),

            # Dynamically Generated Response Message
            "message": final_message,

            # Non-fatal warnings (e.g. a node that degraded gracefully after retries)
            "warnings": state.get("warnings", []),

            # Metadata
            "analysis_metadata": state.get("analysis_metadata", {}),
            "timestamp": datetime.now().isoformat(),
            "success": True,
            "agent_path": state.get("agent_path", [])
        }

        # Apply standardization and camelCase conversion (matching old main.py post-processing)
        standardized_response = standardize_and_convert_response(response_data)

        # Store both raw (snake_case) and standardized (camelCase) responses
        state["agent_response"] = response_data  # Keep raw for internal use
        state["agent_response_standardized"] = standardized_response  # For API response
        state["overall_ranking"] = overall_ranking
        state["current_agent"] = "search_workflow"
        state["agent_status"] = "completed"

        logger.info("[SEARCH_AGENT] Final response generated and standardized successfully")

        session_id = state.get("session_id") or state.get("search_session_id")
        if session_id and ranked_products and workflow_step == "finalAnalysis":
            try:
                from domain.search.services.search_session_context import commit_vendor_results_from_state

                commit_vendor_results_from_state(
                    session_id,
                    state,
                    assistant_message=final_message,
                )
            except Exception as ctx_exc:
                logger.warning("[SEARCH_AGENT] Failed to commit vendor results to context: %s", ctx_exc)

    except Exception as e:
        logger.exception(f"[SEARCH_AGENT] Error generating final response: {e}")
        error_message = f"Response generation error: {str(e)}"
        state["error_message"] = error_message
        state["agent_response"] = {
            "error": error_message,
            "success": False,
            "timestamp": datetime.now().isoformat(),
            "agent_path": state.get("agent_path", [])
        }

        # Send notification for final response generation failure
        _notify_failure("Final Response Generation",
            f"Failed to generate final response: {str(e)}",
            state, error=str(e))

    return state


def handle_error(state: AgenticSystemState) -> AgenticSystemState:
    """
    Handle errors in the workflow.
    """
    error_message = state.get("error_message")
    logger.error(f"[SEARCH_AGENT] Handling error: {error_message}")

    state["agent_response"] = {
        "error": error_message,
        "success": False,
        "timestamp": datetime.now().isoformat(),
        "detected_product_type": state.get("detected_product_type", ""),
        "structured_requirements": state.get("structured_requirements", ""),
        "agent_path": state.get("agent_path", [])
    }

    state["current_agent"] = "search_workflow"
    state["agent_status"] = "error"

    return state


# ============================================================================
# WORKFLOW CONDITION FUNCTIONS
# ============================================================================

def should_continue(state: AgenticSystemState) -> Literal["continue", "end"]:
    """
    Check if workflow should continue or end.
    """
    if state.get("error_message"):
        return "end"
    return "continue"


def route_after_validation(state: AgenticSystemState) -> Literal["continue", "generate_response", "handle_error"]:
    """
    Route after product type detection and validation.

    HITL removed: never pauses on missing fields. Only diverts from the linear
    pipeline for two terminal cases — product_not_found (needs a friendly error
    message) and hard validation errors.
    """
    if state.get("product_not_found"):
        logger.info("[SEARCH_AGENT] Product type not found - skipping to response with friendly message")
        return "generate_response"

    if state.get("error_message"):
        logger.error("[SEARCH_AGENT] Validation error - routing to error handler")
        return "handle_error"

    missing_fields = state.get("missing_mandatory_fields", [])
    if missing_fields:
        logger.info(
            f"[SEARCH_AGENT] {len(missing_fields)} mandatory fields missing — "
            f"HITL disabled, continuing with partial data"
        )

    logger.info("[SEARCH_AGENT] Validation complete → Continuing workflow")
    return "continue"


def route_after_intent(state: AgenticSystemState) -> Literal["extract_requirements", "update_agent", "generate_response", "handle_error"]:
    """
    Route after intent classification based on intent type and workflow step.

    This is the WORKFLOW ORCHESTRATOR that decides which node to execute next based on:
    - Intent type (productRequirements, workflow, clarification, reset, etc.)
    - Current workflow step (initialInput, awaitAllSpecs, finalAnalysis)
    - Context (missing fields, existing search params, etc.)

    Routing Logic:
    - productRequirements → extract_requirements (full validation)
    - workflow → generate_response (step transition message)
    - clarification → generate_response (ask question)
    - reset/router_needed → generate_response (direct message)
    - error → handle_error
    """
    if state.get("error_message"):
        return "handle_error"

    intent_type = state.get("search_intent", "productRequirements")
    current_step = state.get("workflow_step", "initialInput")
    has_prior_search = bool(state.get("has_prior_search"))

    logger.info(f"[SEARCH_AGENT] Routing - Intent: {intent_type}, Step: {current_step}")

    # Handle reset intents
    if state.get("reset_intent"):
        logger.info("[SEARCH_AGENT] Reset intent detected - routing to response")
        return "generate_response"

    # HITL removed: clarification_needed is no longer a pause condition.
    # (classify_search_intent now converts clarification intents into
    # productRequirements and lets the full pipeline run.)

    # Handle contextual QNA
    if intent_type == "contextual_qna":
        logger.info("[SEARCH_AGENT] Contextual QnA - routing to response to answer question")
        return "generate_response"

    # Handle router_needed
    if state.get("router_needed"):
        logger.info("[SEARCH_AGENT] Router needed - routing to response")
        return "generate_response"

    # Workflow navigation intents (user saying yes/no/skip) — HITL removed,
    # so we treat them as a request to run the full pipeline immediately.
    if intent_type == "workflow":
        logger.info(f"[SEARCH_AGENT] Workflow intent at step '{current_step}' — routing straight to extract_requirements")
        return "extract_requirements"

    # At awaitAllSpecs, chat messages auto-update sidebar specs (no manual schema edits) --
    # but only when a real prior search actually exists to update; otherwise this is a
    # fresh turn (e.g. stale/mismatched workflow_step) and must go through full extraction.
    if current_step == "awaitAllSpecs" and intent_type in ("modification", "productRequirements") and has_prior_search:
        logger.info(
            "[SEARCH_AGENT] %s at awaitAllSpecs — routing to update_agent (automatic schema sync)",
            intent_type,
        )
        return "update_agent"

    # Modification intent on other steps — apply the change via update_agent
    if intent_type == "modification" and has_prior_search:
        logger.info("[SEARCH_AGENT] Modification intent detected - routing to update_agent")
        return "update_agent"

    # Everything else (productRequirements and unknowns) → full parallel pipeline
    logger.info(f"[SEARCH_AGENT] Intent '{intent_type}' - routing to extract_requirements")
    return "extract_requirements"


# ============================================================================
# WORKFLOW GRAPH CREATION
# ============================================================================

def route_after_llm_response(state: AgenticSystemState) -> Literal["continue_workflow", "end"]:
    """
    Decide whether to continue with the full search pipeline or terminate.

    Modifications end here (awaitAllSpecs edit loop). Vendor search runs only
    when the user explicitly proceeds to finalAnalysis.
    """
    intent_type = state.get("search_intent", "")

    if state.get("modification_applied") or intent_type == "modification":
        logger.info("[SEARCH_AGENT] Modification complete → Ending (awaitAllSpecs edit loop)")
        return "end"

    if state.get("skip_full_workflow"):
        logger.info("[SEARCH_AGENT] skip_full_workflow set → Ending without vendor pipeline")
        return "end"

    if intent_type == "contextual_qna":
        logger.info("[SEARCH_AGENT] Contextual QnA → Ending (answer already produced)")
        return "end"

    if state.get("router_needed"):
        logger.info("[SEARCH_AGENT] router_needed → Ending workflow, skipping search pipeline")
        return "end"

    if state.get("reset_intent"):
        logger.info("[SEARCH_AGENT] reset_intent → Ending workflow")
        return "end"

    logger.info(
        f"[SEARCH_AGENT] Continuing to full search pipeline "
        f"(intent={intent_type!r}, missing_fields={len(state.get('missing_mandatory_fields', []))})"
    )
    return "continue_workflow"


