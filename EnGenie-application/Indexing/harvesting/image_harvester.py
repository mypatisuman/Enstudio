"""
Image acquisition for Indexing pipeline.

Product images:
  search_and_verify_product(vendor, model, product_type) -> dict|None
  collect_product_images(product_type, vendor, model_families) -> list[dict]
  check_image_exists(vendor, model, product_type) -> bool
  store_product_image(img_bytes, vendor, model, product_type, source_url) -> bool

Vendor logos:
  search_and_verify_logo(vendor_name) -> dict|None
  collect_vendor_logo(vendor_name) -> bool
  check_logo_exists(vendor_norm) -> bool
  store_vendor_logo(img_bytes, vendor, source_url) -> bool

AI image generation (Imagen 4):
  generate_image_nano_banana(product_name, client) -> bytes
  verify_image_with_llm(img_bytes, product_name, client) -> bool

Shared:
  normalize_image_for_llm(img_bytes) -> (bytes, mime_type) | None
  _get_genai_client() -> google.genai.Client
"""

import io
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .resilience import RetryConfig, retry_with_backoff, get_next_google_api_key
from .web_search import (_search_images_serper, _search_images_serpapi,
                         _search_images_google_cse, _download_image)
from ..infra.storage import (azure_blob_manager, cache_image, get_cached_image,
                              mongo_src)

log = logging.getLogger(__name__)


# ── shared LLM client ─────────────────────────────────────────────────────────

def _get_genai_client():
    """Initialise google.genai client with next available API key."""
    from google import genai
    return genai.Client(api_key=get_next_google_api_key())


def _get_llm(temperature: float = 0.1):
    import sys
    import os
    _HERE = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.abspath(os.path.join(_HERE, "..", "..", "Backend"))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from common.ai.llm.manager import get_flash_llm
    return get_flash_llm(temperature=temperature)


# ── image normalisation ───────────────────────────────────────────────────────

def normalize_image_for_llm(image_bytes: bytes) -> Optional[Tuple[bytes, str]]:
    """
    Convert image bytes to JPEG (RGB) so Gemini can safely process them.
    Handles palette/RGBA/LA modes. Returns (jpeg_bytes, 'image/jpeg') or None.
    """
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        log.debug("[IMAGE] normalize_image_for_llm failed: %s", e)
        return None


# ── LLM image verification ────────────────────────────────────────────────────

@retry_with_backoff(RetryConfig(max_retries=6, base_delay=5.0))
def verify_single_image_with_llm(image_bytes: bytes, query: str,
                                  image_type: str = "product") -> bool:
    """Return True if LLM confirms the image matches the query."""
    normalized = normalize_image_for_llm(image_bytes)
    if not normalized:
        return False
    img_bytes, mime = normalized
    if image_type == "logo":
        prompt = (f"Does this image show the '{query}' company logo with a transparent "
                  f"or clean background? Reply EXACTLY 'YES' if correct logo with clean "
                  f"background, or 'NO' otherwise.")
    else:
        prompt = (f"Does this image clearly show a professional '{query}' industrial "
                  f"product/equipment? Reply EXACTLY 'YES' if correct, or 'NO' otherwise.")
    
    import base64
    from langchain_core.messages import HumanMessage
    
    b64_data = base64.b64encode(img_bytes).decode("utf-8")
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
            },
        ]
    )
    
    llm = _get_llm(temperature=0.1)
    resp = llm.invoke([message])
    return "YES" in resp.content.strip().upper()


@retry_with_backoff(RetryConfig(max_retries=6, base_delay=5.0))
def select_best_image_with_llm(images: List[Dict[str, Any]], query: str,
                                image_type: str = "product") -> Optional[int]:
    """Ask LLM to pick the best image from a list; returns index or None."""
    if not images:
        return None
    if image_type == "logo":
        prompt = (f"I'm providing {len(images)} logo images for '{query}'. "
                  f"Select the index (0,1,2...) of the BEST logo with transparent/clean background. "
                  f"Reply with ONLY the integer index or 'NONE'.")
    else:
        prompt = (f"I'm providing {len(images)} product images for '{query}'. "
                  f"Select the index (0,1,2...) of the BEST professional product image. "
                  f"Reply with ONLY the integer index or 'NONE'.")
    
    import base64
    from langchain_core.messages import HumanMessage
    
    content = [{"type": "text", "text": prompt}]
    for i, img in enumerate(images):
        normalized = normalize_image_for_llm(img["bytes"])
        if normalized:
            img_bytes, mime = normalized
            b64_data = base64.b64encode(img_bytes).decode("utf-8")
            content.append({"type": "text", "text": f"\nImage {i}:"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
            })
            
    message = HumanMessage(content=content)
    llm = _get_llm(temperature=0.1)
    resp = llm.invoke([message])
    result = resp.content.strip().upper()
    if "NONE" in result:
        return None
    m = re.search(r"\d+", result)
    if m:
        idx = int(m.group())
        return idx if 0 <= idx < len(images) else None
    return None


