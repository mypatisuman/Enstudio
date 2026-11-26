"""
Web search and PDF discovery for Indexing pipeline.

  _search_serper(query)            -> list[dict]   web search via Serper API
  _search_serpapi(query)           -> list[dict]   web search via SerpAPI
  _filter_score(results, ...)      -> list[dict]   rank results by keyword score
  _search_pdfs(vendor, pt, fams)   -> list[dict]   per-model datasheet discovery
  _download_image(url)             -> bytes|None   HTTP image download
  _download_to_blob(url, meta)     -> (bool, msg, doc_id)  stream PDF → blob

Env vars: SERPER_API_KEY, SERPAPI_KEY
"""

import os
import re
import logging
import requests
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from .resilience import RetryConfig, retry_with_backoff, SimpleCache

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"))   # Indexing/.env

log = logging.getLogger(__name__)

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

_search_cache = SimpleCache(ttl=3600)

_HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── web search ────────────────────────────────────────────────────────────────

@retry_with_backoff(RetryConfig(max_retries=2, base_delay=2.0))
def _search_serper(query: str) -> List[Dict[str, Any]]:
    """Full-text web search via Serper API; results cached by query."""
    cache_key = f"serper_{query}"
    if cached := _search_cache.get(cache_key):
        return cached
    if not SERPER_API_KEY:
        return []
    try:
        items = requests.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": 3},
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            timeout=30,
        ).json().get("organic", [])
        results = [{"title": i.get("title"), "url": i.get("link"),
                    "snippet": i.get("snippet"), "source": "serper"}
                   for i in items if i.get("link")]
        _search_cache.set(cache_key, results)
        return results
    except Exception as e:
        log.warning("[SEARCH] serper failed: %s", e)
        return []


@retry_with_backoff(RetryConfig(max_retries=2, base_delay=2.0))
def _search_serpapi(query: str) -> List[Dict[str, Any]]:
    """Full-text web search via SerpAPI; results cached by query."""
    cache_key = f"serpapi_{query}"
    if cached := _search_cache.get(cache_key):
        return cached
    if not SERPAPI_KEY:
        return []
    try:
        from serpapi.google_search import GoogleSearch
        items = (GoogleSearch({"q": query, "api_key": SERPAPI_KEY, "num": 3})
                 .get_dict().get("organic_results", []))
        results = [{"title": i.get("title"), "url": i.get("link"),
                    "snippet": i.get("snippet"), "source": "serpapi"}
                   for i in items if i.get("link")]
        _search_cache.set(cache_key, results)
        return results
    except Exception as e:
        log.warning("[SEARCH] serpapi failed: %s", e)
        return []


# ── image search ──────────────────────────────────────────────────────────────

@retry_with_backoff(RetryConfig(max_retries=2, base_delay=2.0))
def _search_images_serper(query: str, num: int = 10) -> List[Dict[str, Any]]:
    cache_key = f"serper_img_{query}"
    if cached := _search_cache.get(cache_key):
        return cached
    if not SERPER_API_KEY:
        return []
    try:
        imgs = requests.post(
            "https://google.serper.dev/images",
            json={"q": query, "num": num},
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            timeout=30,
        ).json().get("images", [])
        results = [{"url": i.get("imageUrl"), "title": i.get("title"), "source": "serper"}
                   for i in imgs if i.get("imageUrl")]
        _search_cache.set(cache_key, results)
        return results
    except Exception as e:
        log.warning("[SEARCH] serper images failed: %s", e)
        return []


@retry_with_backoff(RetryConfig(max_retries=2, base_delay=2.0))
def _search_images_serpapi(query: str, num: int = 10) -> List[Dict[str, Any]]:
    cache_key = f"serpapi_img_{query}"
    if cached := _search_cache.get(cache_key):
        return cached
    if not SERPAPI_KEY:
        return []
    try:
        from serpapi.google_search import GoogleSearch
        imgs = (GoogleSearch({"q": query, "tbm": "isch",
                              "api_key": SERPAPI_KEY, "num": num})
                .get_dict().get("images_results", []))
        results = [{"url": i.get("original"), "title": i.get("title"), "source": "serpapi"}
                   for i in imgs if i.get("original")]
        _search_cache.set(cache_key, results)
        return results
    except Exception as e:
        log.warning("[SEARCH] serpapi images failed: %s", e)
        return []


