"""Pydantic schemas for the extraction workflow's structured LLM outputs.

Reference-pattern layered defense: parse (JSON armor) -> validate
(these models, extra="ignore") -> coerce (ensure_compliant fills
defaults and NEVER raises). Downstream code always receives a
well-shaped dict.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Compliant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @classmethod
    def ensure_compliant(cls, raw) -> dict:
        """Validate; on any failure return the model's defaults merged
        with whatever raw fields do validate individually. Never raises."""
        if not isinstance(raw, dict):
            raw = {}
        try:
            return cls.model_validate(raw).model_dump()
        except Exception:
            out = cls().model_dump()
            for k in list(out):
                if k in raw:
                    try:
                        out[k] = cls.model_validate({**out, k: raw[k]}) \
                            .model_dump()[k]
                    except Exception:
                        pass
            return out


class QCDecision(_Compliant):
    """A QC controller's decision (symbol/text/geometry/consolidation)."""
    verdict: str = "ok"
    action: str = "proceed"
    actions: list[str] = Field(default_factory=list)   # line agent variant
    redispatch_target: str | None = None
    escalate_crops: list | None = None
    intent: str | None = None
    reason: str = ""


class LLMAResult(_Compliant):
    """LLM A (symbol verifier) output."""
    nodes: list[dict] = Field(default_factory=list)
    tag_readings: list[dict] = Field(default_factory=list)
    error: str | None = None


class SymbolDetectResult(_Compliant):
    """Per-tile agentic symbol detection output (symbol_detect.md)."""
    detections: list[dict] = Field(default_factory=list)


class TextReadResult(_Compliant):
    """Per-symbol-crop agentic text reading output (text_read.md)."""
    legible: bool = False
    text: str = ""
    kind: str = "tag"
    confidence: float = 0.0


class TextReadTileResult(_Compliant):
    """Per-tile agentic text reading output, fallback path (text_read_tile.md)."""
    detections: list[dict] = Field(default_factory=list)


class LineTraceResult(_Compliant):
    """Per-tile agentic line tracing output (line_trace.md)."""
    runs: list[dict] = Field(default_factory=list)


class LineVerifyResult(_Compliant):
    """Full-page line-trace verification output (line_verify.md)."""
    runs: list[dict] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    merged: list[list[str]] = Field(default_factory=list)


class LLMBResult(_Compliant):
    """LLM B (connection auditor) output."""
    edges: list[dict] = Field(default_factory=list)
    junctions: list[dict] = Field(default_factory=list)
    unaudited: bool = False
