import os
import re
import sys
import io
import json
import logging
import requests
from datetime import datetime, UTC
from typing import Any, Dict, List, Tuple

from common.infra.mongodb_config import get_mongodb_connection
from common.infra.mongodb_utils import mongodb_file_manager
from common.ai.llm import get_flash_llm

logger = logging.getLogger(__name__)

def check_category_presence(product_type: str) -> Tuple[bool, List[str], str]:
    """
    Check whether a product type's requirements schema exists, and pull its
    field names to guide vendor-spec extraction.

    SINGLE SOURCE OF TRUTH: the PRIMARY check reads the same 5-tier hierarchy
    collection (catalog_hierarchy via ProductHierarchyRepository) that the PDF
    schema indexer writes to — so freshly auto-indexed types are immediately
    eligible for vendor-data scraping. The legacy `specs` collection is kept
    only as a fallback for pre-5-tier data.

    Returns:
        (is_present, schema_field_names, canonical_product_type)
    """
    # 1. PRIMARY — 5-tier catalog_hierarchy (what the schema getter/indexer use)
    try:
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
        resolved = ProductHierarchyRepository.resolve_parameters_schema_by_name(product_type)
        if resolved and (resolved.get("mandatoryRequirements") or resolved.get("optionalRequirements")):
            schema_fields = list(resolved.get("mandatoryRequirements", {}).keys()) + \
                            list(resolved.get("optionalRequirements", {}).keys())
            logger.info(f"[CATEGORY_SCRAPER] Category '{product_type}' found in 5-tier hierarchy "
                        f"({len(schema_fields)} schema fields)")
            return True, schema_fields, product_type
    except Exception as e:
        logger.warning(f"[CATEGORY_SCRAPER] 5-tier category check failed for '{product_type}': {e}")

    # 2. FALLBACK — legacy specs collection
    try:
        conn = get_mongodb_connection()
        specs_col = conn['collections']['specs']

        # Try case-insensitive exact match, then partial match
        schema_doc = specs_col.find_one({"product_type": {"$regex": f"^{re.escape(product_type)}$", "$options": "i"}})
        if not schema_doc:
            schema_doc = specs_col.find_one({"product_type": {"$regex": re.escape(product_type), "$options": "i"}})
        if not schema_doc:
            return False, [], product_type

        canonical_pt = schema_doc.get("product_type", product_type)
        schema_fields: List[str] = []
        data_section = schema_doc.get("data", {})
        for section_name in ["mandatory_requirements", "optional_requirements"]:
            section = data_section.get(section_name, {})
            for subcat, fields in section.items():
                if isinstance(fields, dict):
                    schema_fields.extend(fields.keys())
                elif isinstance(fields, list):
                    schema_fields.extend(fields)
        logger.info(f"[CATEGORY_SCRAPER] Category '{canonical_pt}' found in legacy specs collection")
        return True, schema_fields, canonical_pt
    except Exception as e:
        logger.error(f"[CATEGORY_SCRAPER] Error checking category presence: {e}")
        return False, [], product_type


