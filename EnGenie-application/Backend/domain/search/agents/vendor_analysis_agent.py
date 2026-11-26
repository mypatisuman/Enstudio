"""
Deep Analysis Agent for Search Workflow

Complete implementation matching the old API's analysis chain:
1. StructuredRequirementsGeneration
2. ProductTypeDetection
3. ProductDataLoading (from MongoDB)
4. VendorListLoading & Filtering
5. FilteredPDFLoading (Azure Blob)
6. ParallelVendorAnalysis (ThreadPoolExecutor)
7. FinalRanking

All data from MongoDB - no local files.
Returns ranked_products with standardized format.
"""

import json
from common.helpers.notifications import notify_failure as _notify_failure
import logging
import os
import threading
import time
from concurrent.futures import as_completed
# Context-propagating pool: keeps benchmark run/test attribution across worker
# threads (a plain ThreadPoolExecutor loses it, undercounting benchmark tokens).
from common.monitoring.benchmarking.context import BenchmarkThreadPoolExecutor as ThreadPoolExecutor
from datetime import datetime
from functools import cache
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from domain.search.services.product_service import _load_products_from_mongodb_direct, load_pdfs_from_database, load_pdfs_from_urls
from common.helpers.node_retry import is_transient_error
from common.infra.repositories.interaction_log_repository import interaction_logger

# LLM Manager
from common.ai.llm import LLM_PROVIDER, get_flash_llm, get_pro_llm
from common.ai.llm.config import PROVIDER_MODELS

# Google GenAI for direct PDF passing (Spatial AI)
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


def _pdf_chunk_chars() -> int:
    """PDF-text chunk size (chars) for deep analysis, bounded by the LLM's
    context window. Override with VENDOR_ANALYSIS_PDF_CHUNK_CHARS (default 300000)."""
    override = int(os.getenv("VENDOR_ANALYSIS_PDF_CHUNK_CHARS", "0"))
    if override > 0:
        return override
    return 300000

# LangSmith tracing for the raw google-genai SDK calls below.
# The LangChain-wrapped LLMs are auto-traced; this decorator covers the
# Spatial-AI path that bypasses LangChain by calling genai.Client directly.
from typing import Callable, TypeVar
_F = TypeVar("_F", bound=Callable[..., Any])
try:
    from langsmith import traceable  # type: ignore[import-not-found]
except ImportError:
    def traceable(*dargs: Any, **dkwargs: Any) -> Any:  # type: ignore[no-redef]
        # No-op fallback when langsmith is unavailable
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        def _decorator(fn: _F) -> _F:
            return fn
        return _decorator


def _spatial_ai_inputs_filter(inputs: dict) -> dict:
    """Strip raw PDF bytes from trace inputs — keep metadata only."""
    filtered = dict(inputs)
    pdf_list = filtered.get("pdf_bytes_list") or []
    try:
        filtered["pdf_bytes_list"] = (
            f"<{len(pdf_list)} PDFs, {sum(len(b) for b in pdf_list)} bytes total>"
        )
    except Exception:
        filtered["pdf_bytes_list"] = "<bytes>"
    return filtered


logger = logging.getLogger(__name__)




# ============================================================================
# LLM INSTANCES
# ============================================================================

_llm_pro = get_pro_llm(temperature=0.1)    # For deep vendor analysis based on requirements
_llm_flash = get_flash_llm(temperature=0.1)  # For ranking and simpler operations

# ============================================================================
# RATE LIMITER  (replaces fixed semaphore / worker cap / stagger delays)
# ============================================================================
#
# A token-bucket rate limiter is used instead of a fixed concurrency semaphore
# because it scales automatically to ANY number of parallel search instances:
#
#   N parallel searches → each gets ~rate/N LLM calls per second
#
# This means there is no hardcoded limit to configure — just add more search
# instances and the rate limiter distributes the budget fairly among them,
# preventing 429 bursts without any manual tuning.
#
# Tokens are added at LLM_CALLS_PER_SECOND (default 2.5) up to a burst
# capacity of LLM_BURST_CAPACITY (default 4). Both can be overridden via env
# if a higher-tier deployment supports more throughput.

