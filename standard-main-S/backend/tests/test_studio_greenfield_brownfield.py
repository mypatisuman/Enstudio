"""
Unit and integration tests for Greenfield and Brownfield Describe specialists in studio.
"""

import pytest
from agents.describe.agents.router import route_message, INTENTS
from agents.describe.agents.greenfield_agent import build_greenfield_agent
from agents.describe.agents.brownfield_agent import build_brownfield_agent
from agents.describe.services.isa_classifier import parse_isa_tag, classify_node_kind
from agents.describe.workflows.describe_workflow import _BUILDERS


def test_intents_include_greenfield_and_brownfield():
    assert "greenfield" in INTENTS
    assert "brownfield" in INTENTS
    assert "greenfield" in _BUILDERS
    assert "brownfield" in _BUILDERS


def test_router_detects_greenfield_and_brownfield():
    intent, reason, controller = route_message("pid_1", "Design a new chemical dosing system from scratch", use_llm=False)
    assert intent == "greenfield"

    intent, reason, controller = route_message("pid_1", "Retrofit a steam letdown station and tie into existing header TP-01", use_llm=False)
    assert intent == "brownfield"

    intent, reason, controller = route_message("pid_1", "Clean-sheet pasteurization unit design", use_llm=False)
    assert intent == "greenfield"

    intent, reason, controller = route_message("pid_1", "Debottleneck the existing line and add a bypass", use_llm=False)
    assert intent == "brownfield"


def test_agent_compilation():
    gf_agent = build_greenfield_agent()
    assert gf_agent is not None

    bf_agent = build_brownfield_agent()
    assert bf_agent is not None


def test_greenfield_brownfield_prompts_load_and_have_reasoning_phases():
    """Both prompts must load non-empty and carry the Phase 1-5 reasoning
    checklist added to reinforce instrument/accessory completeness before
    authoring — a regression here (empty file, broken markdown, or the
    phase section silently dropped) would remove that reinforcement
    without any other test noticing, since the LLM call itself isn't
    exercised by the unit tests."""
    from agents.prompts import load_prompt
    from agents.describe.prompts.catalog import (
        DESCRIBE_GREENFIELD_V1, DESCRIBE_BROWNFIELD_V1,
    )

    greenfield = load_prompt("describe_greenfield")
    brownfield = load_prompt("describe_brownfield")
    assert greenfield.strip(), "describe_greenfield.md is empty"
    assert brownfield.strip(), "describe_brownfield.md is empty"
    # catalog constants must reflect the same file content the loader reads
    assert DESCRIBE_GREENFIELD_V1 == greenfield
    assert DESCRIBE_BROWNFIELD_V1 == brownfield

    for name, text in (("greenfield", greenfield), ("brownfield", brownfield)):
        assert "ENGINEERING REASONING PHASES" in text, f"{name} missing phases section"
        for phase in ("Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5"):
            assert phase in text, f"{name} missing {phase}"
        # Phase 3 is the load-bearing "enumerate every instrument/accessory"
        # step both prompts were extended with — check it names all 4 of
        # the connection-topology categories, not just the section header.
        assert "4-WAY" in text.upper()
        for leg in ("Acc -> Acc", "Acc -> Inst", "Inst -> Inst", "Inst -> Acc"):
            assert leg in text, f"{name} Phase 3 missing connection type {leg}"

    # brownfield's Phase 3 must explicitly guard against duplicating an
    # instrument that already exists on the line — the one place its
    # phase wording deliberately diverges from greenfield's.
    assert "duplicate" in brownfield.lower()


def test_studio_isa_classifier():
    # Standard tags
    assert classify_node_kind("PT-101") == "transmitter"
    assert classify_node_kind("100-PDT-201A") == "transmitter"
    assert classify_node_kind("20-FCV-101") == "valve"
    assert classify_node_kind("01-P-101A") == "pump"
    assert classify_node_kind("MNF-101") == "manifold"
    assert classify_node_kind("SYP-101") == "siphon"
    assert classify_node_kind("TW-101") == "thermowell"
    assert classify_node_kind("POS-101") == "positioner"
    assert classify_node_kind("ACT-101") == "actuator"
    assert classify_node_kind("AFR-101") == "regulator"
    assert classify_node_kind("TP-01") == "tie_in"

    # Grammar Parser
    parsed = parse_isa_tag("100-PDT-201A")
    assert parsed["is_isa_standard"] is True
    assert parsed["measured_variable"] == "Pressure / Vacuum"
    assert parsed["modifier"] == "Differential"
    assert parsed["function_letters"] == "T"
