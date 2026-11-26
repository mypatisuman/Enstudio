"""
adapters/engine/constants.py -- lookup tables, mapping dictionaries, and
compiled regexes used across the engine package.

Extracted from adapters/engine.py (Phase 10), moved verbatim -- values
unchanged, only relocated.
"""
from __future__ import annotations

import re
from pathlib import Path


# One level deeper than the old adapters/engine.py (now adapters/engine/constants.py),
# so this needs an extra .parent to still resolve to <studio>/schemas.
SCHEMA_DIR = Path(__file__).parent.parent.parent / 'schemas'


INSTRUMENT_KINDS = {
    'transmitter', 'controller', 'indicator',
    'recorder', 'switch', 'analyzer', 'element'
}


PROCESS_KINDS = {
    'vessel', 'separator', 'pump',
    'heat_exchanger', 'compressor', 'column', 'reactor',
    'absorber', 'adsorption', 'filter', 'meter', 'vendor_package', 'package'
}


MECHANICAL_KINDS = {
    'valve',        # control valves WITH positioner belong here too — positioner is the instrument
    'checkvalve',   # non-return valves — purely mechanical
    'relief',       # PSV, rupture disc — safety mechanical device
}


CONNECTOR_KINDS = {
    'off_page_connector',  # pipe run continuing to another drawing
}


ALL_KINDS = INSTRUMENT_KINDS | PROCESS_KINDS | MECHANICAL_KINDS | CONNECTOR_KINDS


ANNOTATION_BLACKLIST = {
    # Original set
    'AUTO', 'PUMP HEAD', 'COMP BASE', 'PUMP', 'MOTOR',
    'SPARE', 'FUTURE', 'TYP', 'NOTE', 'SEE', 'FROM',
    'TO', 'VENT', 'DRAIN', 'INLET', 'OUTLET', 'SUPPLY',
    'RETURN', 'BYPASS', 'LOCAL', 'REMOTE', 'PANEL',
    # Drawing / document text
    'NOTES', 'REV', 'REVISION', 'REFERENCE', 'REF', 'TYPICAL',
    'DETAIL', 'SECTION', 'AREA', 'UNIT', 'PLANT', 'SHEET', 'PAGE',
    'DRAWING', 'DWG', 'SCALE', 'DATE', 'BY', 'CHK', 'APPD',
    'ISSUED', 'CLIENT', 'PROJECT', 'TITLE', 'DESCRIPTION',
    'GENERAL', 'ARRANGEMENT', 'LEGEND', 'SYMBOL', 'INDEX', 'LIST',
    'TABLE', 'SPEC', 'SPECIFICATION', 'REFER', 'EXISTING',
    'PROPOSED', 'DELETED', 'REMOVED', 'HOLD', 'MATCH LINE',
    'BATTERY LIMIT', 'BL', 'TBD', 'TBC', 'N/A', 'NA',
    'CONTINUATION', 'CONTINUED',
}


_RE_LINE_DESIG  = re.compile(r'^\d+["\']-?[A-Z]{1,4}-\d+[#]?$')  # 2"-CS-150#


_RE_DRAWING_NO  = re.compile(r'^\d{3,}-\d+-\d+$')                 # 157-2-100


_GARBAGE_PFXS   = ('ghost_', 'line_', 'annotation_')


_ISA_MEASURED_VAR: dict[str, str] = {
    'F': 'flow',         'P': 'pressure',   'T': 'temperature', 'L': 'level',
    'A': 'composition',  'Q': 'quantity',   'D': 'differential','S': 'speed',
    'W': 'weight',       'V': 'vibration',  'H': 'hand',        'X': 'unclassified',
    'E': 'voltage',      'Z': 'position',
    # J = Power, R = Ratio — measurement-only first letters used by AIRCO
    # (electric heater power, flow ratio). Both rarely have a controller.
    'J': 'power',        'R': 'ratio',
}


