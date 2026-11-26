"""
Generic Product Type Image Utilities
Minimal implementation: Fetches existing images from MongoDB/Blob Storage only.
No fallback to generation.
"""
import logging
import re
from typing import Any

from common.infra.blob_sas import generate_sas_url
from common.infra.mongodb_config import get_mongodb_connection

logger = logging.getLogger(__name__)

_hierarchy_db_host_logged = False


def _log_hierarchy_db_host_once() -> None:
    """Log which physical Restructured DB host resolve_generic_image_id will
    query, the first time it's needed. get_restructured_db() targets
    RESTRUCTURED_DB_URI when set, else falls back to MONGODB_URI -- two
    differently-configured deployments can silently end up talking to two
    different physical clusters with different hierarchy data, which is hard
    to detect without this logged explicitly."""
    global _hierarchy_db_host_logged
    if _hierarchy_db_host_logged:
        return
    _hierarchy_db_host_logged = True
    try:
        from common.infra.mongodb_config import get_restructured_db

        host = get_restructured_db().client.address
        logger.info(f"[GenericImage] Hierarchy-based image resolution using Restructured DB host: {host}")
    except Exception as exc:
        logger.warning(f"[GenericImage] Could not determine Restructured DB host: {exc}")


def _lookup_generic_image_in_db(normalized_type: str) -> dict[str, Any] | None:
    """Direct DB lookup for a generic image by normalized product type.

    The module-level `_GENERIC_IMAGES_CACHE` is loaded ONCE and never refreshed,
    so a generic image added AFTER the cache was populated stays invisible until a
    server restart (this is exactly why a present image — e.g. 'pump' — can fail to
    display). On a cache miss we query the DB directly so newly-added images resolve
    without a restart.
    """
    try:
        coll = get_mongodb_connection()['collections']['generic_images']
        doc = coll.find_one({"product_type_normalized": normalized_type})
        if not doc:
            base = normalized_type.rstrip('s')  # tolerate simple plural/singular
            if base and base != normalized_type:
                doc = coll.find_one({"product_type_normalized": base})
        if not doc and len(normalized_type) >= 3:
            doc = coll.find_one({"product_type_normalized": {"$regex": re.escape(normalized_type)}})
        return doc
    except Exception as exc:
        logger.error(f"[GenericImage] DB fallback lookup failed for '{normalized_type}': {exc}")
        return None


def _lookup_generic_image_by_hierarchy(product_type: str) -> dict[str, Any] | None:
    """Resolve `product_type` to its L2 hierarchy node's generic_image_id, then
    look that id up as an exact match — deterministic, no fuzzy scoring needed
    once the hierarchy has attached an image. Returns None if the product type
    isn't in the hierarchy yet or its L2 node has no image attached, so callers
    can fall back to the pre-existing fuzzy string match unchanged.

    Any failure here (including a misconfigured/unreachable Restructured DB
    connection) is logged at WARNING, not silently swallowed at debug level --
    a broken hierarchy lookup should be visible in application logs rather
    than only discoverable by manually re-running the resolver against the
    database, which is what made this feature's rollout hard to diagnose.
    """
    try:
        _log_hierarchy_db_host_once()
        from common.infra.repositories.product_hierarchy_repository import ProductHierarchyRepository

        image_id = ProductHierarchyRepository.resolve_generic_image_id(product_type)
        if not image_id:
            return None
        coll = get_mongodb_connection()['collections']['generic_images']
        doc = coll.find_one({"$or": [{"id": image_id}, {"product_type_normalized": image_id}]})
        if not doc:
            logger.warning(
                f"[GenericImage] Hierarchy resolved '{product_type}' -> generic_image_id={image_id!r} "
                f"but no matching generic_images document exists -- the hierarchy link is stale."
            )
        return doc
    except Exception as exc:
        logger.warning(f"[GenericImage] Hierarchy-based lookup failed for '{product_type}': {exc}")
        return None


def _notify_failure(failed_step: str, error_message: str, **extra_context):
    """Send a system-level failure notification. Silently swallows errors."""
    try:
        from common.infra.repositories.notification_repository import create_failure_notification
        create_failure_notification(
            user_id=0,
            username="System",
            user_email="",
            failed_step=failed_step,
            error_message=error_message,
            page="search",
            additional_context=extra_context,
        )
    except Exception as notify_err:
        logger.warning(f"[NOTIFICATION] Failed to create {failed_step} notification: {notify_err}")


