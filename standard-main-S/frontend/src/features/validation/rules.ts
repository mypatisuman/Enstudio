import type { GraphNode, ValidationRule, ValidationIssue } from './types'
import { confidenceInfo } from '../review/confidence'

// ── Node classification ───────────────────────────────────────────────────
// The graph mixes real symbols (equipment, instruments) with structural helper
// nodes (junctions/tees/manifolds) that are legitimately unlabelled and don't
// need their own connection accounting. Rules use these to avoid false flags.
const JUNCTION_KINDS = new Set(['junction', 'tee', 'manifold'])
const isJunction = (n: GraphNode) => n.category === 'junction' || JUNCTION_KINDS.has(n.kind)
const isEquipment = (n: GraphNode) => n.category === 'equipment'
const isInstrument = (n: GraphNode) => n.category === 'instrument'
const hasTag = (n: GraphNode) => n.label.trim().length > 0

// Group nodes by their (non-empty) label. Shared by the two duplicate rules.
function labelGroups(nodes: GraphNode[], keep: (n: GraphNode) => boolean): Map<string, GraphNode[]> {
  const m = new Map<string, GraphNode[]>()
  for (const n of nodes) {
    if (!hasTag(n) || !keep(n)) continue
    const arr = m.get(n.label) ?? []
    arr.push(n)
    m.set(n.label, arr)
  }
  return m
}

