"""Smoke tests for the agentic pipeline scaffold (agents/).

Run without CV dependencies (ultralytics/torch) and without API keys:
the detection tool boundary is monkeypatched, and controllers run in
rules-only mode when no provider is configured.
"""
import json
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.extraction.state import ExtractionState, can_retry, retries_used  # noqa: E402
from agents.toolkit import box_iou, parse_controller_json, run_controller  # noqa: E402
from agents.extraction.agents import symbol_agent, line_agent  # noqa: E402
from agents.extraction.workflows.extraction_workflow import build_supervisor  # noqa: E402


# ── toolkit ──────────────────────────────────────────────────────────────────

def test_box_iou_disjoint_and_identical():
    assert box_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert box_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)


def test_parse_controller_json_plain_and_fenced():
    assert parse_controller_json('{"action": "proceed"}') == {"action": "proceed"}
    fenced = 'noise\n```json\n{"action": "retry_lower_conf"}\n```\nmore'
    parsed = parse_controller_json(fenced)
    assert parsed and parsed["action"] == "retry_lower_conf"


def test_run_controller_rules_only():
    decision, kind, usage = run_controller(
        "unused {x}", {"x": 1},
        fallback=lambda m: {"verdict": "ok", "action": "proceed", "reason": "r"},
        allowed_actions={"proceed"}, stage="t", use_llm=False)
    assert decision["action"] == "proceed"
    assert kind == "rules" and usage is None


def test_run_controller_falls_back_when_llm_unavailable(monkeypatch):
    # Force the provider import to fail — decision must fall back to rules.
    import builtins
    real_import = builtins.__import__

    def broken(name, *a, **k):
        if name.startswith("adapters"):
            raise ImportError("no provider in test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", broken)
    decision, kind, _ = run_controller(
        "p {x}", {"x": 1},
        fallback=lambda m: {"verdict": "ok", "action": "proceed", "reason": "r"},
        allowed_actions={"proceed"}, stage="t", use_llm=True)
    assert decision["action"] == "proceed"
    assert kind == "llm_fallback_rules"


# ── state helpers ────────────────────────────────────────────────────────────

def test_retry_budget():
    s: ExtractionState = {"retry_counts": {"symbol_detection": 2}}
    assert retries_used(s, "symbol_detection") == 2
    assert not can_retry(s, "symbol_detection")
    assert can_retry(s, "other_stage")


# ── symbol agent QC rules ────────────────────────────────────────────────────

def _m(**over):
    base = {"symbols_found": 40, "page_ink_density": 0.05,
            "low_conf_fraction": 0.1, "cross_class_overlap_pairs": 0,
            "reprompt_used": False, "conf_used": 0.35, "retries_used": 0}
    base.update(over)
    return base


def test_symbol_qc_rules_nominal():
    d = symbol_agent._rule_fallback(_m())
    assert d["action"] == "proceed" and d["verdict"] == "ok"


def test_symbol_qc_rules_empty_page_retries_lower_conf():
    d = symbol_agent._rule_fallback(_m(symbols_found=0))
    assert d["action"] == "retry_lower_conf"


def test_symbol_qc_rules_low_conf_triggers_reprompt():
    d = symbol_agent._rule_fallback(_m(low_conf_fraction=0.7))
    assert d["action"] == "retry_reprompt"


def test_symbol_qc_rules_low_conf_does_not_reprompt_twice():
    d = symbol_agent._rule_fallback(_m(low_conf_fraction=0.7, reprompt_used=True))
    assert d["action"] == "proceed"


def test_symbol_qc_rules_budget_exhausted_proceeds():
    d = symbol_agent._rule_fallback(_m(symbols_found=0, retries_used=2))
    assert d["action"] == "proceed"


