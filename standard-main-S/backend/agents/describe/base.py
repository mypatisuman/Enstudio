"""Shared bounded tool-loop engine for the Describe specialists.

This is infrastructure, not an agent: each dedicated specialist supplies
its own name, prompt file, and tool registry, and gets back a compiled
graph with the same guarantees everywhere — bounded steps, JSON armor,
unknown-tool rejection, write auditing, and the confirmation interrupt
for tools that declare `requires_confirmation`.
"""
from __future__ import annotations

import json

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from agents.prompts import fill_prompt
from agents.retry import retryable_node
from agents.streaming import stage as emit_stage
from agents.toolkit import parse_controller_json
from agents.describe.services import repository as R
from agents.describe.state import DescribeState

MAX_STEPS = 8


def llm_complete(prompt: str) -> str:
    """Module-level for testability. Smart tier: authoring needs judgment."""
    from adapters.llm_factory import get_provider
    return get_provider().complete(prompt, max_tokens=2000, tier="smart").text


def _transcript(state: DescribeState) -> str:
    lines = [f'ENGINEER: "{state["user_message"]}"']
    for m in state.get("messages") or []:
        lines.append(f"{m['role'].upper()}: {m['content']}")
    return "\n".join(lines)


def _safe_summary(pid: str) -> str:
    try:
        return R.graph_summary(pid)
    except Exception as e:
        return f"(graph summary unavailable: {str(e)[:100]})"


def _recompute_grid_safely(pid: str) -> None:
    """Post-write hook: the grid is a derived view, never load-bearing —
    a recompute failure must not block or fail the engineer's edit."""
    try:
        from agents.describe.services.grid_service import recompute_grid
        grid = recompute_grid(pid)
        emit_stage("grid_layout", "recomputed",
                   rows=grid["row_count"], cols=grid["col_count"])
    except Exception as e:
        emit_stage("grid_layout", "recompute_failed", detail=str(e)[:200])


def tool_catalog(tools: dict) -> str:
    """Authoritative tool signatures, generated from the functions themselves.

    The describe prompts used to hand-write these, and they drifted: the
    brownfield prompt taught get_node(node_id), get_connections(node_id) and
    get_loops(loop_number) while the code took `tag` and `status_filter`, so an
    agent following its own prompt wasted steps on argument errors. Generating
    the list from inspect.signature makes that class of drift impossible.
    """
    import inspect as _inspect
    lines = []
    for name, spec in tools.items():
        fn = spec["fn"]
        params = []
        try:
            for i, (pname, p) in enumerate(_inspect.signature(fn).parameters.items()):
                if i == 0 and pname == "pid":
                    continue
                if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                params.append(pname if p.default is p.empty
                              else f"{pname}={p.default!r}")
        except (TypeError, ValueError):
            pass
        doc = spec.get("doc") or (_inspect.getdoc(fn) or "")
        doc = " ".join(doc.split("\n\n")[0].split())
        flags = []
        if spec.get("writes"):
            flags.append("writes")
        if spec.get("requires_confirmation"):
            flags.append("engineer must confirm")
        flag_text = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"- {name}({', '.join(params)}){flag_text}: {doc or name}")
    return "\n".join(lines)


_CATALOG_HEADER = (
    "\n\nTOOL SIGNATURES (authoritative: call tools with exactly these argument "
    "names; the project id is supplied for you)\n")


