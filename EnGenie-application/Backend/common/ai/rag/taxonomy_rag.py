"""
Taxonomy RAG — Consolidated Single File
========================================
All taxonomy-related functionality lives here:

  1. TaxonomyContextManager       — conversation context + anaphora resolution
  2. generate_short_description() — LLM-based product description generation
  3. TaxonomyRAG                  — file similarity search + spec extraction from MongoDB
  4. SpecificationRetriever       — MongoDB / JSON spec lookup
  5. TaxonomyNormalizationAgent   — alias map + name normalization (batch + context-aware)
  6. TaxonomyIntegrationAdapter   — 3-step pipeline: normalize → enrich → search payload
  7. get_taxonomy_for_category()  — lightweight category + spec-field mapping (live workflows)

Callers:
  - solution/agents/deep_instrument_analysis_agent.py  →  get_taxonomy_for_category
  - search/agents/validation_agent.py               →  get_taxonomy_for_category
"""

import json
import logging
import os
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from common.infra.mongodb_config import Collections, get_mongodb_connection
from common.infra.mongodb_utils import get_schema_from_mongodb, mongodb_retry
from common.ai.llm import get_lite_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache: product types from specs collection
# Avoids a ~4s MongoDB distinct() call on every parallel taxonomy lookup
# Thread-safe with lock to prevent thundering herd on cache expiry
# ---------------------------------------------------------------------------
_product_types_cache: dict = {"types": [], "expires_at": 0.0}
_product_types_cache_lock = threading.Lock()  # P0.4: Prevent thundering herd
_PRODUCT_TYPES_CACHE_TTL = 300  # seconds (5 minutes)

# ---------------------------------------------------------------------------
# Short-lived result cache for get_taxonomy_for_category
# Prevents redundant LLM calls when identical (category, spec_fields) inputs
# arrive concurrently (e.g. duplicate frontend requests or parallel agents).
# ---------------------------------------------------------------------------
_taxonomy_result_cache: dict = {}  # key → {"result": ..., "expires_at": float}
_taxonomy_result_cache_lock = threading.Lock()
_TAXONOMY_RESULT_CACHE_TTL = 60  # seconds (1 minute)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _friendly_name(field: str) -> str:
    """Convert camelCase to 'Title Case With Spaces'.

    Examples:
        measurementRange → Measurement Range
        processPressureRange → Process Pressure Range
        accuracy → Accuracy
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    return spaced.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Section 1 — TaxonomyContextManager
# ---------------------------------------------------------------------------

class TaxonomyContextManager:
    """
    Manages conversation context for Taxonomy Normalization.
    Handles history tracking, anaphora resolution, and context filtering.
    """

    def __init__(self, max_history: int = 5):
        self.history: list[dict[str, str]] = []
        self.max_history = max_history
        self.active_entities: dict[str, list[dict[str, Any]]] = {
            "instruments": [],
            "accessories": []
        }

    def load_history(self, history: list[dict[str, str]]) -> None:
        """Load conversation history (last N turns)."""
        if not history:
            return
        filtered = [
            msg for msg in history
            if msg.get("role") in ("user", "assistant")
        ]
        self.history = filtered[-self.max_history:]

    def set_active_entities(
        self,
        instruments: list[dict[str, Any]],
        accessories: list[dict[str, Any]]
    ) -> None:
        """
        Update the list of currently identified items in the solution.
        These serve as the primary context for resolving references like 'it' or 'the meter'.
        """
        self.active_entities["instruments"] = instruments or []
        self.active_entities["accessories"] = accessories or []

    def resolve_contextual_references(self, user_input: str) -> str:
        """
        Enrich user input by resolving anaphora (pronouns) using active entities.
        Example: 'Change it to 500C' -> 'Change the Pressure Transmitter to 500C'
        """
        lower_input = user_input.lower()

        # 1. Check for specific pronouns/references
        anaphora_triggers = [
            "it", "that", "this",
            "the instrument", "the meter", "the sensor", "the transmitter",
            "the device", "the unit"
        ]

        # 2. Add variable shorthand context triggers
        variable_triggers = {
            "temperature": "temperature",
            "temp": "temperature",
            "flow": "flow",
            "pressure": "pressure",
            "level": "level"
        }

        # First, see if they used a generic variable word and we have a specific matching instrument active
        for var, var_type in variable_triggers.items():
            if re.search(r'\b' + re.escape(var) + r'\b', lower_input):
                for inst in reversed(self.active_entities["instruments"]):
                    canonical = (inst.get("canonical_name") or inst.get("name") or "").lower()
                    if var_type in canonical:
                        mapped_name = inst.get('canonical_name') or inst.get('name')
                        logger.info(f"[TaxonomyContext] Resolved variable '{var}' to active entity: '{mapped_name}'")
                        if lower_input.strip() == var:
                            return mapped_name
                        return f"{user_input} (referring to {mapped_name})"

        # Fallback to standard anaphora
        has_trigger = False
        exact_trigger = False
        for t in anaphora_triggers:
            if re.search(r'\b' + re.escape(t) + r'\b', lower_input):
                has_trigger = True
                if lower_input.strip() == t:
                    exact_trigger = True
                break

        if not has_trigger:
            return user_input

        # Try to find the most recent/relevant entity
        latest_instrument = None
        if self.active_entities["instruments"]:
            latest_instrument = self.active_entities["instruments"][-1]

        if latest_instrument:
            canonical = latest_instrument.get("canonical_name") or latest_instrument.get("name")
            if canonical:
                logger.info(f"[TaxonomyContext] Resolved context: '{latest_instrument.get('name')}' for input '{user_input}'")
                if exact_trigger:
                    return canonical
                return f"{user_input} (referring to {canonical})"

        return user_input

    def filter_relevant_context(self) -> str:
        """
        Summarize history into a string relevant for taxonomy tasks.
        Excludes chatter, focuses on product modifications.
        """
        context_str = ""
        for msg in self.history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if len(content.split()) > 2:
                context_str += f"{role.upper()}: {content}\n"
        return context_str.strip()


# ---------------------------------------------------------------------------
# Section 2 — TaxonomyRAG
# ---------------------------------------------------------------------------

GOOGLE_API_KEY_RAG = os.getenv("GOOGLE_API_KEY", "")

SHORT_DESCRIPTION_PROMPT = """You are a concise industrial product description generator.

Given a product type, category, and optional specifications, generate a **single-sentence** technical
description (max 30 words) that captures the product's primary function and key characteristics.

Product Type: {product_type}
Category: {category}
Key Specifications: {specifications}

Rules:
- Focus on the product's measurement/control purpose
- Include the physical quantity being measured/controlled
- Mention the primary output signal type if known (e.g. 4-20mA, HART)
- Do NOT include vendor names, model numbers, or pricing
- Keep it under 30 words

