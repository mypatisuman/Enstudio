"""
Solution Workflow Schemas

Pydantic models for the solution workflow's LLM structured outputs
and API request/response shapes.
"""
import logging
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Product Hierarchy Entity Models (Instrument → Specifications → Parameter → Device)
# ---------------------------------------------------------------------------

class ParameterLevel(str, Enum):
    required = "Required"
    optional = "Optional"
    advanced = "Advanced"


class Parameter(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(description="Unique parameter identifier")
    name: str = Field(description="Parameter name")
    value: str | None = Field(default=None, description="Parameter value")
    level: ParameterLevel = Field(description="Required / Optional / Advanced")
    units: str | None = Field(default=None, description="Unit of measurement (e.g. V, HZ)")


class Specifications(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(description="Unique specifications identifier")
    safety: list[Parameter] = Field(default_factory=list)
    electrical: list[Parameter] = Field(default_factory=list)
    mechanical: list[Parameter] = Field(default_factory=list)
    process: list[Parameter] = Field(default_factory=list)
    environmental: list[Parameter] = Field(default_factory=list)
    performance: list[Parameter] = Field(default_factory=list)
    certifications: list[Parameter] = Field(default_factory=list)
    other: list[Parameter] = Field(default_factory=list)


class Device(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(description="Unique device identifier")
    oem: str = Field(description="Original equipment manufacturer")
    model_series: str = Field(description="Product model series")
    model_number: str = Field(description="Specific model number / SKU")
    specs_doc_id: str | None = Field(default=None, description="Reference to the source specs document")


class Instrument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(description="Unique instrument identifier")
    name: str = Field(description="Instrument display name")
    type: Literal["Equipment", "Accessory"] = Field(description="Equipment or Accessory")
    specifications: Specifications | None = Field(default=None, description="Empty / null for accessories without spec blocks")
    level: Literal["L0", "L1", "L2", "L3"] = Field(description="Hierarchy depth level")
    parent_id: str | None = Field(default=None, description="Parent instrument id (null for root instruments)")
    device: Device | None = Field(default=None, description="Matched physical device; null until product search resolves it")


class InstrumentSpec(BaseModel):
    name: str = Field(description="Instrument name or type")
    tag: str = Field(default="", description="Instrument tag number")
    requirements: dict[str, Any] = Field(default_factory=dict, description="Technical requirements")
    standards: list[str] = Field(default_factory=list, description="Applicable engineering standards")


class AccessorySpec(BaseModel):
    name: str = Field(description="Accessory name or type")
    requirements: dict[str, Any] = Field(default_factory=dict, description="Technical requirements")
    standards: list[str] = Field(default_factory=list, description="Applicable engineering standards")
    parent_instrument_category: str = Field(default="", description="Category of the parent instrument this accessory supports")


class ComponentRole(BaseModel):
    """Purpose/role of a single instrument or accessory within the designed solution."""
    model_config = ConfigDict(extra="ignore")
    name: str = Field(default="", description="Component name (product or category)")
    category: str = Field(default="", description="Generic component category")
    purpose: str = Field(default="", description="Why this component is part of the solution")


# ---------------------------------------------------------------------------
# P&ID Graph Models (ISA-5.1 / ISO 10628 Topological Diagram)
# ---------------------------------------------------------------------------

class PIDNode(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(description="Unique node identifier, e.g. 'n1', 'n2'")
    label: str = Field(description="ISA-5.1 tag or equipment label, e.g. 'PT-101', 'PCV-101', 'V-101'")
    kind: str = Field(default="transmitter", description="Node type: vessel, pump, heat_exchanger, column, reactor, filter, valve, checkvalve, relief, transmitter, controller, switch, indicator, off_page_connector, junction, tie_in")
    description: str = Field(default="", description="Functional description of the node")
    area: str = Field(default="", description="Process area or sub-system name")
    subsystem_id: str | None = Field(default=None, description="Sub-system identifier")
    is_tie_in: bool = Field(default=False, description="Whether node is a brownfield tie-in point")
    tie_in_label: str | None = Field(default=None, description="Tie-in point tag, e.g. 'TP-01'")
    vendor: str | None = Field(default=None, description="Vendor / OEM name, e.g. Emerson, Yokogawa, Fisher, Endress+Hauser")
    model_family: str | None = Field(default=None, description="L3 Model Family, e.g. Rosemount 3051 Series, EJX Series")
    model_series: str | None = Field(default=None, description="L4 Model Series / Product Name, e.g. 3051CD Differential Pressure Transmitter")
    model_number: str | None = Field(default=None, description="Model number SKU / catalog code")
    standards: list[str] = Field(default_factory=list, description="Applicable engineering standards, e.g. ASME B16.5, IEC 61508 SIL-2")
    parent_instrument_tag: str | None = Field(default=None, description="Parent instrument tag, e.g. PT-101 for an accessory like MNF-101")
    parent_instrument_id: str | None = Field(default=None, description="Parent instrument ID if inline accessory")
    specifications: dict[str, Any] = Field(default_factory=dict, description="Key engineering parameters / specs")
    categorized_specs: dict[str, Any] = Field(default_factory=dict, description="Categorized specifications (process, mechanical, electrical, safety, certifications)")
    x: float | None = Field(default=None, description="X coordinate on 2D canvas")
    y: float | None = Field(default=None, description="Y coordinate on 2D canvas")
    # Provenance and package membership. These must survive model_dump: the
    # graph returns as active_pid_graph on the next turn, and the retrofit
    # tools rely on them to avoid duplicating loops and to group loop members.
    spec_status: str | None = Field(
        default=None,
        description="Where the specifications came from: asset_inventory (the user's "
                    "Assets Table), stated (the engineer), bom_selection (this project's "
                    "BOM), or unspecified (nothing known; never invented)")
    instrument_config: dict[str, Any] = Field(default_factory=dict, description="HART identity and PV mapping from the Assets Table")
    loop: str | None = Field(default=None, description="ISA loop number this node belongs to")
    package: str | None = Field(default=None, description="Instrument package that built this node: pressure, temperature, flow or level")
    package_role: str | None = Field(default=None, description="Role within the package, e.g. transmitter, manifold, control_valve")
    package_anchor: str | None = Field(default=None, description="Tag of the process node the package taps")


class PIDEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    from_id: str = Field(alias="from", description="Source node id or tag")
    to_id: str = Field(alias="to", description="Destination node id or tag")
    kind: Literal["stream", "impulse", "signal", "pneumatic", "relief", "utility", "bypass", "recycle"] = Field(
        default="stream", description="Edge type"
    )
    label: str = Field(default="", description="Line designation or signal type, e.g. 3\"-STM-1001-A1B or 4-20mA HART")
    fluid: str = Field(default="", description="Process fluid")
    line_size: str = Field(default="", description="Line size")


class PIDLayoutCell(BaseModel):
    model_config = ConfigDict(extra="ignore")
    row: int = Field(description="Grid row index")
    col: int = Field(description="Grid col index")
    node_id: str = Field(description="Node ID")
    tag: str = Field(description="Node tag")


class PIDSubsystemArea(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(description="Unique area identifier, e.g. 'area_10'")
    name: str = Field(description="Sub-system name, e.g. 'Feedwater Cascade Control'")
    x: float = Field(default=0.0, description="Bounding box top-left X coordinate")
    y: float = Field(default=0.0, description="Bounding box top-left Y coordinate")
    width: float = Field(default=0.0, description="Bounding box width")
    height: float = Field(default=0.0, description="Bounding box height")
    node_ids: list[str] = Field(default_factory=list, description="List of node IDs in this sub-system")


class PIDLayout(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rows: int = Field(default=0, description="Total rows in grid")
    cols: int = Field(default=0, description="Total columns in grid")
    cells: list[PIDLayoutCell] = Field(default_factory=list, description="Positioned cells")
    subsystem_areas: list[PIDSubsystemArea] = Field(default_factory=list, description="Sub-system bounding areas")


class PIDGraph(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_type: Literal["greenfield", "brownfield"] = Field(
        default="greenfield", description="Project type: greenfield (clean-sheet) or brownfield (retrofit/tie-ins)"
    )
    nodes: list[PIDNode] = Field(default_factory=list, description="P&ID nodes")
    edges: list[PIDEdge] = Field(default_factory=list, description="P&ID edges")
    layout: PIDLayout = Field(default_factory=PIDLayout, description="Computed 2D grid layout")
    subsystem_areas: list[PIDSubsystemArea] = Field(default_factory=list, description="Sub-system bounding areas")
    summary: str = Field(default="", description="Summary of P&ID topology")
    svg_preview: str | None = Field(default=None, description="Pre-rendered SVG preview")
    generation_path: str | None = Field(default=None, description="tool_loop (the agent built it) or fallback (deterministic build)")
    validation: dict[str, Any] = Field(default_factory=dict, description="Drawing quality: orphans, duplicate tags, score, loop status")
    spec_status_counts: dict[str, int] = Field(default_factory=dict, description="Node count per specification provenance")
    notes: list[str] = Field(default_factory=list, description="What a modification left alone, and why")
    pending_action: dict[str, Any] | None = Field(
        default=None,
        description="An engineer decision this drawing is waiting on: kind confirm_delete "
                    "(queued deletions, applied by POST /api/pid/confirm) or subsystem_choice "
                    "(which subsystem a retrofit goes into, answered by POST /api/pid/clarify)")
    session_id: str | None = Field(default=None, description="Solution session this drawing is persisted under")
    revision: int | None = Field(default=None, description="Persisted revision number; confirm/clarify requests must name it")


class DesignedSolution(BaseModel):
    """Optimized engineering solution produced by the standalone solution-build agent.

    This is a higher-level, reasoned design artifact (objectives, component purposes,
    design narrative, recommendations, and topological P&ID graph) returned alongside the BOM.
    """
    model_config = ConfigDict(extra="ignore")
    project_objective: str = Field(default="", description="Inferred overall goal of the system")
    design_overview: str = Field(default="", description="Optimized engineering solution narrative")
    component_roles: list[ComponentRole] = Field(default_factory=list, description="Purpose/role of each component")
    optimizations: list[str] = Field(default_factory=list, description="Best-practice / improvement recommendations")
    design_considerations: list[str] = Field(default_factory=list, description="Safety, standards, operability, redundancy notes")
    assumptions: list[str] = Field(default_factory=list, description="Engineering assumptions made")
    pid_graph: PIDGraph | None = Field(default=None, description="Topological P&ID graph generated for this solution")


class SolutionRequest(BaseModel):
    user_input: str = Field(description="User's instrument identification request")
    session_id: str = Field(default="default", description="Conversation session identifier")
    user_id: int | None = Field(default=None, description="Authenticated user ID")
    stream_id: str | None = Field(default=None, description="SSE stream ID for live progress")
    skip_standards: bool = Field(default=False, description="Skip standards application")
    current_instruments: list[dict[str, Any]] = Field(default_factory=list, description="Existing instruments to modify")
    current_accessories: list[dict[str, Any]] = Field(default_factory=list, description="Existing accessories to modify")


class SolutionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool
    intent: str | None = Field(default=None, description="Detected project intent (identify/modify/router_needed)")
    input_range: str | None = Field(default=None, description="Input range (short|mid|long)")
    response_type: str | None = Field(default=None, description="Type of response being returned")
    project_name: str = Field(default="", description="Extracted project name")
    message: str = Field(default="", description="Human-readable response message")
    summary: str = Field(default="", description="Summary of identified instruments/changes")
    instruments: list[dict[str, Any]] = Field(default_factory=list, description="Identified instruments")
    accessories: list[dict[str, Any]] = Field(default_factory=list, description="Identified accessories")
    sub_systems: list[dict[str, Any]] = Field(default_factory=list, description="Identified project sub-systems")
    awaiting_confirmation: bool = Field(default=False, description="Whether agent is awaiting user confirmation")
    # Must be declared here: model_config=extra='ignore' drops any undeclared key during
    # ensure_compliant(), which would otherwise strip this before the frontend can round-trip it.
    awaiting_holistic_confirmation: bool = Field(default=False, description="Whether the holistic agent awaits the user's reply to gap questions / proceed confirmation")
    refinement_applied: bool = Field(default=False, description="True when this turn incrementally refined the existing solution (post-build refinement window)")
    engineering_completeness: dict[str, Any] | None = Field(default=None, description="Engineering completeness scores + remaining_gaps from the holistic agent's latest evaluation")
    consolidated_requirements: str | None = Field(default=None, description="The gate-consolidated requirement (original + chat-supplied answers) when consolidation happened this turn")
    is_empty_result: bool = Field(default=False, description="True if no instruments or accessories were identified")
    identification_warning: str | None = Field(default=None, description="Warning when identification yields no results")
    clarification_needed: bool = Field(default=False, description="Whether agent needs more info from user")
    clarification_questions: list[str] = Field(default_factory=list, description="Questions to ask the user")
    clarification_context: dict[str, Any] = Field(default_factory=dict, description="Context for clarification")
    open_dashboard: bool = Field(default=False, description="Whether to open the dashboard after response")
    sample_input: str = Field(default="", description="Sample input suggestion for the user")
    standards_applied: bool = Field(default=False, description="Whether engineering standards were applied")
    # Designed solution from the standalone parallel solution-build agent (requirements intent).
    # Must be declared here: model_config=extra='ignore' drops any undeclared key during
    # ensure_compliant(), which would otherwise strip this before it reaches the UI.
    designed_solution: DesignedSolution | None = Field(default=None, description="Optimized engineering solution (objectives, component purposes, design)")
    pid_graph: PIDGraph | None = Field(default=None, description="Topological P&ID diagram with nodes, edges, grid layout and SVG")
    agent_path: list[str] = Field(default_factory=list, description="Internal agent execution path for debugging")
    # changes_made is a list of change descriptions for modification intents
    # (it may also be a dict for legacy/structured summaries).
    changes_made: list[Any] | dict[str, Any] | None = Field(default=None, description="Summary of changes (modification intent only)")
    warnings: list[str] | None = Field(default=None, description="Non-fatal warnings from the agent")
    # Router redirect fields (intent=router_needed only)
    router_category: str | None = Field(default=None, description="Router category for redirect")
    router_target_page: str | None = Field(default=None, description="Target page for redirect")
    router_requires_routing: bool = Field(default=False, description="Whether a page redirect is required")
    router_url: str = Field(default="", description="Target URL for redirect")
    # Error field
    error: str | None = Field(default=None, description="Error message if success=False")

    @classmethod
    def ensure_compliant(cls, response: dict[str, Any]) -> dict[str, Any]:
        """Validate & normalize a raw solution-workflow response against this object
        model so the workflow output always conforms to the published contract:
        correct field types, defaults filled in, and unknown keys dropped
        (model_config extra='ignore') so the output strictly mirrors the schema.

        Returns a model-normalized dict. If the response cannot be coerced to the
        model, logs the violation and returns the raw dict unchanged so the
        workflow never fails purely on output formatting.
        """
        if not isinstance(response, dict):
            logger.error("[SolutionResponse] Output is %s, not a dict — cannot enforce object model.", type(response).__name__)
            return response
        try:
            return cls.model_validate(response).model_dump(exclude_none=True)
        except Exception as exc:  # noqa: BLE001
            logger.error("[SolutionResponse] Output not compliant with object model: %s", exc)
            return response

    @classmethod
    def is_compliant(cls, response: dict[str, Any]) -> bool:
        """Return True if *response* already conforms to the object model."""
        if not isinstance(response, dict):
            return False
        try:
            cls.model_validate(response)
            return True
        except Exception:  # noqa: BLE001
            return False
