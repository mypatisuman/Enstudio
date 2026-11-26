"""Structured Pydantic models for procurement strategies and vendor analysis."""

import logging
from typing import Any, Iterator
from pydantic import Field, model_validator

from common.models.base import LenientModel, MongoModel

logger = logging.getLogger(__name__)


class StrategyEntry(LenientModel):
    """Pydantic model representing a single procurement strategy row/entry in the database."""

    vendor_name: str = ""
    category: str = ""
    subcategory: str = ""
    strategy: str = Field(default="", alias="stratergy")
    notes: str = ""
    strategy_priority: str = ""

    vendor_name_embedding: list[float] | None = None
    category_embedding: list[float] | None = None
    subcategory_embedding: list[float] | None = None
    strategy_embedding: list[float] | None = Field(default=None, alias="stratergy_embedding")

    @model_validator(mode="before")
    @classmethod
    def _map_aliases(cls, data: Any) -> Any:
        """Dynamically map all column variations and aliases to standardized Pydantic fields."""
        if not isinstance(data, dict):
            return data
        
        # Standardize keys by replacing spaces and hyphens with underscores
        clean_data = {}
        for k, v in data.items():
            safe_key = str(k).strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")
            clean_data[safe_key] = v

        # Helper to find first matching key and its embedding from possible column variations
        def get_val_and_emb(possible_keys, target_field, data_dict):
            for k in possible_keys:
                safe_k = k.replace(" ", "_").replace("-", "_").replace(".", "_")
                if safe_k in data_dict:
                    val = str(data_dict.get(safe_k, "")).strip()
                    if val:
                        data_dict[target_field] = val
                        emb_key = f"{safe_k}_embedding"
                        if emb_key in data_dict:
                            data_dict[f"{target_field}_embedding"] = data_dict[emb_key]
                        break

        # Map vendor name variations
        get_val_and_emb(['vendor_name', 'vendor', 'manufacturer', 'supplier', 'vendor name'], 'vendor_name', clean_data)
        # Map category variations
        get_val_and_emb(['category', 'product_category', 'product_type', 'product category'], 'category', clean_data)
        # Map subcategory variations
        get_val_and_emb(['subcategory', 'sub_category', 'sub category'], 'subcategory', clean_data)
        # Map strategy variations
        get_val_and_emb(['strategy', 'stratergy', 'procurement_strategy', 'procurement strategy'], 'strategy', clean_data)
        # Map notes variations
        get_val_and_emb(['notes', 'note', 'comment', 'comments'], 'notes', clean_data)

        # Standardize strategy keys for Cosmos DB compatibility
        if "strategy" in clean_data and "stratergy" not in clean_data:
            clean_data["stratergy"] = clean_data["strategy"]
            if "strategy_embedding" in clean_data:
                clean_data["stratergy_embedding"] = clean_data["strategy_embedding"]

        return clean_data


class StandardStorage(LenientModel):
    """Pydantic model representing blob storage configuration for strategy files."""

    storage: str = "azure_blob"
    blobUrl: str | None = None
    embeddingsBlobUrl: str | None = None
    cachedEmbeddingsSasUrl: str | None = None
    embeddingsSasUrlExpiry: str | None = None
    cachedSasUrl: str | None = None
    sasUrlExpiry: str | None = None
    container: str = "strategy-documents"
    blobName: str | None = None


class StrategyDocument(MongoModel):
    """Pydantic model representing a strategy document in the database."""

    user_id: int | str
    filename: str
    uploaded_at: str = ""
    entry_count: int = 0
    extraction_method: str = "upload_time_embeddings"
    csv_columns: list[str] = Field(default_factory=list)
    storage: StandardStorage | None = None
    status: str = "ready"
    error_message: str | None = None
    data: list[StrategyEntry] = Field(default_factory=list)


