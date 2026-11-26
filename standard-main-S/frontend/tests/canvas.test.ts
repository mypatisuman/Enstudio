// Phase 3 Canvas regression suite.
//
// Run: node tests/canvas.test.ts        (Node >= 23.6 strips types natively)
//
// Lives OUTSIDE src/ on purpose: tsconfig.app.json has `include: ["src"]` and
// `types: ["vite/client"]`, so a test importing node:assert from inside src/
// adds a TS2591 error to the build (the two pre-existing *.test.ts files in
// src/ do exactly that). Keeping these here means the suite costs the tsc
// baseline nothing.
//
// The 20 scenarios the phase brief lists, plus the routing/provenance rules.
// No React renderer, no LLM, no Tauri: every unit under test is pure.

import assert from 'node:assert/strict'

import {
  sanitizeWaypoints, routeKindFor, edgeTrust, buildRoute,
} from '../src/features/canvas/utils/waypoints.ts'
import {
  checkGraphIntegrity, describeIntegrity, makeEdgeId,
} from '../src/features/canvas/utils/graphIntegrity.ts'
import {
  cellSizeFor, extractedLayout, normalizedPointToPixel, pixelPointToNormalized,
  pixelToNormalized, EXTRACTED_MARGIN,
} from '../src/components/canvas/extractedLayout.ts'
import { edgeFlowType } from '../src/features/canvas/utils/edgeHelpers.ts'
import { roundedPolyline } from '../src/features/canvas/utils/pipePath.ts'

let passed = 0
function test(name: string, fn: () => void) {
  try {
    fn()
    passed++
  } catch (err) {
    console.error(`FAIL: ${name}`)
    throw err
  }
}

const size = () => ({ w: 60, h: 40 })
const node = (id: string, x: number, y: number, extra: Record<string, unknown> = {}) =>
  ({ id, label: id, kind: 'vessel', x, y, ...extra }) as never

// ── 1-3. routing: straight, bend, multi-segment ─────────────────────────────

test('1. single pipe with no bends routes as bendable', () => {
  const interior = sanitizeWaypoints([[0.1, 0.5], [0.9, 0.5]])
  assert.deepEqual(interior, [])
  assert.equal(routeKindFor({ waypoints: [], bend_x: null, bend_y: null },
    interior, 'extracted'), 'bendable')
  assert.equal(edgeFlowType('process', false), 'bendable')
})

test('2. pipe with one real bend routes through the extracted waypoint', () => {
  const interior = sanitizeWaypoints([[0.1, 0.5], [0.5, 0.5], [0.5, 0.9]])
  assert.equal(interior.length, 1)
  assert.deepEqual(interior[0], { x: 0.5, y: 0.5 })
  assert.equal(routeKindFor({ waypoints: [], bend_x: null, bend_y: null },
    interior, 'extracted'), 'waypoint')
  assert.equal(edgeFlowType('process', true), 'waypoint')
})

test('3. multi-segment route keeps every interior bend in order', () => {
  const interior = sanitizeWaypoints([
    [0.1, 0.1], [0.4, 0.1], [0.4, 0.6], [0.8, 0.6], [0.8, 0.9],
  ])
  assert.equal(interior.length, 3)
  assert.deepEqual(interior.map(p => [p.x, p.y]),
    [[0.4, 0.1], [0.4, 0.6], [0.8, 0.6]])
})

// ── 4-9. topology shapes reach the canvas as the backend produced them ──────

test('4. inline valve is two edges, each with its own route', () => {
  const a = sanitizeWaypoints([[0.1, 0.5], [0.3, 0.5], [0.45, 0.5]])
  const b = sanitizeWaypoints([[0.55, 0.5], [0.7, 0.5], [0.9, 0.5]])
  assert.equal(a.length, 1)
  assert.equal(b.length, 1)
  assert.notDeepEqual(a[0], b[0])
})

test('5. T-junction branch keeps its perpendicular leg', () => {
  const branch = sanitizeWaypoints([[0.5, 0.2], [0.5, 0.5], [0.5, 0.5]])
  // duplicate interior point collapses; the leg survives as one bend
  assert.equal(branch.length, 1)
  assert.deepEqual(branch[0], { x: 0.5, y: 0.5 })
})

