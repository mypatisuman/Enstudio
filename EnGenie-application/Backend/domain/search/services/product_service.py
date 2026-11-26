import json
from common.helpers.notifications import notify_failure as _notify_failure
import logging
import io
import re
from typing import Any

from common.infra.azure_blob import azure_blob_manager
from common.infra.mongodb_utils import mongodb_file_manager
from common.infra.mongodb_config import get_mongodb_connection

logger = logging.getLogger(__name__)


# ============================================================================
# VENDOR DB SERVICES
# ============================================================================

def get_available_vendors() -> list[str]:
    """Get all available vendor names from MongoDB."""
    try:
        from common.infra.mongodb_utils import get_available_vendors_from_mongodb
        return get_available_vendors_from_mongodb()
    except Exception as e:
        logger.warning(f"[PRODUCT_SERVICE] Error getting available vendors: {e}")
        return []


def get_vendors_for_product(product_type: str) -> list[str]:
    """Get vendor names for a specific product type from MongoDB."""
    try:
        from common.infra.mongodb_utils import get_vendors_for_product_type
        return get_vendors_for_product_type(product_type)
    except Exception as e:
        logger.warning(f"[PRODUCT_SERVICE] Error getting vendors for '{product_type}': {e}")
        return []


def get_schema_for_product(product_type: str) -> dict[str, Any] | None:
    """Get the requirements schema for a product type from MongoDB."""
    try:
        from common.infra.mongodb_utils import get_schema_from_mongodb
        return get_schema_from_mongodb(product_type)
    except Exception as e:
        logger.warning(f"[PRODUCT_SERVICE] Schema fetch failed for '{product_type}': {e}")
        return None


def _get_mongodb_connection():
    """Get MongoDB connection."""
    try:
        return get_mongodb_connection()
    except Exception as e:
        logger.error(f"[PRODUCT_SERVICE] MongoDB connection failed: {e}")
        return None

def _split_product_type(product_type: str) -> list[str]:
    """Split a product type string into individual keyword terms for MongoDB AND matching."""
    if not product_type:
        logger.error("[PRODUCT_SERVICE] No product_type provided to _split_product_type")
        return []
    stop_words = {"a", "an", "the", "for", "with", "and", "or", "of", "to", "in", "on", "by"}
    words = product_type.lower().strip().split()
    terms = [w for w in words if len(w) > 2 and w not in stop_words]
    return terms if terms else [product_type]

def _load_products_from_mongodb_direct(product_type: str | list[str]) -> str:
    """
    Load products from MongoDB matching the given product type.

    Accepts either a raw product type string (e.g. 'Coriolis Flow Meter')
    or a pre-split list of terms for backward compatibility.

    Args:
        product_type: Product type string or list of keyword terms

    Returns:
        JSON string of products
    """
    if isinstance(product_type, str):
        search_categories = _split_product_type(product_type)
    else:
        search_categories = product_type

    try:
        conn = _get_mongodb_connection()
        if not conn:
            logger.error("[PRODUCT_SERVICE] MongoDB connection failed")
            return "[]"

        vendors_col = conn['collections'].get('vendors')
        if vendors_col is None:
            logger.error("[PRODUCT_SERVICE] Vendors collection not found")
            return "[]"

        if not search_categories:
            logger.warning("[PRODUCT_SERVICE] No search categories provided")
            return "[]"

        logger.info(f"[PRODUCT_SERVICE] Loading products for categories: {search_categories}")

        # Build query - AND logic: ALL search categories must match
        if len(search_categories) > 1:
            category_conditions = [
                {'product_type': {'$regex': re.escape(cat), '$options': 'i'}}
                for cat in search_categories
            ]
            query = {'$and': category_conditions}
        else:
            query = {'product_type': {'$regex': re.escape(search_categories[0]), '$options': 'i'}}
        logger.debug(f"[PRODUCT_SERVICE] MongoDB query: {query}")

        def _fetch_docs(q):
            result = []
            for doc in vendors_col.find(q):
                try:
                    if 'data' in doc:
                        product_data = doc['data']
                    else:
                        product_data = {k: v for k, v in doc.items() if k not in ['_id']}
                        
                    if isinstance(product_data, list):
                        vendor = doc.get('vendor_name', 'Unknown')
                        prod_type = doc.get('product_type', 'unknown')
                        for item in product_data:
                            if isinstance(item, dict):
                                item.setdefault('vendor', vendor)
                                item.setdefault('product_type', prod_type)
                                result.append(item)
                    else:
                        vendor = doc.get('vendor_name') or product_data.get('vendor', 'Unknown')
                        prod_type = doc.get('product_type') or product_data.get('product_type', 'unknown')
                        product_data.setdefault('vendor', vendor)
                        product_data.setdefault('product_type', prod_type)
                        result.append(product_data)
                except Exception as e:
                    logger.warning(f"[PRODUCT_SERVICE] Failed to process product document: {e}")
            return result

        products = _fetch_docs(query)

        if not products and len(search_categories) > 1:
            logger.warning(f"[PRODUCT_SERVICE] AND query returned 0 products for {search_categories}. Trying tiered fallbacks...")

            if len(search_categories) > 2:
                for i in range(len(search_categories) - 1):
                    pair = search_categories[i:i + 2]
                    pair_query = {'$and': [{'product_type': {'$regex': re.escape(cat), '$options': 'i'}} for cat in pair]}
                    products = _fetch_docs(pair_query)
                    if products:
                        logger.info(f"[PRODUCT_SERVICE] Pair fallback {pair} returned {len(products)} products")
                        break

            if not products:
                or_conditions = [{'product_type': {'$regex': re.escape(cat), '$options': 'i'}} for cat in search_categories]
                fallback_query = {'$or': or_conditions}
                products = _fetch_docs(fallback_query)
                logger.info(f"[PRODUCT_SERVICE] Full OR fallback returned {len(products)} products")

        logger.info(f"[PRODUCT_SERVICE] Loaded {len(products)} products from MongoDB for categories: {search_categories}")
        return json.dumps(products, ensure_ascii=False)

    except Exception as e:
        logger.exception(f"[PRODUCT_SERVICE] Product loading failed: {e}")
        return "[]"

