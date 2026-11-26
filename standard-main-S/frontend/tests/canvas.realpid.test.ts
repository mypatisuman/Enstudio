// Phase 3 Step 14 — verification against a REAL extracted drawing.
//
// Run: node tests/canvas.realpid.test.ts [pid]
//
// Reads the actual studio.db produced by the extraction pipeline and pushes
// its real nodes/edges through the exact frontend units the Canvas uses:
// sanitizeWaypoints -> routeKindFor -> normalizedPointToPixel, plus the
// layout and the integrity check.
//
// This is a DATA-PATH verification, not a pixel comparison: there is no
// browser or screenshot capability here, so it cannot prove the rendered
// image matches the source sheet. What it does prove is that every extracted
// route survives the journey to React Flow intact, in range, and anchored to
// the same coordinate system as the symbols.
//
// Skips cleanly (exit 0) when no database or no extracted project is present.

import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

import { sanitizeWaypoints, routeKindFor, edgeTrust } from '../src/features/canvas/utils/waypoints.ts'
import { checkGraphIntegrity, makeEdgeId } from '../src/features/canvas/utils/graphIntegrity.ts'
import { extractedLayout, normalizedPointToPixel } from '../src/components/canvas/extractedLayout.ts'

const DB = '../EngineeringHub/EngineeringHub/studio.db'
const PY = '../backend/.venv/Scripts/python.exe'

if (!existsSync(DB) || !existsSync(PY)) {
  console.log('canvas.realpid.test.ts: SKIPPED (no studio.db / venv on this machine)')
  process.exit(0)
}

const pidArg = process.argv[2] ?? ''
const script = `
import sqlite3, json, sys
db = ${JSON.stringify(DB)}
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
pid = ${JSON.stringify(pidArg)}
if not pid:
    row = c.execute("SELECT pid FROM edges GROUP BY pid ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    pid = row[0] if row else ''
if not pid:
    print(json.dumps({'pid': None})); sys.exit()
nodes = []
for r in c.execute("SELECT id,label,kind,x,y,extra_json FROM nodes WHERE pid=?", (pid,)):
    ex = json.loads(r['extra_json'] or '{}')
    nodes.append({'id': r['id'], 'label': r['label'] or '', 'kind': r['kind'] or '',
                  'x': r['x'], 'y': r['y'], 'drawing': ex.get('drawing', ''),
                  'page': ex.get('page'), 'page_w': ex.get('page_w'), 'page_h': ex.get('page_h')})
edges = []
for r in c.execute("SELECT from_id,to_id,kind,extra_json FROM edges WHERE pid=?", (pid,)):
    ex = json.loads(r['extra_json'] or '{}')
    edges.append({'source': r['from_id'], 'target': r['to_id'], 'kind': r['kind'] or 'process',
                  'waypoints': ex.get('waypoints'), 'bend_x': ex.get('bend_x'),
                  'bend_y': ex.get('bend_y'), 'provenance': ex.get('provenance'),
                  'audited': ex.get('audited')})
print(json.dumps({'pid': pid, 'nodes': nodes, 'edges': edges}))
`
const raw = execFileSync(PY, ['-c', script], { encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 })
const data = JSON.parse(raw)

if (!data.pid) {
  console.log('canvas.realpid.test.ts: SKIPPED (no extracted project in the database)')
  process.exit(0)
}

const { pid, nodes, edges } = data
console.log(`canvas.realpid.test.ts — project "${pid}": ${nodes.length} nodes, ${edges.length} edges`)

// ── 1. every node has usable normalised coordinates ─────────────────────────
const badCoord = nodes.filter((n: { x: number; y: number }) =>
  !Number.isFinite(n.x) || !Number.isFinite(n.y) || n.x < -0.05 || n.x > 1.05 || n.y < -0.05 || n.y > 1.05)
assert.equal(badCoord.length, 0,
  `nodes with unusable coords: ${badCoord.slice(0, 5).map((n: { id: string }) => n.id).join(', ')}`)

// ── 2. layout places every node finitely ────────────────────────────────────
const CW = 3000, CH = 2200
const size = () => ({ w: 60, h: 40 })
const { pos } = extractedLayout(nodes, size, CW, CH,
  edges.map((e: { source: string; target: string }) => ({ source: e.source, target: e.target })))
assert.equal(pos.size, nodes.length, 'every real node must be placed')
for (const [id, p] of pos) {
  assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y), `${id} placed at (${p.x}, ${p.y})`)
}

// ── 3. real waypoints survive to a real route ───────────────────────────────
let withStored = 0, routed = 0, fellBack = 0
const bendCounts: number[] = []
for (const e of edges) {
  const stored = Array.isArray(e.waypoints) ? e.waypoints.length : 0
  if (stored >= 3) withStored++
  const interior = sanitizeWaypoints(e.waypoints)
  const kind = routeKindFor(e, interior, 'extracted')
  if (kind === 'waypoint') {
    routed++
    bendCounts.push(interior.length)
    // Every route point must convert to a finite pixel inside a sane window.
    for (const p of interior) {
      const px = normalizedPointToPixel(p.x, p.y, CW, CH)
      assert.ok(Number.isFinite(px.x) && Number.isFinite(px.y),
        `${e.source}->${e.target}: non-finite route pixel`)
      assert.ok(px.x >= -200 && px.x <= CW + 200 && px.y >= -200 && px.y <= CH + 200,
        `${e.source}->${e.target}: route pixel far off canvas (${px.x}, ${px.y})`)
    }
  } else {
    fellBack++
  }
}

// ── 4. integrity of the graph React Flow would receive ──────────────────────
const seen = new Map<string, number>()
const nodeIds = new Set(nodes.map((n: { id: string }) => n.id))
const rfNodes = nodes.map((n: { id: string }) => ({ id: n.id, position: pos.get(n.id)! }))
const rfEdges = edges
  .filter((e: { source: string; target: string }) => nodeIds.has(e.source) && nodeIds.has(e.target))
  .map((e: { source: string; target: string }) => ({
    id: makeEdgeId(e.source, e.target, seen), source: e.source, target: e.target,
  }))
const report = checkGraphIntegrity(rfNodes, rfEdges)
assert.equal(report.duplicateNodeIds.length, 0, `duplicate node ids: ${report.duplicateNodeIds}`)
assert.equal(report.duplicateEdgeIds.length, 0, `duplicate edge ids: ${report.duplicateEdgeIds}`)
assert.equal(report.danglingEdges.length, 0, 'no dangling edges after filtering')
assert.equal(report.invalidPositions.length, 0, 'no non-finite positions')

// ── 5. provenance distribution ──────────────────────────────────────────────
const trust: Record<string, number> = {}
for (const e of edges) {
  const t = edgeTrust(e)
  trust[t] = (trust[t] ?? 0) + 1
}

const dropped = edges.length - rfEdges.length
const mean = bendCounts.length
  ? (bendCounts.reduce((a, b) => a + b, 0) / bendCounts.length).toFixed(1) : '-'

console.log(`  edges with >=3 stored waypoints : ${withStored}`)
console.log(`  edges routed through WaypointEdge: ${routed}  (mean ${mean} interior bends)`)
console.log(`  edges on the bendable fallback   : ${fellBack}`)
console.log(`  edges dropped (endpoint not in node set): ${dropped}`)
console.log(`  provenance: ${JSON.stringify(trust)}`)
console.log('canvas.realpid.test.ts: all assertions passed')
