import { useState } from 'react'

// `kinds` lists every edge.kind that maps to this legend row. The extractor
// writes 'process' (97 of 98 edges on a real drawing) while the canvas falls
// back to 'stream' for an edge with no kind, so the main pipe arrives under
// either name — matching only 'stream' left the legend showing Signal alone
// while 97 process lines went unexplained.
const ALL_LINE_TYPES = [
  { kinds: ['process', 'stream'], name: 'Process (Main pipe)', stroke: '#ffffff', dash: '' },
  { kinds: ['signal'], name: 'Signal (Electrical)', stroke: '#1565C0', dash: '6 3' },
  { kinds: ['pneumatic'], name: 'Pneumatic', stroke: '#38bdf8', dash: '4 3' },
  { kinds: ['bypass'], name: 'Bypass', stroke: '#f59e0b', dash: '5 3' },
  { kinds: ['recycle'], name: 'Recycle', stroke: '#22c55e', dash: '5 3' },
  { kinds: ['hydraulic'], name: 'Hydraulic', stroke: '#a78bfa', dash: '5 2' },
  { kinds: ['utility'], name: 'Utility', stroke: '#0d9488', dash: '2 2' },
  { kinds: ['cross-drawing'], name: 'Cross-drawing', stroke: '#7c3aed', dash: '6 4' },
  { kinds: ['assoc'], name: 'Association', stroke: '#334155', dash: '3 2' }
]

export const LineLegend = ({ presentKinds }: {
  presentKinds: Set<string>
}) => {
  const [show, setShow] = useState(false)
  const visibleLines = ALL_LINE_TYPES.filter(l => l.kinds.some(k => presentKinds.has(k)))
  if (visibleLines.length === 0) return null

  return (
    <div style={{ position: 'relative', display: 'flex', alignItems: 'center', zIndex: 999 }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}>
      <button className="btn btn-ghost" style={{ fontSize: 11, padding: '3px 8px', fontWeight: 'bold', fontFamily: 'serif', cursor: 'default' }}>i</button>
      {show && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 8,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 6, padding: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          width: 220, display: 'flex', flexDirection: 'column', gap: 10
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 2 }}>P&ID Line Types</div>
          {visibleLines.map(l => (
            <div key={l.name} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <svg width="40" height="4" overflow="visible">
                <line x1="0" y1="2" x2="40" y2="2" stroke={l.stroke} strokeWidth="2" strokeDasharray={l.dash} />
              </svg>
              <span style={{ fontSize: 11, color: 'var(--text)' }}>{l.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
