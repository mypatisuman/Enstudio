"""
P&ID Builder Service — Central Dispatcher and Layout Engine.
Routes to GreenfieldPIDAgent or BrownfieldPIDAgent, computes 2D spatial layouts,
and renders standards-compliant ISA-5.1 SVG schematics with full 4-way accessory symbols
and rich Assets Table nameplate & calibrated range tooltips.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

from domain.solution.schemas import (
    PIDGraph,
    PIDNode,
    PIDEdge,
    PIDLayout,
    PIDLayoutCell,
    PIDSubsystemArea,
)
from domain.solution.services.isa_classifier import classify_node_kind, parse_isa_tag
from domain.solution.services.asset_specs import summarize as summarize_spec_status

logger = logging.getLogger(__name__)

#: Tooltip wording for each specification provenance (see asset_specs).
_SPEC_STATUS_LABELS = {
    "asset_inventory": "Assets Table (installed device)",
    "stated": "Stated by engineer",
    "bom_selection": "Bill of Materials selection",
    "unspecified": "Unspecified - no data yet",
}


# ---------------------------------------------------------------------------
# Project Mode Detector
# ---------------------------------------------------------------------------

_BROWNFIELD_KEYWORDS = re.compile(
    r"\b(brownfield|retrofit|tie[- ]?in|revamp|debottleneck|existing (line|pipe|plant|unit|header|drawing)|"
    r"tp-\d+|add to existing|modify existing|replacement|tap into)\b",
    re.IGNORECASE,
)

_MUTATION_KEYWORDS = re.compile(
    r"\b(add|modify|replace|insert|remove|delete|change|upgrade|update|append|splice|attach|retrofit)\b",
    re.IGNORECASE,
)

#: Wording that means "instrument the existing plant", even with no mutation
#: verb: "pressure control on the feed subsystem", "a flow loop for E-101".
#: Ported from the Describe router's state-aware override.
_RETROFIT_HINT = re.compile(
    r"\b(sub-?systems?|instrument(ation)? packages?|accessor(y|ies)|tie[- ]?in|tie into|"
    r"(pressure|temperature|flow|level)( control)? (loops?|transmitters?|instruments?|"
    r"measurements?|indicators?|packages?|control))\b",
    re.IGNORECASE,
)


_GREENFIELD_KEYWORDS = re.compile(
    r"\b(greenfield|clean[- ]?sheet|new plant|new facility|new design|brand new|from scratch|new installation|new system)\b",
    re.IGNORECASE,
)


def should_request_pid_clarification(
    requirements: str = "",
    context: str = "",
    has_active_pid: bool = False,
) -> bool:
    """
    Determines if user input lacks an explicit project mode declaration.
    Returns True if neither Greenfield nor Brownfield is explicitly stated,
    and no active P&ID is currently loaded in session memory.
    """
    if has_active_pid:
        return False
        
    text = f"{requirements} {context}".strip()
    if not text:
        return False
        
    has_greenfield = bool(_GREENFIELD_KEYWORDS.search(text))
    has_brownfield = bool(_BROWNFIELD_KEYWORDS.search(text))
    
    # If explicitly specified by user, no clarification is needed
    if has_greenfield or has_brownfield:
        return False
        
    # If ambiguous, prompt the user for clarification
    return True


def generate_pid_clarification_data() -> dict[str, Any]:
    """Generates the structured clarification payload for the frontend chat / modal."""
    return {
        "clarification_type": "pid_project_type",
        "question": "Is this a brand-new clean-sheet design from scratch (Greenfield) or a retrofit onto an existing plant / P&ID drawing (Brownfield)? If Brownfield, please provide details of your existing P&ID image/drawing, line numbers, or existing equipment tags to tie into.",
        "options": [
            "No, design a new Greenfield P&ID from scratch",
            "Yes, this is a Brownfield retrofit (I have an existing drawing / plant setup)",
        ],
        "allow_image_upload": True,
    }


def parse_pid_clarification_response(response: str = "") -> str:
    """
    Parses the user's response to the P&ID clarification question:
    - 'No' / 'Greenfield' / 'From scratch' / 'Option 1' -> 'greenfield'
    - 'Yes' / 'Brownfield' / 'Existing' / 'Option 2'     -> 'brownfield'
    """
    text = response.strip().lower()
    
    # Check for negative / greenfield response
    if any(k in text for k in [
        "no", "greenfield", "scratch", "clean", "clean-sheet", "brand new",
        "option 1", "new p&id", "new plant", "new facility", "new installation",
        "fresh", "from scratch", "nope", "nah", "create new", "build new",
        "no drawing", "no image", "no existing", "fresh design"
    ]):
        return "greenfield"
        
    # Check for affirmative / brownfield response
    if any(k in text for k in [
        "yes", "brownfield", "existing", "retrofit", "tie-in", "tie in",
        "drawing", "option 2", "image", "revamp", "debottleneck",
        "active drawing", "modify existing", "plant drawing", "update existing",
        "i have a drawing", "i have an image", "have existing", "uploaded"
    ]):
        return "brownfield"
        
    return "greenfield"


def classify_pid_intent(
    requirements: str = "",
    context: str = "",
    has_active_pid: bool = False,
) -> str:
    """
    Intelligently classifies user input into one of three execution paths:
      1. 'brownfield_update' -> Evolutionary mutation of an existing active P&ID graph in session memory.
      2. 'brownfield'        -> New retrofit / tie-in design anchored to existing plant hardware & DB assets.
      3. 'greenfield'        -> Clean-sheet autonomous P&ID generation with battery limits and 100-series loops.
    """
    text = f"{requirements} {context}".strip()
    
    # 1. An explicit clean-sheet request is a new design, even when a drawing
    #    is already loaded: "design a brand new plant ... and add" must not be
    #    read as a modification of the old one.
    if has_active_pid and _GREENFIELD_KEYWORDS.search(requirements) and \
            not _BROWNFIELD_KEYWORDS.search(requirements):
        return "greenfield"

    # 2. An active P&ID plus modification verbs or retrofit wording is an
    #    in-place update of that drawing.
    if has_active_pid and (_MUTATION_KEYWORDS.search(requirements)
                           or _RETROFIT_HINT.search(requirements)):
        return "brownfield_update"
        
    # 3. If prompt mentions plant revamp / retrofit / tie-in keywords
    if _BROWNFIELD_KEYWORDS.search(text):
        return "brownfield"
        
    # 4. Default to clean-sheet Greenfield design
    return "greenfield"


def detect_project_type(requirements: str = "", context: str = "") -> str:
    """Backward-compatible wrapper for project type detection."""
    intent = classify_pid_intent(requirements=requirements, context=context, has_active_pid=False)
    return "brownfield" if intent in ["brownfield", "brownfield_update"] else "greenfield"

# ---------------------------------------------------------------------------
# 2D Grid Layout Math & Sub-system Area Bounding Boxes
# ---------------------------------------------------------------------------

def calculate_pid_layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Computes a spacious, non-overlapping multi-corridor 2D matrix layout:
      - Sub-system areas are allocated strictly separated horizontal column blocks.
      - Functional vertical corridors (Rows 0-5) prevent signal, utility, and process line overlap:
          Row 0 (y=140): Utility streams (HW_INLET, SOV, HW_OUTLET), Solenoids, Air Regulators (AFR)
          Row 1 (y=280): Primary Transmitters & Field Sensing Elements (TT, PT, FT, LT, AT, ZT)
          Row 2 (y=420): Sensing Taps & Hardware (TW Thermowell, MNF Manifold, SYP Siphon)
          Row 3 (y=580): Primary Process Stream & Major Equipment (INLET_FEED, Tie-Ins, Valves, Vessels, Exchangers, OUTLET_HEADER)
          Row 4 (y=740): Control Room / DCS Panel Controllers (TIC, PIC, FIC, LIC in PNL-01)
          Row 5 (y=900): Final Control Elements & Actuation (Positioners, Diaphragm Actuators, Divert Valves)
    """
    node_map = {n["id"]: n for n in nodes}
    
    # 1. Group Nodes by Sub-system Area and sort areas logically from inlet to outlet
    area_order_weights = {
        "feed": 10,
        "inlet": 10,
        "column_top": 15,
        "preparation": 15,
        "hot_water": 20,
        "cooling": 20,
        "utility": 20,
        "reaction": 30,
        "heating": 30,
        "exchanger": 30,
        "condenser": 30,
        "distillate": 35,
        "circuit": 35,
        "reflux": 40,
        "drum": 40,
        "diversion": 45,
        "safety": 45,
        "discharge": 45,
        "outlet": 50,
        "pnl": 35,
        "panel": 35,
    }
    
    def get_area_weight(area_name: str) -> int:
        name_lower = area_name.lower()
        for kw, wt in area_order_weights.items():
            if kw in name_lower:
                return wt
        return 50
        
    area_groups: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        area_name = n.get("area") or "PROCESS_AREA"
        area_groups.setdefault(area_name, []).append(n)
        
    sorted_areas = sorted(area_groups.keys(), key=lambda a: (get_area_weight(a), a))
    
    ROW_MAP = {
        "off_page_connector_utility": 0,
        "regulator": 0,
        "transmitter": 1,
        "switch": 1,
        "indicator": 1,
        "relief": 1,
        "thermowell": 2,
        "manifold": 2,
        "siphon": 2,
        "valve": 3,
        "checkvalve": 3,
        "heat_exchanger": 3,
        "vessel": 3,
        "pump": 3,
        "column": 3,
        "reactor": 3,
        "filter": 3,
        "off_page_connector": 3,
        "tie_in": 3,
        "controller": 4,
        "actuator": 5,
        "positioner": 5,
    }
    
    CELL_WIDTH = 280.0
    CELL_HEIGHT = 170.0
    OFFSET_X = 150.0
    OFFSET_Y = 150.0
    
    current_col = 1
    cells: list[dict[str, Any]] = []
    positions: dict[str, dict[str, float]] = {}
    
    for area_name in sorted_areas:
        a_nodes = area_groups[area_name]
        area_start_col = current_col
        
        # Ensure node kinds are accurately classified
        for n in a_nodes:
            lbl = n.get("label", n.get("id", ""))
            reclassified = classify_node_kind(
                tag=lbl,
                category=n.get("kind", ""),
                asset_metadata=n.get("specifications"),
            )
            n["kind"] = reclassified

        # Sort nodes within area: process stream equipment first, then taps/instruments, then controllers/accessories
        def node_sort_key(n: dict[str, Any]) -> int:
            kind = n.get("kind", "")
            lbl = n.get("label", "").upper()
            if "INLET" in lbl or "FEED" in lbl:
                return 0
            if kind in ["off_page_connector", "tie_in", "valve", "heat_exchanger", "vessel", "pump", "column", "reactor"]:
                return 1
            if kind in ["thermowell", "manifold", "siphon"]:
                return 2
            if kind in ["transmitter", "switch", "indicator", "relief"]:
                return 3
            if kind in ["controller"]:
                return 4
            if kind in ["positioner", "actuator"]:
                return 5
            if "OUTLET" in lbl or "HEADER" in lbl:
                return 9
            return 3

        sorted_a_nodes = sorted(a_nodes, key=node_sort_key)
        
        # Track occupied (row, col) in this area
        area_occupied: set[tuple[int, int]] = set()
        
        for n in sorted_a_nodes:
            nid = n["id"]
            kind = n.get("kind", "transmitter")
            lbl = n.get("label", "").upper()
            
            # Refine row based on label semantics
            if "HW_INLET" in lbl or "HW_OUTLET" in lbl or "HWC" in lbl or "SOV" in lbl:
                row = 0 if ("HW" in lbl or "SOV" in lbl) else 1
            elif kind == "regulator" or "AFR" in lbl:
                row = 0
            elif "V-DIV" in lbl or "ACT-DIV" in lbl:
                row = 5 if "ACT" in lbl else 3
            else:
                row = ROW_MAP.get(kind, 3)
                
            # Place in area column, advancing if cell is already occupied
            col = area_start_col
            while (row, col) in area_occupied:
                col += 1
                
            area_occupied.add((row, col))
            cells.append({"row": row, "col": col, "node_id": nid, "tag": n.get("label", nid)})
            n["x"] = OFFSET_X + ((col - 1) * CELL_WIDTH)
            n["y"] = OFFSET_Y + (row * CELL_HEIGHT)
            positions[nid] = {"x": n["x"], "y": n["y"], "row": row, "col": col}
            
        area_max_col = max((col for r, col in area_occupied), default=area_start_col)
        current_col = area_max_col + 1
        
    max_row = max((c["row"] for c in cells), default=0) + 1
    max_col = max((c["col"] for c in cells), default=0) + 1
    
    # 2. Compute Sub-system Bounding Boxes as Standardized Clean Vertical Plant Zones
    subsystem_areas: list[dict[str, Any]] = []
    area_idx = 10
    max_node_y = max((n["y"] for n in nodes if "y" in n and n["y"] is not None), default=580.0)
    zone_top_y = 68.0
    zone_bottom_y = max(max_node_y + 110.0, 520.0)
    zone_height = max(zone_bottom_y - zone_top_y, 450.0)

    for area_name in sorted_areas:
        a_nodes = area_groups[area_name]
        xs = [n["x"] for n in a_nodes if "x" in n and n["x"] is not None]
        if xs:
            min_x = min(xs) - 80.0
            max_x = max(xs) + 80.0
            subsystem_areas.append({
                "id": f"area_{area_idx}",
                "name": area_name,
                "x": max(min_x, 20.0),
                "y": zone_top_y,
                "width": max(max_x - min_x, 220.0),
                "height": zone_height,
                "node_ids": [n["id"] for n in a_nodes],
            })
            area_idx += 10
            
    return {
        "rows": max_row,
        "cols": max_col,
        "cells": cells,
        "subsystem_areas": subsystem_areas,
    }


