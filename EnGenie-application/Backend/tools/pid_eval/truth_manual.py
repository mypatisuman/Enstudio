"""Hand-read ground truth (tags printed on the drawing + expected symbol type + inferred valves)."""
TRUTH = {
    "pid3": {
        "equipment": {"M-116": "mixer", "R-110A": "vessel", "R-110B": "vessel", "HE-112": "heat_exchanger",
                      "V-113": "vessel", "F-114": "filter", "F-111": "filter"},
        "instruments": """HV-1066 PSV-1111 PI-1180 PI-1110 HV-1150 XY-1150 HV-1152 CK-1152 PSV-1140 HV-1153 XY-1160
            IHP-1101 PIT-1101 TI-1102 TE-1102 HV-1155 XY-1155 HV-1170 CK-1171 PSV-1100 HV-1165 XY-1165 IHP-1104
            PIT-1104 TI-1105 TE-1105 HV-1113 HV-1114 CK-1150 TE-1121 TE-1122 HV-1143 NV-1144 HV-1141 HV-1173
            TI-1103A TI-1103B TI-1103C TI-1103D TI-1103E TI-1103F TI-1103G TI-1103H TE-1103 HV-1154 HV-1151 XY-1151
            HV-1161 XY-1161 HV-1171 CK-1114 HV-1125 CK-1124 PI-1120 PCV-1121 HV-1123 FIC-1108 FTC-1108 FE-1108
            TI-1107A TI-1107B TI-1107C TI-1107D TI-1107E TI-1107F TI-1107G TI-1107H TE-1107 HV-1156 HV-1158
            XY-1156 HV-1166 XY-1166 BPR-1130 HV-1175 PCV-1172 HV-1176""".split(),
        "inferred": ["FCV-1108"],
        "not_symbols": ["FE-1205"],                 # "BYPASS TO FE-1205": off-sheet reference
        "line_labels": [],
    },
    "pid13": {
        "equipment": {"V-101": "vessel", "C-102": "compressor", "V-103": "vessel", "F-1009": "filter", "F-1008": "filter"},
        "instruments": """HV-1001 XV-1001 XY-1001 HS-1001 PI-1001 PCV-1003 PI-1005 PIT-1007 PI-1007 IHP-1007 IHA-1021
            IHA-1022 IHP-1014 IHP-3016 IHP-1015 IHL-4001 HV-1020 XY-1020 HS-1020 HV-1022 PI-1021 PIT-1014 PI-1014
            PI-1019 PCV-1013 PI-1011 PIT-1015 PI-1015 PSV-1023 FI-1009 FY-1009 FTC-1009 FE-1009 CK-1003 DI-1017
            FIC-1017 FIT-1017 FE-1017 FY-1017 FV-1017 CK-1006 HV-1002 XV-1002 XY-1002 HS-1002 PI-1004 PIT-1006
            PI-1006 IHP-1006 FRC-1008 FI-1008 FY-1008 FTC-1008 FE-1008 CK-1004 PCV-1019 PCV-1018 HS-1010 XY-1010
            XV-1010 PI-1012 FI-1016 DI-1016 FIT-1016 FE-1016 CK-1005 HV-1021 AI-1021 AIT-1021 AE-1021 AI-1022
            AIT-1022 AE-1022""".split(),
        "inferred": ["FCV-1009", "FCV-1008"],
        "not_symbols": [],
        "line_labels": ["H-1001", "IA-1002", "RV-1007", "PG-1005", "CO2-1003", "PG-1004", "PG-1006"],
    },
}

# ── Unseen drawings, read by hand before any run (code frozen at md5 4af2a9cd) ──
_IH_CLUSTER_14 = """IHT-2001A IHT-2002A IHT-3001 IHT-3002 IHT-3003 IHT-3004 IHT-3005 IHT-3006 IHT-3007 IHT-3008
    IHT-3009 IHT-3010 IHT-3011 IHT-3012 IHT-3013 IHT-3014 IHT-3015 IHT-4002 IHA-1021 IHA-1022""".split()