test('6. 4-way junction: four separate edges each keep their own geometry', () => {
  const legs = [
    sanitizeWaypoints([[0.1, 0.5], [0.3, 0.5], [0.5, 0.5]]),
    sanitizeWaypoints([[0.9, 0.5], [0.7, 0.5], [0.5, 0.5]]),
    sanitizeWaypoints([[0.5, 0.1], [0.5, 0.3], [0.5, 0.5]]),
    sanitizeWaypoints([[0.5, 0.9], [0.5, 0.7], [0.5, 0.5]]),
  ]
  assert.equal(legs.filter(l => l.length === 1).length, 4)
  const uniq = new Set(legs.map(l => `${l[0].x},${l[0].y}`))
  assert.equal(uniq.size, 4, 'each leg has its own bend point')
})

test('7. crossover: two edges may cross on screen without sharing a node', () => {
  const nodes = [node('a', 0.1, 0.5), node('b', 0.9, 0.5),
                 node('c', 0.5, 0.1), node('d', 0.5, 0.9)]
  const edges = [{ source: 'a', target: 'b' }, { source: 'c', target: 'd' }]
  const r = checkGraphIntegrity(
    nodes.map(n => ({ id: (n as { id: string }).id, position: { x: 0, y: 0 } })),
    edges.map((e, i) => ({ id: `e${i}`, ...e })))
  assert.equal(r.ok, true, 'crossing geometry is not a graph error')
  assert.equal(r.selfLoops.length, 0)
})

test('8. instrument branch route is preserved separately from the header', () => {
  const header = sanitizeWaypoints([[0.1, 0.5], [0.9, 0.5]])
  const branch = sanitizeWaypoints([[0.5, 0.5], [0.5, 0.3], [0.5, 0.2]])
  assert.deepEqual(header, [])
  assert.equal(branch.length, 1)
})

test('9. parallel pipes keep distinct routes and distinct edge ids', () => {
  const seen = new Map<string, number>()
  const id1 = makeEdgeId('a', 'b', seen)
  const id2 = makeEdgeId('c', 'd', seen)
  assert.notEqual(id1, id2)
  const p1 = sanitizeWaypoints([[0.1, 0.40], [0.5, 0.40], [0.9, 0.40]])
  const p2 = sanitizeWaypoints([[0.1, 0.42], [0.5, 0.42], [0.9, 0.42]])
  assert.notDeepEqual(p1[0], p2[0])
})

// ── 10-11. pages and drawings ───────────────────────────────────────────────

test('10. two pages land in separate cells and never overlap', () => {
  const nodes = [
    node('p1_n1', 0.1, 0.1, { drawing: 'page_1', page_w: 4096, page_h: 2896 }),
    node('p1_n2', 0.9, 0.9, { drawing: 'page_1', page_w: 4096, page_h: 2896 }),
    node('p2_n1', 0.1, 0.1, { drawing: 'page_2', page_w: 4096, page_h: 2896 }),
    node('p2_n2', 0.9, 0.9, { drawing: 'page_2', page_w: 4096, page_h: 2896 }),
  ]
  const { pos } = extractedLayout(nodes, size, 3000, 2200, [])
  const p1 = ['p1_n1', 'p1_n2'].map(id => pos.get(id)!)
  const p2 = ['p2_n1', 'p2_n2'].map(id => pos.get(id)!)
  const maxX1 = Math.max(...p1.map(p => p.x))
  const minX2 = Math.min(...p2.map(p => p.x))
  assert.ok(minX2 > maxX1, `page 2 must start right of page 1: ${maxX1} vs ${minX2}`)
})

test('11. a portrait sheet gets a portrait cell, not a fixed 2800x2000', () => {
  const landscape = cellSizeFor([{ page_w: 4096, page_h: 2048 }])
  const portrait = cellSizeFor([{ page_w: 2048, page_h: 4096 }])
  assert.ok(landscape.w > landscape.h, 'landscape stays landscape')
  assert.ok(portrait.h > portrait.w, 'portrait stays portrait')
  assert.equal(Math.max(landscape.w, landscape.h), 2800)
  assert.equal(Math.max(portrait.w, portrait.h), 2800)
})