class StrategyCatalog(LenientModel):
    """Catalog holding a collection of strategy documents, equipped with vector cosine similarity searching."""

    documents: list[StrategyDocument] = Field(default_factory=list)

    def search_entries(
        self,
        input_vendor_embedding: list[float] | None = None,
        input_category_embedding: list[float] | None = None,
        input_subcategory_embedding: list[float] | None = None,
        input_strategy_embedding: list[float] | None = None,
        detected_vendors: list[str] | None = None,
        detected_categories: list[str] | None = None,
        detected_subcategories: list[str] | None = None,
        detected_strategy_keywords: list[str] | None = None,
        general_keywords: list[str] | None = None,
        category_filter: str | None = None,
        min_score: float = 0.3,
        top_k: int = 10,
        use_structured_input: bool = False
    ) -> list[dict[str, Any]]:
        """Search and score strategy entries using embedding similarity."""
        from common.ai.embedding_manager import cosine_similarity

        detected_vendors = detected_vendors or []
        detected_categories = detected_categories or []
        detected_subcategories = detected_subcategories or []
        detected_strategy_keywords = detected_strategy_keywords or []
        general_keywords = general_keywords or []

        results = []
        seen_vendors = set()

        for doc in self.documents:
            for entry in doc.data:
                vendor_name = entry.vendor_name
                category = entry.category
                subcategory = entry.subcategory
                strategy_text = entry.strategy

                if not vendor_name:
                    continue

                # Deduplication key
                vendor_key = f"{vendor_name.lower()}:{category.lower()}"
                if vendor_key in seen_vendors:
                    continue

                # Apply category filter
                if category_filter:
                    cat_lower = category.lower()
                    sub_lower = subcategory.lower()
                    filter_lower = category_filter.lower()
                    if filter_lower not in cat_lower and filter_lower not in sub_lower:
                        continue

                # Cosine similarity scoring
                vendor_similarity = None
                max_category_similarity = None
                subcategory_similarity = None
                strategy_similarity = None

                score = 0.0
                reasons = []

                # 1. Vendor Match (50% weight)
                if input_vendor_embedding and entry.vendor_name_embedding:
                    vendor_similarity = cosine_similarity(input_vendor_embedding, entry.vendor_name_embedding)
                    if vendor_similarity >= 0.75:
                        vendor_score = (vendor_similarity - 0.75) / 0.25 * 0.5
                        score += vendor_score
                        reasons.append(f"Vendor match: '{vendor_name}' (similarity: {vendor_similarity:.2f})")

                # 2. Category Match (30% weight)
                max_category_similarity = 0.0
                if input_category_embedding and entry.category_embedding:
                    category_similarity = cosine_similarity(input_category_embedding, entry.category_embedding)
                    max_category_similarity = max(max_category_similarity, category_similarity)

                if input_category_embedding and entry.subcategory_embedding:
                    cat_subcat_similarity = cosine_similarity(input_category_embedding, entry.subcategory_embedding)
                    max_category_similarity = max(max_category_similarity, cat_subcat_similarity)

                if max_category_similarity >= 0.75:
                    category_score = (max_category_similarity - 0.75) / 0.25 * 0.3
                    score += category_score
                    reasons.append(f"Category match: '{category}' (similarity: {max_category_similarity:.2f})")

                # 3. Subcategory Match (5% weight)
                if input_subcategory_embedding and entry.subcategory_embedding:
                    subcategory_similarity = cosine_similarity(input_subcategory_embedding, entry.subcategory_embedding)
                    if subcategory_similarity >= 0.75:
                        subcategory_score = (subcategory_similarity - 0.75) / 0.25 * 0.05
                        score += subcategory_score
                        reasons.append(f"Subcategory match: '{subcategory}' (similarity: {subcategory_similarity:.2f})")

                # 4. Strategy Match (15% weight)
                if input_strategy_embedding and entry.strategy_embedding:
                    strategy_similarity = cosine_similarity(input_strategy_embedding, entry.strategy_embedding)
                    if strategy_similarity >= 0.70:
                        strategy_score = (strategy_similarity - 0.70) / 0.30 * 0.15
                        score += strategy_score
                        reasons.append(f"Strategy match (similarity: {strategy_similarity:.2f})")

                # 5. General Keywords Match (5% weight fallback for text queries)
                if not use_structured_input and general_keywords:
                    text_to_search = f"{category} {subcategory} {strategy_text}".lower()
                    matched_general_kws = [kw for kw in general_keywords if kw.lower() in text_to_search]
                    if matched_general_kws:
                        keyword_boost = len(matched_general_kws) * 0.02
                        score += min(0.05, keyword_boost)
                        reasons.append(f"General keywords: {', '.join(matched_general_kws[:5])}")

                # Secondary normalization if vendor isn't provided
                if not input_vendor_embedding:
                    norm_weights = 0.0
                    norm_score = 0.0

                    if input_category_embedding and max_category_similarity is not None:
                        norm_weights += 1.0
                        norm_score += max_category_similarity

                    if input_subcategory_embedding and subcategory_similarity is not None:
                        norm_weights += 1.0
                        norm_score += subcategory_similarity

                    if input_strategy_embedding and strategy_similarity is not None:
                        norm_weights += 1.0
                        norm_score += strategy_similarity

                    if norm_weights > 0:
                        avg_sim = norm_score / norm_weights
                        score = max(score, (avg_sim - 0.5) / 0.5)

                if score >= min_score:
                    seen_vendors.add(vendor_key)
                    results.append({
                        "vendor_name": vendor_name,
                        "category": category,
                        "subcategory": subcategory,
                        "stratergy": strategy_text,
                        "similarity_score": round(score, 2),
                        "match_reason": "; ".join(reasons),
                        "source": "strategy_rag_embeddings"
                    })

        # Sort and return top results
        results.sort(key=lambda x: x['similarity_score'], reverse=True)
        return results[:top_k]
