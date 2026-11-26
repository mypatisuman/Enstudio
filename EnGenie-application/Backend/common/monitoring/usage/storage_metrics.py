"""
Storage Utilization Metrics Module
Tracks MongoDB database size, collection sizes, and storage growth
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)


class StorageMetrics:
    """Manages storage utilization metrics tracking"""

    def __init__(self):
        self.collection_name = "storage_metrics"
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Ensure TTL index exists for automatic data expiration (7 days)"""
        try:
            collection = mongodb_manager.get_collection(self.collection_name)
            
            # Check for existing TTL indexes on 'timestamp'
            existing_indexes = collection.index_information()
            
            # The logs showed a conflict with 'timestamp_ttl_90d'
            # We drop it if it exists to apply our new 7-day policy
            for index_name, index_info in existing_indexes.items():
                if "key" in index_info and index_info["key"][0][0] == "timestamp" and "expireAfterSeconds" in index_info:
                    if index_info.get("expireAfterSeconds") != 604800:
                        logger.info(f"[STORAGE] Dropping old TTL index '{index_name}' to update to 7 days")
                        collection.drop_index(index_name)
            
            # Create the new 7-day index
            collection.create_index("timestamp", expireAfterSeconds=604800, name="timestamp_ttl_7d")
            logger.info("[STORAGE] TTL index (7 days) verified")
        except Exception as e:
            logger.warning(f"[STORAGE] Failed to manage TTL index: {e}")

    def capture_storage_snapshot(self) -> bool:
        """
        Capture current storage snapshot and save to MongoDB

        Returns:
            bool: True if snapshot captured successfully
        """
        try:
            db = mongodb_manager.database

            # Get database stats
            db_stats = db.command("dbStats")

            # Get collection stats (bounded to 3s per collection to avoid CosmosDB socket hangs)
            collection_stats = []
            for coll_name in db.list_collection_names():
                try:
                    coll_stats = db.command("collStats", coll_name, maxTimeMS=3000)
                    collection_stats.append({
                        "name": coll_name,
                        "size_bytes": coll_stats.get("size", 0),
                        "size_mb": round(coll_stats.get("size", 0) / (1024 * 1024), 2),
                        "document_count": coll_stats.get("count", 0),
                        "index_count": coll_stats.get("nindexes", 0),
                        "index_size_bytes": coll_stats.get("totalIndexSize", 0),
                        "index_size_mb": round(coll_stats.get("totalIndexSize", 0) / (1024 * 1024), 2),
                        "storage_size_bytes": coll_stats.get("storageSize", 0),
                        "storage_size_mb": round(coll_stats.get("storageSize", 0) / (1024 * 1024), 2)
                    })
                except Exception as coll_error:
                    logger.debug(f"[STORAGE] Could not get stats for collection {coll_name}: {coll_error}")

            # Prepare snapshot
            snapshot = {
                "timestamp": datetime.now(UTC),
                "database": {
                    "name": db.name,
                    "size_bytes": db_stats.get("dataSize", 0),
                    "size_mb": round(db_stats.get("dataSize", 0) / (1024 * 1024), 2),
                    "size_gb": round(db_stats.get("dataSize", 0) / (1024 * 1024 * 1024), 2),
                    "storage_size_bytes": db_stats.get("storageSize", 0),
                    "storage_size_mb": round(db_stats.get("storageSize", 0) / (1024 * 1024), 2),
                    "index_size_bytes": db_stats.get("indexSize", 0),
                    "index_size_mb": round(db_stats.get("indexSize", 0) / (1024 * 1024), 2),
                    "collection_count": db_stats.get("collections", 0),
                    "document_count": db_stats.get("objects", 0)
                },
                "collections": collection_stats
            }

            # Save snapshot
            collection = mongodb_manager.get_collection(self.collection_name)
            collection.insert_one(snapshot)

            logger.info(
                f"[STORAGE] Captured storage snapshot - "
                f"DB Size: {snapshot['database']['size_mb']:.2f} MB, "
                f"Collections: {len(collection_stats)}"
            )
            return True

        except Exception as e:
            logger.error(f"[STORAGE] Failed to capture storage snapshot: {str(e)}")
            return False

    def get_current_storage(self, force_refresh: bool = False) -> dict[str, Any]:
        """
        Get current storage metrics. 
        Tries to return the latest snapshot from the last 4 hours first.
        
        Args:
            force_refresh: If True, perform a live scan regardless of cached snapshots
        """
        try:
            # 1. Check for a recent snapshot first (unless force_refresh is True)
            if not force_refresh:
                collection = mongodb_manager.get_collection(self.collection_name)
                four_hours_ago = datetime.now(UTC) - timedelta(hours=4)
                
                latest_snapshot = collection.find_one(
                    {"timestamp": {"$gte": four_hours_ago}},
                    sort=[("timestamp", -1)]
                )
                
                if latest_snapshot:
                    logger.info(f"[STORAGE] Returning FAST cached snapshot from {latest_snapshot.get('timestamp')}")
                    if "_id" in latest_snapshot:
                        del latest_snapshot["_id"]
                    if "timestamp" in latest_snapshot and isinstance(latest_snapshot["timestamp"], datetime):
                        latest_snapshot["timestamp"] = latest_snapshot["timestamp"].isoformat()
                    
                    # Ensure blob_storage exists in snapshot (backwards compatibility)
                    if "blob_storage" not in latest_snapshot and "database" in latest_snapshot:
                        latest_snapshot["blob_storage"] = self.get_blob_storage_metrics()
                    
                    latest_snapshot["is_cached"] = True
                    return latest_snapshot
                else:
                    logger.info("[STORAGE] No recent snapshot found, falling back to LIVE scan")

            # 2. Fallback to Live Scan (Slow)
            logger.info("[STORAGE] Performing LIVE storage scan (Azure Blobs + MongoDB)...")
            db = mongodb_manager.database
            db_stats = db.command("dbStats")

            # Get collection stats
            collection_stats = []
            for coll_name in db.list_collection_names():
                try:
                    coll_stats = db.command("collStats", coll_name)
                    collection_stats.append({
                        "name": coll_name,
                        "size_mb": round(coll_stats.get("size", 0) / (1024 * 1024), 2),
                        "document_count": coll_stats.get("count", 0),
                        "index_size_mb": round(coll_stats.get("totalIndexSize", 0) / (1024 * 1024), 2)
                    })
                except:
                    pass

            # Sort by size (largest first)
            collection_stats.sort(key=lambda x: x.get("size_mb", 0), reverse=True)

            # Get Azure Blob metrics
            blob_metrics = self.get_blob_storage_metrics()

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "database": {
                    "name": db.name,
                    "size_mb": round(db_stats.get("dataSize", 0) / (1024 * 1024), 2),
                    "size_gb": round(db_stats.get("dataSize", 0) / (1024 * 1024 * 1024), 2),
                    "storage_size_mb": round(db_stats.get("storageSize", 0) / (1024 * 1024), 2),
                    "index_size_mb": round(db_stats.get("indexSize", 0) / (1024 * 1024), 2),
                    "collection_count": db_stats.get("collections", 0),
                    "document_count": db_stats.get("objects", 0)
                },
                "blob_storage": blob_metrics,
                "collections": collection_stats,
                "is_cached": False
            }

        except Exception as e:
            logger.error(f"[STORAGE] Failed to get current storage: {str(e)}")
            return {"error": str(e)}

    def get_blob_storage_metrics(self) -> dict[str, Any]:
        """Get Azure Blob Storage metrics (size and counts)"""
        try:
            from common.infra.azure_blob import azure_blob_manager
            client = azure_blob_manager.blob_service_client
            if not client:
                return {"size_mb": 0, "size_gb": 0, "container_count": 0, "blob_count": 0}

            containers = list(client.list_containers())
            total_size_bytes = 0
            total_blobs = 0

            for c in containers:
                try:
                    container_client = client.get_container_client(c.name)
                    # Optimize by using paginated loops to avoid iterator hanging/memory spikes
                    for page in container_client.list_blobs().by_page():
                        page_blobs = list(page)
                        total_blobs += len(page_blobs)
                        total_size_bytes += sum(b.size for b in page_blobs if getattr(b, 'size', None))
                except Exception as ce:
                    logger.warning(f"[STORAGE] Failed to get metrics for container {c.name}: {str(ce)}")

            return {
                "size_mb": round(total_size_bytes / (1024 * 1024), 2),
                "size_gb": round(total_size_bytes / (1024 * 1024 * 1024), 2),
                "container_count": len(containers),
                "blob_count": total_blobs
            }
        except Exception as e:
            logger.error(f"[STORAGE] Failed to get blob metrics: {str(e)}")
            return {"size_mb": 0, "size_gb": 0, "container_count": 0, "blob_count": 0, "error": str(e)}

    def get_storage_history(
        self,
        hours: int = 168,  # 1 week
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get storage history snapshots

        Args:
            hours: Number of hours to look back
            limit: Maximum number of snapshots to return

        Returns:
            list: List of storage snapshots
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Get snapshots
            snapshots = list(collection.find(
                {"timestamp": {"$gte": time_threshold}},
                {"_id": 0}
            ).sort("timestamp", -1).limit(limit))

            logger.info(f"[STORAGE] Retrieved {len(snapshots)} storage snapshots")
            return snapshots

        except Exception as e:
            logger.error(f"[STORAGE] Failed to get storage history: {str(e)}")
            return []

    def get_storage_growth(self, hours: int = 168) -> dict[str, Any]:
        """
        Calculate storage growth rate

        Args:
            hours: Number of hours to analyze

        Returns:
            dict: Storage growth metrics
        """
        try:
            snapshots = self.get_storage_history(hours=hours, limit=1000)

            if len(snapshots) < 2:
                return {
                    "error": "Insufficient data for growth calculation (need at least 2 snapshots)"
                }

            # Sort by timestamp (oldest first)
            snapshots.sort(key=lambda x: x.get("timestamp"))

            oldest = snapshots[0]
            newest = snapshots[-1]

            oldest_size_mb = oldest.get("database", {}).get("size_mb", 0)
            newest_size_mb = newest.get("database", {}).get("size_mb", 0)

            growth_mb = newest_size_mb - oldest_size_mb
            growth_percentage = (growth_mb / oldest_size_mb * 100) if oldest_size_mb > 0 else 0

            # Calculate time difference
            time_diff = newest.get("timestamp") - oldest.get("timestamp")
            hours_diff = time_diff.total_seconds() / 3600

            # Calculate growth rate per day
            growth_rate_mb_per_day = (growth_mb / hours_diff * 24) if hours_diff > 0 else 0

            return {
                "time_period_hours": hours,
                "snapshots_analyzed": len(snapshots),
                "oldest_snapshot": oldest.get("timestamp").isoformat(),
                "newest_snapshot": newest.get("timestamp").isoformat(),
                "oldest_size_mb": oldest_size_mb,
                "newest_size_mb": newest_size_mb,
                "growth_mb": round(growth_mb, 2),
                "growth_percentage": round(growth_percentage, 2),
                "growth_rate_mb_per_day": round(growth_rate_mb_per_day, 2),
                "growth_rate_gb_per_month": round(growth_rate_mb_per_day * 30 / 1024, 2)
            }

        except Exception as e:
            logger.error(f"[STORAGE] Failed to calculate storage growth: {str(e)}")
            return {"error": str(e)}

    def get_collection_breakdown(self, force_refresh: bool = False) -> dict[str, Any]:
        """
        Get storage breakdown by collection (current state)

        Returns:
            dict: Collection storage breakdown
        """
        try:
            current_storage = self.get_current_storage(force_refresh=force_refresh)

            if "error" in current_storage:
                return current_storage

            collections = current_storage.get("collections", [])
            total_size_mb = current_storage.get("database", {}).get("size_mb", 0)

            # Calculate percentages
            for coll in collections:
                coll_size = coll.get("size_mb", 0)
                coll["percentage"] = round((coll_size / total_size_mb * 100) if total_size_mb > 0 else 0, 2)

            return {
                "total_size_mb": total_size_mb,
                "total_collections": len(collections),
                "collections": collections[:20]  # Top 20 collections
            }

        except Exception as e:
            logger.error(f"[STORAGE] Failed to get collection breakdown: {str(e)}")
            return {"error": str(e)}


# Global instance
storage_metrics = StorageMetrics()