Return ONLY the description text, no quotes or labels."""


def generate_short_description(
    product_type: str,
    category: str,
    specifications: dict[str, Any] | None = None
) -> str:
    """
    Generate a concise technical description from product_type + category + specs.

    Uses LLM to produce a ~1 sentence description suitable for similarity search.
    Example: "Pressure Transmitter for industrial process pressure measurement,
              range 0-100 bar, 4-20mA output signal"
    """
    if not GOOGLE_API_KEY_RAG:
        # Fallback: simple concatenation
        spec_str = ""
        if specifications:
            top_specs = list(specifications.items())[:5]
            spec_str = ", ".join(f"{k}: {v}" for k, v in top_specs if v)
        desc = f"{product_type} for {category} applications"
        if spec_str:
            desc += f", {spec_str}"
        return desc

    try:
        spec_summary = ""
        if specifications:
            top_specs = list(specifications.items())[:5]
            spec_summary = ", ".join(f"{k}: {v}" for k, v in top_specs if v)

        llm = get_lite_llm(temperature=0.1)
        prompt = ChatPromptTemplate.from_template(SHORT_DESCRIPTION_PROMPT)
        chain = prompt | llm | StrOutputParser()

        description = chain.invoke({
            "product_type": product_type,
            "category": category,
            "specifications": spec_summary or "Not specified"
        }).strip()

        logger.info(f"[TaxonomyRAG] Generated short description for '{product_type}': '{description[:80]}...'")
        return description

    except Exception as e:
        logger.warning(f"[TaxonomyRAG] LLM description generation failed for '{product_type}': {e}")
        desc = f"{product_type} for {category} applications"
        if specifications:
            top_specs = list(specifications.items())[:3]
            spec_str = ", ".join(f"{k}: {v}" for k, v in top_specs if v)
            if spec_str:
                desc += f", {spec_str}"
        return desc


class TaxonomyRAG:
    """
    RAG Service for Taxonomy.

    Provides:
    - generate_short_description: LLM-based product description generation
    - get_top_files_by_similarity: MongoDB text search + SequenceMatcher scoring
    - extract_specifications_from_files: Parse specs from matched vendor product docs
    """

    def __init__(self):
        self.collection_type = "taxonomy"

    def index_taxonomy(self, taxonomy_data: dict[str, Any]) -> None:
        """Reserved for future vector indexing — currently no-op."""
        pass

    def retrieve(self, query: str, top_k: int = 5, item_type: str | None = None) -> list[dict[str, Any]]:
        """
        Reserved for future RAG retrieval — currently delegates to the
        MongoDB-backed `get_top_files_by_similarity`. The active validation
        path uses `get_taxonomy_for_category` (LLM-based) and does NOT depend
        on this method, so the previous WARNING was misleading log noise.
        """
        try:
            return self.get_top_files_by_similarity(query, top_k=top_k)
        except Exception as e:
            logger.debug(f"[TaxonomyRAG] retrieve() fallback failed: {e}")
            return []

    def get_top_files_by_similarity(
        self, query: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        """
        Search MongoDB 'vendors' collection for vendor product documents
        whose product_type + description best match the query string.

        Uses a two-stage approach:
        1. MongoDB regex filter on product_type keywords (coarse)
        2. SequenceMatcher scoring on document description vs query (fine)

        Args:
            query: Enriched search string (product_type + category + description)
            top_k: Number of top matching documents to return

        Returns:
            List of dicts with keys: _id, product_type, vendor_name, score, data
        """
        try:
            conn = get_mongodb_connection()
            vendors_collection = conn['collections']['vendors']

            # Extract keywords from query for coarse filtering
            query_lower = query.lower()
            # Use the first 2-3 meaningful words as keywords for MongoDB regex
            stop_words = {
                "for", "the", "and", "with", "in", "of", "a", "an", "to",
                "is", "are", "on", "at", "by", "from", "or", "as", "that",
                "this", "it", "its", "applications", "industrial", "process",
                "measurement", "measuring", "signal", "output"
            }
            words = [w for w in re.split(r'\s+', query_lower) if w and w not in stop_words and len(w) > 2]
            keywords = words[:3]  # Use top 3 keywords

            if not keywords:
                logger.warning("[TaxonomyRAG] No keywords extracted from query, skipping file search")
                return []

            logger.info(f"[TaxonomyRAG] Searching vendors collection with keywords: {keywords}")

            # Stage 1: Coarse MongoDB regex filter
            regex_conditions = [
                {"product_type": {"$regex": kw, "$options": "i"}}
                for kw in keywords
            ]
            mongo_query = {"$or": regex_conditions}
            candidates = list(vendors_collection.find(mongo_query).limit(50))

            if not candidates:
                logger.info(f"[TaxonomyRAG] No candidates found for keywords: {keywords}")
                return []

            logger.info(f"[TaxonomyRAG] Found {len(candidates)} candidate documents")

            # Stage 2: Score each candidate using SequenceMatcher
            scored = []
            for doc in candidates:
                # Build a comparison string from the document
                doc_product_type = (doc.get("product_type") or "").lower()
                (doc.get("vendor_name") or doc.get("vendor") or "").lower()

                # Try to extract description from nested data
                doc_description = ""
                doc_data = doc.get("data", doc)
                if isinstance(doc_data, dict):
                    doc_description = (doc_data.get("description") or "").lower()
                    # Also try models-level description
                    models = doc_data.get("models", [])
                    if models and isinstance(models, list):
                        first_model = models[0] if models else {}
                        if isinstance(first_model, dict):
                            model_desc = first_model.get("description", "")
                            if model_desc:
                                doc_description = f"{doc_description} {model_desc}".strip().lower()

                doc_text = f"{doc_product_type} {doc_description}".strip()

                if not doc_text:
                    continue

                score = SequenceMatcher(None, query_lower, doc_text).ratio()
                scored.append({
                    "_id": str(doc.get("_id", "")),
                    "product_type": doc.get("product_type", ""),
                    "vendor_name": doc.get("vendor_name") or doc.get("vendor", ""),
                    "score": round(score, 3),
                    "data": doc_data
                })

            # Sort by score descending, return top_k
            scored.sort(key=lambda x: x["score"], reverse=True)
            top_results = scored[:top_k]

            for r in top_results:
                logger.info(
                    f"[TaxonomyRAG] Match: '{r['vendor_name']}' / '{r['product_type']}' "
                    f"(score={r['score']})"
                )

            return top_results

        except Exception as e:
            logger.error(f"[TaxonomyRAG] get_top_files_by_similarity failed: {e}")
            return []

    def extract_specifications_from_files(
        self, product_name: str, files: list[dict[str, Any]]
    ) -> dict:
        """
        Extract and merge ALL technical specifications from matched vendor product documents.

        Parses the nested structure:
            data.models[*].sub_models[*].specifications

        Args:
            product_name: Canonical product name (for logging)
            files: List of vendor product docs returned by get_top_files_by_similarity

        Returns:
            Merged dict of all specification fields across all matched files
        """
        if not files:
            return self._mechanical_fallback(product_name)

        merged_specs: dict[str, Any] = {}
        files_processed = 0

        for file_doc in files:
            try:
                data = file_doc.get("data", file_doc)
                if not isinstance(data, dict):
                    continue

                vendor_name = file_doc.get("vendor_name", "unknown")
                file_product_type = file_doc.get("product_type", "unknown")

                # Extract top-level specs if present
                top_level_specs = data.get("specifications", {})
                if isinstance(top_level_specs, dict):
                    for k, v in top_level_specs.items():
                        if v and k not in merged_specs:
                            merged_specs[k] = v

                # Extract from models → sub_models → specifications
                models = data.get("models", [])
                if not isinstance(models, list):
                    models = []

                for model in models:
                    if not isinstance(model, dict):
                        continue

                    # Model-level specs
                    model_specs = model.get("specifications", {})
                    if isinstance(model_specs, dict):
                        for k, v in model_specs.items():
                            if v and k not in merged_specs:
                                merged_specs[k] = v

                    # Sub-model specs
                    sub_models = model.get("sub_models", [])
                    if not isinstance(sub_models, list):
                        sub_models = []

                    for sub_model in sub_models:
                        if not isinstance(sub_model, dict):
                            continue
                        sub_specs = sub_model.get("specifications", {})
                        if isinstance(sub_specs, dict):
                            for k, v in sub_specs.items():
                                if v and k not in merged_specs:
                                    merged_specs[k] = v

                files_processed += 1
                logger.info(
                    f"[TaxonomyRAG] Extracted specs from '{vendor_name}/{file_product_type}': "
                    f"{len(merged_specs)} total fields so far"
                )

            except Exception as e:
                logger.warning(f"[TaxonomyRAG] Failed to extract specs from file: {e}")

        if not merged_specs:
            logger.info(f"[TaxonomyRAG] No specs extracted for '{product_name}', using fallback")
            return self._mechanical_fallback(product_name)

        if os.getenv("TAXONOMY_USE_MODEL", "false").strip().lower() in ("1", "true", "yes"):
            try:
                from common.infra.repositories.taxonomy_repository import TaxonomyRepository
                tax = TaxonomyRepository.get_full_taxonomy()
                merged_specs = tax.normalize_parameter_keys(product_name, merged_specs)
                logger.info(f"[TaxonomyRAG] Normalized extracted specs using active taxonomy model")
            except Exception as e:
                logger.warning(f"[TaxonomyRAG] Model-driven key normalization failed in file extraction: {e}")

        logger.info(
            f"[TaxonomyRAG] Extracted {len(merged_specs)} specification fields for "
            f"'{product_name}' from {files_processed} files"
        )
        return merged_specs

    def _mechanical_fallback(self, product_name: str) -> dict:
        logger.info(f"[TaxonomyRAG] Applying mechanical fallback for '{product_name}'.")
        return {
            "product_name": product_name,
            "category": "Mechanical Accessory",
            "primary_function": "Mechanical mounting, support or protection",
            "typical_materials": ["stainless steel", "aluminum", "carbon steel"],
            "note": "No functional engineering specifications found in taxonomy. "
                    "This item is likely a mechanical/structural accessory."
        }


_taxonomy_rag_instance = None


def get_taxonomy_rag() -> TaxonomyRAG:
    global _taxonomy_rag_instance
    if _taxonomy_rag_instance is None:
        _taxonomy_rag_instance = TaxonomyRAG()
    return _taxonomy_rag_instance


# ---------------------------------------------------------------------------
# Section 3 — SpecificationRetriever
# ---------------------------------------------------------------------------

class SpecificationRetriever:
    """
    Retrieves specifications for normalized product types from MongoDB or JSON files.

    Supports two modes:
    1. MongoDB mode: Queries a MongoDB collection for product specifications
    2. JSON file mode: Loads specifications from JSON catalog files
    """

    def __init__(
        self,
        mongodb_uri: str | None = None,
        mongodb_database: str = None,
        mongodb_collection: str = None,
        json_catalog_path: str | None = None
    ):
        self.mongodb_uri = mongodb_uri or os.getenv("MONGODB_URI")
        self.mongodb_database = mongodb_database or os.getenv("MONGODB_DATABASE", "engenie")
        self.mongodb_collection = mongodb_collection or os.getenv("MONGODB_COLLECTION", "specs")
        self.json_catalog_path = json_catalog_path

        self._mongo_client = None
        self._json_catalog = None

        self.mode = self._determine_mode()
        logger.info(f"[SpecRetriever] Initialized in {self.mode} mode")

    def _determine_mode(self) -> str:
        if self.mongodb_uri:
            return "mongodb"
        elif self.json_catalog_path:
            return "json"
        else:
            default_path = os.path.join(
                os.path.dirname(__file__),
                "..", "data", "product_catalog.json"
            )
            self.json_catalog_path = default_path
            return "json"

    def _get_mongo_client(self):
        if self._mongo_client is None and self.mongodb_uri:
            try:
                from pymongo import MongoClient
                self._mongo_client = MongoClient(self.mongodb_uri)
                self._mongo_client.admin.command('ping')
                logger.info("[SpecRetriever] MongoDB connection established")
            except Exception as e:
                logger.error(f"[SpecRetriever] MongoDB connection failed: {e}")
                self._mongo_client = None
        return self._mongo_client

    def _load_json_catalog(self) -> dict[str, Any]:
        if self._json_catalog is not None:
            return self._json_catalog
        if not self.json_catalog_path:
            logger.warning("[SpecRetriever] No JSON catalog path specified")
            return {}
        try:
            catalog_path = Path(self.json_catalog_path)
            if not catalog_path.exists():
                logger.warning(f"[SpecRetriever] JSON catalog not found: {catalog_path}")
                return {}
            if catalog_path.is_file():
                with open(catalog_path, encoding='utf-8-sig') as f:
                    self._json_catalog = json.load(f)
                logger.info(f"[SpecRetriever] Loaded catalog from {catalog_path}")
            elif catalog_path.is_dir():
                self._json_catalog = {}
                for json_file in catalog_path.glob("*.json"):
                    with open(json_file, encoding='utf-8-sig') as f:
                        data = json.load(f)
                        self._json_catalog.update(data)
                logger.info(f"[SpecRetriever] Loaded catalog from directory {catalog_path}")
            return self._json_catalog or {}
        except Exception as e:
            logger.error(f"[SpecRetriever] Failed to load JSON catalog: {e}")
            return {}

    def get_specification(self, canonical_name: str) -> dict[str, Any] | None:
        """Get specification for a single product by canonical name."""
        if self.mode == "mongodb":
            return self._get_spec_from_mongodb(canonical_name)
        else:
            return self._get_spec_from_json(canonical_name)

    def _get_spec_from_mongodb(self, canonical_name: str) -> dict[str, Any] | None:
        try:
            client = self._get_mongo_client()
            if not client:
                return None
            db = client[self.mongodb_database]
            collection = db[self.mongodb_collection]
            spec = collection.find_one(
                {"product_type": {"$regex": f"^{canonical_name}$", "$options": "i"}}
            )
            if spec:
                spec.pop('_id', None)
                logger.debug(f"[SpecRetriever] Found spec for '{canonical_name}' in MongoDB")
                return spec
            logger.debug(f"[SpecRetriever] No spec found for '{canonical_name}' in MongoDB")
            return None
        except Exception as e:
            logger.error(f"[SpecRetriever] MongoDB query failed for '{canonical_name}': {e}")
            return None

    def _get_spec_from_json(self, canonical_name: str) -> dict[str, Any] | None:
        catalog = self._load_json_catalog()
        if not catalog:
            return None
        if canonical_name in catalog:
            logger.debug(f"[SpecRetriever] Found spec for '{canonical_name}' in JSON (exact)")
            return catalog[canonical_name]
        canonical_lower = canonical_name.lower()
        for key, value in catalog.items():
            if key.lower() == canonical_lower:
                logger.debug(f"[SpecRetriever] Found spec for '{canonical_name}' in JSON (case-insensitive)")
                return value
        logger.debug(f"[SpecRetriever] No spec found for '{canonical_name}' in JSON")
        return None

    def get_specifications_batch(
        self,
        normalized_items: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Retrieve specifications for all normalized items in batch."""
        logger.info(f"[SpecRetriever] Batch retrieval for {len(normalized_items)} items")
        results = {}
        found_count = 0
        for idx, item in enumerate(normalized_items):
            item_key = f"item_{idx}"
            canonical_name = item.get("canonical_name", "")
            original_name = (
                item.get("product_type") or item.get("product_name")
                or item.get("name") or canonical_name
            )
            if not canonical_name:
                logger.warning(f"[SpecRetriever] Item {idx} has no canonical_name, skipping")
                results[item_key] = {
                    "canonical_name": "",
                    "original_name": original_name,
                    "specifications": {},
                    "spec_found": False,
                    "error": "No canonical name"
                }
                continue
            spec = self.get_specification(canonical_name)
            if spec:
                found_count += 1
                results[item_key] = {
                    "canonical_name": canonical_name,
                    "original_name": original_name,
                    "specifications": spec,
                    "spec_found": True,
                    "category": item.get("category", "unknown"),
                    "quantity": item.get("quantity", 1)
                }
            else:
                results[item_key] = {
                    "canonical_name": canonical_name,
                    "original_name": original_name,
                    "specifications": {},
                    "spec_found": False,
                    "category": item.get("category", "unknown"),
                    "quantity": item.get("quantity", 1)
                }
        logger.info(
            f"[SpecRetriever] Batch complete: {found_count}/{len(normalized_items)} "
            f"specifications found"
        )
        return results

    def close(self):
        """Close MongoDB connection if open."""
        if self._mongo_client:
            self._mongo_client.close()
            logger.info("[SpecRetriever] MongoDB connection closed")


