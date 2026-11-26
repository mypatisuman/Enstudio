"""
Storage layer for Indexing pipeline.

Provides:
  - mongo_src()  -> product-recommender DB (read-only source: vendors, documents, images)
  - mongo_dst()  -> (Restructured-A, Restructured-B) tuple for dual-cluster writes
  - AzureBlobManager  -> blob upload/download helpers
  - MongoDBFileManager -> upload_document_to_blob, upload_json_data, image cache helpers
  - get_available_vendors_from_mongodb, get_vendors_for_product_type

Env vars (from Indexing/.env or Backend/.env):
  MONGODB_URI                     -- cluster A (engenie)
  AZURE_STORAGE_CONNECTION_STRING
  AZURE_STORAGE_ACCOUNT_NAME
  AZURE_STORAGE_ACCOUNT_KEY
"""

import os
import re
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, BinaryIO

from dotenv import load_dotenv
from pymongo import MongoClient

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))          # repo root
load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"))                            # Indexing/.env  (GOOGLE keys)
load_dotenv(os.path.join(_ROOT, "Backend", ".env"), override=True)                  # Backend/.env    (MONGODB_URI, AZURE)

log = logging.getLogger(__name__)

CLUSTER_A = os.getenv("MONGODB_URI")


# ── connection helpers ────────────────────────────────────────────────────────

def mongo_src() -> Any:
    """Return Restructured DB (source: vendors, documents, images, specs)."""
    return MongoClient(CLUSTER_A, serverSelectionTimeoutMS=60000)["Restructured"]


def mongo_dst():
    """Return Restructured DB client."""
    a = MongoClient(CLUSTER_A, serverSelectionTimeoutMS=60000)["Restructured"]
    return a, a


# ── Azure Blob Manager ────────────────────────────────────────────────────────

class AzureBlobManager:
    """Azure Blob Storage operations for Indexing pipeline."""

    def __init__(self):
        self.account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self.account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        self.connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.blob_service_client = None

        if self.connection_string:
            try:
                from azure.storage.blob import BlobServiceClient
                self.blob_service_client = BlobServiceClient.from_connection_string(
                    self.connection_string)
                log.info("[AZURE] Blob service client initialized")
            except ImportError:
                log.warning("[AZURE] azure-storage-blob not installed")
            except Exception as e:
                log.warning("[AZURE] Failed to init blob client: %s", e)
        else:
            log.warning("[AZURE] AZURE_STORAGE_CONNECTION_STRING not set")

    # ── internal ──────────────────────────────────────────────────────────────

    def _ensure_container(self, name: str) -> bool:
        if not self.blob_service_client:
            return False
        try:
            cc = self.blob_service_client.get_container_client(name)
            if not cc.exists():
                cc.create_container()
                log.info("[AZURE] Created container: %s", name)
            return True
        except Exception as e:
            log.error("[AZURE] ensure_container %s failed: %s", name, e)
            return False

    def _upload(self, container: str, blob_name: str, data: bytes,
                content_type: str = "application/octet-stream") -> Dict[str, str]:
        from azure.storage.blob import ContentSettings
        self._ensure_container(container)
        bc = self.blob_service_client.get_blob_client(container=container, blob=blob_name)
        bc.upload_blob(data, overwrite=True,
                       content_settings=ContentSettings(content_type=content_type))
        url = f"https://{self.account_name}.blob.core.windows.net/{container}/{blob_name}"
        log.info("[AZURE] Uploaded %s/%s", container, blob_name)
        return {"storage": "azure_blob", "container": container,
                "blobName": blob_name, "blobUrl": url}

    # ── public upload helpers ─────────────────────────────────────────────────

    def ensure_containers_exist(self) -> Dict[str, bool]:
        containers = ["generic-images", "vendor-logos", "product-images",
                      "strategy-documents", "standards-documents",
                      "product-documents", "user-projects"]
        return {c: self._ensure_container(c) for c in containers}

    def upload_product_image(self, file_bytes: bytes, product_type_normalized: str,
                             vendor_name_normalized: str, model_family_normalized: str,
                             content_type: str = "image/jpeg") -> Dict[str, str]:
        blob_name = (f"{product_type_normalized}/{vendor_name_normalized}/"
                     f"{model_family_normalized}/{vendor_name_normalized}_{model_family_normalized}.jpeg")
        return self._upload("product-images", blob_name, file_bytes, content_type)

    def upload_vendor_logo(self, file_bytes: bytes, vendor_name_normalized: str,
                           content_type: str = "image/png") -> Dict[str, str]:
        return self._upload("vendor-logos",
                            f"{vendor_name_normalized}_logo.png", file_bytes, content_type)

    def upload_generic_image(self, file_bytes: bytes, product_type_normalized: str,
                             content_type: str = "image/png") -> Dict[str, str]:
        return self._upload("generic-images",
                            f"generic_{product_type_normalized}.png", file_bytes, content_type)

    def upload_strategy_document(self, file_bytes: bytes, filename: str,
                                 user_id: int, content_type: str = "application/pdf") -> Dict[str, str]:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return self._upload("strategy-documents",
                            f"user_{user_id}/{ts}_{filename}", file_bytes, content_type)

    def upload_standards_document(self, file_bytes: bytes, filename: str,
                                  user_id: int, content_type: str = "application/pdf") -> Dict[str, str]:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return self._upload("standards-documents",
                            f"user_{user_id}/{ts}_{filename}", file_bytes, content_type)

    def upload_product_document(self, file_bytes: bytes, product_type: str,
                                vendor_name: str, filename: str,
                                content_type: str = "application/pdf") -> Dict[str, str]:
        def _norm(s):
            return re.sub(r"[-\s]+", "_", re.sub(r"[^\w\s-]", "", s.lower().strip())).strip("_") or "unknown"
        blob_name = f"{_norm(product_type)}/{_norm(vendor_name)}/{filename}"
        return self._upload("product-documents", blob_name, file_bytes, content_type)

    def upload_project_data(self, project_json_bytes: bytes, user_id: int,
                            project_id: str, content_type: str = "application/json") -> Dict[str, str]:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return self._upload("user-projects",
                            f"user_{user_id}/project_{project_id}_{ts}.json",
                            project_json_bytes, content_type)

    def download_project_data(self, blob_info: Dict) -> bytes:
        bc = self.blob_service_client.get_blob_client(
            container=blob_info["container"], blob=blob_info["blobName"])
        return bc.download_blob().readall()

    def download_document_from_url(self, blob_url: str) -> bytes:
        if not self.account_name or self.account_name not in blob_url:
            raise ValueError(f"URL does not match account: {blob_url}")
        path = blob_url.replace(
            f"https://{self.account_name}.blob.core.windows.net/", "")
        container, blob_name = path.split("/", 1)
        bc = self.blob_service_client.get_blob_client(
            container=container, blob=blob_name)
        data = bc.download_blob().readall()
        log.info("[AZURE] Downloaded %d bytes from %s", len(data), blob_name)
        return data

    def get_blob_url(self, container: str, blob_name: str) -> str:
        return f"https://{self.account_name}.blob.core.windows.net/{container}/{blob_name}"

    def generate_sas_url(self, blob_url: str, expiry_hours: int = 1) -> Optional[str]:
        try:
            from azure.storage.blob import generate_blob_sas, BlobSasPermissions
            from datetime import timedelta
            if not self.account_key:
                return None
            path = blob_url.replace(
                f"https://{self.account_name}.blob.core.windows.net/", "")
            container, blob_name = path.split("/", 1)
            token = generate_blob_sas(
                account_name=self.account_name,
                container_name=container,
                blob_name=blob_name,
                account_key=self.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(hours=expiry_hours))
            return f"{blob_url}?{token}"
        except Exception as e:
            log.error("[AZURE] SAS generation failed: %s", e)
            return None

    def test_connection(self) -> Dict[str, Any]:
        result = {"connected": False, "account_name": self.account_name,
                  "has_connection_string": bool(self.connection_string),
                  "containers": [], "error": None}
        if not self.blob_service_client:
            result["error"] = "client not initialized"
            return result
        try:
            result["containers"] = [c.name for c in
                                    self.blob_service_client.list_containers()]
            result["connected"] = True
        except Exception as e:
            result["error"] = str(e)
        return result


