"""PDF Schema Indexer — schema-level auto-indexing (self-healing search).

When a user searches for a product type that has no requirements schema in the
5-tier hierarchy, this service:
  1. records the miss in `missing_product_types` (audit queue),
  2. finds a datasheet PDF — first in the `documents` collection / Azure Blob,
     else harvested from the web via SerpAPI (and saved back to blob + documents
     with source "pdf_schema_indexer" so future searches reuse it),
  3. LLM-extracts a 3-tier requirements schema (+ units) from the PDF text,
     falling back to LLM-only generation when no usable PDF text exists,
  4. persists the schema into the SAME hierarchy collection the shared schema
     getter reads (`catalog_hierarchy` via ProductHierarchyRepository), re-reads
     it to confirm, and marks the tracking record `indexed` / `failed`.

Triggered from `MongoDBFileManager.get_schema_from_mongodb` after all existing
lookup cascades miss. Best-effort by design: every failure degrades to the
normal "schema not found" behavior and must never break the user's search.
"""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

from common.ai.llm import get_flash_llm
from common.infra.mongodb_utils import mongodb_file_manager
from common.infra.repositories.missing_product_type_repository import (
    MissingProductTypeRepository,
    STATUS_FAILED,
    STATUS_INDEXED,
)
from domain.search.services.advanced_specs_service import METADATA_BLOCKLIST
from domain.search.services.category_scraper import (
    _parse_llm_json,
    download_pdf,
    extract_text_from_pdf_bytes,
    search_pdf_catalogs,
)

logger = logging.getLogger(__name__)

# Text cap fed to the LLM (extract_text_from_pdf_bytes already caps at 50 pages).
_MAX_SCHEMA_TEXT_CHARS = 80_000
_PDF_FILE_TYPES = {"$in": ["application/pdf", "pdf"]}

# L1 nodes require an L0 parent — auto-indexed types are anchored under this
# stable synthetic category (idempotent upsert; carries no parameters, so it
# contributes nothing to the band cascade).
_AUTO_INDEX_CATEGORY = "Auto Indexed"


def _tiers_have_content(schema: dict[str, Any] | None) -> bool:
    return bool(schema) and bool(
        schema.get("mandatoryRequirements")
        or schema.get("optionalRequirements")
        or schema.get("latestRequirements")
    )


def _per_word_regex_and(field: str, product_type: str) -> dict[str, Any]:
    """Multi-word types: AND of per-word case-insensitive regexes on `field`
    (every word re.escape'd); single word: one escaped regex."""
    words = [w for w in str(product_type).split() if w.strip()]
    if len(words) > 1:
        return {"$and": [{field: {"$regex": re.escape(w), "$options": "i"}} for w in words]}
    return {field: {"$regex": re.escape(product_type.strip()), "$options": "i"}}


def _find_pdf_in_documents(product_type: str) -> tuple[bytes | None, str | None]:
    """Locate an existing datasheet PDF for the product type in the documents
    collection and download its bytes from blob storage.

    Returns (pdf_bytes, source_description) or (None, None).
    """
    try:
        documents = mongodb_file_manager.db["documents"]

        query = {"file_type": _PDF_FILE_TYPES, "blob_url": {"$ne": None},
                 **_per_word_regex_and("product_type", product_type)}
        doc = documents.find_one(query)

        if not doc:
            # Fallback: match the product type against filename / PDF title.
            name_conditions = [
                _per_word_regex_and("filename", product_type),
                _per_word_regex_and("pdf_title", product_type),
            ]
            doc = documents.find_one({
                "file_type": _PDF_FILE_TYPES,
                "blob_url": {"$ne": None},
                "$or": name_conditions,
            })

        if not doc:
            return None, None

        from common.infra.azure_blob import azure_blob_manager
        pdf_bytes = azure_blob_manager.download_document_from_url(
            doc["blob_url"], fallback_url=doc.get("source_url"))
        if not pdf_bytes:
            return None, None
        source = f"documents:{doc.get('filename', doc.get('blob_url'))}"
        logger.info(f"[PDF_SCHEMA_INDEXER] Using existing PDF for '{product_type}': {source}")
        return pdf_bytes, source
    except Exception as e:
        logger.warning(f"[PDF_SCHEMA_INDEXER] Existing-PDF lookup failed for '{product_type}': {e}")
        return None, None


