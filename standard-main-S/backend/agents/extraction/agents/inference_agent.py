"""Inference Passes Agent — Pass 3 tag repair, Pass 4 connection
proposals, control-loop inference, plus the new cross-check that drops
inference proposals contradicting audited edges.

Sequencing carries feedback: tags are repaired first (better loops),
loops next (better tier-2 connection matches), connections last.
All outputs are proposals for the Review screen — never silent writes.
"""
from __future__ import annotations

from agents.extraction.state import ExtractionState
from agents.retry import retryable_node
from agents.streaming import stage as emit_stage
from agents.toolkit import qc_report

STAGE = "inference_passes"


def _on_inference_exhausted(state: ExtractionState, err: Exception) -> dict:
    """Degradation policy: proposals are enrichment — never fail the run."""
    return {"proposals": [], "loops": [],
            "qc_reports": [qc_report(STAGE, "failed", {}, "degrade",
                                     f"inference passes failed: {err}",
                                     "rules")]}


@retryable_node(max_attempts=2, label=STAGE,
                on_exhausted=_on_inference_exhausted)
def inference_node(state: ExtractionState) -> dict:
    nodes = state.get("verified_nodes") or []
    edges = state.get("verified_edges") or []
    known_tags = [n.get("label") for n in nodes if n.get("label")]

    tag_proposals = _pass3_tags(nodes, edges, known_tags)
    loops = _infer_loops(nodes)
    conn_result = _pass4_connections(nodes, edges)
    conn_proposals = conn_result.get("proposals", [])

    dropped = _conflict_check(conn_proposals, edges)
    conn_proposals = [p for p in conn_proposals if p not in dropped]

    proposals = tag_proposals + conn_proposals
    persisted = _persist_proposals(state.get("pid", ""), proposals)
    emit_stage(STAGE, "complete", tag_proposals=len(tag_proposals),
               connection_proposals=len(conn_proposals),
               conflicts_dropped=len(dropped), loops=len(loops),
               persisted=persisted)
    return {
        "proposals": proposals,
        "loops": loops,
        "qc_reports": [qc_report(
            STAGE, "ok",
            {"tag_proposals": len(tag_proposals),
             "connection_proposals": len(conn_proposals),
             "conflicts_dropped": len(dropped), "loops": len(loops)},
            "proceed", "inference passes complete", "rules")],
    }


def _persist_proposals(pid: str, proposals: list) -> bool:
    """Write proposals to the proposals table so the Review screen's
    queue sees them — the human gate this workflow feeds. Tolerant:
    persistence failure never fails the run (proposals stay in state
    and the NDJSON stream regardless)."""
    if not pid or not proposals:
        return False
    try:
        import json as _json
        from adapters.db import get_db
        db = get_db()
        for p in proposals:
            node_id = p.get("node_id") or p.get("from_tag") or ""
            db.execute(
                "INSERT INTO proposals (pid, node_id, type, original, "
                "proposed, confidence, method, review_state, extra_json) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(pid, node_id, type) DO UPDATE SET "
                "proposed=excluded.proposed, confidence=excluded.confidence, "
                "method=excluded.method, review_state=excluded.review_state, "
                "extra_json=excluded.extra_json",
                (pid, node_id, p.get("type", "connection"),
                 str(p.get("original", "")),
                 str(p.get("proposed") or p.get("to_tag") or ""),
                 float(p.get("confidence", 0.0) or 0.0),
                 p.get("method", "inference"),
                 p.get("review_state", "inferred"),
                 _json.dumps(p)))
        db.commit()
        return True
    except Exception as e:
        emit_stage(STAGE, "persist_partial", detail=str(e)[:200])
        return False


def _pass3_tags(nodes: list, edges: list, known_tags: list) -> list:
    out = []
    try:
        from adapters.tag_inference import infer_tag, normalize_tag
        for n in nodes:
            tag = n.get("label") or ""
            area = n.get("area") or ""
            if tag and tag not in ("??", "XX"):
                fix = normalize_tag(tag, area, n.get("kind", ""), known_tags)
                if fix:
                    out.append({"type": "tag", "node_id": n.get("id"),
                                "original": tag, **fix})
            else:
                prop = infer_tag(n, nodes, edges, known_tags)
                if prop:
                    out.append({"type": "tag", "node_id": n.get("id"),
                                "original": tag, **prop})
    except Exception as e:
        emit_stage(STAGE, "pass3_partial", detail=str(e)[:200])
    return out


def _pass4_connections(nodes: list, edges: list) -> dict:
    try:
        from adapters.connectivity_inference import run_connectivity_inference
        return run_connectivity_inference(nodes, edges)
    except Exception as e:
        emit_stage(STAGE, "pass4_partial", detail=str(e)[:200])
        return {"proposals": []}


def _infer_loops(nodes: list) -> list:
    try:
        from domain.loop_inference import infer_loops
        instruments = {n["label"]: {"area": n.get("area", ""),
                                    "type": n.get("kind_detail", "")}
                       for n in nodes
                       if n.get("label") and _is_instrument(n)}
        espx = {"studio": {"instruments": instruments}, "nodes": nodes}
        loops = infer_loops(espx)
        return [{"loop_id": k, **v} if isinstance(v, dict)
                else {"loop_id": k, "loop": v} for k, v in loops.items()]
    except Exception as e:
        emit_stage(STAGE, "loops_partial", detail=str(e)[:200])
        return []


def _is_instrument(node: dict) -> bool:
    try:
        from domain.kind_mapping import INSTRUMENT_KINDS
        return node.get("kind") in INSTRUMENT_KINDS
    except Exception:
        return node.get("kind") in {"transmitter", "controller", "indicator",
                                    "recorder", "switch", "analyzer",
                                    "element", "instrument"}


def _conflict_check(proposals: list, audited_edges: list) -> list:
    """Deterministic conflict rules (the PROPOSAL_CONFLICT prompt escalates
    only genuinely ambiguous cases; duplicates and contradictions are
    plain code). Geometric/audited evidence outranks inference."""
    audited = {(e.get("from"), e.get("to")) for e in audited_edges} | \
              {(e.get("to"), e.get("from")) for e in audited_edges}
    dropped = []
    for p in proposals:
        pair = (p.get("from_tag") or p.get("from"),
                p.get("to_tag") or p.get("to"))
        if pair in audited:
            dropped.append(p)
    return dropped