# ---------------------------------------------------------------------------
# Vector ISA-5.1 SVG Generator with 4-Way Accessories, Subsystems & Tooltips
# ---------------------------------------------------------------------------

def generate_pid_svg(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    layout: dict[str, Any],
    project_type: str = "greenfield",
) -> str:
    """Renders standard ISA-5.1 symbols into an interactive SVG with pill badges, tooltips & zero text overlaps."""
    subsystem_areas = layout.get("subsystem_areas", [])
    node_xs = [n.get("x", 0) for n in nodes if "x" in n and n.get("x") is not None]
    node_ys = [n.get("y", 0) for n in nodes if "y" in n and n.get("y") is not None]
    area_max_xs = [a.get("x", 0) + a.get("width", 0) for a in subsystem_areas]
    area_max_ys = [a.get("y", 0) + a.get("height", 0) for a in subsystem_areas]

    max_x = max(node_xs + area_max_xs + [900.0])
    max_y = max(node_ys + area_max_ys + [540.0])

    width = int(max_x + 80.0)
    height = int(max_y + 60.0)
    
    node_map = {n["id"]: n for n in nodes}
    subsystem_areas = layout.get("subsystem_areas", [])
    
    is_brownfield = project_type.lower() == "brownfield"
    badge_bg = "#fef3c7" if is_brownfield else "#e0f2fe"
    badge_border = "#d97706" if is_brownfield else "#0284c7"
    badge_text_color = "#92400e" if is_brownfield else "#0369a1"
    badge_label = "BROWNFIELD RETROFIT (ASSETS BOUND)" if is_brownfield else "GREENFIELD DESIGN (CLEAN-SHEET P&ID)"
    
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="width:100%; height:auto; background:#ffffff; font-family:Inter, ui-sans-serif, system-ui, sans-serif; user-select:none;">',
        '<defs>',
        '  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '    <path d="M 0 1 L 10 5 L 0 9 z" fill="#0f172a" />',
        '  </marker>',
        '  <marker id="arrow-impulse" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">',
        '    <path d="M 0 1 L 10 5 L 0 9 z" fill="#0284c7" />',
        '  </marker>',
        '  <filter id="shadow" x="-8%" y="-8%" width="120%" height="120%">',
        '    <feDropShadow dx="1" dy="2" stdDeviation="2" flood-color="#0f172a" flood-opacity="0.08" />',
        '  </filter>',
        '</defs>',
        '<!-- Background Grid -->',
        '<pattern id="grid-pat" width="40" height="40" patternUnits="userSpaceOnUse">',
        '  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#f1f5f9" stroke-width="1"/>',
        '</pattern>',
        f'<rect width="{width}" height="{height}" fill="url(#grid-pat)" />',
        
        f'<!-- Project Mode Header Badge -->',
        f'<g transform="translate(30, 20)">',
        f'  <rect width="330" height="28" rx="6" fill="{badge_bg}" stroke="{badge_border}" stroke-width="1.2" />',
        f'  <circle cx="16" cy="14" r="4.5" fill="{badge_border}" />',
        f'  <text x="30" y="18.5" font-size="11" font-weight="700" fill="{badge_text_color}" letter-spacing="0.5">{badge_label}</text>',
        f'</g>',
        
        '<!-- Sub-system Area Bounding Boxes -->'
    ]
    
    # Render Sub-system Bounding Boxes with non-overlapping top header pills in top zone margin
    for area in subsystem_areas:
        ax, ay = area.get("x", 0), area.get("y", 68.0)
        aw, ah = area.get("width", 220), area.get("height", 800)
        aname = area.get("name", "Sub-system")
        aid = area.get("id", "").upper()
        clean_title = f"{aid}: {aname.upper()[:28]}"
        pill_w = min(len(clean_title) * 7.2 + 20, aw - 24)
        
        svg_parts.append(
            f'<rect x="{ax}" y="{ay}" width="{aw}" height="{ah}" rx="12" '
            f'fill="#f8fafc" fill-opacity="0.45" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="6,4" />'
        )
        svg_parts.append(
            f'<rect x="{ax+10}" y="{ay+10}" width="{pill_w}" height="22" rx="4" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1" />'
        )
        svg_parts.append(
            f'<text x="{ax+16}" y="{ay+25}" font-size="9.5" font-weight="700" fill="#475569" letter-spacing="0.3">'
            f'{clean_title}</text>'
        )
        
    svg_parts.append('<!-- Process & Signal Edges (Layer 1: Base Stream & Signal Paths) -->')
    edge_paths: list[str] = []
    edge_labels: list[str] = []
    
    # Render Edges & Non-Overlapping Pill Badges in strict Z-Index layers
    for edge_idx, e in enumerate(edges):
        f_node = node_map.get(e.get("from"))
        t_node = node_map.get(e.get("to"))
        if not f_node or not t_node:
            continue
        fx, fy = f_node.get("x", 0), f_node.get("y", 0)
        tx, ty = t_node.get("x", 0), t_node.get("y", 0)
        kind = e.get("kind", "stream")
        
        if kind == "stream":
            stroke = "#0f172a"
            stroke_width = "3.5"
            dash = ""
            marker = 'marker-end="url(#arrow)"'
        elif kind == "impulse":
            stroke = "#0284c7"
            stroke_width = "1.75"
            dash = ""
            marker = 'marker-end="url(#arrow-impulse)"'
        elif kind == "signal":
            stroke = "#d97706"
            stroke_width = "1.75"
            dash = 'stroke-dasharray="5,4"'
            marker = ""
        elif kind == "pneumatic":
            stroke = "#059669"
            stroke_width = "1.75"
            dash = 'stroke-dasharray="8,3,2,3"'
            marker = ""
        elif kind == "relief":
            stroke = "#dc2626"
            stroke_width = "2.5"
            dash = 'stroke-dasharray="4,2"'
            marker = 'marker-end="url(#arrow)"'
        else:
            stroke = "#64748b"
            stroke_width = "2"
            dash = 'stroke-dasharray="4,4"'
            marker = ""
            
        if abs(fy - ty) < 5:
            d = f"M {fx} {fy} L {tx} {ty}"
            mx = (fx + tx) / 2
            my = fy - 22  # Clear 22px buffer above line
        elif abs(fx - tx) < 5:
            d = f"M {fx} {fy} L {tx} {ty}"
            mx = fx + 20
            my = (fy + ty) / 2
        else:
            mid_x = fx + (tx - fx) * 0.5
            d = f"M {fx} {fy} L {mid_x} {fy} L {mid_x} {ty} L {tx} {ty}"
            mx = mid_x
            my = (fy + ty) / 2
            
        edge_paths.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{stroke_width}" {dash} {marker} />')
        
        # Render Edge Label with dedicated 100% opaque white pill badge (Rendered in Layer 2 over all paths)
        if e.get("label"):
            raw_label = str(e["label"]).strip()
            display_label = raw_label[:28]
            lbl_w = len(display_label) * 6.8 + 18
            
            edge_labels.append(
                f'<g class="edge-label">'
                f'<rect x="{mx - lbl_w/2}" y="{my - 10}" width="{lbl_w}" height="20" rx="4" '
                f'fill="#ffffff" stroke="{stroke}" stroke-width="1.2" opacity="1" filter="url(#shadow)" />'
                f'<text x="{mx}" y="{my+3.5}" font-size="9" fill="{stroke}" text-anchor="middle" font-weight="700">{display_label}</text>'
                f'</g>'
            )
            
    svg_parts.extend(edge_paths)
    svg_parts.append('<!-- Edge Labels & Stream Badges (Layer 2: Rendered Over Paths to Prevent Line Clipping) -->')
    svg_parts.extend(edge_labels)
    
    svg_parts.append('<!-- P&ID Nodes (Layer 3: Solid-Filled Equipment & Sensing Elements on Top) -->')
    
    # Render Nodes with Rich Asset Tooltips & Badges
    for n in nodes:
        x, y = n.get("x", 0), n.get("y", 0)
        tag = n.get("label", "")
        kind = n.get("kind", "transmitter")
        is_tie_in = n.get("is_tie_in") or kind == "tie_in"
        specs = n.get("specifications") or {}
        
        # Build comprehensive SVG tooltip text with Vendor, Model Family, Series & Standards
        tooltip_lines = [f"TAG: {tag} [{kind.upper()}]"]
        if n.get("description"):
            tooltip_lines.append(f"Function: {n['description']}")
        # The node's own nameplate (specifications.manufacturer / model) is the
        # authoritative source for a device bound from the Assets Table, which
        # BOM enrichment deliberately leaves untouched. Fall back to it so a
        # real installed device never renders without its make and model.
        vendor = n.get("vendor") or specs.get("manufacturer")
        model_series = n.get("model_series") or specs.get("model")
        if vendor:
            tooltip_lines.append(f"Vendor (OEM): {vendor}")
        if n.get("model_family"):
            tooltip_lines.append(f"Model Family: {n['model_family']}")
        if model_series and model_series != n.get("model_family"):
            tooltip_lines.append(f"Model Series: {model_series}")
        if n.get("parent_instrument_tag"):
            tooltip_lines.append(f"Supporting: {n['parent_instrument_tag']}")
        if n.get("standards") and len(n["standards"]) > 0:
            tooltip_lines.append(f"Standards: {', '.join(n['standards'][:3])}")
        if specs.get("serial_number"):
            tooltip_lines.append(f"Serial No: {specs['serial_number']}")
        if specs.get("calibrated_range"):
            tooltip_lines.append(f"Calibrated Range: {specs['calibrated_range']}")
        if specs.get("wetted_material") or specs.get("body_material") or specs.get("material"):
            tooltip_lines.append(f"Material: {specs.get('wetted_material') or specs.get('body_material') or specs.get('material')}")
        if specs.get("connected_system") or specs.get("connected_panel"):
            tooltip_lines.append(f"Panel: {specs.get('connected_system') or specs.get('connected_panel')}")
        if specs.get("protocol"):
            tooltip_lines.append(f"Protocol: {specs['protocol']}")
        if n.get("area"):
            tooltip_lines.append(f"Area: {n['area']}")
        if n.get("loop"):
            tooltip_lines.append(f"Loop: {n['loop']}")
        spec_status = n.get("spec_status") or ""
        if spec_status:
            tooltip_lines.append(f"Specs source: {_SPEC_STATUS_LABELS.get(spec_status, spec_status)}")

        tooltip_str = html.escape("\n".join(tooltip_lines))

        svg_parts.append(
            f'<g class="pid-node" data-id="{n["id"]}" data-tag="{tag}" data-kind="{kind}" '
            f'data-spec-status="{html.escape(spec_status)}" style="cursor:pointer;">'
        )
        svg_parts.append(f'  <title>{tooltip_str}</title>')
        
        if is_tie_in or kind == "tie_in":
            # Brownfield Tie-In Point Symbol (Amber Chamfered Tag)
            svg_parts.append(
                f'<polygon points="{x-32},{y-16} {x+20},{y-16} {x+32},{y} {x+20},{y+16} {x-32},{y+16}" '
                f'fill="#fffbeb" stroke="#d97706" stroke-width="2.5" filter="url(#shadow)" />'
            )
            svg_parts.append(f'<text x="{x-4}" y="{y+4}" font-size="11" font-weight="800" fill="#92400e" text-anchor="middle">{tag}</text>')
            
        elif kind == "off_page_connector":
            # Greenfield Battery Limit Connector
            svg_parts.append(
                f'<polygon points="{x-40},{y-16} {x+25},{y-16} {x+40},{y} {x+25},{y+16} {x-40},{y+16}" '
                f'fill="#f8fafc" stroke="#334155" stroke-width="2" filter="url(#shadow)" />'
            )
            svg_parts.append(f'<text x="{x-5}" y="{y+4}" font-size="11" font-weight="700" fill="#1e293b" text-anchor="middle">{tag}</text>')
            
        elif kind == "manifold":
            # 3-Valve / 5-Valve Manifold Symbol (Rectangle with 3 valve dots & equalize line)
            svg_parts.append(
                f'<rect x="{x-24}" y="{y-12}" width="48" height="24" rx="4" fill="#f0fdf4" stroke="#16a34a" stroke-width="1.8" filter="url(#shadow)" />'
            )
            svg_parts.append(f'<circle cx="{x-14}" cy="{y}" r="3" fill="#16a34a" />')
            svg_parts.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#16a34a" />')
            svg_parts.append(f'<circle cx="{x+14}" cy="{y}" r="3" fill="#16a34a" />')
            tag_w = len(tag) * 6.5 + 10
            svg_parts.append(f'<rect x="{x - tag_w/2}" y="{y+16}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#bbf7d0" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x}" y="{y+28}" font-size="10" font-weight="700" fill="#15803d" text-anchor="middle">{tag}</text>')
            
        elif kind == "siphon":
            # Pigtail Siphon Loop Symbol
            svg_parts.append(
                f'<circle cx="{x}" cy="{y}" r="14" fill="#ffffff" stroke="#0284c7" stroke-width="2" />'
            )
            svg_parts.append(f'<line x1="{x}" y1="{y-14}" x2="{x}" y2="{y-20}" stroke="#0284c7" stroke-width="2" />')
            svg_parts.append(f'<line x1="{x}" y1="{y+14}" x2="{x}" y2="{y+20}" stroke="#0284c7" stroke-width="2" />')
            tag_w = len(tag) * 6.5 + 10
            svg_parts.append(f'<rect x="{x+18}" y="{y-7}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#bae6fd" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x+23+tag_w/2-5}" y="{y+5}" font-size="10" font-weight="700" fill="#0369a1" text-anchor="middle">{tag}</text>')
            
        elif kind == "thermowell":
            # Thermowell Sheath Symbol
            svg_parts.append(f'<line x1="{x}" y1="{y-18}" x2="{x}" y2="{y+18}" stroke="#475569" stroke-width="3" />')
            svg_parts.append(f'<rect x="{x-8}" y="{y-18}" width="16" height="6" fill="#475569" />')
            tag_w = len(tag) * 6.5 + 10
            svg_parts.append(f'<rect x="{x+16}" y="{y-7}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x+21+tag_w/2-5}" y="{y+5}" font-size="10" font-weight="700" fill="#334155" text-anchor="middle">{tag}</text>')
            
        elif kind == "positioner":
            # Smart Positioner Box Symbol
            svg_parts.append(
                f'<rect x="{x-22}" y="{y-16}" width="44" height="32" rx="4" fill="#eff6ff" stroke="#2563eb" stroke-width="1.8" filter="url(#shadow)" />'
            )
            svg_parts.append(f'<text x="{x}" y="{y+4}" font-size="9.5" font-weight="800" fill="#1d4ed8" text-anchor="middle">POS</text>')
            tag_w = len(tag) * 6.5 + 12
            svg_parts.append(f'<rect x="{x - tag_w/2}" y="{y+21}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#bfdbfe" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x}" y="{y+33}" font-size="10" font-weight="700" fill="#1e40af" text-anchor="middle">{tag}</text>')
            
        elif kind == "actuator":
            # Pneumatic Spring-Diaphragm Dome Symbol
            svg_parts.append(f'<path d="M {x-18} {y} A 18 18 0 0 1 {x+18} {y} Z" fill="#e2e8f0" stroke="#0f172a" stroke-width="2" />')
            svg_parts.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+16}" stroke="#0f172a" stroke-width="2" />')
            tag_w = len(tag) * 6.5 + 10
            svg_parts.append(f'<rect x="{x - tag_w/2}" y="{y-32}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x}" y="{y-20}" font-size="10" font-weight="700" fill="#0f172a" text-anchor="middle">{tag}</text>')
            
        elif kind == "regulator":
            # Air Filter Regulator (AFR) Symbol
            svg_parts.append(
                f'<polygon points="{x},{y-14} {x+14},{y} {x},{y+14} {x-14},{y}" fill="#f0fdfa" stroke="#0d9488" stroke-width="1.8" />'
            )
            tag_w = len(tag) * 6.5 + 10
            svg_parts.append(f'<rect x="{x - tag_w/2}" y="{y+18}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#99f6e4" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x}" y="{y+30}" font-size="10" font-weight="700" fill="#0f766e" text-anchor="middle">{tag}</text>')
            
        elif kind in ["vessel", "column", "reactor"]:
            svg_parts.append(
                f'<rect x="{x-45}" y="{y-45}" width="90" height="90" rx="16" fill="#f8fafc" stroke="#0f172a" stroke-width="2.5" filter="url(#shadow)" />'
            )
            svg_parts.append(f'<text x="{x}" y="{y-6}" font-size="13" font-weight="700" fill="#0f172a" text-anchor="middle">{tag}</text>')
            desc = (n.get("description") or kind)[:14]
            svg_parts.append(f'<text x="{x}" y="{y+12}" font-size="9" fill="#64748b" text-anchor="middle">{desc}</text>')
            
        elif kind == "pump":
            svg_parts.append(f'<circle cx="{x}" cy="{y}" r="28" fill="#f8fafc" stroke="#0f172a" stroke-width="2.5" filter="url(#shadow)" />')
            svg_parts.append(f'<polygon points="{x+18},{y-18} {x+34},{y-18} {x+24},{y-2}" fill="#0f172a" />')
            svg_parts.append(f'<text x="{x}" y="{y+4}" font-size="12" font-weight="700" fill="#0f172a" text-anchor="middle">{tag}</text>')
            
        elif kind == "heat_exchanger":
            svg_parts.append(f'<circle cx="{x}" cy="{y}" r="32" fill="#f8fafc" stroke="#0f172a" stroke-width="2.5" filter="url(#shadow)" />')
            svg_parts.append(f'<path d="M {x-22} {y} Q {x-11} {y-16} {x} {y} T {x+22} {y}" fill="none" stroke="#0f172a" stroke-width="2" />')
            svg_parts.append(f'<text x="{x}" y="{y+18}" font-size="11" font-weight="700" fill="#0f172a" text-anchor="middle">{tag}</text>')
            
        elif kind == "valve":
            svg_parts.append(
                f'<polygon points="{x-20},{y-14} {x},{y} {x-20},{y+14}" fill="#ffffff" stroke="#0f172a" stroke-width="2" />'
            )
            svg_parts.append(
                f'<polygon points="{x+20},{y-14} {x},{y} {x+20},{y+14}" fill="#ffffff" stroke="#0f172a" stroke-width="2" />'
            )
            if "PCV" in tag or "FCV" in tag or "TCV" in tag or "LCV" in tag or "CV" in tag or "DIV" in tag:
                svg_parts.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y-20}" stroke="#0f172a" stroke-width="2" />')
                svg_parts.append(f'<path d="M {x-14} {y-20} A 14 14 0 0 1 {x+14} {y-20} Z" fill="#e2e8f0" stroke="#0f172a" stroke-width="1.5" />')
            tag_w = len(tag) * 6.5 + 12
            svg_parts.append(f'<rect x="{x - tag_w/2}" y="{y+18}" width="{tag_w}" height="17" rx="3" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x}" y="{y+30}" font-size="11" font-weight="700" fill="#0f172a" text-anchor="middle">{tag}</text>')
            
        elif kind == "relief":
            svg_parts.append(f'<polygon points="{x-14},{y-10} {x},{y} {x-14},{y+10}" fill="#fee2e2" stroke="#dc2626" stroke-width="2" />')
            svg_parts.append(f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y-16}" stroke="#dc2626" stroke-width="2" />')
            tag_w = len(tag) * 6.5 + 10
            svg_parts.append(f'<rect x="{x - tag_w/2}" y="{y+18}" width="{tag_w}" height="16" rx="3" fill="#ffffff" stroke="#fecaca" stroke-width="0.8" />')
            svg_parts.append(f'<text x="{x}" y="{y+30}" font-size="11" font-weight="700" fill="#dc2626" text-anchor="middle">{tag}</text>')
            
        elif kind == "controller":
            # Dynamic circle radius to accommodate longer tags like S-SFC-301
            tag_len = len(tag)
            r = 30 if tag_len > 6 else 26
            svg_parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fef3c7" stroke="#b45309" stroke-width="2" filter="url(#shadow)" />')
            svg_parts.append(f'<line x1="{x-r}" y1="{y}" x2="{x+r}" y2="{y}" stroke="#b45309" stroke-width="1.5" />')
            
            # Robust tag parsing for complex tags e.g. "S-SFC-301", "TIC-101", "FIC_202"
            parts = re.split(r"[-_]", tag)
            if len(parts) >= 2:
                top_text = "-".join(parts[:-1])
                bottom_text = parts[-1]
                top_fs = "9" if len(top_text) > 5 else "10"
                bottom_fs = "9.5" if len(bottom_text) > 4 else "10.5"
                svg_parts.append(f'<text x="{x}" y="{y-4}" font-size="{top_fs}" font-weight="700" fill="#92400e" text-anchor="middle">{top_text}</text>')
                svg_parts.append(f'<text x="{x}" y="{y+14}" font-size="{bottom_fs}" font-weight="600" fill="#92400e" text-anchor="middle">{bottom_text}</text>')
            else:
                m = re.match(r"([A-Za-z]+)(\d+)", tag)
                if m:
                    svg_parts.append(f'<text x="{x}" y="{y-4}" font-size="10" font-weight="700" fill="#92400e" text-anchor="middle">{m.group(1)}</text>')
                    svg_parts.append(f'<text x="{x}" y="{y+14}" font-size="10" font-weight="600" fill="#92400e" text-anchor="middle">{m.group(2)}</text>')
                else:
                    svg_parts.append(f'<text x="{x}" y="{y-4}" font-size="9" font-weight="700" fill="#92400e" text-anchor="middle">{tag[:5]}</text>')
                    if len(tag) > 5:
                        svg_parts.append(f'<text x="{x}" y="{y+14}" font-size="9" font-weight="600" fill="#92400e" text-anchor="middle">{tag[5:]}</text>')
                
        else:
            # Transmitter (Field circle)
            tag_len = len(tag)
            r = 28 if tag_len > 6 else 24
            svg_parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#e0f2fe" stroke="#0369a1" stroke-width="2" filter="url(#shadow)" />')
            
            parts = re.split(r"[-_]", tag)
            if len(parts) >= 2:
                top_text = "-".join(parts[:-1])
                bottom_text = parts[-1]
                top_fs = "9" if len(top_text) > 5 else "10"
                bottom_fs = "9.5" if len(bottom_text) > 4 else "10.5"
                svg_parts.append(f'<text x="{x}" y="{y-3}" font-size="{top_fs}" font-weight="700" fill="#075985" text-anchor="middle">{top_text}</text>')
                svg_parts.append(f'<text x="{x}" y="{y+13}" font-size="{bottom_fs}" font-weight="600" fill="#075985" text-anchor="middle">{bottom_text}</text>')
            else:
                m = re.match(r"([A-Za-z]+)(\d+)", tag)
                if m:
                    svg_parts.append(f'<text x="{x}" y="{y-3}" font-size="10" font-weight="700" fill="#075985" text-anchor="middle">{m.group(1)}</text>')
                    svg_parts.append(f'<text x="{x}" y="{y+13}" font-size="10" font-weight="600" fill="#075985" text-anchor="middle">{m.group(2)}</text>')
                else:
                    svg_parts.append(f'<text x="{x}" y="{y+4}" font-size="10" font-weight="700" fill="#075985" text-anchor="middle">{tag}</text>')
                
            # Subtitle badge with calibrated range if present
            cal_rng = specs.get("calibrated_range")
            if cal_rng and cal_rng != "0 - 100%":
                display_rng = cal_rng[:14]
                rw = len(display_rng) * 5.8 + 8
                svg_parts.append(f'<rect x="{x - rw/2}" y="{y+28}" width="{rw}" height="14" rx="3" fill="#ffffff" stroke="#bae6fd" stroke-width="0.6" opacity="0.95" />')
                svg_parts.append(f'<text x="{x}" y="{y+38}" font-size="8.5" font-weight="600" fill="#0284c7" text-anchor="middle">{display_rng}</text>')
                
        svg_parts.append('</g>')
        
    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def _enrich_nodes_with_bom_metadata(
    nodes: list[dict[str, Any]],
    instruments: list[dict[str, Any]],
    accessories: list[dict[str, Any]],
    designed_solution: dict[str, Any] | None = None,
) -> None:
    """
    Enriches P&ID nodes with concrete Vendor (OEM), Model Family (L3),
    Model Series (L4), Standards, Parent Instrument Links, and Categorized Specs
    from the Solution Bill of Materials (BOM).
    """
    inst_by_category: dict[str, dict[str, Any]] = {}
    for inst in (instruments or []):
        cat = (inst.get("category") or "").strip().lower()
        pname = (inst.get("product_name") or "").strip().lower()
        if cat:
            inst_by_category[cat] = inst
        if pname:
            inst_by_category[pname] = inst

    acc_by_category: dict[str, dict[str, Any]] = {}
    for acc in (accessories or []):
        cat = (acc.get("category") or "").strip().lower()
        aname = (acc.get("accessory_name") or "").strip().lower()
        if cat:
            acc_by_category[cat] = acc
        if aname:
            acc_by_category[aname] = acc

    # Map primary instrument tags to link accessories
    inst_tag_by_category: dict[str, str] = {}
    for n in nodes:
        lbl = n.get("label", "").upper()
        kind = n.get("kind", "")
        if kind in ["transmitter", "valve"]:
            inst_tag_by_category[kind] = lbl
            if "PT" in lbl or "press" in n.get("description", "").lower():
                inst_tag_by_category["pressure"] = lbl
            if "TT" in lbl or "temp" in n.get("description", "").lower():
                inst_tag_by_category["temperature"] = lbl
            if "FT" in lbl or "flow" in n.get("description", "").lower():
                inst_tag_by_category["flow"] = lbl
            if "LT" in lbl or "level" in n.get("description", "").lower():
                inst_tag_by_category["level"] = lbl
            if "PCV" in lbl or "TCV" in lbl or "FCV" in lbl or "valve" in n.get("description", "").lower():
                inst_tag_by_category["valve"] = lbl

    for n in nodes:
        lbl = n.get("label", "")
        kind = n.get("kind", "")
        desc = n.get("description", "")
        specs = n.get("specifications") or {}
        n["specifications"] = specs

        # 1. Match with BOM instrument or accessory
        matched_inst: dict[str, Any] | None = None
        matched_acc: dict[str, Any] | None = None

        for k, inst in inst_by_category.items():
            if (
                k in desc.lower()
                or k in lbl.lower()
                or (k in "pressure transmitter" and "PT" in lbl)
                or (k in "temperature transmitter" and "TT" in lbl)
                or (k in "flow transmitter" and "FT" in lbl)
                or (k in "level transmitter" and "LT" in lbl)
                or (k in "control valve" and "PCV" in lbl)
            ):
                matched_inst = inst
                break

        if not matched_inst:
            for k, acc in acc_by_category.items():
                if (
                    k in desc.lower()
                    or k in lbl.lower()
                    or (k in "manifold" and "MNF" in lbl)
                    or (k in "siphon" and "SYP" in lbl)
                    or (k in "thermowell" and "TW" in lbl)
                    or (k in "positioner" and "POS" in lbl)
                    or (k in "actuator" and "ACT" in lbl)
                    or (k in "regulator" and "AFR" in lbl)
                ):
                    matched_acc = acc
                    break

        # A node bound to an installed device (spec_status "asset_inventory")
        # keeps that device's nameplate: the BOM describes what the project
        # would buy, not what is installed. Everything applied from the BOM is
        # real project data and is marked "bom_selection". Nothing is filled
        # when the BOM is silent -- this function used to supply "Emerson
        # Automation", "Rosemount 3051 Series", a vendor for every accessory
        # (FIELDVUE DVC6200, 67CFR, ...), an "IEC 61508 SIL-2" standards list
        # and a "PT-101" parent link whether or not that tag existed.
        from_asset = n.get("spec_status") == "asset_inventory"
        applied = False

        if matched_inst:
            dev = matched_inst.get("device") or {}
            if not from_asset:
                for key, value in (
                    ("vendor", dev.get("oem") or specs.get("manufacturer") or specs.get("vendor")),
                    ("model_family", dev.get("model_series") or specs.get("model_family")),
                    ("model_series", dev.get("model_number") or matched_inst.get("product_name")
                     or specs.get("model")),
                ):
                    if value and not n.get(key):
                        n[key] = value
                        applied = True
            if not n.get("standards") and matched_inst.get("standards"):
                n["standards"] = matched_inst["standards"]
                applied = True

            # Merge any specifications from BOM
            bom_specs = matched_inst.get("specifications") or {}
            if isinstance(bom_specs, dict) and not from_asset:
                before = len(specs)
                for sk, sv in bom_specs.items():
                    if isinstance(sv, list):  # grouped specs (safety, electrical, etc.)
                        for p in sv:
                            if isinstance(p, dict) and p.get("name") and p.get("value"):
                                specs.setdefault(p["name"], p["value"])
                    elif isinstance(sv, dict):
                        for subk, subv in sv.items():
                            specs.setdefault(subk, subv)
                    elif sv is not None and not isinstance(sv, (list, dict)):
                        specs.setdefault(sk, sv)
                applied = applied or len(specs) > before

        elif matched_acc:
            dev = matched_acc.get("device") or {}
            if not from_asset:
                for key, value in (
                    ("vendor", dev.get("oem")),
                    ("model_family", dev.get("model_series")),
                    ("model_series", dev.get("model_number") or matched_acc.get("accessory_name")),
                ):
                    if value and not n.get(key):
                        n[key] = value
                        applied = True
            if not n.get("standards") and matched_acc.get("standards"):
                n["standards"] = matched_acc["standards"]
                applied = True

            # Link an accessory to its parent instrument -- only to a tag that
            # is actually on this drawing.
            parent_cat = (matched_acc.get("parent_instrument_category") or "").lower()
            if not n.get("parent_instrument_tag"):
                parent = None
                if "press" in parent_cat or "MNF" in lbl or "SYP" in lbl:
                    parent = inst_tag_by_category.get("pressure")
                elif "temp" in parent_cat or "TW" in lbl:
                    parent = inst_tag_by_category.get("temperature")
                elif "valve" in parent_cat or "POS" in lbl or "ACT" in lbl or "AFR" in lbl:
                    parent = inst_tag_by_category.get("valve")
                if parent:
                    n["parent_instrument_tag"] = parent

        if applied and n.get("spec_status") in (None, "", "unspecified"):
            n["spec_status"] = "bom_selection"

        # Organize categorized_specs dictionary
        cat_specs: dict[str, dict[str, Any]] = {
            "process": {},
            "mechanical": {},
            "electrical": {},
            "safety": {},
            "certifications": {},
        }
        for sk, sv in specs.items():
            sk_lower = sk.lower()
            if any(w in sk_lower for w in ["calibrated", "range", "fluid", "flow", "temp", "pressure", "medium", "accuracy", "span"]):
                cat_specs["process"][sk] = sv
            elif any(w in sk_lower for w in ["material", "wetted", "flange", "body", "trim", "size", "connection", "enclosure", "form"]):
                cat_specs["mechanical"][sk] = sv
            elif any(w in sk_lower for w in ["protocol", "signal", "power", "supply", "hart", "voltage", "connected", "rack", "panel", "input", "output"]):
                cat_specs["electrical"][sk] = sv
            elif any(w in sk_lower for w in ["sil", "safety", "fail", "action", "trip", "interlock"]):
                cat_specs["safety"][sk] = sv
            elif any(w in sk_lower for w in ["atex", "iecex", "fm", "cert", "standard", "rating", "approval"]):
                cat_specs["certifications"][sk] = sv
            else:
                cat_specs["process"][sk] = sv

        n["categorized_specs"] = {k: v for k, v in cat_specs.items() if v}


