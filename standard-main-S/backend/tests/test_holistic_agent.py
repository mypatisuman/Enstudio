"""Tests for the Holistic Agent (disambiguation gate) — both the pure
resolve_target() decision function and its wiring into
describe_workflow.run_describe_turn(), per the build plan's §8 test list.
"""
import json
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from agents.describe import base as B  # noqa: E402
from agents.describe.agents import holistic_agent as H  # noqa: E402
from agents.describe.services import repository as R  # noqa: E402
from agents.describe.workflows import describe_workflow as W  # noqa: E402

PID = "holproj"


@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    dbmod.get_db().execute(
        "INSERT INTO projects (id, title) VALUES (?, ?)", (PID, "Test"))
    yield dbmod
    dbmod.close_db()


def _pending(pid: str, session_id: str) -> dict | None:
    return W._load_pending(pid, session_id)


def _script_llm(monkeypatch, responses: list[str]):
    it = iter(responses)
    monkeypatch.setattr(B, "llm_complete", lambda prompt: next(it))


def _no_llm(monkeypatch):
    """Force the regex fallback path deterministically for pure
    resolve_target() tests that don't care about tag extraction."""
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)


# ── §8 row 1: no pair referenced -> clear, no grid lookup ───────────────────

def test_no_target_reference_is_clear_no_grid_lookup(db, monkeypatch):
    _no_llm(monkeypatch)
    called = {"n": 0}
    monkeypatch.setattr(H, "find_adjacent_cell_pairs",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or [])
    verdict, method = H.resolve_target(PID, "add a new tank")
    assert verdict.clarity == "no_target"
    assert method == "rules"
    assert called["n"] == 0


# ── §8 row 2: single unambiguous pair -> clear + resolved_target ────────────

def test_single_unambiguous_pair_resolves(db, monkeypatch):
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    from agents.describe.services.grid_service import recompute_grid
    recompute_grid(PID)

    verdict, _ = H.resolve_target(
        PID, "add a valve between V-101 and E-101", intent="authoring")
    assert verdict.clarity == "clear"
    assert verdict.resolved_target["tag_a"] == "V-101"
    assert verdict.resolved_target["tag_b"] == "E-101"


# ── §8 row 3: THE scenario — duplicate tags -> ambiguous + candidates ───────

def test_duplicate_adjacent_pairs_is_ambiguous_with_candidates(db, monkeypatch):
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y) VALUES "
        "('n_v2', ?, 'vessel', 'V-101', 0, 0), "
        "('n_e2', ?, 'heat_exchanger', 'E-101', 0, 0)", (PID, PID))
    R._db().execute(
        "INSERT INTO edges (pid, from_id, to_id, kind) "
        "VALUES (?, 'n_v2', 'n_e2', 'stream')", (PID,))
    R._db().commit()
    from agents.describe.services.grid_service import recompute_grid
    recompute_grid(PID)

    verdict, _ = H.resolve_target(
        PID, "add a valve between V-101 and E-101", intent="authoring")
    assert verdict.clarity == "ambiguous"
    assert len(verdict.candidates) == 2
    q = H._format_clarifying_question(verdict)
    assert "V-101" in q and "E-101" in q


# ── §8 row 4: zero adjacent pairs -> ambiguous, "not connected" reason ──────

def test_tags_exist_but_never_neighbors_is_ambiguous_not_missing(db, monkeypatch):
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "P-101", "kind": "pump"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "P-101"},
                      {"from_tag": "P-101", "to_tag": "E-101"}])
    from agents.describe.services.grid_service import recompute_grid
    recompute_grid(PID)

    verdict, _ = H.resolve_target(
        PID, "add a valve between V-101 and E-101", intent="authoring")
    assert verdict.clarity == "ambiguous"
    assert "not directly connected" in verdict.reason


# ── §8 row 5: empty grid (fresh project) -> tag-duplicate check only ────────

def test_empty_grid_falls_back_to_edge_adjacency(db, monkeypatch):
    """No recompute_grid() call at all — grid_positions empty — must
    still resolve via the edge-fallback path in find_adjacent_cell_pairs,
    never crash or treat "no grid" as automatically ambiguous."""
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])

    verdict, _ = H.resolve_target(
        PID, "add a valve between V-101 and E-101", intent="authoring")
    assert verdict.clarity == "clear"
    assert verdict.resolved_target["via"] == "edge"


