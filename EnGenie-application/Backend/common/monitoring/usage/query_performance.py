"""
Database Query Performance Tracking Module
Tracks slow MongoDB queries and provides performance analytics
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)


class QueryPerformanceTracker:
    """Manages database query performance tracking"""

    def __init__(self, slow_query_threshold_ms: float = 1000.0):
        """
        Initialize query performance tracker

        Args:
            slow_query_threshold_ms: Threshold in milliseconds to consider a query slow (default: 1000ms = 1 second)
        """
        self.collection_name = "query_performance"
        self.slow_query_threshold_ms = slow_query_threshold_ms

    def record_query(
        self,
        collection_name: str,
        operation: str,
        execution_time_ms: float,
        query_filter: dict[str, Any] | None = None,
        result_count: int | None = None,
        is_indexed: bool | None = None
    ) -> bool:
        """
        Record a database query

        Args:
            collection_name: Name of the MongoDB collection
            operation: Type of operation (find, aggregate, update, insert, delete)
            execution_time_ms: Query execution time in milliseconds
            query_filter: Optional query filter/criteria (sanitized)
            result_count: Optional number of documents returned/affected
            is_indexed: Optional flag indicating if query used an index

        Returns:
            bool: True if recorded successfully
        """
        try:
            # Only record slow queries to avoid excessive logging
            if execution_time_ms < self.slow_query_threshold_ms:
                return True  # Skip fast queries

            collection = mongodb_manager.get_collection(self.collection_name)

            # Sanitize query filter (remove actual values, keep structure)
            sanitized_filter = self._sanitize_query_filter(query_filter) if query_filter else {}

            # Prepare query record
            query_record = {
                "collection": collection_name,
                "operation": operation,
                "execution_time_ms": execution_time_ms,
                "query_filter": sanitized_filter,
                "result_count": result_count,
                "is_indexed": is_indexed,
                "is_slow": execution_time_ms >= self.slow_query_threshold_ms,
                "timestamp": datetime.now(UTC)
            }

            collection.insert_one(query_record)
            logger.warning(
                f"[SLOW_QUERY] {collection_name}.{operation} took {execution_time_ms:.2f}ms "
                f"(threshold: {self.slow_query_threshold_ms}ms)"
            )
            return True

        except Exception as e:
            logger.error(f"[QUERY_PERF] Failed to record query: {str(e)}")
            return False

    def get_slow_queries(
        self,
        hours: int = 24,
        limit: int = 100,
        collection_name: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Get slow queries

        Args:
            hours: Number of hours to look back
            limit: Maximum number of queries to return
            collection_name: Optional filter by collection name

        Returns:
            list: List of slow queries
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Build query
            match_query = {
                "timestamp": {"$gte": time_threshold},
                "is_slow": True
            }
            if collection_name:
                match_query["collection"] = collection_name

            # Get slow queries
            slow_queries = list(collection.find(
                match_query,
                {"_id": 0}
            ).sort("execution_time_ms", -1).limit(limit))

            logger.info(f"[QUERY_PERF] Retrieved {len(slow_queries)} slow queries")
            return slow_queries

        except Exception as e:
            logger.error(f"[QUERY_PERF] Failed to get slow queries: {str(e)}")
            return []

    def get_query_statistics(
        self,
        hours: int = 24,
        collection_name: str | None = None
    ) -> dict[str, Any]:
        """
        Get query performance statistics

        Args:
            hours: Number of hours to look back
            collection_name: Optional filter by collection name

        Returns:
            dict: Query statistics
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Build query
            match_query = {"timestamp": {"$gte": time_threshold}}
            if collection_name:
                match_query["collection"] = collection_name

            # Aggregate statistics
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "total_slow_queries": {"$sum": 1},
                        "avg_execution_time_ms": {"$avg": "$execution_time_ms"},
                        "max_execution_time_ms": {"$max": "$execution_time_ms"},
                        "min_execution_time_ms": {"$min": "$execution_time_ms"},
                        "total_documents_processed": {"$sum": "$result_count"}
                    }
                }
            ]

            result = list(collection.aggregate(pipeline))

            if result:
                r = result[0]
                return {
                    "time_period_hours": hours,
                    "collection": collection_name or "all_collections",
                    "total_slow_queries": r.get("total_slow_queries", 0),
                    "avg_execution_time_ms": round(r.get("avg_execution_time_ms", 0), 2),
                    "max_execution_time_ms": round(r.get("max_execution_time_ms", 0), 2),
                    "min_execution_time_ms": round(r.get("min_execution_time_ms", 0), 2),
                    "total_documents_processed": r.get("total_documents_processed", 0),
                    "slow_query_threshold_ms": self.slow_query_threshold_ms
                }
            else:
                return {
                    "time_period_hours": hours,
                    "collection": collection_name or "all_collections",
                    "total_slow_queries": 0,
                    "avg_execution_time_ms": 0,
                    "max_execution_time_ms": 0,
                    "min_execution_time_ms": 0,
                    "total_documents_processed": 0,
                    "slow_query_threshold_ms": self.slow_query_threshold_ms
                }

        except Exception as e:
            logger.error(f"[QUERY_PERF] Failed to get query statistics: {str(e)}")
            return {"error": str(e)}

    def get_queries_by_collection(self, hours: int = 24) -> dict[str, Any]:
        """
        Get slow query count grouped by collection

        Args:
            hours: Number of hours to look back

        Returns:
            dict: Queries grouped by collection
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by collection
            pipeline = [
                {"$match": {"timestamp": {"$gte": time_threshold}}},
                {
                    "$group": {
                        "_id": "$collection",
                        "slow_query_count": {"$sum": 1},
                        "avg_execution_time_ms": {"$avg": "$execution_time_ms"},
                        "max_execution_time_ms": {"$max": "$execution_time_ms"}
                    }
                },
                {"$sort": {"slow_query_count": -1}}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                formatted_results.append({
                    "collection": r.get("_id"),
                    "slow_query_count": r.get("slow_query_count", 0),
                    "avg_execution_time_ms": round(r.get("avg_execution_time_ms", 0), 2),
                    "max_execution_time_ms": round(r.get("max_execution_time_ms", 0), 2)
                })

            return {
                "time_period_hours": hours,
                "collections": formatted_results,
                "total_collections_with_slow_queries": len(formatted_results)
            }

        except Exception as e:
            logger.error(f"[QUERY_PERF] Failed to get queries by collection: {str(e)}")
            return {"error": str(e)}

    def _sanitize_query_filter(self, query_filter: dict[str, Any]) -> dict[str, Any]:
        """
        Sanitize query filter to remove actual values while keeping structure

        Args:
            query_filter: Original query filter

        Returns:
            dict: Sanitized query filter
        """
        if not query_filter:
            return {}

        sanitized = {}
        for key, value in query_filter.items():
            if isinstance(value, dict):
                # For operators like $gt, $lt, etc., just indicate their presence
                sanitized[key] = dict.fromkeys(value.keys(), "<value>")
            elif isinstance(value, (list, tuple)):
                sanitized[key] = f"<array[{len(value)}]>"
            else:
                sanitized[key] = "<value>"

        return sanitized


# Global instance
query_performance_tracker = QueryPerformanceTracker(slow_query_threshold_ms=1000.0)
