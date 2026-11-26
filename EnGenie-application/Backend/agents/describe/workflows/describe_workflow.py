"""Describe workflow — dispatch assembly ONLY (the reference convention:
workflows wire, agents work).

Each specialist is an independent compiled graph with its own checkpoint
thread (describe:{pid}:{session}:{agent}). One engineer message goes to
exactly one specialist. Only the Deletion agent can interrupt, so
resolve always resumes that agent's thread.

Holistic Agent (disambiguation gate): runs before authoring, update AND
deletion. It is NOT a specialist graph — it's a plain function call in
this dispatch layer, because its job is to decide whether to call a
specialist at all, not to itself hold a multi-step tool loop.

Clarification is a real cross-turn conversation: when the gate blocks
with "which one did you mean?", the pending context (original message,
intent, extracted tags, candidates, round) is persisted in the
describe_pending table — surviving restarts and multiple processes, the
same durability the deletion interrupt already has. The engineer's next
message is interpreted against that pending context:

  "2"  /  "option 2"          -> that candidate, deterministically
  "the one in area 100"       -> candidate whose area/row matches
  brand-new tags (disjoint)   -> pending dropped; treated as a new request
  anything else               -> merged with the original request and
                                 re-resolved; bounded rounds still apply

Grid recompute happens ONCE per turn, here, after the specialist
finishes — not per-write inside the tool loop. Any turn that applied
write ops gets a recompute, which also covers update_node (area/move
changes shift alignment groups) without per-tool flags.
"""
from __future__ import annotations

import json
import re

from agents.streaming import stage as emit_stage
from agents.describe.agents.holistic_agent import (
    MAX_CLARIFICATION_ROUNDS, _format_clarifying_question, extract_tags,
    resolve_target)
from agents.describe.agents.router import route_message
from agents.describe.agents.query_agent import build_query_agent
from agents.describe.agents.authoring_agent import build_authoring_agent
from agents.describe.agents.update_agent import build_update_agent
from agents.describe.agents.deletion_agent import build_deletion_agent
from agents.describe.agents.validation_agent import build_validation_agent
from agents.describe.agents.solution_agent import build_solution_agent
from agents.describe.agents.greenfield_agent import build_greenfield_agent
from agents.describe.agents.brownfield_agent import build_brownfield_agent

_BUILDERS = {
    "query": build_query_agent,
    "authoring": build_authoring_agent,
    "update": build_update_agent,
    "deletion": build_deletion_agent,
    "validation": build_validation_agent,
    "solution": build_solution_agent,
    "greenfield": build_greenfield_agent,
    "brownfield": build_brownfield_agent,
}

# greenfield/brownfield gated so their turns get the same spatial
# disambiguation AND engineering-completeness pre-check authoring/solution
# already receive (see the matching intent tuple in
# input_analyze_agent.evaluate_input_holisticness) — a clean-sheet or
# retrofit request with critical Class B constraints missing (fluid
# properties, control philosophy, SIL target, ...) now blocks with
# clarifying questions BEFORE the specialist starts inventing/authoring
# components, instead of guessing silently.
_GATED_INTENTS = {"authoring", "update", "deletion", "greenfield", "brownfield"}

#: Specialists that own a tool with requires_confirmation, in resume priority.
_CONFIRMING_AGENTS = ("deletion", "brownfield")

_TAG_IN_TEXT = re.compile(r"\b[A-Z]{1,5}-\d{1,6}[A-Z]?\b")


def _touched_tags(ops: list[dict]) -> set[str]:
    """Tags a turn's write ops created or changed, from args and results."""
    tags: set[str] = set()
    for op in ops or []:
        args = op.get("args") or {}
        for n in args.get("nodes") or []:
            if isinstance(n, dict) and n.get("tag"):
                tags.add(str(n["tag"]))
        for key in ("tag", "new_tag", "anchor_tag", "from_tag", "to_tag", "new_to"):
            if args.get(key):
                tags.add(str(args[key]))
        if isinstance(args.get("new_node"), dict) and args["new_node"].get("tag"):
            tags.add(str(args["new_node"]["tag"]))
        tags.update(_TAG_IN_TEXT.findall(str(op.get("result") or "")))
    return tags


