"""
ISA-5.1 / ISO 10628 Dynamic Instrument & Equipment Classifier.
Provides formal ISA-5.1 grammar parsing and multi-tier semantic metadata resolution.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# ISA-5.1 Grammar Definitions
# ---------------------------------------------------------------------------

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

# Mechanical / Plant Equipment Prefixes (Single letter + numbers, or keyword prefixes)
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

# Regex pattern for ISA-5.1 Functional Lettering:
# Matches tags like: "100-PDT-201A", "01PT101", "PT-201", "XV-2001", "FIC_101", "20-FCV-101"
ISA_TAG_REGEX = re.compile(
    r"^(?:(?P<unit>\d+)[-_/])?"                     # Optional Plant Unit Prefix (e.g. "100-", "01")
    r"(?P<letters>[A-Za-z]{2,5})"                   # ISA Letters (e.g. "PDT", "PCV", "XV", "FIC")
    r"(?:[-_/]?(?P<loop>\d+))?"                     # Loop Number (e.g. "201", "101")
    r"(?P<suffix>[A-Za-z])?$",                      # Optional Suffix (e.g. "A", "B")
    re.IGNORECASE,
)


def parse_isa_tag(tag: str) -> dict[str, Any]:
    """
    Parses an ISA-5.1 tag string into its constituent grammar components:
      - unit_prefix: e.g. "100"
      - letters: e.g. "PDT"
      - measured_variable: e.g. "P" (Pressure)
      - modifier: e.g. "D" (Differential)
      - function_letters: e.g. "T" (Transmitter)
      - loop_number: e.g. "201"
      - suffix: e.g. "A"
    """
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
    """
    Multi-Tier Dynamic Classifier for P&ID Nodes (ISA-5.1 / ISO 10628):
      Tier 1: Explicit Semantic Asset Metadata Overrides (Flow Meter, Control Valve, etc.)
      Tier 2: Explicit Accessories & Inline Hardware (SYP, TW, MNF, POS, ACT, AFR, SOV, TP)
      Tier 3: Formal ISA-5.1 Grammar (PT, FT, TT, LT, FCV, TCV, PIC, etc.)
      Tier 4: Mechanical Equipment (Vessels, Columns, Pumps, Exchangers)
      Tier 5: Fallback
    """
    tag_clean = (tag or "").strip()
    tag_u = tag_clean.upper()
    cat_u = (category or "").upper()
    meta = asset_metadata or {}
    
    meta_type = str(meta.get("asset_type") or meta.get("category") or "").upper()
    meta_name = str(meta.get("asset_name") or meta.get("product_name") or "").upper()
    meta_model = str(meta.get("model") or "").upper()
    combined_semantics = f"{cat_u} {meta_type} {meta_name} {meta_model}".strip()

    # ──────────────────────────────────────────────────────────────────────────
    # TIER 1: EXPLICIT SEMANTIC ASSET METADATA OVERRIDES
    # ──────────────────────────────────────────────────────────────────────────
    if any(k in combined_semantics for k in ["TRANSMITTER", "FLOW METER", "PRESSURE SENSOR", "LEVEL SENSOR", "TEMPERATURE SENSOR", "MASS FLOW", "METER"]):
        return "transmitter"
    if any(k in combined_semantics for k in ["CONTROL VALVE", "GLOBE VALVE", "BUTTERFLY VALVE", "BALL VALVE", "ISOLATION VALVE", "SOLENOID VALVE", "HAND VALVE"]):
        return "valve"
    if any(k in combined_semantics for k in ["SAFETY VALVE", "RELIEF VALVE", "SAFETY RELIEF", "PSV", "PRV"]):
        return "relief"
    if any(k in combined_semantics for k in ["CHECK VALVE", "NON-RETURN", "NRV"]):
        return "checkvalve"
    if "TIE-IN" in combined_semantics or "TIE IN" in combined_semantics or "TIEIN" in combined_semantics:
        return "tie_in"
    if "POSITIONER" in combined_semantics:
        return "positioner"
    if "ACTUATOR" in combined_semantics:
        return "actuator"
    if "AIR FILTER" in combined_semantics or "FILTER REGULATOR" in combined_semantics:
        return "regulator"
    if "THERMOWELL" in combined_semantics:
        return "thermowell"
    if "MANIFOLD" in combined_semantics:
        return "manifold"
    if "SIPHON" in combined_semantics or "SYPHON" in combined_semantics:
        return "siphon"

    # ──────────────────────────────────────────────────────────────────────────
    # TIER 2: EXPLICIT ACCESSORIES, TIE-INS & INLINE HARDWARE
    # ──────────────────────────────────────────────────────────────────────────
    norm_tag = re.sub(r"^\d+[-_/]", "", tag_clean).upper()
    if norm_tag.startswith("TP"):
        return "tie_in"
    if norm_tag.startswith("SYP") or norm_tag.startswith("SIP"):
        return "siphon"
    if norm_tag.startswith("TW"):
        return "thermowell"
    if norm_tag.startswith("MNF"):
        return "manifold"
    if norm_tag.startswith("POS"):
        return "positioner"
    if norm_tag.startswith("ACT"):
        return "actuator"
    if norm_tag.startswith("AFR"):
        return "regulator"
    if norm_tag.startswith("SOV"):
        return "switch"
    if norm_tag.startswith("PSV") or norm_tag.startswith("PRV"):
        return "relief"
    if norm_tag.startswith("NRV") or norm_tag.startswith("CKV"):
        return "checkvalve"
    if norm_tag.startswith("HV") or norm_tag.startswith("XV") or norm_tag.startswith("BV") or norm_tag.startswith("SDV") or norm_tag.startswith("ESDV") or norm_tag.startswith("BDV"):
        return "valve"
    if norm_tag.startswith("INLET") or norm_tag.startswith("OUTLET") or "HEADER" in tag_u or "BATTERY" in tag_u:
        return "off_page_connector"

    # ──────────────────────────────────────────────────────────────────────────
    # TIER 3: HIGH-CONFIDENCE ISA-5.1 INSTRUMENT & VALVE TAG GRAMMAR
    # ──────────────────────────────────────────────────────────────────────────
    parsed = parse_isa_tag(tag_clean)
    if parsed.get("is_isa_standard"):
        funcs = parsed.get("function_letters", "")
        letters = parsed.get("letters", "")
        first_letter = parsed.get("first_letter", "")

        # 1. Final Control Elements (Valves: FCV, TCV, PCV, LCV)
        if "V" in funcs:
            if "SV" in letters or (first_letter == "P" and "S" in letters and "V" in letters):
                return "relief"
            return "valve"

        # 2. Controllers (FIC, PIC, TIC, LIC, SIC, AIC, XC)
        if "C" in funcs:
            return "controller"

        # 3. Switches & Interlocks (PSH, PSL, TSH, TSL, LSH, LSL, FSH, FSL, XS)
        if "S" in funcs or letters.endswith("SH") or letters.endswith("SL") or letters == "XS":
            return "switch"

        # 4. Transmitters (PT, PDT, FT, TT, LT, AT, ZT, WT)
        if "T" in funcs:
            return "transmitter"

        # 5. Positioners & Transducers (FY, TY, PY, LY)
        if "Y" in funcs:
            return "positioner"

        # 6. Actuators & Drives
        if "Z" in funcs:
            return "actuator"

        # 7. Primary Sensing Elements (FE, TE, PE, LE)
        if "E" in funcs:
            return "transmitter"

        # 8. Indicators (PI, TI, FI, LI)
        if "I" in funcs:
            return "indicator"

    # ──────────────────────────────────────────────────────────────────────────
    # TIER 4: MECHANICAL PROCESS EQUIPMENT PATTERNS
    # ──────────────────────────────────────────────────────────────────────────
    for pattern, kind in MECHANICAL_EQUIPMENT_PATTERNS:
        if pattern.search(norm_tag):
            return kind

    if "PUMP" in cat_u or "PUMP" in meta_type:
        return "pump"
    if "HEAT EXCHANGER" in cat_u or "COOLER" in cat_u or "HEATER" in cat_u or "CONDENSER" in cat_u or "REBOILER" in cat_u:
        return "heat_exchanger"
    if "COLUMN" in cat_u or "TOWER" in cat_u or (cat_u.startswith("C-") and "TRANSMITTER" not in combined_semantics):
        return "column"
    if "REACTOR" in cat_u or "VESSEL" in cat_u or "TANK" in cat_u or "DRUM" in cat_u:
        if not any(k in tag_u for k in ["PT", "LT", "TT", "FT", "AT", "FIC", "PIC", "TIC", "LIC"]):
            return "vessel"

    # ──────────────────────────────────────────────────────────────────────────
    # TIER 5: CONTEXTUAL FALLBACK
    # ──────────────────────────────────────────────────────────────────────────
    if "TRANSMITTER" in combined_semantics or "SENSOR" in combined_semantics or tag_u.endswith("T"):
        return "transmitter"
    if "CONTROLLER" in combined_semantics or tag_u.endswith("C"):
        return "controller"
    if "VALVE" in combined_semantics:
        return "valve"

    return "transmitter"

