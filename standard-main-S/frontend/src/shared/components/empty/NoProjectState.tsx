import type { ReactNode } from 'react'

// The "No project selected" placeholder — identical structural pattern
// (icon + h3 + p inside .no-project) repeated verbatim across Review,
// Ingest, Gaps, and Export screens; only icon/opacity/copy differ.
export function NoProjectState({
  icon, iconOpacity, title, body,
}: { icon: ReactNode; iconOpacity?: number; title: string; body: string }) {
  return (
    <div className="no-project">
      <div className="no-project-icon" style={iconOpacity != null ? { opacity: iconOpacity } : undefined}>
        {icon}
      </div>
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  )
}
