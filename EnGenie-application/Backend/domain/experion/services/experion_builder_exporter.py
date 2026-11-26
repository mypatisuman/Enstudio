"""
Honeywell Experion PKS Exporters.
Generates:
1. Control Builder XML for direct C300 CEE strategy import.
2. Quick Builder / Point Builder CSV for bulk tag database loading.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from xml.dom import minidom
from domain.experion.schemas import ExperionStrategy


def generate_control_builder_xml(strategy: ExperionStrategy) -> str:
    """
    Serializes an ExperionStrategy into Honeywell Control Builder compatible XML.
    Structures Control Modules, contained CEE Function Blocks (DATAACQ, PID, AO, DEVCTL),
    their parameter nameplates, and inter-pin connection wires.
    """
    root = ET.Element("ExperionExport")
    root.set("SchemaVersion", "Honeywell-CEE-R520")
    root.set("Tool", "EnGenie P&ID DCS Synthesis Engine")

    # Header / Target Info
    target_elem = ET.SubElement(root, "TargetSystem")
    target_elem.set("ControllerTag", strategy.target_controller)
    target_elem.set("ControllerType", "C300")
    target_elem.set("Environment", "Control Execution Environment (CEE)")
    target_elem.set("Release", strategy.cee_version)

    # Strategy Section
    strategy_elem = ET.SubElement(root, "ControlStrategy")
    strategy_elem.set("ProjectTitle", strategy.project_title)
    strategy_elem.set("TotalControlModules", str(len(strategy.control_modules)))
    strategy_elem.set("TotalBlocks", str(strategy.total_blocks))
    strategy_elem.set("TotalIOPoints", str(strategy.total_io_points))

    summary_elem = ET.SubElement(strategy_elem, "Summary")
    summary_elem.text = strategy.summary

    # Control Modules
    for cm in strategy.control_modules:
        cm_elem = ET.SubElement(strategy_elem, "ControlModule")
        cm_elem.set("Tag", cm.cm_name)
        cm_elem.set("LoopType", cm.loop_type)
        cm_elem.set("ExecutionPeriodMs", str(cm.period_ms))
        cm_elem.set("AssignedController", cm.controller)

        desc_elem = ET.SubElement(cm_elem, "Description")
        desc_elem.text = cm.description

        if cm.primary_pv_tag:
            cm_elem.set("PrimaryPVTag", cm.primary_pv_tag)
        if cm.primary_sp_tag:
            cm_elem.set("PrimarySPTag", cm.primary_sp_tag)
        if cm.primary_op_tag:
            cm_elem.set("PrimaryOPTag", cm.primary_op_tag)

        # Blocks
        blocks_elem = ET.SubElement(cm_elem, "FunctionBlocks")
        for b in cm.blocks:
            b_elem = ET.SubElement(blocks_elem, "FunctionBlock")
            b_elem.set("Tag", b.tag)
            b_elem.set("BlockType", b.block_type)
            b_elem.set("ExecutionOrder", str(b.execution_order))
            if b.source_instrument_tag:
                b_elem.set("SourceInstrumentTag", b.source_instrument_tag)

            b_desc = ET.SubElement(b_elem, "Description")
            b_desc.text = b.description

            params_elem = ET.SubElement(b_elem, "Parameters")
            for p_name, p_val in b.parameters.items():
                p_elem = ET.SubElement(params_elem, "Parameter")
                p_elem.set("Name", p_name)
                p_elem.set("Value", str(p_val))
                if isinstance(p_val, bool):
                    p_elem.set("DataType", "BOOLEAN")
                elif isinstance(p_val, (int, float)):
                    p_elem.set("DataType", "REAL")
                else:
                    p_elem.set("DataType", "STRING")

        # Wires
        connections_elem = ET.SubElement(cm_elem, "Connections")
        for w in cm.wires:
            w_elem = ET.SubElement(connections_elem, "Connection")
            w_elem.set("FromBlock", w.from_block)
            w_elem.set("FromPin", w.from_param)
            w_elem.set("ToBlock", w.to_block)
            w_elem.set("ToPin", w.to_param)

    # Pretty print XML
    rough_string = ET.tostring(root, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def generate_point_builder_csv(strategy: ExperionStrategy) -> str:
    """
    Serializes an ExperionStrategy into Honeywell Quick Builder / Point Builder CSV format.
    Standard comma-separated table of points, I/O attributes, ranges, and engineering units.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Standard Honeywell Experion Point Builder CSV Header
    writer.writerow([
        "PointName",
        "BlockTag",
        "ControlModule",
        "PointType",
        "Description",
        "Controller",
        "PeriodMs",
        "PVEULO",
        "PVEUHI",
        "EUDESC",
        "AlarmHH",
        "AlarmH",
        "AlarmL",
        "AlarmLL",
        "DefaultMode",
        "FailAction",
        "SourceInstrumentTag",
    ])

    for cm in strategy.control_modules:
        for b in cm.blocks:
            params = b.parameters
            point_type_map = {
                "DATAACQ": "ANALOG_INPUT",
                "PID": "REGULATORY_PID",
                "PIDFF": "REGULATORY_PID_FEEDFORWARD",
                "AO": "ANALOG_OUTPUT",
                "DEVCTL": "DEVICE_CONTROL",
                "DIGACQ": "DIGITAL_INPUT",
            }
            pt_type = point_type_map.get(b.block_type, b.block_type)

            writer.writerow([
                b.tag,
                b.tag,
                cm.cm_name,
                pt_type,
                b.description,
                cm.controller,
                cm.period_ms,
                params.get("PVEULO", 0.0),
                params.get("PVEUHI", 100.0),
                params.get("EUDESC", "%"),
                params.get("HIGH_HIGH_LIMIT", ""),
                params.get("HIGH_LIMIT", ""),
                params.get("LOW_LIMIT", ""),
                params.get("LOW_LOW_LIMIT", ""),
                params.get("MODE", "AUTO"),
                params.get("FAILACT", ""),
                b.source_instrument_tag or "",
            ])

    return output.getvalue()
