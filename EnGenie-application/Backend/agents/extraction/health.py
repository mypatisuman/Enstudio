"""Extraction workflow health check (reference check_X_agent_health
convention). Every probe is failure-isolated; the report never raises.
"""
from __future__ import annotations

EXTRACTION_PROMPTS = [
    "qc_preamble", "supervisor_route", "symbol_qc", "text_qc", "line_qc",
    "cv_consolidation", "geometry_qc", "deletion_justify",
    "proposal_conflict", "unreadable_crops_addendum",
]


def check_extraction_health() -> dict:
    checks: dict = {}

    try:
        from agents.extraction.workflows.extraction_workflow import \
            build_extraction_workflow
        build_extraction_workflow(checkpointer=None)
        checks["graph_compiles"] = True
    except Exception as e:
        checks["graph_compiles"] = f"FAIL: {str(e)[:150]}"

    try:
        from agents.prompts import load_prompt
        missing = [n for n in EXTRACTION_PROMPTS
                   if not _loads(load_prompt, n)]
        checks["prompts"] = True if not missing else f"MISSING: {missing}"
    except Exception as e:
        checks["prompts"] = f"FAIL: {str(e)[:150]}"

    # No trained-detector probes here. Detection is pure LLM: there is no
    # YOLOv8, RapidOCR or U-Net in the loop, so their importability is not a
    # health signal. What matters is whether the configured model can see.

    # Vision readiness IS the detection health signal. With no ML fallback, a
    # provider that cannot accept images means extraction cannot run at all --
    # so this must read as degraded rather than quietly passing.
    try:
        from services.detection_router import describe_backend
        detection = describe_backend()
        checks["detection_engine"] = detection.get("resolved") or "FAIL: " +             str(detection.get("reason"))
        checks["ml_fallback"] = False
        checks["provider_vision"] = detection.get("provider_vision")
        checks["provider_detail"] = detection.get("provider_detail")
    except Exception as e:
        checks["detection_engine"] = f"FAIL: {str(e)[:150]}"
        checks["ml_fallback"] = False

    # Hard guarantee, not a claim: if a trained-model package has been imported
    # by anything in this process, detection is not what it says it is.
    try:
        from services.detection_router import assert_no_ml_imported
        loaded = assert_no_ml_imported()
        checks["no_ml_loaded"] = True if not loaded else f"ML LOADED: {loaded}"
    except Exception as e:
        checks["no_ml_loaded"] = f"FAIL: {str(e)[:120]}"

    try:
        from adapters.db import get_db
        get_db().execute("SELECT 1")
        checks["db"] = True
    except Exception as e:
        checks["db"] = f"FAIL: {str(e)[:150]}"

    try:
        from agents.extraction.agents.orchestration import configured_provider
        checks["llm_provider"] = configured_provider() or "not configured"
    except Exception as e:
        checks["llm_provider"] = f"FAIL: {str(e)[:150]}"

    # A resolvable detection engine is load-bearing: without one, extraction
    # cannot produce anything, so it belongs in the healthy/degraded verdict.
    ok = all(v is True for k, v in checks.items()
             if k in ("graph_compiles", "prompts", "db"))
    engine = checks.get("detection_engine")
    ok = ok and isinstance(engine, str) and not engine.startswith("FAIL")         and engine != "NONE"
    return {"workflow": "extraction",
            "status": "healthy" if ok else "degraded", "checks": checks}


def _loads(loader, name: str) -> bool:
    try:
        return bool(loader(name).strip())
    except Exception:
        return False
