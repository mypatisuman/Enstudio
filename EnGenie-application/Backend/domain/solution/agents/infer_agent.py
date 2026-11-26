"""
Node 3 — Infer Agent (Pro, per-item parallel)

For each Instrument (and its associated Accessories), runs a dedicated Pro LLM
call in parallel to infer all missing specifications using:
  - Taxonomy-expanded fields from Node 2
  - Retrieved engineering standards from Node 2
  - Engineering first principles and industry best practices

This implements the solution.md requirement:
  "Infer Agent — Pro with Reasoning — Executed in parallel for each Instrument/Accessory"
"""

import json
import logging
import os
import sys
from collections import defaultdict
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from domain.orchestrator.state import AgenticSystemState
from domain.solution.agents.shared import (
    INFER_AGENT_PROMPT,
    REQUIRED_INSTRUMENT_FIELDS,
    REQUIRED_ACCESSORY_FIELDS,
    llm_pro,
    _parse_llm_json,
)
from domain.solution.memory import append_node_execution_context
from common.ai.llm import SOLUTION_LLM_PROVIDER, with_json_mode
from common.helpers.node_retry import retryable_node
from common.helpers.progress_tracker import progress_tracker

logger = logging.getLogger(__name__)

_TAXONOMY_KEYS = [
    "original_category", "db_category", "category_mapped",
    "taxonomy_found", "use_db_category_only",
    "semantic_match", "semantic_confidence",
    "spec_field_mappings", "mapped_specifications",
]


def _build_sample_input(specifications: dict[str, Any], category: str = "") -> str:
    """
    Build sample_input from category name and specifications.
    Format: "Category, key: clean_value, key2: clean_value2, ..."
    Tags ([INFERRED], [STANDARD]) are stripped for clean frontend display.
    """
    spec_parts = []
    for key, value in (specifications or {}).items():
        clean_value = (
            str(value)
            .replace("[INFERRED]", "")
            .replace("[STANDARD]", "")
            .strip()
        )
        if clean_value:
            spec_parts.append(f"{key}: {clean_value}")
    specs_str = ", ".join(spec_parts)
    return f"{category}, {specs_str}" if category and specs_str else (category or specs_str)


