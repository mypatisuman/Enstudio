"""Hand-read connection lists (read off the drawings, not from any run).

required  a link drawn directly between two tagged symbols (pipe order: a gauge
          tapping a run sits in series on it; a signal / leader line; symbols
          drawn touching)
optional  not counted either way: siblings at an unmarked tee or junction,
          links through an unlabelled symbol, interlock cause-list links
FLAGS     off-sheet flags by position (canvas frame, x 0..1000): a read flag is
          renamed to the nearest entry within 60 units, whatever it was called
"""
import itertools

P = lambda *pairs: {tuple(sorted(p)) for p in pairs}
ALL = lambda *tags: {tuple(sorted(p)) for p in itertools.combinations(tags, 2)}

CONN = {
    "pid13": {
        "flags": {"HYDROGEN": (99, 159), "AIR": (99, 246), "CO2": (99, 428), "RECYCLE": (99, 519),
                  "TO-PREHEATER-TOP": (909, 157), "TO-VENT": (909, 181), "TO-PREHEATER-LOW": (910, 241)},
        "required": P(
            # hydrogen line
            ("HYDROGEN", "HV-1001"), ("HV-1001", "XV-1001"), ("XV-1001", "PI-1001"), ("PI-1001", "PCV-1003"),
            ("PCV-1003", "PI-1005"), ("PI-1005", "PIT-1007"), ("PIT-1007", "F-1009"), ("F-1009", "FE-1009"),
            ("FE-1009", "FCV-1009"), ("FCV-1009", "CK-1003"), ("CK-1003", "TO-PREHEATER-TOP"),
            ("XY-1001", "XV-1001"), ("HS-1001", "XY-1001"), ("PIT-1007", "PI-1007"), ("PI-1007", "IHP-1007"),
            ("FTC-1009", "FE-1009"), ("FTC-1009", "FI-1009"), ("FTC-1009", "FY-1009"), ("FTC-1009", "FCV-1009"),
            # air line
            ("AIR", "HV-1020"), ("HS-1020", "XY-1020"), ("PI-1021", "HV-1021"), ("HV-1021", "C-102"),
            # suction / compressor / discharge
            ("PIT-1014", "PI-1014"), ("PI-1014", "IHP-1014"), ("V-101", "C-102"), ("C-102", "V-103"),
            ("PI-1019", "PCV-1013"), ("PCV-1013", "PI-1011"), ("PI-1011", "PIT-1015"),
            ("V-103", "PSV-1023"), ("V-103", "FE-1017"), ("PSV-1023", "TO-VENT"),
            ("FE-1017", "FV-1017"), ("FV-1017", "CK-1006"), ("CK-1006", "TO-PREHEATER-LOW"),
            ("PIT-1015", "PI-1015"), ("PI-1015", "IHP-1015"), ("FE-1017", "FIT-1017"), ("FIT-1017", "DI-1017"),
            ("FIT-1017", "FIC-1017"), ("FIC-1017", "FY-1017"), ("FY-1017", "FV-1017"),
            # CO2 line
            ("CO2", "HV-1002"), ("HV-1002", "XV-1002"), ("XV-1002", "PI-1004"), ("PI-1004", "PIT-1006"),
            ("PIT-1006", "F-1008"), ("F-1008", "FE-1008"), ("FE-1008", "FCV-1008"), ("FCV-1008", "CK-1004"),
            ("XY-1002", "XV-1002"), ("HS-1002", "XY-1002"), ("PIT-1006", "PI-1006"), ("PI-1006", "IHP-1006"),
            ("FTC-1008", "FE-1008"), ("FTC-1008", "FI-1008"), ("FTC-1008", "FY-1008"), ("FTC-1008", "FCV-1008"),
            ("FRC-1008", "FY-1008"), ("FRC-1008", "FI-1016"),
            # recycle line
            ("RECYCLE", "XV-1010"), ("XV-1010", "PI-1012"), ("PI-1012", "FE-1016"), ("FE-1016", "CK-1005"),
            ("CK-1005", "PCV-1018"), ("CK-1005", "PCV-1019"), ("XY-1010", "XV-1010"), ("HS-1010", "XY-1010"),
            ("FE-1016", "FIT-1016"), ("FIT-1016", "FI-1016"), ("FIT-1016", "DI-1016"),
            # analysers
            ("AE-1021", "AIT-1021"), ("AIT-1021", "AI-1021"), ("AI-1021", "IHA-1021"),
            ("AE-1022", "AIT-1022"), ("AIT-1022", "AI-1022"), ("AI-1022", "IHA-1022"),
        ),
        "optional": (
            ALL("CK-1004", "PCV-1018", "PCV-1019", "PIT-1014", "PI-1019", "V-101")        # suction junction
            | ALL("PIT-1015", "V-103", "PSV-1023", "FE-1017")                              # discharge tee
            | ALL("AIR", "HV-1020", "HV-1022", "PI-1021", "XY-1020")                       # XV-1020 unlabelled + bypass
            | P(("PI-1021", "C-102"), ("PCV-1019", "PCV-1018"))
            | {tuple(sorted((hs, i))) for hs in ("HS-1001", "HS-1002", "HS-1020", "HS-1010")
               for i in ("IHP-1007", "IHA-1021", "IHA-1022", "IHP-1014", "IHP-3016", "IHP-1015", "IHL-4001",
                         "IHP-1006")}
            | P(("HYDROGEN", "XV-1001"), ("CO2", "XV-1002"), ("RECYCLE", "PI-1012"))   # TP test points
        ),
    },
    "pid15": {
        "flags": {"PREHEATED-H2": (99, 101), "SIGNAL-2001": (99, 118), "SIGNAL-2002": (99, 166),
                  "PREHEATED-CO2": (99, 187), "RELIEF": (919, 85), "WATER": (919, 131),
                  "TO-SEPARATOR": (919, 398)},
        "required": (
            P(("PREHEATED-H2", "R-301"), ("PREHEATED-CO2", "R-301"),
              ("SIGNAL-2001", "TE-2001A"), ("SIGNAL-2002", "TE-2002A"),
              ("R-301", "PSV-3017"), ("R-301", "PIT-3016"), ("PSV-3017", "RELIEF"),
              ("PIT-3016", "PI-3016"), ("PI-3016", "IHP-3016"),
              ("WATER", "Z-303"), ("FIC-3026", "HE-302"),
              ("R-301", "HE-302"), ("HE-302", "TO-SEPARATOR"), ("TW-3000", "R-301"),
              ("TIS-3031B", "IHTS-3031B"), ("TY-3031", "TIC-3031A"), ("TIC-3031A", "IHT-3031A"),
              ("TIC-3031A", "TE-3008"), ("EY-3031", "TY-3031"), ("TY-3031", "JEF-3031"), ("JEF-3031", "R-301"),
              ("EY-3031", "IHTS-3031B"))
            | {tuple(sorted((f"FIC-302{i}", "R-301"))) for i in range(1, 6)}
            | {tuple(sorted((f"TE-30{i}", "R-301"))) for i in range(11, 16)}
            | {tuple(sorted((f"TIS-3031B", f"TE-30{i}"))) for i in range(11, 16)}
            | {tuple(sorted((f"TE-30{i:02d}", f"TI-30{i:02d}"))) for i in range(1, 16)}
            | {tuple(sorted((f"TI-30{i:02d}", f"IHT-30{i:02d}"))) for i in range(1, 16)}
        ),
        "optional": (
            ALL("Z-303", "HE-302", "R-301", *[f"FIC-302{i}" for i in range(1, 7)])       # cooling-water headers
            | ALL("PREHEATED-H2", "PREHEATED-CO2", "TE-2001A", "TE-2002A", "R-301")      # inlet tees
            | ALL("TW-3000", *[f"TE-30{i:02d}" for i in range(1, 11)])                  # stacked multipoint TE
            | ALL("TIS-3031B", *[f"TE-30{i}" for i in range(11, 16)])                    # the switch's signal bus
            | {tuple(sorted((c, "TIC-3031A"))) for c in ("IHT-3031A", "IHTS-3031B", "IHA-1021", "IHA-1022",
                                                        "IHT-4002", *[f"IHT-30{i:02d}" for i in range(1, 16)])}
        ),
    },
}


# ── synthetic drawings (synth/generate.py) ──
import json as _json
from pathlib import Path as _Path
for _f in sorted((_Path(__file__).resolve().parent / "synth" / "out").glob("*.json")):
    _d = _json.loads(_f.read_text(encoding="utf-8"))
    _c = _d["connections"]
    CONN[_d["name"]] = {"flags": {k: tuple(v) for k, v in _c["flags"].items()},
                        "required": {tuple(sorted(p)) for p in _c["required"]},
                        "optional": {tuple(sorted(p)) for p in _c.get("optional") or []}}
