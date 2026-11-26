"""
services/detection_router.py — the single detection entry point.

THIS APPLICATION IS PURE LLM. THERE IS NO ML FALLBACK.
=======================================================
Every symbol, every tag and every pipe run is read by a vision LLM. No trained
model participates in detection: no YOLOv8, no U-Net, no RapidOCR. When the
configured provider cannot see images, detection FAILS LOUDLY. It does not
quietly detour through a trained detector, because a silent detour changes what
the product is without telling anyone.

WHY THIS MODULE EXISTS
----------------------
There used to be three independent, disagreeing answers to "which detector
runs?":

  * main.py                  preferred the vision-LLM services, falling back to
                             the CV ones on ImportError.
  * api/detect.py            imported the CV services directly, always.
  * extraction_cli/image.py  (what the desktop app runs) also imported the CV
                             services directly.

So the same drawing produced different results depending on the entry point,
and the "no ML in the loop" property held only for the Flask upload route.
Every call site now resolves here.

A first attempt at this module offered `llm`, `cv` and `auto` engines with
`auto` falling back to the trained detectors. That reintroduced exactly the
ML involvement the design forbids, so the CV engine and the fallback are gone.
`STUDIO_DETECTION_ENGINE` is still read, but the only accepted value is `llm`;
anything else is refused rather than silently honoured.

WHAT IS NOT ML
--------------
The vision-LLM detectors reuse classical geometry helpers -- tiling, non-max
suppression, box merging, line grouping, leader-line filtering, snapping. Those
are arithmetic over coordinates, with no trained model and no learned weights,
and they are verified ML-free by tests/test_pure_llm_detection.py. OpenCV and
NumPy are likewise used only to cut tiles, measure ink density and encode PNGs.
Classical image manipulation is not machine learning; a trained detector is.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

#: The only supported engine. Kept as a named constant so the intent is greppable.
ENGINE = "llm"
VALID_ENGINES = (ENGINE,)

#: Packages that must never be imported as part of detection. Asserted by tests.
FORBIDDEN_ML_MODULES = ("torch", "torchvision", "ultralytics",
                        "rapidocr_onnxruntime", "onnxruntime")


class VisionUnavailable(RuntimeError):
    """The configured provider/model cannot accept images.

    Raised instead of falling back to a trained detector. Callers surface this
    to the operator so the fix is "configure a vision-capable model", not an
    invisible change of engine.
    """


@dataclass(frozen=True)
class DetectionBackend:
    """The three detector entry points, all vision-LLM."""
    engine: str
    requested: str
    detect_symbols: Callable
    detect_text: Callable
    detect_lines: Callable
    reason: str = ""

    @property
    def is_llm(self) -> bool:
        return True


def configured_engine() -> str:
    """Resolve the requested engine.

    Only "llm" is supported. A configured value of anything else is a
    misconfiguration: it is logged and refused rather than honoured, because
    honouring "cv" would mean running trained models.
    """
    for source, raw in (
        ("STUDIO_DETECTION_ENGINE", os.getenv("STUDIO_DETECTION_ENGINE")),
        ("detection_engine setting", _setting("detection_engine")),
    ):
        value = (raw or "").strip().lower()
        if not value:
            continue
        if value == ENGINE:
            return ENGINE
        logger.warning(
            "Ignoring %s=%r: this application is pure LLM and has no trained "
            "detector. The only supported value is %r.", source, value, ENGINE)
    return ENGINE


def _setting(key: str) -> str:
    try:
        from adapters.config import load_config
        return (load_config().get(key) or "").strip()
    except Exception:
        return ""


def provider_vision_status() -> tuple[bool, str]:
    """(can_see_images, human-readable reason). Never raises."""
    try:
        from adapters.llm_factory import get_provider
        provider = get_provider()
        if provider.supports_vision("fast"):
            return True, "provider fast tier is vision-capable"
        return False, "provider fast tier is not vision-capable"
    except Exception as exc:
        return False, "provider unavailable ({})".format(str(exc)[:120])


def resolve_backend(engine: str | None = None) -> DetectionBackend:
    """Return the vision-LLM detector trio.

    Raises VisionUnavailable when the provider cannot accept images, and
    ValueError when a caller explicitly asks for a non-LLM engine. Neither
    condition falls back to a trained model.
    """
    requested = (engine or configured_engine()).strip().lower()
    if requested != ENGINE:
        raise ValueError(
            "Unknown detection engine {!r}. This application is pure LLM: the "
            "only supported engine is {!r}, and there is no trained-model "
            "fallback.".format(requested, ENGINE))

    has_vision, why = provider_vision_status()
    if not has_vision:
        raise VisionUnavailable(
            "Agentic detection needs a vision-capable model and has no ML "
            "fallback by design, but {}. Point the fast tier at a model that "
            "accepts images (Anthropic Claude 3+, Gemini 1.5+, GPT-4o/5+, or "
            "an Ollama vision family such as llava/llama3.2-vision).".format(why))

    from services.llm_symbol_detection_service import process_detect_symbols
    from services.llm_text_detection_service import detect_text_from_bytes
    from services.llm_line_detection_service import detect_lines_from_bytes
    return DetectionBackend(ENGINE, requested, process_detect_symbols,
                            detect_text_from_bytes, detect_lines_from_bytes,
                            "vision-LLM detectors ({})".format(why))


def describe_backend() -> dict:
    """Non-raising diagnostic summary, for health endpoints and startup logs."""
    has_vision, why = provider_vision_status()
    info: dict[str, object] = {
        "requested": configured_engine(),
        "engine": ENGINE,
        "ml_fallback": False,
        "provider_vision": has_vision,
        "provider_detail": why,
    }
    try:
        backend = resolve_backend()
        info["resolved"] = backend.engine
        info["reason"] = backend.reason
    except Exception as exc:
        info["resolved"] = None
        info["reason"] = str(exc)[:300]
    return info


def assert_no_ml_imported() -> list[str]:
    """Return any forbidden ML package currently loaded.

    A guard for tests and for anyone debugging a claim that this pipeline is
    ML-free: if a trained-model package has been imported, detection is not
    what it says it is.
    """
    import sys
    return [m for m in FORBIDDEN_ML_MODULES if m in sys.modules]
