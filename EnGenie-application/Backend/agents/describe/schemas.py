"""Pydantic schemas for the Describe workflow's structured LLM outputs."""
from __future__ import annotations

from pydantic import Field

from agents.extraction.schemas import _Compliant


class ToolCall(_Compliant):
    thought: str = ""
    tool: str = ""
    args: dict = Field(default_factory=dict)


class FinalReply(_Compliant):
    reply: str = ""
    title: str | None = None


class RouterDecision(_Compliant):
    action: str = "query"
    intent: str | None = None
    reason: str = ""


class TagReferences(_Compliant):
    """Output of the Holistic Agent's tag-extraction LLM call — which
    equipment/instrument tags (or bare descriptions) the engineer named
    in a free-text authoring/update request. Everything downstream of
    this (adjacency, disambiguation) is plain code, never the LLM."""
    tags: list[str] = Field(default_factory=list)


class HolisticVerdict(_Compliant):
    """The Input Analyze / Holistic Agent's evaluation and disambiguation decision.

    clarity:
      "clear"      — Input is complete and target reference is clear/unambiguous.
      "no_target"  — Request needs no target resolution (e.g. adding unreferenced item).
      "ambiguous"  — 2+ adjacent cell-pairs matched, or referenced tag is duplicated.
      "blocked"    — Critical engineering prerequisites (Class B) are missing.
    """
    clarity: str = "clear"
    resolved_target: dict | None = None      # single pair/node, when clarity == "clear"
    candidates: list[dict] = Field(default_factory=list)   # when ambiguous
    tags: list[str] = Field(default_factory=list)   # extracted tag references
    reason: str = ""
    inferred_plant_type: str = ""           # Process/unit type (e.g. "Catalytic Reactor Train with Knockout Separation")
    unit_operations: list[str] = Field(default_factory=list) # Sequenced process stages
    inferred_control_strategy: str = ""     # High-level control and safety objectives
    engineering_completeness: dict = Field(default_factory=dict)
    critical_missing: list[dict] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    gap_resolution: list[dict] = Field(default_factory=list)
    solution_design: dict | None = None


class InputAnalysisResult(_Compliant):
    """Parsed structured response from the Input Analyze LLM evaluation."""
    inferred_plant_type: str = ""
    unit_operations: list[str] = Field(default_factory=list)
    inferred_control_strategy: str = ""
    engineering_completeness: dict = Field(default_factory=dict)
    reasoning: str = ""
    critical_missing: list[dict] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    gap_resolution: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class InstrumentSpecifications(_Compliant):
    tag_number: str = ""
    asset_name: str = ""
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    calibrated_range: str = ""
    protocol: str = "4-20mA HART 7"
    connected_system: str = "Cabinet PNL-01"
    location: str = ""


class HARTIdentity(_Compliant):
    equipment_category: str = ""
    hart_tag: str = ""
    hart_long_tag: str = ""
    message: str = ""
    descriptor: str = ""


class PVMapping(_Compliant):
    primary_variable: str = ""
    secondary_variable: str = ""
    tertiary_variable: str = ""
    quaternary_variable: str = ""
    urv: str = ""
    lrv: str = ""
    pv_units: str = ""


class MeasurementControl(_Compliant):
    flow_direction: str = "Forward Only"
    damping: str = "0.5 s"


class InstrumentConfig(_Compliant):
    hart_identity: HARTIdentity = Field(default_factory=HARTIdentity)
    pv_mapping: PVMapping = Field(default_factory=PVMapping)
    measurement_control: MeasurementControl = Field(default_factory=MeasurementControl)


class ConfiguredAsset(_Compliant):
    tag: str = ""
    name: str = ""
    category: str = ""
    purpose: str = ""
    specifications: InstrumentSpecifications = Field(default_factory=InstrumentSpecifications)
    instrument_config: InstrumentConfig = Field(default_factory=InstrumentConfig)