def _harvest_pdf_from_web(product_type: str) -> tuple[bytes | None, str | None]:
    """Web-search a brochure/datasheet PDF, download it, and save it to blob +
    documents collection (source "pdf_schema_indexer") for future searches.

    Returns (pdf_bytes, source_url) or (None, None).
    """
    candidate_limit = max(2, int(os.getenv("SCRAPER_PDF_CANDIDATES", "8")))
    for pdf_info in search_pdf_catalogs(product_type, limit=candidate_limit):
        url = pdf_info.get("url", "")
        pdf_bytes = download_pdf(url)
        if not pdf_bytes:
            continue

        clean_pt = re.sub(r"[^\w\s-]", "", product_type).strip().replace(" ", "_") or "product"
        filename = f"{clean_pt}_datasheet_{datetime.now(UTC).strftime('%Y%m%d')}.pdf"
        try:
            doc_id = mongodb_file_manager.upload_document_to_blob(pdf_bytes, {
                "product_type": product_type,
                "vendor_name": "Unknown",
                "collection_type": "documents",
                "file_type": "application/pdf",
                "filename": filename,
                "source_url": url,
                "pdf_title": pdf_info.get("title", ""),
                "source": "pdf_schema_indexer",
            })
            logger.info(f"[PDF_SCHEMA_INDEXER] Saved harvested PDF for '{product_type}' (doc id: {doc_id})")
        except Exception as upload_err:
            # Non-fatal — the in-memory bytes are enough for this request.
            logger.error(f"[PDF_SCHEMA_INDEXER] Failed to persist harvested PDF: {upload_err}")

        return pdf_bytes, url
    return None, None


def _sanitize_tier(raw: Any, cap: int) -> dict[str, None]:
    """Clean one requirements tier: Title Case parameter names, null values,
    metadata fields (tag/PO/serial/project/vendor/cost...) dropped."""
    out: dict[str, None] = {}
    if isinstance(raw, list):
        raw = {str(k): None for k in raw}
    if not isinstance(raw, dict):
        return out
    for key in raw:
        name = str(key).strip()
        if not name or name.lower() in METADATA_BLOCKLIST:
            continue
        if name.islower():
            name = name.title()
        out[name] = None
        if len(out) >= cap:
            break
    return out


def _sanitize_schema(raw: dict[str, Any]) -> dict[str, Any] | None:
    mandatory = _sanitize_tier(raw.get("mandatoryRequirements"), cap=10)
    optional = _sanitize_tier(raw.get("optionalRequirements"), cap=10)
    latest = _sanitize_tier(raw.get("latestRequirements"), cap=8)
    units = raw.get("units") if isinstance(raw.get("units"), dict) else {}
    if not mandatory:
        return None
    return {
        "mandatoryRequirements": mandatory,
        "optionalRequirements": optional,
        "latestRequirements": latest,
        "units": {str(k).strip(): str(v).strip() for k, v in units.items() if k and v},
    }


