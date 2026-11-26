"""Deterministic cache-key helper for Pydantic models and plain values."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def cache_key(*parts: Any) -> str:
    """Stable MD5 over any mix of Pydantic models and JSON-able values.

    Models serialize via model_dump_json() (deterministic field order); other
    values via json.dumps(sort_keys=True, default=str).
    """
    pieces: list[str] = []
    for p in parts:
        if isinstance(p, BaseModel):
            pieces.append(p.model_dump_json())
        else:
            pieces.append(json.dumps(p, sort_keys=True, default=str))
    return hashlib.md5("|".join(pieces).encode("utf-8")).hexdigest()
