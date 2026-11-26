"""
ISA-5.1 / ISO 10628 Dynamic Instrument & Equipment Classifier for studio.
Provides formal ISA-5.1 grammar parsing and multi-tier semantic metadata resolution.
"""

from __future__ import annotations

import re
from typing import Any

# Measured / Initiating Variables (First Letter in ISA-5.1)
ISA_MEASURED_VARIABLES: dict[str, str] = {
    "A": "Analysis",
    "B": "Burner / Combustion",
    "C": "User's Choice",
    "D": "Differential (Modifier)",
    "E": "Voltage",
    "F": "Flow Rate",
    "G": "User's Choice (Gauging)",
    "H": "Hand / Manual",
    "I": "Current",
    "J": "Power",
    "K": "Time / Schedule",
    "L": "Level",
    "M": "Moisture / Humidity",
    "N": "User's Choice",
    "O": "User's Choice",
    "P": "Pressure / Vacuum",
    "Q": "Quantity / Totalize",
    "R": "Radiation",
    "S": "Speed / Frequency",
    "T": "Temperature",
    "U": "Multivariable",
    "V": "Vibration / Mechanical",
    "W": "Weight / Force",
    "X": "Unclassified / Safety",
    "Y": "Event / State",
    "Z": "Position / Dimension",
}

# Modifiers (Second Letter if present)
ISA_MODIFIERS: dict[str, str] = {
    "D": "Differential",
    "F": "Ratio / Fraction",
    "M": "Momentary",
    "Q": "Integrate / Totalize",
    "S": "Safety / Interlock",
    "Z": "Emergency",
}

# Mechanical / Plant Equipment Prefixes
MECHANICAL_EQUIPMENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:TK|DRUM|VESSEL|TANK|ACCUMULATOR)[-_]?", re.IGNORECASE), "vessel"),
    (re.compile(r"^V[-_]?\d+", re.IGNORECASE), "vessel"),
    (re.compile(r"^(?:PUMP|PU)[-_]?", re.IGNORECASE), "pump"),
    (re.compile(r"^P[-_]?\d+", re.IGNORECASE), "pump"),
    (re.compile(r"^(?:HEX|HX|HEATER|COOLER|CONDENSER|REBOILER)[-_]?", re.IGNORECASE), "heat_exchanger"),
    (re.compile(r"^(?:HE|E)[-_]?\d+", re.IGNORECASE), "heat_exchanger"),
    (re.compile(r"^(?:COL|COLUMN|TOWER)[-_]?", re.IGNORECASE), "column"),
    (re.compile(r"^C[-_]?\d+", re.IGNORECASE), "column"),
    (re.compile(r"^(?:RX|REACTOR)[-_]?", re.IGNORECASE), "reactor"),
    (re.compile(r"^R[-_]?\d+", re.IGNORECASE), "reactor"),
    (re.compile(r"^(?:FLT|STR|STRAINER|FILTER)[-_]?", re.IGNORECASE), "filter"),
    (re.compile(r"^(?:PSV|PRV|RV|SAFETY[-_]?VALVE)[-_]?", re.IGNORECASE), "relief"),
    (re.compile(r"^(?:NRV|CKV|CHECK[-_]?VALVE)[-_]?", re.IGNORECASE), "checkvalve"),
    (re.compile(r"^(?:TP|TIE[-_]?IN|NOZZLE)[-_]?", re.IGNORECASE), "tie_in"),
    (re.compile(r"^(?:INLET|OUTLET|BATTERY[-_]?LIMIT|HDR|HEADER)[-_]?", re.IGNORECASE), "off_page_connector"),
    (re.compile(r"^(?:MNF|MANIFOLD)[-_]?", re.IGNORECASE), "manifold"),
    (re.compile(r"^(?:SYP|SIP|SIPHON|SYPHON)[-_]?", re.IGNORECASE), "siphon"),
    (re.compile(r"^(?:TW|WELL|THERMOWELL)[-_]?", re.IGNORECASE), "thermowell"),
    (re.compile(r"^(?:POS|POSITIONER)[-_]?", re.IGNORECASE), "positioner"),
    (re.compile(r"^(?:ACT|ACTUATOR)[-_]?", re.IGNORECASE), "actuator"),
    (re.compile(r"^(?:AFR|AIR[-_]?FILTER)[-_]?", re.IGNORECASE), "regulator"),
    (re.compile(r"^(?:SOV|SOLENOID)[-_]?", re.IGNORECASE), "switch"),
]

# Regex pattern for ISA-5.1 Functional Lettering
ISA_TAG_REGEX = re.compile(
    r"^(?:(?P<unit>\d+)[-_/])?"                     # Optional Plant Unit Prefix (e.g. "100-", "01")
    r"(?P<letters>[A-Za-z]{2,5})"                   # ISA Letters (e.g. "PDT", "PCV", "XV", "FIC")
    r"(?:[-_/]?(?P<loop>\d+))?"                     # Loop Number (e.g. "201", "101")
    r"(?P<suffix>[A-Za-z])?$",                      # Optional Suffix (e.g. "A", "B")
    re.IGNORECASE,
)


