"""Tests for E6 — project.json manifest updates on a successful agentic
extraction run. merge_results() already delegates to extraction_cli's
_merge(), which itself calls main.update_manifest_after_extract()
internally; these tests prove that chain actually reaches project.json
when main.PROJECTS_DIR is aligned with the run's hub (the real-world
case — a single ENGINEERING_HUB env var backs both main.py's Flask
process and the agentic pipeline's `hub` state field).
"""
import json
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from agents.extraction.agents import orchestration as O  # noqa: E402


@pytest.fixture()
def aligned_hub(tmp_path, monkeypatch):
    """Point main.py's process-global PROJECTS_DIR at the same hub the
    agentic state dict uses — otherwise _merge()'s manifest write goes
    to the real dev EngineeringHub instead of the test's tmp_path."""
    hub = tmp_path / "hub"
    (hub / "projects" / "tproj").mkdir(parents=True)
    (hub / "projects" / "tproj" / "drawing.png").write_bytes(b"fake")

    import main as _s
    monkeypatch.setattr(_s, "PROJECTS_DIR", hub / "projects")
    return hub


def test_merge_results_updates_project_manifest(aligned_hub):
    state = {
        "pid": "tproj", "hub": str(aligned_hub), "file_hash": "abc123",
        "source_path": str(aligned_hub / "projects" / "tproj" / "drawing.png"),
        "llm_a_result": {"instruments": {}, "equipment": {}, "connections": []},
        "page_pipeline_results": {
            "0": {"nodes": [{"id": "p0_n1", "kind": "pump", "label": "P-101"}],
                 "edges": []}},
    }
    out = O.merge_results.__wrapped__(state)
    assert [n["id"] for n in out["verified_nodes"]] == ["p0_n1"]

    manifest_path = aligned_hub / "projects" / "tproj" / "project.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["extraction"]["status"] == "complete"
    assert manifest["extraction"]["nodes"] == 1
    assert manifest["extraction"]["source_hash"] == "abc123"
    assert any(s["hash"] == "abc123" for s in manifest["sources"])


def test_merge_results_manifest_survives_repeat_runs(aligned_hub):
    """Second run with the same file hash must not duplicate the sources
    entry (matching update_manifest_after_extract's own dedup rule)."""
    state = {
        "pid": "tproj", "hub": str(aligned_hub), "file_hash": "abc123",
        "source_path": str(aligned_hub / "projects" / "tproj" / "drawing.png"),
        "llm_a_result": {},
        "page_pipeline_results": {
            "0": {"nodes": [{"id": "p0_n1"}], "edges": []}},
    }
    O.merge_results.__wrapped__(state)
    O.merge_results.__wrapped__(state)

    manifest_path = aligned_hub / "projects" / "tproj" / "project.json"
    manifest = json.loads(manifest_path.read_text())
    matching = [s for s in manifest["sources"] if s["hash"] == "abc123"]
    assert len(matching) == 1
