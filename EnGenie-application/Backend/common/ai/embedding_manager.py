"""
Embedding Manager - Vector embeddings for semantic search
Uses a hosted LLM embedding model (DeepInfra, OpenAI-compatible endpoint):
no model runs in this process.

Similarity scale: every threshold in the application (0.70-0.80 after the
(c + 1) / 2 mapping) was tuned on all-MiniLM-L6-v2. The hosted model scores
unrelated texts much higher (raw cosine ~0.6 where MiniLM gave ~0.2), so its
raw cosine is mapped onto MiniLM's scale by quantile matching, fitted on 3,655
pairs of instrumentation / procurement phrases. Each threshold keeps about
the same share of matches it had (0.75: 59 pairs before, 63 after).
"""

import logging
import os
import threading
import time
from collections import OrderedDict

import httpx
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("DEEPINFRA_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
EMBEDDING_DIM = int(os.getenv("DEEPINFRA_EMBEDDING_DIM", "1024"))
_BASE_URL = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai").rstrip("/")
_TIMEOUT = float(os.getenv("DEEPINFRA_EMBEDDING_TIMEOUT", "60"))
_BATCH = 64
_RETRIES = 3

# Qwen3-Embedding-0.6B raw cosine -> all-MiniLM-L6-v2 raw cosine (quantile knots)
_KNOTS_MODEL = [-1.0, 0.484, 0.51, 0.528, 0.546, 0.561, 0.578, 0.596, 0.618, 0.657,
                0.667, 0.673, 0.68, 0.692, 0.707, 0.722, 0.755, 0.809, 1.0]
_KNOTS_MINILM = [-1.0, 0.017, 0.051, 0.077, 0.101, 0.124, 0.15, 0.181, 0.221, 0.278,
                 0.302, 0.314, 0.326, 0.343, 0.36, 0.391, 0.466, 0.587, 1.0]
_CALIBRATED = EMBEDDING_MODEL == "Qwen/Qwen3-Embedding-0.6B"

_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_CACHE_MAX = 4096
_lock = threading.Lock()
_warned_dims: set[int] = set()


def _api_key() -> str:
    key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPINFRA_API_KEY is not set: embeddings are unavailable")
    return key


def _request(texts: list[str]) -> list[list[float]]:
    """One call to the embedding endpoint, retried on transient failures."""
    last = None
    for attempt in range(_RETRIES):
        try:
            r = httpx.post(f"{_BASE_URL}/embeddings",
                           headers={"Authorization": f"Bearer {_api_key()}"},
                           json={"model": EMBEDDING_MODEL, "input": texts, "encoding_format": "float"},
                           timeout=_TIMEOUT)
            if r.status_code == 200:
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code < 500 and r.status_code != 429:
                break                                   # a bad request / key: do not retry
        except httpx.HTTPError as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Embedding request failed: {last}")


def get_embedding_model() -> dict:
    """The hosted model's description (kept for health checks); raises when
    no API key is configured."""
    _api_key()
    return {"model": EMBEDDING_MODEL, "dimensions": EMBEDDING_DIM, "provider": "deepinfra"}


def generate_embedding(text: str) -> list[float] | None:
    """
    Generate embedding vector for a single text.

    Returns:
        List of floats (EMBEDDING_DIM) representing the embedding, or None if failed
    """
    if not text or not text.strip():
        return None
    key = text.strip()
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        emb = _request([key])[0]
    except Exception as e:
        logger.error(f"[EMBEDDING] Failed to generate embedding for text: {e}")
        return None
    with _lock:
        _cache[key] = emb
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return emb


def generate_embeddings_batch(texts: list[str], show_progress: bool = False) -> list[list[float] | None]:
    """
    Generate embeddings for multiple texts in batches.

    Returns:
        List of embeddings, None for empty texts (or for a batch that failed)
    """
    if not texts:
        return []
    result: list[list[float] | None] = [None] * len(texts)
    valid = [(i, t.strip()) for i, t in enumerate(texts) if t and t.strip()]
    for start in range(0, len(valid), _BATCH):
        chunk = valid[start:start + _BATCH]
        try:
            embs = _request([t for _i, t in chunk])
        except Exception as e:
            logger.error(f"[EMBEDDING] Failed to generate batch embeddings: {e}")
            continue
        for (i, _t), emb in zip(chunk, embs, strict=False):
            result[i] = emb
        if show_progress:
            logger.info(f"[EMBEDDING] {min(start + _BATCH, len(valid))}/{len(valid)} embedded")
    return result


def refresh_stale_embeddings(entries: list[dict]) -> int:
    """Re-embed, in place, every `<field>_embedding` whose vector came from
    another model (other dimensions), from the entry's `<field>` text. For
    records kept outside the database (strategy CSV payloads in blob storage),
    which are refreshed as they are loaded. Returns the number re-embedded."""
    todo: list[tuple[dict, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key, vec in list(entry.items()):
            if not key.endswith("_embedding") or not isinstance(vec, list) or len(vec) == EMBEDDING_DIM:
                continue
            text = entry.get(key[: -len("_embedding")])
            if isinstance(text, str) and text.strip():
                todo.append((entry, key, text))
            else:
                entry[key] = None
    if not todo:
        return 0
    embs = generate_embeddings_batch([t for _e, _k, t in todo])
    for (entry, key, _t), emb in zip(todo, embs, strict=False):
        entry[key] = emb
    logger.info(f"[EMBEDDING] Re-embedded {sum(e is not None for e in embs)}/{len(todo)} stale vectors with {EMBEDDING_MODEL}")
    return sum(e is not None for e in embs)


def _to_scale(raw: np.ndarray | float):
    """The hosted model's raw cosine on the scale the thresholds were tuned on."""
    return np.interp(raw, _KNOTS_MODEL, _KNOTS_MINILM) if _CALIBRATED else raw


def _dims_ok(dim: int) -> bool:
    """A vector stored by the previous model (384 dimensions) cannot be compared:
    it must be re-embedded (scripts/reembed_vectors.py)."""
    if dim == EMBEDDING_DIM:
        return True
    if dim not in _warned_dims:
        _warned_dims.add(dim)
        logger.warning(f"[EMBEDDING] Ignoring stored vectors of {dim} dimensions (model {EMBEDDING_MODEL} "
                       f"gives {EMBEDDING_DIM}); re-embed them with scripts/reembed_vectors.py")
    return False


def cosine_similarity(embedding1: list[float], embedding2: list[float]) -> float:
    """
    Similarity between two embeddings, 0 to 1 (1 = identical); 0.0 when they
    come from different models (dimensions differ).
    """
    try:
        vec1, vec2 = np.asarray(embedding1, dtype=float), np.asarray(embedding2, dtype=float)
        if vec1.shape != vec2.shape or not _dims_ok(vec1.shape[0]) or not _dims_ok(vec2.shape[0]):
            return 0.0
        norm1, norm2 = np.linalg.norm(vec1), np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        raw = float(np.dot(vec1, vec2) / (norm1 * norm2))
        return float((_to_scale(raw) + 1) / 2)
    except Exception as e:
        logger.error(f"[EMBEDDING] Failed to calculate cosine similarity: {e}")
        return 0.0


def find_most_similar(query_embedding: list[float],
                      candidate_embeddings: list[list[float]],
                      threshold: float = 0.75) -> list[tuple]:
    """
    Find most similar embeddings to a query embedding.

    Returns:
        List of tuples (index, similarity_score) sorted by similarity (highest first);
        candidates of another model's dimensions are skipped
    """
    try:
        query_vec = np.asarray(query_embedding, dtype=float)
        if not _dims_ok(query_vec.shape[0]):
            return []
        query_norm = np.linalg.norm(query_vec)
        results = []
        for i, cand in enumerate(candidate_embeddings):
            if cand is None:
                continue
            vec = np.asarray(cand, dtype=float)
            if vec.shape != query_vec.shape:
                _dims_ok(vec.shape[0])
                continue
            norm = np.linalg.norm(vec)
            if norm == 0 or query_norm == 0:
                continue
            sim = float((_to_scale(float(vec @ query_vec / (norm * query_norm))) + 1) / 2)
            if sim >= threshold:
                results.append((i, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    except Exception as e:
        logger.error(f"[EMBEDDING] Failed to find similar embeddings: {e}")
        return []
