// Canvas-specific ISA classification — answers "is this conceptually an
// instrument (for soft-tag grouping / connection-kind inference)?" from a
// raw kind string. This is a DIFFERENT question from `getNodeType` in
// classification.ts (which maps kind+label to a specific render shape) and
// deliberately has a different kind/fragment list — do not merge the two.
//
// NOTE: CanvasScreen.tsx's dagre-layout computation (inside its `layoutResult`
// useMemo) has its OWN second, narrower instrument classifier that operates
// on a node-id -> kind lookup map built from React Flow's internal node
// list, with a kind/fragment set that is a subset of this one (e.g. it
// excludes "switch", "sensor", "totalizer"). That second copy exists
// on purpose for a local heuristic (splitting a junction's pipe-neighbours
// from its instrument-tap neighbours) and was confirmed to NOT be behavior-
// identical to this canonical version during Phase 6's audit — merging them
// would silently reclassify some nodes for that heuristic. Left separate
// and documented here rather than merged, per Phase 6's guidance.

const INSTR_KINDS = new Set([
  'transmitter', 'controller', 'indicator', 'recorder', 'switch', 'analyzer', 'element', 'instrument',
])
// Also matches YOLO compound type names like "Pressure_Indicator", "Temperature_Element".
// Kept in sync with the instrument-fragment list in ISANodes.getNodeType().
const INSTR_FRAGMENTS = ['indicator', 'element', 'controller', 'transmitter', 'meter', 'gauge',
  'sensor', 'recorder', 'analyzer', 'totalizer', 'indicating', 'differential', 'transducer',
  'thermocouple', 'relay', 'selector', 'interlock', 'sampling', 'detector', 'monitor']

export const isInstrument = (k: string) => {
  const lk = (k ?? '').toLowerCase()
  return INSTR_KINDS.has(lk) || INSTR_FRAGMENTS.some(f => lk.includes(f))
}

// Off-page detection: category/kind/type are authoritative; label regex is a last resort.
export const isOffPage = (kind: string, label = '', category = '') =>
  category.toLowerCase() === 'off_page' ||
  category.toLowerCase() === 'connector' ||
  /^off[_ ]?page/i.test(kind ?? '') ||
  /^(inlet|outlet)$/i.test(kind ?? '') ||
  /off.?page/i.test(label ?? '') ||
  /\bHEADER\b/i.test(label ?? '')
