"""Data-integrity checks for the graph tables (Phase 5).

These look for the states that document identity is supposed to make
impossible. They are read-only: every check reports, none repairs, because
every problem listed here has more than one plausible correct repair and
guessing at one is how extraction data gets silently rewritten.

Why this is Python and not a database constraint: `PRAGMA foreign_keys` is
OFF for this connection (adapters/db.py), and turning it on would start
rejecting writes across the whole legacy dataset mid-session. The indexes
these queries rely on are created by db.migrate_db(). Enforcing referential
integrity at the database layer is recorded as a Phase 6 candidate.
"""
from __future__ import annotations

from adapters import db as _db


def _rows(conn, sql, params=()):
    return [tuple(r) for r in conn.execute(sql, params).fetchall()]


def check_integrity(pid: str | None = None) -> dict:
    """Return {check_name: [offending rows]} — empty lists mean healthy.

    Scoped to one project when `pid` is given, otherwise the whole database.
    """
    conn = _db.get_db()
    where = 'WHERE pid = ?' if pid else ''
    p = (pid,) if pid else ()

    report: dict[str, list] = {}

    # An edge endpoint with no matching node. Renders as a missing pipe, or
    # silently vanishes in the frontend's id filter.
    report['orphan_edges'] = _rows(conn, f"""
        SELECT e.id, e.pid, e.from_id, e.to_id FROM edges e
        {where.replace('pid', 'e.pid')}
        {'AND' if pid else 'WHERE'} (
            NOT EXISTS (SELECT 1 FROM nodes n WHERE n.pid = e.pid AND n.id = e.from_id)
         OR NOT EXISTS (SELECT 1 FROM nodes n WHERE n.pid = e.pid AND n.id = e.to_id))
    """, p)

    # An edge joining two documents. Extraction is per-document, so a real
    # cross-document connection cannot be produced by it — this means an id
    # collided, or an edge outlived the document that owned it.
    report['cross_document_edges'] = _rows(conn, f"""
        SELECT e.id, e.pid, e.from_id, e.to_id, ns.source_id, nt.source_id
          FROM edges e
          JOIN nodes ns ON ns.pid = e.pid AND ns.id = e.from_id
          JOIN nodes nt ON nt.pid = e.pid AND nt.id = e.to_id
        {where.replace('pid', 'e.pid')}
        {'AND' if pid else 'WHERE'} ns.source_id IS NOT NULL
          AND nt.source_id IS NOT NULL
          AND ns.source_id != nt.source_id
    """, p)

    # A node or edge attributed to a document that is not in its project.
    report['nodes_with_foreign_source'] = _rows(conn, f"""
        SELECT n.id, n.pid, n.source_id FROM nodes n
        {where.replace('pid', 'n.pid')}
        {'AND' if pid else 'WHERE'} n.source_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM sources s WHERE s.id = n.source_id AND s.pid = n.pid)
    """, p)
    report['edges_with_foreign_source'] = _rows(conn, f"""
        SELECT e.id, e.pid, e.source_id FROM edges e
        {where.replace('pid', 'e.pid')}
        {'AND' if pid else 'WHERE'} e.source_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM sources s WHERE s.id = e.source_id AND s.pid = e.pid)
    """, p)

    # A node pointing at a project that no longer exists.
    report['nodes_without_project'] = _rows(conn, f"""
        SELECT n.id, n.pid FROM nodes n
        {where.replace('pid', 'n.pid')}
        {'AND' if pid else 'WHERE'} NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = n.pid)
    """, p)

    # Two documents claiming the same page label. Legal for a real drawing
    # number shared between revisions, so this is reported, not an error.
    report['pages_shared_across_documents'] = _rows(conn, f"""
        SELECT pid, json_extract(extra_json,'$.drawing') AS drawing,
               COUNT(DISTINCT source_id) AS docs
          FROM nodes
        {where}
        {'AND' if pid else 'WHERE'} source_id IS NOT NULL
          AND json_extract(extra_json,'$.drawing') IS NOT NULL
          AND json_extract(extra_json,'$.drawing') != ''
         GROUP BY pid, drawing HAVING docs > 1
    """, p)

    # Canvas positions and review rows left behind by a deleted node.
    report['stale_canvas_positions'] = _rows(conn, f"""
        SELECT c.pid, c.node_id FROM canvas_positions c
        {where.replace('pid', 'c.pid')}
        {'AND' if pid else 'WHERE'} NOT EXISTS
            (SELECT 1 FROM nodes n WHERE n.pid = c.pid AND n.id = c.node_id)
    """, p)

    # The same file uploaded twice as two documents. Upload dedupes on hash,
    # so this means the dedupe was bypassed.
    report['duplicate_source_hashes'] = _rows(conn, f"""
        SELECT pid, file_hash, COUNT(*) FROM sources
        {where}
        {'AND' if pid else 'WHERE'} file_hash IS NOT NULL AND file_hash != ''
         GROUP BY pid, file_hash HAVING COUNT(*) > 1
    """, p)

    return report


def describe_integrity(report: dict) -> str:
    """One-line-per-problem summary. Empty string when everything is clean."""
    bad = {k: v for k, v in report.items() if v}
    if not bad:
        return ''
    return '\n'.join(f'{k}: {len(v)} row(s)' for k, v in sorted(bad.items()))