# ---------------------------------------------------------------------------
# Central Dispatcher Function
# ---------------------------------------------------------------------------

def _rule_intent(requirements: str, context: str, has_active_pid: bool) -> tuple[str, bool]:
    """(intent, decisive). The same keyword rules as classify_pid_intent, plus
    whether they actually decided anything.

    Only a request against a loaded drawing can be undecided. Without one the
    choice is clean-sheet vs retrofit, and when the wording does not say,
    holistic_agent asks the engineer (should_request_pid_clarification) -- a
    person's answer beats a model's guess, so the rules' greenfield default
    stands."""
    text = f"{requirements} {context}".strip()
    if has_active_pid:
        if _GREENFIELD_KEYWORDS.search(requirements) and not _BROWNFIELD_KEYWORDS.search(requirements):
            return "greenfield", True
        if _MUTATION_KEYWORDS.search(requirements) or _RETROFIT_HINT.search(requirements):
            return "brownfield_update", True
        return "greenfield", False
    if _BROWNFIELD_KEYWORDS.search(text):
        return "brownfield", True
    return "greenfield", True


def _router_llm_complete(prompt: str) -> str:
    """One fast-tier model call for the P&ID router. Module-level so tests can
    replace it."""
    from common.ai.llm import get_solution_flash_llm

    resp = get_solution_flash_llm(temperature=0.0).invoke(
        prompt, config={"metadata": {"agent_type": "pid_router"}})
    content = getattr(resp, "content", resp)
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


