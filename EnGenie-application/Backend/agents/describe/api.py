"""Flask blueprint for the Describe agent.

Additive and self-contained — NOT registered automatically. To expose it
from the studio server, add one line in main.py after app creation:

    from agents.describe.api import describe_agent_bp
    app.register_blueprint(describe_agent_bp)

Routes:
    POST /api/agent/describe/<pid>            {message, session_id?}
    POST /api/agent/describe/<pid>/resolve    {session_id, confirmed}

A response with {"pending_delete": ...} means the turn is paused on the
delete-confirmation interrupt; the client shows its confirm banner and
calls /resolve. All imports are lazy so registering the blueprint can
never break server startup.
"""
from __future__ import annotations

from flask_compat import Blueprint, jsonify, request

describe_agent_bp = Blueprint("describe_agent", __name__)
describe_agent_router = describe_agent_bp.router


def _checkpointer():
    from agents.checkpoints import make_checkpointer
    from utils.paths import resolve_hub      # shared hub resolution
    return make_checkpointer(resolve_hub())


@describe_agent_bp.post("/api/agent/describe/<pid>")
def describe_turn(pid: str):
    from agents.describe.workflows.describe_workflow import run_describe_turn
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400
    final = run_describe_turn(pid, message,
                              session_id=str(body.get("session_id") or "web"),
                              checkpointer=_checkpointer())
    if "__interrupt__" in final:
        return jsonify({"pending_delete": final["__interrupt__"][0].value})
    return jsonify({"reply": final.get("reply"),
                    "title": final.get("title"),
                    "solution_design": final.get("solution_design"),
                    "ops": final.get("ops") or [],
                    "agent": final.get("agent"),
                    "mode": final.get("mode"),
                    "analysis": final.get("analysis"),
                    "citations": final.get("citations") or [],
                    "sources": final.get("sources") or []})


@describe_agent_bp.get("/api/agent/health")
def agent_health():
    from agents.orchestrator.workflows.health import check_app_health
    return jsonify(check_app_health())


@describe_agent_bp.post("/api/agent/describe/<pid>/resolve")
def describe_resolve(pid: str):
    from agents.describe.workflows.describe_workflow import resolve_describe_turn
    body = request.get_json(silent=True) or {}
    final = resolve_describe_turn(pid,
                                  str(body.get("session_id") or "web"),
                                  bool(body.get("confirmed")),
                                  checkpointer=_checkpointer())
    if "__interrupt__" in final:
        return jsonify({"pending_delete": final["__interrupt__"][0].value})
    return jsonify({"reply": final.get("reply"),
                    "ops": final.get("ops") or []})
