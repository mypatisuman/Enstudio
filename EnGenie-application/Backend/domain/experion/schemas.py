"""
Experion PKS (C300 / CEE) Data Schemas.
Models for Honeywell Control Modules, Function Blocks, Wire Interconnects,
and OPC UA runtime communication.
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ExperionBlockParam(BaseModel):
    """Parameter of an Experion Function Block (e.g. PV, SP, OP, PVEUHI, GAIN)."""
    model_config = ConfigDict(extra="ignore")
    name: str
    value: Any
    data_type: str = "REAL"  # REAL, BOOLEAN, ENUM, STRING, INTEGER
    description: str = ""
    is_tunable: bool = False
    is_connectable: bool = True


class ExperionBlock(BaseModel):
    """
    Honeywell Experion CEE Function Block within a Control Module.
    Common types:
    - DATAACQ: Analog Input acquisition / signal conditioning
    - PID / PIDFF: Regulatory control block (Standard or Feedforward)
    - AO: Analog Output / Valve positioning
    - DEVCTL: Device Control block (pumps, motors, on/off valves)
    - DIGACQ: Digital Input acquisition (switches, contacts)
    - PIDERG: Enhanced regulatory control block
    """
    model_config = ConfigDict(extra="ignore")
    tag: str = Field(description="Block tag name, e.g. 'FIC101_PID' or 'FT101_AI'")
    block_type: Literal["DATAACQ", "PID", "PIDFF", "AO", "DEVCTL", "DIGACQ", "FLAG", "NUMERIC"] = "PID"
    description: str = Field(default="", description="Block description")
    execution_order: int = Field(default=1, description="Execution sequence inside CM")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Block parameters")
    source_instrument_tag: str | None = Field(default=None, description="Original ISA-5.1 P&ID tag")
    source_node_id: str | None = Field(default=None, description="Originating node ID in PIDGraph")


class ExperionWire(BaseModel):
    """Internal signal wire connection between block pins within a Control Module."""
    model_config = ConfigDict(extra="ignore")
    from_block: str = Field(description="Source block tag, e.g. 'FT101_AI'")
    from_param: str = Field(description="Source pin name, e.g. 'PV' or 'OUT'")
    to_block: str = Field(description="Destination block tag, e.g. 'FIC101_PID'")
    to_param: str = Field(description="Destination pin name, e.g. 'PV' or 'IN'")


class ExperionControlModule(BaseModel):
    """
    Honeywell Experion CEE Control Module (CM).
    Represents an autonomous regulatory loop, cascade loop, or equipment module
    assigned to a C300 controller execution environment.
    """
    model_config = ConfigDict(extra="ignore")
    cm_name: str = Field(description="Control Module tag name, e.g. 'CM_FIC101' or 'CM_P101'")
    loop_type: Literal["FLOW", "TEMPERATURE", "PRESSURE", "LEVEL", "CASCADE", "DISCRETE_EQUIPMENT", "SAFETY_INTERLOCK", "GENERAL"] = "GENERAL"
    description: str = Field(default="", description="Loop or module description")
    controller: str = Field(default="CEE01_C300", description="Target C300 controller tag")
    period_ms: int = Field(default=100, description="Execution period in milliseconds (50, 100, 200, 500, 1000)")
    blocks: list[ExperionBlock] = Field(default_factory=list, description="Contained CEE function blocks")
    wires: list[ExperionWire] = Field(default_factory=list, description="Inter-block parameter connections")
    primary_pv_tag: str | None = Field(default=None, description="Primary PV transmitter tag")
    primary_sp_tag: str | None = Field(default=None, description="Primary controller tag")
    primary_op_tag: str | None = Field(default=None, description="Final control element tag")


class ExperionStrategy(BaseModel):
    """Complete Experion DCS architecture inferred from P&ID."""
    model_config = ConfigDict(extra="ignore")
    target_controller: str = Field(default="CEE01_C300", description="Honeywell C300 Process Controller ID")
    cee_version: str = Field(default="R520.1", description="Experion PKS CEE Software Release")
    project_title: str = Field(default="EnGenie Experion C300 Strategy", description="Project Name")
    control_modules: list[ExperionControlModule] = Field(default_factory=list, description="Inferred Control Modules")
    total_loops: int = Field(default=0)
    total_blocks: int = Field(default=0)
    total_io_points: int = Field(default=0)
    summary: str = Field(default="")


class OPCTagValue(BaseModel):
    """Live runtime value of an Experion tag/parameter."""
    model_config = ConfigDict(extra="ignore")
    tag: str
    parameter: str  # PV, SP, OP, MODE, ALMSTAT
    value: Any
    status: str = "Good"  # Good, Bad, Uncertain
    timestamp: str | None = None
    units: str | None = None


class OPCConnectionConfig(BaseModel):
    """OPC UA connection configuration to Honeywell Experion OPC Server."""
    model_config = ConfigDict(extra="ignore")
    endpoint_url: str = Field(default="opc.tcp://localhost:4840", description="Experion OPC UA Server URL")
    security_policy: str = Field(default="None", description="None, Basic256Sha256")
    username: str | None = None
    password: str | None = None
    simulation_mode: bool = Field(default=True, description="Use built-in loop simulator if server unreachable")


class OPCWriteRequest(BaseModel):
    """Request to update a setpoint, mode, or output on an Experion loop."""
    model_config = ConfigDict(extra="ignore")
    cm_name: str
    block_tag: str
    parameter: str  # SP, MODE, OP
    value: Any