def assess_vendor_data_presence(product_type: str) -> Dict[str, Any]:
    """
    Evaluate whether a product type has vendor product data anywhere.

    Gate logic (shared by the detect_product_type trigger and the scraper's
    post-lock double-check): count vendor products in the primary 5-tier
    hierarchy; only when that is zero, count the flat vendors collection
    (case-insensitive exact match) and matching datasheet PDFs in documents.
    Scraping is warranted when the flat count is 0 OR no PDFs exist.

    Returns:
        {should_scrape, hierarchy_count, flat_vendor_count, pdf_count, reason}
    """
    result = {"should_scrape": False, "hierarchy_count": 0,
              "flat_vendor_count": None, "pdf_count": None, "reason": ""}

    # 1. Primary 5-tier hierarchy
    try:
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
        tier_products = ProductHierarchyRepository.get_vendor_products_by_name(product_type)
        result["hierarchy_count"] = len(tier_products) if tier_products else 0
    except Exception as tier_err:
        logger.warning(f"[CATEGORY_SCRAPER] 5-tier product check failed for '{product_type}': {tier_err}")

    if result["hierarchy_count"] > 0:
        return result

    # 2. Flat vendors collection (case-insensitive exact match, escaped)
    flat_count = 0
    try:
        conn = get_mongodb_connection()
        vendors_col = conn['collections']['vendors']
        flat_count = vendors_col.count_documents(
            {"product_type": {"$regex": f"^{re.escape(product_type)}$", "$options": "i"}})
    except Exception as flat_err:
        logger.warning(f"[CATEGORY_SCRAPER] Flat vendors count failed for '{product_type}': {flat_err}")
    result["flat_vendor_count"] = flat_count

    # 3. Datasheet PDFs in the documents collection
    pdf_count = 0
    try:
        documents = mongodb_file_manager.db["documents"]
        words = [w for w in str(product_type).split() if w.strip()]
        pdf_query: Dict[str, Any] = {"file_type": {"$in": ["application/pdf", "pdf"]}}
        if len(words) > 1:
            pdf_query["$and"] = [{"product_type": {"$regex": re.escape(w), "$options": "i"}} for w in words]
        else:
            pdf_query["product_type"] = {"$regex": re.escape(product_type.strip()), "$options": "i"}
        pdf_count = documents.count_documents(pdf_query)
    except Exception as pdf_err:
        logger.warning(f"[CATEGORY_SCRAPER] Documents PDF count failed for '{product_type}': {pdf_err}")
    result["pdf_count"] = pdf_count

    if flat_count == 0 or pdf_count == 0:
        result["should_scrape"] = True
        result["reason"] = (f"vendor_data_missing (hierarchy_products=0, "
                            f"flat_vendor_products={flat_count}, datasheet_pdfs={pdf_count})")
    return result

def search_pdf_catalogs(product_type: str, limit: int = 2) -> List[Dict[str, Any]]:
    """
    Search Google for catalog/brochure PDF URLs of the product type using SerpAPI.
    """
    serpapi_key = os.getenv("SERPAPI_KEY")
    if not serpapi_key:
        logger.error("[CATEGORY_SCRAPER] SERPAPI_KEY is not configured in environment")
        return []
        
    search_query = f"{product_type} brochure datasheet catalog filetype:pdf"
    logger.info(f"[CATEGORY_SCRAPER] Searching SerpAPI for: '{search_query}'")
    
    try:
        from serpapi import GoogleSearch
        search = GoogleSearch({
            "q": search_query,
            "engine": "google",
            "api_key": serpapi_key,
            "num": 10
        })
        results = search.get_dict()
        organic_results = results.get("organic_results", [])
        
        pdf_links = []
        for res in organic_results:
            link = res.get("link", "")
            title = res.get("title", "")
            snippet = res.get("snippet", "")
            
            # Check if link looks like a PDF link
            if link.lower().endswith(".pdf") or "pdf" in link.lower():
                pdf_links.append({
                    "url": link,
                    "title": title,
                    "snippet": snippet
                })
                if len(pdf_links) >= limit:
                    break
                    
        logger.info(f"[CATEGORY_SCRAPER] Found {len(pdf_links)} PDF catalog links")
        return pdf_links
    except Exception as e:
        logger.error(f"[CATEGORY_SCRAPER] SerpAPI search failed: {e}")
        return []