def _post_write_validation(pid: str, ops: list[dict]) -> dict:
    """Validate what this turn touched: loops that include a touched tag, and
    the drawing-level quality score. Never raises."""
    try:
        from agents.describe.services import repository as R
        touched = _touched_tags(ops)
        loops = [l for l in R.get_loops(pid) if R.loop_members(l) & touched]
        incomplete = [l["loop_id"] for l in loops if l.get("status") != "complete"]
        drawing = R.validate_drawing(pid)
        return {"touched_tags": sorted(touched), "loops": len(loops),
                "incomplete_loops": incomplete, "drawing_score": drawing.get("score"),
                "orphans": drawing.get("orphans")}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _after_writes(pid: str, res: dict) -> None:
    """Shared follow-up for any turn that applied write ops: validation, then
    regeneration of the project's exports so they reflect the edit."""
    validation = _post_write_validation(pid, res.get("ops") or [])
    res["validation"] = validation
    # Full results travel as structured data (res["validation"]). The reply is
    # only amended when there is something to act on: a control loop this
    # turn touched that is still incomplete.
    if not validation.get("error") and res.get("reply") and validation["incomplete_loops"]:
        res["reply"] = (f"{res['reply']} Check: incomplete control loop(s) "
                        f"{', '.join(validation['incomplete_loops'])}.")
    try:
        from services.export_refresh import refresh_after_edit
        res["exports"] = refresh_after_edit(pid)
    except Exception as exc:
        res["exports"] = {"error": str(exc)[:200]}

    # Local accuracy metrics recording (0 LLM credits used)
    try:
        from domain.solution.services.pid_accuracy_service import save_accuracy_evaluation
        acc_rec = save_accuracy_evaluation(
            pid=pid,
            agent_type=res.get("agent") or "describe",
            user_message=res.get("last_message") or (res.get("reply") or "")[:120],
            metadata={"ops_count": len(res.get("ops") or [])}
        )
        res["accuracy_evaluation"] = {
            "score": acc_rec.get("accuracy_score"),
            "rating": acc_rec.get("rating"),
        }
    except Exception:
        pass


_SELECTION_RE = re.compile(
    r"^\s*(?:option|choice|number|#)?\s*(\d+)\s*\.?\s*$", re.IGNORECASE)


def thread_id(pid: str, session_id: str, agent: str) -> str:
    return f"describe:{pid}:{session_id}:{agent}"


# ── Pending-clarification store (describe_pending table) ─────────────────────

def _db():
    from adapters.db import get_db
    return get_db()


def _load_pending(pid: str, session_id: str) -> dict | None:
    try:
        row = _db().execute(
            "SELECT data_json FROM describe_pending WHERE pid=? AND session_id=?",
            (pid, session_id)).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def _save_pending(pid: str, session_id: str, data: dict) -> None:
    db = _db()
    db.execute(
        "INSERT INTO describe_pending (pid, session_id, data_json) VALUES (?,?,?) "
        "ON CONFLICT(pid, session_id) DO UPDATE SET data_json=excluded.data_json",
        (pid, session_id, json.dumps(data)))
    db.commit()


def _clear_pending(pid: str, session_id: str) -> None:
    try:
        db = _db()
        db.execute("DELETE FROM describe_pending WHERE pid=? AND session_id=?",
                   (pid, session_id))
        db.commit()
    except Exception:
        pass


# ── Clarification-reply interpretation ───────────────────────────────────────

def _parse_candidate_selection(reply: str, n: int) -> int | None:
    """'2', 'option 2', '#2.' -> 0-based index, when in range."""
    m = _SELECTION_RE.match(reply)
    if not m:
        return None
    idx = int(m.group(1))
    return idx - 1 if 1 <= idx <= n else None


def _match_candidate_by_detail(reply: str, candidates: list[dict]) -> dict | None:
    """A reply naming a candidate's distinguishing detail ('the one in
    area 100', 'row 3') selects it — only when exactly one matches."""
    rl = reply.lower()
    hits = []
    for c in candidates:
        needles = []
        if c.get("area"):
            needles.append(str(c["area"]).lower())
        if c.get("row") is not None:
            needles.append(f"row {c['row']}")
        if any(nd and nd in rl for nd in needles):
            hits.append(c)
    return hits[0] if len(hits) == 1 else None


# ── The gate ────────────────────────────────────────────────────────────────

def _blocked(pid: str, session_id: str, question: str, solution_design: dict | None = None,
             active_solution: dict | None = None, history: list[dict] | None = None) -> dict:
    res: dict = {"agent": "holistic", "reply": question, "messages": [], "ops": []}
    updated_solution = active_solution
    if solution_design:
        from agents.describe.services.solution_merger import merge_solution_designs
        updated_solution = merge_solution_designs(active_solution, solution_design)
        res["solution_design"] = updated_solution
    
    msgs = list(history or [])
    msgs.append({"role": "assistant", "content": question})
    from agents.describe.services import repository as R
    R.save_describe_session(pid, session_id, msgs, updated_solution)
    res["_history"] = msgs
    res["blocked"] = True
    return res


def _run_holistic_gate(pid: str, message: str, session_id: str,
                       intent: str, *, use_llm: bool) -> dict:
    """Fresh-request path (no pending). Returns either
    {"blocked_reply": q} or {"resolved_target": t|None, "dispatch_message": m, "holistic_context": dict}."""
    verdict, method = resolve_target(pid, message, intent=intent,
                                     use_llm=use_llm)
    emit_stage("holistic_agent", "resolved", clarity=verdict.clarity,
              method=method, candidates=len(verdict.candidates))

    holistic_context = {
        "resolved_target": verdict.resolved_target,
        "inferred_plant_type": getattr(verdict, "inferred_plant_type", ""),
        "unit_operations": getattr(verdict, "unit_operations", []),
        "inferred_control_strategy": getattr(verdict, "inferred_control_strategy", ""),
    }

    if verdict.clarity in ("clear", "no_target"):
        return {"resolved_target": verdict.resolved_target,
                "dispatch_message": message,
                "holistic_context": holistic_context}

    _save_pending(pid, session_id, {
        "message": message, "intent": intent, "tags": verdict.tags,
        "candidates": verdict.candidates, "round": 1,
    })
    return {
        "blocked_reply": _format_clarifying_question(verdict),
        "solution_design": getattr(verdict, "solution_design", None),
    }


