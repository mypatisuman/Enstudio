"""
domain/kind_mapping.py — palette-kind <-> canonical-kind mapping.

Extracted from main.py (Phase 4). Editor UI works in "palette kinds"
(vessel_v, pump_cent, ft ...); exporters work in "canonical kinds"
(vessel, pump, transmitter ...). normalize_kind() is the single source of
truth translating between them — moved here verbatim, along with the kind
sets/tables it and other main.py routes read directly.

Pure stdlib, no Flask/DB/adapters/services imports.
"""
from __future__ import annotations

INSTRUMENT_KINDS = {
    'transmitter', 'controller', 'indicator',
    'recorder', 'switch', 'analyzer', 'element'
}
PROCESS_KINDS = {
    'vessel', 'separator', 'pump', 'valve', 'checkvalve',
    'heat_exchanger', 'compressor', 'column', 'reactor',
    'absorber', 'adsorption', 'relief', 'filter', 'meter'
}
MECHANICAL_KINDS = {'valve', 'checkvalve', 'relief'}
CONNECTOR_KINDS  = {'off_page_connector'}

# ── Kind mapping — single source of truth ────────────────────────────────────
# palette kinds  → what the editor renders  (vessel_v, pump_cent, ft …)
# canonical kinds → what exporters consume  (vessel, pump, transmitter …)
#
# Rule: server normalises on GET /api/editor/<pid> (canonical→palette),
#       server de-normalises on POST /api/editor/<pid> (palette→canonical).
#       Editor JS never maps kinds.

PALETTE_TO_CANONICAL = {
    'vessel_v':'vessel','vessel_h':'vessel','flash_drum':'vessel',
    'knockout':'vessel','accumulator':'vessel','surge_drum':'vessel',
    'tank_atm':'vessel','tank_cone':'vessel','tank_float':'vessel',
    'hopper':'vessel','decanter':'vessel','settler':'vessel','cooling_tower':'vessel',
    'crystallizer':'vessel','dryer_rotary':'vessel','dryer_spray':'vessel',
    'dryer_fb':'vessel','mixer':'vessel','agitator':'vessel','conveyor':'vessel',
    'generator':'vessel','transformer':'vessel','ups':'vessel',
    'hx_st':'heat_exchanger','hx_plate':'heat_exchanger','hx_double':'heat_exchanger',
    'hx_spiral':'heat_exchanger','condenser':'heat_exchanger','reboiler_k':'heat_exchanger',
    'reboiler_t':'heat_exchanger','economizer':'heat_exchanger','evaporator':'heat_exchanger',
    'superheater':'heat_exchanger','air_cooler':'heat_exchanger','boiler':'heat_exchanger',
    'fired_heater':'heat_exchanger','furnace':'heat_exchanger',
    'dist_tray':'column','dist_packed':'column','absorber_col':'column','stripper':'column',
    'extractor':'column','scrubber_col':'column','packed_column':'column',
    'adsorber':'column','ion_exchange':'column',
    'cyclone':'separator','hydrocyclone':'separator','centrifuge':'separator','membrane':'separator',
    'filter_pf':'filter','filter_rv':'filter','screen':'filter',
    'cstr':'reactor','pfr':'reactor','batch_reactor':'reactor','fixed_bed':'reactor',
    'fluidized_bed':'reactor','reformer':'reactor','bioreactor':'reactor','electrolyzer':'reactor',
    'pump_cent':'pump','pump_pd':'pump','pump_diaphragm':'pump',
    'blower':'compressor','comp_cent':'compressor','comp_recip':'compressor',
    'comp_screw':'compressor','ejector':'compressor',
    'steam_turb':'compressor','gas_turb':'compressor',
    'cv_globe':'valve','cv_ball':'valve','cv_butterfly':'valve','cv_gate':'valve',
    'cv_plug':'valve','cv_diaphragm':'valve','checkvalve':'checkvalve',
    'damper':'valve','flame_arrestor':'valve',
    'psv':'relief','rupture_disc':'relief','flare':'relief',
    'ft':'transmitter','lt':'transmitter','pt':'transmitter','tt':'transmitter',
    'at':'transmitter','wt':'transmitter','dt':'transmitter','st':'transmitter',
    'vt':'transmitter','ff_h1':'transmitter','ff_ld':'transmitter',
    'fe':'element','le':'element','pe':'element','te':'element','ae':'element',
    'fic':'controller','fi':'indicator','fr':'recorder',
    'fsh':'switch','fsl':'switch','fahh':'alarm','fall':'alarm','fy':'relay',
    'vsd':'controller','dcs':'controller','plc':'controller','sis':'controller',
    'rtu':'controller','hmi':'controller',
}

# Canonical kind → preferred palette kind (used when loading extracted data
# that has no kind_detail — e.g. nodes created by PDF extraction).
CANONICAL_TO_PALETTE = {
    'vessel':'vessel_v','separator':'vessel_v','absorber':'vessel_v',
    'pump':'pump_cent',
    'heat_exchanger':'hx_st',
    'column':'dist_tray',
    'reactor':'cstr',
    'compressor':'comp_cent',
    'valve':'cv_globe','checkvalve':'checkvalve',
    'relief':'psv','filter':'filter_pf','meter':'ft',
    'transmitter':'ft','controller':'fic','indicator':'fi',
    'recorder':'fr','switch':'fsh','element':'fe','analyzer':'at',
    'alarm':'fsh','relay':'fy',
}

# Canonical instrument kinds — used to split nodes into instruments vs equipment
CANONICAL_INSTR_KINDS = {
    'transmitter','controller','indicator','recorder',
    'switch','analyzer','element','alarm','relay',
}


def normalize_kind(kind: str, kind_detail: str = None):
    """Return (palette_kind, canonical_kind) for any espx node.

    Priority: kind_detail (set by editor saves) > palette lookup > canonical lookup.
    Ensures the editor always receives a palette kind and exporters always
    receive a canonical kind, regardless of which code path created the node.
    """
    if kind_detail and kind_detail in PALETTE_TO_CANONICAL:
        return kind_detail, PALETTE_TO_CANONICAL[kind_detail]
    if kind in PALETTE_TO_CANONICAL:
        return kind, PALETTE_TO_CANONICAL[kind]
    if kind in CANONICAL_TO_PALETTE:
        return CANONICAL_TO_PALETTE[kind], kind
    return kind, kind
