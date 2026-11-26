"""
Unified schema + value merge for the Search workflow.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from domain.search.services.schema_field_matching import (
    _EMPTY_VALUES,
    is_empty_value,
    normalize_field_name as _normalize_field_name,
)

logger = logging.getLogger(__name__)


def _friendly_name(field: str) -> str:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    return spaced.replace("_", " ").title()


def _is_nested_node(val: Any) -> bool:
    return isinstance(val, dict) and any(isinstance(v, dict) for v in val.values())


def _spec_field_name(spec: dict[str, Any]) -> str | None:
    """A spec dict's field name, whichever key it was stored under."""
    return spec.get("field") or spec.get("name") or spec.get("key")


def _spec_category(spec: dict[str, Any]) -> str:
    """A spec dict's category, defaulting to 'General' if absent/blank."""
    category = spec.get("category") or "General"
    return str(category) if str(category).strip() else "General"


def _deep_merge_dict(base: dict, overlay: dict) -> dict:
    """Merge ``overlay`` into ``base`` without clobbering non-empty base values."""
    result = copy.deepcopy(base)
    for key, oval in overlay.items():
        if key not in result:
            result[key] = copy.deepcopy(oval)
            continue
        bval = result[key]
        if isinstance(bval, dict) and isinstance(oval, dict):
            result[key] = _deep_merge_dict(bval, oval)
        elif is_empty_value(bval) and not is_empty_value(oval):
            result[key] = oval
    return result


