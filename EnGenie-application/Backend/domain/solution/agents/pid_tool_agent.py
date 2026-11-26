"""
pid_tool_agent.py - the bounded tool-loop engine shared by the P&ID specialists.

This is infrastructure, not an agent. Each specialist supplies its own name,
prompt and tool registry and gets back a runner with the same guarantees
everywhere: bounded steps, JSON armor, unknown-tool rejection, write auditing,
and a confirmation gate for tools that declare requires_confirmation.

WHY A LOOP INSTEAD OF ONE CALL
------------------------------
The previous greenfield and brownfield agents made a single LLM call that had
to emit the entire node/edge graph as one JSON object. That meant the model
never read the drawing it was editing, could not check whether a tag already
existed, and produced different wiring on every run. Here the model takes one
step at a time against a live PIDGraphStore: inspect, then author, then report.

The loop is plain Python rather than a LangGraph StateGraph because these
specialists are called synchronously from solution_build_node and have no
cross-turn checkpoint of their own. The tool contract, step budget and
confirmation gate are the parts that matter, and they are identical either way.

NOTE ON DELETION
----------------
Tools marked requires_confirmation never run unconfirmed. A caller may decide
immediately with a `confirm` callback, or pass a `deferred` list: the request
is then queued, persisted with the drawing as its pending_action, and applied
only when the engineer approves it through POST /api/pid/confirm. With neither,
the tool is refused and the model is told to ask in its reply.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from typing import Any, Callable

from domain.solution.services.pid_graph_store import PIDGraphStore

logger = logging.getLogger(__name__)

MAX_STEPS = 14

_CATALOG_HEADER = (
    "\n\nTOOL SIGNATURES (authoritative: call tools with exactly these "
    "argument names)\n")


def tool_catalog(tools: dict[str, dict]) -> str:
    """Authoritative tool signatures, generated from the functions themselves.

    The P&ID prompts used to hand-write their tool lists, and they drifted: the
    prompt taught get_node(node_id) while the code took `tag`, so the agent
    wasted steps on argument errors. Generating this from inspect.signature
    makes that class of drift impossible.
    """
    lines = []
    for name, spec in tools.items():
        fn = getattr(PIDGraphStore, spec["method"])
        params = []
        try:
            for pname, p in inspect.signature(fn).parameters.items():
                if pname == "self":
                    continue
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                params.append(pname if p.default is p.empty
                              else "%s=%r" % (pname, p.default))
        except (TypeError, ValueError):
            pass
        doc = spec.get("doc") or (inspect.getdoc(fn) or "")
        doc = " ".join(doc.split("\n\n")[0].split())
        flags = []
        if spec.get("writes"):
            flags.append("writes")
        if spec.get("requires_confirmation"):
            flags.append("engineer must confirm")
        flag_text = " [%s]" % ", ".join(flags) if flags else ""
        lines.append("- %s(%s)%s: %s" % (name, ", ".join(params), flag_text,
                                         doc or name))
    return "\n".join(lines)


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _undouble(text: str) -> str:
    return text.replace("{{", "{").replace("}}", "}")


def fill_prompt(template: str, values: dict[str, str]) -> str:
    """Fill {name} placeholders the way ChatPromptTemplate.from_template does,
    so the P&ID prompts keep this repo's convention of doubling literal braces.

    Not str.format and not a blanket replace: the values are JSON, and JSON
    that ends in a nested object ends in "}}". Un-doubling after substitution
    would corrupt it, so only the template's own literal text is un-doubled.
    Placeholders not in `values` (e.g. {tool_catalog}) are left for a later
    stage."""
    out: list[str] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(template):
        if m.start() > 0 and template[m.start() - 1] == "{":
            continue                        # inside a doubled literal: {{x}}
        if m.group(1) not in values:
            continue
        out.append(_undouble(template[pos:m.start()]))
        out.append(values[m.group(1)])
        pos = m.end()
    out.append(_undouble(template[pos:]))
    return "".join(out)


def _transcript(messages: list[dict]) -> str:
    return "\n".join("%s: %s" % (m["role"].upper(), m["content"])
                     for m in messages)


class ToolLoopResult:
    """What one specialist turn produced."""

    def __init__(self, store: PIDGraphStore, reply: str, steps: int,
                 ops: list[dict], used_llm: bool,
                 rejected_tools: list[str] | None = None,
                 hit_step_limit: bool = False) -> None:
        self.store = store
        self.reply = reply
        self.steps = steps
        self.ops = ops
        self.used_llm = used_llm
        self.rejected_tools = rejected_tools or []
        #: True when the budget ran out before the model replied. The work so
        #: far is in `store`, but it may be half a drawing.
        self.hit_step_limit = hit_step_limit

    @property
    def wrote_anything(self) -> bool:
        return bool(self.ops)


def build_tool_agent(agent_name: str, tools: dict[str, dict],
                     max_steps: int = MAX_STEPS) -> Callable:
    """Compile a dedicated specialist: its own prompt, its own tools.

    tools: {name: {"method": str, "writes": bool,
                   "requires_confirmation": bool?, "doc": str?}}

    Returns run(store, system_prompt, user_message, llm_complete, confirm=None,
    deferred=None).
    """
    catalog = tool_catalog(tools)

    def run(store: PIDGraphStore, system_prompt: str, user_message: str,
            llm_complete: Callable[[str], str],
            confirm: Callable[[dict], bool] | None = None,
            deferred: list[dict] | None = None) -> ToolLoopResult:
        """Run one specialist turn.

        Destructive tools (requires_confirmation) are, in order of preference:
        decided now by `confirm`, queued into `deferred` for the engineer to
        approve later, or refused. They are never executed unconfirmed."""
        messages: list[dict] = [{"role": "engineer", "content": user_message}]
        rejected: list[str] = []
        steps = 0

        if "{tool_catalog}" in system_prompt:
            system = system_prompt.replace("{tool_catalog}", catalog)
        else:
            system = system_prompt + _CATALOG_HEADER + catalog

        while steps < max_steps:
            prompt = (system + "\n\nCONVERSATION SO FAR\n" +
                      _transcript(messages) + "\n\nYour JSON response:")
            try:
                raw = llm_complete(prompt)
            except Exception as exc:
                logger.warning("[%s] LLM call failed at step %d: %s",
                               agent_name, steps, exc)
                raise

            parsed = _parse(raw)
            if not parsed:
                messages.append({
                    "role": "tool",
                    "content": "ERROR: your last message was not valid JSON. "
                               "Reply with a single JSON object containing "
                               "either 'tool' and 'args', or 'reply'."})
                steps += 1
                continue

            requested = parsed.get("tool")
            if not requested:
                reply = (parsed.get("reply") or "").strip()
                if not reply:
                    reply = "Design complete. " + store.graph_summary()
                return ToolLoopResult(store, reply, steps, store.ops, True, rejected)

            if requested not in tools:
                # Dedicated-agent boundary: this specialist does not own that
                # tool. Surface it so the model recovers in-loop rather than
                # failing the turn.
                rejected.append(requested)
                messages.append({"role": "assistant", "content": json.dumps(parsed)})
                messages.append({
                    "role": "tool",
                    "content": "ERROR: tool '%s' is not available to the %s. "
                               "Available tools: %s. If the engineer's request "
                               "needs it, say so in a reply instead."
                               % (requested, agent_name, sorted(tools))})
                steps += 1
                continue

            spec = tools[requested]
            args = parsed.get("args") or {}
            if not isinstance(args, dict):
                messages.append({"role": "tool",
                                 "content": "ERROR: args must be an object"})
                steps += 1
                continue

            if spec.get("requires_confirmation"):
                targets = args.get("tags") or [
                    t for t in (args.get("from_tag"), args.get("to_tag")) if t]
                request = {"tool": requested, "method": spec["method"],
                           "args": args, "tags": targets,
                           "reason": args.get("reason", "")}
                if confirm is not None:
                    outcome = None if confirm(request) else \
                        "CANCELLED by the engineer. Do not retry it."
                elif deferred is not None:
                    # The engineer confirms later, from the P&ID Studio: the
                    # request is persisted with the drawing and applied by
                    # POST /api/pid/confirm. Nothing is removed in this turn.
                    deferred.append(request)
                    outcome = ("QUEUED FOR CONFIRMATION. The engineer will be "
                               "asked to approve removing %s; nothing has been "
                               "removed yet. Do not retry it. Finish the rest of "
                               "the request and mention the pending removal in "
                               "your reply." % (", ".join(targets) or requested))
                else:
                    outcome = ("NOT CONFIRMED. Deletion needs the engineer's "
                               "explicit approval, which is not available in "
                               "this turn. Do not retry it; say what you would "
                               "remove in your reply instead.")
                if outcome:
                    messages.append({"role": "assistant",
                                     "content": json.dumps(parsed)})
                    messages.append({"role": "tool",
                                     "content": "%s: %s" % (requested, outcome)})
                    steps += 1
                    continue

            try:
                result = getattr(store, spec["method"])(**args)
            except TypeError as exc:
                result = "ERROR: bad arguments for %s: %s" % (requested, exc)
            except Exception as exc:
                result = "ERROR: %s failed: %s" % (requested, str(exc)[:200])

            content = result if isinstance(result, str) else json.dumps(
                result, default=str)
            messages.append({"role": "assistant", "content": json.dumps(parsed)})
            messages.append({"role": "tool",
                             "content": "%s: %s" % (requested, content[:2000])})
            steps += 1

        applied = [op.get("result") for op in store.ops]
        done = ("Applied so far: " + " | ".join(str(a) for a in applied)
                if applied else "No changes were applied.")
        reply = ("I reached my step limit (%d) before finishing. %s Send the "
                 "next part of the request to continue." % (max_steps, done))
        return ToolLoopResult(store, reply, steps, store.ops, True, rejected,
                              hit_step_limit=True)

    run.catalog = catalog           # type: ignore[attr-defined]
    run.tools = tools               # type: ignore[attr-defined]
    run.agent_name = agent_name     # type: ignore[attr-defined]
    return run


def _parse(raw: str) -> dict[str, Any] | None:
    """JSON armor: the model is asked for one JSON object per turn, but wraps
    it in prose or a fenced block often enough to need unwrapping."""
    from domain.solution.agents.shared import _parse_llm_json
    try:
        parsed = _parse_llm_json(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and parsed:
        return parsed
    return None


# ── specialist helpers ──────────────────────────────────────────────────────
#
# Shared by the greenfield and brownfield agents so the two cannot drift in
# how they talk to the model or shape their result.

#: A tool-loop drawing below this validate_drawing score (mostly orphans or
#: duplicate tags) is treated as a failed run and replaced by the deterministic
#: build rather than shipped.
MIN_ACCEPTED_SCORE = 70


def solution_llm_complete(prompt: str, *, user_id: int | None,
                          agent_type: str) -> str:
    """One call to the solution-tier model, tagged for usage tracking the same
    way the previous single-shot chains were."""
    from common.ai.llm import SOLUTION_LLM_PROVIDER, with_json_mode
    from domain.solution.agents.shared import llm_pro

    llm = with_json_mode(llm_pro, SOLUTION_LLM_PROVIDER)
    resp = llm.invoke(prompt, config={"metadata": {"user_id": user_id,
                                                   "agent_type": agent_type}})
    content = getattr(resp, "content", resp)
    if isinstance(content, list):          # multi-part message content
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p)
                          for p in content)
    return str(content or "")


def components_json(instruments: list[dict] | None,
                    accessories: list[dict] | None) -> str:
    return json.dumps({
        "instruments": [
            {"category": i.get("category"),
             "product_name": i.get("product_name"),
             "quantity": i.get("quantity", 1),
             "specifications": i.get("specifications", {}),
             "standards": i.get("standards", [])}
            for i in instruments or []],
        "accessories": [
            {"category": a.get("category"),
             "accessory_name": a.get("accessory_name"),
             "parent_instrument_category": a.get("parent_instrument_category")}
            for a in accessories or []],
    }, indent=2, default=str)


def designed_json(designed_solution: dict | None) -> str:
    d = designed_solution or {}
    return json.dumps({k: d.get(k) for k in (
        "project_objective", "design_overview", "component_roles",
        "optimizations", "design_considerations", "assumptions")
        if d.get(k)}, indent=2, default=str) or "{}"


def accept(result: ToolLoopResult) -> tuple[bool, str]:
    """Whether a tool-loop run produced a drawing worth shipping."""
    if result.hit_step_limit:
        return False, "step limit reached before the design was complete"
    if not result.store.nodes:
        return False, "the model built nothing"
    score = result.store.validate_drawing()["score"]
    if score < MIN_ACCEPTED_SCORE:
        return False, "drawing quality score %d below %d" % (score, MIN_ACCEPTED_SCORE)
    return True, ""


def graph_result(store: PIDGraphStore, *, reply: str, path: str,
                 notes: list[str] | None = None,
                 pending_action: dict | None = None) -> dict[str, Any]:
    """The graph dict build_pid_from_solution consumes, plus how it was made.

    generation_path is "tool_loop" or "fallback"; validation and spec_status
    counts let the UI show how much of the drawing is backed by real data."""
    from domain.solution.services import asset_specs as SPECS

    graph = store.to_graph(summary=reply or store.graph_summary())
    graph["generation_path"] = path
    graph["validation"] = store.validate_drawing()
    graph["validation"]["loops"] = [
        {"loop_id": l["loop_id"], "status": l["status"]} for l in store.get_loops()]
    graph["spec_status_counts"] = SPECS.summarize(store.nodes)
    if notes:
        graph["notes"] = notes
    if pending_action:
        graph["pending_action"] = pending_action
    return graph


def confirm_delete_action(deferred: list[dict]) -> dict | None:
    """The pending_action a turn leaves when it queued deletions: what the
    engineer is asked, and the exact tool calls POST /api/pid/confirm replays."""
    if not deferred:
        return None
    targets = sorted({t for d in deferred for t in d.get("tags") or []})
    return {
        "kind": "confirm_delete",
        "question": "Remove %s from the P&ID? Every connection to %s is removed "
                    "too." % (", ".join(targets) or "the selected items",
                              "it" if len(targets) == 1 else "them"),
        "targets": targets,
        "actions": [{"tool": d["tool"], "method": d["method"], "args": d["args"]}
                    for d in deferred],
    }