class _LLMRateLimiter:
    """
    Process-wide token-bucket rate limiter for all LLM API calls made by
    vendor analysis threads, across every concurrent search instance.

    How it works
    ------------
    Tokens are added at `rate` per second up to `burst` capacity.  Each call
    to `acquire()` consumes one token; if the bucket is empty the caller
    sleeps in 50 ms increments until a token becomes available.

    This is strictly superior to a fixed semaphore when N parallel searches
    are active:  a semaphore with capacity K allows K simultaneous calls
    regardless of how many searches are fighting for them, which can still
    produce bursts.  The rate limiter instead caps the *rate* of new calls,
    so N searches each naturally get rate/N calls per second — no bursts.
    """

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate            # tokens / second
        self._capacity = float(burst)
        self._tokens = float(burst)  # start full so first calls are immediate
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now

    def acquire(self) -> None:
        """Block until one token is available (never raises)."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.05)  # 50 ms polling while waiting for next token

    # Context-manager support — token is consumed on entry, nothing to release.
    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_) -> None:
        pass


_llm_rate_limiter = _LLMRateLimiter(
    rate=float(os.getenv("LLM_CALLS_PER_SECOND", "2.5")),
    burst=int(os.getenv("LLM_BURST_CAPACITY", "4")),
)

# Circuit breaker: abort remaining vendors after this many consecutive hard
# failures (not timeouts/rate-limits — those are transient and shared across
# parallel search instances; counting them let one instance's final-analysis
# burst 429-starve its siblings into tripping THEIR breakers).  5 gives enough
# tolerance for a few empty vendors on a heavy model without killing an
# otherwise-good run.
_CIRCUIT_BREAKER_THRESHOLD = 5

# Cap on concurrently-running vendor-analysis threads PER search instance.
# Was referenced but never defined (NameError in the LLM-only fallback path),
# and the main path spawned one thread per vendor with no cap — multiplied
# across parallel search instances that saturates the shared LLM deployment.
_MAX_VENDOR_WORKERS = int(os.getenv("MAX_VENDOR_WORKERS", "5"))

# A catalog with fewer products than this AND no datasheet URLs is considered
# too sparse to trust a zero-match outcome from (typically a couple of
# just-scraped entries for a product type the DB doesn't cover yet). When such
# a catalog yields 0 matches, retry in knowledge-only mode so the user gets
# conservative approximate matches instead of an empty result.
_MIN_CATALOG_PRODUCTS = int(os.getenv("DEEP_ANALYSIS_MIN_CATALOG_PRODUCTS", "3"))

# Per-vendor timeout in seconds (default: 60s so slow vendors don't block the search).
_PER_VENDOR_TIMEOUT = int(os.getenv("DEEP_ANALYSIS_VENDOR_TIMEOUT", "60"))

# Max products analysed per LLM call. Cramming all of a large vendor's products
# into one call makes the JSON answer exceed the model's output-token budget →
# truncation → unparseable output (counted as a failure). Splitting products
# into sub-batches bounds each call's output size.
_PRODUCTS_PER_CALL = int(os.getenv("DEEP_ANALYSIS_PRODUCTS_PER_CALL", "12"))

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

def _load_prompt(filename: str) -> str:
    """Load a prompt file from the prompts directory with graceful fallback."""
    try:
        with open(os.path.join(_PROMPTS_DIR, filename), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {filename}")
        return ""

def flatten_schema_leaf_keys(schema: dict[str, Any]) -> list[str]:
    """Flatten a nested detected_schema/mapped_requirements dict (tier -> category -> field -> value)
    into an ordered, de-duplicated list of leaf field names to request per-vendor for the
    comparison table. Tolerates a flat {field: value} shape too (returns its keys directly)."""
    if not isinstance(schema, dict):
        return []

    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    tiers = ("mandatoryRequirements", "optionalRequirements", "latestRequirements", "advancedRequirements")
    has_tiers = any(tier in schema for tier in tiers)

    if has_tiers:
        for tier in tiers:
            categories = schema.get(tier)
            if not isinstance(categories, dict):
                continue
            for _category, fields in categories.items():
                if isinstance(fields, dict):
                    for field_name in fields:
                        _add(field_name)
    else:
        # Flat {field: value} schema — use keys directly.
        for field_name in schema:
            _add(field_name)

    return keys


def _discover_top_vendors_for_product(product_type: str, top_k: int = 5) -> list[str]:
    """
    Lightweight LLM-based vendor discovery used ONLY as a no-DB fallback.
    Kept here to avoid circular imports with search_agent.py.
    Returns a list of vendor name strings (no model-family details needed).
    """
    try:
        prompt = (
            f"List the top {top_k} industrial instrument manufacturers that make '{product_type}'. "
            f"Return ONLY a JSON array of proper vendor name strings, e.g. [\"Emerson\", \"ABB\"]. "
            f"No explanation."
        )
        resp = _llm_flash.invoke(prompt)
        text = str(resp.content).strip()
        # Strip markdown fences
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
        if text.endswith("```"):
            text = text[:-3]
        import re as _re_inner
        m = _re_inner.search(r'\[.*\]', text, _re_inner.DOTALL)
        if m:
            names = json.loads(m.group(0))
            if isinstance(names, list):
                return [str(n) for n in names[:top_k] if n]
    except Exception as e:
        logger.warning(f"[DEEP_ANALYSIS] _discover_top_vendors_for_product failed: {e}")
    return ["Emerson", "ABB", "Yokogawa", "Endress+Hauser", "Honeywell"]

FORMAT_INSTRUCTIONS = """
Return ONLY a valid JSON array matching the following schema, with no markdown formatting or code fences. If there are no matches, return an empty array [].
[
  {
    "product_name": "exact model name",
    "vendor": "vendor name",
    "model_family": "product family",
    "match_score": 85,
    "requirements_match": true,
    "reasoning": "detailed explanation incorporating both mandatory and optional analysis text",
    "limitations": "list of concerns or limitations based on the analysis",
    "spec_values": {"<comparison spec key>": "<value found in this vendor's source, or null if not stated>"}
  }
]
"""

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _extract_json_objects(text: str) -> list:
    """Best-effort recovery of JSON objects from possibly truncated/wrapped LLM
    output. Scans for balanced top-level {...} objects (respecting strings/escapes)
    and returns the ones that parse — so a response truncated mid-array (e.g. cut
    off at the model's output-token cap) still yields the complete objects that
    did arrive, instead of losing everything."""
    objects: list = []
    depth = 0
    start = None
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        objects.append(json.loads(text[start:i + 1]))
                    except Exception:
                        pass
                    start = None
    return objects


def _safe_json_parser():
    """
    Create a safe JSON parser that handles LLM output gracefully.
    Extracts JSON from markdown code fences and handles parsing errors.
    """
    class SafeJsonParser:
        def parse(self, text):
            """Parse JSON from LLM output with error handling."""
            try:
                # Handle AIMessage objects from LangChain
                if hasattr(text, 'content'):
                    text = text.content

                # Convert to string if needed
                if not isinstance(text, str):
                    text = str(text)

                # Remove markdown code fences if present
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    parts = text.split("```")
                    text = parts[1] if len(parts) > 1 else text

                text = text.strip()
                logger.debug(f"[DEEP_ANALYSIS] Parsing JSON: {text[:100]}...")

                # Try to parse as JSON
                result = json.loads(text)

                # Ensure it's a list
                if not isinstance(result, list):
                    logger.warning(f"[DEEP_ANALYSIS] JSON parsed but not a list, wrapping: {type(result)}")
                    result = [result] if result else []

                logger.debug(f"[DEEP_ANALYSIS] Successfully parsed JSON with {len(result)} items")
                return result

            except json.JSONDecodeError as e:
                # Salvage complete objects from truncated/wrapped output (e.g. a
                # response cut at the output-token cap) instead of losing all.
                salvaged = _extract_json_objects(text)
                if salvaged:
                    logger.warning(f"[DEEP_ANALYSIS] JSON parse failed ({e}); salvaged {len(salvaged)} object(s) from partial output")
                    return salvaged
                logger.exception(f"[DEEP_ANALYSIS] JSON parsing failed: {e}")
                logger.error(f"[DEEP_ANALYSIS] Failed to parse text: {text[:200]}")
                return []
            except Exception as e:
                logger.exception(f"[DEEP_ANALYSIS] Unexpected parsing error: {e}")
                return []

        def __call__(self, text):
            """Make parser callable."""
            return self.parse(text)

    return SafeJsonParser()


def _prepare_vendor_payloads(products_json: str, pdf_content: dict[str, str], pdf_bytes: dict[str, list[bytes]] = None) -> dict[str, dict[str, Any]]:
    """Prepare per-vendor analysis payloads.

    Includes ALL vendors that have products, regardless of whether they have PDFs.
    Vendors with PDFs get their documentation attached; vendors without PDFs are
    still analyzed using product JSON data alone.

    Now also includes raw PDF bytes for direct Spatial AI passing.
    """
    pdf_bytes = pdf_bytes or {}
    pdf_content = pdf_content or {}

    try:
        products = json.loads(products_json) if products_json else []
        vendor_payloads = {}

        # Step 1: Seed payloads from PDF content (vendors WITH PDFs)
        for vendor_name, text in pdf_content.items():
            vendor_payloads[vendor_name] = {
                "vendor_name": vendor_name,
                "products": [],
                "pdf_text": text,
                "pdf_bytes": pdf_bytes.get(vendor_name, [])  # Raw PDF bytes for Spatial AI
            }

        # Step 2: Also seed from pdf_bytes for vendors that may have bytes but no extracted text
        for vendor_name, bytes_list in pdf_bytes.items():
            if vendor_name not in vendor_payloads:
                vendor_payloads[vendor_name] = {
                    "vendor_name": vendor_name,
                    "products": [],
                    "pdf_text": "",
                    "pdf_bytes": bytes_list
                }

        # Step 3: Attach products to vendors AND create payloads for vendors WITHOUT PDFs
        for product in products:
            vendor_name = product.get('vendor') or product.get('vendor_name', 'Unknown')
            if vendor_name not in vendor_payloads:
                # Vendor has products but no PDF — still include for analysis
                vendor_payloads[vendor_name] = {
                    "vendor_name": vendor_name,
                    "products": [],
                    "pdf_text": "",
                    "pdf_bytes": []
                }
            vendor_payloads[vendor_name]["products"].append(product)

        # Final cleanup: deduplicate pdf_bytes if any overlaps occurred
        for v_data in vendor_payloads.values():
            if v_data["pdf_bytes"]:
                # Use list(dict.fromkeys()) to dedup bytes objects while preserving order
                # Note: bytes are hashable in Python
                try:
                    v_data["pdf_bytes"] = list(dict.fromkeys(v_data["pdf_bytes"]))
                except Exception:
                    pass

        vendors_with_pdf = sum(1 for v in vendor_payloads.values() if v.get("pdf_bytes") or v.get("pdf_text"))
        vendors_without_pdf = len(vendor_payloads) - vendors_with_pdf
        vendors_with_spatial = sum(1 for v in vendor_payloads.values() if v.get("pdf_bytes"))
        
        logger.info(f"[DEEP_ANALYSIS] Prepared {len(vendor_payloads)} grouped vendor payloads "
                     f"({vendors_with_pdf} with PDFs, {vendors_with_spatial} with raw bytes for Spatial AI, "
                     f"{vendors_without_pdf} without PDFs)")
        
        return vendor_payloads

    except Exception as e:
        logger.exception(f"[DEEP_ANALYSIS] Payload preparation failed: {e}")
        return {}

def _genai_usable() -> bool:
    """Disabled: DeepInfra is active provider; spatial AI is Google-specific."""
    return False


def _get_genai_client():
    """Get Google GenAI client for direct PDF passing."""
    if not GENAI_AVAILABLE:
        return None
    try:
        api_key = os.getenv("GOOGLE_API_KEY")  # Use Generative Language API key only; KEY1 is Custom Search
        if not api_key:
            return None
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.warning(f"[DEEP_ANALYSIS] Failed to initialize GenAI client: {e}")
        return None


@traceable(
    run_type="llm",
    name="VendorAnalysisSpatialAI",
    process_inputs=_spatial_ai_inputs_filter,
)
def _invoke_vendor_analysis_direct(
    vendor_name: str,
    pdf_bytes_list: list[bytes],
    products: list[dict],
    structured_requirements: str,
    applicable_standards: str = "",
    standards_specs: str = "",
    user_id: str = None,
    comparison_spec_keys: list[str] = None,
) -> dict[str, Any]:
    """Invoke vendor analysis by passing raw PDF bytes directly to Gemini (Spatial AI).

    This gives the LLM full spatial understanding of tables, diagrams, and layouts
    without any text extraction corruption.

    Returns:
        Dict with vendor_matches list, or None if direct PDF approach fails.
    """
    client = _get_genai_client()
    if not client:
        logger.warning(f"[DEEP_ANALYSIS] GenAI client not available for direct PDF analysis of {vendor_name}")
        return None

    try:
        # Load prompt template
        prompt_content = _load_prompt('vendor_analysis_agent.md')

        # Fill in prompt variables
        products_json = json.dumps(products, ensure_ascii=False)
        filled_prompt = prompt_content.replace("{vendor_name}", vendor_name)
        filled_prompt = filled_prompt.replace("{structured_requirements}", structured_requirements)
        filled_prompt = filled_prompt.replace("{applicable_standards}", applicable_standards or "No standards specified")
        filled_prompt = filled_prompt.replace("{standards_specs}", standards_specs or "No standards specs provided")
        filled_prompt = filled_prompt.replace("{pdf_content_json}", "[PDF documents are attached directly as files below — read them visually]")
        filled_prompt = filled_prompt.replace("{products_json}", products_json)
        filled_prompt = filled_prompt.replace("{comparison_spec_keys}", json.dumps(comparison_spec_keys or []))
        filled_prompt = filled_prompt.replace("{format_instructions}", FORMAT_INSTRUCTIONS)

        # Build multimodal content parts: prompt text + raw PDF files
        parts = [filled_prompt]

        for i, pdf_bytes in enumerate(pdf_bytes_list):
            parts.append(f"\n--- PDF Document {i+1} for {vendor_name} ---")
            parts.append(types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf'))

        total_pdf_size = sum(len(b) for b in pdf_bytes_list)

        # Get model name from provider configuration (only works with Google provider)
        if LLM_PROVIDER != "google":
            logger.warning(f"[DEEP_ANALYSIS] Direct PDF analysis only supports Google provider, current provider: {LLM_PROVIDER}")
            return None

        model_name = PROVIDER_MODELS.get("google", {}).get("pro", "gemini-2.5-pro")
        logger.info(f"[DEEP_ANALYSIS] 🚀 Sending {len(pdf_bytes_list)} raw PDFs ({total_pdf_size} bytes) directly to {model_name} for {vendor_name} (Spatial AI)")

        response = client.models.generate_content(
            model=model_name,
            contents=parts
        )

        # Extract token usage and record it
        try:
            from common.ai.llm import record_manual_usage
            usage = response.usage_metadata
            input_tokens = usage.prompt_token_count or 0
            output_tokens = usage.candidates_token_count or 0

            # Record manual usage (will fetch user_id from session if available)
            record_manual_usage(
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                agent_type="search",
                feature_type="deep_analysis",
                request_type="spatial_ai",
                user_id=user_id
            )
        except Exception as usage_err:
            logger.debug(f"[DEEP_ANALYSIS] Failed to record usage from Spatial AI: {usage_err}")

        # Parse JSON from response
        result_text = response.text.strip()
        parser = _safe_json_parser()
        parsed = parser.parse(result_text)

        if isinstance(parsed, list):
            result = {"vendor_matches": parsed}
        elif isinstance(parsed, dict):
            result = parsed if "vendor_matches" in parsed else {"vendor_matches": [parsed] if parsed else []}
        else:
            result = {"vendor_matches": []}

        logger.info(f"[DEEP_ANALYSIS] ✓ Spatial AI analysis complete for {vendor_name}: {len(result.get('vendor_matches', []))} matches")
        return result

    except Exception as e:
        logger.warning(f"[DEEP_ANALYSIS] ⚠️ Direct PDF (Spatial AI) failed for {vendor_name}: {e}")
        return None


def _invoke_chain_product_batched(
    vendor_chain,
    structured_requirements: str,
    vendor_name: str,
    products: list[dict],
    pdf_payload: str,
    applicable_standards: str = "",
    standards_specs: str = "",
    user_id: str = None,
    comparison_spec_keys: list[str] = None,
) -> dict[str, Any]:
    """Run the vendor chain over product sub-batches and merge the matches.

    Analysing every product of a large vendor in a single call makes the JSON
    answer exceed the model's output-token budget → truncation → unparseable
    output (counted as a vendor failure). Splitting products into groups of
    _PRODUCTS_PER_CALL keeps each call's output within budget; the full PDF text
    is passed to every sub-batch so matching context is preserved.
    """
    sub_batches = [products[i:i + _PRODUCTS_PER_CALL] for i in range(0, len(products), _PRODUCTS_PER_CALL)]
    logger.info(
        f"[DEEP_ANALYSIS] {vendor_name}: {len(products)} products → {len(sub_batches)} sub-batch(es) "
        f"of ≤{_PRODUCTS_PER_CALL} to bound output size"
    )

    all_matches: list = []
    for idx, sub in enumerate(sub_batches, 1):
        try:
            result = vendor_chain.invoke({
                "structured_requirements": structured_requirements,
                "products_json": json.dumps(sub, ensure_ascii=False),
                "pdf_content_json": pdf_payload,
                "applicable_standards": applicable_standards or "No standards specified",
                "standards_specs": standards_specs or "No standards specs provided",
                "vendor_name": vendor_name,
                "comparison_spec_keys": json.dumps(comparison_spec_keys or []),
            }, config={"metadata": {"user_id": user_id, "agent_type": "search"}})
            if isinstance(result, dict):
                matches = result.get("vendor_matches", [])
            elif isinstance(result, list):
                matches = result
            else:
                matches = []
            all_matches.extend(matches)
            logger.info(f"[DEEP_ANALYSIS] {vendor_name} sub-batch {idx}/{len(sub_batches)}: {len(matches)} matches")
        except Exception as e:  # noqa: BLE001 — one bad sub-batch shouldn't sink the vendor
            logger.error(f"[DEEP_ANALYSIS] {vendor_name} sub-batch {idx}/{len(sub_batches)} failed: {e}")
            continue

    # Products are partitioned across sub-batches; dedup by product_name
    # defensively (keep higher score) without dropping unnamed matches.
    unique: dict = {}
    passthrough: list = []
    for m in all_matches:
        pname = m.get("product_name", "") if isinstance(m, dict) else ""
        if not pname:
            passthrough.append(m)
            continue
        if pname not in unique or m.get("match_score", 0) > unique[pname].get("match_score", 0):
            unique[pname] = m
    merged = list(unique.values()) + passthrough
    logger.info(f"[DEEP_ANALYSIS] ✓ {vendor_name} product-batched analysis: {len(merged)} matches from {len(sub_batches)} sub-batch(es)")
    return {"vendor_matches": merged}


def _invoke_vendor_chain(
    vendor_chain,
    structured_requirements: str,
    vendor_name: str,
    vendor_data: dict[str, Any],
    applicable_standards: str = "",
    standards_specs: str = "",
    user_id: str = None,
    comparison_spec_keys: list[str] = None,
) -> dict[str, Any]:
    """Invoke vendor chain for single vendor analysis with error handling.

    Strategy:
    1. Acquire one token from _llm_rate_limiter before any LLM call.  The
       rate limiter distributes capacity fairly across ALL concurrent search
       instances without requiring any fixed configuration.
    2. Try direct PDF passing via Spatial AI (raw bytes → Gemini) for best accuracy.
    3. Fallback to text-based LangChain chain if Spatial AI fails.
    4. If text-based also hits token limit, use chunked processing.
    5. On rate-limit errors, sleep with jitter before re-raising so the
       with_retry wrapper in manager.py gets breathing room.
    """
    import random as _random

    # Acquire a rate-limiter token BEFORE any LLM work.  This is the single
    # choke-point that keeps concurrent searches from overwhelming the API
    # regardless of how many search instances are active.
    with _llm_rate_limiter:
      try:
        pdf_bytes_list = vendor_data.get("pdf_bytes", [])
        pdf_text = vendor_data.get("pdf_text", "")
        products = vendor_data.get("products", [])

        logger.info(
            f"[DEEP_ANALYSIS][_invoke_vendor_chain] ENTER (rate-limiter token acquired) — "
            f"vendor={vendor_name!r} "
            f"products={len(products)} "
            f"raw_pdf_count={len(pdf_bytes_list)} "
            f"pdf_text_len={len(pdf_text)} "
            f"thread={threading.current_thread().name} "
            f"active_threads={threading.active_count()} "
            f"genai_usable={_genai_usable()}"
        )

        # === PRIMARY: Try direct PDF passing via Spatial AI ===
        # Requires a configured Google key; Kimi-only deployments skip straight
        # to text-based analysis instead of attempting + falling back per vendor.
        if pdf_bytes_list and _genai_usable():
            logger.info(f"[DEEP_ANALYSIS] 📄 Attempting Spatial AI (direct PDF) for {vendor_name}...")
            result = _invoke_vendor_analysis_direct(
                vendor_name=vendor_name,
                pdf_bytes_list=pdf_bytes_list,
                products=products,
                structured_requirements=structured_requirements,
                applicable_standards=applicable_standards,
                standards_specs=standards_specs,
                user_id=user_id,
                comparison_spec_keys=comparison_spec_keys,
            )
            if result is not None and result.get("vendor_matches"):
                logger.info(f"[DEEP_ANALYSIS] ✓ Spatial AI succeeded for {vendor_name}")
                return result
            elif result is not None:
                logger.info(f"[DEEP_ANALYSIS] Spatial AI returned no matches for {vendor_name}, falling back to text-based analysis")
            else:
                logger.info(f"[DEEP_ANALYSIS] Spatial AI failed for {vendor_name}, falling back to text-based analysis")

        # === FALLBACK: Text-based LangChain chain ===
        pdf_payload = json.dumps({vendor_name: pdf_text}, ensure_ascii=False) if pdf_text else "{}"
        products_payload = json.dumps(products, ensure_ascii=False)

        logger.info(f"[DEEP_ANALYSIS] 📝 Using text-based analysis for {vendor_name} (text length: {len(pdf_text)})")

        # Proactive chunking for large text content to avoid context-window
        # overflows and API timeouts. Chunk size is capped by the model's
        # context window regardless of how large the input is.
        chunk_size = _pdf_chunk_chars()
        if len(pdf_text) > chunk_size:
            logger.info(f"[DEEP_ANALYSIS] 📝 Text length {len(pdf_text)} exceeds chunk limit {chunk_size}. Running proactive chunked analysis...")

            result = _invoke_vendor_chain_chunked(
                vendor_chain=vendor_chain,
                structured_requirements=structured_requirements,
                vendor_name=vendor_name,
                products=products,
                pdf_text=pdf_text,
                applicable_standards=applicable_standards,
                standards_specs=standards_specs,
                chunk_size=chunk_size,
                comparison_spec_keys=comparison_spec_keys,
            )
            logger.info(f"[DEEP_ANALYSIS] ✓ Proactive chunked analysis complete for {vendor_name}: {len(result.get('vendor_matches', []))} matches")
            return result

        # Bound OUTPUT size: many products in one call make the JSON answer
        # exceed the model's max_tokens → truncated → unparseable. Split the
        # products into sub-batches so each call's output stays within budget.
        if len(products) > _PRODUCTS_PER_CALL:
            return _invoke_chain_product_batched(
                vendor_chain, structured_requirements, vendor_name, products,
                pdf_payload, applicable_standards, standards_specs, user_id,
                comparison_spec_keys,
            )

        try:
            result = vendor_chain.invoke({
                "structured_requirements": structured_requirements,
                "products_json": products_payload,
                "pdf_content_json": pdf_payload,
                "applicable_standards": applicable_standards or "No standards specified",
                "standards_specs": standards_specs or "No standards specs provided",
                "vendor_name": vendor_name,
                "comparison_spec_keys": json.dumps(comparison_spec_keys or []),
            }, config={"metadata": {"user_id": user_id, "agent_type": "search"}})

            # Format result
            if not isinstance(result, dict):
                logger.warning(f"[DEEP_ANALYSIS] Vendor chain returned non-dict result for {vendor_name}: {type(result)}")
                result = {"vendor_matches": result if isinstance(result, list) else []}

            if "vendor_matches" not in result:
                vendor_matches = result if isinstance(result, list) else []
                result = {"vendor_matches": vendor_matches}

            logger.info(f"[DEEP_ANALYSIS] ✓ Vendor {vendor_name} text-based analysis complete: {len(result.get('vendor_matches', []))} matches")
            return result

        except Exception as token_error:
            # Check if it's a token limit or timeout error
            error_str = str(token_error).lower()
            is_token_limit = any(keyword in error_str for keyword in [
                "token count exceeds",
                "maximum number of tokens",
                "token limit",
                "input too long"
            ])
            is_timeout = any(keyword in error_str for keyword in [
                "read operation timed out",
                "timeout",
                "timed out",
                "request timeout",
                "connection timeout",
                "read timeout"
            ])

            if is_token_limit or is_timeout:
                # RETRY: Use chunked processing
                error_type = "Token limit" if is_token_limit else "Timeout"
                logger.warning(f"[DEEP_ANALYSIS] ⚠️ {error_type} exceeded for {vendor_name} (PDF: {len(pdf_text)} chars)")
                logger.info("[DEEP_ANALYSIS] Retrying with chunked analysis...")

                result = _invoke_vendor_chain_chunked(
                    vendor_chain=vendor_chain,
                    structured_requirements=structured_requirements,
                    vendor_name=vendor_name,
                    products=products,
                    pdf_text=pdf_text,
                    applicable_standards=applicable_standards,
                    standards_specs=standards_specs,
                    chunk_size=_pdf_chunk_chars(),
                    comparison_spec_keys=comparison_spec_keys,
                )

                logger.info(f"[DEEP_ANALYSIS] ✓ Chunked analysis complete for {vendor_name}: {len(result.get('vendor_matches', []))} matches")
                return result
            else:
                # Not a token error - re-raise original exception
                raise

      except Exception as e:
        error_str = str(e).lower()
        is_rate_limit = any(kw in error_str for kw in ("429", "rate limit", "ratelimit", "quota", "resource exhausted", "too many requests"))
        is_timeout = any(kw in error_str for kw in ("timeout", "timed out", "deadline exceeded"))
        is_token_limit = any(kw in error_str for kw in ("token count exceeds", "maximum number of tokens", "token limit", "input too long"))
        error_class = "rate_limit" if is_rate_limit else ("timeout" if is_timeout else ("token_limit" if is_token_limit else "unknown"))

        if is_rate_limit:
            # Sleep with jitter before re-raising so the with_retry wrapper in
            # manager.py (which uses wait_exponential_jitter=True) gets breathing
            # room between attempts instead of hammering the endpoint again.
            _sleep_secs = _random.uniform(3.0, 8.0)
            logger.warning(
                f"[DEEP_ANALYSIS][_invoke_vendor_chain] Rate-limited for {vendor_name!r}. "
                f"Sleeping {_sleep_secs:.1f}s before re-raising for retry wrapper. error={e!r}"
            )
            time.sleep(_sleep_secs)

        logger.exception(
            f"[DEEP_ANALYSIS][_invoke_vendor_chain] FAILED — "
            f"vendor={vendor_name!r} "
            f"error_class={error_class!r} "
            f"error={e!r} "
            f"products={len(vendor_data.get('products', []))} "
            f"pdf_text_len={len(vendor_data.get('pdf_text', ''))} "
            f"thread={threading.current_thread().name}"
        )
        return {"vendor_matches": [], "error": str(e)}


def _invoke_vendor_chain_chunked(
    vendor_chain,
    structured_requirements: str,
    vendor_name: str,
    products: list[dict],
    pdf_text: str,
    applicable_standards: str = "",
    standards_specs: str = "",
    chunk_size: int | None = None,
    comparison_spec_keys: list[str] = None,
) -> dict[str, Any]:
    """
    Process large PDF in chunks and combine results in parallel.

    For vendors with very large PDFs (e.g., complete product catalogs),
    split the PDF into chunks and analyze each chunk in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor
    try:
        chunk_size = chunk_size or _pdf_chunk_chars()
        # Split PDF into chunks
        chunks = []
        for i in range(0, len(pdf_text), chunk_size):
            chunk = pdf_text[i:i + chunk_size]
            chunks.append(chunk)

        logger.info(f"[DEEP_ANALYSIS] Processing {vendor_name} in {len(chunks)} chunks ({chunk_size} chars each) sequentially to prevent rate limits")

        all_matches = []
        products_payload = json.dumps(products, ensure_ascii=False)

        # Process each chunk sequentially
        for chunk_idx, chunk in enumerate(chunks, 1):
            try:
                # Add a brief pause between chunks to give the API rate limits time to breathe
                if chunk_idx > 1:
                    import time
                    time.sleep(2.0)

                logger.info(f"[DEEP_ANALYSIS] Processing chunk {chunk_idx}/{len(chunks)} for {vendor_name}")

                pdf_payload = json.dumps({vendor_name: chunk}, ensure_ascii=False)

                result = vendor_chain.invoke({
                    "structured_requirements": structured_requirements,
                    "products_json": products_payload,
                    "pdf_content_json": pdf_payload,
                    "applicable_standards": applicable_standards or "No standards specified",
                    "standards_specs": standards_specs or "No standards specs provided",
                    "vendor_name": vendor_name,
                    "comparison_spec_keys": json.dumps(comparison_spec_keys or []),
                })

                # Extract matches from this chunk
                if isinstance(result, dict):
                    chunk_matches = result.get("vendor_matches", [])
                elif isinstance(result, list):
                    chunk_matches = result
                else:
                    chunk_matches = []

                logger.info(f"[DEEP_ANALYSIS] Chunk {chunk_idx}/{len(chunks)} for {vendor_name}: {len(chunk_matches)} matches found")
                all_matches.extend(chunk_matches)
            except Exception as chunk_error:
                logger.error(f"[DEEP_ANALYSIS] Chunk {chunk_idx} failed for {vendor_name}: {chunk_error}")
                continue

        # Deduplicate matches by product_name
        unique_matches = {}
        for match in all_matches:
            product_name = match.get("product_name", "")
            if product_name:
                # Keep the match with highest score
                if product_name not in unique_matches:
                    unique_matches[product_name] = match
                else:
                    existing_score = unique_matches[product_name].get("match_score", 0)
                    new_score = match.get("match_score", 0)
                    if new_score > existing_score:
                        unique_matches[product_name] = match

        final_matches = list(unique_matches.values())
        logger.info(f"[DEEP_ANALYSIS] ✓ Chunked analysis complete for {vendor_name}: {len(final_matches)} unique matches (from {len(all_matches)} total)")

        return {"vendor_matches": final_matches}

    except Exception as e:
        logger.exception(f"[DEEP_ANALYSIS] Chunked analysis failed for {vendor_name}: {e}")
        return {"vendor_matches": [], "error": str(e)}

def _run_parallel_vendor_analysis(
    structured_requirements: str,
    products_json: str,
    pdf_content: dict[str, str],
    vendor_chain,
    applicable_standards: str = "",
    standards_specs: str = "",
    user_id: str = None,
    stream_id: str = None,
    pdf_bytes: dict[str, list[bytes]] = None,
    comparison_spec_keys: list[str] = None,
) -> dict[str, Any]:
    def _emit(message, progress):
        if stream_id:
            try:
                from common.helpers.progress_tracker import progress_tracker
                progress_tracker.emit(stream_id, "step", {"message": message, "progress": progress})
            except Exception:
                pass
    """Run vendor analysis in parallel using ThreadPoolExecutor with robust error handling.

    Improvements over original:
    - Capped max_workers to _MAX_VENDOR_WORKERS (default 5) to avoid API rate-limit cascades
    - Circuit breaker: aborts remaining vendors after _CIRCUIT_BREAKER_THRESHOLD consecutive failures
    - Configurable per-vendor timeout via _PER_VENDOR_TIMEOUT
    """
    try:
        payloads = _prepare_vendor_payloads(products_json, pdf_content, pdf_bytes=pdf_bytes)

        if not payloads:
            logger.warning(
                f"[DEEP_ANALYSIS][_run_parallel_vendor_analysis] No vendor payloads — "
                f"products_json_len={len(products_json) if products_json else 0} "
                f"pdf_content_vendors={list(pdf_content.keys()) if pdf_content else []} "
                f"pdf_bytes_vendors={list(pdf_bytes.keys()) if pdf_bytes else []}"
            )
            return {"vendor_matches": [], "vendor_run_details": []}

        # All vendors are submitted to a SINGLE thread pool capped at
        # _MAX_VENDOR_WORKERS.  Rate limiting is additionally handled inside
        # each worker (_invoke_vendor_chain acquires a token from
        # _llm_rate_limiter before touching the LLM).  The cap matters when
        # several search instances run in parallel: an uncapped per-vendor
        # fan-out multiplied across instances saturates the shared LLM
        # deployment and 429-starves the sibling instances.
        all_vendor_items = list(payloads.items())
        total_vendors = len(all_vendor_items)
        pool_workers = min(total_vendors, _MAX_VENDOR_WORKERS) or 1

        logger.info(
            f"[DEEP_ANALYSIS][_run_parallel_vendor_analysis] START — "
            f"vendors={list(payloads.keys())} "
            f"total={total_vendors} "
            f"pool_workers={pool_workers} "
            f"rate_limiter={_llm_rate_limiter._rate:.1f} calls/s "
            f"burst={int(_llm_rate_limiter._capacity)} "
            f"timeout={_PER_VENDOR_TIMEOUT}s "
            f"circuit_breaker_threshold={_CIRCUIT_BREAKER_THRESHOLD} "
            f"thread={threading.current_thread().name} "
            f"active_threads={threading.active_count()}"
        )

        all_vendor_matches = []
        vendor_run_details = []
        consecutive_failures = 0
        circuit_broken = False
        completed_count = 0

        _emit("Deep Vendor Analysis", 75)

        with ThreadPoolExecutor(max_workers=pool_workers) as executor:
            futures = {
                executor.submit(
                    _invoke_vendor_chain,
                    vendor_chain,
                    structured_requirements,
                    vendor_name,
                    vendor_data,
                    applicable_standards,
                    standards_specs,
                    user_id,
                    comparison_spec_keys,
                ): vendor_name
                for vendor_name, vendor_data in all_vendor_items
            }

            for future in as_completed(futures):
                vendor_name = futures[future]
                completed_count += 1

                if circuit_broken:
                    future.cancel()
                    vendor_run_details.append({
                        "vendor_name": vendor_name,
                        "success": False,
                        "error": "Skipped — circuit breaker tripped due to consecutive failures"
                    })
                    logger.warning(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] ⚡ {vendor_name}: SKIPPED (circuit breaker)")
                    continue

                try:
                    result = future.result(timeout=_PER_VENDOR_TIMEOUT)

                    if isinstance(result, dict):
                        matches = result.get('vendor_matches', [])
                        error = result.get('error', '')

                        vendor_run_details.append({
                            "vendor_name": vendor_name,
                            "matches_found": len(matches) if matches else 0,
                            "success": not error,
                            "error": error if error else ""
                        })

                        if matches:
                            all_vendor_matches.extend(matches)
                            consecutive_failures = 0
                            logger.info(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] ✓ {vendor_name}: {len(matches)} matches found")
                        elif error:
                            # Transient failures (429 rate-limit, quota, timeout,
                            # 5xx) are contention with OTHER parallel search
                            # instances, not evidence this run is broken — they
                            # must not trip the circuit breaker and abort the
                            # remaining vendors.
                            if is_transient_error(Exception(error)):
                                logger.warning(
                                    f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: "
                                    f"transient failure (NOT counted toward circuit breaker): {error}"
                                )
                            else:
                                consecutive_failures += 1
                            logger.info(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: No matches (error: {error})")
                        else:
                            consecutive_failures = 0
                            logger.info(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: No matches (no error)")
                    else:
                        consecutive_failures += 1
                        logger.warning(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: Invalid result type: {type(result)}")
                        vendor_run_details.append({
                            "vendor_name": vendor_name,
                            "success": False,
                            "error": f"Invalid result type: {type(result)}"
                        })

                except TimeoutError:
                    # Timeout = slowness, not a systemic failure.  Do NOT
                    # count toward circuit breaker.
                    logger.error(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: Timed out after {_PER_VENDOR_TIMEOUT}s")
                    vendor_run_details.append({
                        "vendor_name": vendor_name,
                        "success": False,
                        "error": f"Analysis timed out after {_PER_VENDOR_TIMEOUT}s"
                    })

                except Exception as e:
                    # Same transient-vs-hard split as above: don't let shared
                    # LLM/API contention from sibling searches abort this run.
                    if is_transient_error(e):
                        logger.warning(
                            f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: "
                            f"transient error (NOT counted toward circuit breaker): {e}"
                        )
                    else:
                        consecutive_failures += 1
                    logger.exception(f"[DEEP_ANALYSIS] [{completed_count}/{total_vendors}] {vendor_name}: Error during analysis: {e}")
                    vendor_run_details.append({
                        "vendor_name": vendor_name,
                        "success": False,
                        "error": str(e)
                    })

                # Circuit breaker check
                if consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                    remaining = total_vendors - completed_count
                    if remaining > 0:
                        circuit_broken = True
                        logger.error(
                            f"[DEEP_ANALYSIS] ⚡ CIRCUIT BREAKER TRIPPED: {consecutive_failures} consecutive failures. "
                            f"Cancelling {remaining} remaining vendor analyses to prevent cascade."
                        )
                        for f in futures:
                            f.cancel()
                        break

                # Emit rolling progress (75 % → 85 %)
                progress_pct = 75 + int((completed_count / total_vendors) * 10)
                _emit("Deep Vendor Analysis", progress_pct)

        if circuit_broken:
            logger.warning(f"[DEEP_ANALYSIS] Parallel analysis PARTIALLY complete (circuit breaker): "
                           f"{len(all_vendor_matches)} matches from {completed_count - (len(payloads) - completed_count)} vendors")
        else:
            logger.info(f"[DEEP_ANALYSIS] Parallel analysis complete: {len(all_vendor_matches)} total matches found across {len(payloads)} vendors")

        return {
            "vendor_matches": all_vendor_matches,
            "vendor_run_details": vendor_run_details
        }

    except Exception as e:
        logger.exception(f"[DEEP_ANALYSIS] Parallel analysis initialization failed: {e}")
        return {"vendor_matches": [], "vendor_run_details": [], "error": str(e)}


def run_vendor_analysis(
    user_input: str,
    structured_requirements: str = "",
    search_session_id: str = "",
    specified_vendors: list[str] = None,
    applicable_standards: list[str] = None,
    standards_specs: dict[str, Any] = None,
    product_type: str = None,
    stream_id: str = None,
    user_id: str = None,
    products_json: str = None,
    preloaded_pdf_content: dict[str, str] = None,
    preloaded_pdf_bytes: dict[str, list[bytes]] = None,
    comparison_spec_keys: list[str] = None,
) -> dict[str, Any]:
    """
    Execute complete deep analysis chain matching old API.

    Steps:
    1. Load products from MongoDB (skip if products_json provided)
    2. Load and filter vendors
    3. Load PDFs for filtered vendors (skip if preloaded_pdf_content/preloaded_pdf_bytes provided)
    4. Run parallel vendor analysis

    Args:
        user_input: Original user input
        structured_requirements: LLM-extracted structured requirements
        search_session_id: Session identifier
        specified_vendors: Optional list of specific vendors to analyze
        applicable_standards: List of applicable standards
        standards_specs: Dictionary of standards specifications
        product_type: Detected product type
        stream_id: SSE stream ID for live progress updates
        user_id: Authenticated user ID
        products_json: Pre-loaded products JSON (skip MongoDB re-query)
        preloaded_pdf_content: Pre-loaded PDF text per vendor (skip Azure Blob re-download)
        preloaded_pdf_bytes: Pre-loaded raw PDF bytes per vendor (skip Azure Blob re-download)

    Returns:
        Dict with vendor_analysis and overall_ranking
    """
    _active_instances = threading.active_count()
    logger.info(
        f"[DEEP_ANALYSIS] run_vendor_analysis ENTER — "
        f"session={search_session_id!r} "
        f"product_type={product_type!r} "
        f"thread={threading.current_thread().name} "
        f"active_threads={_active_instances} "
        f"has_preloaded_pdf_content={preloaded_pdf_content is not None} "
        f"has_preloaded_pdf_bytes={preloaded_pdf_bytes is not None} "
        f"specified_vendors={specified_vendors} "
        f"stream_id={stream_id!r}"
    )
    logger.info(f"[DEEP_ANALYSIS] Starting complete analysis chain for session {search_session_id}")
    logger.info(f"[DEEP_ANALYSIS] user_input: {user_input}")
    logger.info(f"[DEEP_ANALYSIS] structured_requirements: {structured_requirements}")

    # Helper to emit SSE events safely
    def _emit(message, progress):
        if stream_id:
            try:
                from common.helpers.progress_tracker import progress_tracker
                progress_tracker.emit(stream_id, "step", {"message": message, "progress": progress})
            except Exception:
                pass

    try:
        # Step 1: Load products — 5-tier L3→L4 traversal first, flat catalog as fallback
        logger.info("[DEEP_ANALYSIS] Step 1: ProductDataLoading")
        if not products_json:
            _pt = product_type if product_type else user_input
            try:
                from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
                logger.info(
                    f"[5TIER_AUDIT][vendor_analysis] STEP1_PRODUCTS attempting "
                    f"source=Restructured DB method=get_vendor_products_by_name "
                    f"traversal=L2->L3->L4 product_type={_pt!r}"
                )
                tier_products = ProductHierarchyRepository.get_vendor_products_by_name(_pt)
                if tier_products:
                    products_json = json.dumps(tier_products, ensure_ascii=False)
                    vendors_found = list({p.get("vendor") or p.get("vendor_name") for p in tier_products if p.get("vendor") or p.get("vendor_name")})
                    has_url = sum(1 for p in tier_products if p.get("datasheet_url"))
                    logger.info(
                        f"[5TIER_AUDIT][vendor_analysis] STEP1_PRODUCTS=5-tier-SUCCESS "
                        f"db=Restructured collections=L3+L4 "
                        f"product_type={_pt!r} total={len(tier_products)} "
                        f"unique_vendors={len(vendors_found)} vendors={vendors_found} "
                        f"with_datasheet_url={has_url}/{len(tier_products)}"
                    )
                else:
                    logger.warning(
                        f"[5TIER_AUDIT][vendor_analysis] STEP1_PRODUCTS=FALLBACK-flat-vendors "
                        f"reason=5-tier returned 0 products "
                        f"db=product-recommender collection=vendors product_type={_pt!r}"
                    )
                    products_json = _load_products_from_mongodb_direct(_pt)
            except Exception as _tier_err:
                logger.warning(
                    f"[5TIER_AUDIT][vendor_analysis] STEP1_PRODUCTS=FALLBACK-flat-vendors "
                    f"reason=5-tier exception: {_tier_err} "
                    f"db=product-recommender collection=vendors"
                )
                products_json = _load_products_from_mongodb_direct(_pt)
        else:
            _preloaded = json.loads(products_json) if products_json else []
            has_url = sum(1 for p in _preloaded if p.get("datasheet_url"))
            logger.info(
                f"[5TIER_AUDIT][vendor_analysis] STEP1_PRODUCTS=preloaded-from-state "
                f"total={len(_preloaded)} with_datasheet_url={has_url}/{len(_preloaded)} "
                f"(already loaded by identify_vendors_agent)"
            )
        logger.info(f"[DEEP_ANALYSIS] Products loaded: {len(json.loads(products_json) if products_json else [])} products")

        # Check if we got any products
        products_list = json.loads(products_json) if products_json and products_json != "[]" else []
        if not products_list:
            logger.warning("[DEEP_ANALYSIS] No products found in MongoDB — attempting LLM-only analysis without product JSON")

            # Notify Admin
            _notify_failure("Deep Analysis Agent - Data Loading",
                f"No products found in MongoDB for: {product_type or user_input}. Falling back to LLM-only analysis.",
                product_type=product_type or user_input)

            # Discover top vendors via LLM and attempt analysis without DB products.
            # IMPORTANT: do NOT import from search_agent here — circular import.
            # Use the local _discover_top_vendors_for_product helper.
            product_label = product_type or user_input
            _emit("Verifying Vendors", 65)
            try:
                fallback_vendors = _discover_top_vendors_for_product(product_label, top_k=5)
                if specified_vendors:
                    # Prefer user-specified vendors even when DB is empty
                    fallback_vendors = specified_vendors[:5] or fallback_vendors
            except Exception as disc_err:
                logger.warning(f"[DEEP_ANALYSIS] Vendor discovery for LLM-only fallback failed: {disc_err}")
                fallback_vendors = specified_vendors[:5] if specified_vendors else [
                    "Emerson", "ABB", "Yokogawa", "Endress+Hauser", "Honeywell"
                ]

            if not fallback_vendors:
                logger.error("[DEEP_ANALYSIS] LLM-only fallback: vendor discovery also failed — using hardcoded defaults")
                fallback_vendors = ["Emerson", "ABB", "Yokogawa", "Endress+Hauser", "Honeywell"]

            # Build an empty-products payload so _prepare_vendor_payloads gets vendor entries
            _emit("Verifying Datasheets", 70)
            pdf_result = load_pdfs_from_database(
                product_type=product_label,
                filtered_vendors=fallback_vendors
            )
            pdf_content = pdf_result.get("pdf_content", {})
            pdf_bytes_fallback = pdf_result.get("pdf_bytes", {})

            # Seed vendor payloads manually since products list is empty.
            # When a vendor has no PDF text, inject a knowledge-only note so the
            # LLM uses its training-data knowledge of that vendor's product line
            # instead of returning empty matches due to a missing-context prompt.
            _knowledge_only_note = (
                f"[NO DATASHEET AVAILABLE — USE GENERAL KNOWLEDGE]\n"
                f"No product datasheets or catalog data were found for this vendor.\n"
                f"Use your knowledge of {product_label} products from this vendor to\n"
                f"evaluate suitability against the user requirements. Estimate match\n"
                f"scores conservatively (≤0.70) to reflect the uncertainty."
            )
            vendor_payloads_fallback: dict[str, dict] = {}
            for vname in fallback_vendors:
                _pdf_text = pdf_content.get(vname, "")
                if not _pdf_text:
                    _pdf_text = _knowledge_only_note.replace("{product_label}", product_label)
                    logger.info(f"[DEEP_ANALYSIS] No PDF for fallback vendor '{vname}' — injecting knowledge-only note")
                vendor_payloads_fallback[vname] = {
                    "vendor_name": vname,
                    "products": [],
                    "pdf_text": _pdf_text,
                    "pdf_bytes": pdf_bytes_fallback.get(vname, [])
                }

            prompt_content = _load_prompt("vendor_analysis_agent.md")
            vendor_prompt = ChatPromptTemplate.from_template(prompt_content).partial(
                format_instructions=FORMAT_INSTRUCTIONS
            )
            vendor_chain = vendor_prompt | _llm_pro | _safe_json_parser()

            standards_str_fb = "\n".join(applicable_standards) if applicable_standards else "No standards"
            specs_str_fb = "\n".join(
                [f"{k}: {v}" for k, v in (standards_specs or {}).items()]
            ) if standards_specs else "No specs"

            # Run parallel analysis with seeded payloads
            all_vendor_matches_fb: list[dict] = []
            vendor_run_details_fb: list[dict] = []
            
            # Process in batches of _MAX_VENDOR_WORKERS (5)
            batch_size_fb = _MAX_VENDOR_WORKERS
            payload_items_fb = list(vendor_payloads_fallback.items())
            batches_fb = [payload_items_fb[i:i + batch_size_fb] for i in range(0, len(payload_items_fb), batch_size_fb)]
            
            for batch_idx, batch in enumerate(batches_fb, 1):
                logger.info(f"[DEEP_ANALYSIS] Fallback Batch {batch_idx}/{len(batches_fb)}...")
                with ThreadPoolExecutor(max_workers=len(batch)) as ex:
                    futs = {
                        ex.submit(
                            _invoke_vendor_chain,
                            vendor_chain,
                            structured_requirements or user_input,
                            vname,
                            vdata,
                            standards_str_fb,
                            specs_str_fb,
                            user_id,
                            comparison_spec_keys,
                        ): vname
                        for vname, vdata in batch
                    }
                    for fut in as_completed(futs):
                        vname = futs[fut]
                        try:
                            res = fut.result(timeout=_PER_VENDOR_TIMEOUT)
                            matches = res.get("vendor_matches", []) if isinstance(res, dict) else []
                            vendor_run_details_fb.append({
                                "vendor_name": vname,
                                "matches_found": len(matches),
                                "success": True,
                                "error": ""
                            })
                            all_vendor_matches_fb.extend(matches)
                        except Exception as fe:
                            vendor_run_details_fb.append({
                                "vendor_name": vname,
                                "success": False,
                                "error": str(fe)
                            })

            # Ranking is handled downstream by vendor_ranking_agent
            fallback_ranking = {"ranked_products": all_vendor_matches_fb}
            logger.info(
                f"[DEEP_ANALYSIS] LLM-only fallback complete: "
                f"{len(all_vendor_matches_fb)} vendor matches produced"
            )
            if not all_vendor_matches_fb:
                logger.warning(
                    "[DEEP_ANALYSIS] LLM-only fallback produced 0 matches — "
                    "vendors had no product data and LLM returned no results. "
                    "Root cause: product catalog not populated for this product type."
                )
            return {
                "vendor_analysis": {"vendor_matches": all_vendor_matches_fb, "vendor_run_details": vendor_run_details_fb},
                "overall_ranking": fallback_ranking,
            }

        # Step 2: Load and filter vendors
        logger.info("[DEEP_ANALYSIS] Step 2: VendorListLoading")
        _emit("Verifying Vendors", 65)
        products_list_for_families = json.loads(products_json) if products_json and products_json != "[]" else []
        
        # Extract raw vendors
        raw_vendors = set()
        for p in products_list_for_families:
            v = p.get('vendor') or p.get('vendor_name')
            if v:
                raw_vendors.add(v.strip())
        
        # Vendors are already filtered and capped by identify_vendors_agent
        unique_vendors = {v.lower(): v for v in raw_vendors}
        vendors_list = list(unique_vendors.values())
        
        vendor_filter_note = ""
        if specified_vendors:
            requested_matches = [v for v in vendors_list if any(sv.lower() in v.lower() for sv in specified_vendors)]
            if requested_matches:
                vendors_list = requested_matches
            elif vendors_list:
                # None of the user-requested vendors have catalog products for this
                # product type, but other vendors do. Rather than returning zero
                # products (hard fail), fall back to the available vendor pool and
                # flag it so the UI can explain the substitution.
                vendor_filter_note = (
                    f"None of your selected vendors ({', '.join(specified_vendors)}) have "
                    f"catalogued products for this product type. Showing the closest "
                    f"available matches from: {', '.join(vendors_list)}."
                )
                logger.warning(
                    f"[DEEP_ANALYSIS] Requested vendors {specified_vendors} have no catalog "
                    f"products; falling back to all available vendors: {vendors_list}"
                )
            else:
                vendors_list = requested_matches
        
        vendor_info = {"vendors": vendors_list}
        products_list_for_families = json.loads(products_json) if products_json and products_json != "[]" else []
        valid_model_families = []
        for p in products_list_for_families:
            fam = p.get('model_family', '')
            if fam and fam not in valid_model_families:
                valid_model_families.append(fam)

        logger.info(f"[DEEP_ANALYSIS] Vendors filtered to: {vendors_list}")
        logger.info(f"[DEEP_ANALYSIS] Found {len(valid_model_families)} unique model families to load PDFs for.")

        if not vendors_list:
            logger.warning("[DEEP_ANALYSIS] No vendors to analyze after filtering")

            # Notify Admin
            _notify_failure("Deep Analysis Agent - Vendor Filtering",
                "No vendors available for analysis after filtering.",
                specified_vendors=specified_vendors)

            return {
                "vendor_analysis": {"vendor_matches": []},
                "overall_ranking": {"ranked_products": []},
                "error": "No vendors available for analysis"
            }

        # Step 3: Load PDFs — use 5-tier L4 datasheet_url when available, else flat documents
        logger.info("[DEEP_ANALYSIS] Step 3: FilteredPDFLoading")
        if preloaded_pdf_content is not None or preloaded_pdf_bytes is not None:
            pdf_content = preloaded_pdf_content or {}
            pdf_bytes = preloaded_pdf_bytes or {}
            logger.info(
                f"[DEEP_ANALYSIS] ⚡ Skipping Azure Blob download — reusing pre-loaded PDFs: "
                f"{len(pdf_content)} text entries, {len(pdf_bytes)} raw byte entries"
            )
        else:
            _emit("Verifying Datasheets", 70)
            # Build vendor→[url] map from 5-tier products (have datasheet_url from L4)
            _tier_vendor_urls: dict[str, list[str]] = {}
            for _p in products_list_for_families:
                _v = _p.get("vendor") or _p.get("vendor_name", "")
                _u = _p.get("datasheet_url", "")
                if _v and _u:
                    _tier_vendor_urls.setdefault(_v, []).append(_u)

            if _tier_vendor_urls:
                logger.info(
                    f"[5TIER_AUDIT][vendor_analysis] STEP3_PDF=5-tier-L4-datasheet_url "
                    f"db=Restructured collection=L4 field=datasheet_url "
                    f"vendors={list(_tier_vendor_urls.keys())} "
                    f"total_urls={sum(len(v) for v in _tier_vendor_urls.values())}"
                )
                pdf_result = load_pdfs_from_urls(_tier_vendor_urls)
                logger.info(
                    f"[5TIER_AUDIT][vendor_analysis] STEP3_PDF result "
                    f"vendors_with_pdfs={pdf_result.get('vendors_with_pdfs', [])} "
                    f"total_loaded={pdf_result.get('total_loaded', 0)} "
                    f"success={pdf_result.get('success')}"
                )
            else:
                logger.warning(
                    f"[5TIER_AUDIT][vendor_analysis] STEP3_PDF=FALLBACK-flat-documents "
                    f"reason=no datasheet_url in L4 products "
                    f"db=product-recommender collection=documents"
                )
                pdf_result = load_pdfs_from_database(
                    product_type=product_type or user_input,
                    filtered_vendors=vendors_list,
                    valid_model_families=valid_model_families
                )
            pdf_content = pdf_result.get("pdf_content", {})
            pdf_bytes = pdf_result.get("pdf_bytes", {})
        logger.info(
            f"[5TIER_AUDIT][vendor_analysis] STEP3_PDF final "
            f"pdf_text_vendors={list(pdf_content.keys())} "
            f"pdf_bytes_vendors={list(pdf_bytes.keys())}"
        )

        # Step 4: Create vendor analysis chain
        logger.info("[DEEP_ANALYSIS] Step 4: ParallelVendorAnalysis")
        # Build vendor prompt from markdown file (used as fallback when Spatial AI is unavailable)
        prompt_content = _load_prompt('vendor_analysis_agent.md')
        vendor_prompt = ChatPromptTemplate.from_template(prompt_content).partial(format_instructions=FORMAT_INSTRUCTIONS)

        # Use safer JSON parser with error handling (already using pro model _llm_pro)
        vendor_chain = vendor_prompt | _llm_pro | _safe_json_parser()

        # Format standards
        standards_str = "\n".join(applicable_standards) if applicable_standards else "No standards"
        specs_str = "\n".join([f"{k}: {v}" for k, v in (standards_specs or {}).items()]) if standards_specs else "No specs"

        logger.info(f"[DEEP_ANALYSIS] Starting parallel vendor analysis for {len(vendors_list)} vendors")
        if GENAI_AVAILABLE and pdf_bytes:
            logger.info("[DEEP_ANALYSIS] 🚀 Spatial AI mode ENABLED — will pass raw PDFs directly to Gemini")
        else:
            logger.info("[DEEP_ANALYSIS] 📝 Text-based mode — using extracted text (Spatial AI not available or no raw PDF bytes)")

        # Run parallel analysis (per-vendor sub_step events are emitted inside)
        analysis_result = _run_parallel_vendor_analysis(
            structured_requirements=structured_requirements or user_input,
            products_json=products_json,
            pdf_content=pdf_content,
            vendor_chain=vendor_chain,
            applicable_standards=standards_str,
            standards_specs=specs_str,
            stream_id=stream_id,
            pdf_bytes=pdf_bytes,  # Pass raw PDF bytes for Spatial AI
            user_id=user_id,
            comparison_spec_keys=comparison_spec_keys
        )

        # SPARSE-CATALOG FALLBACK: zero matches from a catalog of one or two
        # datasheet-less entries (typically just-scraped placeholders for a
        # product type the DB doesn't cover) means "no usable data", not
        # "nothing matches". Retry in knowledge-only mode — products_json="[]"
        # forces the LLM-knowledge branch above, which returns directly, so
        # this recursion is bounded at depth 1.
        if not analysis_result.get("vendor_matches"):
            _catalog_sparse = (
                len(products_list) < _MIN_CATALOG_PRODUCTS
                and not any(p.get("datasheet_url") for p in products_list)
            )
            if _catalog_sparse:
                logger.warning(
                    f"[DEEP_ANALYSIS] 0 matches from sparse catalog "
                    f"({len(products_list)} products, none with datasheet URLs) for "
                    f"{(product_type or user_input[:80])!r} — retrying with knowledge-only fallback"
                )
                return run_vendor_analysis(
                    user_input=user_input,
                    structured_requirements=structured_requirements,
                    search_session_id=search_session_id,
                    specified_vendors=specified_vendors,
                    applicable_standards=applicable_standards,
                    standards_specs=standards_specs,
                    product_type=product_type,
                    stream_id=stream_id,
                    user_id=user_id,
                    products_json="[]",  # force knowledge-only branch
                )

        # Step 5: Final output (Ranking removed, handled by vendor_ranking_agent)
        logger.info("[VENDOR_ANALYSIS] Step 5: Preparing Output")
        # _emit("Preparing Results", 95)  # Moved to search_agent
        overall_ranking = {"ranked_products": []}

        logger.info("[VENDOR_ANALYSIS] Analysis complete successfully")

        # Log agent interaction to MongoDB
        try:
            # user_id comes from caller context
            user_id_str = str(user_id) if user_id else 'anonymous'

            # Build response summary
            vendors_analyzed = len(analysis_result.get('vendor_run_details', []))
            products_found = len(analysis_result.get('vendor_matches', []))
            response_summary = f"Vendor Analysis Complete: {vendors_analyzed} vendors analyzed, {products_found} models matched"

            metadata = {
                "agent_type": "deep_analysis",
                "parent_agent": "search",
                "session_id": search_session_id,
                "product_type": product_type or "unknown",
                "vendors_analyzed": vendors_analyzed,
                "products_found": products_found,
                "specified_vendors": specified_vendors or [],
                "standards_applied": applicable_standards or [],
                "success": True
            }

            log_session_id = search_session_id or f"deep_analysis_{user_id_str}_{datetime.now().strftime('%Y%m%d')}"

            interaction_logger.log_interaction(
                user_id=user_id_str,
                session_id=log_session_id,
                user_input=user_input[:500],  # First 500 chars
                response=response_summary,
                metadata=metadata,
                interaction_type="agent_deep_analysis_search"
            )
        except Exception as log_error:
            logger.warning(f"[DEEP_ANALYSIS] Failed to log interaction: {log_error}")

        return {
            "vendor_analysis": analysis_result,
            "overall_ranking": overall_ranking,
            "session_id": search_session_id,
            "analysis_metadata": {
                "total_vendors_analyzed": len(analysis_result.get('vendor_run_details', [])),
                "total_products_found": len(overall_ranking.get('ranked_products', [])),
                "standards_applied": applicable_standards or [],
                "vendor_filter_note": vendor_filter_note
            }
        }

    except Exception as e:
        logger.exception(f"[DEEP_ANALYSIS] Analysis failed with error: {e}")
        logger.error(f"[DEEP_ANALYSIS] user_input: {user_input}")
        logger.error(f"[DEEP_ANALYSIS] structured_requirements: {structured_requirements}")
        logger.error(f"[DEEP_ANALYSIS] session_id: {search_session_id}")

        # Notify Admin
        _notify_failure("Deep Analysis Agent",
            f"Analysis failed with exception: {str(e)}",
            session_id=search_session_id)

        return {
            "vendor_analysis": {"vendor_matches": [], "error": str(e)},
            "overall_ranking": {"ranked_products": []},
            "error": str(e)
        }


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_vendor_analysis_agent_health():
    """
    Health check for Deep Analysis Agent
    Tests: LLM (flash + pro), MongoDB (vendors, products), Azure Blob, prompt files

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
        # 1. Test LLM connectivity (both flash and pro) - checks API key only, no actual call
        dependencies["llm_flash"] = checker.check_llm_connectivity("deepinfra")
        if dependencies["llm_flash"].status == "unavailable":
            status = "unhealthy"

        dependencies["llm_pro"] = checker.check_llm_connectivity("deepinfra")
        if dependencies["llm_pro"].status == "unavailable":
            status = "unhealthy"

        # 2. Test MongoDB collections
        dependencies["mongodb_vendors"] = checker.check_mongodb_collection("vendors")
        if dependencies["mongodb_vendors"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_products"] = checker.check_mongodb_collection("products")
        if dependencies["mongodb_products"].status == "unavailable":
            status = "unhealthy"

        dependencies["mongodb_standards"] = checker.check_mongodb_collection("standards")
        if dependencies["mongodb_standards"].status == "unavailable":
            status = "unhealthy"

        # 3. Test Azure Blob Storage (non-critical - for PDF loading)
        try:
            from common.infra.azure_blob import azure_blob_manager
            azure_blob_manager.blob_service_client.get_account_information()
            dependencies["azure_blob"] = DependencyStatus("azure_blob", "available")
        except Exception as e:
            dependencies["azure_blob"] = DependencyStatus("azure_blob", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"  # Non-critical - can work without PDFs

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[AGENT_HEALTH] Deep analysis agent health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="deep_analysis_agent",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg
    )
