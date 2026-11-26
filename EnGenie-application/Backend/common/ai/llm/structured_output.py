"""
Reusable structured-output validation.

Ensure an LLM output conforms to a target Pydantic model; if it does not,
reprocess it into the model shape. Works for any Pydantic model, so the same
logic backs standards specs (`TechnicalSpecifications`), search vendor matches
(`ProductMatch`), ranking (`RankedProduct`), etc.

Pure module: no LLM/DB/infra imports. The optional reformat step is supplied by
the caller as a callable (`reformat_fn`), keeping this dependency-free and easy
to unit-test.
"""
import json
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

_FENCE_LEADING = re.compile(r"^```[a-zA-Z]*\s*")
_FENCE_TRAILING = re.compile(r"\s*```\s*$")
_JSON_OBJECT_OR_ARRAY = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def extract_json(raw: Any) -> Any | None:
    """Best-effort parse of an LLM response into JSON (dict or list).

    Strips markdown fences and any surrounding prose. Returns the parsed value
    (dict/list/…) or None if it cannot be parsed. No LLM call.
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw).strip()
    text = _FENCE_LEADING.sub("", text)
    text = _FENCE_TRAILING.sub("", text).strip()
    if not (text.startswith("{") or text.startswith("[")):
        match = _JSON_OBJECT_OR_ARRAY.search(text)
        if match:
            text = match.group(0)
    try:
        return json.loads(text)
    except Exception:
        return None


def coerce_to_model(
    data: Any,
    model_cls,
    *,
    reformat_fn: Callable[[str], Any] | None = None,
    allow_field_filter: bool = False,
    label: str = "",
):
    """Validate *data* against *model_cls*; reprocess if it does not conform.

    Tiers:
      1. Validate directly → return the model instance.
      2. If invalid and *reformat_fn* given: reformat the raw dump, re-validate.
         (`reformat_fn(raw_str) -> parsed_json_or_None`.)
      3. If invalid and *allow_field_filter* (lenient flat models only): keep the
         fields that individually validate, drop the rest.

    Returns a validated model instance, or None if it cannot be coerced.
    """
    name = getattr(model_cls, "__name__", str(model_cls))
    try:
        return model_cls.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[STRUCTURED_OUTPUT] %s output not compliant with %s: %s", label or "-", name, exc)

    if reformat_fn is not None:
        raw = data if isinstance(data, str) else json.dumps(data, default=str)
        try:
            fixed = reformat_fn(raw)
        except Exception as exc:  # noqa: BLE001
            logger.error("[STRUCTURED_OUTPUT] reformat failed for %s: %s", name, exc)
            fixed = None
        if fixed is not None:
            try:
                return model_cls.model_validate(fixed)
            except Exception as exc:  # noqa: BLE001
                logger.error("[STRUCTURED_OUTPUT] reprocessed %s still invalid: %s", name, exc)

    if allow_field_filter and isinstance(data, dict):
        safe: dict = {}
        for key, val in data.items():
            try:
                model_cls.model_validate({key: val})
                safe[key] = val
            except Exception:  # noqa: BLE001
                logger.warning("[STRUCTURED_OUTPUT] dropping non-conforming field '%s' for %s", key, name)
        try:
            return model_cls.model_validate(safe)
        except Exception:  # noqa: BLE001
            return None

    return None


def coerce_each(items: Any, model_cls, **kwargs) -> list:
    """Coerce a list of payloads to model instances, dropping any that cannot be
    coerced. Useful for lists like vendor `ProductMatch[]` or `RankedProduct[]`.

    Accepts the parsed list, or a raw string / dict that `extract_json` can turn
    into a list. Returns a list of validated model instances.
    """
    if isinstance(items, (str, bytes)):
        items = extract_json(items)
    if isinstance(items, dict):
        items = [items]
    out: list = []
    for it in (items or []):
        inst = coerce_to_model(it, model_cls, **kwargs)
        if inst is not None:
            out.append(inst)
    return out
