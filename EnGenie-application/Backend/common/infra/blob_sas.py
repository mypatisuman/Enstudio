"""
Universal SAS Token Generator for Azure Blob URLs
Generates time-limited SAS token URLs for any blob stored in Azure
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


import base64

def _generate_svg_placeholder(name: str, is_logo: bool = False) -> str:
    if is_logo:
        initial = name[0].upper() if name else "V"
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120">
            <defs>
                <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#0f172a" />
                    <stop offset="100%" stop-color="#1e293b" />
                </linearGradient>
            </defs>
            <rect width="120" height="120" rx="16" fill="url(#logoGrad)" />
            <circle cx="60" cy="60" r="32" fill="#3b82f6" fill-opacity="0.1" stroke="#3b82f6" stroke-width="2" />
            <text x="60" y="69" font-family="'Inter', sans-serif" font-weight="bold" font-size="28" fill="#60a5fa" text-anchor="middle">{initial}</text>
        </svg>"""
    else:
        # Split long name into two lines
        words = name.split()
        if len(words) > 2:
            name_line1 = " ".join(words[:2]).upper()
            name_line2 = " ".join(words[2:]).upper()
        elif len(words) == 2:
            name_line1 = words[0].upper()
            name_line2 = words[1].upper()
        else:
            name_line1 = name.upper()
            name_line2 = ""
            
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
            <defs>
                <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#1e1b4b" />
                    <stop offset="100%" stop-color="#311042" />
                </linearGradient>
                <linearGradient id="accentGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#a855f7" />
                    <stop offset="100%" stop-color="#ec4899" />
                </linearGradient>
            </defs>
            <rect width="200" height="200" rx="24" fill="url(#bgGrad)" />
            <rect x="20" y="20" width="160" height="160" rx="16" fill="none" stroke="url(#accentGrad)" stroke-width="1.5" stroke-opacity="0.4" />
            <path d="M 30,40 L 40,40" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" />
            <path d="M 40,30 L 40,40" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" />
            <path d="M 170,40 L 160,40" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" />
            <path d="M 160,30 L 160,40" stroke="#a855f7" stroke-width="1.5" stroke-linecap="round" />
            <circle cx="100" cy="85" r="30" fill="none" stroke="url(#accentGrad)" stroke-width="3" />
            <circle cx="100" cy="85" r="12" fill="url(#accentGrad)" />
            <path d="M 70,85 L 130,85 M 100,55 L 100,115" stroke="#ffffff" stroke-width="1.5" stroke-opacity="0.3" />
            <text x="100" y="150" font-family="'Inter', sans-serif" font-weight="bold" font-size="11" fill="#ffffff" text-anchor="middle" letter-spacing="1.5">{name_line1}</text>
            <text x="100" y="168" font-family="'Inter', sans-serif" font-weight="500" font-size="9" fill="#9ca3af" text-anchor="middle" letter-spacing="1">{name_line2}</text>
        </svg>"""
        
    encoded = base64.b64encode(svg.encode('utf-8')).decode('utf-8')
    return f"data:image/svg+xml;base64,{encoded}"


def generate_sas_url(
    blob_url: str,
    expiry_hours: int = 24,
    permissions: str = "r"
) -> str | None:
    """
    Generate a SAS token URL for any Azure Blob Storage URL

    Args:
        blob_url: Full blob URL (e.g., https://account.blob.core.windows.net/container/path/file.pdf)
        expiry_hours: Hours until SAS token expires (default: 1 hour)
        permissions: SAS permissions - "r" (read), "rw" (read/write), etc.

    Returns:
        URL with SAS token appended, or None if failed
    """
    try:
        from common.infra.azure_blob import azure_blob_manager

        # Check for local dev storage — route cloud blob URLs through the
        # backend image proxy.  The proxy downloads the blob server-side using
        # the Azure SDK (with proper credentials) and streams it to the browser,
        # avoiding both SAS-token and public-access issues.
        try:
            import urllib.parse as _urlparse

            is_dev_storage = (azure_blob_manager.account_name == "devstoreaccount1")
            is_dev_env = (os.getenv("AZURE_ENV") == "development")
            is_cloud_url = (blob_url and "blob.core.windows.net" in blob_url and "devstoreaccount1" not in blob_url)
            
            if (is_dev_storage or is_dev_env) and is_cloud_url:
                encoded = _urlparse.quote(blob_url, safe='')
                proxy_url = f"/api/image_proxy?url={encoded}"
                logger.info(f"[SAS] Local dev mode. Routing through image proxy: {proxy_url[:80]}...")
                return proxy_url
        except Exception as fallback_err:
            logger.warning(f"Failed to check local dev storage fallback: {fallback_err}")

        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        # Parse the blob URL
        parsed_url = urlparse(blob_url)
        host = parsed_url.netloc.lower()
        path_parts = parsed_url.path.lstrip('/').split('/', 1)

        if len(path_parts) < 2:
            logger.error(f"Invalid blob URL format: {blob_url}")
            return None

        container_name = path_parts[0]
        blob_name = path_parts[1]

        # Use configured credentials (or env override if requesting productsrecommendertjsq storage)
        if "productsrecommendertjsq" in host:
            account_name = "productsrecommendertjsq"
            account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY") or azure_blob_manager.account_key
        else:
            account_name = azure_blob_manager.account_name
            account_key = azure_blob_manager.account_key

        # Check if Azure is configured
        if not account_name or not account_key:
            logger.error("Azure Storage account name or key not configured")
            return None

        # Generate SAS token
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(UTC) + timedelta(hours=expiry_hours)
        )

        # Append SAS token to URL
        sas_url = f"{blob_url}?{sas_token}"

        logger.debug(f"Generated SAS URL for {blob_name} (expires in {expiry_hours}h)")
        return sas_url

    except ImportError:
        logger.error("azure-storage-blob not installed. Run: pip install azure-storage-blob")
        return None
    except Exception as e:
        logger.error(f"Failed to generate SAS token: {e}")
        return None


def add_sas_to_document(
    document: dict,
    blob_url_field: str = "blob_url",
    output_field: str = "sas_url",
    expiry_hours: int = 1
) -> dict:
    """
    Add SAS URL to a MongoDB document

    Args:
        document: MongoDB document containing blob URL
        blob_url_field: Field name containing the blob URL (supports nested fields like "image.blobUrl")
        output_field: Field name to store the SAS URL
        expiry_hours: Hours until SAS token expires

    Returns:
        Document with SAS URL added
    """
    # Get blob URL from document (handle nested fields)
    blob_url = None

    if '.' in blob_url_field:
        # Nested field (e.g., "image.blobUrl")
        parts = blob_url_field.split('.')
        value = document
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
        blob_url = value
    else:
        # Top-level field
        blob_url = document.get(blob_url_field)

    if blob_url and 'blob.core.windows.net' in blob_url:
        sas_url = generate_sas_url(blob_url, expiry_hours=expiry_hours)
        if sas_url:
            document[output_field] = sas_url

    return document


def get_document_with_sas(
    collection_name: str,
    query: dict,
    blob_url_field: str = "blob_url",
    expiry_hours: int = 1
) -> dict | None:
    """
    Get a document from MongoDB and add SAS URL

    Args:
        collection_name: MongoDB collection name
        query: MongoDB query to find document
        blob_url_field: Field containing blob URL (supports nested like "image.blobUrl")
        expiry_hours: Hours until SAS token expires

    Returns:
        Document with SAS URL added, or None if not found
    """
    try:
        from common.infra.mongodb_config import get_mongodb_connection

        conn = get_mongodb_connection()
        collection = conn['collections'].get(collection_name) or conn['database'][collection_name]

        document = collection.find_one(query)

        if document:
            return add_sas_to_document(document, blob_url_field, expiry_hours=expiry_hours)

        return None

    except Exception as e:
        logger.error(f"Failed to get document with SAS: {e}")
        return None


def get_documents_with_sas(
    collection_name: str,
    query: dict = None,
    blob_url_field: str = "blob_url",
    expiry_hours: int = 1,
    limit: int = 100
) -> list:
    """
    Get multiple documents from MongoDB and add SAS URLs

    Args:
        collection_name: MongoDB collection name
        query: MongoDB query to find documents
        blob_url_field: Field containing blob URL
        expiry_hours: Hours until SAS token expires
        limit: Maximum number of documents to return

    Returns:
        List of documents with SAS URLs added
    """
    if query is None:
        query = {}
    try:
        from common.infra.mongodb_config import get_mongodb_connection

        conn = get_mongodb_connection()
        collection = conn['collections'].get(collection_name) or conn['database'][collection_name]

        documents = list(collection.find(query).limit(limit))

        # Add SAS URLs to all documents
        return [add_sas_to_document(doc, blob_url_field, expiry_hours=expiry_hours)
                for doc in documents]

    except Exception as e:
        logger.error(f"Failed to get documents with SAS: {e}")
        return []


# Collection-specific helper functions
def get_document_pdf_with_sas(query: dict, expiry_hours: int = 1) -> dict | None:
    """Get a PDF document with SAS URL"""
    return get_document_with_sas('documents', query, 'blob_url', expiry_hours)


def get_product_image_with_sas(query: dict, expiry_hours: int = 24) -> dict | None:
    """Get a product image with SAS URL"""
    return get_document_with_sas('images', query, 'image.blobUrl', expiry_hours)


def get_vendor_logo_with_sas(query: dict, expiry_hours: int = 24) -> dict | None:
    """Get a vendor logo with SAS URL"""
    return get_document_with_sas('vendor_logos', query, 'image.blobUrl', expiry_hours)


def get_generic_image_with_sas(query: dict, expiry_hours: int = 24) -> dict | None:
    """Get a generic image with SAS URL"""
    return get_document_with_sas('generic_images', query, 'image.blobUrl', expiry_hours)


def get_strategy_document_with_sas(query: dict, expiry_hours: int = 1) -> dict | None:
    """Get a strategy document with SAS URL"""
    return get_document_with_sas('stratergy', query, 'storage.blobUrl', expiry_hours)


def get_standards_document_with_sas(query: dict, expiry_hours: int = 1) -> dict | None:
    """Get a standards document with SAS URL"""
    return get_document_with_sas('standards', query, 'storage.blobUrl', expiry_hours)



