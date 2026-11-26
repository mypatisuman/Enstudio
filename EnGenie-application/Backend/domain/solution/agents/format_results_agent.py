"""
Node 4 — Format Results Agent

Merges taxonomy-mapped specifications into the final instrument/accessory
specifications, normalises accessory fields for frontend compatibility,
generates a brief chat message via Flash LLM (summary only — heavy inference
is done by Pro in the Infer Agent), and writes all output into
workflow_data so the solution agent can build the final response.
"""

import logging
import os
import re
import sys

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from domain.orchestrator.state import AgenticSystemState


def _norm_field(key: str) -> str:
    """Normalize a spec field name so singular/plural/case/spacing variants collapse
    (e.g. 'Wetted Material' / 'Wetted Materials' / 'wetted_materials' -> 'wetted material')."""
    n = re.sub(r"[\s_\-]+", " ", str(key or "").strip().lower())
    if n.endswith("ies"):
        n = n[:-3] + "y"
    elif n.endswith("s") and not n.endswith("ss"):
        n = n[:-1]
    return n


def _dedup_specs(specs: dict) -> dict:
    """Collapse duplicate spec fields that differ only by name variant (singular/plural,
    case, spacing). On a clash, a user-provided value wins over an `[INFERRED]` one;
    otherwise first occurrence is kept. Preserves first-seen order."""
    if not isinstance(specs, dict):
        return specs or {}
    chosen: dict = {}   # norm_key -> (orig_key, value)
    order: list = []
    for k, v in specs.items():
        nk = _norm_field(k)
        if nk not in chosen:
            chosen[nk] = (k, v)
            order.append(nk)
        else:
            _ek, ev = chosen[nk]
            ev_inferred = isinstance(ev, str) and "[inferred]" in ev.lower()
            v_inferred = isinstance(v, str) and "[inferred]" in v.lower()
            if ev_inferred and not v_inferred:   # prefer the user-provided value
                chosen[nk] = (k, v)
    return {chosen[nk][0]: chosen[nk][1] for nk in order}
from domain.solution.services.category_service import _notify_failure
from domain.solution.agents.shared import llm_flash
from common.ai.prompts.response import SOLUTION_INSTRUMENTS_IDENTIFIED_PROMPT, SOLUTION_NO_INSTRUMENTS_PROMPT
from common.helpers.node_retry import retryable_node

logger = logging.getLogger(__name__)