TRUTH["pid14"] = {
    "equipment": {"HE-201": "heat_exchanger", "HE-202": "heat_exchanger"},
    "instruments": """TI-2001B TAHH-2001B ICTH-2001B TE-2001B TSH-2001 JE-2001 TY-2001 EY-2001 IHTS-2001B TIC-2001A
        TI-2002B TAHH-2002B ICTH-2002B TE-2002B TSH-2002 JE-2002 TY-2002 EY-2002 TIC-2002A""".split() + _IH_CLUSTER_14,
    "inferred": [],
    "optional": ["TE-2001A", "TE-2002A"],          # signal connectors labelled with the remote tag
    "not_symbols": [],
    "line_labels": ["H2-1001", "PG-1005", "H2-2001", "PG-2002"],
    "headers": ["METERED H2", "METERED CO2/RECYCLE GAS", "TE-2001A", "TE-2002A", "TO REACTOR (x2)"],
}
TRUTH["pid15"] = {
    "equipment": {"R-301": "vessel", "HE-302": "heat_exchanger", "Z-303": "other"},
    "instruments": ("""TE-2001A TE-2002A PSV-3017 PIT-3016 PI-3016 IHP-3016 FIC-3021 FIC-3022 FIC-3023 FIC-3024
        FIC-3025 FIC-3026 TIS-3031B IHTS-3031B EY-3031 TY-3031 JEF-3031 TIC-3031A IHT-3031A TW-3000
        IHT-4002 IHA-1021 IHA-1022""".split()
        + [f"{p}-30{i:02d}" for i in range(1, 16) for p in ("TE", "TI", "IHT")]),
    "inferred": [],
    "optional": ["TIC"],                          # "TIC / Local temp" bubble inside Z-303, no number
    "not_symbols": ["TIC-2001", "TIC-2002"],      # "TO TIC-2001" signal flags
    "line_labels": ["H2-2001", "PG-2002", "RV-3005", "CWS-3006", "CWS-3003", "CWS-3007", "CWR-3004",
                    "PG-3001", "PL/PG-3002"],
    "headers": ["PREHEATED H2", "SIGNAL TO TIC-2001", "SIGNAL TO TIC-2002", "PREHEATED CO2", "RELIEF HEADER",
                "WATER MANUAL ADDITION", "TO SEPARATOR"],
}
TRUTH["pid16"] = {
    "equipment": {"V-401": "vessel", "V-402": "vessel", "F-403": "filter", "F-4004": "filter",
                  "F-4005": "filter", "F-4006": "filter"},
    "instruments": """PIC-4003 PIT-4003 FI-4005 DI-4005 FIT-4005 FE-4005 PI-4007 PCV-4006 PI-4009 JER-4006 PY-4003
        PV-4003 HV-4004 HV-4005 HV-4006 HV-4008 HV-4009 HV-4010 CK-4001 AE-4008 JER-4001 IHT-4002 TI-4002
        TE-4002 LG-4010 LIT-4001 HV-4011 HV-4007 DI-4004 FI-4004 FQ-4004 FIT-4004 FE-4004 IHL-4001 LIC-4001
        LY-4001 LV-4001 HV-4001 HV-4002 HV-4003""".split(),
    "inferred": [],
    "optional": ["TP"],
    "not_symbols": ["HE-302"],                    # "157-1-130 / HE-302" is the incoming connector
    "line_labels": ["PL/PG-3002", "PL-4001", "PG-4003", "PG-4004", "PG-4005", "PG-4006", "PL-4002",
                    "PG-4007", "PG-4008"],
    "headers": ["HE-302 (from)", "VENT (x2)", "GAS RECYCLE", "IAS (x2)"],
}
TRUTH["pid18"] = {
    "equipment": {"V-103": "vessel", "C-102": "compressor", "C-104": "compressor", "M-1010": "other",
                  "M-1012": "other", "F-1001": "filter", "F-1002": "filter", "F-1003": "filter",
                  "F-1004": "filter", "F-1005": "filter", "FAN-102": "other", "FAN-104": "other"},
    "instruments": """HV-1001 XV-1001 XY-1001 HS-1001 PI-1020 PCV-1003 PIT-1007 PI-1007 PSV-1016 HV-1012
        FIC-1009 FIT-1009 FE-1009 FY-1009 FV-1009 CK-1003 CK-1013
        HV-1002 XV-1002 XY-1002 HS-1002 PI-1004 CK-1004 PIT-1006 PI-1006 PCV-1013 PIT-1015 PI-1015
        TE-1036A PSV-1038 FIC-1008 FIT-1008 FE-1008 FY-1008 FV-1008 CK-1010 HV-1014
        PT-1022 PI-1022 PI-1023 HV-1005 PSV-1021 PSV-1025 PT-1026 PI-1027 HV-1006 CK-1007 TE-1024
        PSV-1028 PT-1029 PI-1030 HV-1008 PSV-1031 PSV-1033 PI-1035 PT-1034 HV-1009 TE-1032 PI-1034
        OA-1010 AUTO-1010 HS-1010 EY-1010 YI-1010 IN-1010 TI-1024 PI-1026 PI-1029
        YI-1012 EY-1012 HS-1012 IN-1012 TI-1032 FRC-1512
        IHP-1007 IHP-1015 IHP-3002 IHP-1505 IHF-1009 IHP-1022 IHP-1504 IHL-4001 IHT-1516 IHP-1029
        ICPH-1506 IHA-9905 IHA-9906 IHP-1006""".split(),
    "inferred": [],
    "optional": [],
    "not_symbols": [],
    "line_labels": [],
    "headers": [],
}
TRUTH["pid19"] = {
    "equipment": {"C-150": "compressor", "V-151": "vessel", "V-152": "vessel", "HE-153": "heat_exchanger"},
    "instruments": """PSV-1514 PSV-1515 IHTS-1517B IHT-1517A TE-1517A TIC-1517A JE-1517 TY-1517 EY-1517 TE-1517B
        TIS-1517B TI-1513 FRC-1512 FI-1512 FIT-1512 FE-1512 IHP-1505 PI-1505 PIT-1505 CK-1505 CK-1506 HV-1504
        FI-1510 PV-1504 PY-1504 PIC-1504 IHP-1504 PIT-1504 FIC-1503 FIT-1503 FE-1503 FY-1503 FV-1503
        IHT-1516 TI-1516 TE-1516 PI-1507 PSH-1506 PAHH-1506 ICPH-1506 HV-1501 HV-1503 JEL-1520 JEL-1521
        PI-1522 PSL-1519 PALL-1519 ICPL-1519 M-1508 YI-1508 EY-1508 HS-1508 AUTO-1508 OA-1508 IN-1508
        IHP-1022 IHP-1015 IHP-1029 IHP-3002 IHL-4001""".split(),
    "inferred": [],
    "optional": ["JE-M-1518", "JEM-1518", "JE-1518"],   # printed "JE-M / 1518"
    "not_symbols": ["FIC-1008", "V-401", "C-104", "HE-202", "V-1501"],   # connector refs; V-1501 is a line no.
    "line_labels": ["RV-1511", "RV-1512", "GLR-1510", "GLS-9002", "RV-1514", "RV-1513", "P-1505", "P-1507",
                    "P-1515", "P-1508", "P-1516", "P-4004", "CO2-1004", "P-1504", "V-1501"],
    "headers": ["RELIEF VENT HEADER (x3)", "GLR", "GLS", "RECYCLE GAS (x2)", "CO2", "SIGNAL", "VENT HEADER"],
}
_IH_CLUSTER_20 = """IHP-1022 IHP-1505 IHP-3002 IHT-4002 IHP-1029 ICHP-1506 IHT-3004 IHA-9905 IHP-1015 IHP-1504
    IHT-1516 IHL-4001 IHA-9906""".split()