def _subsystem_gate(pid: str, session_id: str, intent: str, message: str,
                    resolved_target: dict | None,
                    holistic_context: dict | None) -> dict:
    """Brownfield only: make sure a retrofit knows which subsystem it goes into.
    Returns {"blocked_reply": q} or {"dispatch_message": m}."""
    if intent != "brownfield":
        return {"dispatch_message": message}
    from agents.describe.services import subsystem_gate as SG
    try:
        verdict = SG.check(pid, message)
    except Exception as exc:                     # fail open, like the Holistic gate
        emit_stage("subsystem_gate", "error", error=str(exc)[:200])
        return {"dispatch_message": message}
    emit_stage("subsystem_gate", verdict["status"], reason=verdict.get("reason"),
               candidates=len(verdict.get("candidates") or []))
    if verdict["status"] == "proceed":
        return {"dispatch_message": message + (verdict.get("note") or "")}
    _save_pending(pid, session_id, {
        "kind": SG.KIND, "message": message, "intent": intent,
        "candidates": verdict["candidates"], "round": 1,
        "resolved_target": resolved_target, "holistic_context": holistic_context,
    })
    return {"blocked_reply": verdict["question"]}


def _resolve_subsystem_reply(pid: str, session_id: str, reply: str,
                             pending: dict, *, use_llm: bool) -> dict:
    """Answer to "which subsystem?". Same outcome shapes as
    _resolve_pending_reply, plus "holistic_context" on dispatch."""
    from agents.describe.services import subsystem_gate as SG
    candidates = pending.get("candidates") or []
    outcome, chosen = SG.interpret(reply, candidates)

    def _go(note: str, prefix: str | None = None) -> dict:
        _clear_pending(pid, session_id)
        return {"dispatch": pending["intent"], "dispatch_message": pending["message"] + note,
                "resolved_target": pending.get("resolved_target"), "prefix_note": prefix,
                "holistic_context": pending.get("holistic_context")}

    if outcome == "select" and chosen:
        emit_stage("subsystem_gate", "selected", subsystem=chosen["name"])
        return _go(SG.dispatch_note(chosen))
    if outcome == "none":
        emit_stage("subsystem_gate", "left_unassigned")
        return _go(SG.dispatch_note(None))

    # Same test as the tag gate: a different intent is a new request, except a
    # query the router only guessed at (short answers often look like one).
    new_intent, reason, _ = route_message(pid, reply, use_llm=use_llm)
    if new_intent != pending["intent"] and (
            new_intent != "query" or "keyword match" in reason.lower()):
        _clear_pending(pid, session_id)
        return {"new_request": True}
    if pending.get("round", 1) >= MAX_CLARIFICATION_ROUNDS:
        emit_stage("subsystem_gate", "round_limit_reached_proceeding")
        return _go(SG.dispatch_note(None),
                   "I couldn't tell which subsystem you meant, so the new equipment is "
                   "left unassigned; move it with assign_to_subsystem when ready.")
    _save_pending(pid, session_id, {**pending, "round": pending.get("round", 1) + 1})
    return {"blocked_reply": SG.question(candidates, "Sorry, I didn't catch which one.")}


