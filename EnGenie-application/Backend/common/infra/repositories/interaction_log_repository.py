"""
Logging utility for storing user interactions in MongoDB
Stores all interactions from a session as a single entry per user
"""
import logging
from datetime import UTC, datetime
from typing import Any

from common.infra.mongodb_config import MongoDBManager

logger = logging.getLogger(__name__)

class InteractionLogger:
    """Handles logging of user interactions to MongoDB"""

    def __init__(self):
        self.mongo_manager = MongoDBManager()
        self.collection_name = "logs"

    def log_interaction(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
        response: Any,
        metadata: dict[str, Any] | None = None,
        interaction_type: str = "chat"
    ) -> bool:
        """
        Log a user interaction to the logs collection

        Args:
            user_id: User identifier
            session_id: Session identifier (to group interactions)
            user_input: What the user provided
            response: System response
            metadata: Additional metadata (agent type, model used, etc.)
            interaction_type: Type of interaction (chat, search, solution, etc.)

        Returns:
            bool: True if logged successfully, False otherwise
        """
        try:
            collection = self.mongo_manager.get_collection(self.collection_name)

            # Prepare interaction entry
            interaction = {
                "input": user_input,
                "response": response if isinstance(response, str) else str(response),
                "metadata": metadata or {},
                "type": interaction_type,
                "timestamp": datetime.now(UTC)
            }

            # Find existing log entry for this session
            existing_log = collection.find_one({
                "user_id": user_id,
                "session_id": session_id
            })

            if existing_log:
                # Update existing log entry by appending new interaction
                collection.update_one(
                    {"_id": existing_log["_id"]},
                    {
                        "$push": {"interactions": interaction},
                        "$inc": {"total_interactions": 1},
                        "$set": {"last_updated": datetime.now(UTC)}
                    }
                )
                logger.info(f"Updated log entry for user {user_id}, session {session_id}")
            else:
                # Create new log entry
                log_entry = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "interactions": [interaction],
                    "total_interactions": 1,
                    "created_at": datetime.now(UTC),
                    "last_updated": datetime.now(UTC)
                }
                collection.insert_one(log_entry)
                logger.info(f"Created new log entry for user {user_id}, session {session_id}")

            return True

        except Exception as e:
            logger.error(f"Error logging interaction: {str(e)}")
            return False

    def get_user_logs(self, user_id: str, limit: int = 10) -> list:
        """
        Get recent log entries for a user

        Args:
            user_id: User identifier
            limit: Maximum number of log entries to return

        Returns:
            list: List of log entries
        """
        try:
            collection = self.mongo_manager.get_collection(self.collection_name)
            logs = list(collection.find(
                {"user_id": user_id}
            ).sort("last_updated", -1).limit(limit))

            # Convert ObjectId to string for JSON serialization
            for log in logs:
                log["_id"] = str(log["_id"])

            return logs

        except Exception as e:
            logger.error(f"Error fetching user logs: {str(e)}")
            return []

    def get_session_log(self, user_id: str, session_id: str) -> dict | None:
        """
        Get log entry for a specific session

        Args:
            user_id: User identifier
            session_id: Session identifier

        Returns:
            dict: Log entry or None if not found
        """
        try:
            collection = self.mongo_manager.get_collection(self.collection_name)
            log = collection.find_one({
                "user_id": user_id,
                "session_id": session_id
            })

            if log:
                log["_id"] = str(log["_id"])

            return log

        except Exception as e:
            logger.error(f"Error fetching session log: {str(e)}")
            return None


# Global logger instance
interaction_logger = InteractionLogger()