_MAX_PDF_PAGES = 50  # Enforced page limit to prevent memory bloat


def _chunk_page_texts(page_texts: list[str], chunk_char_limit: int) -> list[str]:
    """Group per-page text into character-budgeted chunks, shared by both the
    PyMuPDF and pypdf extraction paths below (identical chunking policy,
    different page-text source)."""
    chunks = []
    current_chunk = []
    current_chunk_len = 0
    for page_num, page_text in enumerate(page_texts):
        if not page_text or not page_text.strip():
            continue
        page_content = f"--- Page {page_num + 1} ---\n{page_text}"
        current_chunk.append(page_content)
        current_chunk_len += len(page_content)
        if current_chunk_len >= chunk_char_limit:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_chunk_len = 0
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks


def _extract_text_from_pdf(pdf_bytes: bytes) -> list[str]:
    """Extract text chunks from PDF bytes using PyMuPDF (fitz) or pypdf fallback and chunk them dynamically."""
    pdf_size = len(pdf_bytes)

    # Determine chunk size in characters based on PDF file size in bytes
    if pdf_size < 1 * 1024 * 1024:      # < 1 MB
        chunk_char_limit = 20000
    elif pdf_size < 5 * 1024 * 1024:    # 1 - 5 MB
        chunk_char_limit = 50000
    elif pdf_size < 15 * 1024 * 1024:   # 5 - 15 MB
        chunk_char_limit = 100000
    else:                               # >= 15 MB
        chunk_char_limit = 200000

    logger.info(f"[PRODUCT_SERVICE] Extracting PDF text with chunk limit: {chunk_char_limit} characters (PDF size: {pdf_size} bytes)")

    import os
    disable_pymupdf = os.getenv("DISABLE_PYMUPDF", "true").lower() == "true"

    # Try PyMuPDF first (if not disabled)
    if not disable_pymupdf:
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            max_pages = min(len(doc), _MAX_PDF_PAGES)
            page_texts = [doc[i].get_text() for i in range(max_pages)]
            doc.close()
            chunks = _chunk_page_texts(page_texts, chunk_char_limit)
            logger.info(f"[PRODUCT_SERVICE] Extracted {len(chunks)} text chunks from PDF via PyMuPDF (limited to {max_pages} pages)")
            return chunks
        except Exception as e:
            logger.warning(f"[PRODUCT_SERVICE] PyMuPDF PDF extraction failed or DLL load failed: {e}. Falling back to pypdf...")
    else:
        logger.info("[PRODUCT_SERVICE] PyMuPDF is disabled via DISABLE_PYMUPDF toggle. Using pypdf directly.")

    # Try pypdf fallback
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        max_pages = min(len(reader.pages), _MAX_PDF_PAGES)
        page_texts = [reader.pages[i].extract_text() for i in range(max_pages)]
        chunks = _chunk_page_texts(page_texts, chunk_char_limit)
        logger.info(f"[PRODUCT_SERVICE] Extracted {len(chunks)} text chunks from PDF via pypdf (limited to {max_pages} pages)")
        return chunks
    except Exception as fallback_err:
        logger.error(f"[PRODUCT_SERVICE] pypdf PDF extraction failed: {fallback_err}")
        return []