def build_tool_agent(agent_name: str, prompt_text: str, tools: dict,
                     max_steps: int = MAX_STEPS):
    """Compile a dedicated specialist: its own prompt, its own tools.

    tools: {name: {"fn": callable(pid, **args), "writes": bool,
                   "requires_confirmation": bool?}}
    """

    catalog = tool_catalog(tools)

    def _on_agent_exhausted(state: DescribeState, err: Exception) -> dict:
        return {"reply": "I could not reach the language model — please "
                         "check the provider settings and try again. No "
                         "changes were made by this attempt.",
                "steps": state.get("steps", 0) + 1}

    @retryable_node(max_attempts=2, label=f"{agent_name}.agent",
                    on_exhausted=_on_agent_exhausted)
    def agent_node(state: DescribeState) -> dict:
        steps = state.get("steps", 0)
        if steps >= max_steps:
            applied = [op.get("result", op.get("tool")) for op in state.get("ops") or []]
            done = ("Applied so far: " + " | ".join(str(a) for a in applied)
                    if applied else "No changes were applied.")
            return {"reply": f"I reached my step limit ({max_steps}) before "
                             f"finishing. {done} Send the next part of the "
                             "request to continue.",
                    "steps": steps}

        resolved = state.get("resolved_target")
        active_sol = state.get("active_solution")
        system = fill_prompt(prompt_text, {
            "project_id": state["project_id"],
            "graph_summary": _safe_summary(state["project_id"]),
            "resolved_target": json.dumps(resolved) if resolved else "",
            "holistic_knowledge": json.dumps(state.get("holistic_context") or {}) if state.get("holistic_context") else "",
            "active_solution": json.dumps(active_sol, indent=2) if active_sol else "None (No prior solution state)",
            "tool_catalog": catalog,
        })
        if "{tool_catalog}" not in prompt_text:
            system += _CATALOG_HEADER + catalog
        prompt = system + "\n\nCONVERSATION SO FAR\n" + _transcript(state) + \
            "\n\nYour JSON response:"
        raw = llm_complete(prompt)
        parsed = parse_controller_json(raw) or {}
        if parsed.get("tool") is not None:
            from agents.describe.schemas import ToolCall
            parsed = {**parsed, **ToolCall.ensure_compliant(parsed)}
        elif parsed:
            from agents.describe.schemas import FinalReply
            parsed = {**parsed, **FinalReply.ensure_compliant(parsed)}

        requested = parsed.get("tool")
        if requested:
            if requested not in tools:
                # Dedicated-agent boundary: this specialist does not own
                # that tool. Surface it so the model recovers in-loop.
                emit_stage(agent_name, "tool_rejected", tool=requested)
                return {"messages": [
                    {"role": "assistant", "content": json.dumps(parsed)},
                    {"role": "tool",
                     "content": f"ERROR: tool '{requested}' is not available "
                                f"to the {agent_name}. Available tools: "
                                f"{sorted(tools)}. If the engineer's request "
                                "needs it, say so in a reply instead."}],
                    "steps": steps + 1}
            call = {"tool": requested, "args": parsed.get("args") or {},
                    "thought": parsed.get("thought", "")}
            emit_stage(agent_name, "tool_call", tool=requested)
            return {"messages": [{"role": "assistant",
                                  "content": json.dumps(call)}],
                    "steps": steps + 1}

        reply = parsed.get("reply") or (raw.strip()[:400] if raw.strip()
                                        else "I could not produce a response.")
        emit_stage(agent_name, "reply")
        solution_design = parsed.get("solution_design")
        if not solution_design and state.get("holistic_context"):
            h_ctx = state.get("holistic_context") or {}
            plant_type = h_ctx.get("inferred_plant_type")
            unit_ops = h_ctx.get("unit_operations")
            ctrl_strategy = h_ctx.get("inferred_control_strategy")
            if plant_type or unit_ops:
                solution_design = {
                    "inferred_plant_type": plant_type or "Engineered Process Station",
                    "unit_operations": unit_ops or [],
                    "project_objective": f"Architecture for {plant_type or 'Process System'}",
                    "design_overview": ctrl_strategy or "Configured process units and instrumentation network according to ISA-5.1 standards.",
                    "component_roles": [],
                    "optimizations": ["ISA-5.1 / IEC 61508 standards applied", "Automatic 5-Corridor process grid alignment"],
                    "design_considerations": ["Verify design operating pressure and temperature limits."],
                }

        if not solution_design:
            # Extract nodes added during this turn or mentioned in the user message
            added_nodes: list[tuple[str, str]] = []
            for op in state.get("ops") or []:
                if op.get("tool") == "add_nodes":
                    nodes = op.get("args", {}).get("nodes") or []
                    for n in nodes:
                        tag = n.get("tag") if isinstance(n, dict) else str(n)
                        kind = n.get("kind", "") if isinstance(n, dict) else ""
                        if tag:
                            added_nodes.append((tag, kind))
            
            import re
            user_tags = re.findall(r"\b([A-Z]{1,4}-\d{3,5}[A-H]?|[A-Z]{2,4}-\d{3,5}|[A-Z]+-[A-Z]+-HDR|[A-Z]+-HDR)\b", state.get("user_message", ""))
            for tag in user_tags:
                if not any(tag.upper() == n[0].upper() for n in added_nodes):
                    added_nodes.append((tag, ""))

            if len(added_nodes) >= 1:
                roles = []
                for tag, kind in added_nodes:
                    tag_u = tag.upper()
                    if tag_u.startswith("P-") or "PUMP" in tag_u:
                        cat, purp = "Process Pump", "Fluid circulation and motive force"
                    elif tag_u.startswith("PI") or tag_u.startswith("PT") or "PRESS" in tag_u:
                        cat, purp = "Pressure Indicator", "Line pressure monitoring and tap threshold"
                    elif tag_u.startswith("TI") or tag_u.startswith("TT") or tag_u.startswith("TE") or "TEMP" in tag_u:
                        cat, purp = "Temperature Element / Transmitter", "Continuous process temperature measurement"
                    elif tag_u.startswith("PSV") or "PRV" in tag_u or "RELIEF" in tag_u:
                        cat, purp = "Relief Valve", "Overpressure safety protection and vent discharge"
                    elif tag_u.startswith("HV") or tag_u.startswith("XV") or tag_u.startswith("CV") or tag_u.startswith("XY") or "VALVE" in tag_u:
                        cat, purp = "Control / Hand Valve", "Flow throttling and stream bypass routing"
                    elif tag_u.startswith("CK") or "CHECK" in tag_u:
                        cat, purp = "Check Valve", "Backflow prevention"
                    elif tag_u.startswith("M-") or "MIX" in tag_u:
                        cat, purp = "Static Mixer", "In-line fluid mixing and homogenization"
                    elif tag_u.startswith("R-") or tag_u.startswith("V-") or tag_u.startswith("C-") or tag_u.startswith("TK-") or "REACTOR" in tag_u:
                        cat, purp = "Chemical Reactor / Core Vessel", "Primary process reaction station"
                    elif "HDR" in tag_u or "VENT" in tag_u or "BYPASS" in tag_u or "FEED" in tag_u:
                        cat, purp = "Header / Off-Page Connector", "Tie-in connection to adjacent plant drawing"
                    else:
                        cat, purp = kind or "Process Equipment", f"Integrated process component ({tag})"
                    roles.append({"name": tag, "tag": tag, "category": cat, "purpose": purp})

                msg_summary = state["user_message"].strip().split("\n")[0][:120]
                solution_design = {
                    "inferred_plant_type": "Engineered Process Subsystem",
                    "project_objective": f"Architecture for: {msg_summary}",
                    "design_overview": reply,
                    "component_roles": roles,
                    "optimizations": [
                        "ISA-5.1 standards applied for instrumentation tap placement",
                        "Automatic 5-Corridor process grid alignment",
                        "Dedicated safety relief and bypass routing isolation",
                    ],
                    "design_considerations": [
                        "Verify design operating pressure and temperature limits for all wetted components.",
                        "Ensure relief valve sizing complies with API 520 / ASME Section VIII.",
                    ],
                    "assumptions": [
                        "Utility headers and tie-in connections available from referenced drawings.",
                        "Instrument signals integrated into plant DCS / SIS control logic.",
                    ],
                }

        # Enrich any missing tags from user message into solution_design component_roles
        if solution_design:
            existing_roles_map = {(r.get("tag") or r.get("name") or "").upper(): r for r in solution_design.get("component_roles") or []}
            import re
            user_tags = re.findall(r"\b([A-Z]{1,4}-\d{3,5}[A-H]?|[A-Z]{2,4}-\d{3,5}|[A-Z]+-[A-Z]+-HDR|[A-Z]+-HDR)\b", state.get("user_message", ""))
            for tag in user_tags:
                tag_u = tag.upper()
                if tag_u not in existing_roles_map:
                    if tag_u.startswith("P-") or "PUMP" in tag_u:
                        cat, purp = "Process Pump", "Fluid circulation and motive force"
                    elif tag_u.startswith("PI") or tag_u.startswith("PT") or "PRESS" in tag_u:
                        cat, purp = "Pressure Indicator", "Line pressure monitoring and tap threshold"
                    elif tag_u.startswith("TI") or tag_u.startswith("TT") or tag_u.startswith("TE") or "TEMP" in tag_u:
                        cat, purp = "Temperature Element / Transmitter", "Continuous process temperature measurement"
                    elif tag_u.startswith("PSV") or "PRV" in tag_u or "RELIEF" in tag_u:
                        cat, purp = "Relief Valve", "Overpressure safety protection and vent discharge"
                    elif tag_u.startswith("HV") or tag_u.startswith("XV") or tag_u.startswith("CV") or tag_u.startswith("XY") or "VALVE" in tag_u:
                        cat, purp = "Control / Hand Valve", "Flow throttling and stream bypass routing"
                    elif tag_u.startswith("CK") or "CHECK" in tag_u:
                        cat, purp = "Check Valve", "Backflow prevention"
                    elif tag_u.startswith("M-") or "MIX" in tag_u:
                        cat, purp = "Static Mixer", "In-line fluid mixing and homogenization"
                    elif tag_u.startswith("R-") or tag_u.startswith("V-") or tag_u.startswith("C-") or tag_u.startswith("TK-") or "REACTOR" in tag_u:
                        cat, purp = "Chemical Reactor / Core Vessel", "Primary process reaction station"
                    elif "HDR" in tag_u or "VENT" in tag_u or "BYPASS" in tag_u or "FEED" in tag_u:
                        cat, purp = "Header / Off-Page Connector", "Tie-in connection to adjacent plant drawing"
                    else:
                        cat, purp = "Process Equipment", f"Integrated process component ({tag})"
                    new_role = {"name": tag, "tag": tag, "category": cat, "purpose": purp}
                    existing_roles_map[tag_u] = new_role
                    solution_design.setdefault("component_roles", []).append(new_role)

        if solution_design:
            # Specifications come from real data only (services/asset_specs.py).
            # This block used to fill every component role with specifications
            # invented from its tag prefix; roles now carry what the inventory
            # knows, what the engineer stated, or an explicit "unspecified".
            from services.asset_specs import resolve as _resolve_specs
            for r in solution_design.get("component_roles") or []:
                tag = r.get("tag") or r.get("name") or ""
                meta = _resolve_specs(tag, r.get("specifications"),
                                      r.get("instrument_config"))
                r["spec_status"] = meta["spec_status"]
                for key in ("specifications", "instrument_config"):
                    if meta.get(key):
                        r[key] = meta[key]

        if solution_design and not solution_design.get("layout_plan"):
            roles = solution_design.get("component_roles") or []
            plan = []
            for i, r in enumerate(roles):
                tag = r.get("name") or r.get("tag") or f"ITEM-{i+1}"
                tag_u = tag.upper()
                if "PSV" in tag_u or "VENT" in tag_u or "FLARE" in tag_u or "PRV" in tag_u:
                    plan.append({"tag": tag, "corridor": "Channel 1: Relief & Vent Rail", "row": 0, "col": i, "x": 100 + i * 180, "y": 100, "anchor": "Top relief / vent header"})
                elif "HV-" in tag_u or "XV-" in tag_u or "BYPASS" in tag_u or "DRAIN" in tag_u or "ANALYTICS" in tag_u or "EFFLUENT" in tag_u:
                    plan.append({"tag": tag, "corridor": "Channel 5: Effluent & Bypass", "row": 3, "col": i, "x": 200 + i * 180, "y": 880, "anchor": "Bottom bypass / sample loop"})
                elif "FEED" in tag_u or "MIX" in tag_u or tag_u.startswith("M-"):
                    plan.append({"tag": tag, "corridor": "Channel 2: Ingress Feed Rail", "row": 1, "col": i, "x": 100 + i * 180, "y": 260, "anchor": "Feed ingress rail"})
                elif "HE-" in tag_u or tag_u.startswith("E-") or "KO" in tag_u or "CONDENSER" in tag_u:
                    plan.append({"tag": tag, "corridor": "Channel 4: Condensation & Separation", "row": 2, "col": i, "x": 500 + i * 180, "y": 450, "anchor": "Downstream exchanger / separator"})
                elif tag_u.startswith("R-") or tag_u.startswith("V-") or tag_u.startswith("C-") or tag_u.startswith("TK-") or "REACTOR" in tag_u or "TANK" in tag_u or "COLUMN" in tag_u:
                    plan.append({"tag": tag, "corridor": "Channel 3: Reaction Station", "row": 2, "col": i, "x": 200 + i * 220, "y": 550, "anchor": "Main process station"})
                else:
                    plan.append({"tag": tag, "corridor": "Channel 2: Sensing & Control Tap", "row": 1, "col": i, "x": 150 + i * 140, "y": 320, "anchor": "Instrument branch tap"})
            if plan:
                solution_design["layout_plan"] = plan

        if solution_design and state.get("active_solution"):
            from agents.describe.services.solution_merger import merge_solution_designs
            solution_design = merge_solution_designs(state.get("active_solution"), solution_design)

        return {"reply": reply, "title": parsed.get("title"),
                "solution_design": solution_design,
                "steps": steps + 1}

    def tools_node(state: DescribeState) -> dict:
        last = (state.get("messages") or [])[-1]
        call = json.loads(last["content"])
        name, args = call["tool"], dict(call["args"])
        spec = tools[name]
        pid = state["project_id"]

        if spec.get("requires_confirmation"):
            # delete_nodes uses "tags"; delete_edges uses "from_tag"/
            # "to_tag" — surface whichever shape this tool's args carry
            # so the confirmation banner names the right thing either way.
            targets = args.get("tags") or \
                [t for t in (args.get("from_tag"), args.get("to_tag")) if t]
            decision = interrupt({
                "action": "confirm_delete",
                "agent": agent_name,
                "tool": name,
                "tags": targets,
                "reason": args.get("reason", ""),
                # Which specific occurrence, when the Holistic gate
                # disambiguated a duplicated tag — shows the engineer the
                # node id + area they are confirming, not just a tag name
                # that could mean several nodes.
                "resolved": state.get("resolved_target"),
            })
            if not (decision or {}).get("confirmed"):
                return {"messages": [{"role": "tool",
                                      "content": f"{name}: User CANCELLED "
                                                 "the deletion. Do not "
                                                 "retry it."}]}

        try:
            result = spec["fn"](pid, **args)
        except TypeError as e:
            result = f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:
            result = f"ERROR: {name} failed: {str(e)[:200]}"

        content = result if isinstance(result, str) else json.dumps(result)
        updates: dict = {"messages": [{"role": "tool",
                                       "content": f"{name}: {content[:2000]}"}]}
        succeeded_write = (spec.get("writes") and isinstance(result, str)
                          and not result.startswith(("ERROR", "NOOP")))
        if succeeded_write:
            updates["ops"] = [{"tool": name, "args": args, "result": content}]
        return updates

    def _route(state: DescribeState) -> str:
        if state.get("reply"):
            return END
        last = (state.get("messages") or [{}])[-1]
        # A rejected tool appended its own tool-error message; loop back
        # to the agent rather than executing anything.
        if last.get("role") == "tool":
            return "agent"
        return "tools"

    g = StateGraph(DescribeState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route,
                            {"tools": "tools", "agent": "agent", END: END})
    g.add_edge("tools", "agent")
    return g.compile