def test_single_tag_no_grid_is_clear_when_not_duplicated(db, monkeypatch):
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    verdict, _ = H.resolve_target(PID, "rename FT-101 to FT-102",
                                  intent="update")
    assert verdict.clarity == "clear"


# ── §8 row 6: LLM failure -> regex fallback still resolves simple cases ─────

def test_llm_failure_falls_back_to_regex(db, monkeypatch):
    """A realistic provider failure (bad key, network error) is caught
    INSIDE _extract_tags_llm (its own try/except) and reported as None,
    not raised — resolve_target then transparently uses the regex
    extractor for this call, no retry/exhaustion machinery involved."""
    monkeypatch.setattr(
        "adapters.llm_factory.get_provider",
        lambda: (_ for _ in ()).throw(RuntimeError("ANTHROPIC_API_KEY not set")))
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])

    verdict, method = H.resolve_target(
        PID, "add a valve between V-101 and E-101", intent="authoring")
    assert method == "rules"
    assert verdict.clarity == "clear"


def test_node_level_llm_outage_still_fails_open(db, monkeypatch):
    """A failure that escapes _extract_tags_llm's own guard entirely
    (e.g. a bug in the extraction path itself, not just the provider
    call) is caught one layer up by @retryable_node on resolve_target,
    which fails open to "no_target" (proceed unresolved) rather than
    blocking authoring/update outright — the UX-safeguard, not a
    safety-critical gate, distinction documented in
    _on_resolve_exhausted."""
    monkeypatch.setattr(
        H, "_extract_tags_llm",
        lambda message: (_ for _ in ()).throw(RuntimeError("unexpected bug")))
    verdict, method = H.resolve_target(
        PID, "add a valve between V-101 and E-101", intent="authoring")
    assert verdict.clarity == "no_target"    # fail-open, never blocks
    assert verdict.reason == "disambiguation unavailable"


def test_extract_tags_llm_returns_none_on_exception(monkeypatch):
    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr("adapters.llm_factory.get_provider",
                        lambda: (_ for _ in ()).throw(RuntimeError("no key")))
    assert H._extract_tags_llm("add a valve between V-101 and E-101") is None


# ── the intent-aware fix: update requests must not use pair-adjacency ───────

def test_update_two_tags_uses_single_tag_path_not_pair_adjacency(db, monkeypatch):
    """Regression test for the bug caught during integration: a rename
    surfaces two tag-shaped strings (old + new name) to the regex
    extractor, but must resolve via single-tag duplicate-check on the
    FIRST tag only — never pair-adjacency (which would wrongly report
    'not connected anywhere' since the new tag doesn't exist yet)."""
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    verdict, _ = H.resolve_target(PID, "rename FT-101 to FT-102",
                                  intent="update")
    assert verdict.clarity == "clear"   # not "ambiguous: not connected"


def test_update_duplicate_tag_is_ambiguous(db, monkeypatch):
    _no_llm(monkeypatch)
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y) VALUES "
        "('n_dup', ?, 'transmitter', 'FT-101', 0, 0)", (PID,))
    R._db().commit()

    verdict, _ = H.resolve_target(PID, "rename FT-101 to FT-102",
                                  intent="update")
    assert verdict.clarity == "ambiguous"
    assert len(verdict.candidates) == 2


# ── §8 row 7: Authoring receives resolved_target, doesn't re-search ─────────

def test_authoring_receives_resolved_target_in_prompt(db, monkeypatch):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    from agents.describe.services.grid_service import recompute_grid
    recompute_grid(PID)

    captured_prompts = []

    def fake_llm(prompt):
        captured_prompts.append(prompt)
        return json.dumps({"reply": "ok"})

    monkeypatch.setattr(B, "llm_complete", fake_llm)
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)  # regex

    graphs = {"authoring": W._BUILDERS["authoring"](InMemorySaver())}
    final = W.run_describe_turn(
        PID, "add a valve between V-101 and E-101", "s1", graphs=graphs, use_llm_router=False)

    assert final["agent"] == "authoring"
    prompt = captured_prompts[0]
    assert '"tag_a": "V-101"' in prompt
    assert '"tag_b": "E-101"' in prompt
    # H2 fix: node_a/node_b (unique ids) must ALSO be present — the
    # prompt instructs Authoring to use these, not the ambiguous tags.
    assert '"node_a"' in prompt and '"node_b"' in prompt