# ---------------------------------------------------------------------------
# Section 4 — TaxonomyNormalizationAgent
# ---------------------------------------------------------------------------

class TaxonomyNormalizationAgent:
    """
    Normalizes product item names to canonical taxonomy names.
    Uses a hardcoded alias map as the first line of resolution,
    with optional RAG fallback (currently stubbed).
    """

    def __init__(self, memory=None):
        self.memory = memory
        self._rag = None
        # P2.5 FIX: Cache alias_map at instance level to avoid rebuilding on every call
        self._cached_alias_map: dict[str, str] | None = None
        self._alias_map_memory_id: int | None = None  # Track memory identity for cache invalidation

    def _get_rag(self) -> TaxonomyRAG:
        if self._rag is None:
            self._rag = get_taxonomy_rag()
        return self._rag

    def _build_alias_map_via_model(self) -> dict[str, str]:
        """Phase 3: build the flat alias map via the typed Taxonomy model (JSON + memory + DB)."""
        try:
            from common.models.taxonomy import Taxonomy

            alias_map: dict[str, str] = {}

            # JSON seed
            json_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "taxonomy_aliases.json")
            if os.path.exists(json_path):
                with open(json_path) as f:
                    data = json.load(f)
                alias_map.update(Taxonomy.from_aliases_json(data).flat_alias_index())

            # Memory taxonomy (parity with legacy path)
            if self.memory and hasattr(self.memory, "get_taxonomy"):
                taxonomy = self.memory.get_taxonomy() or {}
                for section in ("instruments", "accessories"):
                    for item in taxonomy.get(section, []):
                        canonical = item.get("name", "")
                        if not canonical:
                            continue
                        alias_map[canonical.lower()] = canonical
                        for alias in item.get("aliases", []):
                            alias_map[alias.lower()] = canonical

            # Live MongoDB alias overrides
            try:
                conn = get_mongodb_connection()
                taxonomy_coll = conn["collections"]["taxonomy"]
                db_docs = list(taxonomy_coll.find({"type": "alias"}))
                if db_docs:
                    alias_map.update(Taxonomy.from_flat_alias_docs(db_docs).flat_alias_index())
            except Exception as db_e:
                logger.debug(f"[TaxonomyNorm] model-path DB alias load skipped: {db_e}")

            logger.info(f"[TaxonomyNorm] Built alias map via Taxonomy model: {len(alias_map)} entries")
            return alias_map
        except Exception as e:
            logger.warning(f"[TaxonomyNorm] Model-based alias map failed, falling back to legacy: {e}")
            return {}

    def _get_alias_map(self) -> dict[str, str]:
        """
        Comprehensive alias map covering common user terms and abbreviations.
        Loads from taxonomy_aliases.json and merges with MongoDB 'taxonomy' collection.
        P2.5 FIX: Cached at instance level to avoid rebuilding on every call.
        """
        # Check cache - invalidate if memory reference changed
        current_memory_id = id(self.memory) if self.memory else None
        if (
            self._cached_alias_map is not None
            and self._alias_map_memory_id == current_memory_id
        ):
            return self._cached_alias_map

        # Phase 3 (opt-in): build the map from the typed Taxonomy model when enabled.
        if os.getenv("TAXONOMY_USE_MODEL", "false").strip().lower() in ("1", "true", "yes"):
            model_map = self._build_alias_map_via_model()
            if model_map:
                self._cached_alias_map = model_map
                self._alias_map_memory_id = current_memory_id
                return model_map

        # 1. Load from JSON file (Primary seed)
        alias_map = {}
        try:
            # Use absolute path to avoid ambiguity
            json_path = os.path.join(os.path.dirname(__file__), "..", "..", "resources", "taxonomy_aliases.json")
            if os.path.exists(json_path):
                with open(json_path) as f:
                    data = json.load(f)
                    # Flatten categorization if present
                    if isinstance(data, dict):
                        for cat, mappings in data.items():
                            if isinstance(mappings, dict):
                                for k, v in mappings.items():
                                    alias_map[k.lower()] = v
                            else:
                                alias_map[cat.lower()] = mappings
                logger.info(f"[TaxonomyNorm] Loaded {len(alias_map)} aliases from JSON file: {json_path}")
        except Exception as json_e:
            logger.warning(f"[TaxonomyNorm] Could not load aliases from JSON: {json_e}")

        # 2. Merge with memory-based taxonomy if available
        if self.memory:
            try:
                if hasattr(self.memory, 'get_taxonomy'):
                    taxonomy = self.memory.get_taxonomy()
                    if taxonomy:
                        for section in ("instruments", "accessories"):
                            for item in taxonomy.get(section, []):
                                canonical = item.get("name", "")
                                if not canonical: continue
                                alias_map[canonical.lower()] = canonical
                                for alias in item.get("aliases", []):
                                    alias_map[alias.lower()] = canonical
            except Exception as mem_e:
                logger.debug(f"[TaxonomyNorm] Memory taxonomy loading skipped: {mem_e}")

        # 3. Load from MongoDB 'taxonomy' collection (Dynamic updates)
        try:
            from common.infra.mongodb_config import get_mongodb_connection
            conn = get_mongodb_connection()
            # Use 'taxonomy' collection for live alias overrides
            taxonomy_coll = conn['collections']['taxonomy']

            db_aliases = list(taxonomy_coll.find({"type": "alias"}))
            for item in db_aliases:
                alias = item.get("alias")
                canonical = item.get("canonical")
                if alias and canonical:
                    alias_map[alias.lower()] = canonical
            if db_aliases:
                logger.info(f"[TaxonomyNorm] Loaded {len(db_aliases)} aliases from MongoDB")
        except Exception as db_e:
            logger.debug(f"[TaxonomyNorm] MongoDB dynamic alias loading skipped: {db_e}")

        # 4. Emergency seed if all else fails
        if not alias_map:
            alias_map = {"temp": "Temperature Transmitter", "press": "Pressure Transmitter"}

        self._cached_alias_map = alias_map
        self._alias_map_memory_id = current_memory_id
        return alias_map

    def _fuzzy_match(
        self,
        raw_lower: str,
        alias_map: dict[str, str],
    ) -> str | None:
        """
        Multi-strategy fuzzy matching:
        1. Strip trailing 's' (plurals)
        2. Substring matching against alias keys
        3. Levenshtein-based close match against all canonical names + alias keys
        """
        from difflib import get_close_matches

        # Strategy 1: Strip plural 's'
        if raw_lower.endswith("s") and len(raw_lower) > 3:
            singular = raw_lower[:-1]
            if singular in alias_map:
                logger.info(f"[TaxonomyNorm] Plural strip match: '{raw_lower}' → '{alias_map[singular]}'")
                return alias_map[singular]

        # Strategy 2: Check if raw_lower is contained in any alias key or vice versa
        for alias_key, canonical in alias_map.items():
            # Skip very short keys to avoid false positives
            if len(alias_key) < 4 or len(raw_lower) < 4:
                continue

            # P1.6 HEURISTIC PROTECTION: Prevent 'gauge' from matching 'transmitter'
            if ("gauge" in raw_lower and "transmitter" in alias_key) or \
               ("transmitter" in raw_lower and "gauge" in alias_key):
                continue

            # Check if either contains the other (minimum 75% overlap in length)
            # P1.7 INCREASE OVERLAP: 0.7 was too low
            if raw_lower in alias_key and len(raw_lower) >= len(alias_key) * 0.75:
                logger.info(f"[TaxonomyNorm] Substring match: '{raw_lower}' in '{alias_key}' → '{canonical}'")
                return canonical
            if alias_key in raw_lower and len(alias_key) >= len(raw_lower) * 0.75:
                logger.info(f"[TaxonomyNorm] Substring match: '{alias_key}' in '{raw_lower}' → '{canonical}'")
                return canonical

        # Strategy 3: Levenshtein-based fuzzy match against alias keys
        all_keys = list(alias_map.keys())
        # P1.5 INCREASE CUTOFF: 0.6 was too loose, matching 'gauge' to 'transmitter'
        close = get_close_matches(raw_lower, all_keys, n=1, cutoff=0.75)
        if close:
            # P1.6 HEURISTIC PROTECTION: Prevent 'gauge' from matching 'transmitter'
            if "gauge" in raw_lower and "transmitter" in close[0].lower():
                logger.info(f"[TaxonomyNorm] Rejecting fuzzy match '{raw_lower}' ≈ '{close[0]}' (gauge vs transmitter)")
            else:
                canonical = alias_map[close[0]]
                logger.info(f"[TaxonomyNorm] Fuzzy match: '{raw_lower}' ≈ '{close[0]}' → '{canonical}'")
                return canonical

        # Strategy 4: Fuzzy match against unique canonical names (the target values)
        canonical_names = list(set(alias_map.values()))
        canonical_lower_map = {c.lower(): c for c in canonical_names}
        # P1.5 INCREASE CUTOFF: 0.6 was too loose
        close_canonical = get_close_matches(raw_lower, list(canonical_lower_map.keys()), n=1, cutoff=0.75)
        if close_canonical:
            canonical = canonical_lower_map[close_canonical[0]]
            # P1.6 HEURISTIC PROTECTION: Prevent 'gauge' from matching 'transmitter'
            if "gauge" in raw_lower and "transmitter" in canonical.lower():
                logger.info(f"[TaxonomyNorm] Rejecting canonical match '{raw_lower}' ≈ '{canonical}' (gauge vs transmitter)")
            else:
                logger.info(f"[TaxonomyNorm] Fuzzy canonical match: '{raw_lower}' ≈ '{canonical}'")
                return canonical

        # Strategy 5: Try matching against specs DB product_type names
        try:
            retriever_names = self._get_specs_product_types()
            if retriever_names:
                names_lower_map = {n.lower(): n for n in retriever_names}
                # P1.5 INCREASE CUTOFF: 0.6 was too loose
                close_db = get_close_matches(raw_lower, list(names_lower_map.keys()), n=1, cutoff=0.75)
                if close_db:
                    canonical = names_lower_map[close_db[0]]
                    # P1.6 HEURISTIC PROTECTION: Prevent 'gauge' from matching 'transmitter'
                    if "gauge" in raw_lower and "transmitter" in canonical.lower():
                        logger.info(f"[TaxonomyNorm] Rejecting DB match '{raw_lower}' ≈ '{canonical}' (gauge vs transmitter)")
                    else:
                        logger.info(f"[TaxonomyNorm] DB fuzzy match: '{raw_lower}' ≈ '{canonical}'")
                        return canonical

                # Strategy 6: DYNAMIC LLM CATEGORIZATION (No hardcoded mapping)
                # If fuzzy match failed, use LLM to pick from the actual DB product types.
                # This ensures we match 'temp sensor' to 'Temperature Transmitter' dynamically.
                # We filter names_lower_map keys by basic substring search to narrow candidates.
                candidates = [n for n in retriever_names if any(w in n.lower() for w in raw_lower.split()[:2])]
                if candidates and len(candidates) > 0:
                    # Limit to top 20 candidates
                    candidates = candidates[:20]
                    # Call LLM to disambiguate
                    from common.ai.llm import get_lite_llm
                    llm = get_lite_llm(temperature=0.1)


                    try:
                        resp = llm.invoke(f"User Input: {raw_lower}\nCandidates: {json.dumps(candidates)}").content.strip()
                        if resp in candidates:
                            logger.info(f"[TaxonomyNorm] Dynamic LLM match: '{raw_lower}' → '{resp}'")
                            return resp
                        logger.debug(f"[TaxonomyNorm] Dynamic LLM match failed: '{resp}' not in candidates")
                    except Exception as llm_e:
                        logger.warning(f"[TaxonomyNorm] Dynamic LLM mapping error: {llm_e}")
        except Exception as e:
            logger.debug(f"[TaxonomyNorm] DB/LLM matching error: {e}")

        return None

    def _get_specs_product_types(self) -> list[str]:
        """Get all product_type values from specs collection for fuzzy matching.

        P0.2 FIX: Uses get_mongodb_connection() instead of creating raw MongoClient
        to avoid connection leak.
        """
        if not hasattr(self, "_specs_product_types_cache"):
            try:
                # Use shared connection pool instead of creating new MongoClient
                conn = get_mongodb_connection()
                specs_collection = conn['collections'][Collections.SPECS]
                self._specs_product_types_cache = specs_collection.distinct("product_type")
                logger.debug(f"[TaxonomyNorm] Loaded {len(self._specs_product_types_cache)} product types from specs DB")
            except Exception as e:
                logger.warning(f"[TaxonomyNorm] Could not load specs product types: {e}")
                self._specs_product_types_cache = []
        return self._specs_product_types_cache

    def _resolve_term(
        self,
        raw_name: str,
        item_type: str,
        alias_map: dict[str, str],
        context_description: str = ""
    ) -> dict[str, Any]:
        raw_lower = raw_name.strip().lower()

        # Step 1: Exact alias map lookup
        if raw_lower in alias_map:
            canonical = alias_map[raw_lower]
            logger.info(f"[TaxonomyNorm] Alias match: '{raw_name}' → '{canonical}'")
            return {
                "canonical_name": canonical,
                "taxonomy_matched": True,
                "match_source": "alias_map",
            }

        # Step 2: Fuzzy matching (plural strip, substring, Levenshtein, DB names)
        fuzzy_result = self._fuzzy_match(raw_lower, alias_map)
        if fuzzy_result:
            return {
                "canonical_name": fuzzy_result,
                "taxonomy_matched": True,
                "match_source": "fuzzy_match",
            }

        # Step 3: RAG vector retrieval
        rag = self._get_rag()
        if rag:
            try:
                query = f"{raw_name} {context_description}".strip()
                results = rag.retrieve(query=query, top_k=1, item_type=item_type)
                if results and results[0].get("score", 0) >= 0.70:
                    canonical = results[0]["name"]
                    logger.info(
                        f"[TaxonomyNorm] RAG match: '{raw_name}' → '{canonical}' "
                        f"(score={results[0]['score']:.2f})"
                    )
                    return {
                        "canonical_name": canonical,
                        "taxonomy_matched": True,
                        "match_source": "rag_retrieval",
                    }
            except Exception as e:
                logger.debug(f"[TaxonomyNorm] RAG retrieval error for '{raw_name}': {e}")

        logger.debug(f"[TaxonomyNorm] No match for '{raw_name}', using as-is")
        return {
            "canonical_name": raw_name,
            "taxonomy_matched": False,
            "match_source": "passthrough",
        }

    def normalize(self, items: list[dict[str, Any]], item_type: str = "instrument") -> list[dict[str, Any]]:
        """Standard normalization without conversation context."""
        if not items:
            return items

        alias_map = self._get_alias_map()
        normalized = []

        for item in items:
            raw_name = (
                item.get("product_type") or item.get("product_name")
                or item.get("name") or item.get("category") or ""
            )
            short_description = item.get("short_description", "")

            logger.info(f"[TaxonomyNorm Standard] Processing Item: '{raw_name}'")
            logger.info(f"[TaxonomyNorm Standard] Extracted Short Desc: '{short_description}'")

            resolution = self._resolve_term(
                raw_name=raw_name,
                item_type=item_type,
                alias_map=alias_map,
                context_description=short_description
            )

            enriched_item = dict(item)
            enriched_item["canonical_name"] = resolution["canonical_name"]

            if resolution["taxonomy_matched"]:
                if "product_type" in enriched_item:
                    enriched_item["product_type"] = resolution["canonical_name"]
                elif "product_name" in enriched_item:
                    enriched_item["product_name"] = resolution["canonical_name"]
                if "name" in enriched_item:
                    enriched_item["name"] = resolution["canonical_name"]

            enriched_item["taxonomy_matched"] = resolution["taxonomy_matched"]
            enriched_item["match_source"] = resolution["match_source"]
            normalized.append(enriched_item)

        matched = sum(1 for i in normalized if i.get("taxonomy_matched"))
        logger.info(
            f"[TaxonomyNorm] Normalized {len(normalized)} {item_type}(s): "
            f"{matched}/{len(normalized)} matched taxonomy"
        )
        return normalized

    def normalize_with_context(
        self,
        items: list[dict[str, Any]],
        user_input: str,
        history: list[dict[str, str]],
        item_type: str = "instrument"
    ) -> list[dict[str, Any]]:
        """Normalize items taking conversation context into account."""
        if not items:
            return items

        ctx = TaxonomyContextManager()
        ctx.load_history(history)

        alias_map = self._get_alias_map()
        normalized = []

        for item in items:
            raw_name = (
                item.get("product_type") or item.get("product_name")
                or item.get("name") or item.get("category") or ""
            )
            short_description = item.get("short_description", "")
            # P1.11 FIX: Assign the computed string to variable instead of discarding
            f"{raw_name} {short_description}".strip()

            resolved_name_from_context = ctx.resolve_contextual_references(raw_name)

            logger.info(f"[TaxonomyNorm Context] Raw Name: '{raw_name}' | Short Description: '{short_description}'")
            logger.info(f"[TaxonomyNorm Context] Resolved Name: '{resolved_name_from_context}' | Dispatching to Taxonomy...")

            resolution = self._resolve_term(
                raw_name=resolved_name_from_context,
                item_type=item_type,
                alias_map=alias_map,
                context_description=short_description
            )

            enriched_item = dict(item)
            enriched_item["canonical_name"] = resolution["canonical_name"]

            if resolution["taxonomy_matched"]:
                if "product_type" in enriched_item:
                    enriched_item["product_type"] = resolution["canonical_name"]
                elif "product_name" in enriched_item:
                    enriched_item["product_name"] = resolution["canonical_name"]
                if "name" in enriched_item:
                    enriched_item["name"] = resolution["canonical_name"]

            enriched_item["taxonomy_matched"] = resolution["taxonomy_matched"]
            enriched_item["match_source"] = resolution["match_source"]

            if resolved_name_from_context != raw_name:
                enriched_item["context_resolved_from"] = raw_name
                enriched_item["context_resolved_to"] = resolved_name_from_context

            normalized.append(enriched_item)

        return normalized

    def normalize_all(
        self,
        instruments: list[dict[str, Any]],
        accessories: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "standardized_instruments": self.normalize(instruments, "instrument"),
            "standardized_accessories": self.normalize(accessories, "accessory"),
        }

    def _get_reverse_alias_map(self) -> dict[str, str]:
        """Builds a map from Canonical Name → Shortest Alias (Database Code)."""
        reverse_map: dict[str, str] = {}
        if not self.memory:
            return reverse_map
        try:
            taxonomy = self.memory.get_taxonomy()
            if not taxonomy:
                return reverse_map
            for section in ("instruments", "accessories"):
                for item in taxonomy.get(section, []):
                    canonical = item.get("name", "")
                    aliases = item.get("aliases", [])
                    if not canonical or not aliases:
                        continue
                    shortest_alias = min(aliases, key=len)
                    reverse_map[canonical.lower()] = shortest_alias
        except Exception as e:
            logger.debug(f"[TaxonomyNorm] Could not build reverse alias map: {e}")
        return reverse_map

    def reverse_normalize(
        self,
        items: list[dict[str, Any]],
        item_type: str = "instrument"
    ) -> list[dict[str, Any]]:
        """Map canonical names back to their database codes/aliases."""
        if not items:
            return items

        reverse_map = self._get_reverse_alias_map()
        normalized = []

        for item in items:
            name_to_reverse = (
                item.get("canonical_name") or item.get("product_type")
                or item.get("product_name") or item.get("name") or ""
            ).strip()
            name_lower = name_to_reverse.lower()

            reversed_code = name_to_reverse
            match_source = "passthrough"

            if name_lower in reverse_map:
                reversed_code = reverse_map[name_lower]
                match_source = "reverse_map"
                logger.info(f"[TaxonomyNorm] Reverse match: '{name_to_reverse}' → '{reversed_code}'")

            enriched_item = dict(item)
            enriched_item["reverse_name"] = reversed_code
            enriched_item["reverse_match_source"] = match_source
            normalized.append(enriched_item)

        return normalized

    def reverse_normalize_all(
        self,
        instruments: list[dict[str, Any]],
        accessories: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "reverse_instruments": self.reverse_normalize(instruments, "instrument"),
            "reverse_accessories": self.reverse_normalize(accessories, "accessory"),
        }

    def batch_normalize_solution_items(
        self,
        instruments: list[dict[str, Any]],
        accessories: list[dict[str, Any]],
        conversation_history: list[dict[str, str]] = None,
        user_input: str = ""
    ) -> dict[str, Any]:
        """
        Batch normalize all instruments and accessories from a Solution Deep Agent.

        Primary entry point for the Solution → Search workflow handoff.

        Returns:
            {
                "standardized_instruments": [...],
                "standardized_accessories": [...],
                "normalization_stats": { total_items, match_rate, ... }
            }
        """
        logger.info(
            f"[TaxonomyNorm] Batch normalization: "
            f"{len(instruments)} instruments, {len(accessories)} accessories"
        )

        if conversation_history and user_input:
            standardized_instruments = self.normalize_with_context(
                instruments, user_input, conversation_history, "instrument"
            )
            standardized_accessories = self.normalize_with_context(
                accessories, user_input, conversation_history, "accessory"
            )
        else:
            standardized_instruments = self.normalize(instruments, "instrument")
            standardized_accessories = self.normalize(accessories, "accessory")

        total_items = len(instruments) + len(accessories)
        instruments_matched = sum(
            1 for item in standardized_instruments if item.get("taxonomy_matched", False)
        )
        accessories_matched = sum(
            1 for item in standardized_accessories if item.get("taxonomy_matched", False)
        )
        total_matched = instruments_matched + accessories_matched
        match_rate = total_matched / total_items if total_items > 0 else 0.0

        stats = {
            "total_items": total_items,
            "instruments_processed": len(instruments),
            "accessories_processed": len(accessories),
            "instruments_matched": instruments_matched,
            "accessories_matched": accessories_matched,
            "total_matched": total_matched,
            "match_rate": round(match_rate, 3)
        }

        logger.info(
            f"[TaxonomyNorm] Batch complete: {total_matched}/{total_items} matched "
            f"({stats['match_rate'] * 100:.1f}%)"
        )

        return {
            "standardized_instruments": standardized_instruments,
            "standardized_accessories": standardized_accessories,
            "normalization_stats": stats
        }


