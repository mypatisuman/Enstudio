"""Redis (de)serialization wrappers for Pydantic models (Phase 5)."""

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def dump_for_redis(model: BaseModel) -> bytes:
    """Serialize a model to UTF-8 JSON bytes for Redis storage."""
    return model.model_dump_json().encode("utf-8")


def load_from_redis(model_cls: type[T], raw: bytes | str | None) -> T | None:
    """Rehydrate a model from Redis bytes/str. Returns None when raw is None."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return model_cls.model_validate_json(raw)