# ── §8 row 8: end-to-end ambiguous -> clarifying -> resolves -> writes ──────

def _make_two_duplicate_pairs(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, area, x, y) VALUES "
        "('n_v2', ?, 'vessel', 'V-101', '200', 0, 0), "
        "('n_e2', ?, 'heat_exchanger', 'E-101', '200', 0, 0)", (PID, PID))
    R._db().execute(
        "INSERT INTO edges (pid, from_id, to_id, kind) "
        "VALUES (?, 'n_v2', 'n_e2', 'stream')", (PID,))
    R._db().commit()
    from agents.describe.services.grid_service import recompute_grid
    recompute_grid(PID)


def test_ambiguous_persists_pending_and_blocks_authoring(db, monkeypatch):
    _make_two_duplicate_pairs(db)
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)

    def fail_if_called(prompt):
        raise AssertionError("Authoring must not run while ambiguous")
    monkeypatch.setattr(B, "llm_complete", fail_if_called)

    first = W.run_describe_turn(
        PID, "add a valve between V-101 and E-101", "s2", use_llm_router=False)
    assert first["agent"] == "holistic"
    assert "which did you mean" in first["reply"]

    pending = _pending(PID, "s2")
    assert pending is not None
    assert pending["intent"] == "authoring"
    assert len(pending["candidates"]) == 2
    assert pending["round"] == 1


def test_numeric_reply_resolves_pending_and_dispatches(db, monkeypatch):
    """The concrete fix for H1: 'option 2' (or a bare '2') must
    deterministically select that candidate — no LLM call, no need to
    resend the whole original sentence."""
    _make_two_duplicate_pairs(db)
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: (_ for _ in ()).throw(
                            AssertionError("must not reach LLM turn 1")))
    W.run_describe_turn(PID, "add a valve between V-101 and E-101", "s4", use_llm_router=False)
    assert _pending(PID, "s4") is not None

    captured = []
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: captured.append(p) or json.dumps({"reply": "done"}))
    final = W.run_describe_turn(PID, "option 2", "s4", use_llm_router=False)

    assert final["agent"] == "authoring"
    assert _pending(PID, "s4") is None      # cleared once resolved
    assert '"node_a"' in captured[0]


def test_detail_reply_matches_candidate_by_area(db, monkeypatch):
    """'the one in area 200' should resolve when exactly one candidate
    matches — no number needed."""
    R.add_nodes(PID, [{"tag": "FT-101", "kind": "transmitter",
                       "area": "100"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, area, x, y) VALUES "
        "('n_dup', ?, 'transmitter', 'FT-101', '200', 0, 0)", (PID,))
    R._db().commit()
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)

    W.run_describe_turn(PID, "rename FT-101 to FT-102", "s5", use_llm_router=False)
    assert _pending(PID, "s5") is not None

    captured = []
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: captured.append(p) or json.dumps({"reply": "done"}))
    final = W.run_describe_turn(PID, "the one in area 200", "s5", use_llm_router=False)

    assert final["agent"] == "update"
    assert _pending(PID, "s5") is None


def test_unrelated_new_request_drops_pending_instead_of_reusing_budget(db, monkeypatch):
    """H1's second half: an unrelated follow-up must NOT inherit the
    old request's half-spent clarification round — the pending context
    is dropped and the new message is routed fresh."""
    _make_two_duplicate_pairs(db)
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: (_ for _ in ()).throw(AssertionError("n/a")))
    W.run_describe_turn(PID, "add a valve between V-101 and E-101", "s6", use_llm_router=False)
    assert _pending(PID, "s6") is not None

    _script_llm(monkeypatch, [json.dumps({"reply": "3 pumps found"})])
    final = W.run_describe_turn(PID, "what pumps do we have?", "s6",
                               use_llm_router=False)
    assert final["agent"] == "query"
    assert _pending(PID, "s6") is None


