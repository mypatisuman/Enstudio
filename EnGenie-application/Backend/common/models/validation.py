"""Warn-don't-raise response validation for use at workflow/HTTP edges.

The default mode is a pure guard rail: it validates the payload and logs a
warning on mismatch, but always returns the original data untouched so it can
never break a live endpoint. Pass normalize=True to opt into the cleaned dump.
"""

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def validate_response(
    model_cls: type[BaseModel],
    data: dict[str, Any],
    *,
    context: str = "",
    normalize: bool = False,
) -> dict[str, Any]:
    """Validate `data` against `model_cls`. Never raises.

    Returns the original dict by default (guard-rail mode). With normalize=True,
    returns the validated model dumped to a JSON-safe dict on success.
    """
    if not isinstance(data, dict):
        return data
    try:
        model = model_cls.model_validate(data)
    except ValidationError as e:
        logger.warning(
            "[MODEL_VALIDATION] %s failed for %s: %s",
            model_cls.__name__,
            context or "response",
            e,
        )
        return data
    if normalize:
        return model.model_dump(by_alias=True, exclude_none=True)
    return data
