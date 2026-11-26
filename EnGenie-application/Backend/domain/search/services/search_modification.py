"""
Shared search spec modification (add / update / remove) for awaitAllSpecs edit loop.
Used by REST API (search.py) and LangGraph update_agent.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from common.helpers.json_text import parse_llm_json as _parse_llm_json

logger = logging.getLogger(__name__)

_TIER_KEYS = (
    "mandatoryRequirements",
    "optionalRequirements",
    "advancedRequirements",
    "latestRequirements",
)


def _load_modification_prompt() -> str:
    prompts_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "prompts",
    )
    path = os.path.join(prompts_dir, "update_agent.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


def unflatten_dot_notation(flat: dict[str, Any]) -> dict[str, Any]:
    """Convert dot-notation keys (from frontend collectedData) to nested dict."""
    root: dict[str, Any] = {}
    for key, value in (flat or {}).items():
        if key in ("unmapped_specs", "detected_product_type", "productType"):
            continue
        parts = key.split(".")
        cur = root
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
    return root


def flatten_tiered_mapped(mapped: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten tiered mapped_requirements to dot-notation."""
    flat: dict[str, Any] = {}
    for key, val in (mapped or {}).items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            flat.update(flatten_tiered_mapped(val, full))
        else:
            flat[full] = val
    return flat