_SCHEMA_JSON_CONTRACT = """
Your output must be a single, valid JSON block with this structure:
{{
  "mandatoryRequirements": {{"Parameter Name": null, ...}},
  "optionalRequirements": {{"Parameter Name": null, ...}},
  "latestRequirements": {{"Parameter Name": null, ...}},
  "units": {{"Parameter Name": "unit", ...}}
}}

Rules:
- mandatoryRequirements: the 5-10 most essential operating/selection parameters
  (e.g. process ranges, ratings, materials, connection, power, accuracy).
- optionalRequirements: 5-10 additional commonly specified parameters.
- latestRequirements: 4-8 advanced/modern differentiating capabilities
  (e.g. diagnostics, digital protocols, condition monitoring).
- Parameter names in Title Case; every requirement value must be null.
- "units" maps parameter names to their typical engineering unit (omit unitless ones).
- EXCLUDE document/order metadata fields entirely: tag number, service description,
  P&ID / line / item number, purchase order, requisition, project name or number,
  document number, revision, date, manufacturer, vendor, model number, serial
  number, quantity, cost, remarks.

Return ONLY the valid JSON block, no prose outside it.
"""


def _extract_schema_from_text(product_type: str, pdf_text: str) -> dict[str, Any] | None:
    """LLM-extract the 3-tier requirements schema from datasheet text."""
    llm = get_flash_llm(temperature=0.1)
    prompt = f"""
You are an expert instrumentation/equipment engineer. From the following
manufacturer datasheet/brochure text for the product type '{product_type}',
derive the REQUIREMENTS SCHEMA a buyer would fill in when specifying one.

Datasheet Text:
\"\"\"
{pdf_text}
\"\"\"
{_SCHEMA_JSON_CONTRACT}
"""
    try:
        resp = llm.invoke(prompt)
        resp_text = resp.content if hasattr(resp, "content") else str(resp)
        return _sanitize_schema(_parse_llm_json(resp_text))
    except Exception as e:
        logger.error(f"[PDF_SCHEMA_INDEXER] LLM schema extraction failed for '{product_type}': {e}")
        return None


def _generate_schema_llm_only(product_type: str) -> dict[str, Any] | None:
    """LLM-only fallback when no PDF (or no extractable text) is available."""
    llm = get_flash_llm(temperature=0.2)
    prompt = f"""
You are an expert instrumentation/equipment engineer. Using your domain
knowledge of '{product_type}' products, produce the REQUIREMENTS SCHEMA a
buyer would fill in when specifying one.
{_SCHEMA_JSON_CONTRACT}
"""
    try:
        resp = llm.invoke(prompt)
        resp_text = resp.content if hasattr(resp, "content") else str(resp)
        return _sanitize_schema(_parse_llm_json(resp_text))
    except Exception as e:
        logger.error(f"[PDF_SCHEMA_INDEXER] LLM-only schema generation failed for '{product_type}': {e}")
        return None


