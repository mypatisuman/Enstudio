import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Rocket, Lightbulb, Info } from 'lucide-react'
import { ShortcutsSection } from '../features/shortcuts/ShortcutsSection'

const QUICK_START = [
  'Create a project — click “+ New” in the sidebar (or Create Project on the home screen).',
  'Upload a P&ID PDF on the Upload screen (drag & drop or browse).',
  'Run AI extraction — instruments & equipment are pulled from the drawing.',
  'Review the results — accept, reject, or edit each item.',
  'Explore & edit on the Canvas, then Export your deliverables.',
]

const TIPS: { label: string; text: string }[] = [
  { label: 'Search', text: 'Type a project name in the header search, then click it or press Enter to open.' },
  { label: 'Canvas', text: 'Drag node handles to reposition, or shift-click two symbols to connect them.' },
  { label: 'Review', text: 'Accept, reject, or edit each extracted instrument inline.' },
  { label: 'Describe', text: 'Chat with AI to add equipment, make connections, and edit the diagram.' },
  { label: 'Validation', text: 'Runs engineering rule checks — duplicate tags, disconnected equipment, low confidence, missing references — with a validation score.' },
  { label: 'Export', text: 'Generate SVG, VIDS YAML, YMPL, or a Markdown report from reviewed data.' },
]

/** In-app Help — quick start, tips/shortcuts, and about. */
export function HelpModal({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const r = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(r)
  }, [])
  const dismiss = () => { setOpen(false); setTimeout(onClose, 160) }

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
        borderRadius: 14, padding: '22px 22px 18px', width: 500, maxHeight: '86vh',
        display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>Help &amp; tips</div>
          <button className="modal-x" onClick={dismiss} aria-label="Close"><X size={17} /></button>
        </div>

        <div className="help-scroll">
          <section>
            <div className="help-h"><Rocket size={15} /> Quick start</div>
            <ol className="help-steps">
              {QUICK_START.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
          </section>

          <section>
            <div className="help-h"><Lightbulb size={15} /> Tips &amp; shortcuts</div>
            <ul className="help-list">
              {TIPS.map((t, i) => (
                <li key={i}><strong>{t.label}</strong> — {t.text}</li>
              ))}
            </ul>
          </section>

          <ShortcutsSection />

          <section>
            <div className="help-h"><Info size={15} /> About</div>
            <p className="help-about">
              enSTUDIO — an AI-powered P&amp;ID extraction and process-engineering toolkit.
              Turn scanned P&amp;IDs into structured, reviewable engineering data and export
              standard deliverables.
            </p>
          </section>
        </div>
      </div>
    </div>,
    document.body,
  )
}
