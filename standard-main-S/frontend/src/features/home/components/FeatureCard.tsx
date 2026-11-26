import type { ReactNode } from 'react'

export function FeatureCard({
  accent, IconComp, title, children, onOpen, screen,
}: {
  accent: string
  IconComp: React.FC<{ size?: number; strokeWidth?: number; color?: string }>
  title: string
  children: ReactNode
  onOpen: () => void
  screen: string
}) {
  return (
    <div className="feature-card">
      <div className="feature-card__bar" style={{ background: accent }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="feature-card__icon" style={{ background: accent + '22', borderColor: accent + '44' }}>
          <IconComp size={17} color={accent} strokeWidth={2} />
        </span>
        <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>{title}</span>
      </div>
      <div style={{ flex: 1 }}>{children}</div>
      <button
        className="feature-card__cta"
        onClick={onOpen}
        style={{ background: accent + '18', borderColor: accent + '55', color: accent }}
      >
        Open {screen} <span className="feature-card__arrow">→</span>
      </button>
    </div>
  )
}