def merge_modification_delta(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """
    Deep-merge tiered mapped requirements.
    Empty strings in delta clear leaves; non-empty values overwrite.
    """
    result = copy.deepcopy(base or {})
    for key, dval in (delta or {}).items():
        if isinstance(dval, dict):
            if key not in result or not isinstance(result[key], dict):
                result[key] = {}
            result[key] = merge_modification_delta(result[key], dval)
        elif isinstance(dval, str) and not dval.strip():
            if key in result:
                result[key] = ""
        else:
            result[key] = dval
    return result


def ensure_tiered_structure(mapped: dict[str, Any]) -> dict[str, Any]:
    """Normalize mapped requirements to tier keys."""
    if any(k in mapped for k in _TIER_KEYS):
        out = copy.deepcopy(mapped)
        for tier in _TIER_KEYS:
            out.setdefault(tier, {})
        return out
    return {"mandatoryRequirements": copy.deepcopy(mapped), "optionalRequirements": {}, "advancedRequirements": {}}
def _merge_flat_provided(
    existing: dict[str, Any],
    flat_updates: dict[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(existing or {})
    for key, val in (flat_updates or {}).items():
        if isinstance(val, str) and not val.strip():
            merged.pop(key, None)
        else:
            merged[key] = val
    return merged


def _hydrate_current_state(
    session_id: str,
    current_state: dict[str, Any] | None,
    collected_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from domain.search.services.search_session_context import load_search_context

    ctx = load_search_context(
        session_id,
        collected_data=collected_data,
        langgraph_state=current_state,
    )
    state = ctx.to_langgraph_state()
    state["change_log"] = list(ctx.change_log)
    state["context_version"] = ctx.version
    return state


def _apply_heuristic_edits(
    user_input: str,
    detected_schema: dict[str, Any],
    mapped_requirements: dict[str, Any],
    provided_requirements: dict[str, Any],
    missing_mandatory: list[str],
    missing_optional: list[str],
) -> tuple[dict[str, Any], bool]:
    from domain.search.services.schema_field_matching import resolve_value_only_update

    updates, needs_clarification = resolve_value_only_update(
        user_input=user_input,
        detected_schema=detected_schema,
        mapped_requirements=mapped_requirements,
        provided_requirements=provided_requirements,
        missing_mandatory=missing_mandatory,
        missing_optional=missing_optional,
    )
    return updates, needs_clarification


def _persist_modification(
    session_id: str,
    merged: dict[str, Any],
    *,
    user_input: str = "",
    assistant_message: str = "",
    changes_made: list[str] | None = None,
) -> None:
    from domain.search.services.search_session_context import (
        ContextEvent,
        commit_search_context_from_merged,
    )

    commit_search_context_from_merged(
        session_id,
        merged,
        ContextEvent.MODIFICATION,
        workflow_step="awaitAllSpecs",
        user_input=user_input,
        assistant_message=assistant_message,
        changes_made=changes_made,
    )


@dataclass
class ModificationResult:
    success: bool = True
    needs_clarification: bool = False
    summary: str = ""
    changes_made: list[str] = field(default_factory=list)
    modified_params: dict[str, Any] = field(default_factory=dict)
    merged: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    next_step: str = "awaitAllSpecs"
    error: str | None = None

    def to_api_response(self) -> dict[str, Any]:
        from domain.search.services.schema_merge import build_api_schema_payload

        out: dict[str, Any] = {
            "success": self.success,
            "needsClarification": self.needs_clarification,
            "changesMade": self.changes_made,
            "modifiedParams": self.modified_params,
            "nextStep": self.next_step,
            "message": self.message or self.summary,
        }
        if self.merged:
            payload = build_api_schema_payload(self.merged)
            out.update(payload)
            out["collectedData"] = payload.get("collectedData") or flatten_tiered_mapped(
                self.merged.get("mapped_requirements") or {}
            )
        if self.error:
            out["error"] = self.error
        return out

    def apply_to_langgraph_state(self, state: dict[str, Any]) -> None:
        from domain.search.services.schema_merge import apply_merged_extraction_to_state

        if self.merged:
            apply_merged_extraction_to_state(state, self.merged)
        state["modification_applied"] = True
        state["modification_summary"] = self.summary
        state["changes_made"] = self.changes_made
        state["needs_clarification"] = self.needs_clarification
        state["workflow_step"] = "awaitAllSpecs"
        state["skip_full_workflow"] = True
        if self.needs_clarification:
            state["llm_generated_response"] = self.summary or self.message
        elif self.message:
            state["llm_generated_response"] = self.message


def apply_search_modification(
    *,
    session_id: str,
    user_input: str,
    current_state: dict[str, Any] | None = None,
    collected_data: dict[str, Any] | None = None,
    conversation_context: str | None = None,
    skip_standard_rag: bool = False,
    user_id: int | None = None,
    stream_id: str | None = None,
    standard_specs: dict[str, Any] | None = None,
) -> ModificationResult:
    """
    Apply user CRUD edits to tiered mapped requirements and refresh sidebar payload.
    Stays on awaitAllSpecs — does not trigger vendor analysis.
    """
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from common.ai.llm import get_deterministic_flash
    from domain.search.services.schema_merge import (
        build_api_schema_payload,
        merge_validation_and_advanced,
        recompute_missing_after_update,
    )
    from domain.search.services.search_messages import generate_sidebar_specs_message

    if stream_id:
        from common.helpers.progress_tracker import progress_tracker
        progress_tracker.emit(stream_id, "step", {
            "step": "modification",
            "message": "Updating Requirements",
            "progress": 20,
        })

    state = _hydrate_current_state(session_id, current_state, collected_data)
    product_type = state.get("detected_product_type", "")
    mapped = state.get("mapped_requirements", {})
    detected_schema = state.get("detected_schema", {})
    provided = state.get("provided_requirements", {}) or {}
    unmapped = state.get("unmapped_specs", {}) or {}

    if not product_type and not mapped:
        return ModificationResult(
            success=False,
            needs_clarification=True,
            summary="I don't have a previous search to modify. Please provide your search requirements.",
            next_step=state.get("workflow_step", "initialInput"),
        )

    missing = recompute_missing_after_update(mapped, detected_schema) if detected_schema else {}
    heuristic_flat, _heuristic_ambiguous = _apply_heuristic_edits(
        user_input,
        detected_schema,
        mapped,
        provided,
        missing.get("missing_mandatory_fields", []),
        missing.get("missing_optional_fields", []),
    )

    if heuristic_flat:
        from domain.search.services.schema_merge import enrich_mapped_requirements

        provided = _merge_flat_provided(provided, heuristic_flat)
        mapped = copy.deepcopy(mapped)
        enrich_mapped_requirements(mapped, detected_schema, provided, unmapped)

    enriched_request = user_input
    if conversation_context and conversation_context != "No previous conversation.":
        enriched_request = f"Recent Conversation:\n{conversation_context}\n\nCurrent User Message: {user_input}"

    if not detected_schema and product_type:
        try:
            from domain.search.services.product_service import get_schema_for_product
            from domain.search.agents.validation_agent import _normalise_schema_keys

            detected_schema = get_schema_for_product(product_type) or {}
            detected_schema = _normalise_schema_keys(detected_schema)
            state["detected_schema"] = detected_schema
        except Exception as exc:
            logger.warning("[SEARCH_MODIFICATION] Schema fetch failed: %s", exc)

    requirement_schema = detected_schema or {}
    current_search_params = {
        "detected_product_type": product_type,
        "mapped_requirements": mapped,
        "provided_requirements": provided,
        "unmapped_specs": unmapped,
        "specified_vendors": state.get("specified_vendors", []),
        "specified_model_families": state.get("specified_model_families", []),
        "applicable_standards": state.get("applicable_standards", []),
        "skip_standards": skip_standard_rag,
    }

    mod_chain = (
        ChatPromptTemplate.from_template(_load_modification_prompt())
        | get_deterministic_flash()
        | StrOutputParser()
    )
    llm_resp = mod_chain.invoke({
        "requirement_schema": json.dumps(requirement_schema, indent=2),
        "current_search_params": json.dumps(current_search_params, indent=2),
        "modification_request": enriched_request,
        "standard_specs": json.dumps(standard_specs or {}, indent=2) or "No standards specs available",
    })

    mod_result = _parse_llm_json(llm_resp)
    if mod_result.get("needs_clarification"):
        return ModificationResult(
            success=True,
            needs_clarification=True,
            summary=mod_result.get("summary", "Could you clarify which field to change?"),
            changes_made=mod_result.get("changes_made", []),
            next_step="awaitAllSpecs",
        )

    modified_params = mod_result.get("modified_search_params", {})
    delta_mapped = ensure_tiered_structure(modified_params.get("mapped_requirements", {}))
    merged_mapped = merge_modification_delta(mapped, delta_mapped)

    flat_from_llm = modified_params.get("provided_requirements_flat") or {}
    merged_provided = _merge_flat_provided(provided, heuristic_flat)
    merged_provided = _merge_flat_provided(merged_provided, flat_from_llm)

    merged_unmapped = copy.deepcopy(unmapped)
    for uk, uv in (modified_params.get("unmapped_specs") or {}).items():
        if isinstance(uv, str) and not uv.strip():
            merged_unmapped.pop(uk, None)
        else:
            merged_unmapped[uk] = uv

    product_type = modified_params.get("detected_product_type", product_type) or product_type

    advanced_result = None
    if product_type:
        try:
            from domain.search.agents.advanced_specs_agent import run_advanced_specs_discovery
            advanced_result = run_advanced_specs_discovery(product_type, stream_id=stream_id)
        except Exception as exc:
            logger.warning("[SEARCH_MODIFICATION] Advanced specs refresh failed: %s", exc)
            advanced_result = {"advanced_specs": state.get("advanced_specs", [])}

    synthetic_validation = {
        "success": True,
        "product_type": product_type,
        "detected_schema": detected_schema,
        "mapped_requirements": merged_mapped,
        "provided_requirements": merged_provided,
        "unmapped_specs": merged_unmapped,
        "specified_vendors": modified_params.get("specified_vendors", state.get("specified_vendors", [])),
        "specified_model_families": modified_params.get(
            "specified_model_families", state.get("specified_model_families", []),
        ),
        "applicable_standards": modified_params.get(
            "applicable_standards", state.get("applicable_standards", []),
        ),
        "schema_source": state.get("schema_source", ""),
        "validation_alert": state.get("validation_alert"),
        "input_range": state.get("input_range", "mid"),
    }
    merged = merge_validation_and_advanced(synthetic_validation, advanced_result)

    message = generate_sidebar_specs_message(
        merged.get("product_type", product_type),
        session_id,
        is_modification=True,
    )

    if session_id:
        _persist_modification(
            session_id,
            merged,
            user_input=user_input,
            assistant_message=message,
            changes_made=mod_result.get("changes_made", []),
        )

    return ModificationResult(
        success=True,
        needs_clarification=False,
        summary=mod_result.get("summary", "Modifications applied."),
        changes_made=mod_result.get("changes_made", []),
        modified_params=modified_params,
        merged=merged,
        message=message,
        next_step="awaitAllSpecs",
    )