def _resolve_pending_reply(pid: str, session_id: str, reply: str,
                           pending: dict, *, use_llm: bool) -> dict:
    """Interpret the engineer's message as an answer to the pending
    clarifying question. Returns one of:
      {"dispatch": intent, "dispatch_message": m, "resolved_target": t,
       "prefix_note": str|None}
      {"blocked_reply": q, "solution_design": d}  — update & redisplay refined solution
      {"new_request": True}                         — unrelated message; re-route fresh
    """
    candidates = pending.get("candidates") or []
    intent = pending["intent"]

    rl = reply.strip().lower()
    clean_rl = re.sub(r"^\[mode:[^\]]+\]\s*", "", reply.strip(), flags=re.IGNORECASE).strip().lower()
    is_explicit_build = (
        clean_rl.startswith("implement the following")
        or clean_rl.startswith("approved")
        or clean_rl in ("proceed", "build", "yes", "confirm", "ok", "build solution on canvas", "go ahead", "build now", "generate p&id", "build canvas", "build from image")
        or "build solution on canvas" in clean_rl
        or "build canvas" in clean_rl
        or "build from image" in clean_rl
        or "build now" in clean_rl
    )
    if is_explicit_build:
        _clear_pending(pid, session_id)
        emit_stage("holistic_agent", "build_approved_dispatching")
        combined = pending["message"]
        comb_lower = combined.lower()
        if "extract" in comb_lower or "uploaded" in comb_lower or "drawing" in comb_lower or "image" in comb_lower or "scan" in comb_lower:
            intent = "brownfield"
        elif intent not in _BUILDERS:
            intent = "solution"
        return {"dispatch": intent, "dispatch_message": combined,
                "resolved_target": candidates[0] if candidates else None,
                "prefix_note": None,
                "is_direct_build": True}

    # If the user selected an option number from spatial disambiguation:
    sel = _parse_candidate_selection(reply, len(candidates))
    if sel is not None and not any(k in rl for k in ("psv", "psig", "bar", "valve", "temp", "pressure")):
        _clear_pending(pid, session_id)
        emit_stage("holistic_agent", "candidate_selected", index=sel + 1)
        return {"dispatch": intent, "dispatch_message": pending["message"],
                "resolved_target": candidates[sel], "prefix_note": None}

    # Match by detail (e.g. area name)
    c_match = _match_candidate_by_detail(reply, candidates)
    if c_match:
        _clear_pending(pid, session_id)
        emit_stage("holistic_agent", "candidate_selected_by_detail")
        return {"dispatch": intent, "dispatch_message": pending["message"],
                "resolved_target": c_match, "prefix_note": None}

    # Check for unrelated new request via intent mismatch or disjoint tags
    new_intent, reason, _ = route_message(pid, reply, use_llm=use_llm)
    if new_intent != intent:
        is_actual_unrelated = (
            new_intent != "query" or
            (new_intent == "query" and "keyword match" in reason.lower())
        )
        if is_actual_unrelated:
            _clear_pending(pid, session_id)
            return {"new_request": True}

    from agents.describe.agents.holistic_agent import extract_tags
    new_tags = extract_tags(pid, reply, use_llm=use_llm)
    pending_tags = pending.get("tags") or []
    if new_tags and not any(t in pending_tags for t in new_tags):
        _clear_pending(pid, session_id)
        return {"new_request": True}

    # Bounded clarification rounds (round limit reached -> proceed)
    if pending.get("round", 1) >= MAX_CLARIFICATION_ROUNDS:
        _clear_pending(pid, session_id)
        emit_stage("holistic_agent", "round_limit_reached_proceeding")
        return {"dispatch": intent, "dispatch_message": pending["message"],
                "resolved_target": candidates[0] if candidates else None,
                "prefix_note": "I still couldn't fully disambiguate your target, so I proceeded with the first option:"}

    # Accumulate the user's additional data into previous input data:
    combined = f"{pending['message']}\n\nAdditional Parameters & Refinements:\n{reply}"
    verdict, _method = resolve_target(pid, combined, intent=intent, use_llm=use_llm)
    updated_solution = getattr(verdict, "solution_design", None)

    _save_pending(pid, session_id, {
        "message": combined,
        "intent": intent,
        "tags": verdict.tags or pending.get("tags") or [],
        "candidates": verdict.candidates or candidates,
        "round": pending.get("round", 1) + 1,
    })

    reply_text = _format_clarifying_question(verdict)
    return {
        "blocked_reply": reply_text,
        "solution_design": updated_solution,
    }



# ── Turn entry points ────────────────────────────────────────────────────────

#: Specialists that answer without changing the drawing.
_READ_ONLY_INTENTS = {"query", "validation"}


def _sources_of(messages: list[dict]) -> list[str]:
    """Card ids the retrieval tool returned during the turn."""
    out: list[str] = []
    for m in messages or []:
        content = str(m.get("content") or "")
        if m.get("role") == "tool" and content.startswith("retrieve_pid_context: SOURCES:"):
            line = content.split("\n", 1)[0].split("SOURCES:", 1)[1]
            out += [s.strip() for s in line.split(",") if s.strip() and s.strip() not in out]
    return out


def _ground_answer(pid: str, res: dict) -> None:
    """Every [TAG] an answer cites must be on the drawing; unknown ones are
    un-bracketed and named. Adds res["citations"] and res["sources"]."""
    if not res.get("reply"):
        return
    try:
        from domain.pid_rag.citations import check_citations
        from domain.pid_rag.snapshot import load_snapshot
        checked = check_citations(res["reply"], load_snapshot(pid)["tags"])
    except Exception as exc:
        emit_stage("rag", "citation_check_failed", error=str(exc)[:200])
        return
    res["reply"] = checked["reply"]
    res["citations"] = checked["citations"]
    if checked["unknown"]:
        res["uncited_tags"] = checked["unknown"]
    res["sources"] = _sources_of(res.get("messages") or [])


