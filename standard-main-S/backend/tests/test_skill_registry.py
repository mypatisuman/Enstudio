"""SkillRegistry tests — fixture-based + real-registry sanity check."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(_STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(_STUDIO_DIR))

from adapters.skill_registry import SkillRegistry  # noqa: E402


# ── Fixture: a self-contained skills tree mirroring the real layout ──────────

CORE_RULES_TEXT = textwrap.dedent("""\
    # Core PID rules

    ## PART 5: LAYOUT RULES (machine-readable YAML)

    ```yaml
    sheet:
      margin_px: 100
    streams:
      primary_y: 0
    ```
""")

DIGITIZATION_TEXT = "# Digitization framework\n\nSection 4 logic.\n"

RECON_V1_TEXT = textwrap.dedent("""\
    # Reconstruction v1 (legacy)

    ## Layout Rules (machine-readable)

    ```yaml
    backbone:
      y: 999
    ```
""")

RECON_V2_TEXT = "# Reconstruction v2\n\nFlow patterns.\n"

TEMPLATE_TEXT = "# Company conventions template\n"

AIRCO_TEXT = "# AIRCO conventions\n\nTag prefixes: PCV uses spoke_below.\n"

REGISTRY_YAML = textwrap.dedent("""\
    version: 2
    skills:
      - id: pid_rules
        path: core/pid-development-rules.md
        type: rules
        priority: 1
        provides: [layout_rules, symbol_sizes]
      - id: digitization_framework
        path: core/pid-digitization-framework.md
        type: framework
        priority: 1
        provides: [classification_logic, layout_algorithm]
      - id: process_reconstruction
        path: reconstruction/process-reconstruction-v2.md
        type: reconstruction
        priority: 2
        supersedes: [reconstruction/process-reconstruction.md]
        provides: [reconstruction_prompt]
      - id: process_reconstruction_v1
        path: reconstruction/process-reconstruction.md
        type: reconstruction
        priority: 2
        provides: [reconstruction_prompt, layout_rules]
      - id: company_template
        path: company/template.md
        type: template
        priority: 0
        provides: [convention_schema]
      - id: airco_conventions
        path: company/AIRCO/conventions.md
        type: company_convention
        priority: 3
        company: AIRCO
        provides: [tag_prefixes, rendering_preferences]
""")


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    root = tmp_path / 'skills'
    (root / 'core').mkdir(parents=True)
    (root / 'reconstruction').mkdir(parents=True)
    (root / 'company' / 'AIRCO').mkdir(parents=True)

    (root / 'registry.yaml').write_text(REGISTRY_YAML, encoding='utf-8')
    (root / 'core' / 'pid-development-rules.md').write_text(CORE_RULES_TEXT, encoding='utf-8')
    (root / 'core' / 'pid-digitization-framework.md').write_text(DIGITIZATION_TEXT, encoding='utf-8')
    (root / 'reconstruction' / 'process-reconstruction.md').write_text(RECON_V1_TEXT, encoding='utf-8')
    (root / 'reconstruction' / 'process-reconstruction-v2.md').write_text(RECON_V2_TEXT, encoding='utf-8')
    (root / 'company' / 'template.md').write_text(TEMPLATE_TEXT, encoding='utf-8')
    (root / 'company' / 'AIRCO' / 'conventions.md').write_text(AIRCO_TEXT, encoding='utf-8')
    return root


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_load_returns_merged_context(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    ctx = reg.load()
    assert ctx['company'] is None
    paths = [s['path'] for s in ctx['skills']]
    assert 'core/pid-development-rules.md' in paths
    assert 'core/pid-digitization-framework.md' in paths
    assert 'reconstruction/process-reconstruction-v2.md' in paths
    # Concatenated text contains every active skill
    assert '# Core PID rules' in ctx['text']
    assert '# Reconstruction v2' in ctx['text']


def test_company_overrides_apply_on_top_of_core(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    ctx = reg.load(company='AIRCO')
    paths = [s['path'] for s in ctx['skills']]
    # Core entries still present
    assert 'core/pid-development-rules.md' in paths
    # Company convention now included
    assert 'company/AIRCO/conventions.md' in paths
    # Higher priority sorts last (overrides at end of merged text)
    assert paths.index('company/AIRCO/conventions.md') > paths.index('core/pid-development-rules.md')
    assert ctx['skills'][-1]['path'] == 'company/AIRCO/conventions.md'
    # Company text appears in merged context
    assert '# AIRCO conventions' in ctx['text']


def test_superseded_files_are_skipped(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    ctx = reg.load()
    paths = [s['path'] for s in ctx['skills']]
    assert 'reconstruction/process-reconstruction.md' not in paths
    assert '# Reconstruction v1 (legacy)' not in ctx['text']

    # Layout rules: v1 backbone YAML must not leak through despite providing layout_rules
    rules = reg.get_layout_rules()
    assert 'backbone' not in rules
    assert rules.get('sheet', {}).get('margin_px') == 100


def test_missing_company_falls_back_to_core(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    ctx = reg.load(company='UNKNOWN_CO')
    paths = [s['path'] for s in ctx['skills']]
    # No company convention loaded
    assert not any(p.startswith('company/') and p.endswith('/conventions.md') for p in paths)
    # Core skills still present
    assert 'core/pid-development-rules.md' in paths
    # get_company_conventions returns empty for unknown company
    assert reg.get_company_conventions('UNKNOWN_CO') == {}


def test_get_company_conventions_returns_airco(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    conv = reg.get_company_conventions('AIRCO')
    assert conv['company'] == 'AIRCO'
    assert conv['path'] == 'company/AIRCO/conventions.md'
    assert '# AIRCO conventions' in conv['text']
    assert 'tag_prefixes' in conv['provides']


def test_get_reconstruction_prompt_includes_company_preface(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    prompt = reg.get_reconstruction_prompt(company='AIRCO')
    assert '# AIRCO conventions' in prompt
    assert '# Reconstruction v2' in prompt
    # Company preface comes before the reconstruction skill
    assert prompt.index('# AIRCO conventions') < prompt.index('# Reconstruction v2')
    # Superseded v1 absent
    assert '# Reconstruction v1 (legacy)' not in prompt


def test_list_companies_returns_airco(skills_dir: Path):
    reg = SkillRegistry(skills_dir)
    assert reg.list_companies() == ['AIRCO']


# ── Real registry sanity check ────────────────────────────────────────────────

def test_real_registry_lists_airco():
    """The shipped registry.yaml must expose AIRCO as the only company."""
    reg = SkillRegistry(_STUDIO_DIR / 'skills')
    assert reg.list_companies() == ['AIRCO']
