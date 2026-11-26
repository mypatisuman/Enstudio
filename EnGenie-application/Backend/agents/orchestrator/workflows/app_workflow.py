"""Application workflow — the unified agentic entry point.

run_app_request() routes one request to the extraction workflow, the
describe workflow, or the health report, and returns a uniform envelope:

    {"workflow": "...", "routing_reason": "...", "result": {...}}
    {"workflow": "describe", "pending_delete": {...}}   (interrupt passthrough)

The desktop app keeps calling the workflow entry points directly; this
surface exists for the API/MCP/automation callers.
"""
from __future__ import annotations

from agents.streaming import stage as emit_stage
from agents.orchestrator.agents.router_agent import route_request


def _already_digitised(pid: str, source_path: str) -> bool:
    """True when this exact file has already been extracted into the project."""
    import hashlib
    from pathlib import Path
    from adapters.db import get_db
    from agents.describe.services import repository as R
    if not R.digitisation_status(pid).get("digitised"):
        return False
    digest = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    row = get_db().execute("SELECT 1 FROM sources WHERE pid=? AND file_hash=? LIMIT 1",
                           (pid, digest)).fetchone()
    return row is not None


def run_brownfield_request(payload: dict, *, use_llm_router: bool = True,
                           extractor=None, describer=None) -> dict:
    """Digitise (when needed), then retrofit, as ONE request.

    payload: {pid, hub, message, source_path?, source_id?, session_id?,
              force_extract?}

    Extraction runs only when the project has no digitised drawing or this
    exact file has not been extracted before (matched by file hash), unless
    force_extract is set. The retrofit then runs as a normal Describe turn,
    so routing, the Holistic gate and the brownfield agent all apply.
    `extractor` / `describer` are injectable for tests.
    """
    pid, message = payload["pid"], (payload.get("message") or "").strip()
    source_path = payload.get("source_path")
    extraction = {"ran": False}
    if source_path and (payload.get("force_extract")
                        or not _already_digitised(pid, source_path)):
        if extractor is None:
            from agents.extraction.workflows.extraction_workflow import \
                run_extraction_agentic as extractor
        emit_stage("app_router", "brownfield_extract", pid=pid)
        result = extractor(payload["hub"], pid, source_path,
                           source_id=payload.get("source_id"))
        extraction = {"ran": True, "status": result.get("status"),
                      "nodes": len(result.get("verified_nodes") or [])}
        if result.get("status") == "failed":
            return {"workflow": "brownfield", "extraction": extraction,
                    "error": result.get("error") or "extraction failed"}
    if not message:
        return {"workflow": "brownfield", "extraction": extraction, "result": None}
    if describer is None:
        from agents.describe.workflows.describe_workflow import run_describe_turn
        from agents.checkpoints import make_checkpointer
        cp = make_checkpointer(payload["hub"]) if payload.get("hub") else None

        def describer(p, m, session_id):
            return run_describe_turn(p, m, session_id=session_id, checkpointer=cp,
                                     use_llm_router=use_llm_router)
    final = describer(pid, message, str(payload.get("session_id") or "app"))
    out = {"workflow": "brownfield", "extraction": extraction,
           "result": {"agent": final.get("agent"), "reply": final.get("reply"),
                      "ops": final.get("ops") or [],
                      "validation": final.get("validation"),
                      "exports": final.get("exports")}}
    if "__interrupt__" in final:
        out["pending_delete"] = final["__interrupt__"][0].value
    return out


def run_app_request(payload: dict, *, use_llm_router: bool = True) -> dict:
    """payload: {message?, source_path?, hub?, pid?, session_id?, mode?}

    mode="brownfield" digitises the uploaded drawing when needed and then
    applies the retrofit message to it, in one request.
    """
    if (payload.get("mode") or "").lower() == "brownfield":
        return run_brownfield_request(payload, use_llm_router=use_llm_router)
    message = (payload.get("message") or "").strip()
    has_file = bool(payload.get("source_path"))
    target, reason, controller = route_request(
        message, has_file=has_file, use_llm=use_llm_router)
    emit_stage("app_router", "routed", workflow=target, reason=reason,
               controller=controller)

    if target == "extraction":
        from agents.extraction.workflows.extraction_workflow import \
            run_extraction_agentic
        result = run_extraction_agentic(
            payload["hub"], payload["pid"], payload["source_path"],
            llm_only=bool(payload.get("llm_only")),
            source_id=payload.get("source_id"))
        return {"workflow": "extraction", "routing_reason": reason,
                "result": {"status": result.get("status"),
                           "nodes": len(result.get("verified_nodes") or []),
                           "edges": len(result.get("verified_edges") or []),
                           "proposals": len(result.get("proposals") or [])}}

    if target == "health":
        from agents.orchestrator.workflows.health import check_app_health
        return {"workflow": "health", "routing_reason": reason,
                "result": check_app_health()}

    from agents.describe.workflows.describe_workflow import run_describe_turn
    from agents.checkpoints import make_checkpointer
    cp = make_checkpointer(payload["hub"]) if payload.get("hub") else None
    final = run_describe_turn(payload["pid"], message,
                              session_id=str(payload.get("session_id")
                                             or "app"),
                              checkpointer=cp)
    if "__interrupt__" in final:
        return {"workflow": "describe", "routing_reason": reason,
                "pending_delete": final["__interrupt__"][0].value}
    return {"workflow": "describe", "routing_reason": reason,
            "result": {"agent": final.get("agent"),
                       "reply": final.get("reply"),
                       "ops": final.get("ops") or []}}
