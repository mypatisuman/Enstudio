"""
Node 2 — Expansion Agent (Standards Match + L3 Spec-Doc Values)

Expands each instrument/accessory using:
  1. Standards RAG — retrieves applicable engineering standards per category
  2. L3 Spec-Doc Values — extracts specs from manufacturer datasheet documents
"""

import json
import logging
import os
import sys
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from typing import Any

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from domain.orchestrator.state import AgenticSystemState
from domain.solution.memory import append_node_execution_context
from common.helpers.node_retry import retryable_node
from common.helpers.progress_tracker import progress_tracker
from common.ai.llm import SOLUTION_LLM_PROVIDER, with_json_mode
from common.infra.azure_blob import azure_blob_manager
from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
from common.services.file_extractor import extract_text_from_file
from domain.solution.agents.shared import _load_prompt, _parse_llm_json, llm_pro
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

SPEC_DOC_VALUE_EXTRACTION_PROMPT = _load_prompt("spec_doc_value_extraction.md")


_MAX_SPEC_DOC_TEXT = 25000


def _normalize_key(k: str) -> str:
    """Normalize a specification field name so camelCase/snake_case/spaces collapse."""
    return k.lower().replace("_", "").replace(" ", "")


def _extract_spec_doc_values(category: str, schema_fields: list[str], text: str) -> dict:
    """Use the Pro LLM to extract values for the given schema fields from datasheet text."""
    if not schema_fields or not text:
        return {}
    prompt = ChatPromptTemplate.from_template(SPEC_DOC_VALUE_EXTRACTION_PROMPT)
    chain = prompt | with_json_mode(llm_pro, SOLUTION_LLM_PROVIDER) | StrOutputParser()
    response = chain.invoke(
        {
            "category": category,
            "schema_fields": json.dumps(schema_fields, indent=2),
            "text": text[:_MAX_SPEC_DOC_TEXT],
        }
    )
    parsed = _parse_llm_json(response) or {}
    return parsed.get("values") or {}


def collect_schema_parameter_names(schema: dict) -> list[str]:
    """Collect ALL parameter names for a node across the L0/L1/L2 band cascade.

    Uses the view-based bidirectional cascade (same source as harness/format agents)
    so ancestor and descendant parameter names from L0/L1/L2 views are all included.
    This gives the PDF extractor the full schema field list to search for, not just
    the matched node's own params.
    """
    if not schema:
        return []

    name = schema.get("name") or schema.get("category") or ""
    if name:
        try:
            # resolve_parameters_schema_by_name uses the view-based cascade (L0/L1/L2 views)
            # and returns {mandatoryRequirements, optionalRequirements, latestRequirements}
            cascaded = ProductHierarchyRepository.resolve_parameters_schema_by_name(name) or {}
            all_names = []
            seen: set = set()
            for tier in ("mandatoryRequirements", "optionalRequirements", "latestRequirements"):
                for param_name in cascaded.get(tier, {}):
                    if param_name and param_name not in seen:
                        seen.add(param_name)
                        all_names.append(param_name)
            if all_names:
                return all_names
        except Exception as e:
            logger.warning(f"[EXPANSION] cascade param names failed for '{name}': {e}")

    # Fallback: read directly from the node's own specifications block
    names = []
    seen = set()
    specs = schema.get("specifications") if "specifications" in schema else schema
    if isinstance(specs, dict):
        for key, section in specs.items():
            if key == "id" or not isinstance(section, dict):
                continue
            for param in (section.get("parameters") or []):
                if isinstance(param, dict):
                    pname = param.get("name")
                    if pname and pname not in seen:
                        seen.add(pname)
                        names.append(pname)
    return names


def populate_schema_values(schema: dict, extracted_values: dict[str, Any]) -> dict:
    """Update specifications parameters in schema with extracted values, matching by 'name'."""
    if not schema or not extracted_values:
        return schema
    
    specs = schema.get("specifications") if "specifications" in schema else schema
    if not isinstance(specs, dict):
        return schema

    for key, section in specs.items():
        if key == "id" or not isinstance(section, dict):
            continue
        parameters = section.get("parameters") or []
        for param in parameters:
            if isinstance(param, dict):
                name = param.get("name")
                if name and name in extracted_values:
                    param["value"] = extracted_values[name]
    return schema


