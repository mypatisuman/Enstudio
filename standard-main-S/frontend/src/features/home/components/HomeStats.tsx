import { StatCard } from '../../../shared/components/card/StatCard'
import { ProgressBar } from './ProgressBar'

export function HomeStats({
  totalI, accepted, rejected, pending, drawings,
  qualityPct, ratio, exportsReady,
  reviewPct, reviewColor, qualityColor,
}: {
  totalI: number
  accepted: number
  rejected: number
  pending: number
  drawings: number
  qualityPct: number
  ratio: number
  exportsReady: number
  reviewPct: number
  reviewColor: string
  qualityColor: string
}) {
  return (
    <>
      {/* ── KPI stat row ── */}
      <div className="stat-row">
        <StatCard label="Instruments" value={totalI} valueClass="accent"
          sub={`${drawings} drawing${drawings !== 1 ? 's' : ''}`} />
        <StatCard label="Review progress" value={`${reviewPct}%`}
          sub={`${accepted} accepted · ${rejected} rejected · ${pending} pending`}
          valueClass={reviewPct >= 80 ? 'success' : reviewPct >= 40 ? 'warning' : 'accent'} />
        <StatCard label="Extraction quality" value={`${qualityPct}%`}
          sub={`edge/node ratio ${ratio.toFixed(2)}`}
          valueClass={ratio >= 0.7 ? 'success' : ratio >= 0.35 ? 'warning' : undefined} />
        <StatCard label="Exports ready" value={`${exportsReady} / 6`} sub="VIDS · YMPL · Markdown · Mermaid · SVG · DXF"
          valueClass={exportsReady === 6 ? 'success' : exportsReady > 0 ? 'warning' : undefined} />
      </div>

      {/* ── Progress bars ── */}
      <div style={{
        background: 'var(--bg-glass)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md)', padding: '16px 20px',
        display: 'flex', flexDirection: 'column', gap: 12, boxShadow: 'var(--shadow-sm)',
      }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>Review progress</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: reviewColor }}>{accepted}/{totalI} ({reviewPct}%)</span>
          </div>
          <ProgressBar pct={reviewPct} color={reviewColor} />
        </div>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>Extraction quality (edge/node ratio)</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: qualityColor }}>{ratio.toFixed(2)} · {qualityPct}%</span>
          </div>
          <ProgressBar pct={qualityPct} color={qualityColor} />
        </div>
      </div>
    </>
  )
}
