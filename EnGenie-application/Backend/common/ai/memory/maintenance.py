"""
Active periodic maintenance for in-process (L1) session memory.

Complements the reactive, cap-triggered LRU eviction already in core.py/search.py
with an idle-based sweep that runs on a schedule (wired via APScheduler in
main.py). Each process instance sweeps only its own in-memory state — there is
no cross-instance coordination here by design: L1 stores are plain per-process
Python dicts, not shared across worker instances, so a per-instance sweep is
correct and sufficient. MongoDB TTL indexes (wired separately in
mongodb_config.py) are the instance-agnostic layer for the shared L2 store.
"""
import logging
import os

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = int(os.environ.get("MEMORY_SWEEP_INTERVAL_SECONDS", str(30 * 60)))  # 30 min default


def run_memory_sweep() -> dict[str, int]:
    """Single sweep pass across all L1 in-memory stores + bounded caches.

    Safe to call repeatedly (e.g. from an APScheduler interval job). Each
    store's sweep is independently try/excepted so one failure doesn't block
    the others. Returns counts evicted per store.
    """
    results: dict[str, int] = {}

    try:
        from common.ai.memory.core import sweep_idle_sessions
        results["conversation_sessions"] = sweep_idle_sessions()
    except Exception as e:
        logger.error(f"[MEMORY_SWEEP] core sweep failed: {e}")
        results["conversation_sessions"] = -1

    try:
        from common.ai.memory.search import sweep_idle_search_sessions
        results["search_sessions"] = sweep_idle_search_sessions()
    except Exception as e:
        logger.error(f"[MEMORY_SWEEP] search sweep failed: {e}")
        results["search_sessions"] = -1

    try:
        from domain.search.services.schema_field_matching import evict_stale_embedding_cache
        results["embedding_cache_evicted"] = evict_stale_embedding_cache()
    except Exception as e:
        logger.error(f"[MEMORY_SWEEP] embedding cache eviction failed: {e}")
        results["embedding_cache_evicted"] = -1

    try:
        # Lazy-imported: app.api.v1.search is a FastAPI router module that pulls
        # in many app-layer dependencies; importing it at maintenance.py's
        # module level risks import-order issues at startup.
        from app.api.v1.search import evict_stale_field_desc_cache
        results["field_desc_cache_evicted"] = evict_stale_field_desc_cache()
    except Exception as e:
        logger.error(f"[MEMORY_SWEEP] field description cache eviction failed: {e}")
        results["field_desc_cache_evicted"] = -1

    logger.info(f"[MEMORY_SWEEP] Sweep complete: {results}")
    return results
