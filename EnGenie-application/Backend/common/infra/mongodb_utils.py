"""
MongoDB Helper Utilities for File Operations
Provides high-level functions for storing and retrieving files using Azure Blob Storage
"""

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any, BinaryIO

from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from common.infra.mongodb_config import get_mongodb_connection

logger = logging.getLogger(__name__)

# ============================================================================
# RESILIENCE: MONGO DB RETRY POLICY
# ============================================================================
# Transient network timeouts are common in Azure Cosmos DB (socket timeout).
# We retry with exponential backoff to handle these gracefully.
# ============================================================================
mongodb_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    # Retry on standard PyMongo errors including NetworkTimeout
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)

class MongoDBFileManager:
    """High-level file management for MongoDB with Azure Blob Storage"""

    def __init__(self):
        self.conn = get_mongodb_connection()
        self.collections = self.conn['collections']
        self.db = self.conn['database']  # Add database property for direct access

    # ==================== UPLOAD OPERATIONS ====================

    def upload_document_to_blob(self, file_path_or_data: str | bytes | BinaryIO,
                                 metadata: dict[str, Any]) -> str:
        """
        Upload document to Azure Blob Storage and save metadata to MongoDB

        Args:
            file_path_or_data: File path, bytes, or file-like object
            metadata: File metadata including collection_type, product_type, vendor_name, etc.

        Returns:
            str: MongoDB document ID
        """
        try:
            from common.infra.azure_blob import azure_blob_manager

            # Determine file data
            if isinstance(file_path_or_data, str):
                # File path
                with open(file_path_or_data, 'rb') as f:
                    file_data = f.read()
                filename = os.path.basename(file_path_or_data)
            elif isinstance(file_path_or_data, bytes):
                # Bytes data
                file_data = file_path_or_data
                filename = metadata.get('filename', 'unknown_file')
            else:
                # File-like object
                file_data = file_path_or_data.read()
                filename = metadata.get('filename', 'unknown_file')

            # Determine content type
            content_type = metadata.get('file_type', 'application/pdf')
            if not content_type.startswith('application/') and not content_type.startswith('image/'):
                # If just 'pdf', convert to 'application/pdf'
                content_type_map = {
                    'pdf': 'application/pdf',
                    'json': 'application/json',
                    'txt': 'text/plain',
                    'doc': 'application/msword',
                    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                }
                content_type = content_type_map.get(content_type.lower(), 'application/octet-stream')

            # Determine collection type (documents, strategy, standards, etc.)
            collection_type = metadata.get('collection_type', 'documents')

            # Upload to appropriate Azure Blob container based on collection type
            blob_info = None

            if collection_type == 'documents':
                # Product documents go to product-documents container
                product_type = metadata.get('product_type', 'unknown')
                vendor_name = metadata.get('vendor_name', 'unknown')

                # Normalize names for folder structure
                def normalize(name):
                    name = name.lower().strip()
                    name = re.sub(r'[^\w\s-]', '', name)
                    name = re.sub(r'[-\s]+', '_', name)
                    return name.strip('_') or 'unknown'

                product_type_norm = normalize(product_type)
                vendor_norm = normalize(vendor_name)

                # Create blob path: product-documents/{product_type}/{vendor}/{filename}
                container_name = 'product-documents'
                blob_name = f"{product_type_norm}/{vendor_norm}/{filename}"

                # Upload using blob manager
                blob_client = azure_blob_manager.blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_name
                )

                from azure.storage.blob import ContentSettings
                blob_client.upload_blob(
                    file_data,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type)
                )

                blob_url = f"https://{azure_blob_manager.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

                blob_info = {
                    'storage': 'azure_blob',
                    'container': container_name,
                    'blobName': blob_name,
                    'blobUrl': blob_url
                }

            elif collection_type == 'strategy_documents':
                # Strategy documents
                user_id = metadata.get('uploaded_by_user_id', metadata.get('user_id', 0))
                blob_info = azure_blob_manager.upload_strategy_document(
                    file_data, filename, user_id, content_type
                )

            elif collection_type == 'standards_documents':
                # Standards documents
                user_id = metadata.get('uploaded_by_user_id', metadata.get('user_id', 0))
                blob_info = azure_blob_manager.upload_standards_document(
                    file_data, filename, user_id, content_type
                )

            elif collection_type == 'assets_documents':
                # Assets documents
                user_id = metadata.get('uploaded_by_user_id', metadata.get('user_id', 0))
                blob_info = azure_blob_manager.upload_assets_document(
                    file_data, filename, user_id, content_type
                )

            else:
                # Fallback: upload to generic documents container
                logger.warning(f"Unknown collection_type '{collection_type}', uploading to product-documents")
                container_name = 'product-documents'
                blob_name = f"uncategorized/{filename}"

                blob_client = azure_blob_manager.blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_name
                )

                from azure.storage.blob import ContentSettings
                blob_client.upload_blob(
                    file_data,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type)
                )

                blob_url = f"https://{azure_blob_manager.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

                blob_info = {
                    'storage': 'azure_blob',
                    'container': container_name,
                    'blobName': blob_name,
                    'blobUrl': blob_url
                }

            # Save metadata to MongoDB documents collection
            document_data = {
                'filename': filename,
                'product_type': metadata.get('product_type'),
                'vendor_name': metadata.get('vendor_name'),
                'model_family': metadata.get('model_family'),
                'collection_type': collection_type,
                'file_type': content_type,
                'file_size': len(file_data),

                # Azure Blob Storage info
                'storage_type': 'azure_blob',
                'container_name': blob_info.get('container'),
                'blob_url': blob_info.get('blobUrl'),

                # Additional metadata
                'source_url': metadata.get('source_url'),
                'pdf_title': metadata.get('pdf_title'),
                'source': metadata.get('source'),
                'uploaded_by_username': metadata.get('uploaded_by_username'),
                'uploaded_by_user_id': metadata.get('uploaded_by_user_id'),

                # Timestamps
                'upload_date': datetime.now(UTC),
                'created_at': datetime.now(UTC),
                'updated_at': datetime.now(UTC)
            }

            # Insert into appropriate MongoDB collection
            target_collection = self.db[collection_type] if collection_type in ['stratergy', 'standards', 'assets'] else self.db['documents']
            result = target_collection.insert_one(document_data)
            doc_id = str(result.inserted_id)

            logger.info(f"Successfully uploaded document to Azure Blob: {filename} -> {blob_info.get('blobUrl')}")
            logger.info(f"Saved metadata to MongoDB collection '{target_collection.name}' with ID: {doc_id}")

            return doc_id

        except Exception as e:
            logger.error(f"Failed to upload document to Azure Blob Storage: {e}")
            raise

    @mongodb_retry
    def upload_json_data(self, json_data: dict[str, Any], metadata: dict[str, Any]) -> str:
        """
        Upload JSON data to MongoDB

        Args:
            json_data: JSON data to store
            metadata: Metadata including collection_type, product_type, vendor_name, etc.

        Returns:
            str: Document ID
        """
        try:
            collection_type = metadata.get('collection_type', 'documents')
            collection = self.collections[collection_type]

            # Add standard metadata
            document = {
                'data': json_data,
                'metadata': {
                    'upload_date': datetime.now(UTC),
                    **metadata
                },
                'product_type': metadata.get('product_type'),
                'vendor_name': metadata.get('vendor_name'),
                'file_type': 'json'
            }

            # Insert document
            result = collection.insert_one(document)
            doc_id = str(result.inserted_id)

            logger.info(f"Successfully uploaded JSON data to MongoDB collection '{collection_type}' (ID: {doc_id})")
            return doc_id

        except Exception as e:
            logger.error(f"Failed to upload JSON data to MongoDB: {e}")
            raise

    # ==================== RETRIEVAL OPERATIONS ====================

    @mongodb_retry
    def get_json_data_from_mongodb(self, collection_name: str, query: dict[str, Any]) -> dict[str, Any] | None:
        """
        Retrieve JSON data from MongoDB collection

        Args:
            collection_name: Collection name
            query: Query to find the document

        Returns:
            Dict: JSON data or None if not found
        """
        try:
            collection = self.collections.get(collection_name)
            if collection is None:
                logger.error(f"Collection '{collection_name}' not found")
                return None

            document = collection.find_one(query)
            if document:
                # Handle both new format (with 'data' field) and legacy format
                if 'data' in document:
                    return document['data']
                else:
                    # Legacy format or direct storage - return the document minus MongoDB metadata
                    return {k: v for k, v in document.items() if k not in ['_id', 'metadata']}

            return None

        except Exception as e:
            logger.error(f"Failed to retrieve JSON data from MongoDB: {e}")
            raise

    def get_schema_from_mongodb(self, product_type: str) -> dict[str, Any] | None:
        """
        Retrieve the 3-tier requirements schema (essential/optional/latest) for a
        product type from the Restructured 5-tier hierarchy.

        PRIMARY path delegates to ``ProductHierarchyRepository.resolve_parameters_schema_by_name``,
        which reads the runtime source-of-truth collection (``RestructuredCollections.HIERARCHY``
        == ``catalog_hierarchy``) and cascade-resolves the matched node's own `parameters`
        plus all inherited ancestor fields (L2 -> L1 -> L0). This is the single, shared
        cascade used across the system; the inline traversal below is kept ONLY as a
        fallback for the legacy ``unified_product_hierarchy`` collection.

        Args:
            product_type: Product type / sub-type / category name to get schema for

        Returns:
            Dict: Schema data formatted as:
                  {
                      "mandatoryRequirements": { ... },
                      "optionalRequirements": { ... },
                      "latestRequirements":   { ... }
                  }
                  or None if not found.
        """
        # PRIMARY — delegate to the shared repository cascade (catalog_hierarchy).
        try:
            from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository
            resolved = ProductHierarchyRepository.resolve_parameters_schema_by_name(product_type)
            if resolved and (resolved.get("mandatoryRequirements")
                             or resolved.get("optionalRequirements")
                             or resolved.get("latestRequirements")):
                logger.info(
                    f"[SCHEMA] Resolved '{product_type}' from 5-tier (catalog_hierarchy): "
                    f"{len(resolved.get('mandatoryRequirements', {}))} mandatory / "
                    f"{len(resolved.get('optionalRequirements', {}))} optional / "
                    f"{len(resolved.get('latestRequirements', {}))} latest"
                )
                return resolved
            logger.info(f"[SCHEMA] No parameters in catalog_hierarchy for '{product_type}'; "
                        f"falling back to legacy unified_product_hierarchy cascade")
        except Exception as e:
            logger.warning(f"[SCHEMA] Repository cascade failed for '{product_type}': {e}; "
                           f"falling back to legacy cascade")

        # FALLBACK — legacy inline cascade against unified_product_hierarchy.
        try:
            # Import dynamically to avoid circular references
            from common.infra.mongodb_config import get_restructured_db
            db = get_restructured_db()
            H = db["unified_product_hierarchy"]

            # find the target node by name (L0/L1/L2). A name can exist at multiple
            # levels (e.g. an L1 'Pressure Transmitter' and a like-named empty L2) —
            # prefer the match that actually carries its own specifications.
            matches = list(H.find({
                "level": {"$in": ["L0", "L1", "L2"]},
                "name": {"$regex": f"^{re.escape(product_type)}$", "$options": "i"}
            }))
            if not matches:
                matches = list(H.find({
                    "level": {"$in": ["L0", "L1", "L2"]},
                    "name": {"$regex": re.escape(product_type), "$options": "i"}
                }).limit(10))
            if not matches:
                return self._auto_index_schema_fallback(product_type)

            def _own_count(n):
                return sum(len(v) for v in (n.get("parameters") or {}).values() if isinstance(v, dict))
            node = max(matches, key=_own_count)

            # build the ancestry chain (node -> parent -> grandparent) via parent_id
            chain, cur, seen = [], node, set()
            while cur and cur["_id"] not in seen:
                chain.append(cur)
                seen.add(cur["_id"])
                pid = cur.get("parent_id")
                cur = H.find_one({"_id": pid}) if pid else None

            def _own(n):
                """(mandatory, optional, latest) {name: value} maps from the node's parameters.
                Values are null for Equipment, enriched (most-common vendor value) for Accessory."""
                sp = n.get("parameters") or {}
                return (dict(sp.get("mandatoryRequirements") or {}),
                        dict(sp.get("optionalRequirements") or {}),
                        dict(sp.get("latestRequirements") or {}))

            # Dynamic Schema Cascade via traversal:
            #   own mandatory -> mandatoryRequirements
            #   own optional  -> optionalRequirements
            #   own latest    -> latestRequirements (Advanced)
            #   ALL inherited (parent + grandparent, any tier) -> optionalRequirements
            #   (inherited added only if not already present anywhere; values preserved)
            om, oo, ol = _own(chain[0])
            mandatory, optional, latest = dict(om), dict(oo), dict(ol)
            for ancestor in chain[1:]:
                am, ao, al = _own(ancestor)
                for k, v in {**am, **ao, **al}.items():
                    if k not in mandatory and k not in optional and k not in latest:
                        optional[k] = v

            if mandatory or optional or latest:
                return {"mandatoryRequirements": mandatory,
                        "optionalRequirements": optional,
                        "latestRequirements": latest}
            # Node matched but carries no parameters anywhere — still a miss.
            return self._auto_index_schema_fallback(product_type)

        except Exception as e:
            logger.error(f"Failed to retrieve schema from Restructured MongoDB: {e}")
            raise

    def _auto_index_schema_fallback(self, product_type: str) -> dict[str, Any] | None:
        """AUTO-INDEXING FALLBACK — called only after ALL schema lookup cascades
        (catalog_hierarchy repository + legacy unified_product_hierarchy) missed.

        Best-effort self-healing: records the miss, harvests a datasheet PDF,
        LLM-extracts a requirements schema and persists it into the 5-tier
        hierarchy so the current and future searches succeed. Guarded by the
        missing_product_types circuit breaker and a per-type lock (inside the
        indexer); any failure degrades to the original not-found behavior.
        """
        try:
            from domain.search.services.pdf_schema_indexer import index_and_persist_pdf_schema
            logger.info(
                f"[AUTO_INDEX] TRIGGERED (schema level) for '{product_type}' — "
                f"all schema lookup cascades missed, starting PDF schema indexer..."
            )
            schema = index_and_persist_pdf_schema(product_type)
            if schema and (schema.get("mandatoryRequirements")
                           or schema.get("optionalRequirements")
                           or schema.get("latestRequirements")):
                logger.info(
                    f"[AUTO_INDEX] SUCCESS (schema level) for '{product_type}': "
                    f"{len(schema.get('mandatoryRequirements', {}))} mandatory / "
                    f"{len(schema.get('optionalRequirements', {}))} optional / "
                    f"{len(schema.get('latestRequirements', {}))} latest"
                )
                return schema
            logger.info(
                f"[AUTO_INDEX] NO SCHEMA (schema level) for '{product_type}' — "
                f"indexer skipped (cooldown) or failed, returning not-found "
                f"(see [PDF_SCHEMA_INDEXER] logs above for the cause)"
            )
        except Exception as e:
            logger.warning(
                f"[AUTO_INDEX] ERROR (schema level) for '{product_type}' "
                f"(non-fatal, degrades to not-found): {e}"
            )
        return None

    # ==================== QUERY OPERATIONS ====================

    def list_files(self, collection_name: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        List files in a collection with optional filters

        Args:
            collection_name: Collection name
            filters: Optional filters to apply

        Returns:
            List of file metadata
        """
        try:
            metadata_collection_name = f"{collection_name}_metadata"
            metadata_collection = self.collections.get(metadata_collection_name)

            if metadata_collection is None:
                return []

            query = filters or {}
            cursor = metadata_collection.find(query)

            return list(cursor)

        except Exception as e:
            logger.error(f"Failed to list files from MongoDB: {e}")
            return []

    def file_exists(self, collection_name: str, query: dict[str, Any]) -> bool:
        """
        Check if file exists in MongoDB

        Args:
            collection_name: Collection name
            query: Query to check

        Returns:
            bool: True if file exists
        """
        try:
            metadata_collection_name = f"{collection_name}_metadata"
            metadata_collection = self.collections.get(metadata_collection_name)

            if metadata_collection is not None:
                return metadata_collection.find_one(query) is not None

            return False

        except Exception as e:
            logger.error(f"Failed to check file existence in MongoDB: {e}")
            return False

# Global instance
mongodb_file_manager = MongoDBFileManager()

# ==================== CONVENIENCE FUNCTIONS ====================

def upload_document_to_blob(file_path_or_data: str | bytes | BinaryIO, metadata: dict[str, Any]) -> str:
    """Convenience function for uploading documents to Azure Blob Storage"""
    return mongodb_file_manager.upload_document_to_blob(file_path_or_data, metadata)

def get_schema_from_mongodb(product_type: str) -> dict[str, Any] | None:
    """Convenience function for retrieving schemas"""
    return mongodb_file_manager.get_schema_from_mongodb(product_type)

def upload_json_to_mongodb(json_data: dict[str, Any], metadata: dict[str, Any]) -> str:
    """Convenience function for uploading JSON data"""
    return mongodb_file_manager.upload_json_data(json_data, metadata)

def get_json_from_mongodb(collection_name: str, query: dict[str, Any]) -> dict[str, Any] | None:
    """Convenience function for retrieving JSON data"""
    return mongodb_file_manager.get_json_data_from_mongodb(collection_name, query)

# ==================== IMAGE CACHING FUNCTIONS ====================

def download_image_from_url(url: str, timeout: int = 30) -> tuple | None:
    """
    Download image from URL and return binary data with metadata

    Args:
        url: Image URL to download
        timeout: Request timeout in seconds

    Returns:
        Tuple of (image_data: bytes, content_type: str, file_size: int) or None if failed
    """
    try:
        import requests

        # Validate URL scheme - reject unsupported schemes
        if not url or not isinstance(url, str):
            logger.warning(f"Invalid URL provided: {url}")
            return None

        # Check for unsupported URL schemes
        unsupported_schemes = ['x-raw-image://', 'data:', 'blob:', 'chrome://', 'about:']
        if any(url.startswith(scheme) for scheme in unsupported_schemes):
            logger.warning(f"Unsupported URL scheme, skipping: {url}")
            return None

        # Ensure URL starts with http:// or https://
        if not url.startswith(('http://', 'https://')):
            logger.warning(f"URL must start with http:// or https://, got: {url}")
            return None

        # Add headers to appear like a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }

        logger.info(f"Downloading image from: {url}")
        response = requests.get(url, timeout=timeout, headers=headers, stream=True)
        response.raise_for_status()

        # Get content type
        content_type = response.headers.get('content-type', 'image/jpeg').lower()

        # Validate it's an image
        if 'image' not in content_type:
            logger.warning(f"URL does not return an image: {url} (content-type: {content_type})")
            return None

        # Download image data
        image_data = b''
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                image_data += chunk

        file_size = len(image_data)

        # Validate minimum size (avoid empty or corrupt images)
        if file_size < 100:  # Less than 100 bytes is suspicious
            logger.warning(f"Downloaded image is too small ({file_size} bytes): {url}")
            return None

        logger.info(f"Successfully downloaded image: {file_size} bytes, type: {content_type}")
        return (image_data, content_type, file_size)

    except requests.Timeout:
        logger.error(f"Timeout downloading image from: {url}")
        return None
    except requests.RequestException as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading image from {url}: {e}")
        return None

def get_cached_image(vendor_name: str, model_family: str, product_type: str) -> dict[str, Any] | None:
    """
    Retrieve cached product image from MongoDB (with Blob URL)

    Args:
        vendor_name: Vendor/manufacturer name
        model_family: Model family name
        product_type: Product type

    Returns:
        Dict containing image metadata with blob URL or None if not found
    """
    try:
        images_collection = mongodb_file_manager.collections['images']

        # Normalize search keys
        def clean_name(name):
            name = name.lower().strip()
            name = re.sub(r'[^\w\s-]', '', name)
            name = re.sub(r'[-\s]+', '_', name)
            return name.strip('_')

        normalized_vendor = clean_name(vendor_name)
        normalized_model = clean_name(model_family)

        logger.info(f"[get_cached_image] Searching for image: vendor='{vendor_name}' (normalized: '{normalized_vendor}'), model='{model_family}' (normalized: '{normalized_model}')")

        # Don't restrict rigidly by normalized_product_type. The scraping process dynamically classifies
        # products, often naming them differently than the generic categories passed from the UI catalog mapping.
        query = {
            'vendor_name_normalized': normalized_vendor,
            'model_family_normalized': normalized_model,
            'status': 'active'
        }

        # If we failed to find one with the exact normalized keys, we can try regex fallbacks
        cached_image = images_collection.find_one(query)

        # Fallback 1: Broad regex search on ID utilizing the vendor and model
        if not cached_image:
            logger.info("[get_cached_image] Exact match not found, trying regex fallback")
            # Security: Use re.escape() to prevent regex injection attacks
            safe_vendor = re.escape(normalized_vendor)
            safe_model = re.escape(normalized_model)
            fallback_query = {
                'id': {'$regex': f'{safe_vendor}.*{safe_model}', '$options': 'i'},
                'status': 'active'
            }
            cached_image = images_collection.find_one(fallback_query)

            # Fallback 2: Try with partial model name match
            if not cached_image:
                logger.info("[get_cached_image] Regex fallback failed, trying partial match")
                partial_query = {
                    'vendor_name_normalized': normalized_vendor,
                    'model_family_normalized': {'$regex': safe_model, '$options': 'i'},
                    'status': 'active'
                }
                cached_image = images_collection.find_one(partial_query)

        if cached_image and cached_image.get('image', {}).get('blobUrl'):
            logger.info(f"[get_cached_image] ✓ Found cached image in Blob Storage for {vendor_name} - {model_family}")
            # Return image metadata with Blob URL
            return {
                'blob_url': cached_image['image']['blobUrl'],
                'title': cached_image.get('metadata', {}).get('original_url', ''),
                'source': cached_image.get('metadata', {}).get('source'),
                'content_type': cached_image.get('contentType', 'image/jpeg'),
                'file_size': cached_image.get('fileSize', 0),
                'original_url': cached_image.get('metadata', {}).get('original_url'),
                'cached': True
            }

        logger.warning(f"[get_cached_image] ✗ No image found for {vendor_name} - {model_family} after all fallback attempts")
        return None

    except Exception as e:
        logger.error(f"Failed to retrieve cached image: {e}")
        return None

def cache_image(vendor_name: str, model_family: str, product_type: str, image_data: dict[str, Any]) -> bool:
    """
    Download and store product image in Azure Blob Storage + MongoDB

    Args:
        vendor_name: Vendor/manufacturer name
        model_family: Model family name
        product_type: Product type (e.g., "Pressure Transmitter")
        image_data: Image data dict containing url, title, source, etc.

    Returns:
        bool: True if successfully cached
    """
    try:
        images_collection = mongodb_file_manager.collections['images']

        # Get image URL
        image_url = image_data.get('url')
        if not image_url:
            logger.warning(f"No URL provided for image caching: {vendor_name} - {model_family}")
            return False

        # Download the actual image
        download_result = download_image_from_url(image_url)
        if not download_result:
            logger.warning(f"Failed to download image from {image_url}, skipping cache")
            return False

        image_bytes, content_type, file_size = download_result

        # Normalize keys for indexing
        normalized_vendor = vendor_name.strip().lower().replace(' ', '_')
        normalized_model = model_family.strip().lower().replace(' ', '_')
        normalized_product_type = product_type.strip().lower().replace(' ', '_')

        # Upload to Azure Blob Storage
        blob_info = azure_blob_manager.upload_product_image(
            file_bytes=image_bytes,
            product_type_normalized=normalized_product_type,
            vendor_name_normalized=normalized_vendor,
            model_family_normalized=normalized_model,
            content_type=content_type
        )

        logger.info(f"Uploaded product image to Blob Storage for {vendor_name} - {model_family}")

        # Store metadata in product_images collection with new schema
        image_doc = {
            "id": f"product_image_{normalized_product_type}_{normalized_vendor}_{normalized_model}",
            "type": "product_model_image",
            "productType": product_type,
            "product_type_normalized": normalized_product_type,
            "vendor_name": vendor_name,
            "vendor_name_normalized": normalized_vendor,
            "model_family": model_family,
            "model_family_normalized": normalized_model,
            "image": blob_info,
            "contentType": content_type,
            "fileSize": file_size,
            "createdAt": datetime.now(UTC).isoformat(),
            "updatedAt": datetime.now(UTC).isoformat(),
            "status": "active",
            "metadata": {
                "source": image_data.get('source', ''),
                "uploaded_by_user_id": None,
                "uploaded_by_username": None,
                "search_query": f"{vendor_name} {model_family} {product_type}",
                "original_url": image_url,
                "is_primary": True,
                "cached_at": datetime.now(UTC).isoformat()
            }
        }

        # Upsert keyed on the collection's UNIQUE index
        # (vendor_name_normalized, model_family_normalized) — NOT on `id`,
        # which embeds product_type: the same vendor+model cached under a
        # second product type produced a different id, so the upsert tried to
        # insert and hit a duplicate-key violation (log session 2026-08-04).
        result = images_collection.update_one(
            {
                'vendor_name_normalized': normalized_vendor,
                'model_family_normalized': normalized_model,
            },
            {'$set': image_doc},
            upsert=True
        )

        if result.upserted_id or result.modified_count > 0:
            logger.info(f"Successfully cached image in Blob Storage for {vendor_name} - {model_family}")
            return True

        return False

    except Exception as e:
        logger.error(f"Failed to cache image in Blob Storage: {e}")
        return False

def get_available_vendors_from_mongodb() -> list[str]:
    """
    Get list of all available vendor names from MongoDB.
    """
    try:
        conn = get_mongodb_connection()
        products_collection = conn['collections']['vendors']

        # Get distinct vendor names from products collection
        vendor_names = products_collection.distinct("vendor_name")

        # Filter out None/empty values and sort
        valid_vendors = [vendor for vendor in vendor_names if vendor and str(vendor).strip()]
        valid_vendors.sort()

        logger.info(f"Retrieved {len(valid_vendors)} vendors from MongoDB")
        return valid_vendors

    except Exception as e:
        logger.error(f"Failed to get vendors from MongoDB: {e}")
        return []

def get_vendors_for_product_type(product_type: str) -> list[str]:
    """
    Get list of vendor names that have products for the specified product type.

    Uses full-phrase OR queries so that "Temperature Sensor" finds vendors for
    both "temperature sensor" AND "temperature transmitter" products — because
    the same vendors supply both and the DB may store either phrase.
    """
    # Sensor/transmitter equivalence map — searching for one also searches the other
    _INSTRUMENT_COUNTERPARTS = {
        'sensor': 'transmitter',
        'transmitter': 'sensor',
        'meter': 'transmitter',
    }

    try:
        conn = get_mongodb_connection()
        vendors_collection = conn['collections']['vendors']

        pt_lower = product_type.lower().strip()

        # Split product type into base word(s) + instrument word
        # e.g. "Temperature Sensor" → base="temperature", instrument="sensor"
        parts = pt_lower.split()
        instrument_word = None
        base_parts = []
        for part in parts:
            if part in _INSTRUMENT_COUNTERPARTS:
                instrument_word = part
            else:
                base_parts.append(part)

        base = ' '.join(base_parts)  # e.g. "temperature", "flow", "pressure"

        # Build OR query: match the exact phrase AND its sensor/transmitter counterpart
        # e.g. "Temperature Sensor" → "temperature sensor" OR "temperature transmitter"
        if instrument_word and base:
            counterpart = _INSTRUMENT_COUNTERPARTS[instrument_word]
            phrase1 = re.escape(f"{base} {instrument_word}")
            phrase2 = re.escape(f"{base} {counterpart}")
            query = {
                '$or': [
                    {'product_type': {'$regex': phrase1, '$options': 'i'}},
                    {'product_type': {'$regex': phrase2, '$options': 'i'}},
                ]
            }
            logger.info(f"[VENDOR_LOADING] Searching for '{base} {instrument_word}' OR '{base} {counterpart}'")
        else:
            # No instrument word (e.g. "RTD") — just use the full phrase
            query = {'product_type': {'$regex': re.escape(pt_lower), '$options': 'i'}}
            logger.info(f"[VENDOR_LOADING] Searching for product type phrase: '{pt_lower}'")

        # Get distinct vendor names from matching documents
        vendor_names = vendors_collection.distinct("vendor_name", query)

        # Broad fallback: if still empty, search by base word alone
        if not vendor_names and base:
            logger.info(f"[VENDOR_LOADING] Phrase query returned 0 vendors, falling back to base term '{base}'")
            vendor_names = vendors_collection.distinct(
                "vendor_name",
                {'product_type': {'$regex': re.escape(base), '$options': 'i'}}
            )

        # Filter out None/empty values and sort
        valid_vendors = [vendor for vendor in vendor_names if vendor and str(vendor).strip()]
        valid_vendors.sort()

        logger.info(f"Retrieved {len(valid_vendors)} vendors for product type '{product_type}': {valid_vendors[:10]}...")
        return valid_vendors

    except Exception as e:
        logger.error(f"Failed to get vendors for product type '{product_type}': {e}")
        # Fallback to all vendors
        return get_available_vendors_from_mongodb()


# ==================== AZURE BLOB STORAGE IMPORT ====================
# Azure Blob Storage utilities are now in a separate file
from common.infra.azure_blob import azure_blob_manager