def _fixed_prompt_tokens(pid: str, intent: str, active_solution: dict | None) -> int:
    """Tokens a specialist's prompt holds before any memory: its instructions,
    the graph summary, the designed solution and the tool list."""
    from agents.describe.prompts import catalog as P
    from agents.describe.services import chat_memory as CM
    prompt = {
        "query": P.DESCRIBE_QUERY_V1, "authoring": P.DESCRIBE_AUTHORING_V1, "update": P.DESCRIBE_UPDATE_V1,
        "deletion": P.DESCRIBE_DELETION_V1, "validation": P.DESCRIBE_VALIDATION_V1,
        "solution": P.DESCRIBE_SOLUTION_V1, "greenfield": P.DESCRIBE_GREENFIELD_V1,
        "brownfield": P.DESCRIBE_BROWNFIELD_V1,
    }.get(intent, "")
    from agents.describe.agents.router import safe_summary
    solution = json.dumps(active_solution, indent=2) if active_solution else ""
    return CM.tokens(prompt) + CM.tokens(safe_summary(pid)) + CM.tokens(solution) + 800


def _dispatch(pid: str, session_id: str, intent: str, message: str,
              resolved_target: dict | None, prefix_note: str | None,
              checkpointer, graphs: dict | None,
              holistic_context: dict | None = None,
              active_solution: dict | None = None,
              history: list[dict] | None = None,
              mem: dict | None = None,
              focus: list[str] | None = None,
              record_message: str | None = None) -> dict:
    """Run one specialist on `message`. `history` already holds the engineer's
    message as typed (`record_message`); the specialist sees the recent window
    of it plus the chat memory, and `message` (the standalone step) as its task."""
    builder = _BUILDERS.get(intent)
    if not builder:
        return {"reply": f"Internal error: unknown intent '{intent}'",
                "messages": [], "ops": []}
    graph = (graphs or {}).get(intent) or builder(checkpointer)
    config = {"configurable": {"thread_id": thread_id(pid, session_id, intent)}}

    msgs = list(history or [])
    recorded = record_message or message
    last_user = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), None)
    if not msgs or (msgs[-1].get("content") != recorded and last_user != recorded):
        msgs.append({"role": "user", "content": recorded})

    from agents.describe.services import chat_memory as CM
    if mem is None:
        mem = CM.load(pid, session_id)
    budget = CM.budget_for(_fixed_prompt_tokens(pid, intent, active_solution))
    ctx = CM.build_context(mem, msgs, query=message, focus=focus, budget_tokens=budget)
    emit_stage("chat_memory", "context", agent=intent, **ctx["stats"])
    init_state = {
        "messages": ctx["messages"],
        "project_id": pid,
        "session_id": session_id,
        "user_message": message,
        "resolved_target": resolved_target,
        "holistic_context": holistic_context or {},
        "active_solution": active_solution,
        "prefix_note": prefix_note,
        "memory_context": ctx["memory_block"],
    }
    final = graph.invoke(init_state, config)
    res = {**final, "agent": intent}
    if final.get("ops"):
        from agents.describe.base import _recompute_grid_safely
        _recompute_grid_safely(pid)
        _after_writes(pid, res)
    if prefix_note and "reply" in res:
        res["reply"] = f"{prefix_note} {res['reply']}"
    if intent == "query":
        _ground_answer(pid, res)

    new_sol = res.get("solution_design")
    updated_solution = active_solution
    if new_sol:
        from agents.describe.services.solution_merger import merge_solution_designs
        updated_solution = merge_solution_designs(active_solution, new_sol)
        res["solution_design"] = updated_solution

    if res.get("reply"):
        msgs.append({"role": "assistant", "content": res["reply"]})
    from agents.describe.services import repository as R
    R.save_describe_session(pid, session_id, msgs, updated_solution)
    res["_history"] = msgs
    res["_active_solution"] = updated_solution

    # Terminal Process Tracking
    comp = (updated_solution or {}).get("completeness") or {}
    roles_cnt = len((updated_solution or {}).get("component_roles") or [])
    ops_cnt = len(res.get("ops") or [])
    print(f"[describe] Solution State: {roles_cnt} components | Maturity: {comp.get('score', 0)}% | Canvas Threshold: {'READY (>=60%)' if comp.get('can_build_canvas') else 'DRAFTING'}", flush=True)
    print(f"[describe] TURN FINISHED | Agent: {intent} | Ops: {ops_cnt} | Reply: {(res.get('reply') or '')[:90]}...", flush=True)
    print(f"[describe] ==============================================================\n", flush=True)

    return res