TRUTH["pid20"] = {
    "equipment": {"HE-201": "heat_exchanger", "HE-202A": "heat_exchanger", "HE-202B": "heat_exchanger"},
    "instruments": [f"{p}-200{n}{s}" for n in (1, 2, 3) for p, s in
                    (("IHT", "A"), ("IHTS", "B"), ("TIC", "A"), ("EY", ""), ("TY", ""), ("JE", ""),
                     ("TE", "B"), ("TW", "B"), ("TIS", "B"))] + ["TE-2002A", "CK-2001", "CK-2002"] + _IH_CLUSTER_20,
    "inferred": [],
    "optional": ["JE-M-2004", "JEM-2004", "JE-2004", "TE-2001A", "TE-2003A"],
    "not_symbols": ["C-150", "R-301"],
    "line_labels": ["H-1001", "H-2001", "P-2002", "P-1508", "P-2003"],
    "headers": ["SIGNAL TE-2001A", "SIGNAL TE-2003A", "METERED H2", "METERED CO2/RECYCLE GAS",
                "PREHEATED H2", "PREHEATED RECYCLE GAS"],
}


# ── synthetic drawings (synth/generate.py): their truth is written beside the image ──
import json as _json
from pathlib import Path as _Path
for _f in sorted((_Path(__file__).resolve().parent / "synth" / "out").glob("*.json")):
    _d = _json.loads(_f.read_text(encoding="utf-8"))
    TRUTH[_d["name"]] = _d["tags"]


def truth_key(name: str, keys) -> str:
    """The truth entry a run name belongs to: the longest key it starts with
    ("pid13L3" -> "pid13", "sync001G" -> "sync001")."""
    hits = [k for k in keys if name.startswith(k)]
    if not hits:
        raise KeyError(f"no truth for {name}")
    return max(hits, key=len)