def _fuzzy_match_vendor(target_vendor: str, pdf_vendor_keys: list[str], threshold: int = 85) -> str:
    """Fuzzy match a target vendor name against PDF vendor keys."""
    if not target_vendor or not pdf_vendor_keys: return None
    target_lower = target_vendor.lower()
    for pdf_vendor in pdf_vendor_keys:
        if pdf_vendor.lower() == target_lower: return pdf_vendor
    try:
        from fuzzywuzzy import fuzz
        best_match, best_score = None, 0
        for pdf_vendor in pdf_vendor_keys:
            similarity = fuzz.ratio(target_lower, pdf_vendor.lower())
            if similarity >= threshold and similarity > best_score:
                best_match, best_score = pdf_vendor, similarity
        if best_match: logger.info(f"[PRODUCT_SERVICE] Fuzzy matched '{target_vendor}' to '{best_match}'")
        return best_match
    except ImportError:
        for pdf_vendor in pdf_vendor_keys:
            if target_lower in pdf_vendor.lower() or pdf_vendor.lower() in target_lower:
                return pdf_vendor
        return None

def _run_parallel_pdf_downloads(work_items: list, download_fn, max_workers: int = 5, timeout: float = 120.0) -> tuple[dict, dict, list]:
    """Run download_fn over work_items on a thread pool and aggregate results
    grouped by vendor. Shared by load_pdfs_from_urls/load_pdfs_from_database,
    which differ only in how they build work_items and download_fn.

    download_fn(item) -> {"vendor": str, "success": bool, "bytes"?: bytes, "text"?: str}

    Returns (pdf_raw_bytes, pdf_texts, vendors_with_pdfs).
    """
    import concurrent.futures

    pdf_raw_bytes: dict[str, list] = {}
    pdf_texts: dict[str, str] = {}
    vendors_with_pdfs: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(work_items) or 1, max_workers)) as ex:
        futures = [ex.submit(download_fn, item) for item in work_items]
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=timeout):
                result = fut.result()
                if not result.get("success"):
                    continue
                vendor = result["vendor"]
                pdf_raw_bytes.setdefault(vendor, []).append(result["bytes"])
                if result.get("text"):
                    pdf_texts[vendor] = pdf_texts.get(vendor, "") + result["text"]
                if vendor not in vendors_with_pdfs:
                    vendors_with_pdfs.append(vendor)
        except (concurrent.futures.TimeoutError, TimeoutError):
            logger.warning(f"[PRODUCT_SERVICE] Parallel PDF download timed out after {timeout}s")

    return pdf_raw_bytes, pdf_texts, vendors_with_pdfs


