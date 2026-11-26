from common.helpers.azure_session import get_session
"""Catalog domain routes."""
import logging
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.errors import notify_failure
from common.infra.mongodb_utils import mongodb_retry

from common.helpers.responses import JSONResponse

blueprint = APIRouter()

_catalog_blob_cache = None
_catalog_blob_cache_time = 0
_catalog_product_types_cache = None
_catalog_product_types_cache_time = 0
_catalog_vendors_cache = {}
_catalog_vendors_cache_time = {}


@blueprint.post("/api/catalog-clear-cache")
@login_required
async def clear_catalog_cache(request: Request):
    session = get_session(request)
    global _catalog_product_types_cache, _catalog_product_types_cache_time
    global _catalog_vendors_cache, _catalog_vendors_cache_time
    _catalog_product_types_cache = None
    _catalog_product_types_cache_time = 0
    _catalog_vendors_cache = {}
    _catalog_vendors_cache_time = {}
    return JSONResponse({"message": "Cache cleared successfully"}, status_code=200)


@blueprint.get("/api/catalog-image")
@login_required
async def get_catalog_image(request: Request):
    session = get_session(request)
    global _catalog_blob_cache, _catalog_blob_cache_time
    try:
        vendor = request.query_params.get('vendor', '').strip()
        model = request.query_params.get('model', '').strip()
        product_type = request.query_params.get('product_type', '').strip()

        if not vendor or not model:
            return JSONResponse({"error": "vendor and model query params are required"}, status_code=400)

        logging.info(f"[catalog-image] Looking for image: vendor={vendor}, model={model}, product_type={product_type}")

        from common.infra.blob_sas import generate_sas_url
        from common.infra.mongodb_utils import get_cached_image

        try:
            cached = get_cached_image(vendor_name=vendor, model_family=model, product_type=product_type)
            if cached and cached.get('blob_url'):
                blob_url = cached['blob_url']
                logging.info(f"[catalog-image] Found image in MongoDB: {blob_url[:100]}...")
                sas_url = generate_sas_url(blob_url, expiry_hours=4)
                if sas_url:
                    logging.info("[catalog-image] Generated SAS URL successfully")
                else:
                    logging.warning("[catalog-image] Failed to generate SAS URL, using blob URL directly")
                return JSONResponse({
                    "found": True,
                    "image_url": sas_url or blob_url,
                    "vendor": vendor,
                    "model": model,
                    "source": "mongodb_cache"
                }, status_code=200)
            else:
                logging.info(f"[catalog-image] No cached image found for vendor={vendor}, model={model}")
                notify_failure("Catalog Image Not Found",
                    f"No cached image found for vendor='{vendor}', model='{model}', product_type='{product_type}'",
                    page='solution', vendor=vendor, model=model, product_type=product_type)
        except Exception as e:
            logging.warning(f"[catalog-image] MongoDB lookup failed for vendor={vendor}, model={model}: {e}")
            notify_failure("Catalog Image MongoDB Lookup",
                f"MongoDB lookup failed for catalog image: vendor={vendor}, model={model}, error={str(e)}",
                page='solution', vendor=vendor, model=model, product_type=product_type, error=str(e))

        return JSONResponse({"found": False}, status_code=200)

    except Exception as e:
        logging.exception(f"[catalog-image] Error fetching image: {e}")
        notify_failure("Catalog Image Fetch", f"Failed to fetch catalog image: {str(e)}", page='solution', error=str(e))
        return JSONResponse({"found": False, "error": "Failed to fetch catalog image"}, status_code=500)