def _are_words_similar(w1: str, w2: str) -> bool:
    """Check if two words are similar, accounting for basic singular/plural matches."""
    w1, w2 = w1.lower(), w2.lower()
    if w1 == w2:
        return True
    if w1.endswith('s') and w1[:-1] == w2:
        return True
    if w2.endswith('s') and w2[:-1] == w1:
        return True
    if w1.endswith('es') and w1[:-2] == w2:
        return True
    if w2.endswith('es') and w2[:-2] == w1:
        return True
    return False


_GENERIC_IMAGES_CACHE = None


def fetch_generic_product_image(product_type: str) -> dict[str, Any] | None:
    """
    Fetch generic product type image from MongoDB and generate SAS URL.
    Uses a robust Python-based token similarity ranker to match queries
    accurately with the cached collection.
    """
    global _GENERIC_IMAGES_CACHE
    try:
        if not product_type:
            return None

        # Hierarchy-resolved lookup first: deterministic once the product type's
        # L2 node has an image attached, so it takes priority over the fuzzy
        # string match below. Falls through unchanged if unresolved.
        hierarchy_doc = _lookup_generic_image_by_hierarchy(product_type)
        if hierarchy_doc:
            image_data = hierarchy_doc.get('image', {})
            blob_url = image_data.get('blobUrl')
            if blob_url:
                sas_url = generate_sas_url(blob_url, expiry_hours=24)
                logger.info(f"[GenericImage] Hierarchy match found for '{product_type}' -> "
                            f"'{hierarchy_doc.get('product_type_normalized')}'")
                return {
                    'url': sas_url if sas_url else blob_url,
                    'product_type': hierarchy_doc.get('productType') or hierarchy_doc.get('product_type')
                                    or hierarchy_doc.get('product_type_normalized', product_type),
                    'source': 'database',
                    'cached': True,
                    'content_type': hierarchy_doc.get('contentType') or image_data.get('contentType', 'image/png'),
                }

        normalized_type = product_type.strip().lower().replace(" ", "_").replace("-", "_")
        query_words = [w for w in normalized_type.split('_') if len(w) >= 3]

        # Use in-memory cache to avoid slow/hanging MongoDB connections on every request
        if _GENERIC_IMAGES_CACHE is None:
            try:
                conn = get_mongodb_connection()
                generic_images_collection = conn['collections']['generic_images']
                _GENERIC_IMAGES_CACHE = list(generic_images_collection.find())
                logger.info(f"[GenericImage] Loaded {len(_GENERIC_IMAGES_CACHE)} generic images into in-memory cache.")
            except Exception as cache_err:
                logger.error(f"[GenericImage] Failed to populate generic images cache from DB: {cache_err}")
                _GENERIC_IMAGES_CACHE = None

        docs = _GENERIC_IMAGES_CACHE
        best_doc = None
        best_score = -1.0

        if not docs:
            logger.warning("[GenericImage] Cache is empty or uninitialized. Falling back to direct DB query.")
            best_doc = _lookup_generic_image_in_db(normalized_type)
        else:
            for doc in docs:
                doc_normalized = doc.get('product_type_normalized') or ''
                doc_normalized = doc_normalized.strip().lower()
                
                doc_id = doc.get('id') or ''
                doc_id_normalized = doc_id.replace('generic_image_', '').replace('generic_', '')

                score = 0.0
                
                # 1. Exact match
                if doc_normalized == normalized_type or doc_id_normalized == normalized_type:
                    score = 100.0
                else:
                    # 2. Token similarity matching
                    doc_words = [w for w in doc_normalized.split('_') if len(w) >= 3]
                    if doc_id_normalized:
                        doc_words.extend(w for w in doc_id_normalized.split('_') if len(w) >= 3)
                    doc_words = list(set(doc_words))
                    
                    if query_words and doc_words:
                        matches = 0
                        for qw in query_words:
                            for dw in doc_words:
                                if _are_words_similar(qw, dw):
                                    matches += 1
                                    break
                        
                        overlap_ratio = matches / len(query_words)
                        score = overlap_ratio * 50.0
                        
                        # 3. Substring matching bonus
                        clean_query = normalized_type.rstrip('s').rstrip('es')
                        clean_doc = doc_normalized.rstrip('s').rstrip('es')
                        if clean_query in clean_doc or clean_doc in clean_query:
                            score += 20.0

                if score > best_score and score > 0.0:
                    best_score = score
                    best_doc = doc

        if not best_doc or (docs and best_score <= 0.0):
            # Cache may be stale (loaded once, never refreshed) or lookup failed -> direct DB fallback
            # so images added after cache load (e.g. 'pump') still resolve.
            fresh = _lookup_generic_image_in_db(normalized_type)
            if fresh:
                if isinstance(_GENERIC_IMAGES_CACHE, list):
                    _GENERIC_IMAGES_CACHE.append(fresh)  # warm the cache for next time
                best_doc = fresh
                logger.info(f"[GenericImage] DB fallback hit for '{product_type}' -> "
                            f"'{fresh.get('product_type_normalized')}'")
            else:
                logger.info(f"[GenericImage] No matching image found for '{product_type}'")
                return None

        # Extract Blob URL
        image_data = best_doc.get('image', {})
        blob_url = image_data.get('blobUrl')

        if not blob_url:
            logger.warning(f"[GenericImage] Document found for '{product_type}' but 'blobUrl' is missing")
            _notify_failure("Generic Image - Missing Blob URL",
                f"Image document exists for '{product_type}' but blobUrl field is missing or empty",
                product_type=product_type, document_id=str(best_doc.get('_id', 'N/A')))
            return None

        # Generate SAS URL for access
        sas_url = generate_sas_url(blob_url, expiry_hours=24)
        final_url = sas_url if sas_url else blob_url

        logger.info(f"[GenericImage] Match found for '{product_type}' -> '{best_doc.get('product_type_normalized')}' (score: {best_score:.1f})")

        return {
            'url': final_url,
            'product_type': best_doc.get('productType') or best_doc.get('product_type') or best_doc.get('product_type_normalized', product_type),
            'source': 'database',
            'cached': True,
            'content_type': best_doc.get('contentType') or best_doc.get('image', {}).get('contentType', 'image/png')
        }


    except Exception as e:
        logger.error(f"[GenericImage] Error fetching image for '{product_type}': {e}")

        # Send notification for generic image fetch error
        _notify_failure("Generic Image Fetch Error",
            f"Error fetching generic image for product '{product_type}': {str(e)}",
            product_type=product_type, error=str(e))

        return None