def test_round_limit_proceeds_with_first_candidate(db, monkeypatch):
    _make_two_duplicate_pairs(db)
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: (_ for _ in ()).throw(AssertionError("n/a")))
    W.run_describe_turn(PID, "add a valve between V-101 and E-101", "s7", use_llm_router=False)
    assert _pending(PID, "s7")["round"] == 1

    # A vague, non-selecting, non-matching reply advances the round
    # without resolving — must still ask again, not silently guess.
    second = W.run_describe_turn(PID, "hmm not sure, either works I guess",
                                 "s7", use_llm_router=False)
    assert second["agent"] == "holistic"
    assert _pending(PID, "s7")["round"] == 2

    captured = []
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: captured.append(p) or json.dumps({"reply": "done"}))
    third = W.run_describe_turn(PID, "still not sure", "s7", use_llm_router=False)
    assert third["agent"] == "authoring"
    assert "I still couldn't fully disambiguate" in third["reply"]
    assert _pending(PID, "s7") is None


def test_deletion_is_gated_and_others_are_not(db, monkeypatch):
    """F0.3: deletion now runs the Holistic gate too (single-tag
    duplicate check); query/validation never do."""
    R.add_nodes(PID, [{"tag": "V-9", "kind": "vessel"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y) VALUES "
        "('n_dup9', ?, 'vessel', 'V-9', 0, 0)", (PID,))
    R._db().commit()
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)

    result = W.run_describe_turn(PID, "delete V-9", "s8", use_llm_router=False)
    assert result["agent"] == "holistic"
    assert _pending(PID, "s8")["intent"] == "deletion"

    _script_llm(monkeypatch, [json.dumps({"reply": "no pumps found"})])
    final = W.run_describe_turn(PID, "what pumps do we have?", "s9",
                               use_llm_router=False)
    assert final["agent"] == "query"
    assert _pending(PID, "s9") is None


# ── insert_between (H2/K1 fix) — direct repository tests ────────────────────

def test_insert_between_removes_stale_direct_edge(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])

    result = R.insert_between(PID, {"tag": "VALVE-1", "kind": "valve"},
                              "V-101", "E-101")
    assert "Inserted VALVE-1" in result
    assert "removed the old direct edge" in result

    conns_v = R.get_connections(PID, "V-101")
    conns_e = R.get_connections(PID, "E-101")
    # V-101 -> VALVE-1 -> E-101, and NO direct V-101 -> E-101 survives.
    assert {c["other"] for c in conns_v} == {"VALVE-1"}
    assert {c["other"] for c in conns_e} == {"VALVE-1"}


def test_insert_between_by_node_id_disambiguates_duplicate_tags(db):
    """The exact H2 fix: node_a/node_b (unique ids) target one specific
    occurrence even when the tag is duplicated — using the tag string
    instead would be ambiguous at the DB layer too."""
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, x, y) VALUES "
        "('n_v2', ?, 'vessel', 'V-101', 500, 500), "
        "('n_e2', ?, 'heat_exchanger', 'E-101', 600, 500)", (PID, PID))
    R._db().execute(
        "INSERT INTO edges (pid, from_id, to_id, kind) "
        "VALUES (?, 'n_v2', 'n_e2', 'stream')", (PID,))
    R._db().commit()

    # Target the SECOND pair by its unique node ids.
    R.insert_between(PID, {"tag": "VALVE-2", "kind": "valve"},
                     "n_v2", "n_e2")

    # First pair's original direct edge is untouched.
    conns_v1 = R.get_connections(PID, "V-101")
    assert any(c["other"] == "E-101" for c in conns_v1)


def test_insert_between_missing_endpoint_errors(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}])
    result = R.insert_between(PID, {"tag": "X-1", "kind": "valve"},
                              "V-101", "NOPE")
    assert result.startswith("ERROR")


def test_insert_between_duplicate_new_tag_errors(db):
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    result = R.insert_between(PID, {"tag": "V-101", "kind": "valve"},
                              "V-101", "E-101")
    assert result.startswith("ERROR")