def test_cross_class_dedup_keeps_higher_score():
    dets = [
        {"type": "tank", "bbox": [0, 0, 100, 100], "score": 0.9},
        {"type": "vessel", "bbox": [5, 5, 100, 100], "score": 0.5},
        {"type": "pump", "bbox": [500, 500, 550, 550], "score": 0.8},
    ]
    out = symbol_agent._dedup_cross_class(dets)
    types = {d["type"] for d in out}
    assert types == {"tank", "pump"}


# ── line agent QC rules ──────────────────────────────────────────────────────

def _lm(**over):
    base = {"retries_used": 0, "segments_per_symbol": 3.0,
            "page_ink_density": 0.05, "reprompt_used": False,
            "leader_line_candidates": 0, "suspected_fused_parallels": 0}
    base.update(over)
    return base


def test_line_qc_rules_nominal_still_classifies_styles():
    d = line_agent._rule_fallback(_lm())
    assert d["actions"] == ["classify_styles"]
    assert d["verdict"] == "ok"


def test_line_qc_rules_sparse_lines_triggers_reprompt():
    d = line_agent._rule_fallback(_lm(segments_per_symbol=0.2))
    assert d["actions"] == ["retry_reprompt"]


def test_line_qc_rules_sparse_lines_does_not_reprompt_twice():
    d = line_agent._rule_fallback(_lm(segments_per_symbol=0.2, reprompt_used=True))
    assert "retry_reprompt" not in d["actions"]
    assert "classify_styles" in d["actions"]


def test_line_qc_rules_combines_refinements():
    d = line_agent._rule_fallback(
        _lm(leader_line_candidates=15, suspected_fused_parallels=5))
    assert set(d["actions"]) == {"drop_leaders", "unfuse_parallels", "classify_styles"}
    assert d["verdict"] == "suspect"


# ── end-to-end supervisor run (detection stubbed) ────────────────────────────