def fetch_product_images_with_fallback_sync(vendor_name: str, product_name: str = None, model_family: str = None, product_type: str = None):
    """
    Synchronous image search that ONLY checks the MongoDB cache.
    No fallback to search engines is performed.
    """
    logger.info(f"Starting image cache lookup for vendor: {vendor_name}, product: {product_name}, model family: {model_family}, type: {product_type}")

    if vendor_name:
        try:
            import re
            conn = get_mongodb_connection()
            images_collection = conn['collections']['images']
            
            # Use model_family for key if available, otherwise just vendor
            cache_key_model = model_family if model_family else ""

            def clean_name(name):
                if not name: return ""
                name = name.lower().strip()
                name = re.sub(r'[^\w\s-]', '', name)
                name = re.sub(r'[-\s]+', '_', name)
                return name.strip('_')

            normalized_vendor = clean_name(vendor_name)
            normalized_model = clean_name(cache_key_model)
            
            # First try exact normalized match
            query = {
                'vendor_name_normalized': normalized_vendor,
                'model_family_normalized': normalized_model,
                'status': 'active'
            }
            
            cached_image = images_collection.find_one(query)
            
            # Fallback 1: Broad regex search on ID
            if not cached_image:
                safe_vendor = re.escape(normalized_vendor)
                safe_model = re.escape(normalized_model)
                if safe_vendor and safe_model:
                    fallback_query = {
                        'id': {'$regex': f'{safe_vendor}.*{safe_model}', '$options': 'i'},
                        'status': 'active'
                    }
                    cached_image = images_collection.find_one(fallback_query)

            # Fallback 2: Partial model match
            if not cached_image:
                partial_query = {
                    'vendor_name_normalized': normalized_vendor,
                    'model_family_normalized': {'$regex': re.escape(normalized_model), '$options': 'i'},
                    'status': 'active'
                }
                cached_image = images_collection.find_one(partial_query)

            # Check both flat 'blob_url' and nested 'image.blobUrl' based on DB schema
            blob_url = None
            if cached_image:
                blob_url = cached_image.get('blob_url')
                if not blob_url and cached_image.get('image'):
                    blob_url = cached_image.get('image', {}).get('blobUrl')

            if cached_image and blob_url:
                logger.info(f"Using cached image from Blob Storage for {vendor_name} - {cache_key_model}")


                sas_url = generate_sas_url(blob_url, expiry_hours=1)
                final_url = sas_url if sas_url else blob_url

                # Return image with SAS URL
                image_response = {
                    'url': final_url,
                    'title': cached_image.get('title', ''),
                    'source': 'azure_blob',
                    'thumbnail': final_url,
                    'domain': 'azure',
                    'cached': True
                }
                return [image_response], "azure_blob"
        except Exception as e:
            logger.error(f"Failed to lookup product image in MongoDB: {e}")

    # Not found in cache. Fallback to web search and save to DB.
    logger.info(f"Image not in cache for {vendor_name} {model_family}. Falling back to web search...")
    images = []
    source_used = "none"

    try:
        import os
        import requests
        
        anti_spam = " product image OR product OR datasheet -used -refurbished -ebay -amazon -alibaba -youtube -pdf -doc"
        search_query = f"{vendor_name} {model_family} {product_type or ''} {anti_spam}".strip()
        
        # 1. Try Serper.dev First
        serper_key = os.getenv("SERPER_API_KEY")
        if serper_key:
            try:
                url = "https://google.serper.dev/images"
                payload = {"q": search_query, "num": 5}
                headers = {"X-API-KEY": serper_key, "Content-Type": "application/json"}
                
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                for item in data.get("images", []):
                    images.append({
                        "url": item.get("imageUrl"),
                        "title": item.get("title", ""),
                        "source": "search_engine",
                        "domain": item.get("link", ""),
                        "thumbnail": item.get("imageUrl")
                    })
                if images:
                    source_used = "search_engine"
            except Exception as e:
                logger.warning(f"Serper search failed for {vendor_name} {model_family}: {e}")

        # 2. Fallback to SerpAPI if Serper failed
        if not images:
            serpapi_key = os.getenv("SERPAPI_KEY")
            if serpapi_key:
                try:
                    from serpapi import GoogleSearch
                    logger.info(f"Falling back to SerpAPI for {vendor_name} {model_family}...")
                    search = GoogleSearch({
                        "q": search_query,
                        "engine": "google_images",
                        "api_key": serpapi_key,
                        "num": 5,
                        "safe": "active",
                        "ijn": 0
                    })
                    results = search.get_dict()
                    for item in results.get("images_results", []):
                        images.append({
                            "url": item.get("original"),
                            "title": item.get("title", ""),
                            "source": "search_engine",
                            "domain": item.get("source", ""),
                            "thumbnail": item.get("thumbnail", "")
                        })
                    if images:
                        source_used = "search_engine"
                except Exception as e:
                    logger.warning(f"SerpAPI search failed for {vendor_name} {model_family}: {e}")

        if images:
            # Found images! Cache the first one for future use.
            logger.info(f"Web search found {len(images)} images for {vendor_name} {model_family}. Caching top image...")
            try:
                from common.infra.mongodb_utils import cache_image
                # The cache_image function downloads the image, uploads to Azure Blob, and inserts into MongoDB
                cache_image(vendor_name, model_family or "", product_type or "Unknown", images[0])
                logger.info(f"Successfully triggered caching for {vendor_name} {model_family}.")
            except Exception as cache_err:
                logger.error(f"Failed to cache downloaded image: {cache_err}")
                
            return images, source_used
            
    except Exception as e:
        logger.error(f"Web fallback search failed for {vendor_name} {model_family}: {e}")

    return [], "none"


def fetch_vendor_logo_sync(vendor_name: str):
    """
    Specialized function to fetch vendor logo with MongoDB caching.
    ONLY checks the MongoDB cache.
    """
    logger.info(f"Fetching logo for vendor: {vendor_name} from cache only")

    # Step 0: Check MongoDB cache first
    try:
        conn = get_mongodb_connection()
        logos_collection = conn['collections']['vendor_logos']
        
        normalized_vendor = vendor_name.strip().lower().replace(' ', '_')

        cached_logo = logos_collection.find_one({
            'id': f'vendor_logo_{normalized_vendor}',
            'status': 'active'
        })

        if cached_logo and cached_logo.get('image', {}).get('blobUrl'):
            logger.info(f"Using cached logo from Blob Storage for {vendor_name}")
            blob_url = cached_logo['image']['blobUrl']

            sas_url = generate_sas_url(blob_url, expiry_hours=24)
            final_url = sas_url if sas_url else blob_url

            return {
                'url': final_url,
                'thumbnail': final_url,
                'source': 'database',
                'cached': True,
                'contentType': cached_logo.get('image', {}).get('contentType', 'image/png')
            }
    except Exception as e:
        logger.error(f"Failed to lookup vendor logo in MongoDB: {e}")
        
    return None



