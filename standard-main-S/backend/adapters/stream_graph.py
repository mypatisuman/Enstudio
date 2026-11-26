"""
adapters/stream_graph.py — Process stream topology graph for canvas layout.

StreamGraph analyses nodes/edges to identify:
  - Main process stream (left-to-right flow)
  - Recycle streams
  - Splits and merges
  - Y-level assignments per stream type

Used by the /api/editor/<pid>/stream-graph route to drive canvas layout.
"""

from __future__ import annotations

from typing import Any


class StreamGraph:
    """Build a directed process topology from YMPL nodes + edges."""

    def __init__(self, nodes: list[dict], edges: list[dict],
                 conventions: Any = None) -> None:
        self._nodes       = nodes or []
        self._edges       = edges or []
        self._conventions = conventions
        self._streams:  list[dict] = []
        self._merges:   list[dict] = []
        self._splits:   list[dict] = []
        self._recycles: list[dict] = []
        self._positions: dict[str, dict] = {}

    # ── Public fluent API ─────────────────────────────────────────────────────

    def build(self) -> 'StreamGraph':
        """Analyse topology and populate stream/split/merge/recycle lists."""
        self._streams  = self._find_streams()
        self._splits   = self._find_splits()
        self._merges   = self._find_merges()
        self._recycles = self._find_recycles()
        return self

    def assign_y_levels(self, rules: dict) -> 'StreamGraph':
        """Assign y-coordinate bands per stream using layout rules."""
        base_y      = rules.get('base_y', 400)
        recycle_y   = rules.get('recycle_y', base_y + 120)
        vent_y      = rules.get('vent_y', base_y - 140)
        utility_y   = rules.get('utility_y', base_y + 200)
        safety_y    = rules.get('safety_y', base_y - 200)

        node_ids = [n.get('id', n.get('label', '')) for n in self._nodes]
        step_x   = rules.get('node_spacing_x', 160)

        for i, nid in enumerate(node_ids):
            self._positions[nid] = {'x': 80 + i * step_x, 'y': base_y}

        for r in self._recycles:
            for nid in r.get('node_ids', []):
                if nid in self._positions:
                    self._positions[nid]['y'] = recycle_y

        return self

    def to_dict(self, rules: dict | None = None) -> dict:
        """Serialise to JSON-safe dict for the Flask route."""
        return {
            'streams':   self._streams,
            'splits':    self._splits,
            'merges':    self._merges,
            'recycles':  self._recycles,
            'positions': self._positions,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _node_by_id(self, nid: str) -> dict:
        for n in self._nodes:
            if n.get('id') == nid or n.get('label') == nid:
                return n
        return {}

    def _out_edges(self, nid: str) -> list[dict]:
        return [e for e in self._edges if e.get('from') == nid and e.get('kind') != 'recycle']

    def _in_edges(self, nid: str) -> list[dict]:
        return [e for e in self._edges if e.get('to') == nid and e.get('kind') != 'recycle']

    def _find_streams(self) -> list[dict]:
        stream_edges = [e for e in self._edges if e.get('kind', 'stream') in ('stream', None, '')]
        return [{'from': e.get('from'), 'to': e.get('to'), 'label': e.get('label', '')}
                for e in stream_edges]

    def _find_splits(self) -> list[dict]:
        splits = []
        seen: set[str] = set()
        for n in self._nodes:
            nid = n.get('id', n.get('label', ''))
            outs = self._out_edges(nid)
            if len(outs) > 1 and nid not in seen:
                seen.add(nid)
                splits.append({'node': nid, 'to': [e.get('to') for e in outs]})
        return splits

    def _find_merges(self) -> list[dict]:
        merges = []
        seen: set[str] = set()
        for n in self._nodes:
            nid = n.get('id', n.get('label', ''))
            ins = self._in_edges(nid)
            if len(ins) > 1 and nid not in seen:
                seen.add(nid)
                merges.append({'node': nid, 'from': [e.get('from') for e in ins]})
        return merges

    def _find_recycles(self) -> list[dict]:
        recycle_edges = [e for e in self._edges if e.get('kind') == 'recycle']
        return [{'from': e.get('from'), 'to': e.get('to'),
                 'node_ids': [e.get('from'), e.get('to')]}
                for e in recycle_edges]
