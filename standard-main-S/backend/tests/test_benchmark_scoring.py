"""Benchmark harness, offline: truth derivation, scoring, and the cost guard.

Nothing here calls a model. The live runner is exercised only up to the point
where it would spend money.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from benchmarks import scoring as S  # noqa: E402
from benchmarks.derive_truth import derive, image_size  # noqa: E402

FIXTURE = REPO / "fixtures" / "connectivity_graph 18.json"
IMAGE = REPO / "fixtures" / "pid-images" / "pid18.png"


def _doc(nodes: dict, edges: list[tuple[str, str]]) -> dict:
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}


def _sym(label, type_="valve", bbox=None):
    return {"type": type_, "label": label, "bbox": bbox or [0, 0, 10, 10]}


def _jx(kind="t_junction"):
    return {"type": kind, "label": ""}


# ── tags ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label, expected", [
    ("PT-1111", True), ("R-110 B", True), ("TI-1103F A", True), ("FIC1108", True),
    ("Filter 1", False), ("sym_92", False), ("CWS HEADER", False), ("", False), (None, False),
])
def test_tag_recognition(label, expected):
    assert S.is_tag(label) is expected


def test_normalisation_ignores_case_spaces_and_hyphens():
    assert S.normalise("r-110 b") == S.normalise("R110B") == "R110B"


def test_tag_precision_recall():
    truth = _doc({"a": _sym("PT-1"), "b": _sym("PIC-1"), "c": _sym("PCV-1")}, [])
    pred = _doc({"x": _sym("pt 1"), "y": _sym("PIC-1"), "z": _sym("XV-9")}, [])
    s = S.score(pred, truth)["tags"]
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert s["precision"] == s["recall"] == pytest.approx(0.6667)


def test_descriptive_labels_are_counted_not_scored():
    truth = _doc({"a": _sym("PT-1"), "b": _sym("Filter 1", "inline_component")}, [])
    s = S.score(truth, truth)
    assert s["tags"]["tp"] == 1 and s["untagged_truth_symbols"] == 1


# ── connections ──────────────────────────────────────────────────────────────

def test_junction_chains_collapse_to_tag_pairs():
    doc = _doc({"a": _sym("V-1"), "j1": _jx(), "j2": _jx("endpoint_share"), "b": _sym("V-2"),
                "c": _sym("V-3")},
               [("a", "j1"), ("j1", "j2"), ("j2", "b"), ("j1", "c")])
    assert S.tag_pairs(doc) == {frozenset(p) for p in [("V1", "V2"), ("V1", "V3"), ("V2", "V3")]}


def test_paths_do_not_pass_through_symbols():
    doc = _doc({"a": _sym("V-1"), "b": _sym("V-2"), "c": _sym("V-3")}, [("a", "b"), ("b", "c")])
    assert S.tag_pairs(doc) == {frozenset(("V1", "V2")), frozenset(("V2", "V3"))}


def test_direct_and_junction_wiring_score_the_same():
    truth = _doc({"a": _sym("V-1"), "j": _jx(), "b": _sym("V-2")}, [("a", "j"), ("j", "b")])
    pred = _doc({"p": _sym("V-1"), "q": _sym("V-2")}, [("q", "p")])
    assert S.score(pred, truth)["connections"]["f1"] == 1.0


def test_restricted_connections_separate_missed_symbols_from_miswiring():
    truth = _doc({"a": _sym("V-1"), "b": _sym("V-2"), "c": _sym("V-3")}, [("a", "b"), ("b", "c")])
    pred = _doc({"a": _sym("V-1"), "b": _sym("V-2")}, [("a", "b")])      # missed V-3 only
    s = S.score(pred, truth)
    assert s["connections"]["recall"] == 0.5
    assert s["connections_among_found_tags"]["f1"] == 1.0


# ── boxes and types ──────────────────────────────────────────────────────────

def test_prediction_boxes_are_scaled_to_the_truth_image():
    truth = _doc({"a": _sym("V-1", bbox=[100, 100, 200, 200])}, [])
    pred = _doc({"a": _sym("V-1", bbox=[50, 50, 100, 100])}, [])
    assert S.score(pred, truth)["boxes"]["mean_iou"] == 0.0          # touch at a corner only
    assert S.score(pred, truth, prediction_scale=2.0)["boxes"]["mean_iou"] == 1.0


def test_type_accuracy():
    truth = _doc({"a": _sym("PT-1", "instrument"), "b": _sym("V-1", "valve")}, [])
    pred = _doc({"a": _sym("PT-1", "instrument"), "b": _sym("V-1", "equipment")}, [])
    assert S.score(pred, truth)["types"]["accuracy"] == 0.5


def test_aggregate_is_micro_averaged():
    truth = _doc({"a": _sym("V-1"), "b": _sym("V-2")}, [("a", "b")])
    perfect = {"score": S.score(truth, truth), "seconds": 10, "tokens_in": 5, "cost_usd": 0.5}
    empty = {"score": S.score(_doc({}, []), truth), "seconds": 30, "tokens_in": 7, "cost_usd": 0.25}
    agg = S.aggregate([perfect, empty])
    assert agg["tags"]["recall"] == 0.5 and agg["tags"]["precision"] == 1.0
    assert agg["seconds_per_drawing"] == 20 and agg["tokens_in"] == 12 and agg["cost_usd"] == 0.75


# ── the real drawing-18 truth ────────────────────────────────────────────────

@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture graph absent")
def test_derived_truth_is_unverified_and_scores_perfectly_against_itself():
    truth = derive(FIXTURE, "pid-images/pid18.png", REPO / "fixtures")
    assert truth["truth"]["verified_by"] is None
    if IMAGE.exists():
        assert (truth["truth"]["image_width"], truth["truth"]["image_height"]) == image_size(IMAGE)
    s = S.score(truth, truth)
    assert s["tags"]["f1"] == 1.0 and s["connections"]["f1"] == 1.0
    assert s["tags"]["tp"] >= 80 and s["connections"]["tp"] >= 100


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture graph absent")
def test_losing_a_junction_edge_costs_connection_recall():
    truth = json.loads(FIXTURE.read_text(encoding="utf-8"))
    damaged = {**truth, "edges": [e for e in truth["edges"]
                                  if not str(e.get("to", "")).startswith("JX_T_")]}
    s = S.score(damaged, truth)
    assert s["tags"]["f1"] == 1.0 and s["connections"]["recall"] < 1.0
    assert s["connections"]["precision"] == 1.0


def test_image_size_rejects_non_png(tmp_path):
    f = tmp_path / "x.png"
    f.write_bytes(b"not a png at all, just bytes")
    assert image_size(f) is None and image_size(tmp_path / "missing.png") is None


# ── runner guard ─────────────────────────────────────────────────────────────

def _truth_dir(tmp_path: Path) -> Path:
    fixtures = tmp_path / "fx"
    (fixtures / "ground_truth").mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (64).to_bytes(4, "big") + (32).to_bytes(4, "big")
    (fixtures / "d.png").write_bytes(png + b"\x00" * 16)
    doc = _doc({"a": _sym("V-1")}, [])
    doc["truth"] = {"image": "d.png", "verified_by": "test"}
    (fixtures / "ground_truth" / "d.json").write_text(json.dumps(doc), encoding="utf-8")
    return fixtures


def _run(*args):
    return subprocess.run([sys.executable, str(BACKEND / "benchmarks" / "run_benchmark.py"), *args],
                          cwd=BACKEND, capture_output=True, text=True, timeout=120)


def test_live_run_refuses_without_cost_confirmation(tmp_path):
    proc = _run("--fixtures", str(_truth_dir(tmp_path)))
    assert proc.returncode == 2 and "--confirm-cost" in proc.stdout


def test_dry_run_validates_without_calling_anything(tmp_path):
    proc = _run("--fixtures", str(_truth_dir(tmp_path)), "--dry-run")
    assert proc.returncode == 0 and "1 truth file(s) valid" in proc.stdout


def test_missing_image_is_reported(tmp_path):
    fixtures = _truth_dir(tmp_path)
    (fixtures / "d.png").unlink()
    proc = _run("--fixtures", str(fixtures), "--dry-run")
    assert proc.returncode == 1 and "image not found" in proc.stdout
