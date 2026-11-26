"""Price and review fetching service using SerpAPI Google Shopping."""
import logging
import os

logger = logging.getLogger(__name__)

_SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
_SERPAPI_URL = "https://serpapi.com/search"


def fetch_price_and_reviews(
    product_name: str,
    vendor_name: str | None = None,
    model_family: str | None = None,
    sub_model: str | None = None,
    product_type: str | None = None,
    user_location: str | None = None,
) -> dict:
    """
    Fetch price and review listings for a product via SerpAPI Google Shopping.

    Returns:
        {
            "results": [...],           # list of product result dicts
            "location_attempted": str,  # location passed in (or None)
            "location_used": str | None # location that returned results (None = fallback to global)
        }
    """
    import requests

    if not _SERPAPI_KEY:
        logger.warning("[PRICE] SERPAPI_KEY not set — returning empty results")
        return {"results": [], "location_attempted": user_location, "location_used": None}

    # Build the search query
    parts = [p for p in [vendor_name, sub_model or model_family, product_name, product_type] if p]
    query = " ".join(parts) if parts else product_name

    def _search(location: str | None) -> list:
        params = {
            "engine": "google_shopping",
            "q": query,
            "api_key": _SERPAPI_KEY,
            "num": 20,
        }
        if location:
            params["location"] = location

        try:
            resp = requests.get(_SERPAPI_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("shopping_results") or data.get("organic_results") or []
            return [_normalise(item) for item in raw]
        except requests.RequestException as exc:
            logger.warning(f"[PRICE] SerpAPI request failed: {exc}")
            return []
        except Exception as exc:
            logger.exception(f"[PRICE] Unexpected error fetching price data: {exc}")
            return []

    # Try with user location first, fall back to global
    location_attempted = user_location or None
    results = _search(location_attempted) if location_attempted else []

    if results:
        return {
            "results": results,
            "location_attempted": location_attempted,
            "location_used": location_attempted,
        }

    # Fallback: no location filter
    global_results = _search(None)
    return {
        "results": global_results,
        "location_attempted": location_attempted,
        "location_used": None,
    }


def _normalise(item: dict) -> dict:
    """Flatten a SerpAPI shopping result into a consistent shape."""
    return {
        "title":        item.get("title", ""),
        "price":        item.get("price", ""),
        "currency":     item.get("currency", ""),
        "rating":       item.get("rating"),
        "reviews":      item.get("reviews"),
        "source":       item.get("source", ""),
        "link":         item.get("link", ""),
        "thumbnail":    item.get("thumbnail", ""),
        "delivery":     item.get("delivery", ""),
        "condition":    item.get("second_hand_condition", "new"),
        "position":     item.get("position"),
    }
