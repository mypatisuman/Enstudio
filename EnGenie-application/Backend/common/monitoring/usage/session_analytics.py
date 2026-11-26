"""
Session Analytics Module
Tracks user sessions with detailed metadata, duration, and activity patterns
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)

# Optional user-agents library for parsing user agent strings
try:
    from user_agents import parse as parse_user_agent
    HAS_USER_AGENTS = True
except ImportError:
    HAS_USER_AGENTS = False
    logger.warning("[SESSION] user-agents library not installed. User agent parsing will be limited.")


class SessionAnalytics:
    """Manages user session tracking and analytics"""

    def __init__(self):
        self.collection_name = "user_sessions"

    def start_session(
        self,
        user_id: str,
        session_id: str,
        request_data: dict[str, Any] | None = None
    ) -> bool:
        """
        Start a new user session with metadata

        Args:
            user_id: User identifier
            session_id: Unique session identifier
            request_data: request object data (headers, remote_addr, etc.)

        Returns:
            bool: True if session started successfully
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Check if session already exists
            existing_session = collection.find_one({
                "user_id": user_id,
                "session_id": session_id
            })

            if existing_session:
                logger.info(f"[SESSION] Session already exists for user {user_id}, session {session_id}")
                return True

            # Extract metadata from request
            metadata = self._extract_session_metadata(request_data) if request_data else {}

            # Create session document
            session_doc = {
                "user_id": user_id,
                "session_id": session_id,
                "start_time": datetime.now(UTC),
                "end_time": None,
                "last_activity": datetime.now(UTC),
                "duration_seconds": 0,
                "interaction_count": 0,
                "is_active": True,
                "metadata": metadata,
                "activity_timeline": []
            }

            collection.insert_one(session_doc)
            logger.info(f"[SESSION] Started session for user {user_id}, session {session_id}")
            return True

        except Exception as e:
            logger.error(f"[SESSION] Failed to start session: {str(e)}")
            return False

    def update_session_activity(
        self,
        user_id: str,
        session_id: str,
        activity_type: str = "interaction",
        activity_details: dict[str, Any] | None = None
    ) -> bool:
        """
        Update session with new activity

        Args:
            user_id: User identifier
            session_id: Session identifier
            activity_type: Type of activity (interaction, page_view, action, etc.)
            activity_details: Additional activity details

        Returns:
            bool: True if updated successfully
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            activity_entry = {
                "timestamp": datetime.now(UTC),
                "type": activity_type,
                "details": activity_details or {}
            }

            now = datetime.now(UTC)
            result = collection.update_one(
                {
                    "user_id": user_id,
                    "session_id": session_id
                },
                {
                    "$set": {
                        "last_activity": now,
                        "is_active": True
                    },
                    "$setOnInsert": {
                        "start_time": now,
                        "end_time": None,
                        "duration_seconds": 0,
                        "metadata": {}
                    },
                    "$inc": {"interaction_count": 1},
                    "$push": {"activity_timeline": activity_entry}
                },
                upsert=True
            )

            if result.modified_count > 0 or result.upserted_id:
                logger.debug(f"[SESSION] Updated activity for session {session_id}")
                return True
            else:
                logger.debug(f"[SESSION] No changes for session {session_id}")
                return False

        except Exception as e:
            logger.error(f"[SESSION] Failed to update session activity: {str(e)}")
            return False

    def end_session(self, user_id: str, session_id: str) -> bool:
        """
        End a user session and calculate duration

        Args:
            user_id: User identifier
            session_id: Session identifier

        Returns:
            bool: True if session ended successfully
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Get session to calculate duration
            session_doc = collection.find_one({
                "user_id": user_id,
                "session_id": session_id
            })

            if not session_doc:
                logger.warning(f"[SESSION] Session not found for ending: {session_id}")
                return False

            # Calculate duration
            end_time = datetime.now(UTC)
            start_time = session_doc.get("start_time")

            # Ensure both datetimes are timezone-aware for comparison
            if start_time and not start_time.tzinfo:
                start_time = start_time.replace(tzinfo=UTC)

            duration_seconds = (end_time - start_time).total_seconds() if start_time else 0

            # Update session
            collection.update_one(
                {"_id": session_doc["_id"]},
                {
                    "$set": {
                        "end_time": end_time,
                        "duration_seconds": duration_seconds,
                        "is_active": False
                    }
                }
            )

            logger.info(f"[SESSION] Ended session {session_id} - Duration: {duration_seconds:.2f}s")
            return True

        except Exception as e:
            logger.error(f"[SESSION] Failed to end session: {str(e)}")
            return False

    def get_session_info(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """
        Get information about a specific session

        Args:
            user_id: User identifier
            session_id: Session identifier

        Returns:
            dict: Session information or None if not found
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            session_doc = collection.find_one({
                "user_id": user_id,
                "session_id": session_id
            }, {"_id": 0})

            return session_doc

        except Exception as e:
            logger.error(f"[SESSION] Failed to get session info: {str(e)}")
            return None

    def mark_inactive_sessions(self, inactivity_minutes: int = 30) -> int:
        """
        Mark sessions as inactive if they haven't had activity in the specified time.

        Args:
            inactivity_minutes: Minutes of inactivity after which to mark session as inactive

        Returns:
            int: Number of sessions marked as inactive
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate inactivity threshold
            inactivity_threshold = datetime.now(UTC) - timedelta(minutes=inactivity_minutes)

            # Find sessions that are marked active but haven't had activity recently
            result = collection.update_many(
                {
                    "is_active": True,
                    "last_activity": {"$lt": inactivity_threshold}
                },
                {
                    "$set": {"is_active": False}
                }
            )

            if result.modified_count > 0:
                logger.info(f"[SESSION] Marked {result.modified_count} sessions as inactive due to {inactivity_minutes}min inactivity")

            return result.modified_count

        except Exception as e:
            logger.error(f"[SESSION] Failed to mark inactive sessions: {str(e)}")
            return 0

    def get_user_sessions(
        self,
        user_id: str,
        limit: int = 10,
        active_only: bool = False,
        hours: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Get sessions for a specific user

        Args:
            user_id: User identifier
            limit: Maximum number of sessions to return
            active_only: Only return active sessions
            hours: Optional time window in hours (None = all time)

        Returns:
            list: List of session documents
        """
        try:
            # Mark inactive sessions before retrieving
            self.mark_inactive_sessions()

            collection = mongodb_manager.get_collection(self.collection_name)

            query = {"user_id": user_id}
            if active_only:
                query["is_active"] = True

            # Add time filter if hours parameter is provided
            if hours is not None:
                time_threshold = datetime.now(UTC) - timedelta(hours=hours)
                query["start_time"] = {"$gte": time_threshold}

            sessions = list(collection.find(
                query,
                {"_id": 0}
            ).sort("start_time", -1).limit(limit))

            logger.info(f"[SESSION] Retrieved {len(sessions)} sessions for user {user_id}")
            return sessions

        except Exception as e:
            logger.error(f"[SESSION] Failed to get user sessions: {str(e)}")
            return []

    def get_session_analytics(
        self,
        user_id: str | None = None,
        hours: int = 24,
        active_only: bool = False
    ) -> dict[str, Any]:
        """
        Get session analytics for a user or all users

        Args:
            user_id: Optional user identifier (None for all users)
            hours: Number of hours to look back
            active_only: Only count active sessions (default: False)

        Returns:
            dict: Analytics data
        """
        try:
            # Mark inactive sessions before calculating analytics
            self.mark_inactive_sessions()

            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Build query
            match_query = {"start_time": {"$gte": time_threshold}}
            if user_id:
                match_query["user_id"] = user_id
            if active_only:
                match_query["is_active"] = True

            # Aggregate statistics
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "total_sessions": {"$sum": 1},
                        "active_sessions": {
                            "$sum": {"$cond": [{"$eq": ["$is_active", True]}, 1, 0]}
                        },
                        "ended_sessions": {
                            "$sum": {"$cond": [{"$eq": ["$is_active", False]}, 1, 0]}
                        },
                        "total_interactions": {"$sum": "$interaction_count"},
                        "avg_interactions_per_session": {"$avg": "$interaction_count"},
                        "avg_duration_seconds": {
                            "$avg": {
                                "$cond": [
                                    {"$eq": ["$is_active", False]},
                                    "$duration_seconds",
                                    None
                                ]
                            }
                        },
                        "total_duration_seconds": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$is_active", False]},
                                    "$duration_seconds",
                                    0
                                ]
                            }
                        }
                    }
                }
            ]

            result = list(collection.aggregate(pipeline))

            if result:
                stats = result[0]
                avg_interactions = stats.get("avg_interactions_per_session") or 0
                avg_duration_sec = stats.get("avg_duration_seconds") or 0
                total_duration_sec = stats.get("total_duration_seconds") or 0

                return {
                    "time_period_hours": hours,
                    "user_id": user_id or "all_users",
                    "total_sessions": stats.get("total_sessions", 0),
                    "active_sessions": stats.get("active_sessions", 0),
                    "ended_sessions": stats.get("ended_sessions", 0),
                    "total_interactions": stats.get("total_interactions", 0),
                    "avg_interactions_per_session": round(avg_interactions, 2),
                    "avg_duration_seconds": round(avg_duration_sec, 2),
                    "avg_duration_minutes": round(avg_duration_sec / 60, 2),
                    "total_duration_hours": round(total_duration_sec / 3600, 2)
                }
            else:
                return {
                    "time_period_hours": hours,
                    "user_id": user_id or "all_users",
                    "total_sessions": 0,
                    "active_sessions": 0,
                    "ended_sessions": 0,
                    "total_interactions": 0,
                    "avg_interactions_per_session": 0,
                    "avg_duration_seconds": 0,
                    "avg_duration_minutes": 0,
                    "total_duration_hours": 0
                }

        except Exception as e:
            logger.error(f"[SESSION] Failed to get session analytics: {str(e)}")
            return {"error": str(e)}

    def get_activity_patterns(self, hours: int = 168) -> dict[str, Any]:
        """
        Get activity patterns (peak usage times)

        Args:
            hours: Number of hours to analyze (default: 168 = 1 week)

        Returns:
            dict: Activity patterns data
        """
        try:
            collection = mongodb_manager.get_collection(self.collection_name)

            # Calculate time threshold
            time_threshold = datetime.now(UTC) - timedelta(hours=hours)

            # Aggregate by hour of day
            pipeline = [
                {"$match": {"start_time": {"$gte": time_threshold}}},
                {
                    "$project": {
                        "hour_of_day": {"$hour": "$start_time"},
                        "day_of_week": {"$dayOfWeek": "$start_time"},
                        "interaction_count": 1
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "hour": "$hour_of_day",
                            "day": "$day_of_week"
                        },
                        "session_count": {"$sum": 1},
                        "total_interactions": {"$sum": "$interaction_count"}
                    }
                },
                {"$sort": {"_id.day": 1, "_id.hour": 1}}
            ]

            results = list(collection.aggregate(pipeline))

            # Process results
            hourly_distribution = {}
            daily_distribution = {}

            for r in results:
                hour = r["_id"]["hour"]
                day = r["_id"]["day"]
                count = r["session_count"]

                hourly_distribution[hour] = hourly_distribution.get(hour, 0) + count
                daily_distribution[day] = daily_distribution.get(day, 0) + count

            # Find peak hours
            peak_hour = max(hourly_distribution.items(), key=lambda x: x[1])[0] if hourly_distribution else 0
            peak_day = max(daily_distribution.items(), key=lambda x: x[1])[0] if daily_distribution else 1

            day_names = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday",
                        5: "Thursday", 6: "Friday", 7: "Saturday"}

            return {
                "time_period_hours": hours,
                "peak_hour_utc": peak_hour,
                "peak_day": day_names.get(peak_day, "Unknown"),
                "hourly_distribution": hourly_distribution,
                "daily_distribution": {day_names.get(k, str(k)): v for k, v in daily_distribution.items()}
            }

        except Exception as e:
            logger.error(f"[SESSION] Failed to get activity patterns: {str(e)}")
            return {"error": str(e)}

    def _extract_session_metadata(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """
        Extract session metadata from request

        Args:
            request_data: Request data dictionary

        Returns:
            dict: Session metadata
        """
        metadata = {}

        try:
            # Extract IP address
            metadata["ip_address"] = request_data.get("remote_addr", "unknown")

            # Extract User-Agent and parse it
            user_agent_string = request_data.get("user_agent", "")
            if user_agent_string:
                if HAS_USER_AGENTS:
                    try:
                        ua = parse_user_agent(user_agent_string)
                        metadata["browser"] = ua.browser.family
                        metadata["browser_version"] = ua.browser.version_string
                        metadata["os"] = ua.os.family
                        metadata["os_version"] = ua.os.version_string
                        metadata["device"] = ua.device.family
                        metadata["is_mobile"] = ua.is_mobile
                        metadata["is_tablet"] = ua.is_tablet
                        metadata["is_pc"] = ua.is_pc
                        metadata["is_bot"] = ua.is_bot
                    except:
                        metadata["user_agent"] = user_agent_string[:200]  # Truncate long UA strings
                else:
                    # Fallback when user-agents library is not installed
                    metadata["user_agent"] = user_agent_string[:200]

            # Extract other headers
            metadata["referer"] = request_data.get("referer", "")
            metadata["origin"] = request_data.get("origin", "")

        except Exception as e:
            logger.warning(f"[SESSION] Error extracting metadata: {str(e)}")

        return metadata


# Global instance
session_analytics = SessionAnalytics()
