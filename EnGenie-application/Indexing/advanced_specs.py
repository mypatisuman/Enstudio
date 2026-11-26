"""
Advanced specification generation for the Indexing pipeline.

Workflow per product: cache-check → extract existing → generate (Pro LLM)
                      → verify (Flash LLM) → store in MongoDB.
"""
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
log = logging.getLogger(__name__)

# Bootstrap Backend on sys.path once at import time
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Backend"))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _llm(tier: str = "flash", temperature: float = 0.2):
    """Return a flash or pro LLM instance."""
    from common.ai.llm.manager import get_flash_llm, get_pro_llm
    return (get_pro_llm if tier == "pro" else get_flash_llm)(temperature=temperature)


# ── prompts ───────────────────────────────────────────────────────────────────

_GEN_PROMPT = """\
As an instrumentation expert, generate ALL relevant ADVANCED specification names for:
Product Type: {product_type}

Existing specs (DO NOT duplicate):
{existing_specs}

Rules:
1. SPECIFIC to "{product_type}" only — not generic features.
2. Focus on cutting-edge / Industry 4.0 capabilities.
3. Use vendor-agnostic standardized terminology (Emerson, ABB, Siemens, etc.).
4. Keep names short (2-3 words). No acronyms or parentheses.

Return ONLY a valid JSON array: ["Name 1", "Name 2", ...]"""

_VERIFY_PROMPT = """\
As an instrumentation expert, verify these advanced spec names for "{product_type}":
{specs_list}

Keep ONLY specs that are:
1. Specific to "{product_type}" (not generic)
2. Vendor-agnostic (recognized across all manufacturers)
3. Available in modern {product_type} products (2025-2026)
4. Short (2-3 words max) — shorten if needed

Return ONLY a valid JSON array: ["Verified 1", "Verified 2", ...]"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_json_list(content: str) -> Optional[List[str]]:
    """Extract and parse a JSON list from an LLM response robustly."""
    if not content:
        return None
    match = re.search(r"\[.*\]", content, re.DOTALL)
    raw_json = match.group(0) if match else re.sub(r"^```[a-z]*\n?|```$", "", content.strip()).strip()
    try:
        result = json.loads(raw_json)
        return [s.strip() for s in result if isinstance(s, str) and s.strip()] if isinstance(result, list) else None
    except Exception as e:
        log.warning("[ADVSPEC] JSON parse error: %s", e)
        return None


def _norm(product_type: str) -> str:
    return product_type.lower().replace(" ", "").replace("_", "")


def get_existing_specs_from_schema(parameters: Dict[str, Any]) -> List[str]:
    """Return all unique field names across the three parameter tiers."""
    tiers = ("mandatoryRequirements", "optionalRequirements", "latestRequirements")
    seen: list[str] = []
    for f in (f for t in tiers for f in (parameters.get(t) or {}).keys()):
        if f not in seen:
            seen.append(f)
    return seen


# ── core pipeline ─────────────────────────────────────────────────────────────

def generate_advanced_specs(product_type: str, existing_specs: List[str]) -> Optional[List[str]]:
    """Pro LLM: generate new advanced spec names, excluding existing ones."""
    log.info("[ADVSPEC] Generating for: %s (excluding %d existing)", product_type, len(existing_specs))
    existing_str = "\n".join(f"- {s}" for s in existing_specs) or "None"
    try:
        content = _llm("pro", 0.2).invoke(
            _GEN_PROMPT.format(product_type=product_type, existing_specs=existing_str)
        ).content
        specs = _parse_json_list(content)
        if specs is None:
            return None
        low = {s.lower() for s in existing_specs}
        validated = [s for s in specs if s.lower() not in low]
        log.info("[ADVSPEC] Generated %d new specs for %s", len(validated), product_type)
        return validated
    except Exception as e:
        log.error("[ADVSPEC] generate failed for %s: %s", product_type, e)
        return None


def verify_specifications_with_pro(product_type: str, specs: List[str]) -> Optional[List[str]]:
    """Flash LLM: verify and filter spec names (trust gate before storing)."""
    log.info("[ADVSPEC] Verifying %d specs for %s", len(specs), product_type)
    specs_list = "\n".join(f"{i+1}. {s}" for i, s in enumerate(specs))
    try:
        content = _llm("flash", 0.3).invoke(
            _VERIFY_PROMPT.format(product_type=product_type, specs_list=specs_list)
        ).content
        result = _parse_json_list(content)
        if result is None:
            return None
        log.info("[ADVSPEC] Verified %d/%d specs for %s", len(result), len(specs), product_type)
        return result
    except Exception as e:
        log.error("[ADVSPEC] verification failed for %s: %s", product_type, e)
        return None


def store_advanced_specs_in_mongodb(product_type: str, specs: List[str], db) -> bool:
    """Upsert verified specs into db.advanced_specifications."""
    doc = {
        "product_type": product_type,
        "normalized_product_type": _norm(product_type),
        "unique_specifications": [{"name": s} for s in specs],
        "specification_count": len(specs),
        "updated_at": datetime.utcnow(),
        "source": "llm_generated",
        "verified": True,
    }
    try:
        r = db["advanced_specifications"].update_one(
            {"normalized_product_type": _norm(product_type)}, {"$set": doc}, upsert=True
        )
        log.info("[ADVSPEC] Stored %d specs for %s (upserted=%s)", len(specs), product_type, bool(r.upserted_id))
        return True
    except Exception as e:
        log.error("[ADVSPEC] store failed for %s: %s", product_type, e)
        return False


def process_single_product(product_type: str, parameters: Dict[str, Any], db) -> bool:
    """
    Full workflow: cache-check → extract → generate → verify → store.
    Returns True on success, False if skipped or failed.
    """
    if db["advanced_specifications"].find_one({"normalized_product_type": _norm(product_type)}):
        log.info("[ADVSPEC] Already cached for %s — skipping", product_type)
        return False

    existing  = get_existing_specs_from_schema(parameters)
    specs     = generate_advanced_specs(product_type, existing)
    if not specs:
        return False

    verified  = verify_specifications_with_pro(product_type, specs)
    if not verified:
        log.warning("[ADVSPEC] Verification returned nothing for %s", product_type)
        return False

    return store_advanced_specs_in_mongodb(product_type, verified, db)


def run_for_all_nodes(catalog_col, db, limit: int = 0) -> Dict[str, str]:
    """Batch-process every L1/L2 node. Returns {product_type: 'ok'|'skipped'}."""
    nodes = list(catalog_col.find({"level": {"$in": ["L1", "L2"]}}, {"name": 1, "parameters": 1}))
    log.info("[ADVSPEC] %d L1/L2 nodes to process", len(nodes))
    results: Dict[str, str] = {}
    for n, node in enumerate(nodes):
        name, params = node.get("name", ""), node.get("parameters") or {}
        if name and params:
            results[name] = "ok" if process_single_product(name, params, db) else "skipped"
        if limit and n + 1 >= limit:
            break
    log.info("[ADVSPEC] Done: %d/%d ok", sum(v == "ok" for v in results.values()), len(results))
    return results