_ISA_FUNCTION_MAP: dict[str, tuple[str, int]] = {
    'T':   ('transmitter', 2),
    'IT':  ('transmitter', 2),
    'FIT': ('transmitter', 2),
    'I':   ('indicator',   2),
    'G':   ('indicator',   2),
    'LG':  ('indicator',   2),
    'IC':  ('controller',  2),
    'ICA': ('controller',  2),
    'C':   ('controller',  2),
    'E':   ('element',     2),
    'R':   ('recorder',    2),
    'IR':  ('recorder',    2),
    'S':   ('switch',      2),
    'SH':  ('switch',      2),
    'SL':  ('switch',      2),
    'A':   ('alarm',       2),
    'AH':  ('alarm',       2),
    'AL':  ('alarm',       2),
    'AHH': ('alarm',       2),
    'ALL': ('alarm',       2),
    'Y':   ('relay',       2),
    'EY':  ('relay',       2),
    'CV':  ('control_valve', 1),
    'V':   ('control_valve', 1),   # FV, PV — overridden below for HV/XV
    'PV':  ('control_valve', 1),
}


_SAFETY_VALVE_PREFIXES = frozenset({
    'PSV', 'PRV', 'RV', 'ORV', 'PRR', 'RD', 'BPV', 'ESDV',
})


_MECHANICAL_VALVE_PREFIXES = frozenset({
    'HV', 'NV', 'CK', 'NRV', 'XV', 'SDV', 'BDV', 'ESD',
    'MOV', 'AOV', 'SV', 'BLV', 'GV', 'PBV',
})


_KIND_TO_CLASS: dict[str, tuple[str, int]] = {
    'transmitter':       ('transmitter',    2),
    'controller':        ('controller',     2),
    'indicator':         ('indicator',      2),
    'recorder':          ('recorder',       2),
    'switch':            ('switch',         2),
    'analyzer':          ('analyzer',       2),
    'element':           ('element',        2),
    'valve':             ('control_valve',  1),
    'cv_globe':          ('control_valve',  1),
    'cv_ball':           ('control_valve',  1),
    'cv_butterfly':      ('control_valve',  1),
    'cv_gate':           ('control_valve',  1),
    'cv_plug':           ('control_valve',  1),
    'cv_diaphragm':      ('control_valve',  1),
    'hand_valve':        ('hand_valve',     3),
    'checkvalve':        ('check_valve',    3),
    'relief':            ('relief_valve',   4),
    'psv':               ('relief_valve',   4),
    'rupture_disc':      ('relief_valve',   4),
    'flame_arrestor':    ('hand_valve',     3),
    'damper':            ('hand_valve',     3),
}


_DESCRIPTION_WORDS = frozenset({
    'PUMP', 'REACTOR', 'RECYCLE', 'FEED', 'VESSEL', 'COLUMN',
    'COMPRESSOR', 'FILTER', 'SEPARATOR', 'INLET', 'OUTLET',
    'SUPPLY', 'RETURN', 'BYPASS', 'DRAIN', 'VENT', 'FLARE',
    'PRODUCT', 'REFLUX', 'BOTTOMS', 'OVERHEAD', 'UTILITY',
    'THERMAL', 'LEVEL', 'LIQUID',
})


_DESCRIPTION_PHRASES = frozenset({
    'PUMP HEAD', 'PUMP BASE', 'COMP BASE', 'MOTOR BASE',
    'SEAL POT', 'LUBE OIL', 'COOLING WATER',
    'REACTOR-EFFLUENT', 'GLS-SUPPLY', 'CO2-LIQUID', 'H2-FEED', 'RECYCLE-GAS',
})


_DCS_ABBREVIATIONS = frozenset({
    'VFD', 'MSD', 'WEO', 'DPM', 'DPH', 'EPL', 'ACL', 'IAS', 'GCV', 'INY',
})


_NON_PHYSICAL_STARTS = frozenset({'HS', 'HC', 'HIC', 'AL', 'AH', 'XA', 'YA', 'ZA', 'PNL'})


_NON_PHYSICAL_ALARM_SUFFIXES = ('AHH', 'ALL', 'AH', 'AL')


_PERRY_PATTERNS: dict[str, list[str]] = {
    'compressor':   ['vessel', 'filter', 'compressor', 'heat_exchanger', 'vessel'],
    'pump':         ['vessel', 'pump', 'checkvalve'],
    'reactor':      ['heat_exchanger', 'reactor', 'heat_exchanger', 'vessel'],
    'distillation': ['column', 'heat_exchanger', 'vessel', 'pump', 'heat_exchanger', 'pump'],
    'separation':   ['heat_exchanger', 'vessel', 'vessel', 'filter', 'pump', 'vessel'],
    'feed':         ['vessel', 'heat_exchanger', 'valve', 'meter'],
    'preheat':      ['heat_exchanger', 'heat_exchanger', 'heat_exchanger'],
}