test('11b. unknown page dims fall back to the historic 2800x2000 cell', () => {
  assert.deepEqual(cellSizeFor([{}]), { w: 2800, h: 2000 })
  assert.deepEqual(cellSizeFor([]), { w: 2800, h: 2000 })
  assert.deepEqual(cellSizeFor([{ page_w: 0, page_h: 0 }]), { w: 2800, h: 2000 })
  assert.deepEqual(cellSizeFor([{ page_w: NaN, page_h: 10 }]), { w: 2800, h: 2000 })
})

// ── 12-15. provenance ───────────────────────────────────────────────────────

test('12. geometry-backed edge reports as geometry', () => {
  assert.equal(edgeTrust({ provenance: 'geometry' }), 'geometry')
})

test('13. LLM edge reports as llm, never as geometry', () => {
  assert.equal(edgeTrust({ provenance: 'llm' }), 'llm')
  assert.notEqual(edgeTrust({ provenance: 'llm' }), 'geometry')
})

test('14. unaudited outranks provenance so it cannot read as verified', () => {
  assert.equal(edgeTrust({ provenance: 'geometry', audited: false }), 'unaudited')
  assert.equal(edgeTrust({ audited: false }), 'unaudited')
  assert.equal(edgeTrust({ provenance: 'geometry', audited: true }), 'geometry')
})

test('15. an edge the backend rejected never reaches the canvas', () => {
  // The Phase 2 guard drops ungrounded LLM edges before persistence, so the
  // canvas renders the accepted graph. Anything it does receive is either
  // geometry, grounded llm, or explicitly unaudited — never "rejected".
  const accepted = [
    { provenance: 'geometry' as const },
    { provenance: 'llm' as const },
    { audited: false },
    {},
  ]
  const trusts = accepted.map(edgeTrust)
  assert.deepEqual(trusts, ['geometry', 'llm', 'unaudited', 'unknown'])
  assert.ok(!trusts.includes('rejected' as never))
})

// ── 16-19. identity safety ──────────────────────────────────────────────────

test('16. duplicate node ids are detected', () => {
  const r = checkGraphIntegrity(
    [{ id: 'n1' }, { id: 'n1' }, { id: 'n2' }], [])
  assert.equal(r.ok, false)
  assert.deepEqual(r.duplicateNodeIds, ['n1'])
  assert.ok(describeIntegrity(r).includes('duplicate node id'))
})

test('17. duplicate edge ids are detected, and makeEdgeId prevents them', () => {
  const r = checkGraphIntegrity([{ id: 'a' }, { id: 'b' }],
    [{ id: 'x', source: 'a', target: 'b' },
     { id: 'x', source: 'a', target: 'b' }])
  assert.equal(r.ok, false)
  assert.deepEqual(r.duplicateEdgeIds, ['x'])

  const seen = new Map<string, number>()
  const ids = [
    makeEdgeId('a', 'b', seen),
    makeEdgeId('a', 'b', seen),   // genuine parallel connection
    makeEdgeId('b', 'a', seen),   // opposite direction is a different edge
  ]
  assert.equal(new Set(ids).size, 3, `ids collided: ${ids.join(', ')}`)
})

test('18. an edge with a missing source is reported', () => {
  const r = checkGraphIntegrity([{ id: 'b' }],
    [{ id: 'e', source: 'ghost', target: 'b' }])
  assert.equal(r.ok, false)
  assert.deepEqual(r.danglingEdges[0].missing, ['ghost'])
})

test('19. an edge with a missing target is reported', () => {
  const r = checkGraphIntegrity([{ id: 'a' }],
    [{ id: 'e', source: 'a', target: 'ghost' }])
  assert.equal(r.ok, false)
  assert.deepEqual(r.danglingEdges[0].missing, ['ghost'])
})

