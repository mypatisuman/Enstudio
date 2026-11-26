"""
Advanced specifications generation service.

Generates 4-8 advanced/technical filtering parameters per product type using the
configured LLM (``get_flash_llm`` — Kimi when the server runs on Kimi), and
upserts them into the ``advanced_specifications`` collection. Product types are
discovered from the ``specs`` and ``vendors`` collections; types that already
have advanced specs are skipped.

Used by:
  - the admin endpoint (POST /api/admin/advanced-specs/generate), run in a
    background thread with progress exposed via :func:`get_status`, and
  - the CLI ``indexing/generate_advanced_specifications.py``.
"""
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from common.ai.llm import get_flash_llm
from common.infra.mongodb_config import get_mongodb_connection

logger = logging.getLogger(__name__)

METADATA_BLOCKLIST = {
    "tag number", "service description", "p&id number", "pid number",
    "line number", "vessel number", "line/vessel number", "item number",
    "purchase order", "po number", "requisition number", "project number",
    "project name", "document number", "revision", "date", "sheet",
    "prepared by", "checked by", "approved by", "customer", "contractor",
    "manufacturer", "vendor", "vendor name", "model number", "serial number",
    "quantity", "unit cost", "total cost", "remarks", "notes", "comments",
    "description", "service", "drawing number", "specification number",
    "data sheet number",
}

# In-memory progress for the most recent admin-triggered generation.
_STATUS: dict[str, Any] = {"running": False, "total": 0, "done": 0, "success": 0,
                           "failed": 0, "started_at": None, "finished_at": None, "error": None}
_LOCK = threading.Lock()


def get_status() -> dict[str, Any]:
    """Snapshot of the current/last generation run (for polling)."""
    with _LOCK:
        return dict(_STATUS)


def _clean_json_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def get_candidate_parameters(db, product_type: str) -> list[str]:
    """Collect candidate parameter names from specs + vendor records (capped at 30)."""
    candidates: set[str] = set()
    try:
        spec_doc = db["specs"].find_one({"$or": [
            {"product_type": product_type}, {"metadata.product_type": product_type}]})
        if spec_doc:
            for node in (spec_doc.get("mandatory_requirements") or {}, spec_doc.get("optional_requirements") or {}):
                for fields in node.values():
                    if isinstance(fields, dict):
                        candidates.update(fields.keys())
                    elif isinstance(fields, list):
                        candidates.update(f for f in fields if isinstance(f, str))
    except Exception as e:
        logger.warning("specs lookup failed for %s: %s", product_type, e)

    try:
        for doc in db["vendors"].find({"$or": [
            {"product_type": product_type}, {"metadata.product_type": product_type}]}).limit(3):
            data_list = doc.get("data") or []
            if not isinstance(data_list, list):
                data_list = [data_list]
            for item in data_list:
                if not isinstance(item, dict):
                    continue
                candidates.update(item.keys())
                for model in item.get("sub_models", []):
                    if isinstance(model, dict) and isinstance(model.get("specifications"), dict):
                        candidates.update(model["specifications"].keys())
    except Exception as e:
        logger.warning("vendors lookup failed for %s: %s", product_type, e)

    filtered = []
    for p in candidates:
        pc = str(p).strip()
        if pc.lower() not in METADATA_BLOCKLIST and len(pc) > 2:
            filtered.append(pc.replace("_", " ").strip())
    return sorted(set(filtered))[:30]