def route_pid_intent(
    requirements: str = "",
    context: str = "",
    active_pid_graph: dict[str, Any] | None = None,
    *,
    use_llm: bool = True,
) -> tuple[str, str]:
    """Decide which P&ID path a request takes. Returns (intent, reason).

    Deterministic keyword rules first, as in classify_pid_intent. Only when the
    rules did not actually decide -- they fell through to the greenfield
    default -- is the model asked, constrained to the intents that make sense
    in this state. That is the Describe router's arrangement, and it matters
    most now that drawings persist: "I need a flow meter on the cooling water
    return" with a drawing already loaded has no keyword either way, and the
    default would silently replace the engineer's drawing with a new one.
    """
    has_active = bool(active_pid_graph)
    intent, decisive = _rule_intent(requirements, context, has_active)
    if decisive or not use_llm or not (requirements or "").strip():
        return intent, "keyword rules" if decisive else "default"

    allowed = ("brownfield_update", "greenfield")
    try:
        from domain.solution.agents.pid_tool_agent import fill_prompt
        from domain.solution.agents.shared import PID_ROUTER_PROMPT, _parse_llm_json
        from domain.solution.services.pid_graph_store import PIDGraphStore

        summary = PIDGraphStore(active_pid_graph).graph_summary(max_tags=25) \
            if has_active else "(no drawing yet)"
        raw = _router_llm_complete(fill_prompt(PID_ROUTER_PROMPT, {
            "requirements": requirements,
            "context": context or "(none)",
            "drawing": summary,
            "allowed": ", ".join(allowed),
        }))
        parsed = _parse_llm_json(raw) or {}
        choice = str(parsed.get("intent") or "").strip().lower()
        if choice in allowed:
            return choice, "model: %s" % str(parsed.get("reason") or "")[:160]
        logging.warning(f"[PID_ROUTER] model chose {choice!r}, not in {allowed}; using {intent}")
    except Exception as exc:
        logging.warning(f"[PID_ROUTER] model routing unavailable ({exc}); using {intent}")
    return intent, "default"