test('19b. two source files sharing local ids are surfaced, not hidden', () => {
  // Backend identity issue tracked for Phase 5: two PDFs in one project both
  // emit n1/n2. The canvas must not render one and silently drop the other.
  const r = checkGraphIntegrity(
    [{ id: 'n1' }, { id: 'n2' }, { id: 'n1' }, { id: 'n2' }], [])
  assert.equal(r.ok, false)
  assert.deepEqual(r.duplicateNodeIds.sort(), ['n1', 'n2'])
})

test('19c. non-finite node positions are caught', () => {
  const r = checkGraphIntegrity(
    [{ id: 'a', position: { x: NaN, y: 0 } },
     { id: 'b', position: { x: 0, y: Infinity } },
     { id: 'c', position: { x: 1, y: 2 } }], [])
  assert.equal(r.ok, false)
  assert.deepEqual(r.invalidPositions.sort(), ['a', 'b'])
})

// ── 20. malformed waypoint data must never crash or corrupt ─────────────────

test('20. invalid waypoint data degrades safely to no route', () => {
  const bad: unknown[] = [
    null, undefined, 'not an array', 42, {},
    [],                                   // empty
    [[0.1, 0.1]],                         // one point
    [[0.1, 0.1], [0.9, 0.9]],             // endpoints only
    [[NaN, 0.1], [0.5, 0.5], [0.9, 0.9]],
    [[0.1, 0.1], [Infinity, 0.5], [0.9, 0.9]],
    [[0.1, 0.1], ['a', 'b'], [0.9, 0.9]],
    [[0.1, 0.1], [null, 0.5], [0.9, 0.9]],
    [[0.1, 0.1], [0.5], [0.9, 0.9]],      // ragged
    [[0.1, 0.1], [99, 99], [0.9, 0.9]],   // far outside the sheet
    [[0.1, 0.1], [-5, 0.5], [0.9, 0.9]],
  ]
  for (const w of bad) {
    const out = sanitizeWaypoints(w)
    assert.ok(Array.isArray(out), `must return an array for ${JSON.stringify(w)}`)
    assert.equal(out.length, 0, `must yield no route for ${JSON.stringify(w)}`)
    assert.equal(
      routeKindFor({ waypoints: w, bend_x: null, bend_y: null }, out, 'extracted'),
      'bendable', 'malformed data must fall back to the interactive router')
  }
})

test('20b. a small overshoot outside 0-1 is tolerated', () => {
  // _snap_start/_snap_end can seat an endpoint marginally off-sheet.
  const out = sanitizeWaypoints([[-0.01, 0.5], [0.5, 0.5], [1.02, 0.5]])
  assert.equal(out.length, 1)
})

// ── routing priority ────────────────────────────────────────────────────────

test('a user-dragged bend outranks the extracted route', () => {
  const interior = sanitizeWaypoints([[0.1, 0.5], [0.5, 0.5], [0.9, 0.5]])
  assert.equal(interior.length, 1)
  assert.equal(routeKindFor({ waypoints: [], bend_x: 0.5, bend_y: 0.6 },
    interior, 'extracted'), 'bendable')
})

test('extracted routes are not used under dagre/process layout', () => {
  const interior = sanitizeWaypoints([[0.1, 0.5], [0.5, 0.5], [0.9, 0.5]])
  assert.equal(routeKindFor({ waypoints: [], bend_x: null, bend_y: null },
    interior, 'dagre'), 'bendable')
  assert.equal(routeKindFor({ waypoints: [], bend_x: null, bend_y: null },
    interior, 'process'), 'bendable')
})

// ── coordinate chain (Step 6: verify, do not rewrite) ───────────────────────

test('normalised -> pixel -> normalised round-trips', () => {
  for (const [x, y] of [[0, 0], [0.25, 0.75], [0.5, 0.5], [1, 1]]) {
    const px = normalizedPointToPixel(x, y, 3000, 2200)
    const back = pixelPointToNormalized(px.x, px.y, 3000, 2200)
    assert.ok(Math.abs(back.x - x) < 1e-9, `x ${x} -> ${back.x}`)
    assert.ok(Math.abs(back.y - y) < 1e-9, `y ${y} -> ${back.y}`)
  }
})