# ── product images ────────────────────────────────────────────────────────────

def check_image_exists(vendor_name: str, model_family: str,
                       product_type: str) -> bool:
    return get_cached_image(vendor_name, model_family, product_type) is not None


def store_product_image(img_bytes: bytes, vendor_name: str, model_family: str,
                        product_type: str, source_url: str = "") -> bool:
    nv = vendor_name.strip().lower().replace(" ", "_").replace("-", "_")
    nm = model_family.strip().lower().replace(" ", "_").replace("-", "_")
    np_ = product_type.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        blob_info = azure_blob_manager.upload_product_image(
            img_bytes, np_, nv, nm, content_type="image/jpeg")
        return cache_image(vendor_name, model_family, product_type,
                           img_bytes, "image/jpeg", blob_info, source_url)
    except Exception as e:
        log.error("[IMAGE] store_product_image failed %s %s: %s", vendor_name, model_family, e)
        return False


def search_and_verify_product(vendor: str, model: str,
                              product_type: str) -> Optional[Dict[str, Any]]:
    """
    Multi-engine search → download → LLM verify pipeline for one model family.
    Returns {"bytes": ..., "url": ...} of the best verified image, or None.
    """
    search_queries = [f"{vendor} {model} {product_type} product"]
    image_urls: List[Dict[str, Any]] = []
    for q in search_queries:
        urls = (_search_images_serper(q, num=10)
                or _search_images_serpapi(q, num=10)
                or _search_images_google_cse(q, num=10))
        if urls:
            image_urls.extend(urls)

    valid: List[Dict[str, Any]] = []
    for img in image_urls[:8]:
        img_bytes = _download_image(img["url"])
        if not img_bytes:
            continue
        term = f"{vendor} {model} {product_type}"
        if verify_single_image_with_llm(img_bytes, term, image_type="product"):
            valid.append({"bytes": img_bytes, "url": img["url"],
                          "title": img.get("title", "")})
        if len(valid) >= 4:
            break

    if not valid:
        return None
    best_idx = select_best_image_with_llm(valid, f"{vendor} {model} {product_type}") or 0
    return valid[best_idx]


