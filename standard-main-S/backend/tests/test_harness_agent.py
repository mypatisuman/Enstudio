"""Tests for the Harness agent's company-convention injection (E5) — the
gap where the agentic llm_a_node/llm_b_node never looked up a project's
company conventions before calling the vision LLM, unlike the classic
Flask pipeline's claude_extract_image(conventions_text=...).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.extraction.agents import harness_agent as H  # noqa: E402


def test_conventions_text_returns_empty_when_no_company(monkeypatch, tmp_path):
    import services.convention_service as cs
    monkeypatch.setattr(cs, "_get_conventions", lambda *a, **k: None)
    state = {"pid": "tproj", "hub": str(tmp_path)}
    assert H._conventions_text(state) == ""


def test_conventions_text_returns_skill_text_when_company_set(monkeypatch,
                                                               tmp_path):
    import services.convention_service as cs
    fake_conv = MagicMock()
    fake_conv.as_skill_text.return_value = "## Company P&ID Conventions: AIRCO\n\nUse AIRCO tag prefixes."
    monkeypatch.setattr(cs, "_get_conventions", lambda *a, **k: fake_conv)
    state = {"pid": "tproj", "hub": str(tmp_path)}
    assert H._conventions_text(state) == \
        "## Company P&ID Conventions: AIRCO\n\nUse AIRCO tag prefixes."


def test_conventions_text_resolves_with_hub_projects_dir(monkeypatch, tmp_path):
    """_get_conventions must be called with hub/projects, not hub itself
    — matching manifest_repository's <projects_dir>/<pid>/project.json
    layout (confirmed against orchestration.intake's proj_dir)."""
    import services.convention_service as cs
    captured = {}

    def fake_get_conventions(pid, hub, projects_dir):
        captured["pid"] = pid
        captured["hub"] = hub
        captured["projects_dir"] = projects_dir
        return None

    monkeypatch.setattr(cs, "_get_conventions", fake_get_conventions)
    state = {"pid": "tproj", "hub": str(tmp_path)}
    H._conventions_text(state)

    assert captured["pid"] == "tproj"
    assert captured["hub"] == tmp_path
    assert captured["projects_dir"] == tmp_path / "projects"


def test_conventions_text_swallows_lookup_errors(monkeypatch, tmp_path):
    import services.convention_service as cs

    def boom(*a, **k):
        raise RuntimeError("manifest corrupt")

    monkeypatch.setattr(cs, "_get_conventions", boom)
    state = {"pid": "tproj", "hub": str(tmp_path)}
    assert H._conventions_text(state) == ""


def test_llm_a_node_passes_conventions_text_through(monkeypatch, tmp_path):
    monkeypatch.setattr(H, "_conventions_text", lambda state: "CONV-TEXT")
    monkeypatch.setattr(H, "_page_bytes", lambda state: b"fake-png-bytes")
    monkeypatch.setattr(H, "_studio_module", lambda: MagicMock())

    captured = {}

    def fake_call_llm_verification(_s, img, media_type, summary, img_w,
                                   img_h, raw_lines, conventions_text=""):
        captured["conventions_text"] = conventions_text
        return {"nodes": []}, {"tokens_in": 10, "tokens_out": 5,
                               "model": "m", "provider": "p",
                               "cost_usd": 0.01}

    import extraction_cli.llm_verification as LV
    monkeypatch.setattr(LV, "_call_llm_verification",
                        fake_call_llm_verification)

    state = {"pid": "tproj", "hub": str(tmp_path), "page_paths": ["x.png"],
             "symbol_detections": [], "text_detections": [],
             "image_size": {"width": 100, "height": 100},
             "text_escalations": [], "retry_counts": {}, "retry_params": {}}
    out = H.llm_a_node.__wrapped__(state)

    assert captured["conventions_text"] == "CONV-TEXT"
    assert out["usage"] == [{"stage": H.STAGE_A, "provider": "p", "model": "m",
                             "input_tokens": 10, "output_tokens": 5,
                             "cost_usd": 0.01}]


def test_llm_b_node_passes_conventions_text_through(monkeypatch, tmp_path):
    monkeypatch.setattr(H, "_conventions_text", lambda state: "CONV-TEXT-B")
    monkeypatch.setattr(H, "_page_bytes", lambda state: b"fake-png-bytes")
    monkeypatch.setattr(H, "_studio_module", lambda: MagicMock())

    captured = {}

    def fake_call_llm_connections(_s, img, media_type, summary,
                                  proposed_graph_text="", conventions_text=""):
        captured["conventions_text"] = conventions_text
        return {"edges": [], "junctions": []}, {"tokens_in": 8, "tokens_out": 3,
                                                 "model": "m", "provider": "p",
                                                 "cost_usd": 0.02}

    import extraction_cli.llm_verification as LV
    monkeypatch.setattr(LV, "_call_llm_connections", fake_call_llm_connections)

    state = {
        "pid": "tproj", "hub": str(tmp_path), "page_paths": ["x.png"],
        "candidate_graph": {"edges": [{"from": "n1", "to": "n2"}],
                            "junctions": []},
        "llm_a_result": {"nodes": [{"id": "n1"}, {"id": "n2"}]},
        "symbol_detections": [], "text_detections": [],
        "image_size": {"width": 100, "height": 100},
        "retry_counts": {}, "retry_params": {},
    }
    out = H.llm_b_node.__wrapped__(state)

    assert captured["conventions_text"] == "CONV-TEXT-B"
    assert out["usage"] == [{"stage": H.STAGE_B, "provider": "p", "model": "m",
                             "input_tokens": 8, "output_tokens": 3,
                             "cost_usd": 0.02}]