@blueprint.get("/api/catalog-data")
@login_required
async def get_catalog_data(request: Request):
    session = get_session(request)
    try:
        import re
        from common.infra.mongodb_config import get_mongodb_connection

        logging.info("[catalog-data] Fetching catalog data from MongoDB")

        def normalize_name(name):
            name = name.lower().strip()
            name = re.sub(r'[^\w\s-]', '', name)
            name = re.sub(r'[-\s]+', '_', name)
            return name.strip('_') or 'unknown'

        conn = get_mongodb_connection()
        specs_collection = conn['collections']['specs']
        images_collection = conn['collections']['images']

        product_type_pipeline = [{"$group": {"_id": "$product_type"}}, {"$sort": {"_id": 1}}]
        product_type_results = list(specs_collection.aggregate(product_type_pipeline))
        product_type_names = [pt['_id'] for pt in product_type_results if pt['_id']]

        logging.info(f"[catalog-data] Found {len(product_type_names)} product types from specs collection")

        product_types = []
        total_vendors_set = set()
        total_model_families = 0

        for product_type_name in product_type_names:
            normalized_product_type = normalize_name(product_type_name)
            images_pipeline = [
                {"$match": {"product_type_normalized": normalized_product_type, "status": "active"}},
                {"$group": {"_id": {"vendor_name": "$vendor_name_normalized", "model_family": "$model_family_normalized"}}},
                {"$group": {"_id": "$_id.vendor_name", "modelFamilies": {"$addToSet": "$_id.model_family"}}},
                {"$sort": {"_id": 1}}
            ]
            vendor_results = list(images_collection.aggregate(images_pipeline))
            vendors = []
            if vendor_results:
                for vendor_result in vendor_results:
                    vendor_name = vendor_result['_id']
                    model_families = sorted([mf for mf in vendor_result['modelFamilies'] if mf])
                    vendors.append({"name": vendor_name, "modelFamilies": model_families})
                    total_vendors_set.add(vendor_name)
                    total_model_families += len(model_families)

            product_types.append({
                "name": product_type_name,
                "vendors": vendors,
                "totalVendors": len(vendors),
                "totalModelFamilies": sum(len(v['modelFamilies']) for v in vendors)
            })

        product_types.sort(key=lambda pt: pt['name'])
        response = {
            "productTypes": product_types,
            "totalProductTypes": len(product_types),
            "totalVendors": len(total_vendors_set),
            "totalModelFamilies": total_model_families
        }

        logging.info(f"[catalog-data] Returning {len(product_types)} product types")
        return JSONResponse(response, status_code=200)

    except Exception as e:
        logging.exception(f"[catalog-data] Error fetching catalog data: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def _compute_catalog_stats(pt_names: list, vendors_col) -> dict:
    import concurrent.futures

    def stats_for_pt(pt_name):
        try:
            result = list(vendors_col.aggregate([
                {"$match": {"product_type": pt_name}},
                {"$group": {
                    "_id": None,
                    "vendors": {"$addToSet": "$vendor_name"},
                    "modelCount": {"$sum": {"$size": {"$ifNull": ["$data.models", []]}}}
                }}
            ], maxTimeMS=15000))
            if result:
                return pt_name, len(result[0].get("vendors", [])), result[0].get("modelCount", 0)
            return pt_name, 0, 0
        except Exception:
            return pt_name, 0, 0

    stats = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        for pt, vc, mc in ex.map(stats_for_pt, pt_names):
            stats[pt] = {"vendorCount": vc, "modelCount": mc}
    return stats


@blueprint.get("/api/catalog-product-types")
@login_required
async def get_catalog_product_types(request: Request):
    session = get_session(request)
    global _catalog_product_types_cache, _catalog_product_types_cache_time
    import time
    try:
        current_time = time.time()
        cache_valid = (
            _catalog_product_types_cache and
            (current_time - _catalog_product_types_cache_time) < 21600 and
            any(pt.get("vendorCount", 0) > 0 for pt in _catalog_product_types_cache.get("productTypes", []))
        )
        if cache_valid:
            logging.info("[catalog-product-types] Returning cached data")
            return JSONResponse(_catalog_product_types_cache, status_code=200, headers={'Cache-Control': 'private, max-age=21600'})

        logging.info("[catalog-product-types] Fetching from MongoDB")

        from common.infra.mongodb_config import get_mongodb_connection
        conn = get_mongodb_connection()
        specs_collection = conn['collections']['specs']
        vendors_collection = conn['collections']['vendors']

        @mongodb_retry
        def get_product_type_names():
            return list(specs_collection.aggregate([
                {"$group": {"_id": "$product_type"}},
                {"$sort": {"_id": 1}}
            ], maxTimeMS=15000))

        try:
            pt_results = get_product_type_names()
        except Exception as e:
            logging.error(f"[catalog-product-types] Failed to get product types: {e}")
            return JSONResponse({"productTypes": [], "totalProductTypes": 0, "error": str(e)}, status_code=200)

        pt_names = [pt["_id"] for pt in pt_results if pt.get("_id")]

        logging.info(f"[catalog-product-types] Computing stats for {len(pt_names)} product types")
        stats = _compute_catalog_stats(pt_names, vendors_collection)
        logging.info(f"[catalog-product-types] Stats ready for {len(stats)} product types")

        product_types = [
            {
                "name": name,
                "vendorCount": stats.get(name, {}).get("vendorCount", 0),
                "modelCount": stats.get(name, {}).get("modelCount", 0)
            }
            for name in pt_names
        ]

        response = {"productTypes": product_types, "totalProductTypes": len(product_types)}
        _catalog_product_types_cache = response
        _catalog_product_types_cache_time = current_time

        logging.info(f"[catalog-product-types] Cached {len(product_types)} product types")
        return JSONResponse(response, status_code=200, headers={'Cache-Control': 'private, max-age=21600'})

    except Exception as e:
        logging.exception(f"[catalog-product-types] Error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/catalog-vendors/{product_type}")
@login_required
async def get_catalog_vendors(request: Request, product_type: str):
    session = get_session(request)
    global _catalog_vendors_cache, _catalog_vendors_cache_time
    import time
    try:
        current_time = time.time()
        cache_key = product_type
        if cache_key in _catalog_vendors_cache:
            cache_age = current_time - _catalog_vendors_cache_time.get(cache_key, 0)
            if cache_age < 3600:
                logging.info(f"[catalog-vendors] Returning cached data for {product_type}")
                return JSONResponse(_catalog_vendors_cache[cache_key], status_code=200)

        from common.infra.mongodb_config import get_mongodb_connection
        logging.info(f"[catalog-vendors] Fetching vendors for {product_type}")
        conn = get_mongodb_connection()
        vendors_collection = conn['collections']['vendors']

        vendors_pipeline = [
            {"$match": {"product_type": product_type, "data.models": {"$exists": True, "$ne": []}}},
            {"$group": {
                "_id": "$vendor_name",
                "modelArrays": {
                    "$push": {
                        "$map": {
                            "input": {"$filter": {"input": {"$ifNull": ["$data.models", []]}, "as": "m", "cond": {"$and": [{"$ne": ["$$m.model_series", None]}, {"$ne": ["$$m.model_series", ""]}]}}},
                            "as": "m",
                            "in": "$$m.model_series"
                        }
                    }
                }
            }},
            {"$addFields": {"modelFamilies": {"$reduce": {"input": "$modelArrays", "initialValue": [], "in": {"$setUnion": ["$$value", "$$this"]}}}}},
            {"$project": {"_id": 1, "modelFamilies": 1}},
            {"$sort": {"_id": 1}}
        ]

        vendor_results = list(vendors_collection.aggregate(vendors_pipeline, maxTimeMS=120000))
        logging.info(f"[catalog-vendors] {len(vendor_results)} vendors found for {product_type}")

        vendors = []
        total_model_families = 0
        for vendor_result in vendor_results:
            vendor_name = vendor_result['_id']
            model_families = sorted([mf for mf in vendor_result.get('modelFamilies', []) if mf])
            vendors.append({"name": vendor_name, "modelFamilies": model_families})
            total_model_families += len(model_families)

        logging.info(f"[catalog-vendors] Aggregation returned {len(vendors)} vendors, {total_model_families} model families")

        response = {
            "name": product_type,
            "vendors": vendors,
            "totalVendors": len(vendors),
            "totalModelFamilies": total_model_families
        }

        _catalog_vendors_cache[cache_key] = response
        _catalog_vendors_cache_time[cache_key] = current_time
        logging.info(f"[catalog-vendors] Cached {len(vendors)} vendors for {product_type}")
        return JSONResponse(response, status_code=200)

    except Exception as e:
        logging.exception(f"[catalog-vendors] Error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
