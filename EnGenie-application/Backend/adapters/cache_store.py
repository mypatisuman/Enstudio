"""
Cache abstraction layer for EngineeringStudio extraction results.

DB-backed: rows live in the `cache_entries` and `cache_manifest` tables of
studio.db (see adapters/db.py). All filesystem reads/writes have been
removed — the previous on-disk JSON cache files are no longer the system
of record.

Key naming convention is preserved unchanged so that all call sites in
main.py continue to work without modification:

  {fhash}_pass0       combined result
  {fhash}_pass1       topology (Pass 1 Sonnet)
  {fhash}_b{N}_pass2  instrument batch N (Pass 2 Haiku)
  {fhash}_pipes_pass3 pipe runs (Pass 2.5 Haiku)
  {fhash}_notes_p{N}_pass4  notes/legend page N
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from adapters.db import get_db


class CacheStore:
    """Thread-safe per-project cache backed by SQLite.

    The hub Path is accepted (and ignored) for API compatibility with the
    historical filesystem-based constructor; the actual storage location is
    determined by adapters/db.py.
    """

    def __init__(self, hub: Optional[Path] = None) -> None:
        self._hub = Path(hub) if hub else None
        self._lock = threading.Lock()

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _scan_record(key: str, response: Any, *, file_hash: str,
                      filename: str, pass_num: int) -> dict:
        """Translate an LLMResponse / plain-dict into the manifest scan dict."""
        if isinstance(response, dict):
            tin      = int(response.get('tokens_in',  0) or 0)
            tout     = int(response.get('tokens_out', 0) or 0)
            model    = response.get('model', '')
            provider = response.get('provider', '')
            cost     = float(response.get('cost_usd', 0.0))
        else:
            tin      = int(getattr(response, 'input_tokens',  0) or 0)
            tout     = int(getattr(response, 'output_tokens', 0) or 0)
            model    = getattr(response, 'model',    '')
            provider = getattr(response, 'provider', '')
            cost     = float(getattr(response, 'cost_usd', 0.0))
        return {
            'key':        key,
            'file_hash':  file_hash,
            'filename':   filename,
            'pass':       pass_num,
            'provider':   provider,
            'model':      model,
            'tokens_in':  tin,
            'tokens_out': tout,
            'cost_usd':   round(cost, 6),
            'timestamp':  datetime.now(timezone.utc).isoformat(),
        }

    # ── Public API ────────────────────────────────────────────────────────

    def get(self, pid: str, key: str) -> Optional[dict]:
        """Load cached result. Returns None if cache miss."""
        row = get_db().execute(
            'SELECT data_json FROM cache_entries WHERE pid = ? AND cache_key = ?',
            (pid, key),
        ).fetchone()
        if not row or row['data_json'] is None:
            return None
        try:
            data = json.loads(row['data_json'])
            print(f'Cache hit: {key}')
            return data
        except Exception:
            return None

    def put(
        self,
        pid: str,
        key: str,
        data: dict,
        response: Any = None,
        *,
        file_hash: str = '',
        filename: str = '',
        pass_num: int = 0,
    ) -> None:
        """Save result + (optionally) append a manifest scan record."""
        conn = get_db()
        with self._lock:
            conn.execute(
                'INSERT OR REPLACE INTO cache_entries (pid, cache_key, data_json) '
                'VALUES (?, ?, ?)',
                (pid, key, json.dumps(data, ensure_ascii=False)),
            )
            print(f'Cached: {key}')

            if response is None:
                return

            scan = self._scan_record(
                key, response, file_hash=file_hash, filename=filename,
                pass_num=pass_num,
            )

            existing = conn.execute(
                'SELECT scan_json, total_tokens, total_cost FROM cache_manifest '
                'WHERE pid = ?', (pid,),
            ).fetchone()
            if existing:
                try:
                    scans = json.loads(existing['scan_json']) if existing['scan_json'] else []
                except Exception:
                    scans = []
                scans.append(scan)
                total_tokens = (existing['total_tokens'] or 0) + scan['tokens_in'] + scan['tokens_out']
                total_cost   = round(
                    (existing['total_cost'] or 0.0) + scan['cost_usd'], 6,
                )
            else:
                scans = [scan]
                total_tokens = scan['tokens_in'] + scan['tokens_out']
                total_cost   = scan['cost_usd']
            conn.execute(
                'INSERT OR REPLACE INTO cache_manifest '
                '(pid, scan_json, total_tokens, total_cost, last_scan) '
                'VALUES (?, ?, ?, ?, ?)',
                (pid, json.dumps(scans, ensure_ascii=False),
                 total_tokens, total_cost, scan['timestamp']),
            )

    def has(self, pid: str, key: str) -> bool:
        """Return True if the key is cached for `pid`."""
        row = get_db().execute(
            'SELECT 1 FROM cache_entries WHERE pid = ? AND cache_key = ? LIMIT 1',
            (pid, key),
        ).fetchone()
        return row is not None

    def list_keys(self, pid: str) -> list:
        """Return all cache keys for a project, sorted."""
        rows = get_db().execute(
            'SELECT cache_key FROM cache_entries WHERE pid = ? ORDER BY cache_key',
            (pid,),
        ).fetchall()
        return [r['cache_key'] for r in rows]

    def get_manifest(self, pid: str) -> dict:
        """Return the manifest dict for the cache-stats endpoint.

        Shape preserved exactly:
            {scans: [...], total_tokens: int, total_cost_usd: float, last_scan: str|None}
        """
        row = get_db().execute(
            'SELECT scan_json, total_tokens, total_cost, last_scan '
            '  FROM cache_manifest WHERE pid = ?', (pid,),
        ).fetchone()
        if row is None:
            return {
                'scans':          [],
                'total_tokens':   0,
                'total_cost_usd': 0.0,
                'last_scan':      None,
            }
        try:
            scans = json.loads(row['scan_json']) if row['scan_json'] else []
        except Exception:
            scans = []
        return {
            'scans':          scans,
            'total_tokens':   row['total_tokens'] or 0,
            'total_cost_usd': float(row['total_cost'] or 0.0),
            'last_scan':      row['last_scan'],
        }

    def invalidate(self, pid: str, key: str) -> None:
        """Delete a cache entry and remove its manifest scan record."""
        conn = get_db()
        with self._lock:
            cur = conn.execute(
                'DELETE FROM cache_entries WHERE pid = ? AND cache_key = ?',
                (pid, key),
            )
            if cur.rowcount:
                print(f'Cache invalidated: {key}')

            row = conn.execute(
                'SELECT scan_json FROM cache_manifest WHERE pid = ?', (pid,),
            ).fetchone()
            if not row or not row['scan_json']:
                return
            try:
                scans = json.loads(row['scan_json'])
            except Exception:
                return
            kept = [s for s in scans if s.get('key') != key]
            if len(kept) == len(scans):
                return  # nothing to update

            total_tokens = sum(int(s.get('tokens_in', 0) or 0) +
                               int(s.get('tokens_out', 0) or 0)
                               for s in kept)
            total_cost   = round(sum(float(s.get('cost_usd', 0.0) or 0.0)
                                     for s in kept), 6)
            last_scan    = kept[-1].get('timestamp') if kept else None
            conn.execute(
                'UPDATE cache_manifest SET scan_json = ?, total_tokens = ?, '
                '  total_cost = ?, last_scan = ? WHERE pid = ?',
                (json.dumps(kept, ensure_ascii=False),
                 total_tokens, total_cost, last_scan, pid),
            )