// Each rule below only reads already-extracted data — no invented engineering
// logic. Severity is fixed per rule (all its issues share it).
export const RULES: ValidationRule[] = [
  {
    id: 'duplicate-tags',
    label: 'Duplicate tags',
    severity: 'critical',
    execute(ctx): ValidationIssue[] {
      const out: ValidationIssue[] = []
      for (const [label, group] of labelGroups(ctx.nodes, isInstrument)) {
        if (group.length < 2) continue
        out.push({
          id: `duplicate-tags:${label}`, ruleId: 'duplicate-tags', severity: 'critical', category: 'instrument',
          tag: label, drawing: group[0].drawing || undefined,
          title: `Duplicate instrument tag "${label}"`,
          description: `${group.length} instruments share the tag "${label}". Tags must be unique.`,
          suggestion: 'Rename or merge the duplicates so each instrument has a unique tag.',
        })
      }
      return out
    },
  },
  {
    id: 'duplicate-equipment-ids',
    label: 'Duplicate equipment IDs',
    severity: 'critical',
    execute(ctx): ValidationIssue[] {
      const out: ValidationIssue[] = []
      for (const [label, group] of labelGroups(ctx.nodes, isEquipment)) {
        if (group.length < 2) continue
        out.push({
          id: `duplicate-equipment-ids:${label}`, ruleId: 'duplicate-equipment-ids', severity: 'critical', category: 'equipment',
          tag: label, drawing: group[0].drawing || undefined,
          title: `Duplicate equipment ID "${label}"`,
          description: `${group.length} equipment items share the ID "${label}".`,
          suggestion: 'Give each equipment item a unique identifier.',
        })
      }
      return out
    },
  },
  {
    id: 'missing-tags',
    label: 'Missing tags',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      // Equipment/instrument symbols with no label. Junctions are excluded —
      // they are unlabelled by design. No `tag` → no Jump (nothing to focus by).
      return ctx.nodes
        .filter(n => !hasTag(n) && (isEquipment(n) || isInstrument(n)))
        .map(n => ({
          id: `missing-tags:${n.id}`, ruleId: 'missing-tags', severity: 'warning' as const,
          category: isEquipment(n) ? 'equipment' as const : 'instrument' as const,
          drawing: n.drawing || undefined,
          title: `Untagged ${n.category || 'symbol'}`,
          description: `A ${n.category || 'symbol'} (${n.kind_detail || n.kind || 'unknown type'}) has no tag.`,
          suggestion: 'Assign a tag in Review so the item can be identified and referenced.',
        }))
    },
  },
  {
    id: 'disconnected-equipment',
    label: 'Disconnected equipment',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      return ctx.nodes
        .filter(n => isEquipment(n) && hasTag(n) && !ctx.connectedIds.has(n.id))
        .map(n => ({
          id: `disconnected-equipment:${n.id}`, ruleId: 'disconnected-equipment', severity: 'warning' as const,
          category: 'equipment' as const, tag: n.label, drawing: n.drawing || undefined,
          title: `Equipment "${n.label}" is not connected`,
          description: `"${n.label}" has no pipe or signal connections on the diagram.`,
          suggestion: 'Verify the equipment should be isolated, or add its missing connections on the Canvas.',
        }))
    },
  },
  {
    id: 'disconnected-instruments',
    label: 'Disconnected instruments',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      return ctx.nodes
        .filter(n => isInstrument(n) && hasTag(n) && !ctx.connectedIds.has(n.id))
        .map(n => ({
          id: `disconnected-instruments:${n.id}`, ruleId: 'disconnected-instruments', severity: 'warning' as const,
          category: 'instrument' as const, tag: n.label, drawing: n.drawing || undefined,
          title: `Instrument "${n.label}" is not connected`,
          description: `"${n.label}" has no signal or process connections on the diagram.`,
          suggestion: 'Check whether the instrument is missing its connection to the process or a controller.',
        }))
    },
  },
  {
    id: 'floating-symbols',
    label: 'Floating symbols',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      // Non-equipment/-instrument symbols (valves, off-page connectors, …) with
      // no edges. Equipment/instruments are covered by the disconnected rules;
      // junctions are structural and excluded.
      return ctx.nodes
        .filter(n => !isEquipment(n) && !isInstrument(n) && !isJunction(n) && !ctx.connectedIds.has(n.id))
        .map(n => ({
          id: `floating-symbols:${n.id}`, ruleId: 'floating-symbols', severity: 'warning' as const,
          category: 'symbol' as const, tag: hasTag(n) ? n.label : undefined, drawing: n.drawing || undefined,
          title: `Floating ${n.kind_detail || n.kind || 'symbol'}${hasTag(n) ? ` "${n.label}"` : ''}`,
          description: `A ${n.kind || 'symbol'} is placed on the diagram with no connections.`,
          suggestion: 'Connect the symbol to the flow, or remove it if it was detected in error.',
        }))
    },
  },
  {
    id: 'missing-connections',
    label: 'Missing connections',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      // Instruments with no recorded equipment reference — a data-level missing
      // link (distinct from disconnected, which is about drawn edges).
      const drawingByTag = new Map(ctx.nodes.map(n => [n.label, n.drawing]))
      return ctx.instruments
        .filter(i => !i.equipment_ref || !i.equipment_ref.trim())
        .map(i => ({
          id: `missing-connections:${i.tag}`, ruleId: 'missing-connections', severity: 'warning' as const,
          category: 'instrument' as const, tag: i.tag, drawing: drawingByTag.get(i.tag) || i.drawing || undefined,
          title: `Instrument "${i.tag}" has no equipment reference`,
          description: `"${i.tag}" is not linked to any equipment (empty equipment reference).`,
          suggestion: 'Set the equipment reference in Review to record what this instrument monitors.',
        }))
    },
  },
  {
    id: 'duplicate-connections',
    label: 'Duplicate connections',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      const seen = new Map<string, number>()
      for (const e of ctx.edges) {
        const key = `${e.source}->${e.target}`
        seen.set(key, (seen.get(key) ?? 0) + 1)
      }
      const out: ValidationIssue[] = []
      for (const [key, count] of seen) {
        if (count < 2) continue
        const [source, target] = key.split('->')
        const srcLabel = ctx.nodeById.get(source)?.label
        const tgtLabel = ctx.nodeById.get(target)?.label
        out.push({
          id: `duplicate-connections:${key}`, ruleId: 'duplicate-connections', severity: 'warning', category: 'connection',
          tag: srcLabel || undefined,
          title: `Duplicate connection${srcLabel && tgtLabel ? ` ${srcLabel} → ${tgtLabel}` : ''}`,
          description: `The same connection is present ${count} times.`,
          suggestion: 'Remove the redundant connection so the topology is not double-counted.',
        })
      }
      return out
    },
  },
  {
    id: 'orphan-pipes',
    label: 'Orphan pipes',
    severity: 'critical',
    execute(ctx): ValidationIssue[] {
      // Edges whose endpoint id does not resolve to any node — a broken pipe.
      return ctx.edges
        .filter(e => !ctx.nodeById.has(e.source) || !ctx.nodeById.has(e.target))
        .map(e => {
          const missing = !ctx.nodeById.has(e.source) ? e.source : e.target
          const known = ctx.nodeById.get(e.source)?.label ?? ctx.nodeById.get(e.target)?.label
          return {
            id: `orphan-pipes:${e.source}->${e.target}`, ruleId: 'orphan-pipes', severity: 'critical' as const,
            category: 'connection' as const, tag: known || undefined,
            title: 'Pipe with a missing endpoint',
            description: `A ${e.kind || 'connection'} references node "${missing}", which does not exist.`,
            suggestion: 'Reconnect the pipe to a valid symbol or delete the dangling connection.',
          }
        })
    },
  },
  {
    id: 'low-confidence',
    label: 'Low confidence',
    severity: 'info',
    execute(ctx): ValidationIssue[] {
      const drawingByTag = new Map(ctx.nodes.map(n => [n.label, n.drawing]))
      return ctx.instruments
        .filter(i => i.confidence > 0 && confidenceInfo(i.confidence).pct < 70)
        .map(i => ({
          id: `low-confidence:${i.tag}`, ruleId: 'low-confidence', severity: 'info' as const,
          category: 'instrument' as const, tag: i.tag, drawing: drawingByTag.get(i.tag) || i.drawing || undefined,
          title: `Low confidence on "${i.tag}" (${confidenceInfo(i.confidence).pct}%)`,
          description: `The extractor is only ${confidenceInfo(i.confidence).pct}% confident about "${i.tag}".`,
          suggestion: 'Confirm or correct this instrument in Review.',
        }))
    },
  },
  {
    id: 'missing-drawing',
    label: 'Missing drawings',
    severity: 'info',
    execute(ctx): ValidationIssue[] {
      // Ported from the former Data Gaps screen's "Missing drawings" tab — the
      // one check that wasn't already covered by another rule here.
      return ctx.instruments
        .filter(i => !i.drawing || !i.drawing.trim())
        .map(i => ({
          id: `missing-drawing:${i.tag}`, ruleId: 'missing-drawing', severity: 'info' as const,
          category: 'instrument' as const, tag: i.tag,
          title: `Instrument "${i.tag}" has no drawing`,
          description: `"${i.tag}" isn't attributed to any drawing.`,
          suggestion: 'Set the drawing in Review so this instrument can be traced to its source sheet.',
        }))
    },
  },
]
