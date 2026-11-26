"""
Azure Blob Storage Utilities
Handles all Azure Blob Storage operations for image uploads
"""

import logging
import os
from datetime import UTC, datetime
from typing import Any

import socket
import time

logger = logging.getLogger(__name__)

class StorageCircuitBreaker:
    """Circuit breaker for Azure Blob Storage to prevent minutes of hanging socket retries."""
    _open_hosts: dict[str, float] = {}
    _COOLDOWN_SECONDS: float = 60.0

    @classmethod
    def can_attempt(cls, host: str) -> bool:
        if not host:
            return False
        last_failed = cls._open_hosts.get(host)
        if last_failed and (time.time() - last_failed) < cls._COOLDOWN_SECONDS:
            return False
        return True

    @classmethod
    def record_failure(cls, host: str):
        if host:
            cls._open_hosts[host] = time.time()
            logger.warning(f"[CIRCUIT_BREAKER] Host '{host}' tripped. Fast-failing storage calls for {cls._COOLDOWN_SECONDS}s.")

    @classmethod
    def record_success(cls, host: str):
        if host and host in cls._open_hosts:
            del cls._open_hosts[host]

    @classmethod
    def check_dns(cls, host: str) -> bool:
        if not cls.can_attempt(host):
            return False
        try:
            socket.gethostbyname(host)
            cls.record_success(host)
            return True
        except Exception:
            cls.record_failure(host)
            return False

def standardize_image_background(file_bytes: bytes, target_format: str = "JPEG") -> bytes:
    """Removes background from image and pastes it on a pure white canvas."""
    try:
        import io

        from PIL import Image
        from rembg import remove

        logger.info("[AZURE_BLOB] Removing image background to standardize on white...")
        subject_only = remove(file_bytes)
        subject_image = Image.open(io.BytesIO(subject_only)).convert("RGBA")

        white_bg = Image.new("RGBA", subject_image.size, "WHITE")
        white_bg.paste(subject_image, (0, 0), subject_image)
        final_image = white_bg.convert("RGB")

        img_byte_arr = io.BytesIO()
        final_image.save(img_byte_arr, format=target_format)
        return img_byte_arr.getvalue()
    except Exception as e:
        logger.warning(f"[AZURE_BLOB] Failed to standardize image background, using original. Error: {e}")
        return file_bytes

