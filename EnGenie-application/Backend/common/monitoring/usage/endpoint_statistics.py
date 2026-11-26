"""
API Endpoint Statistics Module
Tracks API endpoint usage, response times, error rates, and performance metrics
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)


class EndpointStatistics:
    """Manages API endpoint statistics tracking"""

    def __init__(self):
        self.collection_name = "endpoint_statistics"

    def record_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        response_time_ms: float,
        user_id: str | None = None,
        error_message: str | None = None
    ) -> bool:
        """
        Record an API request

        Args:
            endpoint: API endpoint path (e.g., "/api/chat")
            method: HTTP method (GET, POST, PUT, DELETE)
            status_code: HTTP status code (200, 404, 500, etc.)
            response_time_ms: Response time in milliseconds
            user_id: Optional user identifier
            error_message: Optional error message for failed requests

        Returns:
            bool: True if recorded successfully
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Prepare request record
            request_record = {
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "user_id": user_id,
                "error_message": error_message,
                "is_success": 200 <= status_code < 400,
                "is_client_error": 400 <= status_code < 500,
                "is_server_error": status_code >= 500,
                "timestamp": datetime.now(UTC)
            }

            collection.insert_one(request_record)
            logger.debug(f"[ENDPOINT_STATS] Recorded {method} {endpoint} - {status_code} ({response_time_ms:.2f}ms)")
            return True

        except Exception as e:
            logger.error(f"[ENDPOINT_STATS] Failed to record request: {str(e)}")
            return False

    def get_endpoint_summary(
        self,
        endpoint: str | None = None,
        hours: int = 24
    ) -> dict[str, Any]:
        """
        Get summary statistics for endpoints

        Args:
            endpoint: Optional specific endpoint (None for all endpoints)
            hours: Number of hours to look back

        Returns:
            dict: Summary statistics
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Build query
            match_query = {"timestamp": {"$gte": time_threshold}}
            if endpoint:
                match_query["endpoint"] = endpoint

            # Aggregate statistics
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": "$endpoint" if not endpoint else None,
                        "total_requests": {"$sum": 1},
                        "success_count": {
                            "$sum": {"$cond": ["$is_success", 1, 0]}
                        },
                        "client_error_count": {
                            "$sum": {"$cond": ["$is_client_error", 1, 0]}
                        },
                        "server_error_count": {
                            "$sum": {"$cond": ["$is_server_error", 1, 0]}
                        },
                        "avg_response_time_ms": {"$avg": "$response_time_ms"},
                        "min_response_time_ms": {"$min": "$response_time_ms"},
                        "max_response_time_ms": {"$max": "$response_time_ms"},
                        "p95_response_time_ms": {
                            "$percentile": {
                                "input": "$response_time_ms",
                                "p": [0.95],
                                "method": "approximate"
                            }
                        }
                    }
                },
                {"$sort": {"total_requests": -1}}
            ]

            results = list(collection.aggregate(pipeline))

            if not endpoint:
                # Multiple endpoints
                formatted_results = []
                for r in results:
                    total = r.get("total_requests", 0)
                    success = r.get("success_count", 0)
                    formatted_results.append({
                        "endpoint": r.get("_id"),
                        "total_requests": total,
                        "success_count": success,
                        "client_error_count": r.get("client_error_count", 0),
                        "server_error_count": r.get("server_error_count", 0),
                        "success_rate": round((success / total * 100) if total > 0 else 0, 2),
                        "avg_response_time_ms": round(r.get("avg_response_time_ms", 0), 2),
                        "min_response_time_ms": round(r.get("min_response_time_ms", 0), 2),
                        "max_response_time_ms": round(r.get("max_response_time_ms", 0), 2),
                        "p95_response_time_ms": round(r.get("p95_response_time_ms", [0])[0], 2)
                    })
                return {
                    "time_period_hours": hours,
                    "endpoints": formatted_results,
                    "total_endpoints": len(formatted_results)
                }
            else:
                # Single endpoint
                if results:
                    r = results[0]
                    total = r.get("total_requests", 0)
                    success = r.get("success_count", 0)
                    return {
                        "endpoint": endpoint,
                        "time_period_hours": hours,
                        "total_requests": total,
                        "success_count": success,
                        "client_error_count": r.get("client_error_count", 0),
                        "server_error_count": r.get("server_error_count", 0),
                        "success_rate": round((success / total * 100) if total > 0 else 0, 2),
                        "avg_response_time_ms": round(r.get("avg_response_time_ms", 0), 2),
                        "min_response_time_ms": round(r.get("min_response_time_ms", 0), 2),
                        "max_response_time_ms": round(r.get("max_response_time_ms", 0), 2),
                        "p95_response_time_ms": round(r.get("p95_response_time_ms", [0])[0], 2)
                    }
                else:
                    return {
                        "endpoint": endpoint,
                        "time_period_hours": hours,
                        "total_requests": 0,
                        "message": "No data found for this endpoint"
                    }

        except Exception as e:
            logger.error(f"[ENDPOINT_STATS] Failed to get endpoint summary: {str(e)}")
            return {"error": str(e)}

    def get_slowest_endpoints(self, hours: int = 24, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get slowest endpoints by average response time

        Args:
            hours: Number of hours to look back
            limit: Maximum number of endpoints to return

        Returns:
            list: List of slowest endpoints
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate slowest endpoints
            pipeline = [
                {"$match": {"timestamp": {"$gte": time_threshold}}},
                {
                    "$group": {
                        "_id": "$endpoint",
                        "total_requests": {"$sum": 1},
                        "avg_response_time_ms": {"$avg": "$response_time_ms"},
                        "max_response_time_ms": {"$max": "$response_time_ms"}
                    }
                },
                {"$sort": {"avg_response_time_ms": -1}},
                {"$limit": limit}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                formatted_results.append({
                    "endpoint": r.get("_id"),
                    "total_requests": r.get("total_requests", 0),
                    "avg_response_time_ms": round(r.get("avg_response_time_ms", 0), 2),
                    "max_response_time_ms": round(r.get("max_response_time_ms", 0), 2)
                })

            return formatted_results

        except Exception as e:
            logger.error(f"[ENDPOINT_STATS] Failed to get slowest endpoints: {str(e)}")
            return []

    def get_error_statistics(self, hours: int = 24) -> dict[str, Any]:
        """
        Get error statistics across all endpoints

        Args:
            hours: Number of hours to look back

        Returns:
            dict: Error statistics
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate error statistics
            pipeline = [
                {"$match": {"timestamp": {"$gte": time_threshold}}},
                {
                    "$group": {
                        "_id": None,
                        "total_requests": {"$sum": 1},
                        "client_errors": {
                            "$sum": {"$cond": ["$is_client_error", 1, 0]}
                        },
                        "server_errors": {
                            "$sum": {"$cond": ["$is_server_error", 1, 0]}
                        }
                    }
                }
            ]

            result = list(collection.aggregate(pipeline))

            if result:
                r = result[0]
                total = r.get("total_requests", 0)
                client_errors = r.get("client_errors", 0)
                server_errors = r.get("server_errors", 0)
                total_errors = client_errors + server_errors

                return {
                    "time_period_hours": hours,
                    "total_requests": total,
                    "total_errors": total_errors,
                    "client_errors": client_errors,
                    "server_errors": server_errors,
                    "error_rate": round((total_errors / total * 100) if total > 0 else 0, 2),
                    "client_error_rate": round((client_errors / total * 100) if total > 0 else 0, 2),
                    "server_error_rate": round((server_errors / total * 100) if total > 0 else 0, 2)
                }
            else:
                return {
                    "time_period_hours": hours,
                    "total_requests": 0,
                    "total_errors": 0,
                    "client_errors": 0,
                    "server_errors": 0,
                    "error_rate": 0,
                    "client_error_rate": 0,
                    "server_error_rate": 0
                }

        except Exception as e:
            logger.error(f"[ENDPOINT_STATS] Failed to get error statistics: {str(e)}")
            return {"error": str(e)}


# Global instance
endpoint_statistics = EndpointStatistics()
