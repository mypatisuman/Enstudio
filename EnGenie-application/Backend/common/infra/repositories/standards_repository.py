"""Repository layer for standards documents in MongoDB/Cosmos DB."""

import logging
from typing import Any
from bson import ObjectId

from common.infra.mongodb_config import Collections, get_mongodb_connection
from common.infra.mongodb_utils import mongodb_retry
from common.models.standards import StandardsCatalog, StandardDocument, TechnicalSpecifications

logger = logging.getLogger(__name__)


def _get_collection():
    """Get MongoDB collection for standards documents."""
    conn = get_mongodb_connection()
    return conn['collections'][Collections.STANDARDS]


class StandardsRepository:
    """Repository handling standards document hydration, persistence, and specifications caching."""

    @staticmethod
    @mongodb_retry
    def get_catalog_for_user(user_id: int) -> StandardsCatalog:
        """Fetch all documents for a given user and reconstruct the StandardsCatalog."""
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
            logger.info(f"[StandardsRepository] Loaded {len(docs)} document(s) for user {user_id}")

            hydrated_docs = []
            for doc in docs:
                try:
                    hydrated_docs.append(StandardDocument.from_mongo(doc))
                except Exception as parse_err:
                    logger.error(f"[StandardsRepository] Failed to parse document '{doc.get('filename')}': {parse_err}")
            
            return StandardsCatalog(documents=hydrated_docs)
        except Exception as e:
            logger.error(f"[StandardsRepository] Failed to fetch catalog for user {user_id}: {e}", exc_info=True)
            return StandardsCatalog(documents=[])

    @staticmethod
    @mongodb_retry
    def save_document(doc: StandardDocument) -> bool:
        """Idempotently insert or update a standard document based on user_id and filename."""
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
                logger.info(f"[StandardsRepository] Idempotently updated document: '{doc.filename}' (ID: {existing['_id']})")
            else:
                result = collection.insert_one(mongo_payload)
                logger.info(f"[StandardsRepository] Inserted new document: '{doc.filename}' (ID: {result.inserted_id})")

            return True
        except Exception as e:
            logger.error(f"[StandardsRepository] Failed to save document '{doc.filename}': {e}", exc_info=True)
            return False

    @staticmethod
    @mongodb_retry
    def update_specifications(doc_id: str, specs: TechnicalSpecifications) -> bool:
        """Atomically update/cache only the structured specifications for a document by its ID."""
        try:
            collection = _get_collection()
            
            result = collection.update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": {
                    "technical_specifications": specs.model_dump(exclude_none=False)
                }}
            )
            
            success = result.modified_count > 0
            if success:
                logger.info(f"[StandardsRepository] Atomically cached technical specifications for document: '{doc_id}'")
            return True
        except Exception as e:
            logger.error(f"[StandardsRepository] Failed to update specs for document '{doc_id}': {e}", exc_info=True)
            return False
