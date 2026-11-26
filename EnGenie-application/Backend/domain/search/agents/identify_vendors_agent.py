"""
Node 4 — Identify Vendors Agent (No LLM)

Identifies vendors through Strategy RAG or User Input, then filters products.
Extracted from search_agent.py (filter_vendors_by_strategy and search_products).
"""

import json
import logging
from typing import Any

from domain.orchestrator.state import AgenticSystemState
from common.ai.rag import search_vendors_rag
from common.helpers.progress_tracker import progress_tracker
from app.core.errors import notify_failure

logger = logging.getLogger(__name__)

def _notify_failure(state, task_name, message, **kwargs):
    user_id = state.get("user_id")
    session_id = state.get("session_id")
    if user_id:
        notify_failure(
            failed_step=task_name,
            error_message=message,
            page="search",
            user_id=int(user_id) if str(user_id).isdigit() else None,
            session_id=session_id,
            **kwargs
        )


def discover_top_vendors_fallback(product_type: str) -> list[dict[str, Any]]:
    """Discover top 5 vendors using LLM at runtime (no schema gen).

    Returns vendor names only — same format as Priority 1 and Priority 2 vendor
    sources so they flow identically through match_vendor_names and DB intersection.
    Model families are not fetched here since the caller only uses vendor names.
    """
    logger.info(f"[DISCOVER_FALLBACK] Discovering top 5 vendors for '{product_type}'")

    from common.ai.llm import get_flash_llm
    from langchain_core.prompts import ChatPromptTemplate
    from common.ai.prompts.response import DISCOVER_TOP_VENDORS_PROMPT

    llm_flash = get_flash_llm(temperature=0.1)

    prompt_text = ChatPromptTemplate.from_template(DISCOVER_TOP_VENDORS_PROMPT).format(
        product_type=product_type
    )

    try:
        resp = llm_flash.invoke(prompt_text)
        text = str(resp.content)
        text = text.replace("```json","").replace("```","").strip()
        names = json.loads(text)
        if not isinstance(names, list):
            names = ["Emerson", "ABB", "Yokogawa", "Endress+Hauser", "Honeywell"]
        return [{"vendor": name, "model_families": []} for name in names[:5] if name]
    except Exception as e:
        logger.error(f"[DISCOVER_FALLBACK] Failed: {e}")
        return []

