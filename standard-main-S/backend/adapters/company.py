"""
Company P&ID conventions loader and parser.

Reads EngineeringHub/companies/<name>/conventions.md and exposes
lookup methods used by extraction prompts, normalize_kind, and the
editor's layer-visibility system.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

# ── Category / layer lookup tables ────────────────────────────────────────────

_EQUIP_TYPE_TO_CATEGORY: dict[str, str] = {
    'heat exchanger': 'heat_exchanger',
    'vessel': 'vessel',
    'vessel / drum': 'vessel',
    'drum': 'vessel',
    'pump': 'pump',
    'compressor': 'compressor',
    'column': 'column',
    'column / tower': 'column',
    'tower': 'column',
    'reactor': 'reactor',
    'tank': 'vessel',
    'filter': 'filter',
    'air cooler': 'heat_exchanger',
    'motor': 'motor',
    'separator': 'separator',
    'separation': 'separator',
    'glass-lined reactor': 'reactor',
    'glass-lined separator': 'separator',
    'quench cooler': 'heat_exchanger',
    'cooler': 'heat_exchanger',
    'reboiler/kettle': 'heat_exchanger',
    'refrigeration unit': 'vessel',
    'reverse osmosis': 'vessel',
    'panel': 'vessel',
    'recycle marker': 'vessel',
}

_CATEGORY_ALIASES: dict[str, str] = {
    'hx': 'heat_exchanger',
    'heat_exchanger': 'heat_exchanger',
    'heat exchanger': 'heat_exchanger',
    'vessel': 'vessel',
    'drum': 'vessel',
    'tank': 'vessel',
    'pump': 'pump',
    'compressor': 'compressor',
    'column': 'column',
    'reactor': 'reactor',
    'filter': 'filter',
    'separator': 'separator',
    'separation': 'separator',
    'other': 'vessel',
    'motor': 'motor',
}

_LAYER_NAME_MAP: dict[str, str] = {
    'control': 'ctrl_valves',
    'ctrl': 'ctrl_valves',
    'ctrl_valves': 'ctrl_valves',
    'hand': 'hand_valves',
    'hand_valves': 'hand_valves',
    'check': 'check_valves',
    'check_valves': 'check_valves',
    'relief': 'relief_valves',
    'relief_valves': 'relief_valves',
    'isolation': 'isolation',
}

# ISA default valve layer (fallback when no company map entry)
_ISA_VALVE_DEFAULTS: dict[str, str] = {
    'HV': 'hand_valves',  'NV': 'hand_valves',  'SV': 'hand_valves',
    'CK': 'check_valves', 'NRV': 'check_valves',
    'PSV': 'relief_valves', 'PRV': 'relief_valves',
    'RV': 'relief_valves',  'ORV': 'relief_valves',
    'XV': 'isolation', 'SDV': 'isolation', 'BDV': 'isolation',
    'ESD': 'isolation', 'MOV': 'isolation', 'AOV': 'isolation',
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _prefix_of(tag: str) -> str:
    """Extract ISA-style prefix from a tag string.

    HE-1101 → HE,  ADV-104 → ADV,  PSV-201A → PSV
    """
    tag = tag.upper().strip()
    m = re.match(r'^([A-Z]{1,5})[-_]?\d', tag)
    if m:
        return m.group(1)
    return tag.split('-')[0].split('_')[0][:5]


def _parse_table_rows(text: str) -> list[tuple[str, list[list[str]]]]:
    """Return [(header_key, [[col, col, ...], ...]), ...] for every markdown table."""
    tables: list[tuple[str, list[list[str]]]] = []
    header: list[str] | None = None
    rows: list[list[str]] = []

    def _flush():
        if header is not None and rows:
            tables.append(('|'.join(header), rows[:]))

    for line in text.splitlines():
        s = line.strip()
        if not s.startswith('|'):
            _flush()
            header = None
            rows = []
            continue
        cols = [c.strip() for c in s.split('|')]
        # Strip empty first/last artefacts from leading/trailing |
        if cols and cols[0] == '':
            cols = cols[1:]
        if cols and cols[-1] == '':
            cols = cols[:-1]
        if not cols:
            continue
        # Separator row (---|--- …)
        if all(re.match(r'^-+$', c.replace(' ', '')) for c in cols if c.strip()):
            continue
        if header is None:
            header = [c.lower() for c in cols]
        else:
            rows.append(cols)

    _flush()
    return tables


class CompanyConventions:
    """Loads and parses a company conventions.md file."""

    # Registry baseline lives next to the studio code, not inside the HUB.
    _DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / 'skills'

    def __init__(self, company_name: str, hub_path,
                 skills_dir: Path | str | None = None):
        self.name = company_name
        self.path = Path(hub_path) / 'companies' / company_name / 'conventions.md'
        skills = Path(skills_dir) if skills_dir is not None else self._DEFAULT_SKILLS_DIR
        # Registry-shipped baseline. Lower priority than the HUB override.
        self.baseline_path = skills / 'company' / company_name / 'conventions.md'
        self._raw: str = ''
        self._hub_raw: str = ''
        self._baseline_raw: str = ''
        self._equipment_map: dict[str, str] = {}   # prefix → category
        self._valve_map: dict[str, str] = {}        # prefix → layer name
        self._instrument_map: dict[str, dict] = {}  # prefix → {category, variable, expects_controller}
        self._kind_map: dict[str, str] = {}          # prefix → palette kind
        self._parsed = False

    # ── I/O ───────────────────────────────────────────────────────────────────

    def exists(self) -> bool:
        """True if either the HUB override or the registry baseline exists."""
        return self.path.exists() or self.baseline_path.exists()

    def load(self) -> str:
        self._baseline_raw = (
            self.baseline_path.read_text(encoding='utf-8')
            if self.baseline_path.exists() else ''
        )
        self._hub_raw = (
            self.path.read_text(encoding='utf-8')
            if self.path.exists() else ''
        )
        # Public ``_raw`` mirrors whichever source has content. HUB wins so
        # downstream regex searches (e.g. _apply_convention_overrides) see
        # the project-specific overrides first; baseline fills the gap when
        # the HUB file is absent.
        self._raw = self._hub_raw or self._baseline_raw
        self._parsed = False
        return self._raw

    @classmethod
    def _load_merged(cls,
                     company: str,
                     hub_path,
                     skills_dir: Path | str | None = None) -> 'CompanyConventions':
        """Convenience: build, load, and parse a CompanyConventions instance.

        Loads the registry baseline at ``skills_dir/company/<company>/conventions.md``
        and the HUB override at ``hub_path/companies/<company>/conventions.md``,
        then merges them so HUB entries win per-prefix while registry entries
        fill any gaps the HUB doesn't cover.
        """
        inst = cls(company, hub_path, skills_dir=skills_dir)
        inst.load()
        inst.parse()
        return inst

    def save(self, content: str):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding='utf-8')
        self._raw = content
        self._parsed = False
        self._equipment_map.clear()
        self._valve_map.clear()
        self._instrument_map.clear()
        self._kind_map.clear()

    def create_from_template(self, template_path) -> str:
        """Create conventions.md from template, replacing {{COMPANY_NAME}}."""
        content = Path(template_path).read_text(encoding='utf-8')
        content = content.replace('{{COMPANY_NAME}}', self.name)
        self.save(content)
        return content

    # ── Parser ────────────────────────────────────────────────────────────────

    def parse(self):
        """Parse merged conventions into lookup dicts.

        Order: baseline (registry-shipped) first, HUB override second. Each
        parse pass writes into the same ``_equipment_map`` / ``_valve_map``
        / ``_instrument_map`` / ``_kind_map``, so the second pass overrides
        per-prefix. Entries the HUB doesn't mention are left as the
        baseline's values.
        """
        if self._parsed:
            return
        if not self._hub_raw and not self._baseline_raw:
            self.load()
        self._equipment_map.clear()
        self._valve_map.clear()
        self._instrument_map.clear()
        self._kind_map.clear()

        if self._baseline_raw:
            self._parse_all_sections(self._baseline_raw)
        if self._hub_raw:
            self._parse_all_sections(self._hub_raw)

        self._parsed = True

    def _parse_all_sections(self, raw: str):
        """Dispatch every ``## N. ...`` block to its section parser."""
        sections = re.split(r'^##\s+', raw, flags=re.MULTILINE)
        for sec in sections:
            first_line = sec.split('\n')[0].strip()
            if first_line.startswith('1.'):
                self._parse_equip_section(sec)
            elif first_line.startswith('2.'):
                self._parse_valve_section(sec)
            elif first_line.startswith('3.'):
                self._parse_instr_section(sec)
            elif first_line.startswith('10.'):
                self._parse_default_assumptions(sec)

    @staticmethod
    def _split_prefixes(raw: str) -> list[str]:
        """Split a comma-separated prefix cell and strip dashes/whitespace from each."""
        return [tok.strip().rstrip('-').upper() for tok in raw.split(',') if tok.strip().rstrip('-')]

    def _parse_equip_section(self, text: str):
        for header_key, rows in _parse_table_rows(text):
            headers = header_key.lower()
            for row in rows:
                if 'editor kind' in headers:
                    # Equipment Kind Mapping table: [Company Prefix, Editor Kind, Symbol]
                    if len(row) < 2:
                        continue
                    for pfx in self._split_prefixes(row[0]):
                        kind = row[1].strip()
                        if pfx and kind:
                            self._kind_map[pfx] = kind
                elif 'this company' in headers:
                    # Standard table: [Equipment Type, Standard ISA, This Company, Notes]
                    if len(row) < 3:
                        continue
                    raw = row[2].strip()
                    if not raw or raw == '—':
                        continue
                    equip_type = row[0].strip().lower()
                    category = _EQUIP_TYPE_TO_CATEGORY.get(equip_type, 'vessel')
                    for pfx in self._split_prefixes(raw):
                        if pfx:
                            self._equipment_map[pfx] = category
                elif 'category' in headers or 'full name' in headers:
                    # Additional table: [Prefix, Full Name, Category, Notes]
                    if len(row) < 3:
                        continue
                    cat_raw = row[2].strip().lower().split('/')[0].strip()
                    if not cat_raw:
                        continue
                    category = _CATEGORY_ALIASES.get(cat_raw, cat_raw)
                    for pfx in self._split_prefixes(row[0]):
                        if pfx:
                            self._equipment_map[pfx] = category

    def _parse_valve_section(self, text: str):
        for _header_key, rows in _parse_table_rows(text):
            for row in rows:
                if len(row) < 3:
                    continue
                layer_raw = row[2].strip().lower()
                layer = _LAYER_NAME_MAP.get(layer_raw)
                if not layer:
                    continue
                for pfx in self._split_prefixes(row[0]):
                    if pfx:
                        self._valve_map[pfx] = layer

    # Recognised instrument categories used to filter table rows from
    # unrelated content (function-code tables, ISA-meaning rows, etc.).
    _INSTRUMENT_CATEGORIES = frozenset({
        'transmitter', 'controller', 'indicator', 'recorder',
        'switch', 'analyzer', 'element', 'alarm', 'relay',
    })

    # Words that signal the prefix is measurement-only (no control loop).
    _NO_CONTROLLER_PATTERNS = (
        'no controller expected',
        'no control loop',
        'measurement only',
        'measurement-only',
        'monitoring only',
        'monitoring-only',
        'local readout only',
        'feeds historian only',
    )

    # First-letter → measured variable, mirrored from engine._ISA_MEASURED_VAR.
    # Inlined here to avoid a circular adapters→adapters import.
    _ISA_FIRST_LETTER_VARS = {
        'F': 'flow', 'P': 'pressure', 'T': 'temperature', 'L': 'level',
        'A': 'composition', 'Q': 'quantity', 'D': 'differential', 'S': 'speed',
        'W': 'weight', 'V': 'vibration', 'H': 'temperature',  # H = hot (AIRCO)
        'X': 'unclassified', 'E': 'voltage', 'Z': 'position',
        'J': 'power', 'R': 'ratio',
    }

    @classmethod
    def _infer_variable(cls, full_name: str, pfx: str) -> Optional[str]:
        """Best-effort variable extraction from a Full Name cell."""
        n = (full_name or '').lower()
        # Word-form first — most precise
        for v in ('temperature', 'pressure', 'level', 'flow',
                  'power', 'energy', 'ratio', 'vibration', 'composition',
                  'speed', 'weight', 'position', 'differential'):
            if v in n:
                return 'power' if v == 'energy' else v
        # Fall back to the first letter of the prefix
        if pfx:
            return cls._ISA_FIRST_LETTER_VARS.get(pfx[0].upper())
        return None

    @classmethod
    def _expects_controller(cls, notes: str) -> bool:
        n = (notes or '').lower()
        for pat in cls._NO_CONTROLLER_PATTERNS:
            if pat in n:
                return False
        return True

    def _parse_instr_section(self, text: str):
        for _header_key, rows in _parse_table_rows(text):
            for row in rows:
                if len(row) < 3:
                    continue
                pfx = row[0].strip().rstrip('-').upper()
                if not re.match(r'^[A-Z]{1,5}$', pfx):
                    continue
                # Skip the standard ISA-meaning rows ("F", "P", ...) and
                # column-header artefacts.
                if pfx in ('PREFIX', 'CODE', 'NAME', 'TYPE',
                           'F', 'P', 'T', 'L', 'A', 'Q', 'D', 'S', 'W', 'V'):
                    continue
                cat_raw = row[2].strip().lower()
                if cat_raw not in self._INSTRUMENT_CATEGORIES:
                    continue
                full_name = row[1].strip() if len(row) >= 2 else ''
                notes = row[3].strip() if len(row) >= 4 else ''
                ec = self._expects_controller(notes)
                # Relays are non-physical DCS compute functions — they ARE
                # part of the loop, not a measurement that demands one.
                if cat_raw == 'relay':
                    ec = False
                self._instrument_map[pfx] = {
                    'category':           cat_raw,
                    'variable':           self._infer_variable(full_name, pfx),
                    'expects_controller': ec,
                }

    # Section 10 bullets: '- PFX- tags → category ... no controller expected'
    # Picks up prefixes that aren't documented in a Section 3 table (e.g. RT-).
    # Bullet body extends across continuation lines (indented, not starting
    # with '-') until a blank line or the next list item — so multi-line
    # phrases like "measurement-only,\n  no controller expected" are seen.
    _BULLET_RE = re.compile(
        r'^\s*-\s+([A-Z]{1,5})-\s*tags?\s*(?:→|->)\s*'
        r'(.+?)(?=\n\s*-\s|\n\s*\n|\Z)',
        re.MULTILINE | re.DOTALL,
    )

    def _parse_default_assumptions(self, text: str):
        for m in self._BULLET_RE.finditer(text):
            pfx = m.group(1).upper()
            if pfx in self._instrument_map:
                continue  # explicit Section 3 entry wins
            body = m.group(2)
            body_low = body.lower()
            # Pick the category that appears earliest in the bullet, so a
            # bullet like "... ratio transmitter ... no controller expected"
            # registers as transmitter, not controller.
            hits = [
                (body_low.find(c), c)
                for c in self._INSTRUMENT_CATEGORIES
                if c in body_low
            ]
            if not hits:
                continue
            hits.sort()
            category = hits[0][1]
            self._instrument_map[pfx] = {
                'category':           category,
                'variable':           self._infer_variable(body, pfx),
                'expects_controller': self._expects_controller(body),
            }

    # ── Lookup API ────────────────────────────────────────────────────────────

    def get_equipment_category(self, tag: str) -> str:
        """Return category ('heat_exchanger', 'vessel', etc.) for a tag, or ''."""
        if not self._parsed:
            self.parse()
        return self._equipment_map.get(_prefix_of(tag), '')

    def get_valve_layer(self, tag: str) -> str:
        """Return layer name for a valve tag.

        Priority: company map → ISA defaults → 'ctrl_valves'.
        """
        if not self._parsed:
            self.parse()
        pfx = _prefix_of(tag)
        if pfx in self._valve_map:
            return self._valve_map[pfx]
        return _ISA_VALVE_DEFAULTS.get(pfx, 'ctrl_valves')

    def get_instrument_category(self, tag: str) -> Optional[dict]:
        """Return ``{'category', 'variable', 'expects_controller'}`` for a tag,
        or ``None`` if no company entry covers the prefix.

        Sources, highest priority first:
          1. Explicit Section 3 prefix table (e.g. HT, JE, JT)
          2. Section 10 default-assumption bullets (e.g. RT)
        """
        if not self._parsed:
            self.parse()
        entry = self._instrument_map.get(_prefix_of(tag))
        if entry is None:
            return None
        return dict(entry)

    def get_kind_for_tag(self, tag: str) -> str:
        """Map a tag to a palette kind using company conventions, or '' if unknown."""
        if not self._parsed:
            self.parse()
        category = self._equipment_map.get(_prefix_of(tag), '')
        if not category:
            return ''
        _CAT_TO_PALETTE = {
            'vessel': 'storage_vessel',
            'heat_exchanger': 'hx_st',
            'pump': 'pump',
            'compressor': 'compressor',
            'column': 'column',
            'reactor': 'reactor',
            'filter': 'filter',
            'separator': 'flash_drum',
            'motor': 'vsd',
        }
        return _CAT_TO_PALETTE.get(category, 'storage_vessel')

    def as_skill_text(self) -> str:
        """Return conventions as prompt-ready text for Claude extraction calls.

        Prefers the HUB override; falls back to the registry baseline so
        projects without a project-local conventions file still ship the
        company prefixes / preferences to the LLM.
        """
        if not self._hub_raw and not self._baseline_raw:
            self.load()
        body = self._hub_raw or self._baseline_raw
        if not body:
            return ''
        return f'## Company P&ID Conventions: {self.name}\n\n{body}'

    def client_maps(self) -> dict:
        """Return valve_layers and equipment_kinds dicts for the browser client."""
        if not self._parsed:
            self.parse()
        return {
            'valve_layers': dict(self._valve_map),
            'equipment_kinds': dict(self._kind_map),
        }