def generate_specs_for_type(db, llm, product_type: str, dry_run: bool = False) -> dict[str, Any]:
    """Generate + upsert advanced specs for one product type."""
    try:
        candidates = get_candidate_parameters(db, product_type)
        candidate_str = ", ".join(candidates) if candidates else "No existing parameter context available."
        prompt = f"""You are an engineering domain expert.
Identify 4 to 8 unique and advanced technical specifications (parameters) for the product type: "{product_type}".

These are used for advanced procurement filtering to help engineers select exact product models. They MUST be technical parameters (e.g. "Fugitive Emissions Certified", "Response Time", "Diaphragm Material") and NOT generic metadata fields.

CRITICAL RULES:
1. Do NOT include administrative/metadata fields (tag number, service description, p&id number, line/vessel number, item number, po number, project number/name, document number, revision, date, vendor, model number, serial number, quantity, cost, remarks, notes, description, drawing number, specification number, data sheet number).
2. Each must be a technical attribute of the physical device or software.
3. Keep each name concise and Title Cased (e.g. "Fugitive Emissions Certified").

Candidate parameters from catalog/vendor data for context:
{candidate_str}

Output JSON ONLY in this schema (no markdown, no extra text):
{{"product_type": "{product_type}", "unique_specifications": [{{"name": "Parameter 1"}}, {{"name": "Parameter 2"}}]}}"""

        res = llm.invoke(prompt)
        content = getattr(res, "content", str(res)).strip()
        parsed = json.loads(_clean_json_text(content))

        unique_specs = parsed.get("unique_specifications", [])
        if not isinstance(unique_specs, list):
            raise ValueError("unique_specifications is not a list")

        cleaned = []
        for spec in unique_specs:
            name = spec.get("name") or spec.get("key") or spec.get("field")
            if name and str(name).lower().strip() not in METADATA_BLOCKLIST:
                cleaned.append({"name": str(name).strip()})
        if not cleaned:
            raise ValueError("No valid technical specifications generated")

        normalized = product_type.lower().replace(" ", "").replace("_", "")
        doc = {
            "normalized_product_type": normalized,
            "product_type": product_type,
            "unique_specifications": cleaned,
            "specification_count": len(cleaned),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "source": "llm_generated",
            "verified": True,
        }
        if not dry_run:
            db["advanced_specifications"].update_one(
                {"normalized_product_type": normalized}, {"$set": doc}, upsert=True)
            logger.info("[ADV_SPECS] saved %d specs for %s", len(cleaned), product_type)
        else:
            logger.info("[ADV_SPECS][dry-run] %s -> %s", product_type, [c["name"] for c in cleaned])
        return {"success": True, "product_type": product_type, "specs_count": len(cleaned)}
    except Exception as e:
        logger.error("[ADV_SPECS] failed for %s: %s", product_type, e)
        return {"success": False, "product_type": product_type, "error": str(e)}


def _discover_missing_types(db, single_type: str | None) -> list[str]:
    if single_type:
        return [single_type]
    found: set[str] = set()
    for coll in ("specs", "vendors"):
        for doc in db[coll].find({}, {"product_type": 1, "metadata.product_type": 1}):
            pt = doc.get("product_type") or (doc.get("metadata") or {}).get("product_type")
            if pt:
                found.add(pt)
    present = {d.get("normalized_product_type")
               for d in db["advanced_specifications"].find({}, {"normalized_product_type": 1})}
    return sorted(pt for pt in found if pt.lower().replace(" ", "").replace("_", "") not in present)


def run_generation(product_type: str | None = None, dry_run: bool = False,
                   limit: int | None = None, workers: int = 5) -> dict[str, Any]:
    """Run the generation pipeline synchronously. Returns a summary dict.

    Updates the module-level status so the admin endpoint can poll progress.
    """
    conn = get_mongodb_connection()
    db = conn["database"]
    targets = _discover_missing_types(db, product_type)
    if limit:
        targets = targets[:limit]

    with _LOCK:
        _STATUS.update({"running": True, "total": len(targets), "done": 0, "success": 0,
                        "failed": 0, "started_at": datetime.now(timezone.utc).isoformat(),
                        "finished_at": None, "error": None})

    if not targets:
        with _LOCK:
            _STATUS.update({"running": False, "finished_at": datetime.now(timezone.utc).isoformat()})
        return {"total": 0, "success": 0, "failed": 0, "message": "All product types already have advanced specs."}

    llm = get_flash_llm(temperature=0.1)
    success = failed = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(generate_specs_for_type, db, llm, pt, dry_run): pt for pt in targets}
            for fut in as_completed(futures):
                ok = fut.result().get("success")
                success += ok
                failed += not ok
                with _LOCK:
                    _STATUS.update({"done": success + failed, "success": success, "failed": failed})
    except Exception as e:
        with _LOCK:
            _STATUS.update({"running": False, "error": str(e),
                            "finished_at": datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        with _LOCK:
            _STATUS.update({"running": False, "finished_at": datetime.now(timezone.utc).isoformat()})

    return {"total": len(targets), "success": success, "failed": failed}