def load_pdfs_from_urls(vendor_url_map: dict[str, list[str]]) -> dict[str, Any]:
    """Download and extract PDFs directly from pre-known blob URLs (5-tier L4 path).

    Args:
        vendor_url_map: {vendor_name: [datasheet_url, ...]} — duplicates are deduplicated
                        per-vendor; URLs that are None/empty are skipped.

    Returns same shape as load_pdfs_from_database.
    """
    vendors_without_pdfs: list[str] = []

    if not azure_blob_manager:
        return {"pdf_content": {}, "pdf_bytes": {}, "pdf_content_json": "{}", "success": False,
                "message": "Blob manager not available"}

    # Build flat work list: (vendor, url) — one download per unique url per vendor
    work: list[tuple[str, str]] = []
    for vendor, urls in (vendor_url_map or {}).items():
        seen_urls: set[str] = set()
        for url in (urls or []):
            if url and url not in seen_urls:
                seen_urls.add(url)
                work.append((vendor, url))

    if not work:
        return {"pdf_content": {}, "pdf_bytes": {}, "pdf_content_json": "{}",
                "vendors_with_pdfs": [], "vendors_without_pdfs": list(vendor_url_map or {}),
                "total_loaded": 0, "success": True, "message": "No URLs provided"}

    def _download_one(vendor_url: tuple[str, str]):
        vendor, url = vendor_url
        try:
            raw = azure_blob_manager.download_document_from_url(url)
            if not raw or len(raw) > 25 * 1024 * 1024:
                return {"vendor": vendor, "success": False}
            chunks = _extract_text_from_pdf(raw)
            text = "\n\n".join(c for c in chunks if len(c.strip()) > 20)
            return {"vendor": vendor, "bytes": raw, "text": text, "success": True}
        except Exception as e:
            logger.warning(f"[PRODUCT_SERVICE] load_pdfs_from_urls: failed {url}: {e}")
            return {"vendor": vendor, "success": False}

    pdf_raw_bytes, pdf_texts, vendors_with_pdfs = _run_parallel_pdf_downloads(work, _download_one)

    for vendor in (vendor_url_map or {}):
        if vendor not in vendors_with_pdfs:
            vendors_without_pdfs.append(vendor)

    logger.info(
        f"[PRODUCT_SERVICE] load_pdfs_from_urls: {len(vendors_with_pdfs)} vendors with PDFs, "
        f"{len(vendors_without_pdfs)} without"
    )
    return {
        "pdf_content": pdf_texts,
        "pdf_bytes": pdf_raw_bytes,
        "pdf_content_json": json.dumps(pdf_texts, ensure_ascii=False),
        "vendors_with_pdfs": vendors_with_pdfs,
        "vendors_without_pdfs": vendors_without_pdfs,
        "total_loaded": len(pdf_raw_bytes),
        "success": True,
        "message": f"Loaded PDFs for {len(pdf_raw_bytes)} vendors via direct URL"
    }


