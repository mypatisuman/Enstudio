"""Repository layer for strategy documents in MongoDB/Cosmos DB."""

import logging
from typing import Any
from bson import ObjectId

from common.infra.mongodb_config import Collections, get_mongodb_connection
from common.infra.mongodb_utils import mongodb_retry
from common.models.strategy import StrategyCatalog, StrategyDocument

logger = logging.getLogger(__name__)


def _get_collection():
    """Get MongoDB collection for strategy documents."""
    conn = get_mongodb_connection()
    return conn['collections'][Collections.STRATERGY]


class StrategyRepository:
    """Repository handling strategy document hydration, persistence, and dynamic metadata updates."""

    @staticmethod
    @mongodb_retry
    def get_catalog_for_user(user_id: int | str) -> StrategyCatalog:
        """Fetch all documents for a given user and reconstruct the StrategyCatalog."""
        try:
            collection = _get_collection()
            
            # Handle user_id as both int and string representation
            try:
                user_id_int = int(user_id)
                query = {"$or": [{"user_id": user_id}, {"user_id": user_id_int}]}
            except (ValueError, TypeError):
                query = {"user_id": user_id}

            # Fetch matching documents
            docs = list(collection.find(query))
            logger.info(f"[StrategyRepository] Loaded {len(docs)} document(s) for user {user_id}")

            hydrated_docs = []
            for doc in docs:
                try:
                    hydrated_docs.append(StrategyDocument.from_mongo(doc))
                except Exception as parse_err:
                    logger.error(f"[StrategyRepository] Failed to parse document '{doc.get('filename')}': {parse_err}")
            
            return StrategyCatalog(documents=hydrated_docs)
        except Exception as e:
            logger.error(f"[StrategyRepository] Failed to fetch catalog for user {user_id}: {e}", exc_info=True)
            return StrategyCatalog(documents=[])

    @staticmethod
    @mongodb_retry
    def save_document(doc: StrategyDocument) -> bool:
        """Idempotently insert or update a strategy document based on user_id and filename."""
        try:
            collection = _get_collection()
            
            existing = collection.find_one({
                "user_id": doc.user_id,
                "filename": doc.filename
            })

            mongo_payload = doc.to_mongo()

            if existing:
                collection.update_one(
                    {"_id": existing["_id"]},
                    {"$set": mongo_payload}
                )
                logger.info(f"[StrategyRepository] Idempotently updated document: '{doc.filename}' (ID: {existing['_id']})")
            else:
                result = collection.insert_one(mongo_payload)
                logger.info(f"[StrategyRepository] Inserted new document: '{doc.filename}' (ID: {result.inserted_id})")

            return True
        except Exception as e:
            logger.error(f"[StrategyRepository] Failed to save document '{doc.filename}': {e}", exc_info=True)
            return False

    @staticmethod
    @mongodb_retry
    def update_metadata(doc_id: str, fields: dict[str, Any]) -> bool:
        """Atomically update/cache metadata fields (e.g. status, entry_count, or storage URLs) for a document by its ID."""
        try:
            collection = _get_collection()
            
            result = collection.update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": fields}
            )
            
            success = result.modified_count > 0
            if success:
                logger.info(f"[StrategyRepository] Atomically updated metadata fields for document: '{doc_id}'")
            return True
        except Exception as e:
            logger.error(f"[StrategyRepository] Failed to update metadata for document '{doc_id}': {e}", exc_info=True)
            return False
