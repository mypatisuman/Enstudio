import type { ReactNode } from 'react'
import { StatCard } from '../../../shared/components/card/StatCard'

export function ReviewStats({
  instrumentCount, equipmentCount, accepted, rejected, pending, avgConf, showingCount,
  highConf, medConf, lowConf, completionPct, hasConfidence,
}: {
  instrumentCount: number
  equipmentCount: number
  accepted: number
  rejected: number
  pending: number
  avgConf: number
  showingCount: number
  highConf: number
  medConf: number
  lowConf: number
  completionPct: number
  hasConfidence: boolean
}): ReactNode {
  const reviewed = accepted + rejected
  const seg = (n: number) => (instrumentCount > 0 ? (n / instrumentCount) * 100 : 0)
  return (
    <>
      <div className="stat-row">
        <StatCard label="Instruments" value={instrumentCount} valueClass="accent" sub={<>
          <span style={{ color: 'var(--success)' }}>{accepted} accepted</span>
          {' · '}
          <span style={{ color: 'var(--danger)' }}>{rejected} rejected</span>
          {' · '}
          <span>{pending} pending</span>
        </>} />
        <StatCard label="Equipment" value={equipmentCount} sub="process items" />
        {hasConfidence && (
          <StatCard
            label="Confidence"
            value={avgConf > 0 ? `${avgConf}%` : '—'}
            valueClass={avgConf >= 85 ? 'success' : avgConf >= 70 ? 'warning' : 'danger'}
            sub={<>
              <span style={{ color: '#22c55e' }}>{highConf} high</span>
              {' · '}
              <span style={{ color: '#eab308' }}>{medConf} med</span>
              {' · '}
              <span style={{ color: '#ef4444' }}>{lowConf} low</span>
            </>}
          />
        )}
        <StatCard
          label="Completion"
          value={`${completionPct}%`}
          valueClass={completionPct >= 100 ? 'success' : completionPct >= 50 ? 'warning' : undefined}
          sub={`${reviewed} of ${instrumentCount} reviewed`}
        />
      </div>

      {/* Review progress bar — accepted / rejected / pending proportions */}
      <div className="rv-progress" title={`${accepted} accepted · ${rejected} rejected · ${pending} pending`}>
        <div className="rv-progress__seg rv-progress__seg--accepted" style={{ width: `${seg(accepted)}%` }} />
        <div className="rv-progress__seg rv-progress__seg--rejected" style={{ width: `${seg(rejected)}%` }} />
        <div className="rv-progress__seg rv-progress__seg--pending" style={{ width: `${seg(pending)}%` }} />
      </div>
      <div className="rv-progress__legend">
        <span><i className="rv-dot rv-dot--accepted" /> Accepted {Math.round(seg(accepted))}%</span>
        <span><i className="rv-dot rv-dot--rejected" /> Rejected {Math.round(seg(rejected))}%</span>
        <span><i className="rv-dot rv-dot--pending" /> Pending {Math.round(seg(pending))}%</span>
        <span className="rv-progress__showing">Showing {showingCount} of {instrumentCount}</span>
      </div>
    </>
  )
}
