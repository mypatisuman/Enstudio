"""
Strategy RAG (Retrieval-Augmented Generation)

Provides LLM-based standardization search for vendor strategy documents.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

# Add parent directory to path for absolute imports
_parent_dir = os.path.dirname(os.path.dirname(__file__))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from common.infra.mongodb_config import Collections, get_mongodb_connection
from common.ai.llm import get_flash_llm
from common.infra.repositories.strategy_repository import StrategyRepository
from common.models.strategy import StrategyDocument, StrategyEntry

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

STRATEGY_COLLECTION_NAME = Collections.STRATERGY

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_strategy_collection():
    """Get MongoDB collection for strategy documents."""
    try:
        conn = get_mongodb_connection()
        return conn['collections'][STRATEGY_COLLECTION_NAME]
    except Exception as e:
        logger.error(f"[STRATEGY_RAG] Failed to get collection: {e}")
        return None


def _is_proxy_form_url(url: str) -> bool:
    """True for the frontend image-proxy form ('/api/image_proxy?url=...')
    that generate_sas_url returns in dev mode. That form is a RELATIVE browser
    URL — requests.get() on it raises MissingSchema (verified live 2026-08-04),
    so server-side fetches must unwrap it back to the raw blob URL."""
    return bool(url) and not url.startswith(("http://", "https://")) and "image_proxy" in url


def _unwrap_proxy_url(url: str) -> str:
    """Extract the raw blob URL out of a proxy-form value."""
    from urllib.parse import parse_qs, unquote, urlparse
    try:
        params = parse_qs(urlparse(url).query)
        inner = (params.get("url") or [""])[0]
        return unquote(inner) if inner else url
    except Exception:
        return url


def _fetch_payload_bytes(sas_url: str, timeout: int = 120) -> bytes:
    """Download a payload server-side from either a real SAS URL or a cached
    proxy-form value. Proxy-form values are unwrapped to the raw blob URL and
    fetched through the Azure SDK (proper credentials, no SAS needed)."""
    if _is_proxy_form_url(sas_url):
        raw_url = _unwrap_proxy_url(sas_url)
        logger.info(f"[STRATEGY_RAG] Cached URL is proxy-form; downloading via Azure SDK: {raw_url[:100]}")
        from common.infra.azure_blob import azure_blob_manager
        return azure_blob_manager.download_document_from_url(raw_url)
    import requests
    response = requests.get(sas_url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _load_strategy_entries_from_embeddings_sas_url(sas_url: str, filename: str) -> list[dict[str, Any]] | None:
    """Load previously extracted strategy entries (including embeddings) from a gzip-compressed JSON blob SAS URL.

    Exclusively handles gzip-compressed payloads.
    """
    try:
        import gzip
        import json

        logger.info(f"[STRATEGY_RAG] Downloading embeddings payload from SAS URL: {filename}")
        raw_bytes = _fetch_payload_bytes(sas_url, timeout=120)
        decompressed = gzip.decompress(raw_bytes)

        logger.info(
            f"[STRATEGY_RAG] Decompressed embeddings payload: "
            f"{len(raw_bytes) / (1024*1024):.2f} MB → {len(decompressed) / (1024*1024):.2f} MB"
        )

        payload = json.loads(decompressed.decode('utf-8'))

        data = payload.get('data')
        if not isinstance(data, list):
            logger.warning(f"[STRATEGY_RAG] Embeddings payload missing 'data' array: {filename}")
            return None

        # a payload written with the previous embedding model: re-embed its texts
        from common.ai.embedding_manager import refresh_stale_embeddings
        refresh_stale_embeddings(data)
        return data
    except Exception as e:
        logger.error(f"[STRATEGY_RAG] Failed to load or decompress embeddings payload from SAS URL: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def extract_query_entities_with_llm(query: str) -> dict[str, Any]:
    """
    Use LLM to extract and standardize entities from search query.

    Extracts:
    - Vendor names (and standardizes them)
    - Categories/subcategories (and standardizes them)
    - Strategy keywords (preferred, dual source, etc.)
    - General keywords

    Args:
        query: User search query

    Returns:
        Dict with extracted and standardized entities
    """
    try:
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        llm = get_flash_llm(temperature=0.1)

        prompt = ChatPromptTemplate.from_template("""
