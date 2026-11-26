"""
Database Migration and Field Convergence Service
"""
import logging
from common.infra.mongodb_config import Collections, get_mongodb_connection

logger = logging.getLogger("migration_service")


def converge_vendors(coll, apply: bool) -> int:
    """Copy vendor_name -> vendor where vendor missing/empty."""
    q = {
        "vendor_name": {"$exists": True},
        "$or": [{"vendor": {"$exists": False}}, {"vendor": ""}, {"vendor": None}],
    }
    affected = 0
    for doc in coll.find(q, {"vendor_name": 1}):
        affected += 1
        if apply:
            coll.update_one({"_id": doc["_id"]}, {"$set": {"vendor": doc.get("vendor_name", "")}})
    logger.info(
        "[vendors] %s %d doc(s): vendor_name -> vendor",
        "updated" if apply else "would update",
        affected,
    )
    return affected


def converge_strategy(coll, apply: bool) -> int:
    """Within each strategy doc's data[] array, copy stratergy -> strategy where strategy missing."""
    affected = 0
    for doc in coll.find({"data": {"$exists": True}}, {"data": 1}):
        data = doc.get("data") or []
        if not isinstance(data, list):
            continue
        changed = False
        for entry in data:
            if isinstance(entry, dict) and entry.get("stratergy") and not entry.get("strategy"):
                entry["strategy"] = entry["stratergy"]
                changed = True
        if changed:
            affected += 1
            if apply:
                coll.update_one({"_id": doc["_id"]}, {"$set": {"data": data}})
    logger.info(
        "[stratergy] %s %d doc(s): data[].stratergy -> data[].strategy",
        "updated" if apply else "would update",
        affected,
    )
    return affected


def run_field_backfill(apply: bool = False) -> dict:
    """Run all field backfill conversions and return execution metrics."""
    logger.info("Starting field name backfill/convergence (apply=%s)", apply)
    try:
        conn = get_mongodb_connection()
        collections = conn["collections"]
        db = conn["database"]

        vendors_affected = converge_vendors(collections["vendors"], apply)
        strategy_affected = converge_strategy(collections[Collections.STRATERGY], apply)

        return {
            "success": True,
            "apply": apply,
            "vendors_affected": vendors_affected,
            "strategy_affected": strategy_affected,
            "total_affected": vendors_affected + strategy_affected,
            "message": "Field backfill migration completed successfully."
        }
    except Exception as e:
        logger.exception("Error running field backfill migration: %s", e)
        return {
            "success": False,
            "error": str(e),
            "message": "Field backfill migration failed."
        }