def render_graph(
    raw_graph: dict[str, Any],
    project_type: str,
    *,
    instruments: list[dict[str, Any]] | None = None,
    accessories: list[dict[str, Any]] | None = None,
    designed_solution: dict[str, Any] | None = None,
    enrich: bool = True,
) -> dict[str, Any]:
    """Turn a raw agent graph into the validated PIDGraph the UI consumes:
    BOM enrichment, edge normalisation, layout, SVG, and a fresh validation.

    Shared by the solution pipeline and the P&ID endpoints (confirm, clarify),
    so a drawing re-rendered after an engineer's decision looks exactly like
    one produced by a solution turn."""
    from domain.solution.services.pid_graph_store import PIDGraphStore

    nodes = raw_graph.get("nodes", [])
    edges = raw_graph.get("edges", [])

    # Enrich nodes with concrete BOM metadata (Vendor, Model Family, Series, Standards, Specs)
    if enrich:
        _enrich_nodes_with_bom_metadata(nodes, instruments or [], accessories or [],
                                        designed_solution)

    normalized_edges = []
    for e in edges:
        f = e.get("from") or e.get("from_id")
        t = e.get("to") or e.get("to_id")
        if f and t:
            normalized_edges.append({
                "from": f,
                "to": t,
                "kind": e.get("kind", "stream"),
                "label": e.get("label", ""),
                "fluid": e.get("fluid", ""),
                "line_size": e.get("line_size", ""),
            })

    # Calculate 2D layout grid & Sub-system bounding areas
    layout = calculate_pid_layout(nodes, normalized_edges)
    subsystem_areas = layout.get("subsystem_areas", [])

    # Generate Vector SVG preview with sub-system boxes and rich tooltips
    svg_preview = generate_pid_svg(nodes, normalized_edges, layout, project_type=project_type)

    # Validation is recomputed here, after every change, rather than trusted
    # from whoever produced the graph.
    store = PIDGraphStore({"nodes": nodes, "edges": normalized_edges})
    validation = store.validate_drawing()
    validation["loops"] = [{"loop_id": l["loop_id"], "status": l["status"]}
                           for l in store.get_loops()]

    result = {
        "project_type": project_type,
        "nodes": nodes,
        "edges": normalized_edges,
        "layout": layout,
        "subsystem_areas": subsystem_areas,
        "summary": raw_graph.get("summary", f"{project_type.capitalize()} P&ID Topology"),
        "svg_preview": svg_preview,
        "generation_path": raw_graph.get("generation_path"),
        "validation": validation,
        # Counted after enrichment, which can promote nodes to bom_selection.
        "spec_status_counts": summarize_spec_status(nodes),
        "notes": raw_graph.get("notes") or [],
        "pending_action": raw_graph.get("pending_action"),
    }
    return PIDGraph.model_validate(result).model_dump(by_alias=True)