def collect_product_images(product_type: str, vendor_name: str,
                           model_families: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Collect product images for all model families (parallel, max 2 workers).
    Each entry in model_families should have at least {"model_series": "..."}.
    """
    src = mongo_src()
    images_col = src["images"]

    def _collect_one(mf: Dict[str, Any]) -> Dict[str, Any]:
        model = mf.get("model_series", "")
        if not model:
            return {"success": False, "model": "", "reason": "no_model_series"}
        nv = vendor_name.strip().lower().replace(" ", "_").replace("-", "_")
        nm = model.strip().lower().replace(" ", "_").replace("-", "_")
        np_ = product_type.strip().lower().replace(" ", "_").replace("-", "_")
        doc_id = f"product_image_{np_}_{nv}_{nm}"
        if images_col.find_one({"id": doc_id}):
            return {"success": True, "model": model, "cached": True}
        best = search_and_verify_product(vendor_name, model, product_type)
        if not best:
            return {"success": False, "model": model, "reason": "no_valid_images"}
        ok = store_product_image(best["bytes"], vendor_name, model,
                                 product_type, best.get("url", ""))
        return {"success": ok, "model": model}

    with ThreadPoolExecutor(max_workers=min(len(model_families) or 1, 2)) as ex:
        results = list(ex.map(_collect_one, model_families))

    ok = sum(1 for r in results if r.get("success"))
    log.info("[IMAGE] product images: %d/%d succeeded for %s %s",
             ok, len(results), vendor_name, product_type)
    return results


# ── vendor logos ──────────────────────────────────────────────────────────────

def check_logo_exists(vendor_norm: str) -> bool:
    src = mongo_src()
    return bool(src["vendor_logos"].find_one({"vendor_name_normalized": vendor_norm}))


def store_vendor_logo(img_bytes: bytes, vendor_name: str,
                      source_url: str = "") -> bool:
    norm = vendor_name.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        blob_info = azure_blob_manager.upload_vendor_logo(img_bytes, norm, "image/png")
        src = mongo_src()
        doc = {
            "id": f"vendor_logo_{norm}",
            "type": "vendor_logo",
            "vendor_name": vendor_name,
            "vendor_name_normalized": norm,
            "image": blob_info,
            "contentType": "image/png",
            "fileSize": len(img_bytes),
            "createdAt": datetime.utcnow().isoformat(),
            "updatedAt": datetime.utcnow().isoformat(),
            "status": "active",
            "metadata": {"source": source_url, "verified_by_llm": True},
        }
        src["vendor_logos"].update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
        log.info("[IMAGE] Stored logo for %s -> %s", vendor_name, blob_info.get("blobUrl"))
        return True
    except Exception as e:
        log.error("[IMAGE] store_vendor_logo failed %s: %s", vendor_name, e)
        return False


def search_and_verify_logo(vendor_name: str) -> Optional[Dict[str, Any]]:
    """
    Multi-engine search → download → LLM verify for a vendor logo.
    Returns {"bytes": ..., "url": ...} or None.
    """
    query = f"{vendor_name} company logo transparent background PNG"
    image_urls = (_search_images_serper(query, num=10)
                  or _search_images_serpapi(query, num=10)
                  or _search_images_google_cse(query, num=10))
    if not image_urls:
        return None

    valid: List[Dict[str, Any]] = []
    for img in image_urls[:5]:
        img_bytes = _download_image(img["url"])
        if not img_bytes:
            continue
        if verify_single_image_with_llm(img_bytes, vendor_name, image_type="logo"):
            valid.append({"bytes": img_bytes, "url": img["url"],
                          "title": img.get("title", "")})
        if len(valid) >= 3:
            break

    if not valid:
        return None
    best_idx = (select_best_image_with_llm(valid, vendor_name, image_type="logo")
                if len(valid) > 1 else 0) or 0
    return valid[best_idx]


def collect_vendor_logo(vendor_name: str) -> bool:
    """Full pipeline: check cache → search → verify → store. Returns True on success."""
    norm = vendor_name.strip().lower().replace(" ", "_").replace("-", "_")
    if check_logo_exists(norm):
        log.info("[IMAGE] Logo already exists for %s", vendor_name)
        return True
    best = search_and_verify_logo(vendor_name)
    if not best:
        log.warning("[IMAGE] No valid logo found for %s", vendor_name)
        return False
    return store_vendor_logo(best["bytes"], vendor_name, best.get("url", ""))


# ── AI image generation (Imagen 4) ───────────────────────────────────────────

def generate_image_nano_banana(product_name: str, client=None) -> bytes:
    """
    Generate a product image. If LLM_PROVIDER is google, uses Imagen 4.0 via google-genai.
    Otherwise, raises NotImplementedError.
    """
    import sys
    import os
    _HERE = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.abspath(os.path.join(_HERE, "..", "..", "Backend"))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    from common.ai.llm.config import LLM_PROVIDER

    if LLM_PROVIDER == "google":
        from google.genai import types
        if client is None:
            client = _get_genai_client()
        prompt = (
            f"A professional high-quality product photograph of a {product_name} specifically "
            f"designed for industrial automation, process control, and manufacturing. "
            f"The object should look like industrial-grade equipment, typically featuring metallic "
            f"or rugged plastic enclosures, with wiring terminals, sensors, or digital displays if "
            f"typical for this device. Centered composition, studio lighting, isolated on a solid "
            f"pure white background (RGB 255,255,255), no transparency, no shadows, clean edges, "
            f"industrial product photography style."
        )
        result = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1,
                                              output_mime_type="image/jpeg"))
        return result.generated_images[0].image.image_bytes
    else:
        raise NotImplementedError(f"Image generation is not supported for provider '{LLM_PROVIDER}'.")


def verify_image_with_llm(image_bytes: bytes, product_name: str,
                           client=None) -> bool:
    """Verify a generated image matches the product name via LLM vision."""
    prompt = (
        f"You are a strict product photography expert. "
        f"Does this image clearly and accurately show a professional '{product_name}' "
        f"used in industrial or factory settings? "
        f"Reply with EXACTLY 'YES' if correct, or 'NO' if not."
    )
    import base64
    from langchain_core.messages import HumanMessage
    
    b64_data = base64.b64encode(image_bytes).decode("utf-8")
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"},
            },
        ]
    )
    
    llm = _get_llm(temperature=0.1)
    resp = llm.invoke([message])
    return "YES" in resp.content.strip().upper()