def identify_vendors_agent(state: AgenticSystemState) -> AgenticSystemState:
    """
    Identify Vendors Agent (Node 4).

    Identifies vendor list through priority-based filtering:
    1. User-specified vendors
    2. Strategy RAG vendors
    3. Top 5 DB vendors

    Then searches products in DB matching those vendors.
    """
    state.setdefault("agent_path", []).append("identify_vendors_agent")
    try:
        # Emit progress
        import threading as _threading
        stream_id = state.get("stream_id")
        if stream_id:
            progress_tracker.emit(stream_id, "step", {
                "step": "identify_vendors",
                "message": "Identifying Vendors",
                "progress": 40
            })

        logger.info(
            f"[IDENTIFY_VENDORS] ENTER — "
            f"session_id={state.get('session_id')!r} "
            f"stream_id={stream_id!r} "
            f"thread={_threading.current_thread().name} "
            f"active_threads={_threading.active_count()} "
            f"detected_product_type={state.get('detected_product_type')!r} "
            f"specified_vendors={state.get('specified_vendors', [])} "
            f"user_id={state.get('user_id')!r}"
        )
        logger.info("[IDENTIFY_VENDORS] Node 4: Identify Vendors Agent (No LLM)")
        detected_product_type = state.get("detected_product_type", "")

        # ==================================================================
        # PHASE 1: Get source vendor names (priority order)
        # ==================================================================
        source_vendors = []
        source_type = "none"

        # Priority 1: User-specified vendors
        user_specified_vendors = state.get("specified_vendors") or []
        if user_specified_vendors:
            source_vendors = user_specified_vendors
            source_type = "user_specified"
            logger.info(f"[IDENTIFY_VENDORS] Priority 1: User specified vendors: {source_vendors}")

        # Priority 2: Strategy-based vendors (from RAG)
        if not source_vendors:
            user_id = state.get("user_id")
            if user_id:
                logger.info(f"[IDENTIFY_VENDORS] Priority 2: Searching strategy vendors via RAG for user {user_id}...")

                # Determine RAG input source
                instruments = state.get("instruments", [])
                accessories = state.get("accessories", [])
                procurement_strategy = state.get("strategy") or state.get("procurement_strategy")
                rag_product_type = detected_product_type
                data_source = "validation"

                if instruments or accessories:
                    first_item = instruments[0] if instruments else (accessories[0] if accessories else None)
                    if first_item:
                        solution_category = first_item.get("category", "")
                        solution_strategy = first_item.get("strategy", "")
                        if solution_category:
                            rag_product_type = solution_category
                            data_source = "solution_instruments"
                        if solution_strategy:
                            procurement_strategy = solution_strategy

                logger.info(f"[IDENTIFY_VENDORS] RAG input (source={data_source}): product_type='{rag_product_type}', strategy='{procurement_strategy}'")

                try:
                    rag_results = search_vendors_rag(
                        user_id=str(user_id),
                        query="",
                        input_product_type=rag_product_type,
                        input_category=rag_product_type,
                        input_strategy=procurement_strategy,
                        top_k=20,
                        min_score=0.4
                    )

                    if rag_results:
                        source_vendors = [v.get('vendor_name', '') for v in rag_results]
                        source_type = "strategy_based"
                        state["csv_vendor_filter"] = {
                            "vendor_names": source_vendors,
                            "rag_results": rag_results,
                            "search_method": "rag",
                            "total_count": len(rag_results)
                        }
                        logger.info(f"[IDENTIFY_VENDORS] Priority 2: Found {len(source_vendors)} strategy vendors: {source_vendors}")
                    else:
                        logger.info("[IDENTIFY_VENDORS] Priority 2: No strategy vendors found via RAG")

                except Exception as e:
                    logger.warning(f"[IDENTIFY_VENDORS] Priority 2: RAG search failed: {e}")
                    _notify_failure(state, "RAG Vendor Search",
                        f"RAG vendor search failed for product '{detected_product_type}': {str(e)}",
                        product_type=detected_product_type, error=str(e))

        if not source_vendors:
            logger.info("[IDENTIFY_VENDORS] Priority 3: Discovering top 5 vendors from DB...")
            try:
                top_vendors_result = discover_top_vendors_fallback(detected_product_type)
                if top_vendors_result:
                    source_vendors = [
                        v.get('vendor') if isinstance(v, dict) else v
                        for v in top_vendors_result[:5]
                    ]
                    source_vendors = [v for v in source_vendors if v]
                    source_type = "top_5_fallback"
                    logger.info(f"[IDENTIFY_VENDORS] Priority 3: Discovered top 5 DB vendors: {source_vendors}")
            except Exception as e:
                logger.warning(f"[IDENTIFY_VENDORS] Priority 3: DB vendor discovery failed: {e}")

        logger.info(f"[IDENTIFY_VENDORS] Phase 1 complete: {len(source_vendors)} source vendors from '{source_type}'")

        # ==================================================================
        # PHASE 2: Get DB vendors and INTERSECT with source vendors
        # ==================================================================
        all_db_vendors = []
        try:
            from domain.search.services.product_service import get_available_vendors, get_vendors_for_product

            if detected_product_type:
                all_db_vendors = get_vendors_for_product(detected_product_type)
                logger.info(f"[IDENTIFY_VENDORS] DB vendors for '{detected_product_type}': {all_db_vendors}")
            else:
                all_db_vendors = get_available_vendors()
                logger.info(f"[IDENTIFY_VENDORS] All DB vendors: {all_db_vendors}")
        except Exception as e:
            logger.warning(f"[IDENTIFY_VENDORS] Error getting DB vendors: {e}")
            _notify_failure(state, "Database Vendor Fetch",
                f"Failed to fetch vendors from database for product '{detected_product_type}': {str(e)}",
                product_type=detected_product_type, error=str(e))

        # INTERSECT: Match source vendors against DB vendors
        final_vendors = []
        if all_db_vendors and source_vendors:
            final_vendors = match_vendor_names(source_vendors, all_db_vendors)

            if not final_vendors:
                logger.warning(
                    f"[IDENTIFY_VENDORS] INTERSECTION EMPTY — "
                    f"source_vendors={source_vendors} "
                    f"db_vendors={all_db_vendors} "
                    f"source_type={source_type!r} "
                    f"product_type={detected_product_type!r}. "
                    f"LLM name-matching failed or returned no overlap — falling back to all DB vendors."
                )
                # Fallback: use all available DB vendors for this product type so the
                # downstream analysis still has candidates instead of getting 0 results.
                final_vendors = all_db_vendors[:10]
                source_type = "db_all_fallback"
        elif all_db_vendors:
            # Source vendor lookup failed entirely — use all DB vendors as best-effort.
            logger.warning(
                f"[IDENTIFY_VENDORS] No source vendors found by any priority step — "
                f"using all {len(all_db_vendors)} DB vendors for '{detected_product_type}'."
            )
            final_vendors = all_db_vendors[:10]
            source_type = "db_all_fallback"
        else:
            final_vendors = source_vendors if source_vendors else []
            logger.warning(
                f"[IDENTIFY_VENDORS] No DB vendors found for '{detected_product_type}', "
                f"using source vendors as-is so LLM analysis can still run: {final_vendors}"
            )

        # ✅ FINAL FILTERING: Apply smart deduplication and CAP at 10 vendors
        if final_vendors:
            unique_vendors = {}
            # Sort by length so shorter "root" names are processed first
            for v in sorted(final_vendors, key=len):
                v_low = v.lower().strip()
                is_duplicate = False
                for existing_low in unique_vendors:
                    if existing_low in v_low or v_low in existing_low:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    unique_vendors[v_low] = v
            
            final_vendors = list(unique_vendors.values())
            
            # CAP at 10 vendors to prevent excessive latency and API usage
            if len(final_vendors) > 10:
                logger.info(f"[IDENTIFY_VENDORS] Capping {len(final_vendors)} vendors to top 10")
                final_vendors = final_vendors[:10]

        state["filtered_vendors"] = final_vendors
        state["vendor_priority_level"] = source_type
        state["vendor_filter_message"] = f"Using {len(final_vendors)} vendors ({source_type})"

        logger.info(f"[IDENTIFY_VENDORS] ✓ Final filtered vendors ({source_type}): {final_vendors}")

        # ==================================================================
        # PHASE 3: Search products from identified vendors
        # ==================================================================
        if stream_id:
            progress_tracker.emit(stream_id, "step", {
                "step": "search_products",
                "message": "Searching Products",
                "progress": 45
            })

        logger.info(f"[IDENTIFY_VENDORS] Searching products for: {detected_product_type}")

        try:
            from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
            logger.info(
                f"[5TIER_AUDIT][identify_vendors] PRODUCT_LOAD attempting "
                f"source=Restructured DB method=get_vendor_products_by_name "
                f"traversal=L2->L3->L4 product_type={detected_product_type!r}"
            )
            tier_products = ProductHierarchyRepository.get_vendor_products_by_name(detected_product_type)
            if tier_products:
                products = tier_products
                vendors_in_products = list({p.get("vendor") or p.get("vendor_name") for p in products if p.get("vendor") or p.get("vendor_name")})
                has_datasheet = sum(1 for p in products if p.get("datasheet_url"))
                logger.info(
                    f"[5TIER_AUDIT][identify_vendors] PRODUCT_LOAD=5-tier-SUCCESS "
                    f"db=Restructured collections=L3+L4 "
                    f"product_type={detected_product_type!r} "
                    f"total_products={len(products)} "
                    f"unique_vendors={len(vendors_in_products)} vendors={vendors_in_products} "
                    f"products_with_datasheet_url={has_datasheet}/{len(products)}"
                )
            else:
                logger.warning(
                    f"[5TIER_AUDIT][identify_vendors] PRODUCT_LOAD=FALLBACK-flat-vendors "
                    f"reason=5-tier returned 0 products "
                    f"db=product-recommender collection=vendors product_type={detected_product_type!r}"
                )
                from domain.search.services.product_service import _load_products_from_mongodb_direct
                products_json = _load_products_from_mongodb_direct(detected_product_type)
                products = json.loads(products_json) if products_json and products_json != "[]" else []
        except Exception as _tier_err:
            logger.warning(
                f"[5TIER_AUDIT][identify_vendors] PRODUCT_LOAD=FALLBACK-flat-vendors "
                f"reason=5-tier exception: {_tier_err} "
                f"db=product-recommender collection=vendors"
            )
            from domain.search.services.product_service import _load_products_from_mongodb_direct
            products_json = _load_products_from_mongodb_direct(detected_product_type)
            products = json.loads(products_json) if products_json and products_json != "[]" else []

        # Filter by vendors if specified
        if final_vendors and products:
            filtered_products = []
            for product in products:
                vendor = product.get('vendor') or product.get('vendor_name', '')
                if any(v.lower() in vendor.lower() for v in final_vendors):
                    filtered_products.append(product)
            if filtered_products:
                products = filtered_products
                logger.info(f"[IDENTIFY_VENDORS] Filtered to {len(products)} products from vendors: {final_vendors}")
            else:
                # None of the requested vendors have catalog products for this type.
                # Keep the full available pool instead of dropping to zero so the
                # downstream vendor analysis still has candidates to rank.
                logger.warning(
                    f"[IDENTIFY_VENDORS] Requested vendors {final_vendors} have no catalog "
                    f"products for {detected_product_type!r}; keeping all {len(products)} "
                    f"available products from vendors present in the catalog."
                )
                state["vendor_filter_message"] = (
                    f"None of your selected vendors ({', '.join(final_vendors)}) have "
                    f"catalogued products for this product type. Showing the closest "
                    f"available matches instead."
                )

        # Filter by model families if specified
        specified_model_families = state.get("specified_model_families")
        if specified_model_families and products:
            filtered_products = []
            for product in products:
                model_family = product.get('model_family') or product.get('product_name', '')
                if any(m.lower() in model_family.lower() for m in specified_model_families):
                    filtered_products.append(product)
            products = filtered_products
            logger.info(f"[IDENTIFY_VENDORS] Filtered to {len(products)} products from model families: {specified_model_families}")

        if products:
            state["products"] = products
            state["products_json"] = json.dumps(products, ensure_ascii=False)
            state["total_found"] = len(products)
            logger.info(
                f"[IDENTIFY_VENDORS] EXIT SUCCESS — "
                f"total_found={state['total_found']} "
                f"product_type={detected_product_type!r} "
                f"final_vendors={final_vendors} "
                f"source_type={source_type!r}"
            )
        else:
            logger.warning(
                f"[IDENTIFY_VENDORS] EXIT — NO PRODUCTS — "
                f"product_type={detected_product_type!r} "
                f"final_vendors={final_vendors} "
                f"all_db_vendors={all_db_vendors} "
                f"source_vendors={source_vendors} "
                f"source_type={source_type!r}. "
                f"Possible causes: (1) vendors collection empty for this product_type, "
                f"(2) vendor name intersection mismatch, (3) category scraper not yet run."
            )
            state["error_message"] = f"No products found matching {detected_product_type}"
            _notify_failure(state, "Product Search",
                f"No products found in DB for: '{detected_product_type}'.",
                product_type=detected_product_type,
                filtered_vendors=final_vendors)

    except Exception as e:
        logger.exception(f"[IDENTIFY_VENDORS] Error in vendor identification: {e}")
        state["filtered_vendors"] = []
        state["vendor_priority_level"] = "error_fallback"
        state["vendor_filter_message"] = f"Vendor identification error: {str(e)}"
        state["error_message"] = f"Vendor identification error: {str(e)}"

    return state

