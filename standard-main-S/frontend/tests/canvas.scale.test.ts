// Phase 3 Step 12 — large-graph SAFETY (not optimisation).
//
// Run: node tests/canvas.scale.test.ts
//
// Checks that 100 / 500 / 1000 nodes produce a graph that is correct: no
// crash, no NaN, no duplicate ids, no dangling edges, no catastrophic
// overlap. Timing is RECORDED, not asserted — the layout algorithm is
// explicitly out of scope until Phase 4, so a slow result is a finding to
// report, not a failure.

import assert from 'node:assert/strict'

import { extractedLayout } from '../src/components/canvas/extractedLayout.ts'
import {
  checkGraphIntegrity, makeEdgeId,
} from '../src/features/canvas/utils/graphIntegrity.ts'

const NODE_W = 60
const NODE_H = 40
const size = () => ({ w: NODE_W, h: NODE_H })

function buildGraph(n: number) {
  // Deterministic pseudo-random placement — a fixed LCG so a failure is
  // always reproducible.
  let seed = 12345
  const rand = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648
    return seed / 2147483648
  }
  const nodes = Array.from({ length: n }, (_, i) => ({
    id: `n${i + 1}`,
    label: `T-${i + 1}`,
    kind: 'vessel',
    x: rand(),
    y: rand(),
    page_w: 4096,
    page_h: 2896,
  }))
  const edges = Array.from({ length: Math.max(0, n - 1) }, (_, i) => ({
    source: `n${i + 1}`,
    target: `n${i + 2}`,
  }))
  return { nodes, edges }
}

const results: { n: number; ms: number; overlaps: number }[] = []

for (const n of [100, 500, 1000]) {
  const { nodes, edges } = buildGraph(n)

  const t0 = performance.now()
  const { pos } = extractedLayout(nodes as never, size, 3000, 2200, edges)
  const ms = performance.now() - t0

  // Every node placed, with a finite position.
  assert.equal(pos.size, n, `${n}: every node must be placed`)
  for (const [id, p] of pos) {
    assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y),
      `${n}: ${id} has a non-finite position (${p.x}, ${p.y})`)
  }

  // Unique ids and no dangling edges once the graph reaches React Flow.
  const seen = new Map<string, number>()
  const rfNodes = nodes.map(nd => ({ id: nd.id, position: pos.get(nd.id)! }))
  const rfEdges = edges.map(e => ({
    id: makeEdgeId(e.source, e.target, seen),
    source: e.source, target: e.target,
  }))
  const report = checkGraphIntegrity(rfNodes, rfEdges)
  assert.equal(report.ok, true,
    `${n}: integrity failed -> ${JSON.stringify(report)}`)

  // Catastrophic overlap check: count node pairs sharing almost the same
  // spot. The collision solver is bounded (50 iterations x 4px), so some
  // residual overlap is expected on a dense sheet and is NOT asserted away —
  // what would be catastrophic is a large fraction stacked on one point.
  let coincident = 0
  const entries = [...pos.entries()]
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      const a = entries[i][1], b = entries[j][1]
      if (Math.abs(a.x - b.x) < 1 && Math.abs(a.y - b.y) < 1) coincident++
    }
  }
  assert.ok(coincident < n * 0.05,
    `${n}: ${coincident} coincident node pairs — layout collapsed`)

  results.push({ n, ms: Math.round(ms), overlaps: coincident })
}

console.log('canvas.scale.test.ts — layout timing (recorded, not asserted):')
for (const r of results) {
  console.log(`  ${String(r.n).padStart(4)} nodes  ${String(r.ms).padStart(6)} ms   coincident pairs: ${r.overlaps}`)
}
console.log('canvas.scale.test.ts: all safety assertions passed')