# ---------------------------------------------------------------------------
# Section 5 — TaxonomyIntegrationAdapter
# ---------------------------------------------------------------------------

class TaxonomyIntegrationAdapter:
    """
    Adapter to bridge Solution Agent data with Product Search Workflow.
    Ensures that normalized taxonomy data and sample inputs are correctly
    formatted for downstream consumption.
    """

    @staticmethod
    def prepare_search_payload(
        normalized_items: list[dict[str, Any]],
        solution_name: str = "Solution",
        solution_id: str = "",
        sample_inputs: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Convert normalized Solution Agent items into Product Search 'required_products' format."""
        required_products = []

        for item in normalized_items:
            product_type = (
                item.get("canonical_name") or item.get("product_type")
                or item.get("product_name") or item.get("name") or "Unknown Product"
            )
            specs = item.get("specifications", {})
            raw_name = item.get("name", "")
            short_description = item.get("short_description", "")
            if not short_description and sample_inputs:
                short_description = sample_inputs.get(product_type) or sample_inputs.get(raw_name) or ""

            product_entry = {
                "product_type": product_type,
                "quantity": item.get("quantity", 1),
                "application": f"{solution_name} - {item.get('category', 'General')}",
                "requirements": specs,
                "sample_input": short_description,
                "original_name": item.get("name", product_type),
                "taxonomy_matched": item.get("taxonomy_matched", False)
            }

            if "user_specifications" in item:
                product_entry["user_specifications"] = item["user_specifications"]
            if "catalog_specifications" in item:
                product_entry["catalog_specifications"] = item["catalog_specifications"]

            required_products.append(product_entry)

        return {
            "source": "solution_workflow",
            "solution_id": solution_id,
            "solution_name": solution_name,
            "required_products": required_products,
            "total_products": len(required_products)
        }

    @staticmethod
    def verify_normalization_status(items: list[dict[str, Any]]) -> dict[str, Any]:
        """Check if items have been properly normalized by Taxonomy RAG."""
        total = len(items)
        normalized_count = sum(1 for i in items if i.get("taxonomy_matched"))
        missing = [i.get("name", "Unknown") for i in items if not i.get("taxonomy_matched")]
        return {
            "total": total,
            "normalized": normalized_count,
            "coverage_pct": (normalized_count / total * 100) if total > 0 else 0,
            "missing_normalization": missing
        }

    @staticmethod
    def prepare_for_search_workflow(
        solution_deep_agent_output: dict[str, Any],
        mongodb_uri: str | None = None,
        json_catalog_path: str | None = None,
        memory=None
    ) -> dict[str, Any]:
        """
        Complete pipeline: Solution Deep Agent output → Search workflow payload.

        Steps:
        1. Batch normalize instruments + accessories via TaxonomyNormalizationAgent
        2. Description comparison (SequenceMatcher) + specification retrieval
        3. Aggregate specs and package final payload for Search Deep Agent
        """
        start_time = time.time()
        logger.info("[TaxonomyIntegration] Starting pipeline")

        instruments = solution_deep_agent_output.get("identified_instruments", [])
        accessories = solution_deep_agent_output.get("identified_accessories", [])
        solution_name = solution_deep_agent_output.get("solution_name", "Solution")
        user_input = solution_deep_agent_output.get("user_input", "")
        conversation_history = solution_deep_agent_output.get("conversation_history", [])
        total_items = len(instruments) + len(accessories)

        logger.info(
            f"[TaxonomyIntegration] Processing {total_items} items: "
            f"{len(instruments)} instruments, {len(accessories)} accessories"
        )

        try:
            # Step 1: Batch Normalize
            logger.info("[TaxonomyIntegration] Step 1: Batch normalization")
            normalizer = TaxonomyNormalizationAgent(memory=memory)
            normalization_result = normalizer.batch_normalize_solution_items(
                instruments=instruments,
                accessories=accessories,
                conversation_history=conversation_history,
                user_input=user_input
            )
            standardized_instruments = normalization_result["standardized_instruments"]
            standardized_accessories = normalization_result["standardized_accessories"]
            normalization_stats = normalization_result["normalization_stats"]

            logger.info(
                f"[TaxonomyIntegration] Normalization complete: "
                f"{normalization_stats['match_rate'] * 100:.1f}% matched"
            )

            # Step 2: Description comparison + Specification retrieval
            logger.info("[TaxonomyIntegration] Step 2: Description comparison + Specification retrieval")

            retriever = SpecificationRetriever(
                mongodb_uri=mongodb_uri,
                json_catalog_path=json_catalog_path
            )
            rag = get_taxonomy_rag()
            all_normalized_items = standardized_instruments + standardized_accessories
            SIMILARITY_THRESHOLD = 0.35

            for item in all_normalized_items:
                canonical_name = (
                    item.get("canonical_name") or item.get("product_type")
                    or item.get("product_name") or item.get("name", "")
                )
                category = item.get("category", "")
                short_description = item.get("short_description", "")

                # Fetch the specs record once for this product type
                db_record = retriever.get_specification(canonical_name)

                # AUTO-GENERATE short_description if missing
                if not short_description:
                    # First, try to read pre-generated short_description from specs DB
                    if db_record and isinstance(db_record, dict):
                        short_description = db_record.get("short_description", "")

                    # Fallback: generate via LLM if still missing
                    if not short_description:
                        specs = item.get("specifications", item.get("mapped_specifications", {}))
                        short_description = generate_short_description(
                            product_type=canonical_name,
                            category=category,
                            specifications=specs
                        )
                    item["short_description"] = short_description
                    logger.info(
                        f"[TaxonomyIntegration] short_description for "
                        f"'{canonical_name}': '{short_description[:80]}...'"
                    )

                logger.info(
                    f"[TaxonomyIntegration] Processing: '{canonical_name}' | "
                    f"Category: '{category}' | Description: '{short_description[:60]}...'"
                )

                db_description = ""
                if db_record and isinstance(db_record, dict):
                    db_description = db_record.get("description", "")

                similarity_score = 0.0
                enriched_description = short_description

                if short_description and db_description:
                    similarity_score = SequenceMatcher(
                        None,
                        short_description.lower(),
                        db_description.lower()
                    ).ratio()

                    logger.info(
                        f"[TaxonomyIntegration] Similarity score for '{canonical_name}': "
                        f"{similarity_score:.3f} (threshold: {SIMILARITY_THRESHOLD})"
                    )

                    if similarity_score >= SIMILARITY_THRESHOLD:
                        enriched_description = f"{short_description}. {db_description}".strip()
                        logger.info(f"[TaxonomyIntegration] MATCHED — Merged description for '{canonical_name}'")
                    else:
                        logger.info(f"[TaxonomyIntegration] NO MATCH — Using LLM description only for '{canonical_name}'")
                elif db_description and not short_description:
                    enriched_description = db_description

                item["description_similarity"] = round(similarity_score, 3)
                item["db_description"] = db_description
                item["enriched_description"] = enriched_description

                search_query = f"{canonical_name} {category} {enriched_description}".strip()
                files = rag.get_top_files_by_similarity(query=search_query, top_k=3)

                vector_specs = {}
                if files:
                    vector_specs = rag.extract_specifications_from_files(canonical_name, files)
                item["vector_specifications"] = vector_specs

            spec_results = retriever.get_specifications_batch(all_normalized_items)
            retriever.close()

            # Step 3: Aggregate and prepare final payload
            logger.info("[TaxonomyIntegration] Step 3: Aggregating results")
            items_with_specifications = []
            specs_found = 0

            for idx, item in enumerate(all_normalized_items):
                item_key = f"item_{idx}"
                spec_data = spec_results.get(item_key, {})

                merged_specs = item.get("vector_specifications", {})
                db_specs = spec_data.get("specifications", {})
                for k, v in db_specs.items():
                    merged_specs[k] = v

                if os.getenv("TAXONOMY_USE_MODEL", "false").strip().lower() in ("1", "true", "yes"):
                    try:
                        from common.infra.repositories.taxonomy_repository import TaxonomyRepository
                        tax = TaxonomyRepository.get_full_taxonomy()
                        canonical_name = item.get("canonical_name", "")
                        merged_specs = tax.normalize_parameter_keys(canonical_name, merged_specs)
                        logger.info(f"[TaxonomyIntegration] Normalized batch merged specs for '{canonical_name}'")
                    except Exception as e:
                        logger.warning(f"[TaxonomyIntegration] Model-driven key normalization failed in batch merge: {e}")

                has_spec = len(merged_specs) > 0

                aggregated_item = {
                    "id": idx + 1,
                    "original_name": (
                        item.get("product_type") or item.get("product_name") or item.get("name", "")
                    ),
                    "canonical_name": item.get("canonical_name", ""),
                    "category": item.get("category", "unknown"),
                    "quantity": item.get("quantity", 1),
                    "taxonomy_matched": item.get("taxonomy_matched", False),
                    "match_source": item.get("match_source", "unknown"),
                    "specifications": merged_specs,
                    "spec_found": has_spec,
                }

                if "user_specifications" in item:
                    aggregated_item["user_specifications"] = item["user_specifications"]

                items_with_specifications.append(aggregated_item)
                if has_spec:
                    specs_found += 1

            spec_stats = {
                "total_items": total_items,
                "specifications_found": specs_found,
                "specifications_missing": total_items - specs_found,
                "spec_found_rate": round(specs_found / total_items, 3) if total_items > 0 else 0.0
            }

            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"[TaxonomyIntegration] Pipeline complete in {processing_time_ms}ms: "
                f"{specs_found}/{total_items} specs found ({spec_stats['spec_found_rate'] * 100:.1f}%)"
            )

            return {
                "success": True,
                "solution_name": solution_name,
                "total_items": total_items,
                "items_with_specifications": items_with_specifications,
                "normalization_stats": normalization_stats,
                "specification_stats": spec_stats,
                "processing_time_ms": processing_time_ms,
                "standardized_instruments": standardized_instruments,
                "standardized_accessories": standardized_accessories,
            }

        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"[TaxonomyIntegration] Pipeline failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "solution_name": solution_name,
                "total_items": total_items,
                "processing_time_ms": processing_time_ms
            }

    @staticmethod
    def prepare_search_payload_for_item(
        item: dict[str, Any],
        solution_name: str = "Solution",
        solution_id: str = ""
    ) -> dict[str, Any]:
        """Prepare a single item for the Search Deep Agent workflow."""
        return {
            "product_type": item.get("canonical_name", item.get("original_name", item.get("name", ""))),
            "sample_input": f"{item.get('quantity', 1)}x {item.get('canonical_name', item.get('name', ''))}",
            "solution_name": solution_name,
            "solution_id": solution_id,
            "user_specifications": item.get("user_specifications", {}),
            "catalog_specifications": item.get("specifications", {}),
            "quantity": item.get("quantity", 1),
            "category": item.get("category", "unknown"),
            "taxonomy_matched": item.get("taxonomy_matched", False)
        }

    @staticmethod
    def prepare_batch_search_payload(pipeline_result: dict[str, Any]) -> list[dict[str, Any]]:
        """Prepare all items for batch processing by Search Deep Agent."""
        if not pipeline_result.get("success"):
            logger.error("[TaxonomyIntegration] Cannot prepare search payload: pipeline failed")
            return []

        solution_name = pipeline_result.get("solution_name", "Solution")
        items = pipeline_result.get("items_with_specifications", [])
        payloads = []

        for item in items:
            payload = TaxonomyIntegrationAdapter.prepare_search_payload_for_item(
                item=item,
                solution_name=solution_name
            )
            payloads.append(payload)

        logger.info(f"[TaxonomyIntegration] Prepared {len(payloads)} search payloads")
        return payloads


# ---------------------------------------------------------------------------
# Section 6 — Module-level compatibility wrappers
# ---------------------------------------------------------------------------

def prepare_for_search_workflow(*args, **kwargs):
    return TaxonomyIntegrationAdapter.prepare_for_search_workflow(*args, **kwargs)


def prepare_search_payload_for_item(*args, **kwargs):
    return TaxonomyIntegrationAdapter.prepare_search_payload_for_item(*args, **kwargs)


def prepare_batch_search_payload(*args, **kwargs):
    return TaxonomyIntegrationAdapter.prepare_batch_search_payload(*args, **kwargs)


# ---------------------------------------------------------------------------
# Section 7 — get_taxonomy_for_category (existing lightweight live matcher)
# ---------------------------------------------------------------------------

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

TAXONOMY_AND_SPEC_MAPPING_PROMPT = """
You are an expert industrial taxonomy and specification field matching system with semantic analysis capabilities.

**USER INPUT:**
Category: "{user_category}"
Specification Fields: {user_spec_fields}

**DATABASE:**
Matched Product Type: "{db_category}"
Database Specification Fields: {db_spec_fields}

**YOUR TASK:**
1. **Category Matching**: Determine if user category and database category have SAME or DIFFERENT meaning
2. **Specification Field Mapping**: For EACH user specification field, find the best matching database field

---

## PART 1: CATEGORY SEMANTIC MATCHING

**Matching Rules:**

EXACT_MATCH:
- User category exactly matches database type (ignoring case)
- Example: "flow meter" → "Flow Meter"
- Action: use_db_category = true

SAME_MEANING (Semantic Match):
- User category and database category refer to the SAME product type, just different words
- Examples:
  * "pressure sensor" → "Pressure Transmitter" (sensor = transmitter for same measurement)
  * "temp transmitter" → "Temperature Transmitter" (temp = temperature abbreviation)
  * "level gauge" → "Level Transmitter" (gauge = transmitter for same measurement)
- Action: use_db_category = true (frontend shows DB name only)

DIFFERENT_MEANING:
- User category and database category refer to DIFFERENT product types
- Examples:
  * "pressure transmitter" → "Temperature Transmitter" (different measurements)
  * "flow sensor" → "Level Transmitter" (different measurements)
- Action: use_db_category = false (frontend shows both names)

---

## PART 2: SPECIFICATION FIELD MAPPING

For EACH user specification field, match to database field:

**EXACT_MATCH:**
- User field name exactly matches database field (case-insensitive)
- Example: "accuracy" (user) = "accuracy" (DB)
- Action: Use user's original field name

**SEMANTIC_MATCH:**
- User field has SAME MEANING as database field, different words
- Examples:
  * "range" (user) → "measurementRange" (DB) - SAME MEANING
  * "material" (user) → "materials" (DB) - SAME MEANING
  * "temp range" (user) → "ambientTemperatureRange" (DB) - SAME MEANING
  * "operating pressure" (user) → "processPressureRange" (DB) - SAME MEANING
- Action: Use database field name (show DB name in frontend)

**NO_MATCH:**
- User field has no matching database field (different meaning or not found)
- Example: "custom_note" (user) → no DB field
- Action: Use user's original field name

**CRITICAL RULES:**
- If EXACT_MATCH → use user's field name (they already match)
- If SEMANTIC_MATCH → use database field name (for consistency)
- If NO_MATCH → use user's field name (preserve custom fields)

---

## OUTPUT FORMAT

Return ONLY valid JSON (no markdown, no backticks):

{{
  "category_match": {{
    "semantic_match": "EXACT_MATCH" | "SAME_MEANING" | "DIFFERENT_MEANING",
    "use_db_category": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation"
  }},
  "spec_field_mappings": [
    {{
      "user_field": "<original user field name>",
      "db_field": "<matched DB field or user field if no match>",
      "match_type": "EXACT_MATCH" | "SEMANTIC_MATCH" | "NO_MATCH",
      "confidence": 0.0-1.0,
      "reasoning": "Brief explanation"
    }}
  ]
}}

**Decision Summary:**
- Category: EXACT_MATCH or SAME_MEANING → use_db_category = true
- Category: DIFFERENT_MEANING → use_db_category = false
- Spec Fields: EXACT_MATCH → use user field, SEMANTIC_MATCH → use DB field, NO_MATCH → use user field
"""


def _extract_all_spec_fields_from_schema(schema: dict) -> list[str]:
    """Extract all specification field names from schema's mandatory and optional requirements."""
    fields = []

    def traverse(node):
        if isinstance(node, dict):
            # Check if this node is a leaf-level dictionary (all values are primitive types/None, not dicts)
            is_leaf = all(not isinstance(v, dict) for v in node.values())
            if is_leaf:
                fields.extend(node.keys())
            else:
                for k, v in node.items():
                    if isinstance(v, dict):
                        traverse(v)
                    else:
                        fields.append(k)

    mandatory = schema.get("mandatory_requirements") or schema.get("mandatoryRequirements") or {}
    optional = schema.get("optional_requirements") or schema.get("optionalRequirements") or {}
    traverse(mandatory)
    traverse(optional)
    return list(set(fields))


# =========================================================================
# === GENERIC LLM DATA EXTRACTION AGENT ===
# =========================================================================

DYNAMIC_EXTRACTION_PROMPT = """You are a technical data extraction engine with expert industrial domain knowledge.

Read the following user query and extract any key technical specifications, wetted materials, wetted parts, sensor limits, and output protocols.
Output ONLY a flat JSON dictionary of raw key-value pairs (using the exact parameter names as they appear in the query).
Do not include any markdown styling, formatting, or code fences (like ```json). Just return the raw JSON string.

USER QUERY: "{user_query}"
"""

def extract_specifications_generically(user_query: str) -> dict[str, Any]:
    """Dynamically extracts raw key-value parameters from a user query using a generic LLM prompt."""
    if not user_query:
        return {}
    try:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser
        
        llm = get_lite_llm(temperature=0.1)
        prompt = ChatPromptTemplate.from_template(DYNAMIC_EXTRACTION_PROMPT)
        chain = prompt | llm | StrOutputParser()
        
        # Invoke LLM
        response = chain.invoke({"user_query": user_query})
        
        # Clean potential markdown fences
        cleaned = response.strip()
        for prefix in ("```json", "```"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
            
        return json.loads(cleaned.strip())
    except Exception as e:
        logger.warning(f"[TaxonomyExtraction] Failed to extract specifications generically: {e}")
        return {}


@mongodb_retry
def get_taxonomy_for_category(
    category: str,
    user_specifications: dict[str, Any] | None = None
) -> dict:
    """
    Lightweight live matcher used during instrument identification and validation.

    1. Maps user category name to canonical database category name.
    2. Maps user specification field names to database schema field names.

    Uses a single LLM call for both category and spec matching.
    """
    try:
        # ── INPUT LOGGING ──
        logger.info("[TAXONOMY_RAG] ╔══ get_taxonomy_for_category CALLED ══╗")
        logger.info(f"[TAXONOMY_RAG] ║ Input category: '{category}'")
        if user_specifications:
            logger.info(f"[TAXONOMY_RAG] ║ Input spec fields ({len(user_specifications)}): {list(user_specifications.keys())}")
            logger.info(f"[TAXONOMY_RAG] ║ Input spec values: {json.dumps(user_specifications, default=str)[:500]}")
        else:
            logger.info("[TAXONOMY_RAG] ║ Input spec fields: None")

        # ── RESULT CACHE CHECK ──
        # Deduplicate identical concurrent requests (e.g. duplicate frontend calls)
        _cache_key = f"{category.lower()}|{json.dumps(sorted((user_specifications or {}).items()), default=str)}"
        with _taxonomy_result_cache_lock:
            _cached_entry = _taxonomy_result_cache.get(_cache_key)
            if _cached_entry and time.time() < _cached_entry["expires_at"]:
                logger.info(f"[TAXONOMY_RAG] ║ Cache HIT for '{category}' — skipping LLM call")
                return _cached_entry["result"]

        if not category:
            logger.warning("[TAXONOMY_RAG] ╚══ EARLY RETURN: No category provided ══╝")
            return {
                "found": False,
                "matched_category": category,
                "is_exact_match": False,
                "semantic_match": "NO_MATCH",
                "use_db_name": False,
                "confidence": 0.0,
                "reasoning": "No category provided",
                "spec_field_mappings": [],
                "mapped_specifications": user_specifications or {},
                "error": "No category provided"
            }

        # ── STEP 1: FIND DATABASE PRODUCT TYPE ──
        conn = get_mongodb_connection()
        specs_collection = conn['collections'][Collections.SPECS]

        # P0.4 FIX: Thread-safe cache access to prevent thundering herd
        _now = time.time()
        with _product_types_cache_lock:
            if _now < _product_types_cache["expires_at"]:
                available_types = _product_types_cache["types"]
            else:
                available_types = specs_collection.distinct("product_type")
                available_types = [t for t in available_types if t]
                _product_types_cache["types"] = available_types
                _product_types_cache["expires_at"] = _now + _PRODUCT_TYPES_CACHE_TTL

        logger.info(f"[TAXONOMY_RAG] STEP 1: Found {len(available_types)} product types in database")
        logger.debug(f"[TAXONOMY_RAG] Available types: {available_types[:20]}{'...' if len(available_types) > 20 else ''}")

        if not available_types:
            logger.warning("[TAXONOMY_RAG] ╚══ EARLY RETURN: No product types in specs collection ══╝")
            return {
                "found": False,
                "matched_category": category,
                "is_exact_match": False,
                "semantic_match": "NO_MATCH",
                "use_db_name": False,
                "confidence": 0.0,
                "reasoning": "No product types in database",
                "spec_field_mappings": [],
                "mapped_specifications": user_specifications or {}
            }

        # 1. Exact match (case-insensitive)
        matched_product_type = None
        for db_type in available_types:
            if category.lower() == db_type.lower():
                matched_product_type = db_type
                logger.info(f"[TAXONOMY_RAG] STEP 1: ✓ Exact match found: '{category}' → '{db_type}'")
                break

        # 1.5. Taxonomy Normalization (Alias Map + Fuzzy Matching)
        if not matched_product_type:
            from common.ai.rag.taxonomy_rag import TaxonomyNormalizationAgent
            temp_agent = TaxonomyNormalizationAgent()
            alias_map = temp_agent._get_alias_map()

            resolution = temp_agent._resolve_term(category, "instrument", alias_map)
            if resolution["taxonomy_matched"]:
                matched_product_type = resolution["canonical_name"]
                logger.info(f"[TAXONOMY_RAG] STEP 1: ✓ Taxonomy match found: '{category}' → '{matched_product_type}' (via {resolution['match_source']})")

        if not matched_product_type:
            matched_product_type = category
            logger.info(f"[TAXONOMY_RAG] STEP 1: ✗ No exact, alias, or fuzzy match for '{category}', will rely on LLM")

        # ── DYNAMIC OBJECT-MODEL PARAMETER CONTROL (Phase 6 Opt-In) ──
        if os.getenv("TAXONOMY_USE_MODEL", "false").strip().lower() in ("1", "true", "yes"):
            try:
                from common.infra.repositories.taxonomy_repository import TaxonomyRepository
                tax = TaxonomyRepository.get_full_taxonomy()
                
                # Dynamic Object-Model Controlled Normalization
                normalized_specs = tax.normalize_parameter_keys(matched_product_type, user_specifications or {})
                resolved_cascades = tax.resolve_specifications(matched_product_type)
                
                # Merge resolved cascades (defaults) with user-provided specifications
                final_specs = {**resolved_cascades, **normalized_specs}
                
                # Build enhanced spec field mappings for frontend compatibility
                enhanced_spec_mappings = []
                for user_k, resolved_v in (user_specifications or {}).items():
                    # Find matching key in normalized specs
                    matched_db_key = None
                    for canonical_k, norm_v in normalized_specs.items():
                        if norm_v == resolved_v:
                            matched_db_key = canonical_k
                            break
                    enhanced_spec_mappings.append({
                        "user_field": user_k,
                        "db_field": matched_db_key or user_k,
                        "match_type": "EXACT_MATCH" if matched_db_key == user_k else ("SEMANTIC_MATCH" if matched_db_key else "NO_MATCH"),
                        "confidence": 1.0,
                        "display_name": _friendly_name(matched_db_key or user_k),
                        "field_to_use": matched_db_key or user_k
                    })
                
                result = {
                    "found": True,
                    "matched_category": matched_product_type,
                    "is_exact_match": category.lower() == matched_product_type.lower(),
                    "semantic_match": "EXACT_MATCH" if category.lower() == matched_product_type.lower() else "SAME_MEANING",
                    "use_db_name": True,
                    "confidence": 1.0,
                    "reasoning": "Mapped and validated using active 4-tier taxonomy object model",
                    "spec_field_mappings": enhanced_spec_mappings,
                    "mapped_specifications": final_specs
                }
                
                # Save to cache
                with _taxonomy_result_cache_lock:
                    _taxonomy_result_cache[_cache_key] = {
                        "result": result,
                        "expires_at": time.time() + _TAXONOMY_RESULT_CACHE_TTL
                    }
                
                logger.info(f"[TAXONOMY_RAG] ╚══ SUCCESS: Resolved dynamically via Taxonomy Object Model (0 LLM Calls!) ══╝")
                return result
            except Exception as e:
                logger.warning(f"[TAXONOMY_RAG] Failed to map programmatically via model, falling back to legacy pipeline: {e}")

        # ── STEP 2: GET SCHEMA ──
        db_spec_fields = []
        schema_resolved_via_model = False

        if os.getenv("TAXONOMY_USE_MODEL", "false").strip().lower() in ("1", "true", "yes"):
            try:
                from common.infra.repositories.taxonomy_repository import TaxonomyRepository
                tax = TaxonomyRepository.get_full_taxonomy()
                resolved_specs = tax.resolve_specifications(matched_product_type)
                if resolved_specs:
                    db_spec_fields = list(resolved_specs.keys())
                    schema_resolved_via_model = True
                    logger.info(f"[TAXONOMY_RAG] STEP 2: ✓ Schema resolved dynamically via Taxonomy Model — {len(db_spec_fields)} spec fields: {db_spec_fields[:15]}{'...' if len(db_spec_fields) > 15 else ''}")
            except Exception as e:
                logger.warning(f"[TAXONOMY_RAG] STEP 2: Failed to resolve schema via Taxonomy model: {e}")

        if not schema_resolved_via_model:
            schema_doc = get_schema_from_mongodb(matched_product_type)
            if schema_doc:
                db_spec_fields = _extract_all_spec_fields_from_schema(schema_doc)
                logger.info(f"[TAXONOMY_RAG] STEP 2: ✓ Schema found via MongoDB collection — {len(db_spec_fields)} spec fields: {db_spec_fields[:15]}{'...' if len(db_spec_fields) > 15 else ''}")
            else:
                logger.warning(f"[TAXONOMY_RAG] STEP 2: ✗ No schema found for '{matched_product_type}'")

        # ── STEP 3: LLM MATCHING ──
        if not GOOGLE_API_KEY:
            logger.error("[TAXONOMY_RAG] ╚══ EARLY RETURN: GOOGLE_API_KEY not configured ══╝")
            return {
                "found": False,
                "matched_category": category,
                "is_exact_match": False,
                "semantic_match": "NO_MATCH",
                "use_db_name": False,
                "confidence": 0.0,
                "reasoning": "API Key not configured",
                "spec_field_mappings": [],
                "mapped_specifications": user_specifications or {},
                "error": "API Key not configured"
            }

        user_spec_fields_list = list(user_specifications.keys()) if user_specifications else []

        logger.info(
            f"[TAXONOMY_RAG] STEP 3: Calling LLM — "
            f"user_category='{category}', db_category='{matched_product_type}', "
            f"user_spec_fields={user_spec_fields_list}, "
            f"db_spec_fields_count={len(db_spec_fields)}"
        )

        llm = get_lite_llm(temperature=0.1)
        prompt = ChatPromptTemplate.from_template(TAXONOMY_AND_SPEC_MAPPING_PROMPT)
        chain = prompt | llm | StrOutputParser()

        # P0.3 FIX: Retry LLM call with exponential backoff to handle transient failures
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True
        )
        def _invoke_taxonomy_llm():
            return chain.invoke({
                "user_category": category,
                "user_spec_fields": json.dumps(user_spec_fields_list),
                "db_category": matched_product_type,
                "db_spec_fields": json.dumps(db_spec_fields)
            })

        llm_response = _invoke_taxonomy_llm()

        # Log raw LLM response for debugging
        logger.info(f"[TAXONOMY_RAG] STEP 3: Raw LLM response ({len(llm_response)} chars): {llm_response[:600]}")

        # Clean JSON fences
        cleaned_response = llm_response.strip()
        for prefix in ("```json", "```"):
            if cleaned_response.startswith(prefix):
                cleaned_response = cleaned_response[len(prefix):]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]

        llm_result = json.loads(cleaned_response.strip())

        # ── LOG PARSED LLM RESULT ──
        category_match = llm_result.get("category_match", {})
        spec_mappings = llm_result.get("spec_field_mappings", [])

        logger.info(
            f"[TAXONOMY_RAG] STEP 3: LLM parsed — "
            f"semantic_match={category_match.get('semantic_match')}, "
            f"use_db_category={category_match.get('use_db_category')}, "
            f"confidence={category_match.get('confidence')}, "
            f"reasoning='{category_match.get('reasoning', '')[:100]}'"
        )
        logger.info(f"[TAXONOMY_RAG] STEP 3: LLM returned {len(spec_mappings)} spec field mappings")

        # ── STEP 4: BUILD RESULT ──
        mapped_specs = {}
        enhanced_spec_mappings = []
        mapped_user_fields = set()  # Track which user fields were mapped by LLM

        if user_specifications:
            for mapping in spec_mappings:
                user_field = mapping.get("user_field")
                db_field = mapping.get("db_field")
                match_type = mapping.get("match_type")
                confidence = mapping.get("confidence", 0.0)

                if not user_field:
                    logger.warning(f"[TAXONOMY_RAG] STEP 4: Skipping mapping with no user_field: {mapping}")
                    continue

                user_value = user_specifications.get(user_field, "")
                mapped_user_fields.add(user_field)

                # Determine which field name to use
                if match_type == "SEMANTIC_MATCH" and db_field:
                    field_to_use = db_field
                else:
                    field_to_use = user_field

                mapped_specs[field_to_use] = user_value

                enhanced_mapping = {
                    **mapping,
                    "display_name": _friendly_name(field_to_use),
                    "field_to_use": field_to_use
                }
                enhanced_spec_mappings.append(enhanced_mapping)

                logger.info(
                    f"[TAXONOMY_RAG] STEP 4: Spec mapping: "
                    f"'{user_field}' → '{field_to_use}' "
                    f"(type={match_type}, conf={confidence}, value='{str(user_value)[:60]}')"
                )

            # ── FIX: Preserve user specs that the LLM didn't return mappings for ──
            unmapped_count = 0
            for user_key, user_val in user_specifications.items():
                if user_key not in mapped_user_fields:
                    mapped_specs[user_key] = user_val
                    unmapped_count += 1
                    logger.info(
                        f"[TAXONOMY_RAG] STEP 4: ⚠ Unmapped user field preserved: "
                        f"'{user_key}' = '{str(user_val)[:60]}'"
                    )

            if unmapped_count:
                logger.info(f"[TAXONOMY_RAG] STEP 4: Preserved {unmapped_count} unmapped user fields")

        # ── FINAL OUTPUT LOGGING ──
        result = {
            "found": True,
            "matched_category": matched_product_type,
            "is_exact_match": category.lower() == matched_product_type.lower(),
            "semantic_match": category_match.get("semantic_match", "SAME_MEANING"),
            "use_db_name": category_match.get("use_db_category", True),
            "confidence": category_match.get("confidence", 0.9),
            "reasoning": category_match.get("reasoning", ""),
            "spec_field_mappings": enhanced_spec_mappings,
            "mapped_specifications": mapped_specs
        }

        logger.info(
            f"[TAXONOMY_RAG] ╚══ RESULT ══╝  "
            f"found={result['found']}, "
            f"'{category}' → '{result['matched_category']}', "
            f"exact={result['is_exact_match']}, "
            f"semantic={result['semantic_match']}, "
            f"use_db={result['use_db_name']}, "
            f"conf={result['confidence']}, "
            f"spec_mappings={len(result['spec_field_mappings'])}, "
            f"mapped_specs_keys={list(result['mapped_specifications'].keys())}"
        )

        # ── STORE IN RESULT CACHE ──
        with _taxonomy_result_cache_lock:
            _taxonomy_result_cache[_cache_key] = {
                "result": result,
                "expires_at": time.time() + _TAXONOMY_RESULT_CACHE_TTL
            }

        return result

    except json.JSONDecodeError as e:
        logger.exception(f"[TAXONOMY_RAG] ✗ Failed to parse LLM response: {e}")
        return {
            "found": False,
            "matched_category": category,
            "is_exact_match": False,
            "semantic_match": "NO_MATCH",
            "use_db_name": False,
            "confidence": 0.0,
            "reasoning": "Failed to parse LLM response",
            "spec_field_mappings": [],
            "mapped_specifications": user_specifications or {},
            "error": "Failed to parse LLM response"
        }
    except Exception as e:
        logger.exception(f"[TAXONOMY_RAG] ✗ get_taxonomy_for_category failed: {e}")
        return {
            "found": False,
            "matched_category": category,
            "is_exact_match": False,
            "semantic_match": "NO_MATCH",
            "use_db_name": False,
            "confidence": 0.0,
            "reasoning": str(e),
            "spec_field_mappings": [],
            "mapped_specifications": user_specifications or {},
            "error": str(e)
        }


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_taxonomy_rag_health():
    """
    Health check for Taxonomy RAG Module
    Tests: LLM, MongoDB (taxonomy), GridFS, prompt file, embedding manager

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

        # 2. Test MongoDB taxonomy collection
        dependencies["mongodb_taxonomy"] = checker.check_mongodb_collection("taxonomy")
        if dependencies["mongodb_taxonomy"].status == "unavailable":
            status = "unhealthy"

        # 3. Test GridFS availability (for PDF storage)
        try:
            from common.infra.mongodb_config import get_mongodb_connection
            conn = get_mongodb_connection()
            if conn and 'gridfs' in conn:
                dependencies["gridfs"] = DependencyStatus("gridfs", "available")
            else:
                dependencies["gridfs"] = DependencyStatus("gridfs", "unavailable", "GridFS not configured")
                if status == "healthy":
                    status = "degraded"
        except Exception as e:
            dependencies["gridfs"] = DependencyStatus("gridfs", "unavailable", str(e))
            if status == "healthy":
                status = "degraded"

        # 4. Test embedding manager (for semantic matching)
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

        # 5. Test prompt file (DISABLED - legacy prompt file removed)
        # try:
        #     prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "taxonomy_rag_prompt.md")
        #     dep_status = checker.check_prompt_file(prompt_path)
        #     dependencies["prompt_taxonomy_rag"] = dep_status
        #     if dep_status.status == "unavailable":
        #         status = "unhealthy"
        # except Exception as e:
        #     dependencies["prompt_taxonomy_rag"] = DependencyStatus("prompt_taxonomy_rag", "unavailable", str(e))
        #     status = "unhealthy"

    except Exception as e:
        status = "unhealthy"
        error_msg = f"Health check failed: {str(e)}"
        logger.error(f"[RAG_HEALTH] Taxonomy RAG health check error: {str(e)}")

    return AgentHealthStatus(
        agent_name="taxonomy_rag",
        status=status,
        dependencies=dependencies,
        metrics=None,
        last_check=datetime.now(),
        error_message=error_msg
    )