def download_pdf(url: str, timeout: int = 20) -> bytes | None:
    """Download PDF file bytes from a URL."""
    try:
        logger.info(f"[CATEGORY_SCRAPER] Downloading PDF from: {url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        
        # Verify content type
        content_type = resp.headers.get("content-type", "").lower()
        if "application/pdf" not in content_type and not url.lower().endswith(".pdf"):
            logger.warning(f"[CATEGORY_SCRAPER] Response content-type '{content_type}' is not PDF.")
            
        return resp.content
    except Exception as e:
        logger.error(f"[CATEGORY_SCRAPER] Failed to download PDF from {url}: {e}")
        return None

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using PyMuPDF (fitz) with fallback to pypdf."""
    import os
    disable_pymupdf = os.getenv("DISABLE_PYMUPDF", "true").lower() == "true"

    # Try PyMuPDF first (if not disabled)
    if not disable_pymupdf:
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            text_pages = []
            max_pages = min(len(doc), 50)
            for page_num in range(max_pages):
                page_text = doc[page_num].get_text()
                if page_text.strip():
                    text_pages.append(f"--- Page {page_num + 1} ---\n{page_text}")
            doc.close()
            logger.info(f"[CATEGORY_SCRAPER] Extracted PDF text via PyMuPDF (limited to {max_pages} pages)")
            return "\n\n".join(text_pages)
        except Exception as e:
            logger.warning(f"[CATEGORY_SCRAPER] PyMuPDF PDF extraction failed or DLL load failed: {e}. Falling back to pypdf...")
    else:
        logger.info("[CATEGORY_SCRAPER] PyMuPDF is disabled via DISABLE_PYMUPDF toggle. Using pypdf directly.")

    # Try pypdf fallback (pure Python, extremely robust)
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text_pages = []
        max_pages = min(len(reader.pages), 50)
        for page_num in range(max_pages):
            page = reader.pages[page_num]
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_pages.append(f"--- Page {page_num + 1} ---\n{page_text}")
        logger.info(f"[CATEGORY_SCRAPER] Extracted PDF text via pypdf fallback (limited to {max_pages} pages)")
        return "\n\n".join(text_pages)
    except Exception as fallback_err:
        logger.error(f"[CATEGORY_SCRAPER] pypdf fallback extraction also failed: {fallback_err}")
        return ""

def _close_open_brackets(text: str) -> str | None:
    """Terminate a dangling string, drop a trailing half-written key/comma,
    and close every unclosed brace/bracket. Returns None when the text is
    malformed beyond simple truncation (mismatched closers)."""
    stack: List[str] = []
    in_str = False
    escaped = False
    for ch in text:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return None
            stack.pop()
    if in_str:
        text += '"'
    text = re.sub(r"[,\s]+$", "", text)
    # A key with no value yet ('"flow_rate":' or a bare '"flow') can't be closed — drop it.
    text = re.sub(r',?\s*"[^"\\]*"?\s*:?\s*$', "", text)
    return text + "".join(reversed(stack))


def _repair_truncated_json(text: str) -> Dict[str, Any]:
    """Best-effort recovery of LLM JSON cut off mid-output (hit the output
    token cap — seen live as 'Unterminated string' on large catalog chunks).
    Closes open brackets, and if that still doesn't parse, chops back to the
    previous structural boundary and retries, so the models extracted before
    the cutoff are kept instead of losing the whole chunk."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in LLM output")
    text = text[start:]
    for _ in range(50):
        candidate = _close_open_brackets(text)
        if candidate:
            try:
                return json.loads(candidate)
            except Exception:
                pass
        cut = max(text.rfind("},"), text.rfind("],"), text.rstrip().rfind("}"))
        if cut <= 0:
            break
        text = text[:cut + 1]
    raise ValueError("unable to repair truncated JSON")


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Clean and parse JSON output from LLM."""
    cleaned = raw.strip()
    for prefix in ("```json", "```"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except Exception as e:
        logger.warning(f"[CATEGORY_SCRAPER] JSON parsing failed: {e}. Trying simple regex extraction...")
        # Fallback regex search for JSON block
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        # Last resort: repair truncated output so partial extractions survive.
        try:
            repaired = _repair_truncated_json(cleaned)
            logger.warning("[CATEGORY_SCRAPER] Recovered truncated LLM JSON via bracket repair")
            return repaired
        except Exception:
            pass
        raise

def parse_catalog_chunk(product_type: str, schema_fields: List[str], chunk_text: str) -> Dict[str, Any]:
    """Use Gemini LLM to parse a chunk of catalog text and extract vendor, models, and specs."""
    llm = get_flash_llm(temperature=0.1)
    
    prompt = f"""
