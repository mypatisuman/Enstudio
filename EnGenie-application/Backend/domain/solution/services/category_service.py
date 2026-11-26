import logging
import os
import threading
from common.helpers.notifications import notify_failure as _notify_failure
import time

from common.infra.mongodb_config import Collections, get_mongodb_connection

logger = logging.getLogger(__name__)



_valid_categories_cache: list[str] | None = None
_valid_categories_ts: float = 0.0
_VALID_CAT_TTL = 300  # 5 minutes

def _load_valid_categories_from_tier() -> list[str]:
    """5-tier source: L1 product types + L2 sub-categories from the catalog hierarchy."""
    from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository as _RR
    return sorted({n["name"] for n in (_RR.get_by_level("L1") + _RR.get_by_level("L2")) if n.get("name")})


def _load_valid_categories_from_specs() -> list[str]:
    """Legacy fallback: distinct product_type from the specs collection."""
    conn = get_mongodb_connection()
    return sorted(conn['collections'][Collections.SPECS].distinct("product_type"))


def _get_valid_categories_list() -> list[str]:
    """Canonical product-type names as a list.

    Primary source = the 5-tier hierarchy (catalog_hierarchy L1/L2); falls back to the
    legacy specs collection if the 5-tier is empty/unavailable. Cached (5-min TTL).
    """
    global _valid_categories_cache, _valid_categories_ts
    now = time.monotonic()
    if _valid_categories_cache is not None and (now - _valid_categories_ts) < _VALID_CAT_TTL:
        return _valid_categories_cache
    try:
        cats = _load_valid_categories_from_tier()
        src = "5-tier hierarchy"
        if not cats:
            cats, src = _load_valid_categories_from_specs(), "specs DB (fallback: 5-tier empty)"
        _valid_categories_cache = cats
        _valid_categories_ts = now
        logger.info(f"[CATEGORY_SERVICE] Loaded {len(cats)} valid categories from {src}")
    except Exception as e:
        logger.warning(f"[CATEGORY_SERVICE] 5-tier load failed ({e}); trying specs DB fallback")
        try:
            _valid_categories_cache = _load_valid_categories_from_specs()
            _valid_categories_ts = now
        except Exception as e2:
            logger.warning(f"[CATEGORY_SERVICE] Could not load valid categories: {e2}")
            if _valid_categories_cache is None:
                _valid_categories_cache = []
    return _valid_categories_cache


def _get_valid_categories() -> str:
    """Newline '- name' list of ALL canonical product types.

    (Historic version joined with a literal backslash-n string; now real newlines.)
    """
    return "\n".join(f"- {c}" for c in _get_valid_categories_list())


_category_embeddings_cache: tuple[list[str], object] | None = None  # (cats, unit-norm matrix)
_category_emb_lock = threading.Lock()


def get_relevant_categories(query: str, top_k: int | None = None) -> str:
    """Newline '- name' list of the categories most relevant to *query*.

    Embedding-shortlists the full L1+L2 list (~460 names, ~2.5-3K prompt tokens
    when injected whole) down to HOLISTIC_CATEGORY_SHORTLIST entries (default
    80; 0 disables shortlisting). Falls back to the full list on any embedding
    failure. Safe because the list is 'match or fit' guidance for product_name —
    downstream hierarchy matching validates against the real catalog and already
    fuzzy-handles names outside this list.
    """
    global _category_embeddings_cache
    if top_k is None:
        try:
            top_k = int(os.getenv("HOLISTIC_CATEGORY_SHORTLIST", "80"))
        except ValueError:
            top_k = 80
    cats = _get_valid_categories_list()
    if top_k <= 0 or len(cats) <= top_k or not (query or "").strip():
        return "\n".join(f"- {c}" for c in cats)
    try:
        import numpy as np
        from common.ai.embedding_manager import generate_embedding, generate_embeddings_batch

        with _category_emb_lock:
            if _category_embeddings_cache is None or _category_embeddings_cache[0] != cats:
                embs = generate_embeddings_batch(cats)
                if not embs or any(e is None for e in embs):
                    raise ValueError("category embedding batch incomplete")
                matrix = np.asarray(embs, dtype="float32")
                matrix /= (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
                _category_embeddings_cache = (list(cats), matrix)
            cached_cats, matrix = _category_embeddings_cache

        q = generate_embedding((query or "")[:2000])
        if q is None:
            raise ValueError("query embedding unavailable")
        qv = np.asarray(q, dtype="float32")
        qv /= (np.linalg.norm(qv) + 1e-9)
        top_idx = np.argsort(-(matrix @ qv))[:top_k]
        keep = sorted(cached_cats[i] for i in top_idx)
        logger.info(f"[CATEGORY_SERVICE] Shortlisted {len(keep)}/{len(cached_cats)} categories for holistic prompt")
        return "\n".join(f"- {c}" for c in keep)
    except Exception as e:
        logger.warning(f"[CATEGORY_SERVICE] Category shortlist failed ({e}); using full list")
        return "\n".join(f"- {c}" for c in cats)