# ── MongoDB File Manager ──────────────────────────────────────────────────────

class MongoDBFileManager:
    """High-level document/JSON storage backed by Azure Blob + MongoDB metadata."""

    def __init__(self, blob_mgr: AzureBlobManager):
        self._blob = blob_mgr
        self._src = mongo_src()

    def upload_document_to_blob(self, file_data: Union[str, bytes, BinaryIO],
                                metadata: Dict[str, Any]) -> str:
        if isinstance(file_data, str):
            with open(file_data, "rb") as f:
                data = f.read()
            filename = os.path.basename(file_data)
        elif isinstance(file_data, bytes):
            data = file_data
            filename = metadata.get("filename", "document.pdf")
        else:
            data = file_data.read()
            filename = metadata.get("filename", "document.pdf")

        collection_type = metadata.get("collection_type", "documents")
        content_type = metadata.get("file_type", "application/pdf")
        if not content_type.startswith(("application/", "image/", "text/")):
            content_type = {"pdf": "application/pdf", "json": "application/json",
                            "txt": "text/plain"}.get(content_type.lower(),
                                                     "application/octet-stream")

        if collection_type == "documents":
            blob_info = self._blob.upload_product_document(
                data, metadata.get("product_type", "unknown"),
                metadata.get("vendor_name", "unknown"), filename, content_type)
        elif collection_type == "strategy_documents":
            blob_info = self._blob.upload_strategy_document(
                data, filename, metadata.get("user_id", 0), content_type)
        elif collection_type == "standards_documents":
            blob_info = self._blob.upload_standards_document(
                data, filename, metadata.get("user_id", 0), content_type)
        else:
            blob_info = self._blob.upload_product_document(
                data, "uncategorized", "unknown", filename, content_type)

        doc = {
            "filename": filename,
            "product_type": metadata.get("product_type"),
            "vendor_name": metadata.get("vendor_name"),
            "model_family": metadata.get("model_family"),
            "collection_type": collection_type,
            "file_type": content_type,
            "file_size": len(data),
            "storage_type": "azure_blob",
            "container_name": blob_info.get("container"),
            "blob_url": blob_info.get("blobUrl"),
            "source_url": metadata.get("source_url"),
            "pdf_title": metadata.get("pdf_title"),
            "source": metadata.get("source"),
            "upload_date": datetime.utcnow(),
            "created_at": datetime.utcnow(),
        }
        result = self._src["documents"].insert_one(doc)
        log.info("[MONGO] Saved document metadata id=%s blob=%s",
                 result.inserted_id, blob_info.get("blobUrl"))
        return str(result.inserted_id)

    def upload_json_data(self, json_data: Dict[str, Any],
                         metadata: Dict[str, Any]) -> str:
        collection_name = metadata.get("collection_type", "vendors")
        doc = {
            "data": json_data,
            "product_type": metadata.get("product_type"),
            "vendor_name": metadata.get("vendor_name"),
            "file_type": "json",
            "metadata": {"upload_date": datetime.utcnow(), **metadata},
        }
        result = self._src[collection_name].insert_one(doc)
        log.info("[MONGO] Inserted JSON into %s id=%s", collection_name, result.inserted_id)
        return str(result.inserted_id)