def _minimal_png() -> bytes:
    """Valid 1x1 grayscale PNG built from primitives (no Pillow needed)."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)   # 1x1, 8-bit gray
    idat = zlib.compress(b"\x00\xff")                      # filter 0, white px
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


@pytest.fixture()
def fake_hub(tmp_path):
    hub = tmp_path / "hub"
    (hub / "projects" / "tproj").mkdir(parents=True)
    src = hub / "projects" / "tproj" / "drawing.png"
    src.write_bytes(_minimal_png())
    return hub, src


def _patch_pipeline(monkeypatch):
    """Stub every tool boundary so the full graph runs without CV deps
    or API keys. Returns the canned data for assertions."""
    from agents.extraction.agents import (harness_agent, line_agent,
                                    relationship_agent, text_agent)
    import agents.extraction.workflows.extraction_workflow as sup

    symbols = [
        {"type": "pump", "bbox": [10, 10, 50, 50], "score": 0.9},
        {"type": "vessel", "bbox": [100, 10, 200, 90], "score": 0.8},
    ]
    monkeypatch.setattr(symbol_agent, "_call_detection", lambda *a, **k: {
        "detections": symbols, "image_size": {"width": 640, "height": 480}})
    monkeypatch.setattr(text_agent, "_call_ocr", lambda *a, **k: {
        "texts": [{"text": "P-101", "bbox": [12, 55, 48, 65], "score": 0.9,
                   "nearest_symbol": "pump"},
                  {"text": "V-201", "bbox": [110, 95, 150, 105], "score": 0.9,
                   "nearest_symbol": "vessel"}]})
    monkeypatch.setattr(line_agent, "_call_lines", lambda *a, **k: {
        "long_lines": [[50, 30, 100, 30]], "connected_lines": [],
        "signal_lines": []})
    geo = {"edges": [{"from": "n1", "to": "n2", "line_indices": [0],
                      "kind": "process"}],
           "junctions": [], "open_stubs": [], "ambiguous_crossings": [],
           "unmatched_symbols": [], "lines": []}
    monkeypatch.setattr(relationship_agent, "_call_geometry",
                        lambda *a, **k: geo)

    def fake_llm_a(state):
        return {"llm_a_result": {"nodes": [
            {"id": "n1", "kind": "pump", "label": "P-101",
             "bbox": [10, 10, 50, 50]},
            {"id": "n2", "kind": "vessel", "label": "V-201",
             "bbox": [100, 10, 200, 90]}]}}

    def fake_llm_b(state):
        return {"llm_b_result": {
            "edges": (state.get("candidate_graph") or {}).get("edges", []),
            "junctions": []}}

    monkeypatch.setattr(sup, "llm_a_node", fake_llm_a)
    monkeypatch.setattr(sup, "llm_b_node", fake_llm_b)
    return symbols


def test_supervisor_end_to_end(fake_hub, monkeypatch, capsys):
    hub, src = fake_hub
    _patch_pipeline(monkeypatch)

    graph = build_supervisor(checkpointer=None)
    final = graph.invoke({
        "pid": "tproj", "hub": str(hub), "source_path": str(src),
        "llm_only": False, "provider": "",
        "retry_counts": {}, "retry_params": {},
    })

    assert final["status"] == "complete"
    # symbol_detections/text_detections/etc. are now internal to the
    # per-page page_pipeline subgraph (E1: multi-page) and correctly do
    # NOT leak into top-level state — only the namespaced, merged result
    # does. This is the intended encapsulation, not a regression: verify
    # via the merged output instead.
    assert len(final["verified_nodes"]) == 2
    assert len(final["verified_edges"]) == 1
    # Id namespacing now follows the CLASSIC pipeline's convention rather than
    # the agentic engine's old 0-based "p0_" prefix, so the two engines produce
    # interchangeable output (see tests/test_agentic_source_identity.py). For a
    # single-page source with no source_id -- exactly this case -- the classic
    # prefix is empty, so ids stay bare. Asserted against the classic helper so
    # the two cannot drift apart again.
    from extraction_cli.commands import _id_prefix
    expected_prefix = _id_prefix(None, 1, 1)
    assert expected_prefix == ""
    assert final["verified_nodes"][0]["id"] == "n1"
    qc_stages = {r["stage"] for r in final["qc_reports"]}
    assert {"symbol_detection", "text_detection", "line_detection",
            "cv_consolidation", "relationship_building",
            "inference_passes"} <= qc_stages
    assert all(r["controller"] in ("rules", "llm", "llm_fallback_rules")
               for r in final["qc_reports"])

    # NDJSON contract: progress events are JSON lines with a stage key.
    # Non-JSON noise (e.g. import-time warnings) is tolerated, exactly as
    # the desktop consumer parseEntry() tolerates it by returning null.
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    stages = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        assert "stage" in obj
        stages.append(obj["stage"])
    assert "init" in stages and "done" in stages   # "done", not "finish" —
    # matches the legacy CLI's terminal-success stage name (E2 fix)
    for st in ["symbol_detection", "text_detection", "line_detection",
               "cv_consolidation", "relationship_building", "merge",
               "inference_passes"]:
        assert st in stages, f"missing stage {st}"


def test_supervisor_bounded_retry(fake_hub, monkeypatch):
    """Zero detections on a non-blank page -> retry_lower_conf fires, but
    the loop is bounded and the run still completes."""
    hub, src = fake_hub
    _patch_pipeline(monkeypatch)
    calls = {"n": 0}

    def empty_detection(*a, **k):
        calls["n"] += 1
        return {"detections": [], "image_size": {}}

    monkeypatch.setattr(symbol_agent, "_call_detection", empty_detection)
    # Force ink density above the blank-page floor so the retry rule arms.
    monkeypatch.setattr(symbol_agent, "_page_ink_density", lambda b: 0.05)

    graph = build_supervisor(checkpointer=None)
    final = graph.invoke({
        "pid": "tproj", "hub": str(hub), "source_path": str(src),
        "llm_only": False, "provider": "",
        "retry_counts": {}, "retry_params": {},
    })

    assert final["status"] == "complete"          # never wedges
    assert 2 <= calls["n"] <= 3                    # initial + bounded retries
    # retry_counts is scoped inside the per-page page_pipeline subgraph
    # (E1: correctly does not leak across pages in a multi-page run) —
    # the bounded-retry proof lives in qc_reports instead, which DOES
    # propagate to top-level state via _run_one_page's explicit forward.
    retry_reports = [r for r in final["qc_reports"]
                     if r["stage"] == "symbol_detection"
                     and r["action_taken"] == "retry_lower_conf"]
    assert len(retry_reports) <= 2
    last = [r for r in final["qc_reports"]
            if r["stage"] == "symbol_detection"][-1]
    assert last["action_taken"] == "proceed"       # forced proceed at budget


# ── dedicated prompt files ───────────────────────────────────────────────────

def test_prompt_files_load_and_fill():
    from agents.prompts import fill_prompt, load_prompt
    from agents.extraction.prompts import catalog as c

    for name in ["qc_preamble", "supervisor_route", "symbol_qc", "text_qc",
                 "line_qc", "cv_consolidation", "geometry_qc",
                 "deletion_justify", "proposal_conflict",
                 "unreadable_crops_addendum", "symbol_detect",
                 "text_read", "text_read_tile", "line_trace", "line_verify"]:
        assert load_prompt(name).strip(), f"{name}.md empty"

    # QC prompts are composed with the shared preamble.
    assert c.SYMBOL_QC_V1.startswith(c.AGENT_PREAMBLE)
    # symbol_detect/text_read/text_read_tile/line_trace/line_verify
    # accompany vision calls, not metrics decisions — NOT preamble-wrapped
    # like the QC prompts above.
    assert not c.SYMBOL_DETECT_V1.startswith(c.AGENT_PREAMBLE)
    assert "{retry_note}" in c.SYMBOL_DETECT_V1
    assert not c.TEXT_READ_V1.startswith(c.AGENT_PREAMBLE)
    assert "{symbol_type}" in c.TEXT_READ_V1 and "{tag_required_note}" in c.TEXT_READ_V1
    assert not c.TEXT_READ_TILE_V1.startswith(c.AGENT_PREAMBLE)
    assert "{tile_w}" in c.TEXT_READ_TILE_V1 and "{tile_h}" in c.TEXT_READ_TILE_V1
    assert not c.LINE_TRACE_V1.startswith(c.AGENT_PREAMBLE)
    assert "{retry_note}" in c.LINE_TRACE_V1 and "{symbol_list}" in c.LINE_TRACE_V1
    assert not c.LINE_VERIFY_V1.startswith(c.AGENT_PREAMBLE)
    assert "{candidate_runs}" in c.LINE_VERIFY_V1

    # fill_prompt replaces known keys, leaves JSON braces intact.
    filled = fill_prompt(c.SYMBOL_QC_V1, {
        "symbols_found": 12, "page_ink_density": 0.05,
        "low_conf_fraction": 0.1, "cross_class_overlap_pairs": 2,
        "reprompt_used": False, "conf_used": 0.35, "retries_used": 0})
    assert "{symbols_found}" not in filled
    assert "12" in filled
    assert '"verdict": "ok" | "suspect"' in filled   # schema braces intact


# ── schemas (R2) ─────────────────────────────────────────────────────────────

def test_qc_decision_schema_wall():
    from agents.extraction.schemas import QCDecision
    d = QCDecision.model_validate({"verdict": "suspect",
                                   "action": "retry_lower_conf",
                                   "reason": "x", "junk": 1}).model_dump()
    assert d["action"] == "retry_lower_conf" and "junk" not in d
    import pytest as _pt
    with _pt.raises(Exception):
        QCDecision.model_validate({"action": ["not", "a", "string"]})


def test_llm_result_ensure_compliant_never_raises():
    from agents.extraction.schemas import LLMAResult, LLMBResult
    assert LLMAResult.ensure_compliant(None)["nodes"] == []
    assert LLMAResult.ensure_compliant({"nodes": "garbage"})["nodes"] == []
    ok = LLMBResult.ensure_compliant({"edges": [{"from": "a", "to": "b"}],
                                      "junctions": "bad"})
    assert ok["edges"] == [{"from": "a", "to": "b"}]
    assert ok["junctions"] == []


def test_describe_toolcall_schema():
    from agents.describe.schemas import FinalReply, ToolCall
    t = ToolCall.ensure_compliant({"tool": "add_nodes", "args": {"n": 1}})
    assert t["tool"] == "add_nodes" and t["args"] == {"n": 1}
    r = FinalReply.ensure_compliant({"reply": "done", "extra": True})
    assert r["reply"] == "done" and "extra" not in r


# ── retry decorator (R3) ─────────────────────────────────────────────────────

def test_retryable_node_succeeds_after_retry(capsys):
    from agents.retry import retryable_node
    calls = {"n": 0}

    @retryable_node(max_attempts=3, label="flaky")
    def node(state):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    assert node({}) == {"ok": True}
    assert calls["n"] == 3
    out = capsys.readouterr().out
    assert '"status": "retry"' in out


def test_retryable_node_exhaustion_hook(capsys):
    from agents.retry import retryable_node
    hook_seen = {}

    def hook(state, err):
        hook_seen["err"] = str(err)
        return {"status": "degraded"}

    @retryable_node(max_attempts=2, label="doomed", on_exhausted=hook)
    def node(state):
        raise RuntimeError("permanent")

    assert node({}) == {"status": "degraded"}
    assert hook_seen["err"] == "permanent"
    assert '"status": "exhausted"' in capsys.readouterr().out


def test_retryable_node_reraises_fatal():
    from agents.retry import retryable_node
    from agents.streaming import FatalAgentError

    @retryable_node(max_attempts=3, label="fatal",
                    on_exhausted=lambda s, e: {"swallowed": True})
    def node(state):
        raise FatalAgentError("stop now")

    with pytest.raises(FatalAgentError):
        node({})


# ── orchestrator router + health + progress (R4/R5) ──────────────────────────

@pytest.mark.parametrize("message,has_file,expected", [
    ("anything at all", True, "extraction"),
    ("extract this drawing please", False, "extraction"),
    ("add a pump P-101 next to V-1", False, "describe"),
    ("what is the status of the agents?", False, "health"),
    ("hello there", False, "describe"),
])
def test_app_router_rules(message, has_file, expected):
    from agents.orchestrator.agents.router_agent import route_request
    target, _reason, controller = route_request(message, has_file=has_file,
                                                use_llm=False)
    assert target == expected
    assert controller == "rules"


def test_health_reports_never_raise():
    from agents.orchestrator.workflows.health import check_app_health
    report = check_app_health()
    assert report["status"] in ("healthy", "degraded")
    workflows = {r["workflow"] for r in report["workflows"]}
    assert workflows == {"extraction", "describe"}
    ext = next(r for r in report["workflows"]
               if r["workflow"] == "extraction")
    assert ext["checks"]["graph_compiles"] is True
    assert ext["checks"]["prompts"] is True


def test_app_workflow_routes_health():
    from agents.orchestrator.workflows.app_workflow import run_app_request
    out = run_app_request({"message": "are the agents healthy?"},
                          use_llm_router=False)
    assert out["workflow"] == "health"
    assert out["result"]["status"] in ("healthy", "degraded")


def test_stage_events_carry_progress(capsys):
    from agents.streaming import stage
    stage("symbol_detection", "running")
    stage("done", "complete")
    lines = [json.loads(ln) for ln in
             capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines[0]["progress"] == 20
    assert lines[1]["progress"] == 100