def match_vendor_names(strategy_vendors: list[str], db_vendors: list[str]) -> list[str]:
    """
    Match strategy vendor names to database vendor names using LLM.
    Uses Gemini 2.5 Flash Lite with temperature 0.1 for fast, consistent matching.

    Args:
        strategy_vendors: Vendor names from strategy documents (e.g., ["emerson", "abb", "e+h"])
        db_vendors: Vendor names from database (e.g., ["Emerson", "ABB", "Endress+Hauser", "Yokogawa"])

    Returns:
        List of matched database vendor names (e.g., ["Emerson", "ABB", "Endress+Hauser"])
    """
    if not strategy_vendors or not db_vendors:
        logger.warning("[MATCH_VENDORS] Empty input - returning strategy vendors as-is")
        return strategy_vendors

    try:
        from common.ai.llm import get_lite_llm
        from langchain_core.prompts import ChatPromptTemplate
        from common.ai.prompts.response import VENDOR_MATCHING_PROMPT
        import re

        llm = get_lite_llm(temperature=0.1)

        prompt_text = ChatPromptTemplate.from_template(VENDOR_MATCHING_PROMPT).format(
            strategy_vendors_json=json.dumps(strategy_vendors, indent=2),
            db_vendors_json=json.dumps(db_vendors, indent=2)
        )

        resp = llm.invoke(prompt_text)
        text = str(resp.content).strip()

        # Strip markdown fences
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
        if text.endswith("```"):
            text = text[:-3]

        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            matched_vendors = json.loads(m.group(0))
            if isinstance(matched_vendors, list):
                # Filter to only include vendors that exist in db_vendors
                valid_matches = [v for v in matched_vendors if v in db_vendors]
                logger.info(f"[MATCH_VENDORS] Successfully matched {len(valid_matches)} vendors: {valid_matches}")
                return valid_matches
    except Exception as e:
        logger.warning(f"[MATCH_VENDORS] Vendor name matching failed: {e}")

    return strategy_vendors  # Fallback
