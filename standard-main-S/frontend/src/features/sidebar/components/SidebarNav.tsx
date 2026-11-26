import type { ReactNode } from 'react'
import { Home, CheckSquare, Network, PenLine, FileDown, ShieldCheck, Upload } from 'lucide-react'
import type { Screen } from '../../../App'

const NAV: { id: Screen; label: string; icon: ReactNode }[] = [
  { id: 'home',     label: 'Home',      icon: <Home          size={20} /> },
  { id: 'ingest',   label: 'Upload',    icon: <Upload        size={20} /> },
  { id: 'review',   label: 'Review',    icon: <CheckSquare   size={20} /> },
  { id: 'canvas',   label: 'Canvas',    icon: <Network       size={20} /> },
  { id: 'describe', label: 'Describe',  icon: <PenLine       size={20} /> },
  { id: 'validation', label: 'Validation', icon: <ShieldCheck   size={20} /> },
  { id: 'export',     label: 'Export',     icon: <FileDown      size={20} /> },
]

export function SidebarNav({
  collapsed, setCollapsed, activeScreen, setActiveScreen,
}: {
  collapsed: boolean
  setCollapsed: (fn: (c: boolean) => boolean) => void
  activeScreen: Screen
  setActiveScreen: (s: Screen) => void
}) {
  return (
    <>
      {/* Docked at rest; click the logo to toggle docked/undocked. */}
      <div className="sidebar-logo" style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
        <button
          className="logo-toggle"
          onClick={() => setCollapsed(c => !c)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <img src="/logo.png" alt="enSTUDIO" className="logo-icon" style={{ height: 52, width: 'auto', objectFit: 'contain', flexShrink: 0, top: 4 }} />
        </button>
        {!collapsed && <span className="logo-text">enSTUDIO</span>}
      </div>

      {!collapsed && <div className="sidebar-section-label">Navigation</div>}
      <nav className="sidebar-nav">
        {NAV.map(item => (
          <button
            key={item.id}
            className={`nav-item${activeScreen === item.id ? ' active' : ''}`}
            onClick={() => setActiveScreen(item.id)}
            title={collapsed ? item.label : undefined}
          >
            <span className="nav-icon">{item.icon}</span>
            {!collapsed && item.label}
          </button>
        ))}
      </nav>
    </>
  )
}