You are an expert engineering assistant. Analyze the following manufacturer catalog text for the product type '{product_type}' and extract the structured product data.

Target specifications schema fields to extract (match these key names in the 'specifications' dictionary of each model as closely as possible):
{json.dumps(schema_fields, indent=2)}

Manufacturer Catalog Text Chunk:
\"\"\"
{chunk_text}
\"\"\"

Extract the manufacturer/vendor name, the primary model family or series described, a brief description, and all individual models/product numbers found in the text along with their specifications.
Only extract models that have technical specifications in this text.

Your output must be a single, valid JSON block with the following structure:
{{
  "vendor_name": "Name of Manufacturer/Vendor (e.g. Viking Pump, Siemens, Wika)",
  "model_family": "Primary Model Family or Series (e.g. Universal Series, Mark 3, SIMOTICS GP)",
  "description": "Brief summary of the products described (1-2 sentences)",
  "models": [
    {{
      "model_name": "Exact Model Number or Name (e.g. Universal 124A, SIMOTICS GP 1LE1001-1DB2)",
      "specifications": {{
        "field_name_from_schema": "extracted value with unit if applicable (e.g. '5 m3/h', 'IP55', '3-phase AC', 'Zone 1 Ex d')"
      }}
    }}
  ]
}}

Make sure keys inside the model's 'specifications' exactly match the provided schema fields (e.g. pump_type, flow_rate_m3h, wetted_materials, seal_type, head_m, etc. as listed in the schema fields). Keep values clean and concise.

