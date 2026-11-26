import type { GraphNode, ValidationRule, ValidationIssue } from './types';
import { confidenceInfo } from '../review/confidence';

const JUNCTION_KINDS = new Set(['junction', 'tee', 'manifold']);
const isJunction = (n: GraphNode) => n.category === 'junction' || JUNCTION_KINDS.has(n.kind);
const isEquipment = (n: GraphNode) => n.category === 'equipment' || (!isJunction(n) && !n.kind.includes('trans') && !n.kind.includes('indicator') && !n.kind.includes('sensor'));
const isInstrument = (n: GraphNode) => n.category === 'instrument' || n.kind.includes('trans') || n.kind.includes('indicator') || n.kind.includes('sensor') || n.kind.includes('ctrl') || n.kind.includes('valve');
const hasTag = (n: GraphNode) => (n.label || '').trim().length > 0;

function labelGroups(nodes: GraphNode[], keep: (n: GraphNode) => boolean): Map<string, GraphNode[]> {
  const m = new Map<string, GraphNode[]>();
  for (const n of nodes) {
    if (!hasTag(n) || !keep(n)) continue;
    const arr = m.get(n.label) ?? [];
    arr.push(n);
    m.set(n.label, arr);
  }
  return m;
}

export const RULES: ValidationRule[] = [
  {
    id: 'duplicate-tags',
    label: 'Duplicate tags',
    severity: 'critical',
    execute(ctx): ValidationIssue[] {
      const out: ValidationIssue[] = [];
      for (const [label, group] of labelGroups(ctx.nodes, isInstrument)) {
        if (group.length < 2) continue;
        out.push({
          id: `duplicate-tags:${label}`,
          ruleId: 'duplicate-tags',
          severity: 'critical',
          category: 'instrument',
          tag: label,
          drawing: group[0].drawing || undefined,
          title: `Duplicate instrument tag "${label}"`,
          description: `${group.length} instruments share the tag "${label}". Tags must be unique per ISA-5.1 standards.`,
          suggestion: 'Rename or merge the duplicates so each instrument has a unique loop identifier.',
        });
      }
      return out;
    },
  },
  {
    id: 'duplicate-equipment-ids',
    label: 'Duplicate equipment IDs',
    severity: 'critical',
    execute(ctx): ValidationIssue[] {
      const out: ValidationIssue[] = [];
      for (const [label, group] of labelGroups(ctx.nodes, isEquipment)) {
        if (group.length < 2) continue;
        out.push({
          id: `duplicate-equipment-ids:${label}`,
          ruleId: 'duplicate-equipment-ids',
          severity: 'critical',
          category: 'equipment',
          tag: label,
          drawing: group[0].drawing || undefined,
          title: `Duplicate equipment ID "${label}"`,
          description: `${group.length} equipment items share the ID "${label}".`,
          suggestion: 'Give each equipment item a unique identifier (e.g., P-101A and P-101B).',
        });
      }
      return out;
    },
  },
  {
    id: 'missing-tags',
    label: 'Missing tags',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      return ctx.nodes
        .filter(n => !hasTag(n) && !isJunction(n))
        .map(n => ({
          id: `missing-tags:${n.id}`,
          ruleId: 'missing-tags',
          severity: 'warning' as const,
          category: 'equipment' as const,
          drawing: n.drawing || undefined,
          title: `Untagged ${n.category || 'symbol'}`,
          description: `A ${n.category || 'symbol'} (${n.kind_detail || n.kind || 'unknown type'}) has no tag assigned.`,
          suggestion: 'Assign a tag in Review or on the Canvas so the item can be identified in schedules and BOM.',
        }));
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
          id: `disconnected-equipment:${n.id}`,
          ruleId: 'disconnected-equipment',
          severity: 'warning' as const,
          category: 'equipment' as const,
          tag: n.label,
          drawing: n.drawing || undefined,
          title: `Equipment "${n.label}" is not connected`,
          description: `"${n.label}" has no pipe or process stream connections on the diagram.`,
          suggestion: 'Verify if the equipment is an isolated spare, or route process lines to its nozzles on the Canvas.',
        }));
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
          id: `disconnected-instruments:${n.id}`,
          ruleId: 'disconnected-instruments',
          severity: 'warning' as const,
          category: 'instrument' as const,
          tag: n.label,
          drawing: n.drawing || undefined,
          title: `Instrument "${n.label}" is not connected`,
          description: `"${n.label}" has no signal, impulse, or electrical connections on the diagram.`,
          suggestion: 'Connect the instrument to its sensing point, transmitter loop, or DCS block.',
        }));
    },
  },
  {
    id: 'missing-connections',
    label: 'Missing equipment reference',
    severity: 'warning',
    execute(ctx): ValidationIssue[] {
      const drawingByTag = new Map(ctx.nodes.map(n => [n.label, n.drawing]));
      return ctx.instruments
        .filter(i => !i.equipment_ref || !i.equipment_ref.trim())
        .map(i => ({
          id: `missing-connections:${i.tag}`,
          ruleId: 'missing-connections',
          severity: 'warning' as const,
          category: 'instrument' as const,
          tag: i.tag,
          drawing: drawingByTag.get(i.tag) || i.drawing || undefined,
          title: `Instrument "${i.tag}" has no equipment reference`,
          description: `"${i.tag}" is not bound to a parent vessel, pipe, or pump.`,
          suggestion: 'Specify the parent equipment reference in Review to clarify what equipment this loop serves.',
        }));
    },
  },
  {
    id: 'orphan-pipes',
    label: 'Orphan pipes',
    severity: 'critical',
    execute(ctx): ValidationIssue[] {
      return ctx.edges
        .filter(e => !ctx.nodeById.has(e.source) || !ctx.nodeById.has(e.target))
        .map(e => {
          const missing = !ctx.nodeById.has(e.source) ? e.source : e.target;
          const known = ctx.nodeById.get(e.source)?.label ?? ctx.nodeById.get(e.target)?.label;
          return {
            id: `orphan-pipes:${e.source}->${e.target}`,
            ruleId: 'orphan-pipes',
            severity: 'critical' as const,
            category: 'connection' as const,
            tag: known || undefined,
            title: 'Pipe stream with missing termination',
            description: `A ${e.kind || 'stream'} references node "${missing}", which is not present in the graph.`,
            suggestion: 'Attach the stream to a valid symbol or delete the dangling connection on the Canvas.',
          };
        });
    },
  },
  {
    id: 'low-confidence',
    label: 'Low extraction confidence',
    severity: 'info',
    execute(ctx): ValidationIssue[] {
      const drawingByTag = new Map(ctx.nodes.map(n => [n.label, n.drawing]));
      return ctx.instruments
        .filter(i => i.confidence > 0 && confidenceInfo(i.confidence).pct < 70)
        .map(i => ({
          id: `low-confidence:${i.tag}`,
          ruleId: 'low-confidence',
          severity: 'info' as const,
          category: 'instrument' as const,
          tag: i.tag,
          drawing: drawingByTag.get(i.tag) || i.drawing || undefined,
          title: `Low confidence detection on "${i.tag}" (${confidenceInfo(i.confidence).pct}%)`,
          description: `The vision extractor scored "${i.tag}" with ${confidenceInfo(i.confidence).pct}% confidence.`,
          suggestion: 'Review the bounding box and text in the Review screen to confirm or correct.',
        }));
    },
  },
];
