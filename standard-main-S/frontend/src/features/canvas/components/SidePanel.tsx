import { instrColors, equipColors } from '../../../components/canvas/ISANodes'
import { isInstrument } from '../../../domain/isa/instrument'
import { NodeHierarchyField } from '../../hierarchy/NodeHierarchyField'
import type { CData } from '../types'

function Field({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ color: color ?? 'var(--text-secondary)', fontWeight: color ? 600 : 400, fontSize: 12 }}>
        {value}
      </div>
    </div>
  )
}

export function SidePanel({ node, projectId, open, onClose, onEdit }: { node: CData; projectId?: string; open: boolean; onClose: () => void; onEdit: () => void }) {
  const instr = isInstrument(String(node.kind))
  const color = instr ? instrColors(String(node.label)).border : equipColors(String(node.kind)).border
  const soft = node.softChildren ?? []
  return (
    <div className={`side-panel${open ? ' open' : ''}`} style={{ width: 260, flexShrink: 0, borderLeft: '1px solid var(--border)', background: 'var(--bg-secondary)', padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: instr ? '50%' : 2, border: `2px solid ${color}`, flexShrink: 0, display: 'inline-block' }} />
        <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)', flex: 1 }}>{String(node.label)}</span>
        <button onClick={onEdit} style={{ background: 'none', border: 'none', color: '#60a5fa', cursor: 'pointer', fontSize: 12, fontWeight: 600, padding: 2 }}>Edit</button>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 16, padding: 2 }}>×</button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Field label="Category" value={instr ? 'Instrument' : 'Equipment'} color={color} />
        {(node.type || node.kind) && <Field label="Type" value={String(node.type || node.kind).replace(/_/g, ' ')} />}
        {node.kind_detail && node.kind_detail !== node.kind && <Field label="Detail" value={String(node.kind_detail).replace(/_/g, ' ')} />}
        {node.equipment_ref && <Field label="Equip ref" value={String(node.equipment_ref)} />}
        {node.drawing && <Field label="Drawing" value={String(node.drawing)} />}
        {projectId && node.nodeId != null && (
          <NodeHierarchyField key={String(node.nodeId)} projectId={projectId} nodeId={String(node.nodeId)} />
        )}
        {soft.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 6 }}>
              Alarm / switch tags ({soft.length})
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {soft.map(c => {
                const cc = instrColors(c.label)
                return (
                  <span key={c.id} title={c.kind} style={{
                    display: 'inline-flex', alignItems: 'center', gap: 3,
                    padding: '2px 7px', borderRadius: 99, fontSize: 10,
                    border: `1px solid ${cc.border}44`, background: cc.bg, color: cc.text,
                  }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: cc.border, flexShrink: 0 }} />
                    {c.label}
                  </span>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
