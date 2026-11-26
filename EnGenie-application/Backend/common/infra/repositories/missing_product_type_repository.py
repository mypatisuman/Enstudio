"""Active MongoDB repository for the `missing_product_types` tracking collection.

Audit queue + circuit breaker for the search agent's auto-indexing pipelines
(PDF schema indexer / category scraper). Every product type a user searched
for that had no schema, no vendor products, or no datasheet PDFs is recorded
here idempotently, keyed on a normalized name, so that:
  - repeated misses increment a counter instead of duplicating rows,
  - background/admin tooling can drain the queue by popularity, and
  - a `failed` status + cooldown prevents re-running the full web+LLM
    pipeline on every repeated search of an unindexable type.
"""

import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from common.infra.mongodb_config import get_mongodb_connection

logger = logging.getLogger(__name__)

MISSING_PRODUCT_TYPES_COLLECTION = "missing_product_types"

# Statuses a tracking record moves through.
STATUS_PENDING = "pending_indexing"
STATUS_INDEXED = "indexed"
STATUS_FAILED = "failed"

# A reason is "generic" when the caller didn't diagnose anything specific.
# Generic reasons never overwrite an earlier, more specific not_found_reason.
DEFAULT_REASON = "not_found"

# After a failed indexing attempt, suppress re-triggering for this long.
FAILED_COOLDOWN_HOURS = 24

# Per-product-type locks so concurrent requests don't run duplicate
# indexing pipelines (process-local; DB double-checks handle multi-process).
_type_locks: dict[str, threading.Lock] = {}
_type_locks_guard = threading.Lock()


def _get_collection():
    """Get the missing_product_types collection from MongoDB."""
    conn = get_mongodb_connection()
    return conn["database"][MISSING_PRODUCT_TYPES_COLLECTION]


class MissingProductTypeRepository:
    """Idempotent tracking of product types the database could not serve."""

    @staticmethod
    def normalize_name(product_type: str) -> str:
        """Normalized dedupe key: lowercase with spaces/underscores stripped,
        so 'Flow_Meter', 'flow meter' and 'FlowMeter' collapse to one record."""
        return re.sub(r"[\s_]+", "", str(product_type or "").lower().strip())

    @staticmethod
    def get_indexing_lock(product_type: str) -> threading.Lock:
        """Per-product-type lock guarding an indexing pipeline run."""
        key = MissingProductTypeRepository.normalize_name(product_type)
        with _type_locks_guard:
            return _type_locks.setdefault(key, threading.Lock())

    @staticmethod
    def record_missing_product_type(product_type: str, reason: str = DEFAULT_REASON,
                                    user_query: str | None = None,
                                    details: dict[str, Any] | None = None) -> bool:
        """Idempotently record (or refresh) a miss for auditing.

        $setOnInsert first_searched_at + status pending_indexing; $set
        last_searched_at (+ reason/details when specific); $inc search_count;
        $addToSet sample_queries. A generic `reason` is only written on insert
        so it never clobbers an earlier, more specific diagnosis.
        """
        normalized = MissingProductTypeRepository.normalize_name(product_type)
        if not normalized:
            return False
        try:
            now = datetime.now(UTC)
            update: dict[str, Any] = {
                "$setOnInsert": {
                    "product_type": str(product_type).strip(),
                    "first_searched_at": now,
                    "status": STATUS_PENDING,
                },
                "$set": {"last_searched_at": now},
                "$inc": {"search_count": 1},
            }
            if reason and reason != DEFAULT_REASON:
                update["$set"]["not_found_reason"] = reason
            else:
                update["$setOnInsert"]["not_found_reason"] = reason or DEFAULT_REASON
            if details:
                update["$set"]["diagnostic_details"] = details
            if user_query and str(user_query).strip():
                update["$addToSet"] = {"sample_queries": str(user_query).strip()[:500]}

            _get_collection().update_one({"normalized_name": normalized}, update, upsert=True)
            logger.info(f"[MissingProductTypeRepo] Recorded miss for '{product_type}' (reason: {reason})")
            return True
        except Exception as e:
            logger.error(f"[MissingProductTypeRepo] Failed to record miss for '{product_type}': {e}")
            return False

    @staticmethod
    def get_record(product_type: str) -> dict[str, Any] | None:
        """The tracking record for a product type, or None."""
        try:
            return _get_collection().find_one(
                {"normalized_name": MissingProductTypeRepository.normalize_name(product_type)})
        except Exception as e:
            logger.error(f"[MissingProductTypeRepo] Lookup failed for '{product_type}': {e}")
            return None

    @staticmethod
    def get_pending_product_types(limit: int = 20) -> list[dict[str, Any]]:
        """Pending entries, most-searched first (the drain order for tooling)."""
        try:
            cursor = (_get_collection()
                      .find({"status": STATUS_PENDING})
                      .sort("search_count", -1)
                      .limit(int(limit)))
            return list(cursor)
        except Exception as e:
            logger.error(f"[MissingProductTypeRepo] Failed to list pending types: {e}")
            return []

    @staticmethod
    def mark_product_type_status(product_type: str, status: str,
                                 error_message: str | None = None) -> bool:
        """Set `indexed` / `failed` (+ processed_at, and the error when failed)."""
        normalized = MissingProductTypeRepository.normalize_name(product_type)
        if not normalized:
            return False
        try:
            update: dict[str, Any] = {"$set": {
                "status": status,
                "processed_at": datetime.now(UTC),
            }}
            if error_message:
                update["$set"]["error_message"] = str(error_message)[:1000]
            else:
                update["$unset"] = {"error_message": ""}
            result = _get_collection().update_one({"normalized_name": normalized}, update)
            logger.info(f"[MissingProductTypeRepo] Marked '{product_type}' as '{status}'")
            return result.matched_count > 0
        except Exception as e:
            logger.error(f"[MissingProductTypeRepo] Failed to mark '{product_type}' as '{status}': {e}")
            return False

    @staticmethod
    def is_in_failed_cooldown(product_type: str,
                              cooldown_hours: int = FAILED_COOLDOWN_HOURS) -> bool:
        """Circuit breaker: True when the last indexing attempt failed within
        the cooldown window — callers must skip re-indexing and return their
        normal not-found behavior instead of re-running the web+LLM pipeline.

        Fails open (False) on DB errors: the pipelines themselves are
        best-effort and fully wrapped, so an unreachable tracking collection
        should not block a legitimate indexing attempt.
        """
        try:
            record = MissingProductTypeRepository.get_record(product_type)
            if not record or record.get("status") != STATUS_FAILED:
                return False
            processed_at = record.get("processed_at")
            if not isinstance(processed_at, datetime):
                return False
            if processed_at.tzinfo is None:
                processed_at = processed_at.replace(tzinfo=UTC)
            in_cooldown = datetime.now(UTC) - processed_at < timedelta(hours=cooldown_hours)
            if in_cooldown:
                logger.info(
                    f"[MissingProductTypeRepo] '{product_type}' failed indexing at "
                    f"{processed_at.isoformat()} — inside {cooldown_hours}h cooldown, skipping re-index"
                )
            return in_cooldown
        except Exception as e:
            logger.error(f"[MissingProductTypeRepo] Cooldown check failed for '{product_type}': {e}")
            return False
