"""
kind_normalize.py — maps raw YOLO detection type strings (e.g. "Ball_Valve",
"4_Way_Valve", "Pressure_Indicating_Transmitter") to the small canonical
lowercase kind vocabulary svg_pid.py / dxf.py render ISA-5.1 symbols for
("valve", "transmitter", "vessel", ...).

Why keyword-based instead of an exhaustive 147-class table: the YOLO model
(weights/pid/best.pt) has 147 classes and gains more over time as it's
retrained. A substring match on the handful of physically-meaningful words
below survives new/renamed classes without needing a maintenance pass; an
exact-match table silently falls through to "default" for anything not yet
added to it — which is exactly the bug this module fixes.
"""
from __future__ import annotations

CANONICAL_KINDS = frozenset({
    'vessel', 'tank', 'separator', 'heat_exchanger', 'pump', 'compressor', 'reactor',
    'column', 'absorber', 'filter', 'meter', 'relief',
    'transmitter', 'controller', 'indicator', 'recorder', 'switch',
    'analyzer', 'element', 'valve', 'checkvalve', 'regulator',
    'junction', 'off_page_connector', 'inlet', 'outlet', 'package', 'vendor_package',
})

# Ordered (word, kind) rules — first match wins. Instrument function words
# checked before generic ones so e.g. "Flow_Indicating_Controller" resolves
# to 'controller' (the ISA-tag-final, authoritative function), not 'indicator'.
_RULES: list[tuple[str, str]] = [
    ('checkvalve',   'checkvalve'),
    ('check_valve',  'checkvalve'),
    ('relief',       'relief'),
    ('rupture',      'relief'),
    ('safety',       'relief'),
    ('valve',        'valve'),
    ('controller',   'controller'),
    ('control_valve','valve'),   # already caught by 'valve' above; kept for clarity
    ('transmitter',  'transmitter'),
    ('indicator',    'indicator'),
    ('indicating',   'indicator'),
    ('recorder',     'recorder'),
    ('switch',       'switch'),
    ('analy',        'analyzer'),   # analyzer, analysis
    ('sensor',       'element'),
    ('transducer',   'element'),
    ('element',      'element'),
    ('pump',         'pump'),
    ('compressor',   'compressor'),
    ('blower',       'compressor'),
    ('turbine',      'compressor'),
    ('expander',     'compressor'),
    ('exchanger',    'heat_exchanger'),
    ('heater',       'heat_exchanger'),
    ('boiler',       'heat_exchanger'),
    ('condenser',    'heat_exchanger'),
    ('cooler',       'heat_exchanger'),
    ('column',       'column'),
    ('tower',        'column'),
    ('reactor',      'reactor'),
    ('cyclone',      'separator'),
    ('separator',    'separator'),
    ('absorber',     'absorber'),
    ('filter',       'filter'),
    ('strainer',     'filter'),
    ('meter',        'meter'),
    ('vessel',       'vessel'),
    # Atmospheric storage tanks are a distinct Canvas shape (flat-bottomed
    # cylinder with a domed roof) from a pressure vessel's rounded pill —
    # matches classification.ts's getNodeType() 'tank' vs 'vessel' split.
    ('hopper',       'tank'),
    ('storage',      'tank'),
    ('tank',         'tank'),
    ('drum',         'vessel'),
    ('accumulator',  'vessel'),
    ('inlet',        'inlet'),
    ('outlet',       'outlet'),
    ('off_page',     'off_page_connector'),
    ('junction',     'junction'),
    ('regulator',    'regulator'),
]


def normalize_render_kind(raw_kind: str) -> str:
    """Map a raw node 'kind' (YOLO type, palette code, or already-canonical
    kind) to the canonical kind used by the ISA-5.1 renderers.

    Returns 'default' when nothing matches — callers should treat that as
    "draw a generic rectangle", not an error.
    """
    if not raw_kind:
        return 'default'
    if raw_kind in CANONICAL_KINDS:
        return raw_kind
    lo = raw_kind.lower()
    for word, kind in _RULES:
        if word in lo:
            return kind
    return 'default'
