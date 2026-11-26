"""Describe workflow health check (reference check_X_agent_health
convention). Every probe is failure-isolated; the report never raises.
"""
from __future__ import annotations

DESCRIBE_PROMPTS = [
    "describe_router", "describe_holistic", "describe_input_analyze", "describe_query",
    "describe_authoring", "describe_update", "describe_deletion",
    "describe_validation", "describe_solution",
]


def check_describe_health() -> dict:
    checks: dict = {}

    try:
        from agents.describe.workflows.describe_workflow import _BUILDERS
        failed = []
        for intent, builder in _BUILDERS.items():
            try:
                builder(None)
            except Exception:
                failed.append(intent)
        checks["specialist_graphs"] = True if not failed \
            else f"FAIL: {failed}"
    except Exception as e:
        checks["specialist_graphs"] = f"FAIL: {str(e)[:150]}"

    try:
        from agents.prompts import load_prompt
        missing = []
        for n in DESCRIBE_PROMPTS:
            try:
                if not load_prompt(n).strip():
                    missing.append(n)
            except Exception:
                missing.append(n)
        checks["prompts"] = True if not missing else f"MISSING: {missing}"
    except Exception as e:
        checks["prompts"] = f"FAIL: {str(e)[:150]}"

    try:
        from adapters.db import get_db
        get_db().execute("SELECT 1")
        checks["db"] = True
    except Exception as e:
        checks["db"] = f"FAIL: {str(e)[:150]}"

    ok = all(v is True for v in checks.values())
    return {"workflow": "describe",
            "status": "healthy" if ok else "degraded", "checks": checks}