Return ONLY the valid JSON block. Do not write any markdown prose outside the JSON block.
"""
    try:
        resp = llm.invoke(prompt)
        # Handle langchain message objects vs strings
        resp_text = resp.content if hasattr(resp, "content") else str(resp)
        return _parse_llm_json(resp_text)
    except Exception as e:
        logger.error(f"[CATEGORY_SCRAPER] LLM parsing failed for chunk: {e}")
        return {}

def scrape_and_ingest_category_data(product_type: str, max_pdfs: int = 2) -> Dict[str, Any]:
    """
    Check database category, scrape catalogs from web, parse in chunks,
    upload PDFs, and dump structured data into vendors collection.

    Best-effort self-healing: guarded by the missing_product_types circuit
    breaker (a recently failed type is not retried inside the cooldown) and a
    per-type lock so concurrent searches don't run duplicate scrape pipelines.
    """
    from common.infra.repositories.missing_product_type_repository import (
        MissingProductTypeRepository, STATUS_FAILED, STATUS_INDEXED)

    logger.info(f"[CATEGORY_SCRAPER] Initiating scrape and ingestion for: '{product_type}'")

    # Circuit breaker: skip re-scraping a type that failed indexing recently.
    if MissingProductTypeRepository.is_in_failed_cooldown(product_type):
        return {"success": False,
                "message": f"Category '{product_type}' failed indexing recently — inside cooldown, skipping"}

    lock = MissingProductTypeRepository.get_indexing_lock(product_type)
    with lock:
        # Double-check after acquiring: a concurrent request may have just
        # ingested vendor data for this type while we waited on the lock.
        presence = assess_vendor_data_presence(product_type)
        if not presence["should_scrape"]:
            logger.info(f"[CATEGORY_SCRAPER] Vendor data for '{product_type}' appeared while waiting "
                        f"for the indexing lock — skipping duplicate scrape ({presence})")
            return {"success": True, "message": "Vendor data already present — scrape not needed",
                    "total_models_inserted": 0}
        if MissingProductTypeRepository.is_in_failed_cooldown(product_type):
            return {"success": False,
                    "message": f"Category '{product_type}' failed indexing recently — inside cooldown, skipping"}
        return _scrape_and_ingest_locked(product_type, max_pdfs,
                                         MissingProductTypeRepository, STATUS_FAILED, STATUS_INDEXED)


def _scrape_and_ingest_locked(product_type: str, max_pdfs: int,
                              tracking_repo, status_failed: str, status_indexed: str) -> Dict[str, Any]:
    """Body of the scrape pipeline; caller holds the per-type indexing lock."""
    # 1. Verify the category exists — same hierarchy collection the PDF schema
    # indexer writes to (legacy specs as fallback) — and pull its schema fields.
    is_present, schema_fields, canonical_pt = check_category_presence(product_type)
    if not is_present:
        msg = f"Category '{product_type}' has no schema in the 5-tier hierarchy or legacy specs"
        logger.error(f"[CATEGORY_SCRAPER] {msg}")
        tracking_repo.mark_product_type_status(product_type, status_failed, msg)
        return {"success": False, "message": msg}

    logger.info(f"[CATEGORY_SCRAPER] Found canonical category: '{canonical_pt}'")
    logger.info(f"[CATEGORY_SCRAPER] Schema fields for '{canonical_pt}': {schema_fields}")

    # 2. Search for PDF catalogs. Fetch MORE candidate links than max_pdfs and
    # iterate until max_pdfs downloads SUCCEED — external sites 403/timeout
    # regularly (verified live: parker.com bot-blocking halved the harvest when
    # only the first 2 links were considered).
    candidate_limit = max(max_pdfs, int(os.getenv("SCRAPER_PDF_CANDIDATES", "8")))
    pdf_links = search_pdf_catalogs(canonical_pt, limit=candidate_limit)
    if not pdf_links:
        msg = "No PDF catalog links found online via search"
        tracking_repo.mark_product_type_status(product_type, status_failed, msg)
        return {"success": False, "message": msg}

    conn = get_mongodb_connection()
    vendors_col = conn['collections']['vendors']

    successful_downloads = 0
    total_models_inserted = 0

    for pdf_info in pdf_links:
        if successful_downloads >= max_pdfs:
            break
        url = pdf_info["url"]
        title = pdf_info["title"]

        pdf_bytes = download_pdf(url)
        if not pdf_bytes:
            continue

        successful_downloads += 1
        
        # 3. Extract text from PDF
        pdf_text = extract_text_from_pdf_bytes(pdf_bytes)
        if not pdf_text.strip():
            logger.warning(f"[CATEGORY_SCRAPER] PDF contains no extractable text: {url}")
            continue
            
        # 4. Parse text in chunks (to support large PDFs). 60K chars default:
        # 100K-char chunks produced JSON answers past the model's output cap,
        # truncating mid-string (seen live as 'Unterminated string' parse
        # failures). Tunable via SCRAPER_PARSE_CHUNK_CHARS.
        chunk_size = max(10000, int(os.getenv("SCRAPER_PARSE_CHUNK_CHARS", "60000")))
        chunks = [pdf_text[i:i + chunk_size] for i in range(0, len(pdf_text), chunk_size)]
        logger.info(f"[CATEGORY_SCRAPER] PDF has length {len(pdf_text)} characters. Processing in {len(chunks)} chunks.")
        
        extracted_results = []
        for idx, chunk in enumerate(chunks):
            # Cooldown pause to prevent rate limits
            if idx > 0:
                import time
                time.sleep(2.0)
            logger.info(f"[CATEGORY_SCRAPER] Parsing chunk {idx+1}/{len(chunks)} for PDF: {title}")
            chunk_result = parse_catalog_chunk(canonical_pt, schema_fields, chunk)
            if chunk_result and chunk_result.get("models"):
                extracted_results.append(chunk_result)
                
        if not extracted_results:
            logger.warning(f"[CATEGORY_SCRAPER] Failed to extract any models from PDF: {title}")
            continue
            
        # Merge results from chunks
        vendor_name = extracted_results[0].get("vendor_name") or "Unknown Vendor"
        model_family = extracted_results[0].get("model_family") or "Unknown Family"
        description = extracted_results[0].get("description") or f"Brochure for {vendor_name} {canonical_pt}"
        
        # Merge and deduplicate models by model_name
        merged_models = {}
        for res in extracted_results:
            for m in res.get("models", []):
                m_name = m.get("model_name")
                if m_name and m_name not in merged_models:
                    merged_models[m_name] = m
                    
        models_list = list(merged_models.values())
        if not models_list:
            logger.warning(f"[CATEGORY_SCRAPER] No models extracted after merging chunks for PDF: {title}")
            continue
            
        # Clean vendor name and title for filename
        clean_vendor = re.sub(r'[^\w\s-]', '', vendor_name).strip()
        filename = f"{clean_vendor.replace(' ', '_')}_catalog_{datetime.now(UTC).strftime('%Y%m%d')}.pdf"
        
        # 5. Upload PDF to Azure Blob Storage and register in documents collection
        metadata = {
            "product_type": canonical_pt,
            "vendor_name": vendor_name,
            "model_family": model_family,
            "collection_type": "documents",
            "file_type": "application/pdf",
            "filename": filename,
            "source_url": url,
            "pdf_title": title,
            "source": "web_scraper"
        }
        
        try:
            doc_id = mongodb_file_manager.upload_document_to_blob(pdf_bytes, metadata)
            logger.info(f"[CATEGORY_SCRAPER] Uploaded PDF catalog. Doc ID in MongoDB: {doc_id}")
        except Exception as upload_err:
            logger.error(f"[CATEGORY_SCRAPER] Uploading PDF failed: {upload_err}")
            # Non-blocking error, continue to save structured data
            
        # 6. Dump structured models to vendors collection
        vendor_doc = {
            "product_type": canonical_pt,
            "vendor_name": vendor_name,
            "vendor": vendor_name,
            "file_type": "json",
            "model_families": [model_family],
            "description": description,
            "metadata": {
                "upload_date": datetime.now(UTC).isoformat(),
                "vendor_name": vendor_name,
                "product_type": canonical_pt,
                "model_family": model_family,
                "file_type": "json",
                "collection_type": "vendors",
                "source": "web_scraper"
            },
            "data": {
                "product_type": canonical_pt.lower(),
                "vendor": vendor_name,
                "models": models_list
            }
        }
        
        # Upsert based on product_type and vendor_name to prevent duplicates
        try:
            result = vendors_col.update_one(
                {"product_type": canonical_pt, "vendor_name": vendor_name},
                {"$set": vendor_doc},
                upsert=True
            )
            total_models_inserted += len(models_list)
            logger.info(f"[CATEGORY_SCRAPER] Ingested structured vendor product document: {vendor_name} ({len(models_list)} models). Matched: {result.matched_count}, Upserted ID: {result.upserted_id}")
        except Exception as db_err:
            logger.error(f"[CATEGORY_SCRAPER] Failed to save vendor models to MongoDB: {db_err}")
            
    if total_models_inserted > 0:
        tracking_repo.mark_product_type_status(product_type, status_indexed)
        message = (f"Successfully scraped and ingested {total_models_inserted} models "
                   f"for '{canonical_pt}' from {successful_downloads} catalogs.")
    else:
        message = (f"Scrape completed without ingesting any models for '{canonical_pt}' "
                   f"({successful_downloads} of {len(pdf_links)} PDFs downloaded)")
        tracking_repo.mark_product_type_status(product_type, status_failed, message)

    return {
        "success": total_models_inserted > 0,
        "product_type": canonical_pt,
        "successful_downloads": successful_downloads,
        "total_models_inserted": total_models_inserted,
        "message": message
    }
