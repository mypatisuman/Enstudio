"""
Validation Sub-Agent

A self-contained agent called when intent is classified as 'productRequirements'.

HITL removed: this agent NEVER blocks on missing fields. It always returns
`is_complete=True` / `has_missing_fields=False` so the orchestrator can run the
downstream search pipeline end-to-end. Missing-field lists are still computed and
returned for informational/telemetry purposes.

Advanced-specs discovery is no longer invoked here — the orchestrator
(`extract_requirements` in `search_agent.py`) runs `run_advanced_specs_discovery`
in parallel with this agent and merges the results into `detected_schema`.

Steps:
  Step 1 — Detect product type + extract all requirements from user input
  Step 2 — Fetch the matching schema from MongoDB (parallel with Standards RAG)
  Step 3 — Map extracted requirements against the schema
  Step 4 — Compute (informational) missing-field lists and return

No LangChain tools are used. All logic lives here.
"""

import ast
import concurrent.futures
import json
from common.helpers.notifications import notify_failure as _notify_failure
from common.helpers.progress_tracker import progress_tracker
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from common.infra.repositories.interaction_log_repository import interaction_logger
from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
from common.ai.rag.taxonomy_rag import get_taxonomy_for_category
from common.ai.llm import get_flash_llm

logger = logging.getLogger(__name__)




def _resolve_category_alias_from_json(product_type: str) -> str:
    """Map a free-form product type to its canonical name via taxonomy_aliases.json."""
    if not product_type:
        return product_type
    try:
        from pathlib import Path
        # parents[3] == Backend/ (agents->search->domain->Backend); the file lives at
        # Backend/common/resources/. (Was parents[2] -> Backend/domain/common/... which
        # does not exist, so alias resolution silently never fired.)
        _aliases_path = Path(__file__).resolve().parents[3] / "common" / "resources" / "taxonomy_aliases.json"
        with open(_aliases_path, encoding="utf-8") as f:
            aliases = json.load(f)
        needle = product_type.lower().strip()
        for _section, mapping in aliases.items():
            if needle in mapping:
                return mapping[needle]
    except Exception as e:
        logger.debug(f"[VALIDATION_AGENT] alias lookup failed: {e}")
    return product_type


# Path to the search/prompts/ directory (for .md prompt files)
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

DETECT_AND_EXTRACT_PROMPT = open(os.path.join(_PROMPTS_DIR, "detect_and_extract_prompt.md"), encoding="utf-8").read()
SCHEMA_MAPPING_PROMPT = open(os.path.join(_PROMPTS_DIR, "schema_mapping_prompt.md"), encoding="utf-8").read()

from common.ai.prompts.response.response_prompts import (
    MISSING_FIELDS_EXTRACTION_PROMPT,
    SEARCH_PRODUCT_NOT_FOUND_PROMPT,
)

# ============================================================================
# LLM INSTANCE  (shared, flash model for speed)
# ============================================================================

_llm = get_flash_llm(temperature=0.1)


# ============================================================================
# IN-MEMORY SCHEMA CACHE  (same TTL as schema_retrieval_tool)
# ============================================================================

_schema_cache: dict[str, dict[str, Any]] = {}
_cache_timestamps: dict[str, datetime] = {}
_CACHE_TTL_MINUTES = 60 * 24          # 24 hours
_schema_build_locks: dict[str, threading.Lock] = {}


def _get_cached_schema(product_type: str) -> dict[str, Any] | None:
    key = product_type.lower().strip()
    if key in _schema_cache:
        ts = _cache_timestamps.get(key)
        if ts and datetime.now() - ts < timedelta(minutes=_CACHE_TTL_MINUTES):
            return _schema_cache[key]
        _schema_cache.pop(key, None)
        _cache_timestamps.pop(key, None)
    return None


def _set_cached_schema(product_type: str, schema: dict[str, Any]) -> None:
    key = product_type.lower().strip()
    _schema_cache[key] = schema
    _cache_timestamps[key] = datetime.now()


# ============================================================================
# SCHEMA FETCH  (MongoDB → cache → generic fallback)
# ============================================================================

def _resolve_alias(product_type: str) -> str:
    """
    Map free-form/LLM-extracted product type names to the canonical catalog name
    using taxonomy_aliases.json. Returns the original string if no alias matches.

    Fixes the 'Pipe Stand' → 'Instrument Stand' class of bug where the LLM extracts
    a colloquial name that doesn't exist in MongoDB → schema-not-found cascade.
    """
    resolved = _resolve_category_alias_from_json(product_type)
    if resolved and resolved.lower() != product_type.lower():
        logger.info(f"[VALIDATION_AGENT] Alias resolved: '{product_type}' → '{resolved}'")
        return resolved
    return product_type


def _fetch_schema(product_type: str) -> tuple[dict[str, Any] | None, str]:
    """
    Fetch the requirements schema for a product type.

    Returns:
        (schema_dict, source)  where source is 'cache'|'mongodb'|'not_found'
        schema_dict is None if not found
    """
    # 0. Resolve alias FIRST so 'Pipe Stand' becomes 'Instrument Stand' before lookup.
    product_type = _resolve_alias(product_type)

    # 1. Cache check
    cached = _get_cached_schema(product_type)
    if cached:
        return cached, "cache"

    # 2. MongoDB
    try:
        from domain.search.services.product_service import get_schema_for_product
        schema = get_schema_for_product(product_type)
        if schema and (schema.get("mandatory_requirements") or schema.get("mandatoryRequirements")):
            _set_cached_schema(product_type, schema)
            return schema, "mongodb"
    except Exception as e:
        logger.warning(f"[VALIDATION_AGENT] MongoDB schema fetch failed: {e}")

    # 3. Schema not found - return None to indicate product type not supported
    logger.warning(f"[VALIDATION_AGENT] Schema not found for product type: {product_type}")
    return None, "not_found"


# ============================================================================
# SCHEMA KEY NORMALISATION  (snake_case → camelCase)
# ============================================================================

