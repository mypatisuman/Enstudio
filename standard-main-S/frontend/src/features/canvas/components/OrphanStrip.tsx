import { instrColors, equipColors } from '../../../components/canvas/ISANodes'
import { isInstrument } from '../../../domain/isa/instrument'
import type { GraphNode, CData } from '../types'

export function OrphanStrip({
  nodes, selected, onSelect,
}: { nodes: GraphNode[]; selected: CData | null; onSelect: (n: GraphNode) => void }) {
  if (!nodes.length) return null
  return (
    <div style={{
      flexShrink: 0, borderTop: '1px solid var(--border)',
      background: 'var(--bg-secondary)', padding: '7px 14px 9px',
    }}>
      <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginRight: 8 }}>
        Unlinked · {nodes.length}
      </span>
      {nodes.map(n => {
        const instr = isInstrument(n.type ?? n.kind)
        const color = instr ? instrColors(n.label).border : equipColors(n.type ?? n.kind).border
        const isSel = selected?.label === n.label
        return (
          <button key={n.id}
            onClick={() => onSelect(n)}
            title={`${n.kind}${n.area ? ' · ' + n.area : ''}`}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              margin: '2px 3px', padding: '2px 8px', borderRadius: 99,
              border: `1px solid ${isSel ? color : color + '44'}`,
              background: isSel ? color + '22' : 'var(--bg-tertiary)',
              color: 'var(--text-secondary)', fontSize: 10, fontWeight: 600,
              cursor: 'pointer',
            }}>
            <span style={{ width: 6, height: 6, borderRadius: instr ? '50%' : 2, background: color, flexShrink: 0 }} />
            {n.label}
          </button>
        )
      })}
    </div>
  )
}