_AREA_KW: list[tuple[str, list[str]]] = [
    ('compressor',   ['compress', 'compressor', 'booster', 'recycle comp', 'make-up comp']),
    ('reactor',      ['react', 'reactor', 'rxn', 'converter', 'synthesis']),
    ('distillation', ['distil', 'column', 'fractionat', 'strip', 'debutanizer', 'deethanizer',
                      'absorb']),
    ('separation',   ['separ', 'separator', 'flash', 'knockout', 'slug catch', 'scrub']),
    ('preheat',      ['preheat', 'pre-heat', 'furnace', 'fired heat']),
    ('feed',         ['feed', 'inlet', 'storage', 'receiving', 'charge', 'suction']),
    ('pump',         ['pump', 'pumping']),
]


_PAT_KINDS: dict[str, frozenset] = {
    'vessel':         frozenset({'vessel', 'separator'}),
    'drum':           frozenset({'vessel', 'separator'}),
    'tank':           frozenset({'vessel', 'separator'}),
    'heat_exchanger': frozenset({'heat_exchanger'}),
    'hx':             frozenset({'heat_exchanger'}),
    'condenser':      frozenset({'heat_exchanger'}),
    'reboiler':       frozenset({'heat_exchanger'}),
    'compressor':     frozenset({'compressor'}),
    'pump':           frozenset({'pump'}),
    'reactor':        frozenset({'reactor', 'column', 'absorber'}),
    'column':         frozenset({'column', 'absorber'}),
    'filter':         frozenset({'filter'}),
    'valve':          frozenset({'valve'}),
    'checkvalve':     frozenset({'checkvalve'}),
    'meter':          frozenset({'meter'}),
}


_REQUIRED: dict[str, dict] = {
    'compressor': {
        'upstream':    [('vessel',         'suction drum')],
        'downstream':  [('heat_exchanger', 'aftercooler'), ('vessel', 'KO drum')],
        'instruments': ['PI', 'PSV'],
    },
    'pump': {
        'upstream':    [('vessel',      'suction source')],
        'downstream':  [('checkvalve',  'discharge check valve')],
        'instruments': ['PT'],
    },
    'vessel': {
        'instruments': ['LT', 'PSV'],
    },
    'separator': {
        'instruments': ['LT', 'PSV'],
    },
    'reactor': {
        'upstream':    [('heat_exchanger', 'feed preheater')],
        'downstream':  [('heat_exchanger', 'product cooler')],
        'instruments': ['TT', 'TIC', 'PT', 'PSV'],
    },
    'column': {
        'companions':  [
            ('heat_exchanger', 'condenser/overhead'),
            ('vessel',         'reflux drum'),
            ('pump',           'reflux pump'),
            ('heat_exchanger', 'reboiler'),
            ('pump',           'bottoms pump'),
        ],
        'instruments': ['TT', 'PT', 'LT', 'PSV'],
    },
    'absorber': {
        'instruments': ['TT', 'PT', 'LT', 'PSV'],
    },
    'heat_exchanger': {
        'instruments': ['TT'],
    },
    'filter': {
        'instruments': ['DPT', 'DPI'],
    },
}


_PALETTE_TO_CANON: dict[str, str] = {
    'vessel_v': 'vessel', 'vessel_h': 'vessel', 'flash_drum': 'vessel',
    'pump_cent': 'pump', 'pump_pos': 'pump', 'pump_recip': 'pump',
    'comp_cent': 'compressor', 'comp_recip': 'compressor',
    'hx_she': 'heat_exchanger', 'reboiler': 'heat_exchanger',
    'condenser': 'heat_exchanger', 'fired_heater': 'heat_exchanger',
    'cv_globe': 'valve', 'cv_ball': 'valve', 'cv_butterfly': 'valve',
    'cv_gate': 'valve', 'cv_plug': 'valve', 'cv_diaphragm': 'valve',
    'hand_valve': 'valve', 'psv': 'relief', 'rupture_disc': 'relief',
}


_INFER_AREA_ORDER = [
    'delivery', 'meter', 'compress', 'preheat',
    'react', 'separ', 'product', 'collect', 'analyt',
]


_TAG_DIGIT_RANK: dict[str, int] = {
    '0': 0, '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '8': 98, '9': 98,
}
