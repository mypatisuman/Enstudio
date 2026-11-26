import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Upload, Network, CheckSquare, LayoutGrid, PenLine, ShieldCheck, FileDown, ArrowDown, X } from 'lucide-react'

const ALL_STEPS: { title: string; sub: string; icon: ReactNode }[] = [
  { title: 'Create project',      sub: 'Click "+ New" to start a new project on the Describe screen.',            icon: <Plus size={17} /> },
  { title: 'Upload P&ID',         sub: 'Go to Upload and drop a PDF (or build from scratch in Describe).',        icon: <Upload size={17} /> },
  { title: 'Run AI extraction',   sub: 'AI extracts instruments & equipment from the drawing.',                  icon: <Network size={17} /> },
  { title: 'Review data',         sub: 'Accept, reject, or edit each extracted instrument.',                     icon: <CheckSquare size={17} /> },
  { title: 'Explore the Canvas',  sub: 'ISA-5.1 diagram — drag handles or shift-click two symbols to connect.',  icon: <LayoutGrid size={17} /> },
  { title: 'Describe with AI',    sub: 'Chat to add equipment, make connections, and edit the diagram.',         icon: <PenLine size={17} /> },
  { title: 'Check Validation',    sub: 'Review engineering rule checks and the validation score.',               icon: <ShieldCheck size={17} /> },
  { title: 'Export deliverables', sub: 'Generate SVG, VIDS YAML, YMPL, or a Markdown report.',                   icon: <FileDown size={17} /> },
]

/** Popup listing every onboarding step as a card, top-to-bottom with down arrows. */
export function StepsModal({ onCancel }: { onCancel: () => void }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const dismiss = () => { setOpen(false); setTimeout(onCancel, 160) }

  return createPortal(
    <div
      className={`modal-backdrop${open ? ' open' : ''}`}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.65)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
      }}
      onClick={e => { if (e.target === e.currentTarget) dismiss() }}
    >
      <div className="modal-dialog" style={{
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 14, padding: '22px 22px 18px', width: 480, maxHeight: '84vh',
        display: 'flex', flexDirection: 'column', gap: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>Workflow — all steps</div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <div className="steps-scroll">
          {ALL_STEPS.map((s, i) => (
            <div key={i}>
              <div className="step-card">
                <span className="step-card__icon">{s.icon}</span>
                <div className="step-card__text">
                  <div className="step-card__label">{s.title}</div>
                  <div className="step-card__sub">{s.sub}</div>
                </div>
              </div>
              {i < ALL_STEPS.length - 1 && <div className="step-arrow"><ArrowDown size={16} /></div>}
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  )
}