You are an expert in industrial instrumentation and procurement strategy analysis.

Extract and standardize the following entities from the search query:

Query: "{query}"

Instructions:
1. **Vendors**: Extract vendor/manufacturer names and standardize them to proper corporate names
   - Examples: "emerson" → "Emerson", "E+H" → "Endress+Hauser", "abb" → "ABB"

2. **Categories**: Extract product categories/types and standardize them
   - Examples: "pressure sensor" → "Pressure Transmitter", "flow meter" → "Flow Meter"

3. **Subcategories**: Extract more specific product types
   - Examples: "differential pressure" → "Differential Pressure Transmitter"

4. **Strategy Keywords**: Extract procurement strategy terms
   - Examples: "preferred", "dual source", "single source", "approved", "restricted"

5. **General Keywords**: Extract other relevant search terms

Return in JSON format:
{{
    "vendors": ["[standardized vendor names]"],
    "categories": ["[standardized category names]"],
    "subcategories": ["[standardized subcategory names]"],
    "strategy_keywords": ["[standardized strategy keywords]"],
    "general_keywords": ["[other relevant keywords]"]
}}

IMPORTANT:
- Return empty arrays if no entities found in that category
- Standardize all names to proper industry conventions
- Be aggressive in extracting - if unsure, include it
""")

        chain = prompt | llm | JsonOutputParser()

        result = chain.invoke({"query": query})

        logger.info(f"[STRATEGY_RAG] Extracted entities from query: {json.dumps(result, indent=2)}")

        return {
            "vendors": result.get("vendors", []),
            "categories": result.get("categories", []),
            "subcategories": result.get("subcategories", []),
            "strategy_keywords": result.get("strategy_keywords", []),
            "general_keywords": result.get("general_keywords", [])
        }

    except Exception as e:
        logger.error(f"[STRATEGY_RAG] LLM entity extraction failed: {e}")
        # Fallback to basic keyword extraction
        import re
        keywords = re.findall(r'\b[a-zA-Z0-9]+\b', query.lower())
        keywords = [kw for kw in keywords if len(kw) > 2]

        return {
            "vendors": [],
            "categories": [],
            "subcategories": [],
            "strategy_keywords": [],
            "general_keywords": keywords
        }


def standardize_with_llm(text: str, entity_type: str) -> str:
    """
    Standardize a single text field using LLM.

    Args:
        text: Text to standardize
        entity_type: Type of entity (vendor, category, subcategory, strategy)

    Returns:
        Standardized text
    """
    try:
        from langchain_core.prompts import ChatPromptTemplate

        llm = get_flash_llm(temperature=0.1)

        prompt_templates = {
            "vendor": "Standardize this vendor name to proper corporate naming: {text}\nReturn only the standardized name.",
            "category": "Standardize this product category to industry terminology: {text}\nReturn only the standardized category.",
            "subcategory": "Standardize this product subcategory to industry terminology: {text}\nReturn only the standardized subcategory.",
            "strategy": "Standardize this procurement strategy term: {text}\nReturn only the standardized term."
        }

        template = prompt_templates.get(entity_type, "Standardize: {text}")
        prompt = ChatPromptTemplate.from_template(template)

        chain = prompt | llm
        result = chain.invoke({"text": text})

        standardized = result.content.strip()
        logger.debug(f"[STRATEGY_RAG] Standardized {entity_type}: '{text}' → '{standardized}'")

        return standardized

    except Exception as e:
        logger.warning(f"[STRATEGY_RAG] LLM standardization failed for '{text}': {e}")
        return text.strip()


def _extract_csv_strategy_from_sas_url(sas_url: str, filename: str) -> list[dict[str, Any]] | None:
    """
    Extract strategy data from CSV file using SAS URL (direct pandas parsing, no LLM).

    Args:
        sas_url: Azure Blob SAS URL with read access
        filename: Original filename for logging

    Returns:
        List of strategy entries, or None if extraction failed
    """
    try:
        import pandas as pd

        logger.info(f"[STRATEGY_RAG] Downloading CSV from SAS URL: {filename}")

        # Download CSV file (SAS URL or unwrapped proxy-form value)
        csv_bytes = _fetch_payload_bytes(sas_url, timeout=30)

        # Parse CSV with pandas
        from io import StringIO
        csv_data = StringIO(csv_bytes.decode("utf-8", errors="replace"))
        df = pd.read_csv(csv_data)

        logger.info(f"[STRATEGY_RAG] Parsed CSV: {len(df)} rows, {len(df.columns)} columns")

        # Expected columns: vendor_name, category, subcategory, strategy, notes
        # Standardize column names (case-insensitive matching)
        df.columns = df.columns.str.strip().str.lower()

        # Map common column name variations
        column_mapping = {
            'vendor': 'vendor_name',
            'vendor name': 'vendor_name',
            'manufacturer': 'vendor_name',
            'supplier': 'vendor_name',
            'product_category': 'category',
            'product category': 'category',
            'product_type': 'category',
            'sub_category': 'subcategory',
            'sub category': 'subcategory',
            'procurement_strategy': 'strategy',
            'procurement strategy': 'strategy',
            'note': 'notes',
            'comment': 'notes',
            'comments': 'notes'
        }

        # Rename columns based on mapping
        df.rename(columns=column_mapping, inplace=True)

        # Extract strategy entries WITH VECTOR EMBEDDINGS (DYNAMIC - ALL COLUMNS)
        logger.info("[STRATEGY_RAG] Computing vector embeddings for ALL columns dynamically...")

        # Import embedding utilities
        from common.ai.embedding_manager import generate_embeddings_batch

        # Get all column names
        all_columns = list(df.columns)

        # Collect texts for each column across all rows
        column_texts = {col: [] for col in all_columns}
        valid_rows = []

        for _idx, row in df.iterrows():
            # Check if row has minimum required data (at least 2 non-empty columns)
            non_empty_count = sum(1 for val in row if pd.notna(val) and str(val).strip())

            if non_empty_count >= 2:  # At least 2 columns with data
                valid_rows.append(row)

                # Collect text for each column
                for col in all_columns:
                    value = str(row.get(col, '')).strip() if pd.notna(row.get(col)) else ""
                    column_texts[col].append(value)

        if not valid_rows:
            logger.warning("[STRATEGY_RAG] No valid entries found in CSV")
            return None

        # Generate embeddings for ALL columns in batch (much faster than one-by-one)
        logger.info(f"[STRATEGY_RAG] Generating embeddings for {len(valid_rows)} rows x {len(all_columns)} columns...")

        column_embeddings = {}
        for col in all_columns:
            # Generate embeddings for this column
            embeddings = generate_embeddings_batch(column_texts[col], show_progress=False)
            column_embeddings[col] = embeddings
            logger.info(f"[STRATEGY_RAG] ✓ Generated embeddings for column: '{col}'")

        # Create entries with ALL column values + ALL column embeddings
        strategy_entries = []
        for i, row in enumerate(valid_rows):
            entry = {}

            # Store ALL column values as top-level fields
            for col in all_columns:
                # Sanitize column name for MongoDB (replace spaces/special chars with underscore)
                safe_col_name = col.replace(' ', '_').replace('-', '_').replace('.', '_')
                entry[safe_col_name] = column_texts[col][i]

            # Store ALL column embeddings (pattern: column_name_embedding)
            for col in all_columns:
                safe_col_name = col.replace(' ', '_').replace('-', '_').replace('.', '_')
                embedding_key = f"{safe_col_name}_embedding"

                # Only store embedding if the text is not empty
                if column_texts[col][i]:
                    entry[embedding_key] = column_embeddings[col][i]
                else:
                    entry[embedding_key] = None

            strategy_entries.append(entry)

        logger.info(f"[STRATEGY_RAG] ✓ Extracted {len(strategy_entries)} entries with vector embeddings for ALL columns")
        return strategy_entries

    except Exception as e:
        logger.error(f"[STRATEGY_RAG] Failed to extract CSV from SAS URL: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


# ============================================================================
# SEARCH FUNCTIONS
# ============================================================================

def search_vendors_rag(
    user_id: str,
    query: str = "",
    top_k: int = 10,
    min_score: float = 0.3,
    category_filter: str | None = None,
    # NEW: Accept structured input fields
    input_vendor: str | None = None,
    input_category: str | None = None,
    input_subcategory: str | None = None,
    input_product_type: str | None = None,
    input_strategy: str | None = None
) -> list[dict[str, Any]]:
    """
    Search for vendors using LLM-based standardization matching in strategy collection.

    Supports two modes:
    1. Free-text query: Extracts entities from query string
    2. Structured input: Uses provided structured fields (input_category, input_vendor, etc.)

    The function standardizes BOTH input and database fields using LLM, then matches
    based on standardized versions. Returns EXACT database names (not standardized).

    Args:
        user_id: User ID to search within
        query: Free-text search query (used if structured inputs not provided)
        top_k: Number of results to return
        min_score: Minimum score threshold (default: 0.3)
        category_filter: Optional category to filter results
        input_vendor: Vendor name from instruments/accessories list
        input_category: Category from instruments/accessories list
        input_subcategory: Subcategory from instruments/accessories list
        input_product_type: Product type from instruments/accessories list
        input_strategy: Strategy keyword from instruments/accessories list

    Returns:
        List of matched vendors with exact database names
    """
    try:
        # Determine if using structured input or query extraction
        use_structured_input = any([
            input_vendor, input_category, input_subcategory,
            input_product_type, input_strategy
        ])

        detected_vendors = []
        detected_categories = []
        detected_subcategories = []
        detected_strategy_keywords = []
        general_keywords = []

        if use_structured_input:
            logger.info(
                f"[STRATEGY_RAG] Searching with STRUCTURED INPUT:\n"
                f"  Vendor: {input_vendor}\n"
                f"  Category: {input_category}\n"
                f"  Subcategory: {input_subcategory}\n"
                f"  Product Type: {input_product_type}\n"
                f"  Strategy: {input_strategy}"
            )
        else:
            logger.info(f"[STRATEGY_RAG] Searching with FREE-TEXT QUERY: '{query}'" +
                       (f" (category filter: {category_filter})" if category_filter else ""))

        # ===== STEP 1: COMPUTE EMBEDDINGS FOR INPUT QUERY (NO LLM STANDARDIZATION!) =====
        from common.ai.embedding_manager import generate_embedding

        # Generate embeddings for input fields
        input_vendor_embedding = None
        input_category_embedding = None
        input_subcategory_embedding = None
        input_strategy_embedding = None

        if use_structured_input:
            # STRUCTURED INPUT MODE: Generate embeddings for provided fields
            logger.info("[STRATEGY_RAG] Generating embeddings for structured input...")

            if input_vendor:
                input_vendor_embedding = generate_embedding(input_vendor)
                logger.info(f"[STRATEGY_RAG] Input vendor embedding generated for: '{input_vendor}'")

            # Generate embeddings for category
            if input_category:
                input_category_embedding = generate_embedding(input_category)
                detected_categories.append(input_category)  # Store original value
                logger.info(f"[STRATEGY_RAG] Input category embedding generated for: '{input_category}'")

            # Generate embeddings for subcategory
            if input_subcategory:
                input_subcategory_embedding = generate_embedding(input_subcategory)
                detected_subcategories.append(input_subcategory)  # Store original value
                logger.info(f"[STRATEGY_RAG] Input subcategory embedding generated for: '{input_subcategory}'")

            # Generate embeddings for product_type (treated as category)
            if input_product_type:
                # We can also compute category embedding from product_type if category is not provided
                if not input_category_embedding:
                    input_category_embedding = generate_embedding(input_product_type)
                detected_categories.append(input_product_type)  # Store original value
                logger.info(f"[STRATEGY_RAG] Input product_type embedding generated for: '{input_product_type}'")

            # Generate embeddings for strategy
            if input_strategy:
                input_strategy_embedding = generate_embedding(input_strategy)
                detected_strategy_keywords.append(input_strategy)  # Store original value
                logger.info(f"[STRATEGY_RAG] Input strategy embedding generated for: '{input_strategy}'")

        else:
            # FREE-TEXT QUERY MODE: Extract entities from query
            query_entities = extract_query_entities_with_llm(query)

            detected_vendors = query_entities.get("vendors", [])
            detected_categories = query_entities.get("categories", [])
            detected_subcategories = query_entities.get("subcategories", [])
            detected_strategy_keywords = query_entities.get("strategy_keywords", [])
            general_keywords = query_entities.get("general_keywords", [])

        logger.info("[STRATEGY_RAG] Standardized INPUT entities:")
        logger.info(f"  Vendors: {detected_vendors}")
        logger.info(f"  Categories: {detected_categories}")
        logger.info(f"  Subcategories: {detected_subcategories}")
        logger.info(f"  Strategy Keywords: {detected_strategy_keywords}")
        if not use_structured_input:
            logger.info(f"  General Keywords: {general_keywords}")

        # ===== STEP 2: HYDRATE CATALOG VIA REPOSITORY =====
        catalog = StrategyRepository.get_catalog_for_user(user_id)

        if not catalog.documents:
            logger.info(f"[STRATEGY_RAG] No strategy documents found for user {user_id}")
            return []

        # ===== STEP 2.5: CHECK FOR DOCUMENTS WITHOUT DATA AND EXTRACT FROM BLOB URL =====
        # Fallback: If document has blob URL but no extracted data, use SAS URL to access and extract
        for doc in catalog.documents:
            if doc.storage is None:
                continue

            # Preferred path: load extracted embeddings payload from embeddingsBlobUrl
            embeddings_blob_url = doc.storage.embeddingsBlobUrl
            if (not doc.data or len(doc.data) == 0) and embeddings_blob_url:
                logger.info(f"[STRATEGY_RAG] Document '{doc.filename}' has no inline data, loading from embeddings blob")

                try:
                    from common.infra.blob_sas import generate_sas_url

                    cached_sas = doc.storage.cachedEmbeddingsSasUrl
                    cached_sas_expiry = doc.storage.embeddingsSasUrlExpiry

                    sas_url = None

                    if cached_sas and cached_sas_expiry:
                        try:
                            expiry_dt = datetime.fromisoformat(cached_sas_expiry)
                            if datetime.now(UTC) < expiry_dt:
                                sas_url = cached_sas
                                logger.info(f"[STRATEGY_RAG] ✓ Reusing cached embeddings SAS URL (expires: {cached_sas_expiry})")
                            else:
                                logger.info("[STRATEGY_RAG] Cached embeddings SAS URL expired, generating new one")
                        except Exception as parse_error:
                            logger.warning(f"[STRATEGY_RAG] Failed to parse embeddings SAS expiry: {parse_error}")

                    if not sas_url:
                        sas_url = generate_sas_url(embeddings_blob_url, expiry_hours=24)
                        # Proxy-form values are browser-only — usable this request
                        # (unwrapped by _fetch_payload_bytes) but never cached.
                        if sas_url and not _is_proxy_form_url(sas_url):
                            sas_expiry = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
                            StrategyRepository.update_metadata(doc.id, {
                                'storage.cachedEmbeddingsSasUrl': sas_url,
                                'storage.embeddingsSasUrlExpiry': sas_expiry
                            })
                            logger.info(f"[STRATEGY_RAG] ✓ Generated and cached embeddings SAS URL (expires: {sas_expiry})")

                    if not sas_url:
                        logger.error(f"[STRATEGY_RAG] Failed to get embeddings SAS URL for {doc.filename}")
                        continue

                    extracted_data = _load_strategy_entries_from_embeddings_sas_url(sas_url, doc.filename)
                    if extracted_data:
                        doc.data = [StrategyEntry.model_validate(e) for e in extracted_data]
                        logger.info(f"[STRATEGY_RAG] ✓ Loaded {len(extracted_data)} entries from embeddings blob")
                    else:
                        logger.warning(f"[STRATEGY_RAG] Failed to load embeddings payload for {doc.filename}")

                except Exception as e:
                    logger.error(f"[STRATEGY_RAG] Error loading embeddings payload: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

                continue

            # Check if document has no data but has blob URL
            if (not doc.data or len(doc.data) == 0) and doc.storage.blobUrl:
                blob_url = doc.storage.blobUrl
                logger.info(f"[STRATEGY_RAG] Document '{doc.filename}' has no data, extracting from blob URL: {blob_url}")

                try:
                    # Check if cached SAS URL exists and is still valid
                    from common.infra.blob_sas import generate_sas_url
                    cached_sas = doc.storage.cachedSasUrl
                    cached_sas_expiry = doc.storage.sasUrlExpiry

                    sas_url = None

                    # Reuse cached SAS URL if valid (not expired)
                    if cached_sas and cached_sas_expiry:
                        try:
                            expiry_dt = datetime.fromisoformat(cached_sas_expiry)
                            if datetime.now(UTC) < expiry_dt:
                                sas_url = cached_sas
                                logger.info(f"[STRATEGY_RAG] ✓ Reusing cached SAS URL (expires: {cached_sas_expiry})")
                            else:
                                logger.info("[STRATEGY_RAG] Cached SAS URL expired, generating new one")
                        except Exception as parse_error:
                            logger.warning(f"[STRATEGY_RAG] Failed to parse SAS expiry: {parse_error}")

                    # Generate new SAS URL if no valid cached one
                    if not sas_url:
                        sas_url = generate_sas_url(blob_url, expiry_hours=24)  # 24 hour expiry

                        # Proxy-form values are browser-only — usable this request
                        # (unwrapped by _fetch_payload_bytes) but never cached.
                        if sas_url and not _is_proxy_form_url(sas_url):
                            # Cache the SAS URL in MongoDB for reuse
                            sas_expiry = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
                            StrategyRepository.update_metadata(doc.id, {
                                'storage.cachedSasUrl': sas_url,
                                'storage.sasUrlExpiry': sas_expiry
                            })
                            logger.info(f"[STRATEGY_RAG] ✓ Generated and cached new SAS URL (expires: {sas_expiry})")

                    if not sas_url:
                        logger.error(f"[STRATEGY_RAG] Failed to get SAS URL for {doc.filename}")
                        continue

                    # Only CSV files are supported for strategy documents
                    file_ext = doc.filename.lower().split('.')[-1] if '.' in doc.filename else ''

                    if file_ext != 'csv':
                        logger.warning(f"[STRATEGY_RAG] Only CSV files are supported for strategy documents, got: {file_ext}")
                        continue

                    # CSV files: Direct pandas parsing, no LLM extraction needed
                    logger.info(f"[STRATEGY_RAG] CSV file detected, using direct parsing: {doc.filename}")
                    extracted_data = _extract_csv_strategy_from_sas_url(sas_url, doc.filename)

                    if extracted_data:
                        # Do NOT write extracted_data back into MongoDB (may exceed BSON limit).
                        # Keep it in-memory for this request only and update only lightweight metadata.
                        StrategyRepository.update_metadata(doc.id, {
                            'entry_count': len(extracted_data),
                            'extracted_at': datetime.now(UTC).isoformat(),
                            'extraction_method': 'csv_direct_parse'
                        })
                        doc.entry_count = len(extracted_data)
                        doc.data = [StrategyEntry.model_validate(e) for e in extracted_data]
                        logger.info(f"[STRATEGY_RAG] ✓ Extracted {len(extracted_data)} entries from CSV via direct parsing")
                    else:
                        logger.warning(f"[STRATEGY_RAG] Failed to parse CSV file: {doc.filename}")

                except Exception as e:
                    logger.error(f"[STRATEGY_RAG] Error extracting from blob URL: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

        # ===== STEP 3: PERFORM SEARCH VIA STRATEGY CATALOG =====
        results = catalog.search_entries(
            input_vendor_embedding=input_vendor_embedding,
            input_category_embedding=input_category_embedding,
            input_subcategory_embedding=input_subcategory_embedding,
            input_strategy_embedding=input_strategy_embedding,
            detected_vendors=detected_vendors,
            detected_categories=detected_categories,
            detected_subcategories=detected_subcategories,
            detected_strategy_keywords=detected_strategy_keywords,
            general_keywords=general_keywords,
            category_filter=category_filter,
            min_score=min_score,
            top_k=top_k,
            use_structured_input=use_structured_input
        )

        logger.info(f"[STRATEGY_RAG] Found {len(results)} matching vendors, returning top {top_k}")
        return results

    except Exception as e:
        logger.error(f"[STRATEGY_RAG] Search failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def delete_user_strategy_data(user_id: str) -> dict[str, Any]:
    """
    Delete all strategy data for a user.
    """
    try:
        strategy_collection = get_strategy_collection()
        if strategy_collection is None:
            return {"success": False, "error": "Collection not available"}

        # Handle both string and int user_ids
        try:
            user_id_int = int(user_id)
            query = {"$or": [{"user_id": user_id}, {"user_id": user_id_int}]}
        except:
            query = {"user_id": user_id}

        result = strategy_collection.delete_many(query)

        logger.info(f"[STRATEGY_RAG] Deleted {result.deleted_count} strategy documents for user {user_id}")

        return {
            "success": True,
            "deleted_count": result.deleted_count
        }

    except Exception as e:
        logger.error(f"[STRATEGY_RAG] Deletion failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_strategy_rag_health():
    """
    Health check for Strategy RAG Module
    Tests: LLM, MongoDB (strategy), Embedding manager

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
        # 1. Test LLM connectivity
        dependencies["llm_flash"] = checker.check_llm_connectivity("google")
        if dependencies["llm_flash"].status == "unavailable":
            status = "unhealthy"

        # 2. Test MongoDB strategy collection
        dependencies["mongodb_strategy"] = checker.check_mongodb_collection("stratergy")
        if dependencies["mongodb_strategy"].status == "unavailable":
            status = "unhealthy"

        # 3. Test embedding manager (for semantic search)
        try:
            from common.ai.embedding_manager import EMBEDDING_DIM, generate_embedding
            test_embedding = generate_embedding("test")
            if test_embedding and len(test_embedding) == EMBEDDING_DIM:
                dependencies["embedding_manager"] = DependencyStatus("embedding_manager", "available")
            else:
                dependencies["embedding_manager"] = DependencyStatus("embedding_manager", "unavailable", "Invalid embedding")
                if status == "healthy":
                    status = "degraded"
        except Exception as e:
            dependencies["embedding_manager"] = DependencyStatus("embedding_manager", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"

        # 4. Test MongoDB connection
        try:
            from common.infra.mongodb_config import get_mongodb_connection
            conn = get_mongodb_connection()
            if conn:
                dependencies["mongodb_connection"] = DependencyStatus("mongodb_connection", "available")
            else:
                dependencies["mongodb_connection"] = DependencyStatus("mongodb_connection", "unavailable", "Connection failed")
                status = "unhealthy"
        except Exception as e:
            dependencies["mongodb_connection"] = DependencyStatus("mongodb_connection", "unavailable", str(e))
            status = "unhealthy"

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[RAG_HEALTH] Strategy RAG health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="strategy_rag",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg
    )