def index_and_persist_pdf_schema(product_type: str, user_query: str | None = None) -> dict[str, Any] | None:
    """Auto-index a missing product type's requirements schema.

    Returns the schema in the shared getter's shape
    ({mandatoryRequirements, optionalRequirements, latestRequirements}) so the
    current request can proceed, or None when indexing was skipped/impossible.
    """
    if not product_type or not str(product_type).strip():
        return None
    product_type = str(product_type).strip()

    # Circuit breaker: a recently failed type is not retried inside the cooldown.
    if MissingProductTypeRepository.is_in_failed_cooldown(product_type):
        logger.info(
            f"[AUTO_INDEX] SKIPPED (schema level) for '{product_type}' — "
            f"last indexing attempt failed, 24h cooldown active"
        )
        return None

    from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository

    lock = MissingProductTypeRepository.get_indexing_lock(product_type)
    with lock:
        # Double-check after acquiring: a concurrent request may have just
        # indexed this type (or just failed it).
        try:
            existing = ProductHierarchyRepository.resolve_parameters_schema_by_name(product_type)
            if _tiers_have_content(existing):
                logger.info(f"[PDF_SCHEMA_INDEXER] '{product_type}' was indexed concurrently — reusing")
                return existing
        except Exception as e:
            logger.warning(f"[PDF_SCHEMA_INDEXER] Concurrent-index re-check failed: {e}")
        if MissingProductTypeRepository.is_in_failed_cooldown(product_type):
            logger.info(
                f"[AUTO_INDEX] SKIPPED (schema level) for '{product_type}' — "
                f"a concurrent attempt just failed, 24h cooldown active"
            )
            return None

        logger.info(f"[PDF_SCHEMA_INDEXER] Auto-indexing schema for missing product type: '{product_type}'")
        MissingProductTypeRepository.record_missing_product_type(
            product_type,
            reason="schema_not_found_in_hierarchy",
            user_query=user_query,
            details={"has_schema": False},
        )

        try:
            # 2. Find a datasheet PDF: documents collection first, then the web.
            pdf_bytes, pdf_source = _find_pdf_in_documents(product_type)
            if not pdf_bytes:
                pdf_bytes, pdf_source = _harvest_pdf_from_web(product_type)

            # 3. Extract the schema from PDF text; 4. LLM-only fallback.
            schema = None
            if pdf_bytes:
                pdf_text = extract_text_from_pdf_bytes(pdf_bytes)[:_MAX_SCHEMA_TEXT_CHARS]
                if pdf_text.strip():
                    schema = _extract_schema_from_text(product_type, pdf_text)
                else:
                    logger.warning(f"[PDF_SCHEMA_INDEXER] PDF for '{product_type}' had no extractable text")
            if not schema:
                logger.info(f"[PDF_SCHEMA_INDEXER] Falling back to LLM-only schema generation for '{product_type}'")
                schema = _generate_schema_llm_only(product_type)
            if not schema:
                raise ValueError(f"could not derive a requirements schema for '{product_type}'")

            in_memory = {
                "mandatoryRequirements": schema["mandatoryRequirements"],
                "optionalRequirements": schema.get("optionalRequirements", {}),
                "latestRequirements": schema.get("latestRequirements", {}),
            }

            # 5. Persist into the SAME hierarchy collection the schema getter
            # reads (catalog_hierarchy + L1 view), then confirm by re-reading.
            try:
                parent_uid = ProductHierarchyRepository.upsert_node(
                    "L0",
                    _AUTO_INDEX_CATEGORY,
                    metadata={"source": "pdf_schema_indexer"},
                )
                ProductHierarchyRepository.upsert_node(
                    "L1",
                    product_type,
                    parent_id=parent_uid,
                    category=_AUTO_INDEX_CATEGORY,
                    specifications={
                        "parameters": dict(in_memory),
                        "units": schema.get("units", {}),
                    },
                    node_type="equipment",
                    metadata={
                        "source": "pdf_schema_indexer",
                        "auto_indexed_at": datetime.now(UTC).isoformat(),
                        "source_pdf": pdf_source,
                    },
                )
                confirmed = ProductHierarchyRepository.resolve_parameters_schema_by_name(product_type)
                if not _tiers_have_content(confirmed):
                    raise RuntimeError("persisted schema could not be read back from the hierarchy")

                MissingProductTypeRepository.mark_product_type_status(product_type, STATUS_INDEXED)
                logger.info(
                    f"[PDF_SCHEMA_INDEXER] Indexed '{product_type}': "
                    f"{len(confirmed.get('mandatoryRequirements', {}))} mandatory / "
                    f"{len(confirmed.get('optionalRequirements', {}))} optional / "
                    f"{len(confirmed.get('latestRequirements', {}))} latest"
                )
                return confirmed
            except Exception as persist_err:
                # Persist/confirm failed — mark failed, but still hand the
                # in-memory schema to the current request.
                logger.error(f"[PDF_SCHEMA_INDEXER] Persist failed for '{product_type}': {persist_err}")
                MissingProductTypeRepository.mark_product_type_status(
                    product_type, STATUS_FAILED, f"persist: {persist_err}")
                return in_memory

        except Exception as e:
            logger.error(f"[PDF_SCHEMA_INDEXER] Auto-indexing failed for '{product_type}': {e}")
            MissingProductTypeRepository.mark_product_type_status(product_type, STATUS_FAILED, str(e))
            return None