# ── convenience query functions ───────────────────────────────────────────────

def get_available_vendors_from_mongodb() -> List[str]:
    src = mongo_src()
    vendors = [v for v in src["vendors"].distinct("vendor_name") if v and str(v).strip()]
    vendors.sort()
    log.info("[MONGO] %d vendors found", len(vendors))
    return vendors


def get_vendors_for_product_type(product_type: str) -> List[str]:
    try:
        src = mongo_src()
        words = [w for w in re.sub(r"[^a-z0-9 ]", " ",
                                   product_type.lower()).split() if len(w) > 2]
        if len(words) > 1:
            query = {"$and": [{"product_type": {"$regex": w, "$options": "i"}}
                               for w in words]}
        elif words:
            query = {"product_type": {"$regex": words[0], "$options": "i"}}
        else:
            query = {}
        vendors = [v for v in src["vendors"].distinct("vendor_name", query)
                   if v and str(v).strip()]
        vendors.sort()
        log.info("[MONGO] %d vendors for '%s'", len(vendors), product_type)
        return vendors
    except Exception as e:
        log.error("[MONGO] get_vendors_for_product_type failed: %s", e)
        return get_available_vendors_from_mongodb()


# ── image cache helpers ───────────────────────────────────────────────────────

def get_cached_image(vendor_name: str, model_family: str,
                     product_type: str) -> Optional[Dict[str, Any]]:
    try:
        src = mongo_src()
        nv = vendor_name.strip().lower().replace(" ", "_")
        nm = model_family.strip().lower().replace(" ", "_")
        np_ = product_type.strip().lower().replace(" ", "_")
        doc = src["images"].find_one(
            {"id": f"product_image_{np_}_{nv}_{nm}", "status": "active"})
        if doc and doc.get("image", {}).get("blobUrl"):
            return {"blob_url": doc["image"]["blobUrl"],
                    "content_type": doc.get("contentType", "image/jpeg"),
                    "file_size": doc.get("fileSize", 0),
                    "original_url": doc.get("metadata", {}).get("original_url"),
                    "cached": True}
        return None
    except Exception as e:
        log.error("[MONGO] get_cached_image failed: %s", e)
        return None


def cache_image(vendor_name: str, model_family: str, product_type: str,
                image_bytes: bytes, content_type: str,
                blob_info: Dict[str, str], source_url: str = "") -> bool:
    try:
        src = mongo_src()
        nv = vendor_name.strip().lower().replace(" ", "_")
        nm = model_family.strip().lower().replace(" ", "_")
        np_ = product_type.strip().lower().replace(" ", "_")
        doc_id = f"product_image_{np_}_{nv}_{nm}"
        doc = {
            "id": doc_id, "type": "product_model_image",
            "productType": product_type, "product_type_normalized": np_,
            "vendor_name": vendor_name, "vendor_name_normalized": nv,
            "model_family": model_family, "model_family_normalized": nm,
            "image": blob_info, "contentType": content_type,
            "fileSize": len(image_bytes),
            "createdAt": datetime.utcnow().isoformat(),
            "updatedAt": datetime.utcnow().isoformat(),
            "status": "active",
            "metadata": {"original_url": source_url, "is_primary": True,
                         "cached_at": datetime.utcnow().isoformat()},
        }
        r = src["images"].update_one({"id": doc_id}, {"$set": doc}, upsert=True)
        return bool(r.upserted_id or r.modified_count)
    except Exception as e:
        log.error("[MONGO] cache_image failed: %s", e)
        return False


# ── module-level singletons ───────────────────────────────────────────────────

azure_blob_manager = AzureBlobManager()
mongodb_file_manager = MongoDBFileManager(azure_blob_manager)
