import { ClipboardCheck, Network, FileDown, AlertTriangle, Upload, CheckCircle, FileText, Wand2 } from 'lucide-react'
import type { Project, Screen } from '../../../App'
import type { Source } from '../types'
import { FeatureCard } from './FeatureCard'
import { Pill } from './Pill'
import { ExportItem } from './ExportItem'

export function FeatureGrid({
  project, setActiveScreen,
  sourceCount, lastExtracted, sources,
  totalI, accepted, rejected, pending,
  edgeCount, nodeCount,
  orphans, lowConf, lonelyEquip,
  hasVids, hasYmpl, hasMd, hasMermaid,
}: {
  project: Project
  setActiveScreen: (s: Screen) => void
  sourceCount: number
  lastExtracted: string
  sources: Source[]
  totalI: number
  accepted: number
  rejected: number
  pending: number
  edgeCount: number
  nodeCount: number
  orphans: number
  lowConf: number
  lonelyEquip: number
  hasVids: boolean
  hasYmpl: boolean
  hasMd: boolean
  hasMermaid: boolean
}) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

      {/* Row 1 — Upload & Review */}
      <FeatureCard accent="#1E7BFF" IconComp={Upload} title="Ingest" screen="Ingest"
        onOpen={() => setActiveScreen('ingest')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Upload P&amp;ID PDFs for AI extraction
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Pill label="source documents" value={sourceCount} />
            {lastExtracted && <Pill label="last extracted" value={lastExtracted} />}
          </div>
          {sourceCount > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 2 }}>
              {sources.slice(0, 3).map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                  {s.cached
                    ? <CheckCircle size={11} color="var(--success)" strokeWidth={2.5} />
                    : <FileText size={11} color="var(--warning)" strokeWidth={1.8} />
                  }
                  <span style={{ color: 'var(--text-secondary)' }}>{s.filename ?? '—'}</span>
                </div>
              ))}
              {sourceCount > 3 && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>…and {sourceCount - 3} more</div>}
            </div>
          )}
        </div>
      </FeatureCard>

      <FeatureCard accent="#19D27A" IconComp={ClipboardCheck} title="Review" screen="Review"
        onOpen={() => setActiveScreen('review')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            {totalI} instruments across {project.drawings} drawing{project.drawings !== 1 ? 's' : ''}
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Pill label="accepted" value={accepted} color="#22c55e" />
            <Pill label="rejected" value={rejected} color="#ef4444" />
            <Pill label="pending" value={pending} color="#f59e0b" />
          </div>
        </div>
      </FeatureCard>

      {/* Row 2 — Canvas & Describe */}
      <FeatureCard accent="#4DA2FF" IconComp={Network} title="Canvas" screen="Canvas"
        onOpen={() => setActiveScreen('canvas')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Process topology: {edgeCount} connection{edgeCount !== 1 ? 's' : ''} extracted
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Pill label="nodes" value={nodeCount} />
            <Pill label="connections" value={edgeCount} />
          </div>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>ISA symbols · Orthogonal routing · Per-drawing filter</p>
        </div>
      </FeatureCard>

      <FeatureCard accent="#7EC2FF" IconComp={Wand2} title="Describe" screen="Describe"
        onOpen={() => setActiveScreen('describe')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            AI chat to add equipment, make connections, and edit the diagram
          </p>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>Natural language · Live graph edits · Context-aware</p>
        </div>
      </FeatureCard>

      {/* Row 3 — Validation & Export */}
      <FeatureCard accent="#F04E4E" IconComp={AlertTriangle} title="Validation" screen="Validation"
        onOpen={() => setActiveScreen('validation')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Engineering rule checks: duplicate tags, disconnected equipment, low confidence
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <Pill label="orphaned" value={orphans} color={orphans > 0 ? '#f59e0b' : undefined} />
            <Pill label="low confidence" value={lowConf} color={lowConf > 0 ? '#f59e0b' : undefined} />
            <Pill label="unlinked equip" value={lonelyEquip} color={lonelyEquip > 0 ? '#f59e0b' : undefined} />
          </div>
        </div>
      </FeatureCard>

      <FeatureCard accent="#1E7BFF" IconComp={FileDown} title="Export" screen="Export"
        onOpen={() => setActiveScreen('export')}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Generate deliverables from reviewed data
          </p>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gridTemplateRows: 'repeat(3, auto)',
            gridAutoFlow: 'column', columnGap: 12, rowGap: 4, marginTop: 4,
          }}>
            <ExportItem label="VIDS YAML" exists={hasVids} />
            <ExportItem label="YMPL" exists={hasYmpl} />
            <ExportItem label="Markdown report" exists={hasMd} />
            <ExportItem label="Mermaid" exists={hasMermaid} />
            {/* SVG/DXF are generated on demand; show them neutral like the rest
                instead of green just because a cached file lingers on disk. */}
            <ExportItem label="SVG" exists={false} />
            <ExportItem label="DXF" exists={false} />
          </div>
        </div>
      </FeatureCard>

    </div>
  )
}