def _run_change(pid: str, session_id: str, step_message: str, original: str, *,
                checkpointer, graphs, use_llm_router: bool, active_solution: dict | None,
                history: list[dict], mem: dict, focus: list[str]) -> dict:
    """A build / update step: route to the specialist, then the gates, then
    dispatch - the path every message took before input analysis existed."""
    clean_msg = re.sub(r"^\[mode:[^\]]+\]\s*", "", original.strip(), flags=re.IGNORECASE).strip().lower()
    is_direct_build = (
        "build solution on canvas" in clean_msg
        or "build canvas" in clean_msg
        or "build from image" in clean_msg
        or "extract and build" in clean_msg
        or clean_msg in ("proceed", "build", "build now", "generate p&id")
    )
    message = step_message
    intent, reason, controller = route_message(pid, message, use_llm=use_llm_router)
    if is_direct_build:
        if "extract" in clean_msg or "uploaded" in clean_msg or "drawing" in clean_msg or "image" in clean_msg or "scan" in clean_msg:
            intent = "brownfield"
        elif intent not in _BUILDERS:
            intent = "solution"
    print(f"[describe] Routing Decision: Intent -> '{intent}' (via {controller}: {reason})", flush=True)
    emit_stage("describe_router", "routed", intent=intent, reason=reason,
               controller=controller)

    # A retrofit needs a drawing to retrofit. Refuse before spending any model
    # call, with the step the engineer has to take, rather than letting the
    # brownfield agent improvise a plant from nothing.
    if intent == "brownfield":
        from agents.describe.services import repository as _R
        if not _R.digitisation_status(pid).get("digitised"):
            from domain.solution.services.brownfield_vision_service import (
                is_vision_rebuild_request, resolve_uploaded_drawing
            )
            has_drawing = resolve_uploaded_drawing(pid)[0] is not None
            wants_rebuild = is_vision_rebuild_request(message)
            if not (has_drawing or wants_rebuild):
                reply = ("This project has no digitised drawing yet, so there is nothing "
                         "to retrofit. Upload and extract the existing P&ID first, then "
                         "repeat the request. To design a new plant from scratch instead, "
                         "ask for a greenfield design.")
                return _blocked(pid, session_id, reply, None,
                                active_solution=active_solution, history=history) | {
                    "agent": "brownfield", "status": "not_digitised"}

    resolved_target = None
    dispatch_message = message
    holistic_context = None

    # Digitising an uploaded drawing READS a plant; it does not design one.
    # The completeness gate's questions (fluid identity, trays, SIL target)
    # and the "which subsystem?" question do not apply, and used to block
    # "analyze the uploaded drawing" before any vision call was made.
    if intent == "brownfield" and not is_direct_build:
        from domain.solution.services.brownfield_vision_service import is_vision_rebuild_request
        if is_vision_rebuild_request(message):
            is_direct_build = True
            emit_stage("holistic_agent", "skipped", reason="drawing digitisation request")

    if intent in _GATED_INTENTS and not is_direct_build:
        gate = _run_holistic_gate(pid, message, session_id, intent,
                                  use_llm=use_llm_router)
        if "blocked_reply" in gate:
            return _blocked(pid, session_id, gate["blocked_reply"], gate.get("solution_design"),
                            active_solution=active_solution, history=history)
        resolved_target = gate["resolved_target"]
        dispatch_message = gate["dispatch_message"]
        holistic_context = gate.get("holistic_context")

    if not is_direct_build:
        sub = _subsystem_gate(pid, session_id, intent, dispatch_message,
                              resolved_target, holistic_context)
        if "blocked_reply" in sub:
            return _blocked(pid, session_id, sub["blocked_reply"], None,
                            active_solution=active_solution, history=history)
        dispatch_message = sub["dispatch_message"]

    return _dispatch(pid, session_id, intent, dispatch_message,
                     resolved_target, None, checkpointer, graphs,
                     holistic_context=holistic_context,
                     active_solution=active_solution, history=history,
                     mem=mem, focus=focus, record_message=original)


def _run_question(pid: str, session_id: str, step_message: str, original: str, *,
                  checkpointer, graphs, use_llm_router: bool, active_solution: dict | None,
                  history: list[dict], mem: dict, focus: list[str]) -> dict:
    """A question about the built P&ID: the retrieval-augmented Query agent,
    or the Validation agent for quality checks. Neither changes the drawing,
    so no gate applies."""
    intent, reason, controller = route_message(pid, step_message, use_llm=use_llm_router)
    intent = "validation" if intent == "validation" else "query"
    print(f"[describe] Question -> '{intent}' (router said: {reason})", flush=True)
    emit_stage("describe_router", "routed", intent=intent, reason=f"question; {reason}",
               controller=controller)
    return _dispatch(pid, session_id, intent, step_message, None, None, checkpointer, graphs,
                     active_solution=active_solution, history=history,
                     mem=mem, focus=focus, record_message=original)


def _combine(results: list[dict]) -> dict:
    """One response for a turn that ran several steps (e.g. a change, then a question)."""
    if len(results) == 1:
        return results[0]
    final = dict(results[-1])
    final["reply"] = "\n\n".join(r["reply"] for r in results if r.get("reply"))
    final["ops"] = [op for r in results for op in (r.get("ops") or [])]
    final["citations"] = list(dict.fromkeys(t for r in results for t in (r.get("citations") or [])))
    final["sources"] = list(dict.fromkeys(s for r in results for s in (r.get("sources") or [])))
    final["agent"] = "+".join(str(r.get("agent")) for r in results)
    final["title"] = next((r.get("title") for r in results if r.get("title")), None)
    final["solution_design"] = next((r.get("solution_design") for r in reversed(results)
                                     if r.get("solution_design")), None)
    final["steps"] = [{"agent": r.get("agent"), "reply": r.get("reply")} for r in results]
    return final


