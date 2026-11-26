// Phase 4, Step 11 — performance regression guard.
//
// Budgets are ~3x the measured post-optimization time so ordinary machine
// noise cannot fail the run, but reverting the spatial grid would: the
// exhaustive sweep measured 926 ms at 1000 nodes against a 250 ms budget here.
// This asserts complexity class, not a stopwatch reading.

import assert from 'node:assert/strict'
import { extractedLayout } from '../src/components/canvas/extractedLayout.ts'
import { pickHandles } from '../src/features/canvas/utils/edgeHelpers.ts'

const CW = 3000, CH = 2200
const size = () => ({ w: 60, h: 40 })

function makeGraph(n: number, e: number) {
  let seed = 987654321
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
  return {
    nodes: Array.from({ length: n }, (_, i) => ({
      id: `n${i + 1}`, label: `T-${i}`, kind: 'vessel', x: rand(), y: rand(),
      page_w: 4096, page_h: 2896,
    })),
    edges: Array.from({ length: e }, (_, i) => ({
      source: `n${(i % n) + 1}`, target: `n${((i * 7 + 3) % n) + 1}`, kind: 'process',
    })),
  }
}

const median = (fn: () => void, reps = 3) => {
  const s: number[] = []
  for (let i = 0; i < reps; i++) { const t = performance.now(); fn(); s.push(performance.now() - t) }
  return s.sort((a, b) => a - b)[Math.floor(reps / 2)]
}

// Layout budgets. 1000 nodes is the brief's stated target.
for (const [n, budget, was] of [[500, 60, 84], [1000, 250, 927], [2000, 1000, 4267]] as [number, number, number][]) {
  const { nodes, edges } = makeGraph(n, n - 1)
  const ms = median(() => { extractedLayout(nodes as never, size, CW, CH, edges) })
  console.log(`  extractedLayout ${String(n).padStart(4)} nodes  ${ms.toFixed(1).padStart(7)} ms   budget ${budget} ms   (was ${was} ms)`)
  assert.ok(ms < budget, `extractedLayout(${n}) took ${ms.toFixed(1)}ms, budget ${budget}ms`)
}

// pickHandles must be O(1) per edge, not O(nodes). With a Map the 1000/5000
// case is ~0.6 ms; the array scan it replaced was ~17.6 ms.
{
  const { nodes, edges } = makeGraph(1000, 5000)
  const { pos } = extractedLayout(nodes as never, size, CW, CH, edges)
  const idx = new Map(nodes.map(n => [n.id, {
    id: n.id, type: 'vessel_v', position: pos.get(n.id)!, width: 60, height: 40, data: {},
  }]))
  const ms = median(() => { for (const e of edges) pickHandles(idx as never, e.source, e.target) })
  console.log(`  pickHandles     5000 edges ${ms.toFixed(1).padStart(7)} ms   budget 5 ms   (was 17.6 ms)`)
  assert.ok(ms < 5, `pickHandles over 5000 edges took ${ms.toFixed(1)}ms`)
}

console.log('\nperformance budgets OK')