def _get_spec_doc_values_for_category(category: str) -> dict:
    """Fetch L3 datasheet URL, download/extract text, and pull schema field values."""
    try:
        node = ProductHierarchyRepository.find_node_by_name(category)
        if not node:
            logger.info(f"[EXPANSION] Node not found for '{category}'")
            return {}

        node_type = node.get("type", "Equipment")
        if node_type != "Equipment":
            logger.info(f"[EXPANSION] Skipping L3 spec-doc extraction for '{category}' (type={node_type})")
            return {}

        spec_doc_url = ProductHierarchyRepository.get_l3_spec_doc_url(category)
        if not spec_doc_url:
            logger.info(f"[EXPANSION] No L3 spec-doc URL for '{category}'")
            return {}

        schema_fields = collect_schema_parameter_names(node)
        if not schema_fields:
            logger.info(f"[EXPANSION] No schema fields for '{category}'")
            return {}

        logger.info(f"[EXPANSION] Fetching L3 spec-doc for '{category}': {spec_doc_url}")
        file_bytes = azure_blob_manager.download_document_from_url(spec_doc_url)
        filename = spec_doc_url.split("/")[-1] or "spec.pdf"
        extraction = extract_text_from_file(file_bytes, filename)
        text = extraction.get("extracted_text", "")
        if not extraction.get("success") or not text:
            logger.warning(f"[EXPANSION] Text extraction failed or empty for '{category}': {extraction.get('error')}")
            return {}

        values = _extract_spec_doc_values(category, schema_fields, text)
        if values:
            populate_schema_values(node, values)
            logger.info(f"[EXPANSION] Extracted {len(values)} datasheet value(s) for '{category}'")
        return values
    except Exception as e:
        logger.warning(f"[EXPANSION] L3 spec-doc value extraction failed for '{category}': {e}")
        return {}


def _parallel_harness_grounding(
    pairs: list[tuple[dict, str]]
) -> list[dict]:
    """Run harness_evaluate_standards_grounding in parallel for a batch of
    (standards_result, category) pairs.

    Called after the primary RAG futures complete so that document-based harness
    grounding (each an LLM Flash call) does not serialize inside as_completed().
    Worker count = len(pairs), executing all items in parallel at once.

    Returns grounded standards dicts in completion order. On per-item failure the
    ungrounded original result is appended so downstream merge is never skipped.
    """
    from domain.solution.agents.harness_agent import harness_evaluate_standards_grounding

    if not pairs:
        return []

    n = len(pairs)

    if n <= 1:
        return [harness_evaluate_standards_grounding(std_result, cat) for std_result, cat in pairs]

    logging.info(
        f"[EXPANSION] 🚀 Parallel harness grounding: {n} document standard(s) at once"
    )
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=n) as executor:
        future_to_pair: dict = {
            executor.submit(harness_evaluate_standards_grounding, std_result, cat): (std_result, cat)
            for std_result, cat in pairs
        }
        for future in as_completed(future_to_pair):
            std_result, cat = future_to_pair[future]
            try:
                results.append(future.result())
                logging.info(f"[EXPANSION] ✓ Harness grounding done for '{cat}'")
            except Exception as exc:
                logging.error(f"[EXPANSION] ✗ Harness grounding failed for '{cat}': {exc}")
                results.append(std_result)   # fall back to ungrounded result
    return results