def _remember(pid: str, session_id: str, mem: dict, message: str, analysis: dict,
              results: list[dict]) -> None:
    """Fold the finished turn into the chat memory. Never raises."""
    try:
        from agents.describe.services import chat_memory as CM
        from domain.pid_rag.snapshot import load_snapshot
        CM.record_turn(pid, session_id, mem, message=message, analysis=analysis,
                       results=results, known_tags=load_snapshot(pid)["tags"])
    except Exception as exc:
        emit_stage("chat_memory", "record_failed", error=str(exc)[:200])


_INTERNAL_KEYS = ("_history", "_active_solution")


def _public(res: dict, analysis: dict | None) -> dict:
    out = {k: v for k, v in res.items() if k not in _INTERNAL_KEYS}
    if analysis:
        out["analysis"] = {k: analysis.get(k) for k in ("mode", "steps", "standalone", "method", "reason")}
        out["mode"] = analysis.get("mode")
    return out


def run_describe_turn(pid: str, message: str, session_id: str = "default",
                      *, checkpointer=None, use_llm_router: bool = True,
                      graphs: dict | None = None,
                      history: list[dict] | None = None,
                      **kwargs) -> dict:
    """One conversational turn:
        [pending clarification?] -> input analysis (build / update / question /
        mixed, rewritten as standalone steps with the chat memory) -> per step:
        change: route -> [holistic + subsystem gates] -> specialist
        question: retrieval-augmented Query agent (or Validation)
        -> answers checked against the drawing -> chat memory updated.

    The returned dict always carries "agent" ("holistic" when blocked on
    a clarifying question) and, for analysed turns, "mode" and "analysis".
    "__interrupt__" means a delete confirmation is pending — resume with
    resolve_describe_turn()."""
    print(f"\n[describe] ==============================================================", flush=True)
    print(f"[describe] [TURN START] | Project: {pid} | Session: {session_id}", flush=True)
    msg_preview = message.strip().replace('\n', ' ')
    print(f"[describe] Message: {msg_preview[:120]}{'...' if len(msg_preview) > 120 else ''}", flush=True)

    from agents.describe.services import repository as R
    from agents.describe.services import chat_memory as CM
    session_data = R.get_describe_session(pid, session_id) or {}
    if history is None:
        history = list(session_data.get("history") or [])
    else:
        history = list(history)
    active_solution = session_data.get("active_solution")
    if not history or history[-1].get("content") != message:
        history.append({"role": "user", "content": message})

    if active_solution:
        prior_roles = len(active_solution.get("component_roles") or [])
        prior_score = active_solution.get("completeness", {}).get("score", 0)
        print(f"[describe] Session Context Memory Loaded: {prior_roles} components active (Score: {prior_score}%)", flush=True)

    # Context memory of this chat: older messages fold into the rolling summary
    mem = CM.load(pid, session_id)
    if CM.maintain(mem, history, use_llm=use_llm_router):
        emit_stage("chat_memory", "episode_added", upto=mem["summarized_upto"],
                   episodes=len(mem.get("episodes") or []))
    # the input analysis sees a compact memory: a slice of the budget its own prompt leaves
    from agents.describe.prompts.catalog import DESCRIBE_TURN_ANALYSIS_V1
    analysis_budget = int(0.15 * CM.budget_for(CM.tokens(DESCRIBE_TURN_ANALYSIS_V1)))
    memory_context = CM.context_block(mem, max_tokens=analysis_budget, query=message)

    pending = _load_pending(pid, session_id)
    if pending:
        print(f"[describe] Resolving Pending Clarification (Round {pending.get('round', 1)})...", flush=True)
        if pending.get("kind") == "subsystem":
            outcome = _resolve_subsystem_reply(pid, session_id, message, pending,
                                               use_llm=use_llm_router)
        else:
            outcome = _resolve_pending_reply(pid, session_id, message, pending,
                                             use_llm=use_llm_router)
            if "dispatch" in outcome:
                if not outcome.get("is_direct_build"):
                    # A resolved tag can still leave the subsystem open.
                    sub = _subsystem_gate(pid, session_id, outcome["dispatch"],
                                          outcome["dispatch_message"],
                                          outcome["resolved_target"], None)
                    if "blocked_reply" in sub:
                        res = _blocked(pid, session_id, sub["blocked_reply"], None,
                                       active_solution=active_solution, history=history)
                        _remember(pid, session_id, mem, message, {"mode": "clarification"}, [res])
                        return _public(res, None)
                    outcome["dispatch_message"] = sub["dispatch_message"]
        clarification = {"mode": "clarification", "standalone": message}
        if "blocked_reply" in outcome:
            res = _blocked(pid, session_id, outcome["blocked_reply"], outcome.get("solution_design"),
                           active_solution=active_solution, history=history)
            _remember(pid, session_id, mem, message, clarification, [res])
            return _public(res, None)
        if "dispatch" in outcome:
            res = _dispatch(pid, session_id, outcome["dispatch"],
                            outcome["dispatch_message"],
                            outcome["resolved_target"],
                            outcome["prefix_note"], checkpointer, graphs,
                            holistic_context=outcome.get("holistic_context"),
                            active_solution=active_solution, history=history,
                            mem=mem, focus=CM.focus_tags(mem), record_message=message)
            _remember(pid, session_id, mem, message, clarification, [res])
            return _public(res, None)
        # new_request: fall through to normal analysis of this message.

    # Input analysis: build / update / question / mixed, as standalone steps
    from agents.describe.services.turn_analysis import analyze_turn
    from agents.describe.agents.router import safe_summary
    analysis = analyze_turn(pid, message, memory_context=memory_context, focus=CM.focus_tags(mem),
                            graph_summary=safe_summary(pid), use_llm=use_llm_router)
    print(f"[describe] Input Analysis: mode={analysis['mode']} steps="
          f"{[s['kind'] for s in analysis['steps']]} via {analysis['method']}", flush=True)
    emit_stage("turn_analysis", "analysed", mode=analysis["mode"], method=analysis["method"],
               steps=len(analysis["steps"]))

    results: list[dict] = []
    deferred_block: dict | None = None
    for step in analysis["steps"]:
        run = _run_question if step["kind"] == "question" else _run_change
        res = run(pid, session_id, step["message"], message, checkpointer=checkpointer, graphs=graphs,
                  use_llm_router=use_llm_router, active_solution=active_solution, history=history,
                  mem=mem, focus=list(dict.fromkeys(analysis.get("referenced_tags") or [])))
        history = res.get("_history") or history
        active_solution = res.get("_active_solution", active_solution)
        if "__interrupt__" in res:          # a deletion awaits confirmation: stop here
            results.append(res)
            break
        if res.get("blocked") and len(analysis["steps"]) > 1:
            # a change waits on a clarifying question; still answer the questions
            # asked alongside it, and ask the clarifying question last
            deferred_block = res
            continue
        results.append(res)
    if deferred_block is not None:
        results.append(deferred_block)
    _remember(pid, session_id, mem, message, analysis, results)
    return _public(_combine(results), analysis)