class AzureBlobManager:
    """Manages Azure Blob Storage operations for images"""

    def __init__(self):
        self.account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self.account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        self.connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.blob_service_client = None

        # Parse account name and key from connection string if missing
        if self.connection_string and (not self.account_name or not self.account_key):
            try:
                pairs = self.connection_string.split(";")
                for pair in pairs:
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        k_strip = k.strip().lower()
                        if k_strip == "accountname" and not self.account_name:
                            self.account_name = v.strip()
                        elif k_strip == "accountkey" and not self.account_key:
                            self.account_key = v.strip()
                logger.info(f"[AZURE_BLOB] Extracted account name ({self.account_name}) and key from connection string fallback")
            except Exception as conn_err:
                logger.warning(f"[AZURE_BLOB] Failed to parse connection string fallback: {conn_err}")

        # Prioritize connection string authentication (current method)
        if self.connection_string:
            try:
                from azure.storage.blob import BlobServiceClient
                self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
                logger.info("[AZURE_BLOB] Blob service client initialized using connection string authentication")
            except ImportError:
                logger.warning("[AZURE_BLOB] azure-storage-blob not installed. Run: pip install azure-storage-blob")
            except Exception as e:
                logger.warning(f"[AZURE_BLOB] Failed to initialize blob client: {e}")

        if self.blob_service_client is None:
            logger.warning("[AZURE_BLOB] Azure Blob Storage not initialized - no valid credentials found")

    def test_connection(self) -> dict[str, Any]:
        """
        Test Azure Blob Storage connection

        Returns:
            Dict with connection status and details
        """
        result = {
            "connected": False,
            "account_name": self.account_name,
            "has_connection_string": bool(self.connection_string),
            "containers": [],
            "error": None
        }

        if not self.blob_service_client:
            result["error"] = "Blob service client not initialized"
            return result

        try:
            # List containers to verify connection
            containers = list(self.blob_service_client.list_containers())
            result["connected"] = True
            result["containers"] = [c.name for c in containers]
            logger.info(f"[AZURE_BLOB] ✓ Connection successful. Found {len(containers)} containers")
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"[AZURE_BLOB] ✗ Connection failed: {e}")

        return result

    def ensure_containers_exist(self) -> dict[str, bool]:
        """
        Ensure all required containers exist, create if they don't

        Returns:
            Dict of container names and their creation status
        """
        required_containers = [
            "generic-images",
            "vendor-logos",
            "product-images",
            "strategy-documents",
            "standards-documents",
            "assets-documents",  # Assets documents container
            "user-projects"  # Container for project JSON files
        ]

        results = {}

        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Cannot create containers - blob service client not initialized")
            return dict.fromkeys(required_containers, False)

        for container_name in required_containers:
            try:
                container_client = self.blob_service_client.get_container_client(container_name)

                # Check if exists, create if not
                if not container_client.exists():
                    container_client.create_container()
                    logger.info(f"[AZURE_BLOB] ✓ Created container: {container_name}")
                    results[container_name] = True
                else:
                    logger.info(f"[AZURE_BLOB] ✓ Container already exists: {container_name}")
                    results[container_name] = True

            except Exception as e:
                logger.error(f"[AZURE_BLOB] ✗ Failed to ensure container {container_name}: {e}")
                results[container_name] = False

        return results

    def _ensure_container_exists(self, container_name: str) -> bool:
        """
        Ensure a specific container exists, create if it doesn't

        Args:
            container_name: Name of the container to check/create

        Returns:
            bool: True if container exists or was created successfully
        """
        if not self.blob_service_client:
            logger.error(f"[AZURE_BLOB] Cannot ensure container {container_name} - blob service client not initialized")
            return False

        try:
            container_client = self.blob_service_client.get_container_client(container_name)

            # Check if exists, create if not
            if not container_client.exists():
                container_client.create_container()
                logger.info(f"[AZURE_BLOB] ✓ Auto-created container: {container_name}")
            else:
                logger.debug(f"[AZURE_BLOB] Container already exists: {container_name}")

            return True

        except Exception as e:
            logger.error(f"[AZURE_BLOB] ✗ Failed to ensure container {container_name}: {e}")
            return False

    def upload_generic_image(
        self,
        file_bytes: bytes,
        product_type_normalized: str,
        content_type: str = "image/png"
    ) -> dict[str, str] | None:
        """Upload generic product image to blob storage"""
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        try:
            from azure.storage.blob import ContentSettings

            # Standardize image background to pure white
            file_bytes = standardize_image_background(file_bytes, target_format="PNG")

            container_name = "generic-images"

            # Ensure container exists (auto-create if needed)
            if not self._ensure_container_exists(container_name):
                raise Exception(f"Failed to ensure container {container_name} exists")

            blob_name = f"generic_{product_type_normalized}.png"

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded generic image: {blob_url}")

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Generic image upload failed: {e}")
            raise


    def upload_file(self, file_bytes: bytes, filename: str, user_id: int, file_type: str) -> str:
        """Upload a user file to blob storage and return the blob URL.

        This is a lightweight helper used by CSV upload flows.
        """
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        from datetime import datetime

        from azure.storage.blob import ContentSettings

        type_to_container = {
            'strategy': 'strategy-documents',
            'assets': 'assets-documents',
            'standards': 'standards-documents',
            'pdf': 'assets-documents',
            'PDF': 'assets-documents',
            'json': 'assets-documents',
            'JSON': 'assets-documents',
        }

        container_name = type_to_container.get(file_type)
        if not container_name:
            raise Exception(f"Unknown file_type for upload: {file_type}")

        if not self._ensure_container_exists(container_name):
            raise Exception(f"Failed to ensure container {container_name} exists")

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        blob_name = f"user_{user_id}/files/{timestamp}_{filename}"

        blob_client = self.blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        blob_client.upload_blob(
            file_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/octet-stream")
        )

        blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"
        logger.info(f"[AZURE_BLOB] ✓ Uploaded {file_type} file: {blob_url}")
        return blob_url


    def upload_strategy_embeddings(
        self,
        embeddings_bytes: bytes,
        filename: str,
        user_id: int,
        content_type: str = "application/gzip"
    ) -> str:
        """Upload extracted strategy embeddings payload under a separate folder.

        Exclusively handles gzip-compressed payloads.
        Note: Per requirement, embeddings blob keeps the SAME filename as the original.
        """
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        from azure.storage.blob import ContentSettings

        container_name = "strategy-documents"
        if not self._ensure_container_exists(container_name):
            raise Exception(f"Failed to ensure container {container_name} exists")

        blob_name = f"user_{user_id}/embedding/{filename}"
        blob_client = self.blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        # Use longer timeout and concurrency for big embedding payloads
        blob_client.upload_blob(
            embeddings_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
            max_concurrency=10,
            timeout=3600,  # 60 minute overall timeout for huge local payloads
            connection_timeout=3600,
            read_timeout=3600
        )

        blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"
        logger.info(f"[AZURE_BLOB] ✓ Uploaded strategy embeddings ({len(embeddings_bytes) / (1024*1024):.2f} MB): {blob_url}")
        return blob_url


    def upload_assets_embeddings(
        self,
        embeddings_bytes: bytes,
        filename: str,
        user_id: int,
        content_type: str = "application/gzip"
    ) -> str:
        """Upload extracted assets embeddings payload under a separate folder.

        Exclusively handles gzip-compressed payloads.
        Note: Per requirement, embeddings blob keeps the SAME filename as the original.
        """
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        from azure.storage.blob import ContentSettings

        container_name = "assets-documents"
        if not self._ensure_container_exists(container_name):
            raise Exception(f"Failed to ensure container {container_name} exists")

        blob_name = f"user_{user_id}/embeddings/{filename}"
        blob_client = self.blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        # Use larger block size and longer timeout for big embedding payloads
        blob_client.upload_blob(
            embeddings_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
            max_concurrency=4,
            timeout=3600,  # 60 minute timeout for huge local payloads
            connection_timeout=3600,
            read_timeout=3600
        )

        blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"
        logger.info(f"[AZURE_BLOB] ✓ Uploaded assets embeddings ({len(embeddings_bytes) / (1024*1024):.2f} MB): {blob_url}")
        return blob_url

    def upload_vendor_logo(
        self,
        file_bytes: bytes,
        vendor_name_normalized: str,
        content_type: str = "image/png"
    ) -> dict[str, str] | None:
        """Upload vendor logo to blob storage"""
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        try:
            from azure.storage.blob import ContentSettings

            container_name = "vendor-logos"

            # Ensure container exists (auto-create if needed)
            if not self._ensure_container_exists(container_name):
                raise Exception(f"Failed to ensure container {container_name} exists")

            blob_name = f"{vendor_name_normalized}_logo.png"

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded vendor logo: {blob_url}")

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Vendor logo upload failed: {e}")
            raise

    def upload_product_image(
        self,
        file_bytes: bytes,
        product_type_normalized: str,
        vendor_name_normalized: str,
        model_family_normalized: str,
        content_type: str = "image/jpeg"
    ) -> dict[str, str] | None:
        """Upload product model image to blob storage"""
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        try:
            from azure.storage.blob import ContentSettings

            # Standardize image background to pure white
            file_bytes = standardize_image_background(file_bytes, target_format="JPEG")

            container_name = "product-images"

            # Ensure container exists (auto-create if needed)
            if not self._ensure_container_exists(container_name):
                raise Exception(f"Failed to ensure container {container_name} exists")

            blob_name = f"{product_type_normalized}/{vendor_name_normalized}/{model_family_normalized}/{vendor_name_normalized}_{model_family_normalized}.jpeg"

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded product image: {blob_url}")

            # Save metadata to MongoDB images collection for catalog lookups
            try:
                from datetime import datetime

                from common.infra.mongodb_config import get_mongodb_connection

                conn = get_mongodb_connection()
                images_collection = conn['collections']['images']

                image_doc = {
                    'id': f"{vendor_name_normalized}_{model_family_normalized}",
                    'vendor_name_normalized': vendor_name_normalized,
                    'model_family_normalized': model_family_normalized,
                    'product_type_normalized': product_type_normalized,
                    'image': {
                        'blobUrl': blob_url,
                        'container': container_name,
                        'blobName': blob_name,
                        'contentType': content_type
                    },
                    'status': 'active',
                    'storage': 'azure_blob',
                    'createdAt': datetime.now(UTC),
                    'updatedAt': datetime.now(UTC)
                }

                # Upsert to avoid duplicates
                images_collection.update_one(
                    {'id': image_doc['id']},
                    {'$set': image_doc},
                    upsert=True
                )

                logger.info(f"[AZURE_BLOB] ✓ Saved image metadata to MongoDB for {vendor_name_normalized}/{model_family_normalized}")
            except Exception as mongo_err:
                logger.warning(f"[AZURE_BLOB] Failed to save image metadata to MongoDB: {mongo_err}")
                # Don't fail the upload if MongoDB save fails

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Product image upload failed: {e}")
            raise

    def upload_strategy_document(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: int,
        content_type: str = "application/pdf"
    ) -> dict[str, str] | None:
        """Upload strategy document PDF to blob storage"""
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        try:
            from datetime import datetime

            from azure.storage.blob import ContentSettings

            container_name = "strategy-documents"

            # Ensure container exists (auto-create if needed)
            if not self._ensure_container_exists(container_name):
                raise Exception(f"Failed to ensure container {container_name} exists")

            blob_name = f"user_{user_id}/files/{filename}"

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded strategy document: {blob_url}")

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Strategy document upload failed: {e}")
            raise

    def upload_standards_document(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: int,
        content_type: str = "application/pdf"
    ) -> dict[str, str] | None:
        """Upload standards document PDF to blob storage"""
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        try:
            from datetime import datetime, UTC

            from azure.storage.blob import ContentSettings

            container_name = "standards-documents"

            # Ensure container exists (auto-create if needed)
            if not self._ensure_container_exists(container_name):
                raise Exception(f"Failed to ensure container {container_name} exists")

            # Create unique blob name: user_id/timestamp_filename
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            blob_name = f"user_{user_id}/{timestamp}_{filename}"

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded standards document: {blob_url}")

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Standards document upload failed: {e}")
            raise

    def upload_assets_document(self, file_bytes: bytes, filename: str, user_id: int, content_type: str = 'application/pdf') -> dict:
        """Upload assets document PDF to blob storage"""
        if not self.blob_service_client:
            logger.error("[AZURE_BLOB] Blob service client not available")
            raise Exception("Azure Blob Storage not configured")

        try:
            from datetime import datetime

            from azure.storage.blob import ContentSettings

            container_name = "assets-documents"

            # Ensure container exists (auto-create if needed)
            if not self._ensure_container_exists(container_name):
                raise Exception(f"Failed to ensure container {container_name} exists")

            blob_name = f"user_{user_id}/{filename}"

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_client.upload_blob(
                file_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded assets document: {blob_url}")

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Assets document upload failed: {e}")
            raise

    def upload_project_data(self, project_json_bytes: bytes, user_id: int, project_id: str, content_type: str = 'application/json') -> dict:
        """
        Upload project JSON data to Azure Blob Storage

        Args:
            project_json_bytes: Project data as JSON bytes
            user_id: User ID who owns the project
            project_id: Project ID
            content_type: MIME type (default: application/json)

        Returns:
            Dict with storage, container, blobName, blobUrl
        """
        try:
            container_name = "user-projects"

            # Ensure container exists
            self._ensure_container_exists(container_name)

            # Generate blob name with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            blob_name = f"user_{user_id}/project_{project_id}_{timestamp}.json"

            # Upload to blob storage
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            from azure.storage.blob import ContentSettings
            blob_client.upload_blob(
                project_json_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )

            # Construct blob URL
            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

            logger.info(f"[AZURE_BLOB] ✓ Uploaded project: {blob_url}")

            return {
                "storage": "azure_blob",
                "container": container_name,
                "blobName": blob_name,
                "blobUrl": blob_url
            }

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Project upload failed: {e}")
            raise

    def download_project_data(self, blob_info: dict) -> bytes:
        """
        Download project JSON data from Azure Blob Storage

        Args:
            blob_info: Dict with container and blobName keys

        Returns:
            Project data as bytes
        """
        try:
            container = blob_info['container']
            blob_name = blob_info['blobName']

            blob_client = self.blob_service_client.get_blob_client(
                container=container,
                blob=blob_name
            )

            blob_data = blob_client.download_blob().readall()
            logger.info(f"[AZURE_BLOB] ✓ Downloaded project: {blob_name}")

            return blob_data

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Project download failed: {e}")
            raise

    def download_document_from_url(self, blob_url: str, fallback_url: str | None = None) -> bytes:
        """
        Download document directly from Azure Blob Storage using SDK with fast-fail circuit breaker.
        """
        try:
            if not self.blob_service_client:
                raise Exception("Blob service client not initialized")

            # Fast check if account name matches and host is reachable
            host = f"{self.account_name}.blob.core.windows.net" if self.account_name else ""
            if not StorageCircuitBreaker.check_dns(host):
                raise Exception(f"Blob host '{host}' unreachable or circuit open")

            if self.account_name not in blob_url:
                raise Exception(f"Blob URL does not match account: {blob_url}")

            # Remove protocol and domain to get path
            path_part = blob_url.replace(f"https://{self.account_name}.blob.core.windows.net/", "")

            # Split into container and blob name
            parts = path_part.split('/', 1)
            if len(parts) != 2:
                raise Exception(f"Invalid blob URL format: {blob_url}")

            container_name = parts[0]
            blob_name = parts[1]

            logger.info(f"[AZURE_BLOB] Downloading from container={container_name}, blob={blob_name}")

            # Get blob client and download directly
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )

            blob_data = blob_client.download_blob().readall()
            StorageCircuitBreaker.record_success(host)
            logger.info(f"[AZURE_BLOB] ✓ Downloaded {len(blob_data)} bytes from {blob_name}")
            return blob_data

        except Exception as e:
            host = f"{self.account_name}.blob.core.windows.net" if self.account_name else ""
            if "Name or service not known" in str(e) or "Failed to resolve" in str(e):
                StorageCircuitBreaker.record_failure(host)

            if fallback_url and fallback_url.startswith(("http://", "https://")):
                logger.warning(f"[AZURE_BLOB] Blob download failed ({e}); re-fetching from source URL: {fallback_url}")
                try:
                    import requests as _requests
                    response = _requests.get(
                        fallback_url,
                        timeout=15,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"},
                    )
                    response.raise_for_status()
                    logger.info(f"[AZURE_BLOB] ✓ Recovered {len(response.content)} bytes via source URL fallback")
                    return response.content
                except Exception as fb_err:
                    logger.warning(f"[AZURE_BLOB] Fallback URL download also failed: {fb_err}")
            logger.error(f"[AZURE_BLOB] Document download failed: {e}")
            raise

    def delete_document_from_url(self, blob_url: str) -> None:
        """
        Delete a blob given its full URL.
        Safe to call for superseded uploads to prevent orphaned blobs from accumulating.
        """
        try:
            if not self.blob_service_client:
                raise Exception("Blob service client not initialized")

            if self.account_name not in blob_url:
                raise Exception(f"Blob URL does not match account: {blob_url}")

            path_part = blob_url.replace(f"https://{self.account_name}.blob.core.windows.net/", "")
            parts = path_part.split('/', 1)
            if len(parts) != 2:
                raise Exception(f"Invalid blob URL format: {blob_url}")

            container_name = parts[0]
            blob_name = parts[1]

            blob_client = self.blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name
            )
            blob_client.delete_blob(delete_snapshots="include")
            logger.info(f"[AZURE_BLOB] Deleted blob: {blob_name}")
        except Exception as e:
            logger.error(f"[AZURE_BLOB] Blob delete failed: {e}")
            raise

    def get_blob_url(self, container_name: str, blob_name: str) -> str:
        """Get public URL for blob"""
        return f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_name}"

    def generate_sas_url(self, blob_url: str, expiry_hours: int = 1) -> str | None:
        """Generate SAS URL for a blob"""
        try:
            from datetime import datetime, timedelta

            from azure.storage.blob import BlobSasPermissions, generate_blob_sas

            if not self.account_key:
                logger.error("Account key not available for SAS generation")
                return None

            # Parse blob URL to get container and blob name
            # URL format: https://<account>.blob.core.windows.net/<container>/<blob>
            if self.account_name not in blob_url:
                logger.error("Blob URL does not match account name")
                return None

            # Remove protocol and domain to get path
            path_part = blob_url.replace(f"https://{self.account_name}.blob.core.windows.net/", "")

            # Split into container and blob name (blob name might contain slashes)
            parts = path_part.split('/', 1)
            if len(parts) != 2:
                logger.error(f"Invalid blob URL format: {blob_url}")
                return None

            container_name = parts[0]
            blob_name = parts[1]

            sas_token = generate_blob_sas(
                account_name=self.account_name,
                container_name=container_name,
                blob_name=blob_name,
                account_key=self.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(UTC) + timedelta(hours=expiry_hours)
            )

            return f"{blob_url}?{sas_token}"

        except Exception as e:
            logger.error(f"Failed to generate SAS URL: {e}")
            return None
    def download_blob_by_url(self, blob_url: str) -> bytes:
        """Download a blob from ANY Azure Blob Storage URL.

        Unlike ``download_document_from_url`` this does NOT require the URL to
        belong to the currently configured storage account.  It parses the
        account, container and blob name from the URL and creates a one-off
        ``BlobClient`` using ``from_blob_url``.

        This is used by the image proxy endpoint to serve cloud-hosted images
        when the backend is running against local Azurite storage.
        """
        try:
            from urllib.parse import urlparse
            from azure.storage.blob import BlobClient

            parsed = urlparse(blob_url)
            if not parsed.hostname or 'blob.core.windows.net' not in parsed.hostname:
                raise ValueError(f"Not a valid Azure Blob URL: {blob_url}")

            # Extract account name from hostname (<account>.blob.core.windows.net)
            url_account_name = parsed.hostname.split('.')[0]

            # Path: /<container>/<blob_path>
            path_parts = parsed.path.lstrip('/').split('/', 1)
            if len(path_parts) != 2:
                raise ValueError(f"Invalid blob URL path: {blob_url}")

            container_name = path_parts[0]
            blob_name = path_parts[1]

            # If the URL matches our configured account, use the existing client
            if url_account_name == self.account_name and self.blob_service_client:
                blob_client = self.blob_service_client.get_blob_client(
                    container=container_name,
                    blob=blob_name
                )
                data = blob_client.download_blob().readall()
                logger.info(f"[AZURE_BLOB] Downloaded {len(data)} bytes via primary client: {blob_name}")
                return data

            # Otherwise build a one-off client from the URL.
            # Try cloud connection string env var first, then fall back to
            # anonymous access (which will fail for private containers but is
            # the best we can do without credentials).
            cloud_conn_str = os.getenv("AZURE_CLOUD_STORAGE_CONNECTION_STRING")
            if cloud_conn_str:
                from azure.storage.blob import BlobServiceClient
                cloud_client = BlobServiceClient.from_connection_string(cloud_conn_str)
                blob_client = cloud_client.get_blob_client(
                    container=container_name,
                    blob=blob_name
                )
            else:
                # Fall back to anonymous BlobClient from URL
                blob_client = BlobClient.from_blob_url(blob_url)

            data = blob_client.download_blob().readall()
            logger.info(f"[AZURE_BLOB] Downloaded {len(data)} bytes via cross-account client: {blob_name}")
            return data

        except Exception as e:
            logger.error(f"[AZURE_BLOB] Cross-account blob download failed for {blob_url}: {e}")
            raise

# Global instance
azure_blob_manager = AzureBlobManager()