def _to_camel_case(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


def _normalise_schema_keys(data: Any) -> Any:
    """Recursively convert snake_case dict keys to camelCase."""
    if isinstance(data, dict):
        return {_to_camel_case(k): _normalise_schema_keys(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_normalise_schema_keys(i) for i in data]
    return data


# ============================================================================
# (Removed hardcoded _FIELD_SYNONYMS and Python-based mapping)
# Now using LLM-based semantic mapping (SCHEMA_MAPPING_PROMPT)
# ============================================================================


# ============================================================================
# MISSING MANDATORY FIELDS DETECTION
# ============================================================================

_EMPTY_VALUES = {"", "not specified", "not requested", "none specified", "n/a", "na", ","}


# Field-name suffixes/prefixes that should be ignored when fuzzy-matching a
# user-provided key to a schema mandatory field. e.g. "ambient_temperature_limits"
# should match "ambientTemperatureRange" — both reduce to "ambienttemperature".
_FUZZY_NOISE_TOKENS = (
    "range", "limits", "limit", "rating", "type", "value", "spec", "specification",
    "options", "option", "size", "design", "level", "class",
)


def _normalize_field_name(name: str) -> str:
    """Lowercase, drop separators, drop noise tokens — for fuzzy key matching."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name)).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    parts = [p for p in s.split("_") if p and p not in _FUZZY_NOISE_TOKENS]
    return "".join(parts)


def _fuzzy_field_name_match(schema_key: str, provided_key: str) -> bool:
    from domain.search.services.schema_field_matching import fuzzy_field_name_match
    return fuzzy_field_name_match(schema_key, provided_key)


def resolve_provided_value_for_schema_field(
    schema_key: str,
    provided: dict[str, Any],
) -> Any | None:
    from domain.search.services.schema_field_matching import (
        resolve_provided_value_for_schema_field as _resolve_field,
    )
    return _resolve_field(schema_key, provided)


def _backfill_mapped_from_provided(
    mapped: dict[str, Any],
    schema: dict[str, Any],
    provided: dict[str, Any],
    *,
    tiers: tuple[str, ...] | None = None,
) -> None:
    """
    Walk schema tier trees; for empty mapped leaves, match values from ``provided``
    using normalized / fuzzy field-name matching. Mutates ``mapped`` in place.

    Covers mandatory, optional, and advanced tiers so extracted user values
    reach the sidebar even when the LLM mapper skips a tier.
    """
    if not isinstance(mapped, dict) or not isinstance(schema, dict) or not provided:
        return

    tier_keys = tiers or (
        "mandatoryRequirements",
        "optionalRequirements",
        "latestRequirements",
        "advancedRequirements",
    )

    def _resolve_hit(schema_key: str) -> tuple[str, Any] | None:
        val = resolve_provided_value_for_schema_field(schema_key, provided)
        if val is None:
            return None
        for pk, pv in provided.items():
            if pv == val:
                return pk, pv
        return schema_key, val

    def _walk(schema_node: dict, mapped_node: dict, tier_label: str):
        if not isinstance(schema_node, dict):
            return
        for key, schema_val in schema_node.items():
            if isinstance(schema_val, dict):
                if not isinstance(mapped_node.get(key), dict):
                    mapped_node[key] = {}
                _walk(schema_val, mapped_node[key], tier_label)
            else:
                cur = mapped_node.get(key)
                if cur is None or str(cur).strip().lower() in _EMPTY_VALUES:
                    hit = _resolve_hit(key)
                    if hit:
                        orig_k, val = hit
                        mapped_node[key] = val
                        logger.info(
                            f"[VALIDATION_AGENT] Backfilled {tier_label} '{key}' "
                            f"← provided '{orig_k}' = '{val}'"
                        )

    for tier in tier_keys:
        schema_tier = schema.get(tier) or {}
        if not schema_tier:
            continue
        mapped.setdefault(tier, {})
        if not isinstance(mapped[tier], dict):
            mapped[tier] = {}
        _walk(schema_tier, mapped[tier], tier)


def _get_filled_normalized_keys(mapped: dict[str, Any]) -> set[str]:
    """Traverse mapped requirements and collect all non-empty normalized keys."""
    filled = set()
    tier_keys = (
        "mandatoryRequirements",
        "optionalRequirements",
        "latestRequirements",
        "advancedRequirements",
    )

    def _traverse(node: Any):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict):
                    _traverse(v)
                elif v is not None and str(v).strip().lower() not in _EMPTY_VALUES:
                    nk = _normalize_field_name(k)
                    if nk:
                        filled.add(nk)

    for tier in tier_keys:
        _traverse(mapped.get(tier) or {})
    return filled


def _is_standard_document_key(key: str) -> bool:
    """Detect if a key represents an engineering standard/document reference."""
    k = key.strip().upper()
    prefixes = ("API", "ISA", "IEC", "ASTM", "ASME", "ANSI", "ISO", "NEMA", "NACE", "IEEE", "DIN", "BS", "NFPA", "EN", "SAMA")
    for pref in prefixes:
        if re.match(rf"^{pref}\b", k) or re.match(rf"^{pref}\d", k):
            return True
    return False


def _is_ignored_key(key: str) -> bool:
    """Ignore reference standards, general project metadata, and certs that aren't physical specs."""
    k = re.sub(r"[^A-Z0-9]+", "", key.strip().upper())
    
    # 1. Ignored metadata/generic fields
    metadata_fields = {
        "TAGNUMBER", "PIDNUMBER", "LINEVESSELNUMBER", "SERVICEDESCRIPTION", 
        "PROJECTNAME", "AREACLASSIFICATION", "CORROSIVEENVIRONMENT", "MATERIALCERTIFICATION"
    }
    if k in metadata_fields:
        return True
        
    # 2. Certifications & Standards
    certifications = {
        "ATEX", "IECEX", "CEMARKING", "CERTIFICATIONS", "SIL", "SILRATING", 
        "SAFETYINTEGRITYLEVEL", "COMPLIANCE", "STANDARDS"
    }
    if k in certifications:
        return True
        
    # 3. Reference Standards (API 551, ISA-20, etc.)
    if _is_standard_document_key(key):
        return True
        
    return False


def _get_missing_mandatory_fields(mapped: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Return list of mandatory field names that have no value."""
    missing: list[str] = []
    mandatory = schema.get("mandatoryRequirements") or schema.get("mandatorySpecifications") or schema.get("mandatorySpecs") or {}
    provided_mandatory = mapped.get("mandatoryRequirements") or mapped.get("mandatorySpecifications") or mapped.get("mandatorySpecs") or {}

    filled_normalized = _get_filled_normalized_keys(mapped)

    def _traverse(schema_node: dict, provided_node: dict):
        for key, schema_val in schema_node.items():
            if isinstance(schema_val, dict):
                next_provided = provided_node.get(key, {}) if isinstance(provided_node, dict) else {}
                _traverse(schema_val, next_provided)
            else:
                pval = provided_node.get(key) if isinstance(provided_node, dict) else None
                if pval is None or str(pval).strip().lower() in _EMPTY_VALUES:
                    if not _is_ignored_key(key):
                        nk = _normalize_field_name(key)
                        if nk not in filled_normalized:
                            missing.append(key)

    _traverse(mandatory, provided_mandatory)
    return missing


def _count_total_mandatory_fields(schema: dict[str, Any]) -> int:
    """Return total number of mandatory fields defined in the schema."""
    mandatory = schema.get("mandatoryRequirements") or schema.get("mandatorySpecifications") or schema.get("mandatorySpecs") or {}
    count = 0

    def _traverse(schema_node: dict):
        nonlocal count
        for key, schema_val in schema_node.items():
            if isinstance(schema_val, dict):
                _traverse(schema_val)
            else:
                if not _is_ignored_key(key):
                    count += 1

    _traverse(mandatory)
    return count


def _get_missing_optional_fields(mapped: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Return list of optional field names that have no value (user hasn't filled them yet)."""
    missing: list[str] = []
    optional = schema.get("optionalRequirements") or schema.get("optionalSpecifications") or schema.get("optionalSpecs") or {}
    provided_optional = mapped.get("optionalRequirements") or mapped.get("optionalSpecifications") or mapped.get("optionalSpecs") or {}

    filled_normalized = _get_filled_normalized_keys(mapped)

    def _traverse(schema_node: dict, provided_node: dict):
        for key, schema_val in schema_node.items():
            if isinstance(schema_val, dict):
                next_provided = provided_node.get(key, {}) if isinstance(provided_node, dict) else {}
                _traverse(schema_val, next_provided)
            else:
                pval = provided_node.get(key) if isinstance(provided_node, dict) else None
                if pval is None or str(pval).strip().lower() in _EMPTY_VALUES:
                    if not _is_ignored_key(key):
                        nk = _normalize_field_name(key)
                        if nk not in filled_normalized:
                            missing.append(key)

    _traverse(optional, provided_optional)
    return missing


def _friendly_name(field: str) -> str:
    """camelCase → 'Title Case With Spaces'."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    return spaced.replace("_", " ").title()


# ============================================================================
# JSON PARSE HELPER
# ============================================================================

def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    for prefix in ("```json", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return ast.literal_eval(cleaned)


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================

def update_requirements(
    existing_context: dict[str, Any],
    user_input: str,
    stream_id: str = None
) -> dict[str, Any]:
    """
    Update missing requirements without full re-validation.

    Args:
        existing_context: Previous validation result with missing fields
        user_input: User's response providing missing values

    Returns:
        Updated context with new values and appropriate response
    """
    logger.info(f"[VALIDATION_AGENT] Updating requirements: {user_input[:120]}...")

    if stream_id:
        progress_tracker.emit(stream_id, "step", {"message": "Updating", "progress": 20})

    product_type = existing_context.get("product_type", "")
    missing_fields = existing_context.get("missing_mandatory_fields", [])

    if not missing_fields:
        # Already complete, just return existing context
        return existing_context

    # Extract only the missing field values using LLM
    try:
        chain = (
            ChatPromptTemplate.from_template(MISSING_FIELDS_EXTRACTION_PROMPT)
            | _llm
            | StrOutputParser()
        )
        raw_updates = chain.invoke({
            "user_input": user_input,
            "product_type": product_type,
            "missing_fields": missing_fields
        })
        updates = _parse_json(raw_updates)

        logger.info(f"[VALIDATION_AGENT] Extracted updates: {updates}")

        # Update provided_requirements
        provided_requirements = existing_context.get("provided_requirements", {})
        provided_requirements.update(updates)

        # Update mapped_requirements
        mapped_requirements = existing_context.get("mapped_requirements", {})
        detected_schema = existing_context.get("detected_schema", {})

        for field, value in updates.items():
            # Update in mapped requirements
            if "mandatoryRequirements" in mapped_requirements:
                _find_and_update_field(mapped_requirements["mandatoryRequirements"], field, value)
            if "optionalRequirements" in mapped_requirements:
                _find_and_update_field(mapped_requirements["optionalRequirements"], field, value)

        # Backfill again from updated provided_requirements so freshly-supplied
        # values reach the schema even if the LLM extractor used a slightly
        # different key name from the schema field.
        _backfill_mapped_from_provided(mapped_requirements, detected_schema, provided_requirements)

        # Recalculate missing fields
        new_missing_fields = _get_missing_mandatory_fields(mapped_requirements, detected_schema)
        new_missing_friendly = [_friendly_name(f) for f in new_missing_fields]
        has_missing = len(new_missing_fields) > 0

        # Enforce 80% completeness threshold
        total_mandatory = _count_total_mandatory_fields(detected_schema)
        missing_count = len(new_missing_fields)
        provided_count = total_mandatory - missing_count
        completeness_ratio = (provided_count / total_mandatory) if total_mandatory > 0 else 1.0

        logger.info(
            f"[VALIDATION_AGENT] Completeness check: {provided_count}/{total_mandatory} "
            f"mandatory fields provided ({completeness_ratio * 100:.1f}%)"
        )

        # ✨ CLARIFICATION-ROUND CAP: after one clarification round, proceed with
        # whatever we have instead of looping forever. Prior behavior asked for a
        # different missing field on every pass and stalled the UI on
        # "Processing request..." indefinitely.
        # CRITICAL: Only allow proceeding with partial data if completeness is at least 80%.
        clarification_round = int(existing_context.get("clarification_round", 0)) + 1
        MAX_CLARIFICATION_ROUNDS = 2
        if has_missing and clarification_round >= MAX_CLARIFICATION_ROUNDS:
            if completeness_ratio >= 0.8:
                logger.info(
                    f"[VALIDATION_AGENT] Clarification round cap reached "
                    f"({clarification_round}/{MAX_CLARIFICATION_ROUNDS}) and completeness "
                    f"({completeness_ratio * 100:.1f}%) >= 80% — proceeding with partial data. "
                    f"Remaining missing: {new_missing_fields}"
                )
                has_missing = False
            else:
                logger.info(
                    f"[VALIDATION_AGENT] Clarification round cap reached "
                    f"({clarification_round}/{MAX_CLARIFICATION_ROUNDS}) but completeness "
                    f"({completeness_ratio * 100:.1f}%) is less than 80% — forcing continuation of clarification loop."
                )

        # Chat messaging is handled by search_messages.generate_sidebar_specs_message.
        if updates:
            logger.info("[VALIDATION_AGENT] Detected modification input - should be routed to modification handler")
            scenario = "modification_detected"
        else:
            scenario = "user_continue"
            has_missing = False  # Allow to proceed

        validation_alert = {
            "message": None,
            "canContinue": True,
            "missingFields": new_missing_fields if has_missing else [],
            "scenario": scenario
        }

        # Return updated context
        return {
            **existing_context,
            "provided_requirements": provided_requirements,
            "mapped_requirements": mapped_requirements,
            "missing_mandatory_fields": new_missing_fields if has_missing else [],
            "missing_fields_friendly": new_missing_friendly if has_missing else [],
            "has_missing_fields": has_missing,
            "is_complete": not has_missing,
            "clarification_round": clarification_round,
            "validation_alert": validation_alert,
            "response_message": "",
            "success": True,
            "error": None
        }

    except Exception as e:
        logger.exception(f"[VALIDATION_AGENT] Update failed: {e}")
        return {
            **existing_context,
            "error": f"Failed to update requirements: {str(e)}"
        }


def _find_and_update_field(node: dict, search_key: str, value: Any) -> bool:
    """Helper to find and update a field in nested schema structure."""
    camel_key = _to_camel_case(search_key)
    for _k, v in node.items():
        if isinstance(v, dict):
            if all(isinstance(x, (str, type(None))) for x in v.values()):
                # Leaf category
                if search_key in v:
                    v[search_key] = value
                    return True
                if camel_key in v:
                    v[camel_key] = value
                    return True
            else:
                if _find_and_update_field(v, search_key, value):
                    return True
    return False


def run_validation_agent(
    user_input: str,
    skip_standard_rag: bool = False,
    user_id: int | None = None,
    stream_id: str = None,
    pre_mapped: dict = None,
    known_product_type: str = None,
) -> dict[str, Any]:
    """
    Run the full validation pipeline for a 'productRequirements' intent.

    Args:
        user_input: Raw user message containing product requirements.
        skip_standard_rag: If True, skip fetching standard specs from RAG
                          (used when coming from solution page with detailed specs already)
        user_id: User ID for notification creation (optional, will use session if not provided)
        pre_mapped: If provided, uses this pre-mapped specifications dict instead of extracting from scratch.
        known_product_type: Optional known product category (e.g., from tab or session) as fallback.

    Returns:
        Dict with validation/alert results.
    """
    logger.info(f"[VALIDATION_AGENT] Starting validation for: {user_input[:120]}...")

    advanced_specs = []
    standard_specs = {}
    standard_specs_source = None

    if stream_id:
        progress_tracker.emit(stream_id, "step", {"message": "Analyzing Requirements", "progress": 15})

    # ------------------------------------------------------------------ #
    # STEP 1 — Detect product type + extract requirements (single LLM call)
    # ------------------------------------------------------------------ #

    if pre_mapped:
        logger.info("[VALIDATION_AGENT] Bypassing Step 1 (extraction) using pre_mapped dict.")
        product_type = (pre_mapped.get("product_type", "") or known_product_type or "").strip().title()
        provided_requirements = pre_mapped.get("provided_requirements", {}) or pre_mapped.get("mapped_requirements", {})
        specified_vendors = pre_mapped.get("specified_vendors", [])
        specified_model_families = pre_mapped.get("specified_model_families", [])
        applicable_standards = pre_mapped.get("applicable_standards", [])
        strategy = pre_mapped.get("strategy", "")
        confidence = pre_mapped.get("confidence", "high")
        reasoning = pre_mapped.get("reasoning", "")
        input_range = pre_mapped.get("input_range", "mid")
    else:
        try:
            chain = (
                ChatPromptTemplate.from_template(DETECT_AND_EXTRACT_PROMPT)
                | _llm
                | StrOutputParser()
            )
            raw_step1 = chain.invoke({"user_input": user_input})
            step1 = _parse_json(raw_step1)

            product_type = (step1.get("product_type") or "").strip().title()
            if (not product_type or product_type.lower() in ("unknown", "unknownproduct")) and known_product_type:
                product_type = known_product_type.strip().title()
                logger.info(f"[VALIDATION_AGENT] Fallback to known_product_type: '{product_type}'")

            provided_requirements = step1.get("provided_requirements", {})
            specified_vendors = step1.get("specified_vendors", [])
            specified_model_families = step1.get("specified_model_families", [])
            applicable_standards = step1.get("applicable_standards", [])
            strategy = step1.get("strategy", "")
            confidence = step1.get("confidence", "medium")
            reasoning = step1.get("reasoning", "")
            input_range = step1.get("input_range", "mid")

            # ✅ DEBUG: Log immediately after extraction
            logger.info(f"[VALIDATION_AGENT] Step 1 — LLM extracted product_type: '{product_type}'")
            logger.info(f"[VALIDATION_AGENT] Step 1 complete — product_type='{product_type}', "
                        f"requirements={provided_requirements}, confidence={confidence}")

            if not product_type or product_type.lower() in ("unknown", "unknownproduct"):
                return {
                    "success": False,
                    "is_complete": False,
                    "product_type": "",
                    "provided_requirements": provided_requirements,
                    "mapped_requirements": {},
                    "detected_schema": {},
                    "schema_source": "none",
                    "specified_vendors": specified_vendors,
                    "specified_model_families": specified_model_families,
                    "applicable_standards": applicable_standards,
                    "strategy": strategy,
                    "input_range": input_range,
                    "missing_mandatory_fields": [],
                    "missing_fields_friendly": [],
                    "has_missing_fields": False,
                    "validation_alert": None,
                    "standard_specs": {},
                    "standard_specs_source": None,
                    "error": "Could not determine the product type from your input. "
                             "Please specify the type of industrial product you need."
                }

        except Exception as e:
            logger.exception(f"[VALIDATION_AGENT] Step 1 failed: {e}")

            # Notify admin of requirement extraction failure
            _notify_failure("Validation Agent - Requirements Extraction",
                f"Requirement extraction failed: {str(e)}",
                user_input=user_input)

            return {
                "success": False,
                "is_complete": False,
                "product_type": "",
                "provided_requirements": {},
                "mapped_requirements": {},
                "detected_schema": {},
                "schema_source": "none",
                "specified_vendors": [],
                "specified_model_families": [],
                "applicable_standards": [],
                "strategy": "",
                "input_range": "mid",
                "missing_mandatory_fields": [],
                "missing_fields_friendly": [],
                "has_missing_fields": False,
                "validation_alert": None,
                "standard_specs": {},
                "standard_specs_source": None,
                "error": f"Requirement extraction failed: {str(e)}"
            }

    # ------------------------------------------------------------------ #
    # STEP 1.5 — Taxonomy Normalization & Standards RAG
    # ------------------------------------------------------------------ #
    # STEP 1.5 — Taxonomy Normalization & Standards RAG
    # Canonicalize product_type and fetch standards BEFORE schema search
    # ------------------------------------------------------------------ #
    if stream_id:
        progress_tracker.emit(stream_id, "step", {"message": "Applying Standards", "progress": 25})

    standard_specs = {}
    standard_specs_source = None
    taxonomy_result = None
    advanced_specs = []
    raw_schema = None
    schema_source = "none"

    try:
        # user_id must be passed explicitly by the caller
        
        # 1. Canonicalize product type using Taxonomy RAG (fast database/LLM match)
        try:
            taxonomy_result = get_taxonomy_for_category(product_type, provided_requirements)
            if taxonomy_result and taxonomy_result.get("matched_category"):
                new_product_type = taxonomy_result["matched_category"]
                if new_product_type.lower() != product_type.lower():
                    logger.info(f"[VALIDATION_AGENT] Taxonomy RAG mapped product_type: '{product_type}' -> '{new_product_type}'")
                    product_type = new_product_type

                # Remap user spec keys to DB schema keys using taxonomy mappings
                mapped_specs = taxonomy_result.get("mapped_specifications", {})
                if mapped_specs:
                    user_to_db = {}
                    for m in taxonomy_result.get("spec_field_mappings", []):
                        uf = m.get("user_field", "")
                        db_f = m.get("field_to_use") or m.get("db_field", "")
                        if uf and db_f and uf != db_f:
                            user_to_db[uf] = db_f

                    if user_to_db:
                        remapped = {}
                        for key, val in provided_requirements.items():
                            new_key = user_to_db.get(key, key)
                            remapped[new_key] = val
                        provided_requirements = remapped
        except Exception as t_err:
            logger.warning(f"[VALIDATION_AGENT] Taxonomy RAG failed: {t_err}")

        # 2. Execute database queries and standard specs RAG in parallel.
        # NOTE: advanced_specs_agent is intentionally NOT called here anymore.
        # The orchestrator (`extract_requirements` in search_agent.py) runs
        # `run_advanced_specs_discovery` in parallel with this whole validation
        # call so both agents execute concurrently at the top level.
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_schema = executor.submit(_fetch_schema, product_type)

            future_standard = None
            if not skip_standard_rag:
                logger.info(f"[VALIDATION_AGENT] Fetching standard specs for product_type='{product_type}', user_id={user_id}")
                future_standard = executor.submit(ProductHierarchyRepository.get_standards_for_category, user_id=user_id, category=product_type)
            else:
                logger.info("[VALIDATION_AGENT] skip_standard_rag is True - skipping standard RAG")

            # Resolve schema
            raw_schema, schema_source = future_schema.result()

            # Resolve standard specifications RAG
            if future_standard:
                try:
                    standard_rag_result = future_standard.result()
                    if standard_rag_result.get("found"):
                        standard_specs = standard_rag_result.get("specifications", {})
                        standard_specs_source = standard_rag_result.get("source_document", "Standard Document")
                        logger.info(f"[VALIDATION_AGENT] ✓ Found {len(standard_specs)} standard specifications from RAG")
                        
                        # Tag standard specs with (STANDARD) suffix
                        tagged_standard_specs = {
                            key: f"{value} (STANDARD)" if value else value
                            for key, value in standard_specs.items()
                        }

                        # Merge standard specs with user-provided specs
                        merged_requirements = tagged_standard_specs.copy()
                        merged_requirements.update(provided_requirements)  # User specs override standard
                        provided_requirements = merged_requirements
                except Exception as std_err:
                    logger.warning(f"[VALIDATION_AGENT] Standard specs RAG resolution failed: {std_err}")

    except Exception as e:
        logger.warning(f"[VALIDATION_AGENT] Parallel retrieval pipeline failed: {e}")

    # ------------------------------------------------------------------ #
    # STEP 1.6 — F1: standards + essential from the 5-tier band cascade
    # Source applicable_standards from the bidirectional band cascade (L0 ↑ + L1 +
    # L2 ↓), which is grounded in the standards documents, rather than relying solely
    # on the LLM-extracted standards from Step 1. The LLM-extracted list is unioned in
    # (user may name a standard the cascade doesn't carry). Essential fields come from
    # the same call; the mandatory gate below still uses the full schema fetch.
    # ------------------------------------------------------------------ #
    try:
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
        f1 = ProductHierarchyRepository.get_standards_and_essential_by_name(product_type)
        cascade_standards = f1.get("standards") or []
        essential_fields = f1.get("essential") or {}
        logger.info(
            f"[5TIER_AUDIT][validation_agent] STEP_1_6 "
            f"source=Restructured DB method=get_standards_and_essential_by_name "
            f"product_type={product_type!r} "
            f"standards_from_band={len(cascade_standards)} standards={cascade_standards} "
            f"essential_fields={len(essential_fields)} keys={list(essential_fields.keys())[:10]}"
        )
        if cascade_standards:
            merged_std = list(dict.fromkeys([*cascade_standards, *applicable_standards]))
            logger.info(f"[VALIDATION_AGENT] F1 band standards for '{product_type}': "
                        f"{len(cascade_standards)} cascade + {len(applicable_standards)} LLM "
                        f"= {len(merged_std)} merged")
            applicable_standards = merged_std
    except Exception as e:
        logger.warning(f"[VALIDATION_AGENT] F1 band-standards retrieval failed: {e}")

    # ------------------------------------------------------------------ #
    # STEP 2 — Fetch schema from MongoDB (already resolved in parallel)
    # ------------------------------------------------------------------ #
    if stream_id:
        progress_tracker.emit(stream_id, "step", {"message": "Validating Requirements", "progress": 35})

    try:
        raw_schema, schema_source = _fetch_schema(product_type)

        # Taxonomy fallback: a type can be a recognized taxonomy category yet have NO
        # 5-tier/legacy schema (e.g. 'Pressure Relief Valve' exists only in the taxonomy).
        # The solution/expansion workflow still handles these via taxonomy_rag; mirror that
        # here — when taxonomy_rag confidently resolved the category and the user supplied
        # requirements, proceed using those requirements as the schema instead of hard-failing.
        if (schema_source == "not_found" or raw_schema is None) and provided_requirements \
                and taxonomy_result and taxonomy_result.get("found") \
                and taxonomy_result.get("matched_category"):
            logger.info(
                f"[VALIDATION_AGENT] No DB schema for '{product_type}', but taxonomy_rag resolved it "
                f"(conf={taxonomy_result.get('confidence')}); proceeding with provided requirements as schema."
            )
            raw_schema = {
                "product_type": product_type,
                "mandatoryRequirements": dict(provided_requirements),
                "optionalRequirements": {},
            }
            schema_source = "taxonomy_inferred"

        # Check if schema was not found - product type not supported
        if schema_source == "not_found" or raw_schema is None:
            logger.warning(f"[VALIDATION_AGENT] Schema not found for product type: {product_type}")

            # Notify admin that user searched for an unsupported product type
            _notify_failure("Product Category Not Found",
                f"User searched for '{product_type}' but no matching database schema was found.",
                user_id=user_id, user_input=user_input)

            # Generate friendly "not found" response using LLM
            try:
                not_found_chain = (
                    ChatPromptTemplate.from_template(SEARCH_PRODUCT_NOT_FOUND_PROMPT)
                    | _llm
                    | StrOutputParser()
                )
                not_found_message = not_found_chain.invoke({
                    "product_type": product_type.title()  # Capitalize first letter of each word
                }).strip()
                logger.info("[VALIDATION_AGENT] Generated product not found message via LLM")
            except Exception as e:
                logger.exception(f"[VALIDATION_AGENT] Failed to generate not found message: {e}")
                # Fallback to simple message if LLM fails
                not_found_message = (
                    f"Great choice! You are looking for a {product_type}, but unfortunately, "
                    f"we don't have this product type in our database at the moment. "
                    f"Would you like to search for another product?"
                )

            return {
                "success": False,
                "is_complete": False,
                "product_type": product_type,
                "provided_requirements": provided_requirements,
                "mapped_requirements": {},
                "detected_schema": {},
                "schema_source": "not_found",
                "specified_vendors": specified_vendors,
                "specified_model_families": specified_model_families,
                "applicable_standards": applicable_standards,
                "strategy": strategy,
                "input_range": input_range,
                "missing_mandatory_fields": [],
                "missing_fields_friendly": [],
                "has_missing_fields": False,
                "validation_alert": {
                    "message": not_found_message,
                    "canContinue": False,
                    "missingFields": [],
                    "scenario": "product_not_found"
                },
                "standard_specs": {},
                "standard_specs_source": None,
                "error": f"Product type '{product_type}' not found in database"
            }

        # Normalise keys to camelCase so mapping logic works uniformly
        detected_schema = _normalise_schema_keys(raw_schema)

        # NOTE: advanced_specs injection is done by the orchestrator after the
        # parallel `run_advanced_specs_discovery` future resolves. Kept out of
        # here to keep validation focused on the schema+mapping concern.

        # Inject standard specs from RAG into optionalRequirements under a subcategory "Standards Specifications"
        if standard_specs:
            if "optionalRequirements" not in detected_schema:
                detected_schema["optionalRequirements"] = {}
            if "Standards Specifications" not in detected_schema["optionalRequirements"]:
                detected_schema["optionalRequirements"]["Standards Specifications"] = {}
            for key in standard_specs.keys():
                # Check if this standard spec is already defined in mandatory or optional schema
                exists = False
                for cat, fields in detected_schema.get("mandatoryRequirements", {}).items():
                    if isinstance(fields, dict) and key in fields:
                        exists = True
                        break
                if not exists:
                    for cat, fields in detected_schema.get("optionalRequirements", {}).items():
                        if isinstance(fields, dict) and key in fields:
                            # Skip if it is already in our injected subcategory
                            if cat != "Standards Specifications":
                                exists = True
                            break
                if not exists:
                    detected_schema["optionalRequirements"]["Standards Specifications"][key] = ""
            logger.info(f"[VALIDATION_AGENT] Injected standards specs into detected_schema optionalRequirements.")

        logger.info(f"[VALIDATION_AGENT] Step 2 complete — schema_source='{schema_source}', "
                    f"keys={list(detected_schema.keys())}")
        logger.info(
            f"[5TIER_AUDIT][validation_agent] STEP_2 "
            f"source={'Restructured DB (5-tier band cascade)' if schema_source in ('mongodb', 'cache') else schema_source} "
            f"product_type={product_type!r} "
            f"mandatory_count={len(detected_schema.get('mandatoryRequirements', {}))} "
            f"optional_count={len(detected_schema.get('optionalRequirements', {}))} "
            f"latest_count={len(detected_schema.get('latestRequirements', {}))} "
            f"schema_source={schema_source!r}"
        )
    except Exception as e:
        logger.exception(f"[VALIDATION_AGENT] Step 2 (schema fetch) failed: {e}")
        detected_schema = {}
        schema_source = "error"



    # ------------------------------------------------------------------ #
    # STEP 3 — Map requirements onto schema using LLM (semantic matching)
    # ------------------------------------------------------------------ #
    try:
        if pre_mapped:
            logger.info("[VALIDATION_AGENT] Bypassing Step 3 (mapping) using pre_mapped dict.")
            mapped_requirements = pre_mapped.get("mapped_requirements", pre_mapped)
            unmapped_specs = pre_mapped.get("unmapped_specs", {})
            _backfill_mapped_from_provided(
                mapped_requirements,
                detected_schema,
                provided_requirements,
            )
        else:
            # Use LLM to intelligently map extracted requirements into schema structure
            import json
            schema_json = json.dumps(detected_schema, indent=2)
            extracted_json = json.dumps(provided_requirements, indent=2)

            logger.info("[VALIDATION_AGENT] Step 3 - Mapping requirements to schema")
            logger.info(f"[VALIDATION_AGENT] Extracted requirements to map: {list(provided_requirements.keys())}")
            logger.info(f"[VALIDATION_AGENT] Schema structure keys: {list(detected_schema.keys())}")

            mapping_chain = (
                ChatPromptTemplate.from_template(SCHEMA_MAPPING_PROMPT)
                | _llm
                | StrOutputParser()
            )

            raw_mapped = mapping_chain.invoke({
                "schema": schema_json,
                "extracted_requirements": extracted_json
            })

            logger.info(f"[VALIDATION_AGENT] Raw LLM mapping response (first 500 chars): {raw_mapped[:500]}")

            # Parse the LLM response
            mapped_requirements = _parse_json(raw_mapped)

            logger.info(f"[VALIDATION_AGENT] Mapped requirements structure: {json.dumps(mapped_requirements, indent=2)[:1000]}")

            # ── HALLUCINATION GUARD ────────────────────────────────────────────────
            # The schema-mapping LLM sometimes ignores the "ZERO INFERENCE" rule and
            # fills schema fields with typical industry-default values (e.g. ±0.25%
            # accuracy, 4-20 mA output, ¾-inch NPT) even when the user never
            # mentioned them and the standards toggle is OFF.
            #
            # Fix: build an allowlist of normalised values from provided_requirements
            # (stripping the "(STANDARD)" tag so both user and tagged standard values
            # pass through), then zero-out any mapped leaf value not in that list.
            # ──────────────────────────────────────────────────────────────────────
            def _normalise_val(s: str) -> str:
                """Strip STANDARD tag, collapse whitespace, lowercase for comparison."""
                return re.sub(r"\s+", "", str(s).replace(" (STANDARD)", "").strip().lower())

            _allowed_values: set[str] = {
                _normalise_val(v)
                for v in provided_requirements.values()
                if str(v).strip()
            }

            def _nullify_hallucinated(node: Any) -> Any:
                """Recursively clear any non-empty mapped value that was NOT in provided_requirements."""
                if isinstance(node, dict):
                    return {k: _nullify_hallucinated(v) for k, v in node.items()}
                if isinstance(node, str) and node.strip():
                    if _normalise_val(node) not in _allowed_values:
                        return ""
                return node

            mapped_requirements = _nullify_hallucinated(mapped_requirements)
            logger.info(
                f"[VALIDATION_AGENT] Hallucination guard applied. "
                f"Allowed value set ({len(_allowed_values)}): {list(_allowed_values)[:10]}"
            )

            # ✨ PRESERVE UNMAPPED SPECS: Add any user specs that weren't mapped to schema
            # This handles the case where user gives 5 specs but schema only has 4 fields
            def get_all_mapped_values(node, collected=None):
                """Recursively collect all values from nested schema structure."""
                if collected is None:
                    collected = set()
                if isinstance(node, dict):
                    for _key, value in node.items():
                        if isinstance(value, dict):
                            get_all_mapped_values(value, collected)
                        elif value and value != "":  # Non-empty value
                            collected.add(str(value).replace(" (STANDARD)", ""))  # Remove STANDARD tag for comparison
                return collected

            # Get all values that were successfully mapped into the schema
            mapped_values = get_all_mapped_values(mapped_requirements)

            # Find unmapped specs (user provided but not in schema)
            unmapped_specs = {}
            for user_field, user_value in provided_requirements.items():
                if user_value and str(user_value).replace(" (STANDARD)", "") not in mapped_values:
                    unmapped_specs[user_field] = user_value
                    logger.info(f"[VALIDATION_AGENT] Preserved unmapped spec: '{user_field}' = '{user_value}'")

            # ✨ BACKFILL: rescue user-supplied values that the LLM mapper dropped.
            # Without this, fields like `ambient_temperature_limits` get lost and the
            # validator re-asks for `Ambient Temperature Range`, causing the
            # "Processing request..." stall observed in the UI.
            _backfill_mapped_from_provided(mapped_requirements, detected_schema, provided_requirements)

        # Compute missing-field lists for telemetry/response payload.
        # HITL removed: `has_missing` is ALWAYS False so the orchestrator never
        # pauses the pipeline. Missing lists are still returned so the UI can
        # display them as informational context if desired.
        missing_mandatory_fields = _get_missing_mandatory_fields(mapped_requirements, detected_schema)
        missing_optional_fields = _get_missing_optional_fields(mapped_requirements, detected_schema)
        missing_fields_friendly = [_friendly_name(f) for f in missing_mandatory_fields]
        has_missing = False

        logger.info(f"[VALIDATION_AGENT] Step 3 (LLM mapping) complete — "
                    f"mapped {len(provided_requirements)} requirements, "
                    f"unmapped {len(unmapped_specs)} custom specs, "
                    f"missing_mandatory={missing_mandatory_fields} (INFORMATIONAL — pipeline continues), "
                    f"missing_optional={len(missing_optional_fields)}, "
                    f"input_range={input_range}")
    except Exception as e:
        logger.exception(f"[VALIDATION_AGENT] Step 3 (LLM mapping) failed: {e}")

        # Notify admin of mapping failure
        _notify_failure("Validation Agent - LLM Mapping",
            f"LLM Mapping failed: {str(e)}",
            product_type=product_type)

        # No fallback - LLM mapping is the only method now
        mapped_requirements = {}
        unmapped_specs = {}  # ✨ Initialize on error
        missing_mandatory_fields = []
        missing_optional_fields = []
        missing_fields_friendly = []
        has_missing = False

    # Advanced specs are already fetched in parallel during Step 1.5.

    # ------------------------------------------------------------------ #
    # STEP 4 — Informational metadata only (never blocks the pipeline)
    # Chat messaging uses SEARCH_ALL_SPECS_* via search_messages.generate_sidebar_specs_message.
    # ------------------------------------------------------------------ #
    validation_alert = {
        "message": None,
        "canContinue": True,
        "missingFields": missing_mandatory_fields,
        "scenario": "auto_proceed"
    }
    logger.info(
        f"[VALIDATION_AGENT] Step 4 complete — informational alert only "
        f"(HITL removed). missing_mandatory={len(missing_mandatory_fields)}"
    )

    # ------------------------------------------------------------------ #
    # Return consolidated result
    # ------------------------------------------------------------------ #

    logger.info(f"[VALIDATION_AGENT] FINAL RESULT - product_type: '{product_type}', has_missing: {has_missing}, missing_fields: {missing_mandatory_fields}, advanced_specs: {len(advanced_specs)}")

    result = {
        "success": True,
        "is_complete": not has_missing,
        "product_type": product_type,
        "provided_requirements": provided_requirements,
        "mapped_requirements": mapped_requirements,
        "unmapped_specs": unmapped_specs,
        "detected_schema": detected_schema,
        "schema_source": schema_source,
        "specified_vendors": specified_vendors,
        "specified_model_families": specified_model_families,
        "applicable_standards": applicable_standards,
        "strategy": strategy,
        "input_range": input_range,
        "confidence": confidence,
        "reasoning": reasoning,
        "missing_mandatory_fields": missing_mandatory_fields,
        "missing_optional_fields": missing_optional_fields,
        "missing_fields_friendly": missing_fields_friendly,
        "has_missing_fields": has_missing,
        "advanced_specs": advanced_specs,
        "validation_alert": validation_alert,
        "standard_specs": standard_specs,
        "standard_specs_source": standard_specs_source,
        "error": None
    }

    logger.debug(f"[VALIDATION_AGENT] Returning result with product_type='{result['product_type']}'")

    # Log agent interaction to MongoDB
    try:
        user_id_str = str(user_id) if user_id else 'anonymous'

        # Build response summary
        response_summary = f"Validation: product_type={product_type}, is_complete={not has_missing}"
        if has_missing:
            response_summary += f", missing_fields={missing_mandatory_fields[:3]}"  # First 3 missing fields

        metadata = {
            "agent_type": "validation",
            "parent_agent": "search",
            "product_type": product_type,
            "is_complete": not has_missing,
            "has_missing_fields": has_missing,
            "missing_fields_count": len(missing_mandatory_fields),
            "specified_vendors_count": len(specified_vendors),
            "specified_model_families_count": len(specified_model_families),
            "confidence": confidence,
            "schema_source": schema_source,
            "success": result.get("success", True)
        }

        # Use session_id if available (passed from parent agent via user_input context)
        session_id = f"validation_{user_id_str}_{datetime.now().strftime('%Y%m%d')}"

        interaction_logger.log_interaction(
            user_id=user_id_str,
            session_id=session_id,
            user_input=user_input[:500],  # First 500 chars
            response=response_summary,
            metadata=metadata,
            interaction_type="agent_validation"
        )
    except Exception as log_error:
        logger.warning(f"[VALIDATION_AGENT] Failed to log interaction: {log_error}")

    return result


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_validation_agent_health():
    """
    Health check for Validation Agent
    Tests: LLM, MongoDB (taxonomy, standards), prompt files

    Returns:
        AgentHealthStatus with detailed dependency status
    """
    from datetime import datetime

    from common.monitoring.health import (
        AgentHealthChecker,
        AgentHealthStatus,
        DependencyStatus,
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

        # 2. Test MongoDB collections (taxonomy and standards)
        dependencies["mongodb_taxonomy"] = checker.check_mongodb_collection("taxonomy")
        if dependencies["mongodb_taxonomy"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_standards"] = checker.check_mongodb_collection("standards")
        if dependencies["mongodb_standards"].status == "unavailable":
            status = "unhealthy"

        # 3. Test prompt files
        dependencies["prompt_detect_extract"] = checker.check_prompt_file(
            os.path.join(_PROMPTS_DIR, "detect_and_extract_prompt.md")
        )
        if dependencies["prompt_detect_extract"].status == "unavailable":
            status = "unhealthy"

        dependencies["prompt_schema_mapping"] = checker.check_prompt_file(
            os.path.join(_PROMPTS_DIR, "schema_mapping_prompt.md")
        )
        if dependencies["prompt_schema_mapping"].status == "unavailable":
            status = "unhealthy"

        # 4. Test RAG imports (non-critical)
        try:
            dependencies["rag_imports"] = DependencyStatus("rag_imports", "available")
        except Exception as e:
            dependencies["rag_imports"] = DependencyStatus("rag_imports", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[AGENT_HEALTH] Validation agent health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="validation_agent",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg
    )