def test_authoring_agent_owns_insert_between_tool(db, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from agents.describe.agents.authoring_agent import build_authoring_agent, TOOLS
    assert "insert_between" in TOOLS

    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"},
                      {"tag": "E-101", "kind": "heat_exchanger"}])
    R.add_edges(PID, [{"from_tag": "V-101", "to_tag": "E-101"}])
    from agents.describe.services.grid_service import recompute_grid
    recompute_grid(PID)
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)

    it = iter([
        json.dumps({"tool": "insert_between",
                    "args": {"new_node": {"tag": "VALVE-1", "kind": "valve"},
                            "node_a": "V-101", "node_b": "E-101"}}),
        json.dumps({"reply": "Inserted VALVE-1."}),
    ])
    monkeypatch.setattr(B, "llm_complete", lambda p: next(it))

    graphs = {"authoring": W._BUILDERS["authoring"](InMemorySaver())}
    final = W.run_describe_turn(
        PID, "add a valve between V-101 and E-101", "s10",
        graphs=graphs, use_llm_router=False)
    assert final["agent"] == "authoring"
    assert len(final["ops"]) == 1
    assert final["ops"][0]["tool"] == "insert_between"
    conns = R.get_connections(PID, "V-101")
    assert {c["other"] for c in conns} == {"VALVE-1"}   # old V-101->E-101 gone


# ── H3: deletion interrupt payload carries resolved node id ─────────────────

def test_deletion_interrupt_carries_resolved_target(db, monkeypatch):
    R.add_nodes(PID, [{"tag": "V-9", "kind": "vessel"}])
    R._db().execute(
        "INSERT INTO nodes (id, pid, kind, label, area, x, y) VALUES "
        "('n_dup9', ?, 'vessel', 'V-9', '200', 0, 0)", (PID,))
    R._db().commit()
    monkeypatch.setattr(H, "_extract_tags_llm", lambda message: None)

    blocked = W.run_describe_turn(PID, "delete V-9", "s11",
                                  use_llm_router=False)
    assert blocked["agent"] == "holistic"
    pending = _pending(PID, "s11")
    assert pending["intent"] == "deletion"

    from langgraph.checkpoint.memory import InMemorySaver
    captured = []
    monkeypatch.setattr(B, "llm_complete",
                        lambda p: captured.append(p) or json.dumps(
                            {"tool": "delete_nodes",
                             "args": {"tags": ["V-9"], "reason": "test"}}))
    graphs = {"deletion": W._BUILDERS["deletion"](InMemorySaver())}
    paused = W.run_describe_turn(PID, "option 1", "s11", graphs=graphs,
                                 use_llm_router=False)
    assert "__interrupt__" in paused
    payload = paused["__interrupt__"][0].value
    assert payload["resolved"] is not None
    assert payload["resolved"]["node_a"] in ("V-9", "n_dup9")


# ── Engineering Completeness Gating & Input Analysis Tests ───────────────────

def test_input_analyze_blocks_on_critical_missing(db, monkeypatch):
    """When Class B critical design constraints are missing, the gate blocks with questions."""
    from agents.describe.agents.input_analyze_agent import _analyze_input_llm, evaluate_input_holisticness
    from agents.describe.schemas import InputAnalysisResult

    mock_analysis = InputAnalysisResult(
        engineering_completeness={
            "overall_score": 45,
            "process_score": 30,
            "safety_score": 20,
        },
        reasoning="Critical fluid properties and SIL targets are missing.",
        critical_missing=[
            {"category": "Process", "severity": "Critical", "reason": "Fluid density required for valve sizing", "dependency": "Loop -> Valve -> Cv"},
            {"category": "Safety", "severity": "Critical", "reason": "SIL target missing", "dependency": "Safety loops -> SIL targets"}
        ],
        questions=[
            "What is the process fluid and its density/viscosity?",
            "What is the required SIL target and ESD philosophy?"
        ],
        tags=["V-101"]
    )
    monkeypatch.setattr("agents.describe.agents.input_analyze_agent._analyze_input_llm",
                        lambda *a, **k: mock_analysis)

    verdict, method = evaluate_input_holisticness(
        PID, "design a level control system for V-101",
        intent="solution", gate_mode="ENABLED", use_llm=True
    )
    assert verdict.clarity == "blocked"
    assert len(verdict.questions) == 2
    assert verdict.engineering_completeness["overall_score"] == 45
    assert len(verdict.critical_missing) == 2


def test_input_analyze_passes_when_bypassed(db, monkeypatch):
    """When gate mode is BYPASSED, completeness checks do not block."""
    from agents.describe.agents.input_analyze_agent import evaluate_input_holisticness
    R.add_nodes(PID, [{"tag": "V-101", "kind": "vessel"}])

    verdict, _ = evaluate_input_holisticness(
        PID, "design a level control system for V-101",
        intent="solution", gate_mode="BYPASSED", use_llm=False
    )
    assert verdict.clarity in ("clear", "no_target")


