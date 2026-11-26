"""
LLM Token Usage Tracking Module
Tracks LLM API usage per user with detailed analytics and cost tracking
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)


class LLMUsageTracker:
    """Manages LLM token usage tracking and analytics"""

    def __init__(self):
        self.collection_name = "llm_usage"

    def record_usage(
        self,
        user_id: str,
        provider: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        estimated_cost: float,
        response_time_ms: float,
        agent_type: str | None = None,
        feature_type: str | None = None,
        request_type: str | None = None,
        session_id: str | None = None
    ) -> bool:
        """
        Record LLM token usage for a user

        Args:
            user_id: User identifier
            provider: LLM provider (google, openai, anthropic, grok)
            model_name: Model name (gemini-2.5-pro, gpt-5, etc.)
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens
            total_tokens: Total tokens (input + output)
            estimated_cost: Estimated cost in USD
            response_time_ms: Response time in milliseconds
            agent_type: Agent that made the call (chat, search, solution, router)
            feature_type: Feature category (product_search, solution_generation, chat_query, etc.)
            request_type: Type of request (classification, extraction, generation, etc.)

        Returns:
            bool: True if recorded successfully
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Prepare usage record
            usage_record = {
                "user_id": user_id,
                "timestamp": datetime.now(UTC),
                "provider": provider,
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": estimated_cost,
                "response_time_ms": response_time_ms,
                "agent_type": agent_type,
                "feature_type": feature_type,
                "request_type": request_type,
                "session_id": session_id
            }

            collection.insert_one(usage_record)
            logger.debug(
                f"[LLM_USAGE] Recorded usage for user {user_id}: "
                f"{total_tokens:,} tokens, ${estimated_cost:.6f}, "
                f"agent={agent_type}, feature={feature_type}"
            )
            return True

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to record usage: {str(e)}")
            return False

    def get_user_usage(
        self,
        user_id: str,
        hours: int = 24,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get detailed token usage records for a user

        Args:
            user_id: User identifier
            hours: Number of hours to look back
            limit: Maximum number of records to return

        Returns:
            list: List of usage records
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Query usage records
            usage_records = list(collection.find(
                {
                    "user_id": user_id,
                    "timestamp": {"$gte": time_threshold}
                },
                {"_id": 0}
            ).sort("timestamp", -1).limit(limit))

            logger.info(f"[LLM_USAGE] Retrieved {len(usage_records)} usage records for user {user_id}")
            return usage_records

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get user usage: {str(e)}")
            return []

    def get_user_summary(
        self,
        user_id: str,
        hours: int = 24
    ) -> dict[str, Any]:
        """
        Get summary statistics for a user's token usage

        Args:
            user_id: User identifier
            hours: Number of hours to analyze

        Returns:
            dict: Usage summary statistics
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate statistics
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": time_threshold}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_requests": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_input_tokens": {"$sum": "$input_tokens"},
                        "total_output_tokens": {"$sum": "$output_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"},
                        "avg_tokens_per_request": {"$avg": "$total_tokens"},
                        "avg_cost_per_request": {"$avg": "$estimated_cost"},
                        "avg_response_time_ms": {"$avg": "$response_time_ms"}
                    }
                }
            ]

            result = list(collection.aggregate(pipeline))

            if result:
                stats = result[0]
                return {
                    "user_id": user_id,
                    "time_period_hours": hours,
                    "total_requests": stats.get("total_requests", 0),
                    "total_tokens": stats.get("total_tokens", 0),
                    "total_input_tokens": stats.get("total_input_tokens", 0),
                    "total_output_tokens": stats.get("total_output_tokens", 0),
                    "total_cost_usd": round(stats.get("total_cost", 0), 6),
                    "avg_tokens_per_request": round(stats.get("avg_tokens_per_request", 0), 2),
                    "avg_cost_per_request_usd": round(stats.get("avg_cost_per_request", 0), 6),
                    "avg_response_time_ms": round(stats.get("avg_response_time_ms", 0), 2)
                }
            else:
                return {
                    "user_id": user_id,
                    "time_period_hours": hours,
                    "total_requests": 0,
                    "total_tokens": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost_usd": 0.0,
                    "avg_tokens_per_request": 0.0,
                    "avg_cost_per_request_usd": 0.0,
                    "avg_response_time_ms": 0.0
                }

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get user summary: {str(e)}")
            return {"error": str(e)}

    def get_usage_by_agent(
        self,
        user_id: str,
        hours: int = 24
    ) -> dict[str, Any]:
        """
        Get token usage breakdown by agent type

        Args:
            user_id: User identifier
            hours: Number of hours to analyze

        Returns:
            dict: Usage breakdown by agent
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by agent type
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": time_threshold}
                    }
                },
                {
                    "$group": {
                        "_id": "$agent_type",
                        "request_count": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"},
                        "avg_tokens": {"$avg": "$total_tokens"},
                        "avg_response_time": {"$avg": "$response_time_ms"}
                    }
                },
                {"$sort": {"total_tokens": -1}}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                formatted_results.append({
                    "agent_type": r.get("_id") or "unknown",
                    "request_count": r.get("request_count", 0),
                    "total_tokens": r.get("total_tokens", 0),
                    "total_cost_usd": round(r.get("total_cost", 0), 6),
                    "avg_tokens_per_request": round(r.get("avg_tokens", 0), 2),
                    "avg_response_time_ms": round(r.get("avg_response_time", 0), 2)
                })

            return {
                "user_id": user_id,
                "time_period_hours": hours,
                "by_agent": formatted_results
            }

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get usage by agent: {str(e)}")
            return {"error": str(e)}

    def get_usage_by_feature(
        self,
        user_id: str,
        hours: int = 24
    ) -> dict[str, Any]:
        """
        Get token usage breakdown by feature type

        Args:
            user_id: User identifier
            hours: Number of hours to analyze

        Returns:
            dict: Usage breakdown by feature
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by feature type
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": time_threshold}
                    }
                },
                {
                    "$group": {
                        "_id": "$feature_type",
                        "request_count": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"},
                        "avg_tokens": {"$avg": "$total_tokens"},
                        "avg_response_time": {"$avg": "$response_time_ms"}
                    }
                },
                {"$sort": {"total_tokens": -1}}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                formatted_results.append({
                    "feature_type": r.get("_id") or "unknown",
                    "request_count": r.get("request_count", 0),
                    "total_tokens": r.get("total_tokens", 0),
                    "total_cost_usd": round(r.get("total_cost", 0), 6),
                    "avg_tokens_per_request": round(r.get("avg_tokens", 0), 2),
                    "avg_response_time_ms": round(r.get("avg_response_time", 0), 2)
                })

            return {
                "user_id": user_id,
                "time_period_hours": hours,
                "by_feature": formatted_results
            }

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get usage by feature: {str(e)}")
            return {"error": str(e)}

    def get_usage_by_model(
        self,
        user_id: str,
        hours: int = 24
    ) -> dict[str, Any]:
        """
        Get token usage breakdown by model

        Args:
            user_id: User identifier
            hours: Number of hours to analyze

        Returns:
            dict: Usage breakdown by model
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by model
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": time_threshold}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "provider": "$provider",
                            "model": "$model_name"
                        },
                        "request_count": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"},
                        "avg_tokens": {"$avg": "$total_tokens"}
                    }
                },
                {"$sort": {"total_tokens": -1}}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                formatted_results.append({
                    "provider": r["_id"].get("provider") or "unknown",
                    "model_name": r["_id"].get("model") or "unknown",
                    "request_count": r.get("request_count", 0),
                    "total_tokens": r.get("total_tokens", 0),
                    "total_cost_usd": round(r.get("total_cost", 0), 6),
                    "avg_tokens_per_request": round(r.get("avg_tokens", 0), 2)
                })

            return {
                "user_id": user_id,
                "time_period_hours": hours,
                "by_model": formatted_results
            }

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get usage by model: {str(e)}")
            return {"error": str(e)}

    def get_all_users_summary(self, hours: int = 24) -> dict[str, Any]:
        """
        Get aggregate usage statistics across all users

        Args:
            hours: Number of hours to analyze

        Returns:
            dict: Aggregate usage statistics
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate statistics
            pipeline = [
                {"$match": {"timestamp": {"$gte": time_threshold}}},
                {
                    "$group": {
                        "_id": None,
                        "total_users": {"$addToSet": "$user_id"},
                        "total_requests": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"},
                        "avg_tokens_per_request": {"$avg": "$total_tokens"},
                        "avg_cost_per_request": {"$avg": "$estimated_cost"}
                    }
                }
            ]

            result = list(collection.aggregate(pipeline))

            if result:
                stats = result[0]
                return {
                    "time_period_hours": hours,
                    "total_users": len(stats.get("total_users", [])),
                    "total_requests": stats.get("total_requests", 0),
                    "total_tokens": stats.get("total_tokens", 0),
                    "total_cost_usd": round(stats.get("total_cost", 0), 6),
                    "avg_tokens_per_request": round(stats.get("avg_tokens_per_request", 0), 2),
                    "avg_cost_per_request_usd": round(stats.get("avg_cost_per_request", 0), 6)
                }
            else:
                return {
                    "time_period_hours": hours,
                    "total_users": 0,
                    "total_requests": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "avg_tokens_per_request": 0.0,
                    "avg_cost_per_request_usd": 0.0
                }

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get all users summary: {str(e)}")
            return {"error": str(e)}

    def get_top_consumers(
        self,
        hours: int = 24,
        limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Get top token-consuming users

        Args:
            hours: Number of hours to analyze
            limit: Maximum number of users to return

        Returns:
            list: Top users by token consumption
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by user
            pipeline = [
                {"$match": {"timestamp": {"$gte": time_threshold}}},
                {
                    "$group": {
                        "_id": "$user_id",
                        "total_requests": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"}
                    }
                },
                {"$sort": {"total_tokens": -1}},
                {"$limit": limit}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                formatted_results.append({
                    "user_id": r.get("_id"),
                    "total_requests": r.get("total_requests", 0),
                    "total_tokens": r.get("total_tokens", 0),
                    "total_cost_usd": round(r.get("total_cost", 0), 6)
                })

            return formatted_results

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get top consumers: {str(e)}")
            return []

    def get_usage_trend(
        self,
        user_id: str,
        hours: int = 168  # 1 week default
    ) -> dict[str, Any]:
        """
        Get usage trend over time (hourly buckets)

        Args:
            user_id: User identifier
            hours: Number of hours to analyze

        Returns:
            dict: Usage trend data
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by hour
            pipeline = [
                {
                    "$match": {
                        "user_id": user_id,
                        "timestamp": {"$gte": time_threshold}
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "year": {"$year": "$timestamp"},
                            "month": {"$month": "$timestamp"},
                            "day": {"$dayOfMonth": "$timestamp"},
                            "hour": {"$hour": "$timestamp"}
                        },
                        "request_count": {"$sum": 1},
                        "total_tokens": {"$sum": "$total_tokens"},
                        "total_cost": {"$sum": "$estimated_cost"}
                    }
                },
                {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1, "_id.hour": 1}}
            ]

            results = list(collection.aggregate(pipeline))

            formatted_results = []
            for r in results:
                id_data = r.get("_id", {})
                formatted_results.append({
                    "timestamp": f"{id_data.get('year')}-{id_data.get('month'):02d}-{id_data.get('day'):02d} {id_data.get('hour'):02d}:00",
                    "request_count": r.get("request_count", 0),
                    "total_tokens": r.get("total_tokens", 0),
                    "total_cost_usd": round(r.get("total_cost", 0), 6)
                })

            return {
                "user_id": user_id,
                "time_period_hours": hours,
                "trend_data": formatted_results
            }

        except Exception as e:
            logger.error(f"[LLM_USAGE] Failed to get usage trend: {str(e)}")
            return {"error": str(e)}


# Global instance
llm_usage_tracker = LLMUsageTracker()