@retry_with_backoff(RetryConfig(max_retries=2, base_delay=1.0))
def _search_images_google_cse(query: str, num: int = 10) -> List[Dict[str, Any]]:
    """Image search via Google Custom Search JSON API (requires GOOGLE_CSE_ID + GOOGLE_API_KEY)."""
    cse_id = os.getenv("GOOGLE_CSE_ID", "")
    api_key = os.getenv("GOOGLE_API_KEY1") or os.getenv("GOOGLE_API_KEY", "")
    cache_key = f"cse_img_{query}"
    if cached := _search_cache.get(cache_key):
        return cached
    if not cse_id or not api_key:
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"q": query, "cx": cse_id, "key": api_key,
                    "searchType": "image", "num": min(num, 10)},
            timeout=30,
        ).json()
        results = [{"url": i.get("link"), "title": i.get("title"), "source": "cse"}
                   for i in resp.get("items", []) if i.get("link")]
        _search_cache.set(cache_key, results)
        return results
    except Exception as e:
        log.warning("[SEARCH] google cse images failed: %s", e)
        return []


# ── scoring / filtering ───────────────────────────────────────────────────────

def _filter_score(results: List[Dict[str, Any]], vendor: str,
                  product_type: str, models: List[str]) -> List[Dict[str, Any]]:
    """
    Score and rank search results for datasheet relevance.
    Vendor match is required. PDF/spec keywords boost. News/blog/forum penalise.
    """
    spec_kw = ["specification", "datasheet", "manual", "technical",
                "brochure", product_type.lower()]
    vendor_kw = [vendor.lower()] + vendor.lower().replace("(", "").replace(")", "").split()
    model_kw = [w for m in models if isinstance(m, str) for w in m.lower().split()]

    filtered = []
    for r in results:
        txt = f"{r.get('title','')} {r.get('url','')} {r.get('snippet','')}".lower()
        vendor_match = sum(1 for v in vendor_kw if v in txt)
        if not vendor_match:
            continue
        score = (sum(1 for k in spec_kw if k in txt) * 2
                 + vendor_match * 3
                 + sum(1 for k in model_kw if k in txt) * 2
                 + (3 if ".pdf" in txt else 0)
                 - sum(1 for t in ("news", "blog", "forum") if t in txt) * 2)
        if score >= 8:
            filtered.append({"matched_title": r.get("title"), "pdf_url": r.get("url"),
                              "source": r.get("source"), "score": score})
    return sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)


def _search_pdfs(vendor: str, product_type: str,
                 families: Optional[List[str]]) -> List[Dict[str, Any]]:
    """
    Discover datasheets for each model family via web search.
    Returns list of {vendor, model_family, pdfs:[{pdf_url, score}]}.
    """
    pdfs = []
    for model in (families or [None]):
        query = (f"{vendor} {product_type} {model or ''} "
                 "(specification OR datasheet OR manual) filetype:pdf").strip()
        urls = _search_serper(query) or _search_serpapi(query)
        if urls:
            filtered = _filter_score(urls, vendor, product_type,
                                     [model] if model else [])
            unique = list({r["pdf_url"]: r for r in filtered}.values())
            if unique:
                pdfs.append({"vendor": vendor, "model_family": model,
                             "pdfs": unique[:3]})
    return pdfs


# ── download helpers ──────────────────────────────────────────────────────────

@retry_with_backoff(RetryConfig(max_retries=2, base_delay=1.0))
def _download_image(url: str) -> Optional[bytes]:
    """Download a single image; returns None if download fails or content < 500 B."""
    try:
        r = requests.get(url, timeout=10, headers=_HEADERS)
        r.raise_for_status()
        return r.content if len(r.content) >= 500 else None
    except Exception as e:
        log.debug("[SEARCH] image download failed %s: %s", url, e)
        return None


@retry_with_backoff(RetryConfig(max_retries=2, base_delay=3.0))
def _download_to_blob(url: str, metadata: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """
    Stream-download a PDF from url and store it in Azure Blob + MongoDB.
    Returns (success, message, doc_id|None).
    Requires infra.storage.mongodb_file_manager.
    """
    from ..infra.storage import mongodb_file_manager
    try:
        data = b"".join(
            requests.get(url, timeout=60, headers=_HEADERS, stream=True).iter_content(8192))
        if len(data) < 1024:
            return False, "Too small", None
        doc_id = mongodb_file_manager.upload_document_to_blob(data, metadata)
        return True, f"OK {len(data)}", doc_id
    except Exception as e:
        return False, str(e), None
