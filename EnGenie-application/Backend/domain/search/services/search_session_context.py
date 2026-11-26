"""
Unified search session context — single source of truth after schema retrieval.

Lifecycle:
  schema_ready  → baseline at awaitAllSpecs (post validation + schema merge)
  modification  → update_agent edit (upsert in place + change_log)
  proceed       → user confirmed vendor search
  vendor_results → pipeline finished (optional)
  reset         → cleared
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import logging

logger = logging.getLogger(__name__)


class ContextEvent(str, Enum):
    SCHEMA_READY = "schema_ready"
    MODIFICATION = "modification"
    PROCEED = "proceed"
    VENDOR_RESULTS = "vendor_results"
    RESET = "reset"


@dataclass
class SearchSessionContext:
    session_id: str
    workflow_step: str = "awaitAllSpecs"
    product_type: str = ""
    detected_schema: dict[str, Any] = field(default_factory=dict)
    mapped_requirements: dict[str, Any] = field(default_factory=dict)
    provided_requirements: dict[str, Any] = field(default_factory=dict)
    unmapped_specs: dict[str, Any] = field(default_factory=dict)
    missing_mandatory_fields: list[str] = field(default_factory=list)
    missing_optional_fields: list[str] = field(default_factory=list)
    missing_fields_friendly: list[str] = field(default_factory=list)
    missing_advanced_fields: list[str] = field(default_factory=list)
    missing_advanced_fields_friendly: list[str] = field(default_factory=list)
    specified_vendors: list[str] = field(default_factory=list)
    specified_model_families: list[str] = field(default_factory=list)
    applicable_standards: list[str] = field(default_factory=list)
    advanced_specs: list[Any] = field(default_factory=list)
    schema_source: str = ""
    input_range: str = "mid"
    validation_alert: dict[str, Any] | None = None
    collected_data_flat: dict[str, Any] = field(default_factory=dict)
    change_log: list[dict[str, Any]] = field(default_factory=list)
    context_summary: str = ""
    last_turn: dict[str, Any] = field(default_factory=dict)
    vendor_results: list[dict[str, Any]] = field(default_factory=list)
    last_user_input: str = ""
    version: int = 0
    updated_at: str = ""

    def bump_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now().isoformat()

    def to_merged_dict(self) -> dict[str, Any]:
        """Shape compatible with schema_merge helpers."""
        return {
            "product_type": self.product_type,
            "detected_schema": copy.deepcopy(self.detected_schema),
            "mapped_requirements": copy.deepcopy(self.mapped_requirements),
            "provided_requirements": copy.deepcopy(self.provided_requirements),
            "unmapped_specs": copy.deepcopy(self.unmapped_specs),
            "missing_mandatory_fields": list(self.missing_mandatory_fields),
            "missing_optional_fields": list(self.missing_optional_fields),
            "missing_fields_friendly": list(self.missing_fields_friendly),
            "missing_advanced_fields": list(self.missing_advanced_fields),
            "missing_advanced_fields_friendly": list(self.missing_advanced_fields_friendly),
            "specified_vendors": list(self.specified_vendors),
            "specified_model_families": list(self.specified_model_families),
            "applicable_standards": list(self.applicable_standards),
            "advanced_specs": list(self.advanced_specs),
            "schema_source": self.schema_source,
            "input_range": self.input_range,
            "validation_alert": self.validation_alert,
            "workflow_step": self.workflow_step,
        }

    def to_langgraph_state(self) -> dict[str, Any]:
        out = self.to_merged_dict()
        out.update({
            "detected_product_type": self.product_type,
            "structured_requirements": _json_dumps_safe(self.mapped_requirements),
            "session_id": self.session_id,
            "workflow_step": self.workflow_step,
        })
        return out

    def to_api_payload(self) -> dict[str, Any]:
        from domain.search.services.schema_merge import build_api_schema_payload

        payload = build_api_schema_payload(self.to_merged_dict())
        payload["nextStep"] = self.workflow_step
        payload["collectedData"] = dict(self.collected_data_flat)
        payload["changeLog"] = list(self.change_log[-5:])
        return payload

    def summary_for_intent(self, *, max_chars: int = 600) -> str:
        filled_m = _count_filled_leaves(self.mapped_requirements.get("mandatoryRequirements", {}))
        filled_o = _count_filled_leaves(self.mapped_requirements.get("optionalRequirements", {}))
        filled_a = _count_filled_leaves(self.mapped_requirements.get("advancedRequirements", {}))
        lines = [
            f"[SEARCH CONTEXT] Product: {self.product_type or 'unknown'} | Step: {self.workflow_step}",
            f"[Filled] mandatory={filled_m}, optional={filled_o}, advanced={filled_a}",
        ]
        if self.missing_mandatory_fields:
            preview = ", ".join(self.missing_mandatory_fields[:8])
            suffix = "..." if len(self.missing_mandatory_fields) > 8 else ""
            lines.append(f"[Missing mandatory] {preview}{suffix}")
        if self.change_log:
            last = self.change_log[-1]
            changes = last.get("changes_made") or []
            if changes:
                lines.append(f"[Last edit] {changes[0]}")
            elif last.get("user_input"):
                lines.append(f"[Last edit] {str(last['user_input'])[:80]}")
        if self.context_summary:
            lines.append(f"[Summary] {self.context_summary[:200]}")
        text = "\n".join(lines)
        return text[:max_chars]

    def update_rolling_summary(
        self,
        *,
        user_input: str = "",
        assistant_message: str = "",
        event: str = "",
    ) -> None:
        """Maintain a compact rolling summary for intent / LLM injection."""
        parts = [self.context_summary] if self.context_summary else []
        if user_input:
            parts.append(f"User: {user_input[:120]}")
        if assistant_message:
            parts.append(f"Assistant: {assistant_message[:160]}")
        if event:
            parts.append(f"Event: {event}")
        combined = " | ".join(p for p in parts if p)
        self.context_summary = combined[-4000:]
        if user_input or assistant_message:
            self.last_turn = {
                "user_input": user_input[:2000],
                "assistant_message": assistant_message[:4000],
                "timestamp": datetime.now().isoformat(),
            }

    def apply_merged(self, merged: dict[str, Any], *, workflow_step: str | None = None) -> None:
        self.product_type = merged.get("product_type", self.product_type) or self.product_type
        self.detected_schema = copy.deepcopy(merged.get("detected_schema") or self.detected_schema)
        self.mapped_requirements = copy.deepcopy(merged.get("mapped_requirements") or self.mapped_requirements)
        self.provided_requirements = copy.deepcopy(merged.get("provided_requirements") or self.provided_requirements)
        self.unmapped_specs = copy.deepcopy(merged.get("unmapped_specs") or self.unmapped_specs)
        self.missing_mandatory_fields = list(merged.get("missing_mandatory_fields") or [])
        self.missing_optional_fields = list(merged.get("missing_optional_fields") or [])
        self.missing_fields_friendly = list(merged.get("missing_fields_friendly") or [])
        self.missing_advanced_fields = list(merged.get("missing_advanced_fields") or [])
        self.missing_advanced_fields_friendly = list(
            merged.get("missing_advanced_fields_friendly") or []
        )
        self.specified_vendors = list(merged.get("specified_vendors") or self.specified_vendors)
        self.specified_model_families = list(
            merged.get("specified_model_families") or self.specified_model_families
        )
        self.applicable_standards = list(merged.get("applicable_standards") or self.applicable_standards)
        self.advanced_specs = list(merged.get("advanced_specs") or self.advanced_specs)
        self.schema_source = merged.get("schema_source", self.schema_source) or self.schema_source
        self.input_range = merged.get("input_range", self.input_range) or self.input_range
        self.validation_alert = merged.get("validation_alert", self.validation_alert)
        if workflow_step:
            self.workflow_step = workflow_step
        self._sync_collected_data_flat()

    def _sync_collected_data_flat(self) -> None:
        from domain.search.services.search_modification import flatten_tiered_mapped

        self.collected_data_flat = flatten_tiered_mapped(self.mapped_requirements)

    def record_modification(
        self,
        user_input: str,
        changes_made: list[str],
        *,
        filled_before: dict[str, int] | None = None,
        filled_after: dict[str, int] | None = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_input": user_input,
            "changes_made": list(changes_made),
        }
        if filled_before and filled_after:
            entry["filled_before"] = filled_before
            entry["filled_after"] = filled_after
        self.change_log.append(entry)
        self.last_user_input = user_input
        if len(self.change_log) > 50:
            self.change_log = self.change_log[-50:]


def _json_dumps_safe(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj)
    except Exception:
        return "{}"


def _count_filled_leaves(node: Any) -> int:
    from domain.search.services.schema_merge import is_empty_value

    if not isinstance(node, dict):
        return 0 if is_empty_value(node) else 1
    count = 0
    for v in node.values():
        if isinstance(v, dict):
            count += _count_filled_leaves(v)
        elif not is_empty_value(v):
            count += 1
    return count


def _filled_counts(mapped: dict[str, Any]) -> dict[str, int]:
    return {
        "mandatory": _count_filled_leaves(mapped.get("mandatoryRequirements", {})),
        "optional": _count_filled_leaves(mapped.get("optionalRequirements", {})),
        "advanced": _count_filled_leaves(mapped.get("advancedRequirements", {})),
    }


def context_from_merged(
    merged: dict[str, Any],
    session_id: str,
    *,
    workflow_step: str = "awaitAllSpecs",
) -> SearchSessionContext:
    ctx = SearchSessionContext(session_id=session_id, workflow_step=workflow_step)
    ctx.apply_merged(merged, workflow_step=workflow_step)
    ctx.bump_version()
    return ctx


def _meta_or_interim(meta: dict[str, Any], interim: dict[str, Any], key: str, default: Any = None) -> Any:
    """Priority-fallback read used throughout load_search_context's snapshot
    hydration: prefer the top-level metadata value, then the mid-workflow
    interim_state snapshot, then a default."""
    val = meta.get(key)
    if val:
        return val
    val = interim.get(key)
    if val:
        return val
    return default


def load_search_context(
    session_id: str,
    *,
    collected_data: dict[str, Any] | None = None,
    langgraph_state: dict[str, Any] | None = None,
    allow_client_overlay: bool = False,
) -> SearchSessionContext:
    """
    Load unified session context.

    Priority (production SSOT):
      1. Persisted snapshot (MongoDB-backed via search memory hydrate)
      2. In-request LangGraph state if newer than persisted version
      3. Optional client collected_data overlay (disabled by default)
    """
    from common.ai.memory.search import get_search_snapshot

    snapshot = get_search_snapshot(session_id) if session_id else None
    ctx = SearchSessionContext(session_id=session_id or "default")
    persisted_version = 0

    if snapshot:
        meta = snapshot.get("metadata", {}) or {}
        params = snapshot.get("search_params", {}) or {}
        interim = meta.get("interim_state", {}) or {}
        ctx.workflow_step = _meta_or_interim(meta, interim, "workflow_step", "awaitAllSpecs")
        ctx.product_type = meta.get("product_type") or params.get("detected_product_type") or interim.get("detected_product_type", "")
        ctx.detected_schema = copy.deepcopy(meta.get("schema") or interim.get("detected_schema") or {})
        raw_mapped = {k: v for k, v in params.items() if k not in ("unmapped_specs", "detected_product_type")}
        if not raw_mapped:
            raw_mapped = interim.get("mapped_requirements") or {}
        ctx.mapped_requirements = copy.deepcopy(raw_mapped)
        ctx.provided_requirements = copy.deepcopy(_meta_or_interim(meta, interim, "provided_requirements", {}))
        ctx.unmapped_specs = copy.deepcopy(
            params.get("unmapped_specs") or _meta_or_interim(meta, interim, "unmapped_specs", {})
        )
        ctx.missing_mandatory_fields = list(_meta_or_interim(meta, interim, "missing_mandatory_fields", []))
        ctx.missing_optional_fields = list(_meta_or_interim(meta, interim, "missing_optional_fields", []))
        ctx.missing_fields_friendly = list(_meta_or_interim(meta, interim, "missing_fields_friendly", []))
        ctx.missing_advanced_fields = list(_meta_or_interim(meta, interim, "missing_advanced_fields", []))
        ctx.missing_advanced_fields_friendly = list(
            _meta_or_interim(meta, interim, "missing_advanced_fields_friendly", [])
        )
        ctx.specified_vendors = list(_meta_or_interim(meta, interim, "specified_vendors", []))
        ctx.specified_model_families = list(_meta_or_interim(meta, interim, "specified_model_families", []))
        ctx.applicable_standards = list(_meta_or_interim(meta, interim, "applicable_standards", []))
        ctx.advanced_specs = list(_meta_or_interim(meta, interim, "advanced_specs", []))
        ctx.schema_source = _meta_or_interim(meta, interim, "schema_source", "")
        ctx.input_range = interim.get("input_range") or meta.get("input_range") or "mid"
        ctx.change_log = list(meta.get("change_log") or [])
        ctx.collected_data_flat = copy.deepcopy(meta.get("collected_data_flat") or {})
        ctx.context_summary = meta.get("context_summary") or ""
        ctx.last_turn = copy.deepcopy(meta.get("last_turn") or {})
        ctx.vendor_results = list(snapshot.get("results") or [])
        ctx.version = int(meta.get("context_version") or 0)
        ctx.updated_at = meta.get("context_updated_at") or ""
        persisted_version = ctx.version
        ctx._sync_collected_data_flat()

    langgraph_version = int((langgraph_state or {}).get("context_version") or 0)
    if langgraph_state and langgraph_state.get("mapped_requirements"):
        if langgraph_version >= persisted_version or not ctx.mapped_requirements:
            ctx.apply_merged({
                "product_type": langgraph_state.get("detected_product_type", ""),
                "detected_schema": langgraph_state.get("detected_schema", {}),
                "mapped_requirements": langgraph_state.get("mapped_requirements", {}),
                "provided_requirements": langgraph_state.get("provided_requirements", {}),
                "unmapped_specs": langgraph_state.get("unmapped_specs", {}),
                "missing_mandatory_fields": langgraph_state.get("missing_mandatory_fields", []),
                "missing_optional_fields": langgraph_state.get("missing_optional_fields", []),
                "missing_fields_friendly": langgraph_state.get("missing_fields_friendly", []),
                "missing_advanced_fields": langgraph_state.get("missing_advanced_fields", []),
                "missing_advanced_fields_friendly": langgraph_state.get(
                    "missing_advanced_fields_friendly", []
                ),
                "specified_vendors": langgraph_state.get("specified_vendors", []),
                "specified_model_families": langgraph_state.get("specified_model_families", []),
                "applicable_standards": langgraph_state.get("applicable_standards", []),
                "advanced_specs": langgraph_state.get("advanced_specs", []),
                "schema_source": langgraph_state.get("schema_source", ""),
                "input_range": langgraph_state.get("input_range", "mid"),
                "validation_alert": langgraph_state.get("validation_alert"),
            }, workflow_step=langgraph_state.get("workflow_step", ctx.workflow_step))
            ctx.change_log = list(langgraph_state.get("change_log") or ctx.change_log)
            ctx.version = langgraph_version or ctx.version

    if collected_data and (allow_client_overlay or not ctx.mapped_requirements):
        bootstrapped = _apply_collected_data_overlay(ctx, collected_data)
        if bootstrapped and not allow_client_overlay:
            logger.info(
                "[SEARCH_CONTEXT] Bootstrapped from client collected_data (no persisted context) session=%s",
                session_id,
            )
    elif collected_data and ctx.mapped_requirements:
        logger.debug(
            "[SEARCH_CONTEXT] Ignoring client collected_data overlay (backend SSOT) session=%s",
            session_id,
        )

    return ctx


def _apply_collected_data_overlay(ctx: "SearchSessionContext", collected_data: dict[str, Any]) -> bool:
    """Merge client-submitted flat collected_data into ctx.mapped_requirements.
    Shared by load_search_context's two overlay paths (explicit client-overlay
    mode, and no-persisted-context bootstrap). Returns True if a merge happened."""
    from domain.search.services.search_modification import (
        ensure_tiered_structure,
        merge_modification_delta,
        unflatten_dot_notation,
    )

    nested = unflatten_dot_notation(collected_data)
    if not nested:
        return False
    tiered = ensure_tiered_structure(nested)
    ctx.mapped_requirements = merge_modification_delta(ctx.mapped_requirements, tiered)
    ctx._sync_collected_data_flat()
    return True


def commit_search_context(
    ctx: SearchSessionContext,
    event: ContextEvent,
    *,
    user_input: str = "",
    assistant_message: str = "",
    changes_made: list[str] | None = None,
    vendor_results: list[dict[str, Any]] | None = None,
) -> None:
    """Persist session context for cross-request continuity."""
    from common.ai.memory.search import record_context_turn, upsert_search_snapshot

    if event == ContextEvent.RESET:
        ctx = SearchSessionContext(session_id=ctx.session_id, workflow_step="initialInput")

    if event == ContextEvent.PROCEED:
        ctx.workflow_step = "finalAnalysis"

    if event == ContextEvent.SCHEMA_READY:
        ctx.workflow_step = ctx.workflow_step or "awaitAllSpecs"

    if event == ContextEvent.VENDOR_RESULTS and vendor_results is not None:
        ctx.vendor_results = list(vendor_results)
        ctx.workflow_step = ctx.workflow_step or "finalAnalysis"

    ctx.update_rolling_summary(
        user_input=user_input,
        assistant_message=assistant_message,
        event=event.value,
    )
    ctx.bump_version()
    upsert_search_snapshot(
        ctx.session_id,
        _context_to_snapshot(ctx),
        event=event.value,
        vendor_results=vendor_results,
    )
    if user_input or assistant_message:
        record_context_turn(
            ctx.session_id,
            user_input=user_input,
            assistant_message=assistant_message,
            context_summary=ctx.context_summary,
        )
    logger.info(
        "[SEARCH_CONTEXT] commit session=%s event=%s step=%s version=%s",
        ctx.session_id,
        event.value,
        ctx.workflow_step,
        ctx.version,
    )


def commit_search_context_from_merged(
    session_id: str,
    merged: dict[str, Any],
    event: ContextEvent,
    *,
    workflow_step: str | None = None,
    user_input: str = "",
    assistant_message: str = "",
    changes_made: list[str] | None = None,
) -> SearchSessionContext:
    """Build context from merge output and commit (post schema retrieval)."""
    step = workflow_step or (
        "awaitAllSpecs" if event == ContextEvent.SCHEMA_READY else merged.get("workflow_step", "awaitAllSpecs")
    )
    existing = load_search_context(session_id)
    before_counts = _filled_counts(existing.mapped_requirements) if existing.mapped_requirements else {}
    if event == ContextEvent.SCHEMA_READY and not existing.mapped_requirements:
        ctx = context_from_merged(merged, session_id, workflow_step=step)
    else:
        ctx = existing
        ctx.apply_merged(merged, workflow_step=step)
    if event == ContextEvent.MODIFICATION and user_input:
        after_counts = _filled_counts(ctx.mapped_requirements)
        ctx.record_modification(
            user_input,
            changes_made or [],
            filled_before=before_counts,
            filled_after=after_counts,
        )
    commit_search_context(
        ctx,
        event,
        user_input=user_input,
        assistant_message=assistant_message,
        changes_made=changes_made,
    )
    return ctx


def commit_search_context_from_langgraph_state(
    session_id: str,
    state: dict[str, Any],
    event: ContextEvent,
    *,
    user_input: str = "",
    assistant_message: str = "",
    vendor_results: list[dict[str, Any]] | None = None,
) -> SearchSessionContext:
    """Sync LangGraph workflow state back to durable session context."""
    ctx = load_search_context(session_id, langgraph_state=state)
    merged = {
        "product_type": state.get("detected_product_type", ctx.product_type),
        "detected_schema": state.get("detected_schema", ctx.detected_schema),
        "mapped_requirements": state.get("mapped_requirements", ctx.mapped_requirements),
        "provided_requirements": state.get("provided_requirements", ctx.provided_requirements),
        "unmapped_specs": state.get("unmapped_specs", ctx.unmapped_specs),
        "missing_mandatory_fields": state.get("missing_mandatory_fields", ctx.missing_mandatory_fields),
        "missing_optional_fields": state.get("missing_optional_fields", ctx.missing_optional_fields),
        "missing_fields_friendly": state.get("missing_fields_friendly", ctx.missing_fields_friendly),
        "missing_advanced_fields": state.get("missing_advanced_fields", ctx.missing_advanced_fields),
        "missing_advanced_fields_friendly": state.get(
            "missing_advanced_fields_friendly", ctx.missing_advanced_fields_friendly,
        ),
        "specified_vendors": state.get("specified_vendors", ctx.specified_vendors),
        "specified_model_families": state.get("specified_model_families", ctx.specified_model_families),
        "applicable_standards": state.get("applicable_standards", ctx.applicable_standards),
        "advanced_specs": state.get("advanced_specs", ctx.advanced_specs),
        "schema_source": state.get("schema_source", ctx.schema_source),
        "input_range": state.get("input_range", ctx.input_range),
        "validation_alert": state.get("validation_alert", ctx.validation_alert),
        "workflow_step": state.get("workflow_step", ctx.workflow_step),
    }
    ctx.apply_merged(merged, workflow_step=merged.get("workflow_step"))
    ctx.change_log = list(state.get("change_log") or ctx.change_log)
    commit_search_context(
        ctx,
        event,
        user_input=user_input,
        assistant_message=assistant_message,
        vendor_results=vendor_results,
    )
    return ctx


def commit_vendor_results_from_state(
    session_id: str,
    state: dict[str, Any],
    *,
    assistant_message: str = "",
) -> None:
    """Persist vendor pipeline output into session context after analysis."""
    ranked = state.get("ranked_products") or []
    vendor_results = ranked if ranked else (state.get("vendor_matches") or [])
    commit_search_context_from_langgraph_state(
        session_id,
        state,
        ContextEvent.VENDOR_RESULTS,
        assistant_message=assistant_message,
        vendor_results=vendor_results,
    )


def _context_to_snapshot(ctx: SearchSessionContext) -> dict[str, Any]:
    mapped = copy.deepcopy(ctx.mapped_requirements)
    return {
        "search_params": {
            **mapped,
            "unmapped_specs": ctx.unmapped_specs,
            "detected_product_type": ctx.product_type,
        },
        "results": [],
        "metadata": {
            "product_type": ctx.product_type,
            "schema": ctx.detected_schema,
            "schema_source": ctx.schema_source,
            "provided_requirements": ctx.provided_requirements,
            "unmapped_specs": ctx.unmapped_specs,
            "missing_mandatory_fields": ctx.missing_mandatory_fields,
            "missing_optional_fields": ctx.missing_optional_fields,
            "missing_fields_friendly": ctx.missing_fields_friendly,
            "missing_advanced_fields": ctx.missing_advanced_fields,
            "missing_advanced_fields_friendly": ctx.missing_advanced_fields_friendly,
            "specified_vendors": ctx.specified_vendors,
            "specified_model_families": ctx.specified_model_families,
            "applicable_standards": ctx.applicable_standards,
            "advanced_specs": ctx.advanced_specs,
            "workflow_step": ctx.workflow_step,
            "change_log": ctx.change_log,
            "collected_data_flat": ctx.collected_data_flat,
            "context_version": ctx.version,
            "context_updated_at": ctx.updated_at,
            "context_summary": ctx.context_summary,
            "last_turn": ctx.last_turn,
            "last_user_input": ctx.last_user_input,
            "interim_state": {
                "detected_product_type": ctx.product_type,
                "mapped_requirements": ctx.mapped_requirements,
                "detected_schema": ctx.detected_schema,
                "provided_requirements": ctx.provided_requirements,
                "unmapped_specs": ctx.unmapped_specs,
                "missing_mandatory_fields": ctx.missing_mandatory_fields,
                "missing_optional_fields": ctx.missing_optional_fields,
                "missing_fields_friendly": ctx.missing_fields_friendly,
                "missing_advanced_fields": ctx.missing_advanced_fields,
                "missing_advanced_fields_friendly": ctx.missing_advanced_fields_friendly,
                "advanced_specs": ctx.advanced_specs,
                "specified_vendors": ctx.specified_vendors,
                "specified_model_families": ctx.specified_model_families,
                "applicable_standards": ctx.applicable_standards,
                "schema_source": ctx.schema_source,
                "workflow_step": ctx.workflow_step,
                "input_range": ctx.input_range,
            },
        },
    }


def build_context_api_envelope(ctx: SearchSessionContext) -> dict[str, Any]:
    """CamelCase context metadata for API / frontend SSOT sync."""
    payload = ctx.to_api_payload()
    return {
        "contextVersion": ctx.version,
        "contextUpdatedAt": ctx.updated_at,
        "contextSummary": ctx.context_summary,
        "lastTurn": ctx.last_turn,
        "changeLog": payload.get("changeLog", []),
        "collectedData": payload.get("collectedData", {}),
        "nextStep": ctx.workflow_step,
        "productType": ctx.product_type,
        "mappedRequirements": ctx.mapped_requirements,
        "requirementSchema": payload.get("requirementSchema"),
        "missingFields": ctx.missing_mandatory_fields,
        "missingOptionalFields": ctx.missing_optional_fields,
        "missingAdvancedFields": ctx.missing_advanced_fields,
        "vendorResultsCount": len(ctx.vendor_results),
    }


def enrich_response_with_context(session_id: str, response: dict[str, Any]) -> dict[str, Any]:
    """
    Attach latest persisted context fields to an API response.
    Backend collectedData wins over any stale client state.
    """
    if not session_id:
        return response
    try:
        ctx = load_search_context(session_id)
        if not ctx.mapped_requirements and not ctx.product_type:
            return response
        envelope = build_context_api_envelope(ctx)
        for key, val in envelope.items():
            if val is not None and val != "" and val != {} and val != []:
                response[key] = val
        response["contextSynced"] = True
    except Exception as exc:
        logger.warning("[SEARCH_CONTEXT] enrich_response failed session=%s: %s", session_id, exc)
    return response