@retryable_node(max_attempts=2, label="expansion")
def intelligent_standards_retrieval_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Expansion Agent — Standards Match + L3 Datasheet Values (Node 2).

    Performs parallel RAG operations for every unique instrument/accessory category:
    - Standards Match: retrieves uploaded engineering standards for each category
    - L3 Datasheet Values: for instruments, downloads the L3 model-family spec document and
      extracts concrete values for the L0/L1/L2 schema fields (no new keys are added)
    """
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "standards_retrieval",
            "message": "Expanding Standards & Specifications",
            "progress": 40,
        })

    logging.info("[EXPANSION] Node 2: Expansion Agent (Standards + L3 Spec-Doc Values)")

    if state.get("error"):
        return state

    if "deep_analysis" not in state:
        state["deep_analysis"] = {}

    extracted_requirements = state.get("deep_analysis", {}).get("extracted_requirements", {})
    user_id = state.get("user_id")

    logging.info(f"[EXPANSION] extracted_requirements keys: {list(extracted_requirements.keys())}")

    # Collect unique categories and track which items they belong to
    unique_categories: set = set()
    category_to_items: dict = {}

    instruments_list = extracted_requirements.get("instruments", [])
    logging.info(f"[EXPANSION] Processing {len(instruments_list)} instruments")

    for i, instrument in enumerate(instruments_list):
        needs_analysis = instrument.get("_needs_deep_analysis", True)
        category = instrument.get("category", "").strip()
        category_lower = category.lower()
        logging.info(f"[EXPANSION] Instrument {i+1}: category='{category}', needs_analysis={needs_analysis}")
        if category and needs_analysis:
            unique_categories.add(category_lower)
            if category_lower not in category_to_items:
                category_to_items[category_lower] = {"instruments": [], "accessories": [], "original_name": category}
            category_to_items[category_lower]["instruments"].append(i)

    accessories_list = extracted_requirements.get("accessories", [])
    for j, accessory in enumerate(accessories_list):
        needs_analysis = accessory.get("_needs_deep_analysis", True)
        category = accessory.get("category", "").strip()
        category_lower = category.lower()
        if category and needs_analysis:
            unique_categories.add(category_lower)
            if category_lower not in category_to_items:
                category_to_items[category_lower] = {"instruments": [], "accessories": [], "original_name": category}
            category_to_items[category_lower]["accessories"].append(j)

    logging.info(f"[EXPANSION] {len(unique_categories)} categories to expand: {unique_categories}")

    all_standards: list = []

    if unique_categories:
        logging.info(f"[EXPANSION] 🚀 Parallel Standards retrieval for {len(unique_categories)} categories")

        with ThreadPoolExecutor(max_workers=min(len(unique_categories) * 2, 10)) as executor:

            # Submit Standards RAG (only if not skipped and user_id available)
            standards_futures: dict = {}
            if state.get("skip_standards", False):
                logging.info("[EXPANSION] Standards disabled by user toggle")
            elif user_id:
                standards_futures = {
                    executor.submit(ProductHierarchyRepository.get_standards_for_category, user_id, category): category
                    for category in unique_categories
                }
            else:
                logging.warning("[EXPANSION] No user_id — skipping standards retrieval")

            # Submit L3 Spec-Doc value extraction for instrument categories
            spec_doc_futures: dict = {}
            if state.get("skip_spec_doc_values", False):
                logging.info("[EXPANSION] L3 spec-doc value extraction disabled by user toggle")
            else:
                for category in unique_categories:
                    item_indices = category_to_items.get(category, {})
                    if item_indices.get("instruments"):
                        spec_doc_futures[executor.submit(_get_spec_doc_values_for_category, category)] = category

            # Collect Standards results — defer harness grounding for a dedicated
            # parallel pass so LLM calls don't serialize inside as_completed().
            needs_grounding: list = []   # [(standards_result, category), ...]
            for future in as_completed(standards_futures):
                category = standards_futures[future]
                try:
                    standards = future.result()
                    if standards and standards.get("found"):
                        # Skip harness grounding for 5-tier primary results — they have no
                        # source document text to ground against (_full_text is ""), and the
                        # codes are already authoritative from the curated hierarchy.
                        if not standards.get("_is_tier_standards"):
                            # Defer: collect for the parallel harness grounding pass below.
                            needs_grounding.append((standards, category))
                        else:
                            all_standards.append(standards)
                            logging.info(f"[EXPANSION] ✓ Standards (5-tier) retrieved for '{category}'")
                    else:
                        logging.info(f"[EXPANSION] ✗ No standards for '{category}'")
                except Exception as exc:
                    logging.error(f"[EXPANSION] ✗ Standards RAG failed for '{category}': {exc}")

            # Parallel harness grounding pass — all document-based standards grounded
            # simultaneously rather than one-at-a-time in the loop above.
            if needs_grounding:
                grounded_results = _parallel_harness_grounding(needs_grounding)
                all_standards.extend(grounded_results)
                logging.info(
                    f"[EXPANSION] ✓ Parallel harness grounding complete: "
                    f"{len(grounded_results)} document standard(s) grounded"
                )

            # Collect L3 Spec-Doc values
            spec_doc_values_by_category: dict = {}
            for future in as_completed(spec_doc_futures):
                category = spec_doc_futures[future]
                try:
                    values = future.result()
                    if values:
                        spec_doc_values_by_category[category] = values
                        logging.info(f"[EXPANSION] ✓ L3 spec-doc values retrieved for '{category}': {len(values)} fields")
                    else:
                        logging.info(f"[EXPANSION] ✗ No L3 spec-doc values for '{category}'")
                except Exception as exc:
                    logging.error(f"[EXPANSION] ✗ L3 spec-doc extraction failed for '{category}': {exc}")

        logging.info(f"[EXPANSION] ✓ Done. Standards: {len(all_standards)}, SpecDocValues: {len(spec_doc_values_by_category)}")

    # Initialize default category fields (since taxonomy matching is removed)
    def _init_category_fields(item: dict) -> None:
        cat = item.get("category") or ""
        item.setdefault("original_category", cat)
        item.setdefault("db_category", cat)
        item.setdefault("category_mapped", False)
        item.setdefault("taxonomy_found", False)
        item.setdefault("use_db_category_only", False)
        item.setdefault("semantic_match", "SKIPPED")
        item.setdefault("semantic_confidence", 0.0)
        item.setdefault("spec_field_mappings", [])
        item.setdefault("mapped_specifications", {})

    for instrument in instruments_list:
        _init_category_fields(instrument)
    for accessory in accessories_list:
        _init_category_fields(accessory)

    extracted_requirements["instruments"] = instruments_list
    extracted_requirements["accessories"] = accessories_list

    # ── STEP 1: MERGE CATALOG SPECS INTO SPECIFICATIONS ──────────────────────────
    # Retrieve default/catalog specifications (essential, optional, latest) for
    # Accessories, and merge them with user specifications.
    # Priority: user-specified > catalog-specified.
    def _merge_specs_for_item(item: dict) -> None:
        original_specs = item.get("specifications", {})

        # 1. For Accessories, retrieve catalog-enriched default values/units from L0/L1/L2
        db_specs = {}
        cat_name = item.get("db_category") or item.get("category") or ""
        try:
            node = ProductHierarchyRepository.find_node_by_name(cat_name)
            node_type = node.get("type", "Equipment") if node else "Equipment"
            if node_type == "Accessory":
                schema = ProductHierarchyRepository.resolve_parameters_schema_by_name(cat_name) or {}
                for tier in ("mandatoryRequirements", "optionalRequirements", "latestRequirements"):
                    for k, v in schema.get(tier, {}).items():
                        if v is not None and v != "":
                            db_specs[k] = v
                logging.info(f"[EXPANSION] Retrieved {len(db_specs)} pre-vetted catalog specs for accessory '{cat_name}'")
        except Exception as e:
            logging.warning(f"[EXPANSION] Failed to retrieve catalog specs for accessory '{cat_name}': {e}")

        # 2. Merge user specifications with catalog specifications
        merged = {**db_specs}
        for k, v in original_specs.items():
            if v is not None and v != "":
                merged[k] = v

        item["specifications"] = merged
        logging.debug(
            f"[EXPANSION] Pre-merged specs for '{item.get('category', '?')}': "
            f"{len(original_specs)} user + {len(db_specs)} catalog → {len(merged)} merged"
        )

    for instrument in instruments_list:
        _merge_specs_for_item(instrument)
    for accessory in accessories_list:
        _merge_specs_for_item(accessory)

    # ── STEP 2: APPLY STANDARDS AFTER TAXONOMY MERGE ─────────────────────────────
    # Merges standard spec fields (only if not user-provided) and attaches 
    # applicable standard codes (e.g. API 551, IEC 60534) to each item.
    standards_by_category = {}
    codes_by_category = {}
    titles_by_category = {}   # code -> title for UI display (5-tier primary only)
    for std in all_standards:
        cat_match = (std.get("category_match") or "").strip().lower()
        if not cat_match:
            continue
        # 5-tier primary results have specifications: {} and standard_titles: {code: title}.
        # Document-based results have specifications: {field: value} and no standard_titles.
        if not std.get("_is_tier_standards"):
            specs = std.get("specifications", {})
            if "specifications" in specs and isinstance(specs["specifications"], dict):
                specs = specs["specifications"]
            if specs:
                standards_by_category[cat_match] = specs
        else:
            # Capture code->title map for applicable_standards_titles field on each item
            titles = std.get("standard_titles") or {}
            if titles:
                titles_by_category[cat_match] = titles
        codes = std.get("applicable_standards") or []
        if codes:
            codes_by_category[cat_match] = sorted({str(c).strip() for c in codes if str(c).strip()})

    def _apply_standards(item: dict, kind: str) -> None:
        cat = (item.get("db_category") or item.get("category") or "").strip().lower()
        # (a) merge standard spec FIELDS (document-based standards only — 5-tier results
        #     carry curated codes, not field-level values, so standards_by_category is
        #     empty for those categories and this block is skipped).
        std_specs = standards_by_category.get(cat, {})
        if std_specs:
            current_specs = item.get("specifications", {})
            normalized_existing = {_normalize_key(k) for k in current_specs}
            added = 0
            for k, v in std_specs.items():
                if _normalize_key(k) not in normalized_existing:
                    current_specs[k] = f"{v} [STANDARD]"
                    added += 1
            item["specifications"] = current_specs
            item["standards_specs"] = std_specs
            logging.info(f"[EXPANSION] Standards: added {added}/{len(std_specs)} fields to {kind} '{cat}'")
        # (b) attach the applicable-standards CODE list to the canonical field
        # `applicable_standards` (camelCased to `applicableStandards` at the API
        # boundary, which the frontend card reads).
        codes = codes_by_category.get(cat, [])
        if codes:
            existing = item.get("applicable_standards") or []
            item["applicable_standards"] = sorted({*[str(c).strip() for c in existing if str(c).strip()], *codes})
            item.setdefault("standards_source", "Restructured 5-tier hierarchy")
            logging.info(f"[EXPANSION] Standards: attached {len(codes)} applicable-standard codes to {kind} '{cat}'")
        # (c) attach code->title map for the UI (populated only for 5-tier primary results;
        #     document-based results do not have this — format_results_agent fills it via DB).
        titles = titles_by_category.get(cat)
        if titles:
            item["applicable_standards_titles"] = titles
            logging.info(f"[EXPANSION] Standards: attached {len(titles)} standard titles to {kind} '{cat}'")

    for instrument in instruments_list:
        _apply_standards(instrument, "instrument")
    for accessory in accessories_list:
        _apply_standards(accessory, "accessory")

    # ── STEP 3: APPLY L3 SPEC-DOC VALUES (instruments only) ─────────────────────────
    # Values extracted from the L3 datasheet populate the L0/L1/L2 schema fields.
    # Only fields that are part of the resolved schema are extracted, so no new
    # keys are added. User-provided values and standards-tagged values always win.
    def _apply_spec_doc_values(item: dict, kind: str) -> None:
        cat = (item.get("db_category") or item.get("category") or "").strip().lower()
        values = spec_doc_values_by_category.get(cat, {})
        if not values:
            return

        current_specs = item.get("specifications", {})
        # Build a map of norm_key -> original_key for existing specs so we can
        # overwrite [INFERRED] entries (LLM guesses) with real datasheet values.
        norm_to_orig = {_normalize_key(k): k for k in current_specs}
        added = replaced = 0
        for k, v in values.items():
            nk = _normalize_key(k)
            if nk not in norm_to_orig:
                # New field from datasheet — add it.
                current_specs[k] = f"{v} [DATASHEET]"
                norm_to_orig[nk] = k
                added += 1
            else:
                # Key already present — overwrite ONLY if the existing value is
                # [INFERRED] (LLM guess). User-provided and [STANDARD] values win.
                existing_val = current_specs.get(norm_to_orig[nk], "")
                if isinstance(existing_val, str) and "[inferred]" in existing_val.lower():
                    current_specs[norm_to_orig[nk]] = f"{v} [DATASHEET]"
                    replaced += 1
        item["specifications"] = current_specs
        item["spec_doc_values"] = values
        logging.info(
            f"[EXPANSION] SpecDoc: added {added} new + replaced {replaced} inferred "
            f"field(s) with datasheet values for {kind} '{cat}'"
        )

    for instrument in instruments_list:
        _apply_spec_doc_values(instrument, "instrument")

    state["deep_analysis"]["extracted_requirements"] = extracted_requirements

    # Deduplicate standards by source document
    unique_standards: list = []
    seen_sources: set = set()
    for std in all_standards:
        source = std.get("source_document", "") or std.get("source_blob", "")
        if source and source not in seen_sources:
            unique_standards.append(std)
            seen_sources.add(source)
        elif not source:
            unique_standards.append(std)

    state["deep_analysis"]["retrieved_standards"] = unique_standards
    state["deep_analysis"]["taxonomy_mappings"] = {}
    state["deep_analysis"]["categories_queried"] = list(unique_categories)

    logging.info(f"[EXPANSION] ✓ {len(unique_categories)} categories expanded")
    logging.info(f"[EXPANSION] ✓ {len(unique_standards)} unique standards documents")

    state["agent_path"].append("expansion_agent")

    # Append to node-to-node context memory trail
    append_node_execution_context(
        state,
        "expansion_agent",
        f"Retrieved standards & datasheets for {len(unique_categories)} categories ({len(unique_standards)} unique standards)",
        {"categories": list(unique_categories), "standards_count": len(unique_standards)},
    )
    return state