def parse_isa_tag(tag: str) -> dict[str, Any]:
    """Parses an ISA-5.1 tag string into its constituent grammar components."""
    cleaned = (tag or "").strip()
    match = ISA_TAG_REGEX.match(cleaned)
    if not match:
        return {"raw_tag": cleaned, "is_isa_standard": False}

    unit = match.group("unit") or ""
    letters = match.group("letters").upper()
    loop = match.group("loop") or ""
    suffix = match.group("suffix") or ""

    first_char = letters[0]
    measured_var = ISA_MEASURED_VARIABLES.get(first_char, "Unclassified")

    rem = letters[1:]
    modifier = ""
    
    if rem.startswith("SV"):
        modifier = "Safety"
        function_letters = "V"
    elif len(rem) >= 2 and rem[0] in ["D", "F", "Q"]:
        modifier = ISA_MODIFIERS.get(rem[0], "")
        function_letters = rem[1:]
    else:
        function_letters = rem

    return {
        "raw_tag": cleaned,
        "is_isa_standard": True,
        "unit_prefix": unit,
        "letters": letters,
        "first_letter": first_char,
        "measured_variable": measured_var,
        "modifier": modifier,
        "function_letters": function_letters,
        "loop_number": loop,
        "suffix": suffix,
    }


def classify_node_kind(
    tag: str = "",
    category: str = "",
    asset_metadata: dict[str, Any] | None = None,
) -> str:
    """Multi-Tier Dynamic Classifier for P&ID Nodes (ISA-5.1 / ISO 10628)."""
    tag_clean = (tag or "").strip()
    tag_u = tag_clean.upper()
    cat_u = (category or "").upper()
    meta = asset_metadata or {}
    
    meta_type = str(meta.get("asset_type") or meta.get("category") or "").upper()
    meta_name = str(meta.get("asset_name") or meta.get("product_name") or "").upper()
    meta_model = str(meta.get("model") or "").upper()
    combined_semantics = f"{cat_u} {meta_type} {meta_name} {meta_model}".strip()

    # 1. Semantic Metadata Resolution
    if "TIE-IN" in combined_semantics or "TIE IN" in combined_semantics or "TIEIN" in combined_semantics:
        return "tie_in"
    if "MANIFOLD" in combined_semantics:
        return "manifold"
    if "SIPHON" in combined_semantics or "SYPHON" in combined_semantics:
        return "siphon"
    if "THERMOWELL" in combined_semantics:
        return "thermowell"
    if "POSITIONER" in combined_semantics:
        return "positioner"
    if "ACTUATOR" in combined_semantics:
        return "actuator"
    if "AIR FILTER" in combined_semantics or "FILTER REGULATOR" in combined_semantics:
        return "regulator"
    if "SOLENOID" in combined_semantics:
        return "switch"
    if "SAFETY VALVE" in combined_semantics or "RELIEF VALVE" in combined_semantics or "PSV" in combined_semantics:
        return "relief"
    if "CHECK VALVE" in combined_semantics or "NON-RETURN" in combined_semantics:
        return "checkvalve"
    if "CONTROL VALVE" in combined_semantics or "GLOBE VALVE" in combined_semantics or "BUTTERFLY VALVE" in combined_semantics or "BALL VALVE" in combined_semantics or "ISOLATION VALVE" in combined_semantics:
        return "valve"
    if "CONTROLLER" in combined_semantics or "PID BLOCK" in combined_semantics:
        return "controller"
    if "PUMP" in combined_semantics:
        return "pump"
    if "EXCHANGER" in combined_semantics or "HEATER" in combined_semantics or "COOLER" in combined_semantics:
        return "heat_exchanger"
    if "VESSEL" in combined_semantics or "DRUM" in combined_semantics or "TANK" in combined_semantics:
        return "vessel"
    if "COLUMN" in combined_semantics or "TOWER" in combined_semantics:
        return "column"
    if "REACTOR" in combined_semantics:
        return "reactor"
    if "FILTER" in combined_semantics or "STRAINER" in combined_semantics:
        return "filter"
    if "SWITCH" in combined_semantics:
        return "switch"
    if "TRANSMITTER" in combined_semantics or "FLOW METER" in combined_semantics or "PRESSURE SENSOR" in combined_semantics or "LEVEL SENSOR" in combined_semantics or "TEMPERATURE SENSOR" in combined_semantics:
        return "transmitter"

    # 2. Mechanical Equipment Prefix Resolution
    norm_tag = re.sub(r"^\d+[-_/]", "", tag_clean)
    for pattern, kind in MECHANICAL_EQUIPMENT_PATTERNS:
        if pattern.search(norm_tag):
            return kind

    # 3. Formal ISA-5.1 Functional Lettering Grammar
    parsed = parse_isa_tag(tag_clean)
    if parsed.get("is_isa_standard"):
        funcs = parsed.get("function_letters", "")
        letters = parsed.get("letters", "")
        first_letter = parsed.get("first_letter", "")

        if "V" in funcs:
            if "SV" in letters or first_letter == "P" and "S" in letters and "V" in letters:
                return "relief"
            return "valve"
        if "C" in funcs:
            return "controller"
        if "S" in funcs or letters.endswith("SH") or letters.endswith("SL") or letters.endswith("S"):
            return "switch"
        if "T" in funcs:
            return "transmitter"
        if "Y" in funcs:
            return "positioner"
        if "Z" in funcs:
            return "actuator"
        if "E" in funcs:
            return "transmitter"
        if "I" in funcs:
            return "indicator"

    # 4. Contextual Fallback
    if tag_u.startswith("HV") or tag_u.startswith("XV") or tag_u.startswith("BV") or "VALVE" in tag_u:
        return "valve"
    if "TRANSMITTER" in tag_u or tag_u.endswith("T"):
        return "transmitter"
    if "CONTROLLER" in tag_u or tag_u.endswith("C"):
        return "controller"

    return "transmitter"
