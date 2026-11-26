"""
Resilience utilities for Indexing harvesting pipeline.

  RetryConfig            -- exponential-backoff configuration
  retry_with_backoff     -- decorator that retries on any exception
  SimpleCache            -- in-memory TTL cache for search results
  ProgressTracker        -- step/elapsed logger
  get_next_google_api_key -- round-robin over GOOGLE_API_KEY1/GOOGLE_API_KEY (~13 RPM)
  _extract_json          -- pull first JSON array/object from LLM text
  _clean_llm_content     -- strip markdown fences from LLM response
"""

import os
import re
import time
import threading
import logging
from functools import wraps

from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"))   # Indexing/.env

log = logging.getLogger(__name__)

# ── API key rotation ─────────────────────────────────────────────────────────

API_KEYS = [k for k in [os.getenv("GOOGLE_API_KEY1"), os.getenv("GOOGLE_API_KEY")] if k]
_key_lock = threading.Lock()
_current_idx = 0
_last_request_time: list = [0.0] * (len(API_KEYS) or 1)


def get_next_google_api_key() -> str:
    """Return the next available Google API key with ~13 RPM rate limiting per key."""
    global _current_idx
    with _key_lock:
        if not API_KEYS:
            log.warning("[RESILIENCE] No Google API keys configured")
            return ""
        now = time.time()
        elapsed = now - _last_request_time[_current_idx]
        if elapsed < 4.5:
            time.sleep(4.5 - elapsed)
        _last_request_time[_current_idx] = time.time()
        key = API_KEYS[_current_idx]
        _current_idx = (_current_idx + 1) % len(API_KEYS)
        return key


# ── Retry ────────────────────────────────────────────────────────────────────

class RetryConfig:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0,
                 max_delay: float = 60.0, exp_base: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exp_base = exp_base


def retry_with_backoff(config: RetryConfig = None):
    """Decorator: retry up to config.max_retries times with exponential backoff."""
    cfg = config or RetryConfig()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt == cfg.max_retries:
                        raise
                    delay = min(cfg.base_delay * (cfg.exp_base ** attempt), cfg.max_delay)
                    log.warning("[RESILIENCE] %s attempt %d/%d failed: %s — retry in %.1fs",
                                func.__name__, attempt + 1, cfg.max_retries, e, delay)
                    time.sleep(delay)
            raise last_exc   # unreachable but satisfies type checkers
        return wrapper
    return decorator


# ── Cache ────────────────────────────────────────────────────────────────────

class SimpleCache:
    """In-memory TTL cache keyed by string."""

    def __init__(self, ttl: float = 3600.0):
        self._cache: dict = {}
        self._ts: dict = {}
        self.ttl = ttl

    def get(self, key: str):
        if key in self._cache and time.time() - self._ts[key] < self.ttl:
            return self._cache[key]
        return None

    def set(self, key: str, value) -> None:
        self._cache[key] = value
        self._ts[key] = time.time()


# ── Progress tracker ─────────────────────────────────────────────────────────

class ProgressTracker:
    def __init__(self, total: int, name: str = "Op"):
        self.total = total
        self.step = 0
        self.name = name
        self._start = time.time()

    def update(self, msg: str) -> None:
        self.step += 1
        log.info("[%s] %d/%d — %s", self.name, self.step, self.total, msg)

    def elapsed(self) -> float:
        return time.time() - self._start


# ── LLM response parsing helpers ─────────────────────────────────────────────

def _extract_json(text: str) -> str:
    """Extract first JSON object or array from text."""
    m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    return m.group(1) if m else text


def _clean_llm_content(content) -> str:
    """Strip markdown code fences; join list content blocks."""
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return re.sub(r"\n?```$", "", re.sub(r"^```[a-zA-Z]*\n?", "", str(content))).strip()