def load_pdfs_from_database(product_type: str, filtered_vendors: list[str] = None, valid_model_families: list[str] = None) -> dict[str, Any]:
    """Load PDF content from Azure Blob Storage for filtered vendors."""
    filtered_vendors = filtered_vendors or []
    if not product_type or not product_type.strip():
        logger.warning("[PRODUCT_SERVICE] Empty product type provided for PDF loading")
        return {"pdf_content": {}, "pdf_bytes": {}, "pdf_content_json": "{}", "success": False, "message": "Empty product type"}

    product_type = product_type.strip()
    pdf_texts, pdf_raw_bytes, vendors_with_pdfs, vendors_without_pdfs = {}, {}, [], []

    try:
        if not mongodb_file_manager or not azure_blob_manager:
            return {"pdf_content": {}, "pdf_bytes": {}, "pdf_content_json": "{}", "success": False, "message": "DB/Blob managers not available"}

        database = mongodb_file_manager.conn['database']
        documents_collection = database['documents']

        vendor_pdf_counts = {}
        model_family_pdf_counts = {}

        product_words = [w.strip() for w in product_type.split() if w.strip()]

        if len(product_words) > 1:
            query = {
                'file_type': {'$in': ['application/pdf', 'pdf']},
                '$and': [
                    {'product_type': {'$regex': word, '$options': 'i'}}
                    for word in product_words
                ]
            }
        else:
            query = {
                'file_type': {'$in': ['application/pdf', 'pdf']},
                'product_type': {'$regex': product_type, '$options': 'i'}
            }
            
        if valid_model_families:
            model_or_conditions = []
            for family in valid_model_families:
                if family and isinstance(family, str):
                    escaped_fam = re.escape(family)
                    model_or_conditions.append({'model_family': {'$regex': escaped_fam, '$options': 'i'}})
                    model_or_conditions.append({'filename': {'$regex': escaped_fam, '$options': 'i'}})
            
            if model_or_conditions:
                if '$and' in query:
                    query['$and'].append({'$or': model_or_conditions})
                else:
                    query['$and'] = [{'product_type': {'$regex': product_type, '$options': 'i'}}, {'$or': model_or_conditions}]
                if 'product_type' in query and '$and' in query:
                    del query['product_type']

        logger.info(f"[PRODUCT_SERVICE] PDF query using logic for words {product_words} and {len(valid_model_families or [])} model families")

        try:
            pdf_documents = list(documents_collection.find(query))
            logger.info(f"[PRODUCT_SERVICE] Found {len(pdf_documents)} PDF documents matching '{product_type}'")

            # Phase 1: Filter and prepare the list of PDFs to process
            pdfs_to_process = []
            
            for pdf_doc in pdf_documents:
                vendor = pdf_doc.get('vendor_name', 'Unknown')
                filename = pdf_doc.get('filename', 'unknown.pdf')
                blob_url = pdf_doc.get('blob_url')
                doc_model_family = pdf_doc.get('model_family', '')

                if not blob_url: continue


                
                lower_filename = filename.lower()
                if "manual" in lower_filename or "instruction" in lower_filename or "user_guide" in lower_filename:
                    continue

                matched_vendor = None
                if filtered_vendors:
                    matched_vendor = _fuzzy_match_vendor(vendor, filtered_vendors)
                    if not matched_vendor: continue
                    vendor = matched_vendor

                vendor_pdf_counts[vendor] = vendor_pdf_counts.get(vendor, 0)
                if vendor_pdf_counts[vendor] >= 10:
                    continue

                if vendor not in model_family_pdf_counts:
                    model_family_pdf_counts[vendor] = {}
                
                group_key = "unknown_family"
                if doc_model_family:
                    group_key = doc_model_family.lower().strip()
                elif valid_model_families:
                    for fam in valid_model_families:
                        if fam and fam.lower() in lower_filename:
                            group_key = fam.lower().strip()
                            break
                            
                if group_key != "unknown_family":
                    current_fam_count = model_family_pdf_counts[vendor].get(group_key, 0)
                    if current_fam_count >= 1:
                        continue
                
                model_family_pdf_counts[vendor][group_key] = model_family_pdf_counts[vendor].get(group_key, 0) + 1
                vendor_pdf_counts[vendor] += 1
                
                pdfs_to_process.append({
                    "vendor": vendor,
                    "filename": filename,
                    "blob_url": blob_url,
                    "source_url": pdf_doc.get('source_url')
                })

            # Phase 2 & 3: Download + extract in parallel, aggregated grouped by vendor
            logger.info(f"[PRODUCT_SERVICE] Processing {len(pdfs_to_process)} PDFs in parallel...")

            def process_single_pdf(pdf_info):
                vendor = pdf_info["vendor"]
                blob_url = pdf_info["blob_url"]
                filename = pdf_info["filename"]

                try:
                    pdf_bytes_data = azure_blob_manager.download_document_from_url(
                        blob_url, fallback_url=pdf_info.get("source_url"))
                    if pdf_bytes_data and len(pdf_bytes_data) > 25 * 1024 * 1024:
                        logger.warning(f"[PRODUCT_SERVICE] Skipping PDF {filename} because it is too large ({len(pdf_bytes_data)} bytes)")
                        return {"vendor": vendor, "success": False}

                    text_chunks = _extract_text_from_pdf(pdf_bytes_data)

                    full_text = ""
                    if text_chunks:
                        valid_chunks = [chunk for chunk in text_chunks if len(chunk.strip()) > 20]
                        if valid_chunks:
                            full_text = "\n\n".join(valid_chunks) + "\n\n--- End of Document ---\n\n"

                    return {
                        "vendor": vendor,
                        "bytes": pdf_bytes_data,
                        "text": full_text,
                        "success": True
                    }
                except Exception as e:
                    logger.warning(f"[PRODUCT_SERVICE] Failed to download/extract PDF {filename}: {e}")
                    return {"vendor": vendor, "success": False}

            pdf_raw_bytes, pdf_texts, vendors_with_pdfs = _run_parallel_pdf_downloads(pdfs_to_process, process_single_pdf)

        except Exception as e:
            logger.warning(f"[PRODUCT_SERVICE] Failed to query documents collection for product type '{product_type}': {e}")

        for vendor in filtered_vendors:
            if vendor not in vendors_with_pdfs and not _fuzzy_match_vendor(vendor, vendors_with_pdfs):
                vendors_without_pdfs.append(vendor)

        return {
            "pdf_content": pdf_texts,
            "pdf_bytes": pdf_raw_bytes,
            "pdf_content_json": json.dumps(pdf_texts, ensure_ascii=False),
            "vendors_with_pdfs": vendors_with_pdfs,
            "vendors_without_pdfs": vendors_without_pdfs,
            "total_loaded": len(pdf_raw_bytes),
            "success": True,
            "message": f"Loaded PDF content for {len(pdf_raw_bytes)} vendors (with raw bytes for Spatial AI)"
        }
    except Exception as e:
        logger.exception(f"[PRODUCT_SERVICE] PDF loading failed: {e}")
        _notify_failure("PDF Loading", f"Failed to load PDF documents for product '{product_type}': {str(e)}", product_type=product_type, error=str(e))
        return {"pdf_content": {}, "pdf_bytes": {}, "pdf_content_json": "{}", "success": False, "message": str(e)}