test('waypoint pixels and node pixels share one transform', () => {
  // A route point at the same normalised position as a node centre must land
  // on that node centre — if these two ever diverged, pipes would float.
  const nodes = [node('a', 0.3, 0.4)]
  const { pos } = extractedLayout(nodes, size, 3000, 2200, [])
  const p = pos.get('a')!
  const centre = { x: p.x + 60 / 2, y: p.y + 40 / 2 }
  const wp = normalizedPointToPixel(0.3, 0.4, 3000, 2200)
  assert.ok(Math.abs(centre.x - wp.x) < 1e-6, `${centre.x} vs ${wp.x}`)
  assert.ok(Math.abs(centre.y - wp.y) < 1e-6, `${centre.y} vs ${wp.y}`)
})

test('node drag round-trips through pixelToNormalized', () => {
  const { pos } = extractedLayout([node('a', 0.62, 0.31)], size, 3000, 2200, [])
  const p = pos.get('a')!
  const back = pixelToNormalized(p.x, p.y, 60, 40, 3000, 2200)
  assert.ok(Math.abs(back.x - 0.62) < 1e-9)
  assert.ok(Math.abs(back.y - 0.31) < 1e-9)
})

test('margin is respected at the sheet edges', () => {
  const { pos } = extractedLayout([node('a', 0, 0)], size, 3000, 2200, [])
  const p = pos.get('a')!
  assert.equal(p.x + 60 / 2, EXTRACTED_MARGIN)
  assert.equal(p.y + 40 / 2, EXTRACTED_MARGIN)
})

// ── route clipping against the RENDERED symbol boxes ───────────────────────
// The canvas draws every symbol at a fixed node size and extractedLayout
// nudges nodes for alignment/collision, so a bend that cleared the real
// symbol on the sheet can land inside the rendered box. Measured on p-id-3:
// 57 of 145 target-side bends did exactly that, and drawing to them cut the
// pipe straight through the symbol.

const BOX = (x1: number, y1: number, x2: number, y2: number) => ({ x1, y1, x2, y2 })

test('21. a bend outside both symbols is kept and drives the handles', () => {
  const r = buildRoute([{ x: 300, y: 100 }], BOX(0, 80, 60, 120), BOX(280, 200, 340, 240))
  assert.ok(r, 'a clean bend must produce a route')
  assert.deepEqual(r!.pts, [{ x: 300, y: 100 }])
  assert.equal(r!.sourceHandle, 'sr', 'bend is to the right of the source')
  assert.equal(r!.targetHandle, 'tt', 'bend is above the target')
})

test('22. a bend swallowed by the target box is dropped', () => {
  const r = buildRoute([{ x: 300, y: 220 }], BOX(0, 200, 60, 240), BOX(280, 200, 340, 240))
  assert.equal(r, null, 'the only bend was inside the target -> no route')
})

test('23. a bend swallowed by the source box is dropped', () => {
  const r = buildRoute([{ x: 30, y: 220 }], BOX(0, 200, 60, 240), BOX(280, 200, 340, 240))
  assert.equal(r, null)
})

test('24. leading/trailing bends are clipped, the middle one survives', () => {
  const r = buildRoute(
    [{ x: 30, y: 220 }, { x: 170, y: 100 }, { x: 300, y: 220 }],
    BOX(0, 200, 60, 240), BOX(280, 200, 340, 240))
  assert.ok(r)
  assert.deepEqual(r!.pts, [{ x: 170, y: 100 }])
})

test('25. an unroutable elbow falls back rather than crossing a symbol', () => {
  // Both possible corners for the hop land inside the target box.
  const r = buildRoute(
    [{ x: 300, y: 100 }, { x: 500, y: 300 }],
    BOX(0, 80, 60, 120), BOX(280, 80, 520, 320))
  assert.equal(r, null, 'no honest orthogonal path -> interactive fallback')
})