@retryable_node(max_attempts=2, label="infer")
def infer_agent_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Infer Agent — Pro with Reasoning, parallel batched inference (Node 3).

    Items are grouped into batches of INFER_BATCH_SIZE (default 3, instruments
    and accessories batched separately) so the ~1.8K-token static prompt is paid
    once per batch instead of once per item. A batch that fails or returns a
    mismatched array falls back to per-item calls (the old reliable mode).
    All batches run concurrently via ThreadPoolExecutor.
    """
    stream_id = state.get("stream_id")
    if stream_id and state.get("enable_streaming"):
        progress_tracker.emit(stream_id, "step", {
            "step": "infer_specifications",
            "message": "Inferring Specifications",
            "progress": 60,
        })

    logging.info("[INFER_AGENT] Node 3: Infer Agent (per-item parallel, Pro)")

    if state.get("error"):
        return state

    extracted_instruments = state.get("deep_analysis", {}).get("extracted_requirements", {})

    try:
        instruments_list = extracted_instruments.get("instruments", [])
        accessories_list = extracted_instruments.get("accessories", [])
        project_name = extracted_instruments.get("project_name", "")

        # Only these 9 BOM fields are sent to the LLM — clean, no internal pipeline metadata.
        _LLM_FIELDS = ("category", "product_name", "accessory_name", "quantity",
                       "specifications", "strategy", "specified_vendors",
                       "specified_model_families", "user_specified_standards", "skip_standards")

        def _llm_payload(item: dict) -> dict:
            return {k: item[k] for k in _LLM_FIELDS if k in item}

        # Incremental gate (mirrors expansion's _needs_deep_analysis skip): on
        # refinement turns unchanged items are flagged False and pass through
        # verbatim — no Pro LLM call is spent on them. Default True preserves
        # full inference on normal runs.
        infer_instruments = [i for i in instruments_list if i.get("_needs_deep_analysis", True)]
        skip_instruments = [i for i in instruments_list if not i.get("_needs_deep_analysis", True)]
        infer_accessories = [a for a in accessories_list if a.get("_needs_deep_analysis", True)]
        skip_accessories = [a for a in accessories_list if not a.get("_needs_deep_analysis", True)]
        if skip_instruments or skip_accessories:
            logging.info(f"[INFER_AGENT] Skipping inference for {len(skip_instruments)} unchanged "
                         f"instrument(s) and {len(skip_accessories)} unchanged accessorie(s)")

        # Group into batches of up to INFER_BATCH_SIZE items (instruments and
        # accessories batched separately so each payload stays homogeneous).
        # The static prompt template is paid once per BATCH, not once per item —
        # it dominates this node's input cost when sent per item.
        batch_size = max(1, int(os.getenv("INFER_BATCH_SIZE", "3")))

        def _chunk(items: list, n: int) -> list:
            return [items[i:i + n] for i in range(0, len(items), n)]

        batches: list = []       # LLM payloads
        batch_items: list = []   # ("instruments"|"accessories", [original items]) per batch
        for group in _chunk(infer_instruments, batch_size):
            batches.append({
                "project_name": project_name,
                "instruments": [_llm_payload(i) for i in group],
                "accessories": [],
            })
            batch_items.append(("instruments", group))
        for group in _chunk(infer_accessories, batch_size):
            batches.append({
                "project_name": project_name,
                "instruments": [],
                "accessories": [_llm_payload(a) for a in group],
            })
            batch_items.append(("accessories", group))

        logging.info(f"[INFER_AGENT] 🚀 Running {len(batches)} parallel inference call(s) "
                     f"({len(infer_instruments)} instruments + {len(infer_accessories)} accessories, "
                     f"batch size {batch_size})")

        def _run_llm(payload: dict) -> dict:
            prompt = ChatPromptTemplate.from_template(INFER_AGENT_PROMPT)
            chain = prompt | with_json_mode(llm_pro, SOLUTION_LLM_PROVIDER) | StrOutputParser()
            resp = chain.invoke(
                {
                    "extracted_instruments": json.dumps(payload, indent=2),
                    "input_range": state.get("workflow_data", {}).get("input_range", "mid")
                },
                config={"metadata": {"user_id": state.get("user_id"), "agent_type": "solution"}},
            )
            return _parse_llm_json(resp)

        def _lengths_ok(payload: dict, result: dict) -> bool:
            return (len(result.get("instruments", [])) == len(payload.get("instruments", []))
                    and len(result.get("accessories", [])) == len(payload.get("accessories", [])))

        def _infer_batch(batch_payload: dict, batch_idx: int) -> dict:
            """Enrich one batch; on failure or array-length mismatch, retry the
            batch's items one at a time (the pre-batching behavior)."""
            kind, originals = batch_items[batch_idx]
            try:
                result = _run_llm(batch_payload)
                if _lengths_ok(batch_payload, result):
                    names = [(i.get("category") or i.get("accessory_name") or "?")
                             for i in (batch_payload["instruments"] or batch_payload["accessories"])]
                    logging.info(f"[INFER_AGENT] ✓ batch {batch_idx+1}: {', '.join(names)} inferred")
                    return result
                logging.warning(f"[INFER_AGENT] Batch {batch_idx+1} array-length mismatch — retrying items individually")
            except Exception as exc:
                if len(originals) == 1:
                    raise  # single-item batch: outer handler substitutes the original
                logging.warning(f"[INFER_AGENT] Batch {batch_idx+1} failed ({exc}) — retrying items individually")

            merged = {"project_name": batch_payload.get("project_name", ""), "instruments": [], "accessories": []}
            for original in originals:
                single = {
                    "project_name": batch_payload.get("project_name", ""),
                    "instruments": [_llm_payload(original)] if kind == "instruments" else [],
                    "accessories": [_llm_payload(original)] if kind == "accessories" else [],
                }
                try:
                    r = _run_llm(single)
                    if not _lengths_ok(single, r):
                        raise ValueError("single-item array-length mismatch")
                    merged["instruments"].extend(r.get("instruments", []))
                    merged["accessories"].extend(r.get("accessories", []))
                except Exception as sexc:
                    logging.error(f"[INFER_AGENT] ✗ single-item fallback failed — using original: {sexc}")
                    merged[kind].append(_llm_payload(original))
            return merged

        # Run all batches in parallel. Concurrency capped because Azure reserves
        # prompt + the pro tier's max_completion_tokens against the TPM quota at
        # request start — 15 concurrent calls reserved ~0.5M TPM per wave.
        batch_results: list = [None] * len(batches)
        max_workers = min(len(batches), int(os.getenv("INFER_MAX_WORKERS", "6")))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_infer_batch, batch, idx): idx
                for idx, batch in enumerate(batches)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    batch_results[idx] = future.result()
                except Exception as exc:
                    logging.error(f"[INFER_AGENT] ✗ Batch {idx+1} inference failed — using originals: {exc}")
                    batch_results[idx] = batches[idx]

        # Build lookup of original full items (with all pipeline fields) keyed by (category, product_name)
        orig_inst_map  = {
            (i.get("category","").strip().lower(), i.get("product_name","").strip().lower()): i
            for i in instruments_list
        }
        orig_acc_map = {
            (a.get("category","").strip().lower(), a.get("accessory_name","").strip().lower()): a
            for a in accessories_list
        }

        # Merge: take original full item, add only the NEW spec fields from LLM output.
        # Name lookup first; positional lookup (item j of batch batch_idx, arrays are
        # order-preserving per the prompt contract) as the fallback when the LLM
        # returns a mangled category.
        merged_instruments: list = []
        merged_accessories: list = []
        summary_parts: list = []

        for batch_idx, result in enumerate(batch_results):
            if result is None:
                continue
            if result.get("summary"):
                summary_parts.append(result["summary"])
            batch_kind, batch_originals = batch_items[batch_idx]

            for j, llm_inst in enumerate(result.get("instruments", [])):
                cat   = (llm_inst.get("category") or "").strip().lower()
                pname = (llm_inst.get("product_name") or "").strip().lower()
                orig  = orig_inst_map.get((cat, pname))
                if orig is None:
                    orig = next((v for k, v in orig_inst_map.items() if k[0] == cat), None)
                if orig is None:
                    # LLM returned wrong category — use this batch's j-th original
                    if batch_kind == "instruments" and j < len(batch_originals):
                        orig = batch_originals[j]
                        logging.warning(
                            f"[INFER_AGENT] LLM returned wrong category '{cat}' in batch {batch_idx} "
                            f"(expected '{orig.get('category', '?')}') — using original item as fallback"
                        )
                    else:
                        logging.warning(f"[INFER_AGENT] No original found for instrument '{cat}' — skipping")
                        continue
                merged = dict(orig)
                existing_specs = dict(merged.get("specifications", {}))
                for k, v in llm_inst.get("specifications", {}).items():
                    if k not in existing_specs:
                        existing_specs[k] = v
                merged["specifications"] = existing_specs
                merged_instruments.append(merged)

            for j, llm_acc in enumerate(result.get("accessories", [])):
                cat   = (llm_acc.get("category") or "").strip().lower()
                aname = (llm_acc.get("accessory_name") or "").strip().lower()
                orig  = orig_acc_map.get((cat, aname))
                if orig is None:
                    orig = next((v for k, v in orig_acc_map.items() if k[0] == cat), None)
                if orig is None:
                    # LLM returned wrong category — use this batch's j-th original
                    if batch_kind == "accessories" and j < len(batch_originals):
                        orig = batch_originals[j]
                        logging.warning(
                            f"[INFER_AGENT] LLM returned wrong category '{cat}' in accessory batch {batch_idx} "
                            f"(expected '{orig.get('accessory_name', '?')}') — using original item as fallback"
                        )
                    else:
                        logging.warning(f"[INFER_AGENT] No original found for accessory '{cat}' — skipping")
                        continue
                merged = dict(orig)
                existing_specs = dict(merged.get("specifications", {}))
                for k, v in llm_acc.get("specifications", {}).items():
                    if k not in existing_specs:
                        existing_specs[k] = v
                merged["specifications"] = existing_specs
                merged_accessories.append(merged)

        # Passthrough: unchanged (skipped) items join the output verbatim,
        # preserving their fully-specified state from the previous run.
        merged_instruments.extend(dict(i) for i in skip_instruments)
        merged_accessories.extend(dict(a) for a in skip_accessories)

        inferred_result = {
            "project_name": project_name,
            "instruments": merged_instruments,
            "accessories": merged_accessories,
            "summary": summary_parts[0] if summary_parts else "Inference completed.",
            "validation_passed": True,
            "validation_issues": [],
            "recommended_enhancements": [],
            "compliance_notes": [],
        }

        logging.info(
            f"[INFER_AGENT] Merged {len(merged_instruments)} instruments and "
            f"{len(merged_accessories)} accessories from {len(batches)} parallel call(s)"
        )
        logging.info(f"[INFER_AGENT] Preserved taxonomy fields for {len(orig_inst_map) + len(orig_acc_map)} categories")

        # ── Rebuild sample_input via Python — authoritative, always overwrites LLM output ────────
        # Format: "Category, key: clean_value, key2: clean_value2, ..."
        # Tags [INFERRED] and [STANDARD] are stripped — clean display for frontend.
        for instrument in inferred_result.get("instruments", []):
            instrument["sample_input"] = _build_sample_input(
                instrument.get("specifications", {}),
                category=instrument.get("category", ""),
            )

        for accessory in inferred_result.get("accessories", []):
            accessory["sample_input"] = _build_sample_input(
                accessory.get("specifications", {}),
                category=accessory.get("category", "") or accessory.get("accessory_name", ""),
            )

        # Ensure all required fields exist
        for instrument in inferred_result.get("instruments", []):
            for field in REQUIRED_INSTRUMENT_FIELDS:
                if field not in instrument:
                    instrument[field] = "" if field in ("strategy", "sample_input") else (_ for _ in ()).throw(
                        ValueError(f"Missing required field '{field}' in instrument")
                    )
            instrument.setdefault("strategy", "")
            instrument.setdefault("specified_vendors", [])
            instrument.setdefault("specified_model_families", [])
            instrument.setdefault("user_specified_standards", [])
            instrument.setdefault("skip_standards", False)

        for accessory in inferred_result.get("accessories", []):
            for field in REQUIRED_ACCESSORY_FIELDS:
                if field not in accessory:
                    accessory[field] = "" if field in ("strategy", "sample_input") else (_ for _ in ()).throw(
                        ValueError(f"Missing required field '{field}' in accessory")
                    )
            accessory.setdefault("strategy", "")
            accessory.setdefault("specified_vendors", [])
            accessory.setdefault("specified_model_families", [])
            accessory.setdefault("user_specified_standards", [])
            accessory.setdefault("skip_standards", False)
            accessory.setdefault("parent_instrument_category", "")

        if "deep_analysis" not in state:
            state["deep_analysis"] = {}
        state["deep_analysis"]["enhanced_instruments"] = inferred_result
        state["deep_analysis"]["validation"] = {
            "validation_passed": inferred_result.get("validation_passed", True),
            "validation_issues": inferred_result.get("validation_issues", []),
            "recommended_enhancements": inferred_result.get("recommended_enhancements", []),
            "compliance_notes": inferred_result.get("compliance_notes", []),
            "final_message": inferred_result.get("summary", "Inference and validation completed."),
        }

        logging.info(f"[INFER_AGENT] ✓ {len(inferred_result.get('instruments', []))} instruments inferred")
        logging.info(f"[INFER_AGENT] ✓ {len(inferred_result.get('accessories', []))} accessories inferred")

        state["agent_path"].append("infer_agent")

        # Append to node-to-node context memory trail
        append_node_execution_context(
            state,
            "infer_agent",
            f"Inferred physical specs across {len(inferred_result.get('instruments', []))} instruments and {len(inferred_result.get('accessories', []))} accessories",
            {"instrument_count": len(inferred_result.get("instruments", [])), "accessory_count": len(inferred_result.get("accessories", []))},
        )

    except Exception as e:
        logging.exception(f"[INFER_AGENT] Inference failed: {e}")
        if "deep_analysis" not in state:
            state["deep_analysis"] = {}
        state["deep_analysis"]["enhanced_instruments"] = extracted_instruments
        state["deep_analysis"]["validation"] = {
            "validation_passed": True,
            "validation_issues": [],
            "recommended_enhancements": [],
            "compliance_notes": [],
            "final_message": "Validation skipped due to infer agent error",
        }
        logging.warning("[INFER_AGENT] Using pre-inference instruments due to error")

    return state
