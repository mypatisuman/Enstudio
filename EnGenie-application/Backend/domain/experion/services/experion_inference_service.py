"""
Honeywell Experion PKS (C300 CEE) Inference Service.
Parses an ISA-5.1 PIDGraph, reconstructs process control loops and interlocks,
and synthesizes Experion Control Modules (CMs), Function Blocks, and Wire Interconnects.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from domain.experion.schemas import (
    ExperionBlock,
    ExperionControlModule,
    ExperionStrategy,
    ExperionWire,
)
from domain.solution.services.isa_classifier import parse_isa_tag

logger = logging.getLogger(__name__)


# Standard default tuning parameters by process variable type for Honeywell C300 CEE
DEFAULT_PID_TUNING = {
    "FLOW": {
        "GAIN": 0.8,
        "TI": 0.05,  # 3 seconds reset
        "TD": 0.0,
        "ACTION": "REVERSE",
        "PERIOD_MS": 100,
    },
    "TEMPERATURE": {
        "GAIN": 2.5,
        "TI": 2.0,   # 120 seconds reset
        "TD": 0.5,   # 30 seconds derivative
        "ACTION": "REVERSE",
        "PERIOD_MS": 500,
    },
    "PRESSURE": {
        "GAIN": 1.5,
        "TI": 0.2,   # 12 seconds reset
        "TD": 0.0,
        "ACTION": "DIRECT",
        "PERIOD_MS": 100,
    },
    "LEVEL": {
        "GAIN": 2.0,
        "TI": 5.0,   # 300 seconds reset (averaging level control)
        "TD": 0.0,
        "ACTION": "REVERSE",
        "PERIOD_MS": 200,
    },
    "GENERAL": {
        "GAIN": 1.0,
        "TI": 1.0,
        "TD": 0.0,
        "ACTION": "REVERSE",
        "PERIOD_MS": 200,
    },
}

DEFAULT_RANGES = {
    "FLOW": {"LRV": 0.0, "URV": 100.0, "EU": "m3/h"},
    "TEMPERATURE": {"LRV": 0.0, "URV": 200.0, "EU": "degC"},
    "PRESSURE": {"LRV": 0.0, "URV": 10.0, "EU": "bar"},
    "LEVEL": {"LRV": 0.0, "URV": 100.0, "EU": "%"},
    "ANALYSIS": {"LRV": 0.0, "URV": 14.0, "EU": "pH"},
    "GENERAL": {"LRV": 0.0, "URV": 100.0, "EU": "%"},
}


def _clean_tag_name(raw: str) -> str:
    """Sanitize tag into standard Experion point name format (e.g. FIC-101 -> FIC101)."""
    return re.sub(r"[^A-Za-z0-9_]", "", raw.replace("-", "").strip())


def _infer_loop_type(var_letter: str) -> str:
    mapping = {
        "F": "FLOW",
        "T": "TEMPERATURE",
        "P": "PRESSURE",
        "L": "LEVEL",
        "A": "ANALYSIS",
        "Q": "ANALYSIS",
        "S": "SPEED",
        "W": "WEIGHT",
    }
    return mapping.get(var_letter.upper(), "GENERAL")


def infer_experion_strategy(
    pid_graph_data: dict[str, Any],
    controller_name: str = "CEE01_C300",
) -> ExperionStrategy:
    """
    Main entry point: Transforms a PIDGraph dictionary into a complete
    Honeywell Experion PKS C300 Strategy containing Control Modules, CEE Blocks,
    and pin wiring.
    """
    nodes = pid_graph_data.get("nodes", [])
    edges = pid_graph_data.get("edges", [])
    subsystem_areas = pid_graph_data.get("subsystem_areas", []) or pid_graph_data.get("subsystemAreas", [])

    # Index nodes by id and by tag
    nodes_by_id: dict[str, dict[str, Any]] = {n.get("id"): n for n in nodes if n.get("id")}
    nodes_by_tag: dict[str, dict[str, Any]] = {n.get("label"): n for n in nodes if n.get("label")}

    # Build adjacency
    incoming_edges: dict[str, list[dict[str, Any]]] = {}
    outgoing_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        from_id = edge.get("from") or edge.get("from_id")
        to_id = edge.get("to") or edge.get("to_id")
        if from_id:
            outgoing_edges.setdefault(from_id, []).append(edge)
        if to_id:
            incoming_edges.setdefault(to_id, []).append(edge)

    # Classify nodes into functional roles
    controllers: list[dict[str, Any]] = []
    transmitters: list[dict[str, Any]] = []
    valves: list[dict[str, Any]] = []
    equipment: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []

    for n in nodes:
        label = (n.get("label") or "").upper()
        kind = (n.get("kind") or "").lower()
        parsed = parse_isa_tag(label)
        first_char = parsed.get("first_letter") or (label[0] if label else "")
        fn = parsed.get("function_letters") or ""

        if kind in ("pump", "vessel", "heat_exchanger", "column", "reactor", "filter", "tank"):
            equipment.append(n)
        elif "C" in fn or "controller" in kind:
            controllers.append(n)
        elif "T" in fn or "transmitter" in kind:
            transmitters.append(n)
        elif "V" in fn or kind in ("valve", "checkvalve", "relief"):
            valves.append(n)
        elif "S" in fn or "switch" in kind:
            switches.append(n)
        elif "indicator" in kind or "I" in fn:
            transmitters.append(n)

    control_modules: list[ExperionControlModule] = []
    claimed_node_ids: set[str] = set()

    # -----------------------------------------------------------------------
    # 1. Synthesize Regulatory Control Loops (Controllers: PIC, TIC, FIC, LIC)
    # -----------------------------------------------------------------------
    for c_node in controllers:
        c_id = c_node.get("id")
        c_tag = c_node.get("label", "")
        claimed_node_ids.add(c_id)

        parsed_c = parse_isa_tag(c_tag)
        loop_num = parsed_c.get("loop_number") or re.search(r"\d+", c_tag)
        loop_num_str = loop_num.group(0) if hasattr(loop_num, "group") else (str(loop_num) if loop_num else "")
        var_letter = parsed_c.get("first_letter") or (c_tag[0] if c_tag else "F")
        loop_type = _infer_loop_type(var_letter)
        tuning = DEFAULT_PID_TUNING.get(loop_type, DEFAULT_PID_TUNING["GENERAL"])
        ranges = DEFAULT_RANGES.get(loop_type, DEFAULT_RANGES["GENERAL"])

        # Extract node specs if provided
        specs = c_node.get("specifications") or {}
        cat_specs = c_node.get("categorized_specs") or {}
        process_specs = cat_specs.get("process", {})

        # Find connected Transmitter (input to controller)
        tx_node: dict[str, Any] | None = None
        # Check direct incoming signal edges
        for in_edge in incoming_edges.get(c_id, []):
            src_id = in_edge.get("from") or in_edge.get("from_id")
            if src_id in nodes_by_id:
                cand = nodes_by_id[src_id]
                if cand in transmitters:
                    tx_node = cand
                    break

        # Fallback by loop number match (e.g. FT-101 matches FIC-101)
        if not tx_node:
            for t in transmitters:
                if loop_num_str and loop_num_str in t.get("label", ""):
                    tx_node = t
                    break

        # Find connected Final Control Element / Valve (output from controller)
        v_node: dict[str, Any] | None = None
        for out_edge in outgoing_edges.get(c_id, []):
            dest_id = out_edge.get("to") or out_edge.get("to_id")
            if dest_id in nodes_by_id:
                cand = nodes_by_id[dest_id]
                if cand in valves:
                    v_node = cand
                    break

        # Fallback by loop number match (e.g. FV-101 matches FIC-101)
        if not v_node:
            for v in valves:
                if loop_num_str and loop_num_str in v.get("label", ""):
                    v_node = v
                    break

        cm_tag = f"CM_{_clean_tag_name(c_tag)}"
        blocks: list[ExperionBlock] = []
        wires: list[ExperionWire] = []

        # Read range parameters from specs if present
        lrv = float(specs.get("LRV") or process_specs.get("LRV") or ranges["LRV"])
        urv = float(specs.get("URV") or process_specs.get("URV") or ranges["URV"])
        eu = str(specs.get("Units") or process_specs.get("Units") or ranges["EU"])
        default_sp = round(lrv + (urv - lrv) * 0.5, 2)

        # 1a. Input Block (DATAACQ)
        ai_tag = f"{_clean_tag_name(tx_node.get('label') if tx_node else c_tag)}_AI"
        if tx_node:
            claimed_node_ids.add(tx_node.get("id"))
            tx_specs = tx_node.get("specifications") or {}
            lrv = float(tx_specs.get("LRV") or lrv)
            urv = float(tx_specs.get("URV") or urv)
            eu = str(tx_specs.get("Units") or eu)

        span = urv - lrv
        blocks.append(
            ExperionBlock(
                tag=ai_tag,
                block_type="DATAACQ",
                description=f"Analog Input signal acquisition for {tx_node.get('label') if tx_node else c_tag}",
                execution_order=1,
                source_instrument_tag=tx_node.get("label") if tx_node else None,
                source_node_id=tx_node.get("id") if tx_node else None,
                parameters={
                    "PV": default_sp,
                    "PVEUHI": urv,
                    "PVEULO": lrv,
                    "EUDESC": eu,
                    "TF": 1.0,  # 1.0 sec filter time constant
                    "HIGH_HIGH_LIMIT": round(urv - 0.05 * span, 2),
                    "HIGH_LIMIT": round(urv - 0.15 * span, 2),
                    "LOW_LIMIT": round(lrv + 0.15 * span, 2),
                    "LOW_LOW_LIMIT": round(lrv + 0.05 * span, 2),
                    "ALMSTAT": "NORMAL",
                },
            )
        )

        # 1b. Regulatory PID Block
        pid_tag = f"{_clean_tag_name(c_tag)}_PID"
        blocks.append(
            ExperionBlock(
                tag=pid_tag,
                block_type="PID",
                description=f"Regulatory PID loop controller for {c_tag}",
                execution_order=2,
                source_instrument_tag=c_tag,
                source_node_id=c_id,
                parameters={
                    "PV": default_sp,
                    "SP": default_sp,
                    "OP": 50.0,
                    "MODE": "AUTO",
                    "PVEUHI": urv,
                    "PVEULO": lrv,
                    "EUDESC": eu,
                    "OPHI": 100.0,
                    "OPLO": 0.0,
                    "OPEU": "%",
                    "ACTION": tuning["ACTION"],
                    "GAIN": tuning["GAIN"],
                    "TI": tuning["TI"],
                    "TD": tuning["TD"],
                },
            )
        )

        # 1c. Output Block (AO)
        ao_tag = f"{_clean_tag_name(v_node.get('label') if v_node else c_tag)}_AO"
        if v_node:
            claimed_node_ids.add(v_node.get("id"))
            fail_action = (v_node.get("specifications") or {}).get("Fail_Position", "FAIL_CLOSE")
        else:
            fail_action = "FAIL_CLOSE"

        blocks.append(
            ExperionBlock(
                tag=ao_tag,
                block_type="AO",
                description=f"Analog Output signal conditioning for {v_node.get('label') if v_node else 'Control Valve'}",
                execution_order=3,
                source_instrument_tag=v_node.get("label") if v_node else None,
                source_node_id=v_node.get("id") if v_node else None,
                parameters={
                    "OPD": 50.0,
                    "OP": 50.0,
                    "OPHI": 100.0,
                    "OPLO": 0.0,
                    "OPEU": "%",
                    "FAILACT": fail_action,
                },
            )
        )

        # 1d. Wire inter-block pins
        wires.append(ExperionWire(from_block=ai_tag, from_param="PV", to_block=pid_tag, to_param="PV"))
        wires.append(ExperionWire(from_block=pid_tag, from_param="OP", to_block=ao_tag, to_param="OPD"))

        control_modules.append(
            ExperionControlModule(
                cm_name=cm_tag,
                loop_type=loop_type,  # type: ignore
                description=f"{loop_type.capitalize()} Control Loop ({c_tag})",
                controller=controller_name,
                period_ms=tuning["PERIOD_MS"],
                blocks=blocks,
                wires=wires,
                primary_pv_tag=tx_node.get("label") if tx_node else None,
                primary_sp_tag=c_tag,
                primary_op_tag=v_node.get("label") if v_node else None,
            )
        )

    # -----------------------------------------------------------------------
    # 2. Standalone Monitoring Transmitters (Indicators, Untied Sensors)
    # -----------------------------------------------------------------------
    for t in transmitters:
        t_id = t.get("id")
        if t_id in claimed_node_ids:
            continue
        claimed_node_ids.add(t_id)
        t_tag = t.get("label", "")
        parsed_t = parse_isa_tag(t_tag)
        var_letter = parsed_t.get("first_letter") or (t_tag[0] if t_tag else "T")
        loop_type = _infer_loop_type(var_letter)
        ranges = DEFAULT_RANGES.get(loop_type, DEFAULT_RANGES["GENERAL"])

        specs = t.get("specifications") or {}
        lrv = float(specs.get("LRV") or ranges["LRV"])
        urv = float(specs.get("URV") or ranges["URV"])
        eu = str(specs.get("Units") or ranges["EU"])
        span = urv - lrv
        ai_tag = f"{_clean_tag_name(t_tag)}_AI"

        cm = ExperionControlModule(
            cm_name=f"CM_{_clean_tag_name(t_tag)}",
            loop_type=loop_type,  # type: ignore
            description=f"Process Monitoring — {t_tag} ({t.get('description', '')})",
            controller=controller_name,
            period_ms=200,
            blocks=[
                ExperionBlock(
                    tag=ai_tag,
                    block_type="DATAACQ",
                    description=f"Process Variable Acquisition for {t_tag}",
                    execution_order=1,
                    source_instrument_tag=t_tag,
                    source_node_id=t_id,
                    parameters={
                        "PV": round(lrv + span * 0.45, 2),
                        "PVEUHI": urv,
                        "PVEULO": lrv,
                        "EUDESC": eu,
                        "TF": 1.0,
                        "HIGH_HIGH_LIMIT": round(urv - 0.05 * span, 2),
                        "HIGH_LIMIT": round(urv - 0.15 * span, 2),
                        "LOW_LIMIT": round(lrv + 0.15 * span, 2),
                        "LOW_LOW_LIMIT": round(lrv + 0.05 * span, 2),
                        "ALMSTAT": "NORMAL",
                    },
                )
            ],
            wires=[],
            primary_pv_tag=t_tag,
        )
        control_modules.append(cm)

    # -----------------------------------------------------------------------
    # 3. Discrete Equipment & Motor Drives (Pumps, Agitators, Blowers)
    # -----------------------------------------------------------------------
    for eq in equipment:
        eq_id = eq.get("id")
        eq_tag = eq.get("label", "")
        kind = (eq.get("kind") or "").lower()
        if kind in ("pump", "compressor", "agitator", "blower") or eq_tag.upper().startswith(("P-", "P_", "PU-", "M-", "C-")):
            claimed_node_ids.add(eq_id)
            dev_tag = f"{_clean_tag_name(eq_tag)}_DEV"
            cm = ExperionControlModule(
                cm_name=f"CM_{_clean_tag_name(eq_tag)}",
                loop_type="DISCRETE_EQUIPMENT",
                description=f"Motorized Equipment Control — {eq_tag} ({eq.get('description', '')})",
                controller=controller_name,
                period_ms=100,
                blocks=[
                    ExperionBlock(
                        tag=dev_tag,
                        block_type="DEVCTL",
                        description=f"Device Control Block for {eq_tag}",
                        execution_order=1,
                        source_instrument_tag=eq_tag,
                        source_node_id=eq_id,
                        parameters={
                            "STATE": "RUNNING",
                            "COMMAND": "START",
                            "MODE": "AUTO",
                            "RUN_DI": True,
                            "TRIP_DI": False,
                            "START_DO": True,
                            "STOP_DO": False,
                            "FAIL_TO_START_TIMER": 5.0,
                            "INTERLOCK_OK": True,
                        },
                    )
                ],
                wires=[],
                primary_op_tag=eq_tag,
            )
            control_modules.append(cm)

    # -----------------------------------------------------------------------
    # 4. Safety Switches & Interlocks (PSH, PSL, TSH, TSL, ESD valves)
    # -----------------------------------------------------------------------
    for sw in switches:
        sw_id = sw.get("id")
        sw_tag = sw.get("label", "")
        if sw_id in claimed_node_ids:
            continue
        claimed_node_ids.add(sw_id)
        dig_tag = f"{_clean_tag_name(sw_tag)}_DI"
        cm = ExperionControlModule(
            cm_name=f"CM_{_clean_tag_name(sw_tag)}",
            loop_type="SAFETY_INTERLOCK",
            description=f"Safety Interlock / Alarm Switch — {sw_tag}",
            controller=controller_name,
            period_ms=50,
            blocks=[
                ExperionBlock(
                    tag=dig_tag,
                    block_type="DIGACQ",
                    description=f"Digital Input Acquisition for {sw_tag}",
                    execution_order=1,
                    source_instrument_tag=sw_tag,
                    source_node_id=sw_id,
                    parameters={
                        "PV": False,
                        "NORMAL_STATE": "OPEN",
                        "ALARM_STATE": "CLOSED",
                        "ALMSTAT": "NORMAL",
                    },
                )
            ],
            wires=[],
            primary_pv_tag=sw_tag,
        )
        control_modules.append(cm)

    # Calculate statistics
    total_blocks = sum(len(cm.blocks) for cm in control_modules)
    total_io_points = sum(
        1 for cm in control_modules for b in cm.blocks if b.block_type in ("DATAACQ", "AO", "DIGACQ", "DEVCTL")
    )

    summary_text = (
        f"Inferred {len(control_modules)} Experion CEE Control Modules "
        f"({len(controllers)} regulatory PID loops, {total_blocks} total function blocks, "
        f"{total_io_points} I/O channels) mapped to controller {controller_name}."
    )

    return ExperionStrategy(
        target_controller=controller_name,
        cee_version="R520.1",
        project_title=pid_graph_data.get("summary") or "EnGenie Experion C300 Strategy",
        control_modules=control_modules,
        total_loops=len(control_modules),
        total_blocks=total_blocks,
        total_io_points=total_io_points,
        summary=summary_text,
    )