@retryable_node(max_attempts=2, label="format_results")
def format_results_node(state: AgenticSystemState) -> AgenticSystemState:
    """
    Format Results Agent (Node 4).

    Merges mapped_specifications into specifications, normalises accessory
    fields, generates a chat summary via Flash LLM, and stores everything
    in workflow_data for the solution agent.
    """
    logging.info("[FORMAT_RESULTS] Node 4: Format Results")

    if state.get("error"):
        state["workflow_data"]["response_type"] = "error"
        state["workflow_data"]["project_name"] = ""
        state["workflow_data"]["instruments"] = []
        state["workflow_data"]["accessories"] = []
        state["workflow_data"]["summary"] = ""
        state["workflow_data"]["response_message"] = state.get("error", "An error occurred")
        state["workflow_data"]["awaiting_single_item_confirmation"] = False
        state["workflow_data"]["standards_applied"] = False
        return state

    try:
        enhanced_instruments = state.get("deep_analysis", {}).get("enhanced_instruments", {})
        validation = state.get("deep_analysis", {}).get("validation", {})

        instruments = enhanced_instruments.get("instruments", [])
        accessories = enhanced_instruments.get("accessories", [])
        project_name = enhanced_instruments.get("project_name", "")
        summary = enhanced_instruments.get("summary", "")

        # Specs are already fully merged by the Expansion Agent (user > taxonomy > standards).
        # This pass just ensures every item has a specifications dict and logs counts.
        # Internal refinement/pipeline flags are stripped so they never reach the
        # response or the frontend round-trip.
        for item_list in (instruments, accessories):
            for item in item_list:
                if "specifications" not in item:
                    item["specifications"] = {}
                item.pop("_needs_deep_analysis", None)
                item.pop("_newly_added", None)

        # Normalise accessory fields for frontend compatibility
        for accessory in accessories:
            category = accessory.get("category", "")
            accessory_name = accessory.get("accessory_name", "")
            if not category and accessory_name:
                accessory["category"] = accessory_name
                logging.warning(
                    f"[FORMAT_RESULTS] Accessory missing category, using accessory_name: {accessory_name}"
                )
            if accessory_name and not accessory.get("product_name"):
                accessory["product_name"] = accessory_name

        # ── DEDUPLICATION ────────────────────────────────────────────────────────
        # Same category + same product_name → merge into one card, sum quantities.
        # Same category + different product_name → keep as separate cards.
        def _dedup_items(items: list) -> list:
            seen: dict = {}  # key → merged item dict
            order: list = []  # preserve first-occurrence order
            for item in items:
                cat = (item.get("category") or "").strip().lower()
                pname = (item.get("product_name") or item.get("accessory_name") or "").strip().lower()
                key = (cat, pname)
                if key not in seen:
                    seen[key] = dict(item)  # shallow copy
                    order.append(key)
                else:
                    # Sum quantities
                    existing = seen[key]
                    try:
                        existing["quantity"] = int(existing.get("quantity") or 1) + int(item.get("quantity") or 1)
                    except (TypeError, ValueError):
                        existing["quantity"] = str(existing.get("quantity", 1)) + "+" + str(item.get("quantity", 1))
                    # Merge specs: existing wins on conflict, new unique keys are added
                    existing_specs = existing.get("specifications", {})
                    for k, v in item.get("specifications", {}).items():
                        if k not in existing_specs:
                            existing_specs[k] = v
                    existing["specifications"] = existing_specs
                    logging.info(
                        f"[FORMAT_RESULTS] Merged duplicate '{cat}' / '{pname}' "
                        f"→ qty now {existing['quantity']}"
                    )
            return [seen[k] for k in order]

        before_inst = len(instruments)
        before_acc  = len(accessories)
        instruments = _dedup_items(instruments)
        accessories = _dedup_items(accessories)
        if len(instruments) != before_inst:
            logging.info(f"[FORMAT_RESULTS] Deduped instruments: {before_inst} → {len(instruments)}")
        if len(accessories) != before_acc:
            logging.info(f"[FORMAT_RESULTS] Deduped accessories: {before_acc} → {len(accessories)}")

        # Collapse singular/plural/case/spacing duplicate spec fields (e.g.
        # 'Wetted Material' vs 'Wetted Materials', 'Communication Protocol' vs
        # 'Communication Protocols') and attach the per-product standard titles.
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
        for item_list in (instruments, accessories):
            for item in item_list:
                before = len(item.get("specifications") or {})
                item["specifications"] = _dedup_specs(item.get("specifications") or {})
                if before != len(item["specifications"]):
                    logging.info(f"[FORMAT_RESULTS] '{item.get('category', 'unknown')}': "
                                 f"deduped specs {before} -> {len(item['specifications'])}")
                # standard code -> title map for the UI.  Prefer the map already set by
                # the expansion agent (populated from the 5-tier hierarchy in-process,
                # correct cluster).  Only fall back to a DB re-fetch when it is absent —
                # this avoids a redundant round-trip that may hit the wrong cluster.
                if not item.get("applicable_standards_titles"):
                    try:
                        item["applicable_standards_titles"] = ProductHierarchyRepository.get_standards_titles(
                            item.get("category") or item.get("product_name") or item.get("accessory_name") or "")
                    except Exception as exc:
                        logging.debug(f"[FORMAT_RESULTS] standards titles lookup failed: {exc}")
                        item["applicable_standards_titles"] = {}
                logging.info(
                    f"[FORMAT_RESULTS] '{item.get('category', 'unknown')}': "
                    f"{len(item['specifications'])} specs ready for frontend"
                )

        # Log taxonomy mappings
        for instrument in instruments:
            if instrument.get("category_mapped"):
                logging.info(
                    f"[FORMAT_RESULTS] ✓ Instrument taxonomy: "
                    f"'{instrument.get('original_category', '')}' → "
                    f"DB: '{instrument.get('db_category', '')}'"
                )
        for accessory in accessories:
            if accessory.get("category_mapped"):
                logging.info(
                    f"[FORMAT_RESULTS] ✓ Accessory taxonomy: "
                    f"'{accessory.get('original_category', '')}' → "
                    f"DB: '{accessory.get('db_category', '')}'"
                )

        is_single_item = len(instruments) == 1 and len(accessories) == 0
        response_type = "single_item_prompt" if is_single_item else "requirements"
        awaiting_confirmation = is_single_item

        num_instruments = len(instruments)
        num_accessories = len(accessories)
        instrument_names = [inst.get("category", "Unknown") for inst in instruments]
        accessory_names = [
            acc.get("category", acc.get("accessory_name", "Unknown")) for acc in accessories
        ]

        # Helper: format detailed descriptions of instruments or accessories for prompt reasoning
        def _format_items_detail(items: list, is_accessory: bool = False) -> str:
            lines = []
            for item in items:
                name_key = "product_name" if not is_accessory else "accessory_name"
                name = item.get(name_key) or item.get("category", "Unknown")
                qty = item.get("quantity", 1)
                desc = f"- {qty}x {name}"
                
                vendors = item.get("specified_vendors", [])
                if vendors:
                    desc += f" (Preferred Vendors: {', '.join(vendors)})"
                    
                standards = item.get("user_specified_standards", [])
                if standards:
                    desc += f" (Standards: {', '.join(standards)})"
                    
                strategy = item.get("strategy", "")
                if strategy:
                    desc += f" (Procurement Strategy: {strategy})"
                    
                lines.append(desc)
            return "\n".join(lines) if lines else "None"

        # Generate chat message via Flash LLM
        try:
            if num_instruments == 0 and num_accessories == 0:
                prompt = ChatPromptTemplate.from_template(SOLUTION_NO_INSTRUMENTS_PROMPT)
                chain = prompt | llm_flash | StrOutputParser()
                message = chain.invoke({}).strip()
            else:
                # Construct pre-formatted identified_summary for the LLM prompt
                instrument_part = f"**{num_instruments} instrument{'s' if num_instruments != 1 else ''}**" if num_instruments > 0 else ""
                accessory_part = f"**{num_accessories} accessor{'ies' if num_accessories != 1 else 'y'}**" if num_accessories > 0 else ""
                
                if instrument_part and accessory_part:
                    identified_summary = f"{instrument_part} and {accessory_part}"
                elif instrument_part:
                    identified_summary = instrument_part
                else:
                    identified_summary = accessory_part

                prompt = ChatPromptTemplate.from_template(SOLUTION_INSTRUMENTS_IDENTIFIED_PROMPT)
                chain = prompt | llm_flash | StrOutputParser()
                
                extraction_summary = enhanced_instruments.get("summary", "No summary provided.")
                
                message = chain.invoke({
                    "project_name": project_name,
                    "identified_summary": identified_summary,
                    "extraction_summary": extraction_summary,
                    "instruments_detail": _format_items_detail(instruments, is_accessory=False),
                    "accessories_detail": _format_items_detail(accessories, is_accessory=True),
                }).strip()
            logging.info(f"[FORMAT_RESULTS] Chat message: {message[:100]}...")
        except Exception as e:
            logging.exception(f"[FORMAT_RESULTS] Chat message generation failed, using fallback: {e}")
            instrument_word = "instrument" if num_instruments == 1 else "instruments"
            accessory_word = "accessory" if num_accessories == 1 else "accessories"
            message = (
                f"I've identified **{num_instruments} {instrument_word}** and "
                f"**{num_accessories} {accessory_word}** based on your requirements. "
                "You can view the detailed list in the right panel. "
                "Click on any item to run a detailed vendor analysis."
            )

        # Write to workflow_data
        state["workflow_data"]["response_type"] = response_type
        state["workflow_data"]["project_name"] = project_name
        state["workflow_data"]["sub_systems"] = state.get("deep_analysis", {}).get("sub_systems", [])
        state["workflow_data"]["instruments"] = instruments
        state["workflow_data"]["accessories"] = accessories
        state["workflow_data"]["summary"] = summary
        state["workflow_data"]["response_message"] = message
        state["workflow_data"]["awaiting_single_item_confirmation"] = awaiting_confirmation
        state["workflow_data"]["standards_applied"] = False

        if num_instruments == 0 and num_accessories == 0:
            _notify_failure(
                "Deep Instrument Analysis",
                "No instruments or accessories were identified from user input.",
                state=state,
                page="solution",
                user_input=state.get("user_input", ""),
            )

        state["instruments"] = instruments
        state["accessories"] = accessories

        logging.info(f"[FORMAT_RESULTS] Type: {response_type}, Instruments: {num_instruments}, Accessories: {num_accessories}")
        state["agent_path"].append("format_results")

    except Exception as e:
        logging.exception(f"[FORMAT_RESULTS] Result formatting failed: {e}")
        state["error"] = f"Failed to format results: {str(e)}"
        state["workflow_data"]["response_type"] = "error"
        state["workflow_data"]["response_message"] = "Failed to process results"

    return state


def route_deep_analysis(state: AgenticSystemState) -> str:
    """Route to format_results on error, otherwise continue."""
    if state.get("error"):
        logging.info("[FORMAT_RESULTS] Error detected — routing to format_results")
        return "format_results"
    return "continue"