def _schema_from_specs_list(specs_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a nested advancedRequirements schema tree grouped by category."""
    tree: dict[str, Any] = {}
    for spec in specs_list or []:
        name = _spec_field_name(spec)
        if not name:
            continue
        category = _spec_category(spec)
        tree.setdefault(category, {})
        tree[category][str(name)] = ""
    return tree


def normalize_schema_advanced_tiers(detected_schema: dict[str, Any]) -> None:
    """
    Promote ``latestRequirements`` into ``advancedRequirements`` in-place.

    The UI reads ``advancedRequirements`` only; ``latestRequirements`` is kept
    internally until merge completes, then removed from the outward contract.
    """
    if not isinstance(detected_schema, dict):
        return

    latest = detected_schema.get("latestRequirements") or {}
    advanced = detected_schema.get("advancedRequirements") or {}

    if latest and not advanced:
        detected_schema["advancedRequirements"] = copy.deepcopy(latest)
    elif latest and advanced:
        if _is_nested_node(latest) or _is_nested_node(advanced):
            detected_schema["advancedRequirements"] = _deep_merge_dict(
                copy.deepcopy(latest) if _is_nested_node(latest) else {"General": copy.deepcopy(latest)},
                copy.deepcopy(advanced) if _is_nested_node(advanced) else {"General": copy.deepcopy(advanced)},
            )
        else:
            detected_schema["advancedRequirements"] = {**copy.deepcopy(latest), **copy.deepcopy(advanced)}


def build_advanced_schema_structure(
    detected_schema: dict[str, Any],
    advanced_specs_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve the advancedRequirements schema tree used by the sidebar."""
    normalize_schema_advanced_tiers(detected_schema)
    existing = detected_schema.get("advancedRequirements") or {}

    if existing:
        base = copy.deepcopy(existing)
    else:
        base = _schema_from_specs_list(advanced_specs_list)

    # Ensure every field from the agent list exists in the schema tree.
    for spec in advanced_specs_list or []:
        name = _spec_field_name(spec)
        if not name:
            continue
        category = _spec_category(spec)
        if _is_nested_node(base):
            base.setdefault(category, {})
            base[category].setdefault(str(name), "")
        else:
            base.setdefault(str(name), "")

    return base


def _specs_list_to_field_names(specs_list: list[dict[str, Any]]) -> set[str]:
    """Field names from advanced_specs_agent — structure only, not DB default values."""
    names: set[str] = set()
    for spec in specs_list or []:
        name = _spec_field_name(spec)
        if name:
            names.add(str(name))
    return names


def _collect_mapped_leaf_index(mapped: dict[str, Any]) -> dict[str, str]:
    """Collect non-empty mapped leaf values keyed by field name (exact + normalized)."""
    index: dict[str, str] = {}

    def _walk(node: Any):
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            if isinstance(val, dict):
                _walk(val)
            elif not is_empty_value(val):
                text = str(val).strip()
                index[str(key)] = text
                index[_normalize_field_name(str(key))] = text

    for tier in (
        "mandatoryRequirements",
        "optionalRequirements",
        "advancedRequirements",
    ):
        _walk(mapped.get(tier) or {})
    return index


def build_extraction_value_index(
    provided_requirements: dict[str, Any],
    mapped_requirements: dict[str, Any],
    unmapped_specs: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Unified lookup of user-sourced values for populating all schema tiers.

    Priority when resolving a schema field: exact key, normalized key, then fuzzy
    substring match against provided / unmapped keys.
    """
    index: dict[str, str] = {}

    def _ingest_flat(source: dict[str, Any]):
        for key, raw in (source or {}).items():
            if is_empty_value(raw):
                continue
            text = str(raw).strip()
            index[str(key)] = text
            nk = _normalize_field_name(str(key))
            if nk:
                index[nk] = text

    _ingest_flat(provided_requirements)
    _ingest_flat(unmapped_specs or {})
    index.update(_collect_mapped_leaf_index(mapped_requirements))
    return index


def _lookup_extraction_value(key: str, value_index: dict[str, str]) -> str:
    """Resolve a schema field using key index built from extracted user values only."""
    if key in value_index and not is_empty_value(value_index[key]):
        return value_index[key]
    nk = _normalize_field_name(key)
    if nk in value_index and not is_empty_value(value_index[nk]):
        return value_index[nk]
    from domain.search.services.schema_field_matching import (
        field_match_score,
        fuzzy_field_name_match,
    )

    for pk, pv in value_index.items():
        if is_empty_value(pv):
            continue
        if fuzzy_field_name_match(key, pk):
            return pv
        if field_match_score(key, pk) >= 0.72:
            return pv
    return ""


def _prune_schema_tier_for_display(schema_node: dict[str, Any], mapped_node: dict[str, Any]) -> dict[str, Any]:
    """Keep only schema branches that have a non-empty mapped user value."""
    if not isinstance(schema_node, dict):
        return {}
    pruned: dict[str, Any] = {}
    for key, schema_val in schema_node.items():
        if isinstance(schema_val, dict):
            child_mapped = mapped_node.get(key, {}) if isinstance(mapped_node, dict) else {}
            child = _prune_schema_tier_for_display(schema_val, child_mapped if isinstance(child_mapped, dict) else {})
            if child:
                pruned[key] = child
        else:
            mapped_val = mapped_node.get(key) if isinstance(mapped_node, dict) else None
            if not is_empty_value(mapped_val):
                pruned[key] = ""
    return pruned


def build_display_schema(
    detected_schema: dict[str, Any],
    mapped_requirements: dict[str, Any],
) -> dict[str, Any]:
    """
    Sidebar display schema: show ALL mandatory fields (including gaps),
    but only optional/advanced fields the user actually provided values for.
    """
    display: dict[str, Any] = {}
    mandatory_schema = detected_schema.get("mandatoryRequirements") or {}
    if mandatory_schema:
        display["mandatoryRequirements"] = sanitize_schema_template_leaves(
            copy.deepcopy(mandatory_schema)
        )

    optional_schema = detected_schema.get("optionalRequirements") or {}
    optional_mapped = mapped_requirements.get("optionalRequirements") or {}
    pruned_optional = _prune_schema_tier_for_display(optional_schema, optional_mapped)
    if pruned_optional:
        display["optionalRequirements"] = pruned_optional

    advanced_schema = detected_schema.get("advancedRequirements") or {}
    advanced_mapped = mapped_requirements.get("advancedRequirements") or {}
    pruned_advanced = _prune_schema_tier_for_display(advanced_schema, advanced_mapped)
    if pruned_advanced:
        display["advancedRequirements"] = pruned_advanced

    return display


def sanitize_schema_template_leaves(schema_node: Any) -> Any:
    """Return a copy of the schema tree with all leaves set to empty strings."""
    if isinstance(schema_node, dict):
        return {
            k: sanitize_schema_template_leaves(v) if isinstance(v, dict) else ""
            for k, v in schema_node.items()
        }
    return ""


def _populate_mapped_section(
    mapped_node: dict[str, Any],
    schema_node: dict[str, Any],
    value_index: dict[str, str],
    *,
    use_schema_template_fallback: bool = False,
) -> None:
    """Fill ``mapped_node`` leaves from extraction index; preserve existing user values."""
    for key, schema_val in schema_node.items():
        if isinstance(schema_val, dict):
            mapped_node.setdefault(key, {})
            if not isinstance(mapped_node[key], dict):
                mapped_node[key] = {}
            _populate_mapped_section(
                mapped_node[key],
                schema_val,
                value_index,
                use_schema_template_fallback=use_schema_template_fallback,
            )
        else:
            current = mapped_node.get(key)
            if not is_empty_value(current):
                continue
            resolved = _lookup_extraction_value(key, value_index)
            if is_empty_value(resolved) and use_schema_template_fallback and not is_empty_value(schema_val):
                resolved = str(schema_val).strip()
            mapped_node[key] = resolved if not is_empty_value(resolved) else ""


def _propagate_filled_values_across_tiers(mapped: dict[str, Any], schema: dict[str, Any]) -> None:
    """
    Copy already-mapped values into empty leaves in other tiers when the normalized
    field name matches (e.g. accuracy mapped in optional fills advanced accuracy).
    """
    filled = _collect_mapped_leaf_index(mapped)
    if not filled:
        return

    tier_pairs = (
        ("mandatoryRequirements", schema.get("mandatoryRequirements") or {}),
        ("optionalRequirements", schema.get("optionalRequirements") or {}),
        ("advancedRequirements", schema.get("advancedRequirements") or {}),
    )

    for _tier_name, schema_tier in tier_pairs:
        if not schema_tier:
            continue
        mapped.setdefault(_tier_name, {})
        _populate_mapped_section(
            mapped[_tier_name],
            schema_tier,
            filled,
            use_schema_template_fallback=False,
        )


def _assign_unmapped_specs_to_schema(
    mapped: dict[str, Any],
    schema: dict[str, Any],
    unmapped_specs: dict[str, Any],
) -> None:
    """Place still-unmapped user specs onto the best matching empty schema leaf."""
    if not unmapped_specs:
        return

    from domain.search.services.schema_field_matching import (
        _best_leaf_for_provided_key,
        _get_leaf,
        _set_leaf,
    )

    ranked: list[tuple[tuple[str, Any], float]] = []
    for uk, uv in unmapped_specs.items():
        if is_empty_value(uv):
            continue
        leaf, score = _best_leaf_for_provided_key(schema, uk)
        if leaf and score >= 0.72:
            ranked.append(((uk, uv), score))

    ranked.sort(key=lambda x: x[1], reverse=True)

    for (uk, uv), _score in ranked:
        leaf, score = _best_leaf_for_provided_key(schema, uk)
        if not leaf or score < 0.72:
            continue
        if is_empty_value(_get_leaf(mapped, leaf)):
            _set_leaf(mapped, leaf, uv)
            logger.info("[SCHEMA_MERGE] Assigned unmapped '%s' → %s.%s", uk, leaf.tier, leaf.field_key)


def enrich_mapped_requirements(
    mapped_requirements: dict[str, Any],
    detected_schema: dict[str, Any],
    provided_requirements: dict[str, Any],
    unmapped_specs: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Backfill and cross-tier propagate user-extracted values into mandatory,
    optional, and advanced mapped sections. Returns the extraction value index.
    """
    from domain.search.agents.validation_agent import _backfill_mapped_from_provided
    from domain.search.services.schema_field_matching import (
        assign_provided_to_schema_catalog,
        reassign_misplaced_mapped_values,
    )

    combined_provided = {**(provided_requirements or {}), **(unmapped_specs or {})}

    assign_provided_to_schema_catalog(mapped_requirements, detected_schema, combined_provided)
    _backfill_mapped_from_provided(mapped_requirements, detected_schema, combined_provided)

    extraction_index = build_extraction_value_index(
        provided_requirements,
        mapped_requirements,
        unmapped_specs,
    )

    for tier, schema_tier in (
        ("mandatoryRequirements", detected_schema.get("mandatoryRequirements") or {}),
        ("optionalRequirements", detected_schema.get("optionalRequirements") or {}),
        ("advancedRequirements", detected_schema.get("advancedRequirements") or {}),
    ):
        if not schema_tier:
            continue
        mapped_requirements.setdefault(tier, {})
        if not isinstance(mapped_requirements[tier], dict):
            mapped_requirements[tier] = {}
        _populate_mapped_section(
            mapped_requirements[tier],
            schema_tier,
            extraction_index,
            use_schema_template_fallback=False,
        )

    reassign_misplaced_mapped_values(mapped_requirements, detected_schema, combined_provided)
    _propagate_filled_values_across_tiers(mapped_requirements, detected_schema)

    _assign_unmapped_specs_to_schema(
        mapped_requirements,
        detected_schema,
        unmapped_specs or {},
    )

    reassign_misplaced_mapped_values(mapped_requirements, detected_schema, combined_provided)

    return build_extraction_value_index(
        provided_requirements,
        mapped_requirements,
        unmapped_specs,
    )


def _merge_mapped_sections(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Deep-merge ``source`` into ``target`` without overwriting non-empty values."""
    for key, sval in (source or {}).items():
        if isinstance(sval, dict):
            target.setdefault(key, {})
            if isinstance(target[key], dict):
                _merge_mapped_sections(target[key], sval)
            else:
                target[key] = copy.deepcopy(sval)
        elif is_empty_value(target.get(key)) and not is_empty_value(sval):
            target[key] = sval


def _get_missing_advanced_fields(mapped: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    from domain.search.agents.validation_agent import _get_filled_normalized_keys, _is_ignored_key

    missing: list[str] = []
    advanced = schema.get("advancedRequirements") or {}
    provided = mapped.get("advancedRequirements") or {}
    filled_normalized = _get_filled_normalized_keys(mapped)

    def _traverse(schema_node: dict, provided_node: dict):
        for key, schema_val in schema_node.items():
            if isinstance(schema_val, dict):
                next_provided = provided_node.get(key, {}) if isinstance(provided_node, dict) else {}
                _traverse(schema_val, next_provided)
            else:
                pval = provided_node.get(key) if isinstance(provided_node, dict) else None
                if is_empty_value(pval):
                    if not _is_ignored_key(key):
                        nk = _normalize_field_name(key)
                        if nk not in filled_normalized:
                            missing.append(key)

    _traverse(advanced, provided)
    return missing


def merge_validation_and_advanced(
    validation_result: dict[str, Any],
    advanced_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Merge validation + advanced specs into one response dict.

    Returns a copy of ``validation_result`` with updated schema/mapped/missing
    fields and advanced-spec metadata.
    """
    merged = copy.deepcopy(validation_result or {})
    detected_schema = copy.deepcopy(merged.get("detected_schema") or {})
    mapped_requirements = copy.deepcopy(merged.get("mapped_requirements") or {})
    provided_requirements = copy.deepcopy(merged.get("provided_requirements") or {})
    unmapped_specs = copy.deepcopy(merged.get("unmapped_specs") or {})

    advanced_specs_list = (advanced_result or {}).get("advanced_specs", []) or []

    advanced_schema = build_advanced_schema_structure(detected_schema, advanced_specs_list)
    detected_schema["advancedRequirements"] = sanitize_schema_template_leaves(advanced_schema)

    # Drop legacy tier from outward contract — UI uses advancedRequirements only.
    detected_schema.pop("latestRequirements", None)

    mapped_requirements.setdefault("advancedRequirements", {})
    if not isinstance(mapped_requirements["advancedRequirements"], dict):
        mapped_requirements["advancedRequirements"] = {}

    # Carry over any values that were stored under latestRequirements.
    latest_mapped = (validation_result or {}).get("mapped_requirements", {}).get("latestRequirements")
    if isinstance(latest_mapped, dict):
        _merge_mapped_sections(mapped_requirements["advancedRequirements"], latest_mapped)
    mapped_requirements.pop("latestRequirements", None)

    # Enrich all tiers from extracted / mapped user values (not DB defaults).
    enrich_mapped_requirements(
        mapped_requirements,
        detected_schema,
        provided_requirements,
        unmapped_specs,
    )

    # Sanitize mandatory/optional template leaves so sidebar does not show DB placeholders.
    for tier in ("mandatoryRequirements", "optionalRequirements"):
        if detected_schema.get(tier):
            detected_schema[tier] = sanitize_schema_template_leaves(detected_schema[tier])

    missing = recompute_missing_after_update(mapped_requirements, detected_schema)

    merged.update({
        "detected_schema": detected_schema,
        "mapped_requirements": mapped_requirements,
        "missing_mandatory_fields": missing["missing_mandatory_fields"],
        "missing_optional_fields": missing["missing_optional_fields"],
        "missing_fields_friendly": missing["missing_fields_friendly"],
        "missing_advanced_fields": missing["missing_advanced_fields"],
        "missing_advanced_fields_friendly": missing["missing_advanced_fields_friendly"],
        "advanced_specs": advanced_specs_list,
        "advanced_specs_message": (advanced_result or {}).get("response_message", ""),
        "advanced_specs_action": (advanced_result or {}).get("action", "auto_include"),
    })

    logger.info(
        "[SCHEMA_MERGE] merged tiers — mandatory_missing=%s optional_missing=%s "
        "advanced_missing=%s advanced_populated=%s",
        len(missing["missing_mandatory_fields"]),
        len(missing["missing_optional_fields"]),
        len(missing["missing_advanced_fields"]),
        sum(1 for _ in _count_filled_leaves(mapped_requirements.get("advancedRequirements", {}))),
    )
    return merged


def _count_filled_leaves(node: Any):
    if isinstance(node, dict):
        for v in node.values():
            if isinstance(v, dict):
                yield from _count_filled_leaves(v)
            elif not is_empty_value(v):
                yield v


def run_parallel_requirements_extraction(
    user_input: str,
    *,
    pre_product_type: str = "",
    skip_standard_rag: bool = False,
    user_id: int | None = None,
    stream_id: str | None = None,
    pre_mapped: dict | None = None,
) -> dict[str, Any]:
    """
    Run validation_agent and advanced_specs_agent in parallel, then merge.

    Used by both the LangGraph orchestrator and the REST API entrypoint so they
    share identical schema-population behaviour.
    """
    from domain.search.agents.advanced_specs_agent import run_advanced_specs_discovery
    from domain.search.agents.validation_agent import run_validation_agent

    pre_pt = (pre_product_type or "").strip()

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_validation = executor.submit(
            run_validation_agent,
            user_input,
            skip_standard_rag=skip_standard_rag,
            user_id=user_id,
            stream_id=stream_id,
            pre_mapped=pre_mapped,
            known_product_type=pre_pt,
        )
        future_advanced = (
            executor.submit(run_advanced_specs_discovery, pre_pt, stream_id=stream_id)
            if pre_pt
            else None
        )
        validation_result = future_validation.result()
        advanced_result = future_advanced.result() if future_advanced else None

    canonical_pt = (validation_result.get("product_type") or "").strip()
    if canonical_pt and (
        advanced_result is None
        or pre_pt.lower() != canonical_pt.lower()
    ):
        try:
            advanced_result = run_advanced_specs_discovery(canonical_pt, stream_id=stream_id)
        except Exception as exc:
            logger.warning("[SCHEMA_MERGE] Fallback advanced_specs failed: %s", exc)

    return merge_validation_and_advanced(validation_result, advanced_result)


def apply_merged_extraction_to_state(state: dict[str, Any], merged: dict[str, Any]) -> None:
    """Write merged extraction fields onto a LangGraph ``AgenticSystemState`` dict."""
    state["detected_product_type"] = merged.get("product_type", "")
    state["provided_requirements"] = merged.get("provided_requirements", {})
    state["mapped_requirements"] = merged.get("mapped_requirements", {})
    state["unmapped_specs"] = merged.get("unmapped_specs", {})
    state["detected_schema"] = merged.get("detected_schema", {})
    state["schema_source"] = merged.get("schema_source", "")
    state["specified_vendors"] = merged.get("specified_vendors", [])
    state["specified_model_families"] = merged.get("specified_model_families", [])
    state["applicable_standards"] = merged.get("applicable_standards", [])
    state["strategy"] = merged.get("strategy", "")
    state["input_range"] = merged.get("input_range", "mid")
    state["missing_mandatory_fields"] = merged.get("missing_mandatory_fields", [])
    state["missing_optional_fields"] = merged.get("missing_optional_fields", [])
    state["missing_fields_friendly"] = merged.get("missing_fields_friendly", [])
    state["missing_advanced_fields"] = merged.get("missing_advanced_fields", [])
    state["missing_advanced_fields_friendly"] = merged.get("missing_advanced_fields_friendly", [])
    state["validation_alert"] = merged.get("validation_alert")
    state["advanced_specs"] = merged.get("advanced_specs", [])
    state["advanced_specs_message"] = merged.get("advanced_specs_message", "")
    state["advanced_specs_action"] = merged.get("advanced_specs_action", "auto_include")

    mapped_reqs = merged.get("mapped_requirements") or {}
    provided_reqs = merged.get("provided_requirements") or {}
    user_input = state.get("user_input", "")
    if mapped_reqs:
        state["structured_requirements"] = json.dumps(mapped_reqs)
    elif provided_reqs:
        state["structured_requirements"] = json.dumps(provided_reqs)
    else:
        state["structured_requirements"] = user_input


def commit_context_after_extraction(
    session_id: str,
    merged: dict[str, Any],
    *,
    workflow_step: str = "awaitAllSpecs",
    user_input: str = "",
    assistant_message: str = "",
) -> None:
    """Persist unified session context immediately after schema retrieval + merge."""
    if not session_id:
        return
    from domain.search.services.search_session_context import (
        ContextEvent,
        commit_search_context_from_merged,
    )

    commit_search_context_from_merged(
        session_id,
        merged,
        ContextEvent.SCHEMA_READY,
        workflow_step=workflow_step,
        user_input=user_input,
        assistant_message=assistant_message,
    )


def build_api_schema_payload(merged: dict[str, Any]) -> dict[str, Any]:
    """CamelCase-friendly payload fragment for ``search.py`` responses."""
    from domain.search.services.search_modification import flatten_tiered_mapped

    detected_schema = merged.get("detected_schema", {})
    mapped_requirements = merged.get("mapped_requirements", {})
    return {
        "productType": merged.get("product_type", ""),
        "requirementSchema": build_display_schema(detected_schema, mapped_requirements),
        "mappedRequirements": mapped_requirements,
        "collectedData": flatten_tiered_mapped(mapped_requirements),
        "missingFields": merged.get("missing_mandatory_fields", []),
        "missingFieldsFriendly": merged.get("missing_fields_friendly", []),
        "missingOptionalFields": merged.get("missing_optional_fields", []),
        "missingAdvancedFields": merged.get("missing_advanced_fields", []),
        "missingAdvancedFieldsFriendly": merged.get("missing_advanced_fields_friendly", []),
        "validationAlert": merged.get("validation_alert"),
        "specifiedVendors": merged.get("specified_vendors", []),
        "specifiedModelFamilies": merged.get("specified_model_families", []),
        "strategy": merged.get("strategy", ""),
        "schemaSource": merged.get("schema_source", ""),
        "standardSpecs": merged.get("standard_specs", {}),
        "standardSpecsSource": merged.get("standard_specs_source"),
        "advancedSpecs": merged.get("advanced_specs", []),
    }


def recompute_missing_after_update(
    mapped_requirements: dict[str, Any],
    detected_schema: dict[str, Any],
) -> dict[str, Any]:
    """Recompute all three missing-field lists after a user edit."""
    from domain.search.agents.validation_agent import (
        _get_missing_mandatory_fields,
        _get_missing_optional_fields,
    )

    missing_mandatory = _get_missing_mandatory_fields(mapped_requirements, detected_schema)
    missing_optional = _get_missing_optional_fields(mapped_requirements, detected_schema)
    missing_advanced = _get_missing_advanced_fields(mapped_requirements, detected_schema)
    return {
        "missing_mandatory_fields": missing_mandatory,
        "missing_optional_fields": missing_optional,
        "missing_fields_friendly": [_friendly_name(f) for f in missing_mandatory],
        "missing_advanced_fields": missing_advanced,
        "missing_advanced_fields_friendly": [_friendly_name(f) for f in missing_advanced],
    }