def _has_pending_interrupt(graph, config) -> bool:
    """True when `config`'s thread holds a checkpoint paused on an interrupt.

    Returns False (rather than raising) when the graph was compiled without a
    checkpointer, or when the thread has never run -- both mean "nothing to
    resume".
    """
    try:
        snapshot = graph.get_state(config)
    except Exception:
        return False
    if snapshot is None:
        return False
    # `next` is non-empty only while the graph is paused mid-run. The
    # project_id check guards a checkpoint that exists but carries no state.
    values = getattr(snapshot, "values", None) or {}
    return bool(getattr(snapshot, "next", None)) and bool(values.get("project_id"))


def resolve_describe_turn(pid: str, session_id: str, confirmed: bool,
                          *, checkpointer=None,
                          graphs: dict | None = None,
                          **kwargs) -> dict:
    """Resume the Deletion agent's pending confirmation — it is the only
    specialist that interrupts."""
    from langgraph.types import Command
    # Deletion used to be the only specialist that could pause. Brownfield now
    # owns confirmed delete tools as well, so resume whichever one is actually
    # parked on an interrupt for this session.
    agent_name, graph, config = "deletion", None, None
    for candidate in _CONFIRMING_AGENTS:
        g = (graphs or {}).get(candidate) or _BUILDERS[candidate](checkpointer)
        cfg = {"configurable": {"thread_id": thread_id(pid, session_id, candidate)}}
        if _has_pending_interrupt(g, cfg):
            agent_name, graph, config = candidate, g, cfg
            break
    if graph is None:
        graph = (graphs or {}).get("deletion") or _BUILDERS["deletion"](checkpointer)
        config = {"configurable": {"thread_id": thread_id(pid, session_id, "deletion")}}

    # Resuming a thread that has no checkpointed interrupt does NOT no-op:
    # LangGraph starts the graph from empty state, the first node raises
    # KeyError('project_id'), and @retryable_node's on_exhausted handler turns
    # that into "I could not reach the language model" -- blaming the provider
    # for what is really "there is nothing to confirm". The UI hits this
    # whenever a confirm/cancel is sent twice, or after a restart cleared the
    # thread, so it needs a truthful answer instead.
    if not _has_pending_interrupt(graph, config):
        return {"agent": agent_name, "status": "no_pending", "ops": [],
                "messages": [],
                "reply": "There is no deletion awaiting confirmation for this "
                         "conversation. It may already have been confirmed or "
                         "cancelled."}

    final = graph.invoke(Command(resume={"confirmed": confirmed}), config)
    if final.get("ops"):
        from agents.describe.base import _recompute_grid_safely
        _recompute_grid_safely(pid)
        _after_writes(pid, final)
    from agents.describe.services import chat_memory as CM
    _remember(pid, session_id, CM.load(pid, session_id),
              "confirmed the deletion" if confirmed else "cancelled the deletion",
              {"mode": "update"}, [{**final, "agent": agent_name}])
    return {**final, "agent": agent_name}


def create_describe_workflow(checkpointer=None):
    """Factory returning the primary describe StateGraph for LangGraph deployment."""
    return build_brownfield_agent(checkpointer=checkpointer)

