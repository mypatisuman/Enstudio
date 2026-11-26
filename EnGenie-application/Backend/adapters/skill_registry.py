"""
SkillRegistry — central loader for PlantSketch skill files.

Reads ``skills/registry.yaml`` and provides accessors for layout rules,
classification logic, company conventions, and reconstruction prompts.
The registry is the single source of truth: which files exist, their
priority order, what each provides, and which company a convention
applies to. Files referenced by another entry's ``supersedes`` list
are skipped.

Skill resolution rules:
  * Lower ``priority`` is loaded first; higher ``priority`` overrides.
  * ``type: company_convention`` entries are filtered to the requested
    ``company`` (case-insensitive). When no company is requested they
    are dropped entirely — load returns core only.
  * ``supersedes`` paths are dropped from the active set.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


_LAYOUT_MARKERS = (
    '## PART 5: LAYOUT RULES (machine-readable YAML)',
    '## Layout Rules (machine-readable)',
)


class SkillRegistry:
    def __init__(self, skills_dir: Path | str):
        self.skills_dir = Path(skills_dir)
        self.registry_path = self.skills_dir / 'registry.yaml'
        self._registry: dict = {}
        self._cache: dict = {}
        self._load_registry()

    def _load_registry(self) -> None:
        if not self.registry_path.exists():
            self._registry = {'skills': []}
            return
        with self.registry_path.open(encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault('skills', [])
        self._registry = data

    def _resolve(self, company: Optional[str]) -> list[dict]:
        """Return active skill entries for a company, sorted by priority."""
        skills = list(self._registry.get('skills') or [])

        superseded: set[str] = set()
        for s in skills:
            for path in (s.get('supersedes') or []):
                superseded.add(path)

        norm_company = (company or '').strip().upper() or None
        active: list[dict] = []
        for s in skills:
            path = s.get('path', '')
            if path in superseded:
                continue
            if s.get('type') == 'company_convention':
                entry_company = (s.get('company') or '').strip().upper()
                if not norm_company or entry_company != norm_company:
                    continue
            active.append(s)

        active.sort(key=lambda s: s.get('priority', 0))
        return active

    def _read_text(self, rel_path: str) -> str:
        if not rel_path:
            return ''
        p = self.skills_dir / rel_path
        if not p.exists():
            return ''
        return p.read_text(encoding='utf-8')

    @staticmethod
    def _yaml_block(text: str, marker: str) -> dict:
        idx = text.find(marker)
        if idx == -1:
            return {}
        section = text[idx:]
        ys = section.find('```yaml\n')
        if ys == -1:
            return {}
        ye = section.find('\n```', ys + 8)
        if ye == -1:
            return {}
        try:
            block = yaml.safe_load(section[ys + 8:ye]) or {}
        except yaml.YAMLError:
            return {}
        return block if isinstance(block, dict) else {}

    def _first_yaml_block(self, text: str, markers: tuple[str, ...] = _LAYOUT_MARKERS) -> dict:
        for marker in markers:
            block = self._yaml_block(text, marker)
            if block:
                return block
        return {}

    # ── Public API ────────────────────────────────────────────────

    def load(self, company: Optional[str] = None) -> dict:
        """Return merged context: skill metadata + concatenated text."""
        cache_key = (company or '').strip().upper()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        skills_meta: list[dict] = []
        parts: list[str] = []
        for s in self._resolve(company):
            text = self._read_text(s.get('path', ''))
            if not text:
                continue
            skills_meta.append({
                'id': s.get('id'),
                'path': s.get('path'),
                'priority': s.get('priority', 0),
                'type': s.get('type'),
                'company': s.get('company'),
                'provides': list(s.get('provides') or []),
            })
            parts.append(text)

        context = {
            'company': company,
            'skills': skills_meta,
            'text': '\n\n---\n\n'.join(parts),
        }
        self._cache[cache_key] = context
        return context

    def get_layout_rules(self, company: Optional[str] = None) -> dict:
        """Merge machine-readable Part 5 YAML across active skills."""
        merged: dict = {}
        for s in self._resolve(company):
            provides = s.get('provides') or []
            if 'layout_rules' not in provides and 'layout_algorithm' not in provides:
                continue
            text = self._read_text(s.get('path', ''))
            if not text:
                continue
            block = self._first_yaml_block(text)
            if block:
                merged.update(block)
        return merged

    def get_classification_rules(self, company: Optional[str] = None) -> dict:
        merged: dict = {}
        for s in self._resolve(company):
            provides = s.get('provides') or []
            if 'classification_logic' not in provides:
                continue
            text = self._read_text(s.get('path', ''))
            if not text:
                continue
            block = self._first_yaml_block(
                text,
                markers=(
                    '## Classification (machine-readable)',
                    '## Section 4',
                    '## PART 4',
                ),
            )
            if block:
                merged.update(block)
        return merged

    def get_company_conventions(self, company: str) -> dict:
        if not company:
            return {}
        for s in self._resolve(company):
            if s.get('type') != 'company_convention':
                continue
            text = self._read_text(s.get('path', ''))
            return {
                'company': s.get('company') or company,
                'path': s.get('path'),
                'text': text,
                'provides': list(s.get('provides') or []),
            }
        return {}

    def get_reconstruction_prompt(self, company: Optional[str] = None) -> str:
        parts: list[str] = []
        if company:
            conv = self.get_company_conventions(company)
            if conv.get('text'):
                parts.append(conv['text'])
        for s in self._resolve(company):
            if s.get('type') != 'reconstruction':
                continue
            text = self._read_text(s.get('path', ''))
            if text:
                parts.append(text)
        return '\n\n---\n\n'.join(parts)

    def list_companies(self) -> list[str]:
        names: set[str] = set()
        for s in self._registry.get('skills') or []:
            if s.get('type') == 'company_convention' and s.get('company'):
                names.add(str(s['company']))
        return sorted(names)
