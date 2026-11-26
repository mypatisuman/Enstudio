"""
bootstrap/cv_bootstrap.py — startup model warm-up. Now a deliberate no-op.

Detection in this application is performed by a vision LLM. There is no
YOLOv8, no U-Net and no RapidOCR, and no fallback to any of them, so there is
no model to load at startup and nothing to warm.

WHAT THIS USED TO DO
--------------------
It called `initialize_yolo_model()`, `initialize_ocr()` and
`initialize_unet_model()` through `main`, loading three trained models into
memory when the Flask server booted. The agentic extraction pipeline called it
too, from `agents/extraction/agents/orchestration.warmup()`, so every agentic
run loaded them as well. That was the largest remaining piece of real ML
involvement in a pipeline documented as having none.

WHY THE MODULE STILL EXISTS
---------------------------
`main.py` imports `_init_cv_models` at startup and
`helpers/cv_detection_helper.py` sits beside it, so keeping the symbol avoids a
pointless rename across the call sites. It is now genuinely empty of effect:
the real readiness check for a vision-LLM pipeline is "can the configured model
accept an image?", which `services/detection_router.provider_vision_status()`
answers, and which the agentic pipeline's `warmup` node enforces before any
page is processed.

Do not re-point this at trained-model initialisers. See
`services/_ml_disabled.py` for why those entry points now refuse.
"""
from __future__ import annotations


def _init_cv_models() -> None:
    """No-op: a vision LLM has no weights to preload.

    Kept callable, and deliberately silent, so `main.py`'s startup path and
    any other caller keep working without branching on whether a trained
    detector exists.
    """
    return None