# ── greenfield/brownfield gating (added alongside authoring/solution) ───────

def test_greenfield_blocks_on_critical_missing(db, monkeypatch):
    """A clean-sheet request with Class B constraints missing blocks with
    questions BEFORE the greenfield specialist starts authoring, same as
    the existing authoring/solution behavior."""
    from agents.describe.agents.input_analyze_agent import evaluate_input_holisticness
    from agents.describe.schemas import InputAnalysisResult

    mock_analysis = InputAnalysisResult(
        engineering_completeness={"overall_score": 40, "process_score": 25},
        reasoning="No fluid properties or safety architecture provided for a clean-sheet unit.",
        critical_missing=[
            {"category": "Process", "severity": "Critical",
             "reason": "Fluid identity/density required before equipment sizing",
             "dependency": "Equipment -> Sizing -> Fluid Density"},
        ],
        questions=["What is the process fluid and its operating envelope (P, T, flow)?"],
        tags=[],
    )
    monkeypatch.setattr("agents.describe.agents.input_analyze_agent._analyze_input_llm",
                        lambda *a, **k: mock_analysis)

    verdict, _ = evaluate_input_holisticness(
        PID, "design a new clean-sheet reactor unit from scratch",
        intent="greenfield", gate_mode="ENABLED", use_llm=True
    )
    assert verdict.clarity == "blocked"
    assert len(verdict.questions) == 1
    assert verdict.engineering_completeness["overall_score"] == 40


def test_brownfield_blocks_on_critical_missing(db, monkeypatch):
    """A retrofit/tie-in request with Class B constraints missing blocks
    with questions, same mechanism as greenfield/authoring/solution."""
    from agents.describe.agents.input_analyze_agent import evaluate_input_holisticness
    from agents.describe.schemas import InputAnalysisResult

    mock_analysis = InputAnalysisResult(
        engineering_completeness={"overall_score": 55, "safety_score": 30},
        reasoning="SIL target and tie-in utility conditions are not specified.",
        critical_missing=[
            {"category": "Safety", "severity": "Critical",
             "reason": "SIL target required for the new relief loop",
             "dependency": "Safety loops -> SIL targets"},
        ],
        questions=["What SIL target applies to the new safety loop at this tie-in?"],
        tags=["TP-01"],
    )
    monkeypatch.setattr("agents.describe.agents.input_analyze_agent._analyze_input_llm",
                        lambda *a, **k: mock_analysis)

    verdict, _ = evaluate_input_holisticness(
        PID, "retrofit a new relief loop tying into TP-01",
        intent="brownfield", gate_mode="ENABLED", use_llm=True
    )
    assert verdict.clarity == "blocked"
    assert len(verdict.questions) == 1


def test_greenfield_fresh_request_with_no_tags_passes_through(db, monkeypatch):
    """A from-scratch design naming no existing equipment has nothing to
    spatially disambiguate — it must not get stuck asking 'which one did
    you mean' just because greenfield is now gated. (Class-B completeness
    can still separately block it — that's covered by the test above; this
    test isolates the tag-disambiguation half of the gate.)"""
    from agents.describe.agents.input_analyze_agent import evaluate_input_holisticness
    from agents.describe.schemas import InputAnalysisResult

    # A fully-complete analysis (nothing Class-B missing) with zero tags —
    # isolates "no_target" pass-through from the completeness block path.
    mock_analysis = InputAnalysisResult(
        engineering_completeness={"overall_score": 100},
        reasoning="Sufficient detail provided.",
        critical_missing=[], questions=[], tags=[],
    )
    monkeypatch.setattr("agents.describe.agents.input_analyze_agent._analyze_input_llm",
                        lambda *a, **k: mock_analysis)

    verdict, _ = evaluate_input_holisticness(
        PID, "design a new clean-sheet catalytic reactor unit with feed and relief",
        intent="greenfield", gate_mode="ENABLED", use_llm=True
    )
    assert verdict.clarity == "no_target"
    assert verdict.tags == []


def test_gated_intents_include_greenfield_and_brownfield():
    """Locks in the dispatch-layer half of the gate — a regression here
    would silently disconnect greenfield/brownfield from the completeness
    check even if input_analyze_agent.py's tuple stays correct."""
    assert "greenfield" in W._GATED_INTENTS
    assert "brownfield" in W._GATED_INTENTS

