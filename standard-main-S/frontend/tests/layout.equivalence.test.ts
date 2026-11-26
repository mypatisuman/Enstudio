// Phase 4, Step 12/13 — proves the spatial-grid collision resolver in
// extractedLayout() produces the SAME layout as the exhaustive O(n^2) sweep
// it replaced.
//
// tests/_ref/extractedLayout.ref.ts is a byte-for-byte copy of the module with
// only the collision block reverted, so this compares optimized vs original on
// identical inputs through identical surrounding code. A speed-up that moved a
// symbol would fail here — the brief's rule that an optimization changing
// behaviour is a failed optimization.

import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { extractedLayout } from '../src/components/canvas/extractedLayout.ts'
import { extractedLayout as refLayout } from './_ref/extractedLayout.ref.ts'

const CW = 3000, CH = 2200
let checks = 0

function compare(label: string, nodes: any[], edges: any[], size: (n: any) => { w: number; h: number }) {
  const a = extractedLayout(structuredClone(nodes), size, CW, CH, structuredClone(edges))
  const b = refLayout(structuredClone(nodes), size, CW, CH, structuredClone(edges))

  assert.equal(a.pos.size, b.pos.size, `${label}: node count`)
  let maxDrift = 0
  for (const [id, p] of b.pos) {
    const q = a.pos.get(id)
    assert.ok(q, `${label}: ${id} missing from optimized layout`)
    maxDrift = Math.max(maxDrift, Math.abs(p.x - q!.x), Math.abs(p.y - q!.y))
  }
  assert.equal(maxDrift, 0, `${label}: positions drifted by ${maxDrift}px`)

  assert.deepEqual([...a.sizes.keys()].sort(), [...b.sizes.keys()].sort(), `${label}: size keys`)
  for (const [id, s] of b.sizes) assert.deepEqual(a.sizes.get(id), s, `${label}: size of ${id}`)

  checks++
  console.log(`  ok  ${label.padEnd(34)} ${String(nodes.length).padStart(5)} nodes  drift ${maxDrift}px`)
}

function makeGraph(n: number, edgeCount: number, seedInit = 987654321) {
  let seed = seedInit
  const rand = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648 }
  const nodes = Array.from({ length: n }, (_, i) => ({
    id: `n${i + 1}`, label: `T-${i + 1}`, kind: 'vessel',
    x: rand(), y: rand(), page_w: 4096, page_h: 2896,
  }))
  const edges = Array.from({ length: edgeCount }, (_, i) => ({
    source: `n${(i % n) + 1}`, target: `n${((i * 7 + 3) % n) + 1}`, kind: 'process',
  }))
  return { nodes, edges }
}

const uniform = () => ({ w: 60, h: 40 })
// Mixed sizes exercise the CELL = maxDim + PADDING bound: a wide equipment box
// next to a small instrument is the case where a too-small cell would drop a
// real overlap.
const mixed = (n: any) => n.kind === 'equipment' ? { w: 200, h: 70 }
  : n.kind === 'valve' ? { w: 44, h: 44 } : { w: 76, h: 40 }

console.log('synthetic:')
for (const [n, e] of [[50, 49], [100, 99], [300, 299], [500, 499], [1000, 999]] as [number, number][]) {
  const { nodes, edges } = makeGraph(n, e)
  compare(`uniform ${n}`, nodes, edges, uniform)
}

// No edges -> no align groups -> the sameH/sameV branch never fires.
{
  const { nodes } = makeGraph(400, 0)
  compare('no edges (no align groups)', nodes, [], uniform)
}

// Heterogeneous sizes.
{
  const { nodes, edges } = makeGraph(400, 399)
  nodes.forEach((n: any, i: number) => { n.kind = i % 5 === 0 ? 'equipment' : i % 3 === 0 ? 'valve' : 'instrument' })
  compare('mixed sizes', nodes, edges, mixed)
}

// Dense cluster: every node in a tiny region, so nearly every pair overlaps and
// the grid degenerates to one bucket — the worst case for the optimization and
// the strictest ordering test.
{
  const { nodes, edges } = makeGraph(250, 249)
  nodes.forEach((n: any) => { n.x = 0.5 + (n.x - 0.5) * 0.01; n.y = 0.5 + (n.y - 0.5) * 0.01 })
  compare('dense cluster (one bucket)', nodes, edges, uniform)
}

// Sparse: nothing overlaps, so the loop must exit on iteration 1 unchanged.
{
  const nodes = Array.from({ length: 300 }, (_, i) => ({
    id: `n${i + 1}`, label: `T-${i}`, kind: 'vessel',
    x: (i % 20) / 20 + 0.01, y: Math.floor(i / 20) / 20 + 0.01, page_w: 4096, page_h: 2896,
  }))
  compare('sparse grid (no overlaps)', nodes, [], uniform)
}

// Multi-drawing path.
{
  const { nodes, edges } = makeGraph(600, 599)
  nodes.forEach((n: any, i: number) => {
    n.drawing = `page_${(i % 4) + 1}`
    n.page_w = i % 2 ? 2048 : 4096
    n.page_h = i % 2 ? 4096 : 2048
  })
  compare('4 drawings', nodes, edges, uniform)
}

// Vendor packages are excluded from `resolvable`; make sure the exclusion and
// the post-collision packVendorPackages still line up.
{
  const { nodes, edges } = makeGraph(200, 199)
  nodes.forEach((n: any, i: number) => {
    if (i % 20 === 0) n.kind = 'vendor_package'
    else if (i % 20 < 4) { n.kind = 'instrument'; n.equipment_ref = `n${Math.floor(i / 20) * 20 + 1}` }
  })
  compare('vendor packages', nodes, edges, mixed)
}

// ── real projects ───────────────────────────────────────────────────────────
const DB = '../EngineeringHub/EngineeringHub/studio.db'
const PY = '../backend/.venv/Scripts/python.exe'
if (existsSync(DB) && existsSync(PY)) {
  console.log('real projects:')
  const raw = execFileSync(PY, ['-c', `
import sqlite3, json
c=sqlite3.connect(${JSON.stringify(DB)}); c.row_factory=sqlite3.Row
out={}
for (pid,) in c.execute("SELECT DISTINCT pid FROM nodes"):
    ns=[];es=[]
    for r in c.execute("SELECT id,label,kind,x,y,extra_json FROM nodes WHERE pid=?",(pid,)):
        ex=json.loads(r['extra_json'] or '{}')
        ns.append({'id':r['id'],'label':r['label'] or '','kind':r['kind'] or '','x':r['x'],'y':r['y'],
                   'equipment_ref':ex.get('equipment_ref'),'drawing':ex.get('drawing',''),
                   'page_w':ex.get('page_w'),'page_h':ex.get('page_h')})
    for r in c.execute("SELECT from_id,to_id,kind FROM edges WHERE pid=?",(pid,)):
        es.append({'source':r['from_id'],'target':r['to_id'],'kind':r['kind'] or 'process'})
    out[pid]={'nodes':ns,'edges':es}
print(json.dumps(out))`], { encoding: 'utf-8', maxBuffer: 64e6 })
  const projects = JSON.parse(raw)
  for (const [pid, g] of Object.entries<any>(projects)) {
    if (!g.nodes.length) continue
    compare(pid, g.nodes, g.edges, mixed)
  }
} else {
  console.log('real projects: SKIPPED (no studio.db)')
}

console.log(`\n${checks} layouts compared, 0px drift on all of them`)