test('26. handles follow the surviving geometry, not the node centres', () => {
  // Target sits to the RIGHT of the source, so a centre-based guess would say
  // sr/tl. The real route leaves DOWNWARD, and the handle must follow it.
  const r = buildRoute([{ x: 30, y: 400 }], BOX(0, 80, 60, 120), BOX(500, 380, 560, 420))
  assert.ok(r)
  assert.equal(r!.sourceHandle, 'sb', 'route leaves the bottom face')
  assert.equal(r!.targetHandle, 'tl', 'route arrives at the left face')
})

test('27. non-finite bends are dropped by buildRoute too', () => {
  const r = buildRoute(
    [{ x: NaN, y: 100 }, { x: 300, y: 100 }, { x: Infinity, y: 5 }],
    BOX(0, 80, 60, 120), BOX(280, 200, 340, 240))
  assert.ok(r)
  assert.deepEqual(r!.pts, [{ x: 300, y: 100 }])
})

test('28. empty input yields no route', () => {
  assert.equal(buildRoute([], BOX(0, 0, 10, 10), BOX(50, 50, 60, 60)), null)
})

test('29. a single bend between axis-aligned ports is a jog, not a corner', () => {
  // Both valves on one vertical centreline (extractedLayout's snapAlignGroups
  // forces exactly this), with one bend 30px to the side. Measured on real
  // drawings: 23 of 48 routed edges in p-id-3 had this shape, every one with
  // an off-axis endpoint distance of 0.0px. Drawing it produces a Z where the
  // sheet has a straight line.
  const src = BOX(100, 0, 160, 40)      // centre (130, 20)
  const tgt = BOX(100, 400, 160, 440)   // centre (130, 420)
  const r = buildRoute([{ x: 160, y: 200 }], src, tgt)
  assert.equal(r, null, 'jog must be dropped so the run draws straight')
})

test('29b. the same rule applies to a horizontal run', () => {
  const src = BOX(0, 100, 60, 140)      // centre (30, 120)
  const tgt = BOX(400, 100, 460, 140)   // centre (430, 120)
  const r = buildRoute([{ x: 200, y: 150 }], src, tgt)
  assert.equal(r, null)
})

test('29c. TWO bends on an aligned pair are kept — a real detour needs two', () => {
  const src = BOX(100, 0, 160, 40)
  const tgt = BOX(100, 400, 160, 440)
  const r = buildRoute([{ x: 220, y: 150 }, { x: 220, y: 300 }], src, tgt)
  assert.ok(r, 'an out-and-back detour is real geometry and must survive')
  assert.equal(r!.pts.length, 2)
})

test('29d. a single bend on a genuinely diagonal pair is kept', () => {
  // Endpoints are NOT aligned on either axis, so one corner is exactly what
  // an L-shaped pipe looks like.
  const src = BOX(0, 0, 60, 40)          // centre (30, 20)
  const tgt = BOX(400, 400, 460, 440)    // centre (430, 420)
  const r = buildRoute([{ x: 430, y: 20 }], src, tgt)
  assert.ok(r, 'a real L-bend must survive')
  assert.equal(r!.pts.length, 1)
})

test('30. a valve anchors on a PORT face, never on the actuator', () => {
  // Junction sits below-right of the valve, so a plain nearest-face rule
  // would pick the BOTTOM face. A valve has two process ports, left and
  // right; the top is the actuator stem. Anchoring there draws the pipe into
  // the actuator, which reads as a line stopping in mid-air by the symbol.
  // Measured before the fix: 8 of 15 valve ends in p-id-4 did this.
  const valve = BOX(1262, 721, 1316, 771)     // centre (1289, 746)
  const junction = BOX(1414, 998, 1430, 1014) // centre (1422, 1006)
  const r = buildRoute([{ x: 1421, y: 741 }], valve, junction,
    { srcHorizontal: true })
  assert.ok(r)
  assert.equal(r!.sourceHandle, 'sr', 'valve must use its right port')
  assert.notEqual(r!.sourceHandle[1], 't')
  assert.notEqual(r!.sourceHandle[1], 'b')
})

test('30b. the mirrored case uses the left port', () => {
  const valve = BOX(1061, 721, 1115, 771)     // centre (1088, 746)
  const junction = BOX(946, 993, 962, 1009)   // centre (954, 1001)
  const r = buildRoute([{ x: 963, y: 741 }], valve, junction,
    { srcHorizontal: true })
  assert.ok(r)
  assert.equal(r!.sourceHandle, 'sl')
})

