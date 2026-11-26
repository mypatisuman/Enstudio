"""Shared state schema for the agentic extraction pipeline.

Images are passed by file path, never as bytes — checkpoints must stay
small enough to persist per super-step.
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict


class QCReport(TypedDict, total=False):
    stage: str                      # e.g. "symbol_detection"
    verdict: Literal["ok", "suspect", "failed"]
    metrics: dict[str, Any]
    action_taken: str               # "proceed" | "retry_lower_conf" | ...
    reason: str
    controller: Literal["rules", "llm", "llm_fallback_rules"]


class UsageRecord(TypedDict, total=False):
    stage: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    """Reducer for per-stage dict channels written by parallel branches."""
    return {**(a or {}), **(b or {})}


class ExtractionState(TypedDict, total=False):
    # ── Inputs (set at invocation, never mutated) ──────────────────────
    pid: str
    hub: str
    source_path: str
    llm_only: bool
    provider: str
    # sources.id for the document being extracted. Scopes node/edge identity
    # to the document exactly as the classic pipeline does, so two PDFs in one
    # project cannot overwrite each other's rows. None for callers with no
    # sources row (tests, the Flask path), which reproduces the historic
    # unprefixed ids.
    source_id: int | None

    # ── Derived early ──────────────────────────────────────────────────
    file_hash: str
    media_type: str
    page_paths: list[str]           # rendered PNG paths
    cache_hit: bool

    # ── Detection outputs (per modality) ───────────────────────────────
    symbol_detections: list[dict]
    text_detections: list[dict]
    line_segments: dict             # {long_lines, connected_lines, signal_lines}
    image_size: dict                # {width, height}

    # ── Relationship building ──────────────────────────────────────────
    candidate_graph: dict

    # ── LLM verification ───────────────────────────────────────────────
    llm_a_result: dict
    llm_b_result: dict
    verified_nodes: list[dict]
    verified_edges: list[dict]

    # ── Inference passes ───────────────────────────────────────────────
    proposals: list[dict]
    loops: list[dict]

    # ── Text→vision escalation (Text agent → Harness LLM A) ───────────
    text_escalations: list[dict]

    # ── Multi-page (E1) ──────────────────────────────────────────────
    # Per-page results, collected as each page's page_pipeline subgraph
    # finishes. Keyed by page index (int, as a string key for JSON/
    # checkpoint friendliness), value = {"nodes": [...], "edges": [...]}
    # already namespaced with a "p{i}_" node-id prefix so merge_results
    # can safely concatenate across pages with no id collisions. This is
    # additive alongside the existing single-page llm_a_result/
    # llm_b_result/verified_nodes/verified_edges fields, which stay
    # exactly as they are for the N=1 (single image, non-PDF) case —
    # page_pipeline_results is only consulted when it's non-empty.
    page_pipeline_results: Annotated[dict, merge_dicts]
    page_count: int

    # ── Cross-cutting ──────────────────────────────────────────────────
    qc_reports: Annotated[list[QCReport], add]
    usage: Annotated[list[UsageRecord], add]
    retry_counts: Annotated[dict, merge_dicts]   # per-stage bounded-loop guards
    retry_params: Annotated[dict, merge_dicts]   # per-stage params for next retry

    status: Literal["running", "complete", "failed", "cached", "degraded"]
    error: str | None


MAX_RETRIES_PER_STAGE = 2


def retries_used(state: ExtractionState, stage: str) -> int:
    return (state.get("retry_counts") or {}).get(stage, 0)


def can_retry(state: ExtractionState, stage: str) -> bool:
    return retries_used(state, stage) < MAX_RETRIES_PER_STAGE