def build_pid_from_solution(
    requirements: str,
    designed_solution: dict[str, Any] | None,
    instruments: list[dict[str, Any]],
    accessories: list[dict[str, Any]],
    sub_systems: list[dict[str, Any]] | None = None,
    project_type: str | None = None,
    active_pid_graph: dict[str, Any] | None = None,
    *,
    user_id: int | None = None,
    plant_group: tuple[str, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """
    Central P&ID Dispatcher:
    1. Routes the request: greenfield, brownfield retrofit, or an in-place
       modification of the active drawing (route_pid_intent).
    2. For a modification, makes sure the engineer has said which subsystem
       new equipment goes into (subsystem_gate); when they have not, the
       drawing comes back unchanged with a subsystem_choice pending_action.
    3. Synthesizes or modifies the topology through the tool-loop agents.
    4. Renders layout and SVG (render_graph).

    plant_group: the engineer's answer when resuming a subsystem question --
    ("select", candidate) or ("none", None). The gate is skipped when given.
    """
    from domain.solution.agents.greenfield_pid_agent import GreenfieldPIDAgent
    from domain.solution.agents.brownfield_pid_agent import BrownfieldPIDAgent

    if project_type:
        resolved_intent, reason = project_type, "given"
    else:
        resolved_intent, reason = route_pid_intent(
            requirements=requirements,
            context=(designed_solution or {}).get("project_objective", ""),
            active_pid_graph=active_pid_graph,
        )
    logging.info(f"[PID_DISPATCHER] Dispatching P&ID synthesis to intent: "
                 f"{resolved_intent.upper()} ({reason})...")

    if resolved_intent == "brownfield_update" and active_pid_graph:
        from domain.solution.services import subsystem_gate as SG
        from domain.solution.services.pid_graph_store import PIDGraphStore

        agent_request = requirements
        chosen: dict[str, Any] | None = None
        if plant_group is None:
            verdict = SG.check(PIDGraphStore(active_pid_graph), requirements)
            if verdict["status"] == "ask":
                logging.info(f"[PID_DISPATCHER] Subsystem not stated ({verdict['reason']}); "
                             f"asking the engineer before modifying the drawing")
                waiting = {
                    **active_pid_graph,
                    "summary": verdict["question"],
                    "generation_path": "awaiting_clarification",
                    "notes": [],
                    "pending_action": {
                        "kind": SG.KIND,
                        "question": verdict["question"],
                        "candidates": verdict["candidates"],
                        "request": requirements,
                    },
                }
                return render_graph(waiting, active_pid_graph.get("project_type") or "brownfield",
                                    enrich=False)
            chosen = verdict.get("candidate")
            agent_request += verdict.get("note") or ""
        else:
            outcome, chosen = plant_group
            agent_request += SG.dispatch_note(chosen if outcome == "select" else None)

        raw_graph = BrownfieldPIDAgent.update_existing_pid(
            existing_graph=active_pid_graph,
            modification_prompt=agent_request,
            instruments=instruments,
            accessories=accessories,
            sub_systems=[{"name": chosen["name"]}] if chosen else sub_systems,
            user_id=user_id,
        )
        resolved_proj_type = "brownfield"
    elif resolved_intent in ["brownfield", "brownfield_new"]:
        raw_graph = BrownfieldPIDAgent.generate_brownfield_pid(
            requirements=requirements,
            designed_solution=designed_solution,
            instruments=instruments,
            accessories=accessories,
            sub_systems=sub_systems,
            user_id=user_id,
        )
        resolved_proj_type = "brownfield"
    else:
        raw_graph = GreenfieldPIDAgent.generate_greenfield_pid(
            requirements=requirements,
            designed_solution=designed_solution,
            instruments=instruments,
            accessories=accessories,
            sub_systems=sub_systems,
            user_id=user_id,
        )
        resolved_proj_type = "greenfield"

    validated = render_graph(raw_graph, resolved_proj_type, instruments=instruments,
                             accessories=accessories, designed_solution=designed_solution)
    logging.info(
        f"[PID_DISPATCHER] ✓ {resolved_proj_type.capitalize()} P&ID Graph compiled "
        f"via {validated.get('generation_path') or 'unknown'}: "
        f"{len(validated['nodes'])} nodes, {len(validated['edges'])} edges, "
        f"{len(validated['subsystem_areas'])} sub-system areas, "
        f"specs {validated['spec_status_counts']}"
        + (f", pending {validated['pending_action']['kind']}" if validated.get("pending_action") else "")
    )
    return validated