test('30c. without the hint the nearest face still wins (non-valve symbols)', () => {
  const tank = BOX(1262, 721, 1316, 771)
  const junction = BOX(1414, 998, 1430, 1014)
  const r = buildRoute([{ x: 1289, y: 900 }], tank, junction)
  assert.ok(r)
  assert.equal(r!.sourceHandle, 'sb', 'a tank may take a pipe on its bottom')
})

test('31. a bend a few px off its anchor axis is squared onto it', () => {
  // Detector jitter leaves the bend 5px above the port. Left alone the
  // orthogonaliser inserts a corner for those 5px and draws a stair-step
  // where the pipe meets the valve.
  const valve = BOX(1262, 721, 1316, 771)     // right port at y=746
  const junction = BOX(1414, 998, 1430, 1014)
  const r = buildRoute([{ x: 1421, y: 741 }], valve, junction,
    { srcHorizontal: true })
  assert.ok(r)
  assert.equal(r!.pts[0].y, 746, 'bend squared onto the port axis')
})

test('31b. a bend well off the axis is NOT moved', () => {
  const valve = BOX(1262, 721, 1316, 771)     // right port at y=746
  const junction = BOX(1414, 998, 1430, 1014)
  const r = buildRoute([{ x: 1421, y: 700 }], valve, junction,
    { srcHorizontal: true })
  assert.ok(r)
  assert.equal(r!.pts[0].y, 700, '46px is a real bend, not jitter')
})

// ── corner style is one visual language across every router ────────────────

test('32. a polyline corner is ROUNDED, matching BendableEdge', () => {
  const d = roundedPolyline([{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }])
  assert.ok(d.includes('Q'), 'the elbow must be a quadratic, not a hard L')
  assert.ok(d.startsWith('M 0,0'))
  assert.ok(d.endsWith('L 100,100'))
})

test('32b. every elbow of a multi-bend route is rounded', () => {
  const d = roundedPolyline([
    { x: 0, y: 0 }, { x: 100, y: 0 }, { x: 100, y: 100 }, { x: 200, y: 100 },
  ])
  assert.equal((d.match(/Q/g) ?? []).length, 2, 'two corners -> two curves')
})

test('32c. a straight run has no corner at all', () => {
  const d = roundedPolyline([{ x: 0, y: 0 }, { x: 100, y: 0 }])
  assert.equal(d, 'M 0,0 L 100,0')
  assert.ok(!d.includes('Q'))
})

test('32d. coincident and non-finite points never produce NaN in the path', () => {
  for (const pts of [
    [{ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 50, y: 0 }],
    [{ x: 0, y: 0 }, { x: NaN, y: 5 }, { x: 50, y: 0 }],
    [{ x: 0, y: 0 }, { x: 25, y: Infinity }, { x: 50, y: 0 }],
  ]) {
    const d = roundedPolyline(pts)
    assert.ok(!d.includes('NaN'), `NaN leaked into: ${d}`)
    assert.ok(!d.includes('Infinity'), `Infinity leaked into: ${d}`)
  }
})

test('32e. fewer than two usable points yields an empty path, not a crash', () => {
  assert.equal(roundedPolyline([]), '')
  assert.equal(roundedPolyline([{ x: 1, y: 1 }]), '')
  assert.equal(roundedPolyline([{ x: NaN, y: 1 }, { x: 2, y: 2 }]), '')
})

test('32f. the corner radius never overshoots a short segment', () => {
  // A 4px run must not be given a 10px radius — that would bow the line past
  // its own endpoint.
  const d = roundedPolyline([{ x: 0, y: 0 }, { x: 4, y: 0 }, { x: 4, y: 400 }], 10)
  const nums = (d.match(/-?\d+(\.\d+)?/g) ?? []).map(Number)
  assert.ok(nums.every(n => Number.isFinite(n)))
  assert.ok(d.includes('Q 4,0'), 'corner still at the vertex')
})

console.log(`canvas.test.ts: ${passed} assertions passed`)
