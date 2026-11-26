import { confidenceInfo } from './confidence'

/**
 * Confidence pill + hover tooltip. Tooltip shows only data that actually
 * exists on the instrument DTO (exact %, tier, type, drawing) — the model has
 * no AI-provider / extraction-source fields, so those are intentionally not
 * shown rather than fabricated.
 */
export function ConfidenceBadge({ confidence, type, drawing }: {
  confidence: number
  type?: string
  drawing?: string
}) {
  const info = confidenceInfo(confidence)
  if (info.tier === 'none') return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const tip = [
    `Confidence: ${info.pct}% (${info.label})`,
    type ? `Type: ${type}` : '',
    drawing ? `Drawing: ${drawing}` : '',
  ].filter(Boolean).join('\n')
  return (
    <span className={`conf-badge conf-badge--${info.tier}`} title={tip}>
      <span className="conf-badge__dot" />
      {info.pct}%
    </span>
  )
}
