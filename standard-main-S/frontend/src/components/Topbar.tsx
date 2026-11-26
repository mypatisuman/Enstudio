import { useState, useContext, useEffect, useRef } from 'react'
import { listen } from '@tauri-apps/api/event'
import { Search, Bell, Settings, HelpCircle, BarChart2, LogOut, Loader2, AlertTriangle, X } from 'lucide-react'
import type { Project, Screen } from '../App'
import { useAuth } from '../state/useAuth'
import { Ctx } from '../state/useExtraction'
import { listProjects } from '../services/project'
import { storedUserId } from '../services/authApi'
import { HelpModal } from './HelpModal'
import { SettingsModal } from './SettingsModal'
import { EditProfileModal } from './EditProfileModal'
import { UsageModal } from './UsageModal'

const SCREEN_META: Record<Screen, { label: string; stepLabel: string; cta?: { label: string; next: Screen } }> = {
  home:     { label: 'Overview',        stepLabel: 'Overview' },
  ingest:   { label: 'Upload',          stepLabel: 'Upload',   cta: { label: 'Review →', next: 'review' } },
  review:   { label: 'Review',          stepLabel: 'Review',   cta: { label: 'Canvas →', next: 'canvas' } },
  canvas:   { label: 'Canvas',          stepLabel: 'Canvas',   cta: { label: 'Export →', next: 'export' } },
  describe: { label: 'Describe',        stepLabel: 'Describe' },
  validation: { label: 'Validation',    stepLabel: 'Validation', cta: { label: 'Export →', next: 'export' } },
  export:   { label: 'Export',          stepLabel: 'Export' },
}

interface Props {
  activeProject:    Project | null
  activeScreen:     Screen
  setActiveProject: (p: Project | null) => void
}

export default function Topbar({ activeProject, activeScreen, setActiveProject }: Props) {
  const meta = SCREEN_META[activeScreen]
  const { user, logout } = useAuth()
  const ctx = useContext(Ctx)
  const byProject = ctx?.byProject ?? {}
  const [notifOpen, setNotifOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [profileEditOpen, setProfileEditOpen] = useState(false)
  const [usageOpen, setUsageOpen] = useState(false)

  // ── Search ──────────────────────────────────────────────────────────────────
  const [projects, setProjects] = useState<Project[]>([])
  const [query, setQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let alive = true
    const load = () => listProjects(storedUserId()).then(r => { if (alive) setProjects(r) }).catch(() => {})
    load()
    const un = listen('project-updated', load)
    return () => { alive = false; un.then(f => f()) }
  }, [])

  const q = query.trim().toLowerCase()
  const results = q
    ? projects.filter(p => (p.name || p.id).toLowerCase().includes(q) || p.id.toLowerCase().includes(q)).slice(0, 8)
    : []

  const pickProject = (p: Project) => {
    setActiveProject(p)
    setQuery(''); setSearchOpen(false)
    searchRef.current?.blur()
  }

  // Real notification list — one row per project currently extracting or errored.
  // `dismissed` hides rows the user has closed via the X; a project re-appears
  // if its status later changes (e.g. running → failed) since that's new info.
  const [dismissed, setDismissed] = useState<Record<string, string>>({})
  const nameOf = (pid: string) => projects.find(p => p.id === pid)?.name || pid
  const notifItems = Object.entries(byProject)
    .filter(([, s]) => s.isExtracting || s.extractError)
    .map(([pid, s]) => ({ pid, kind: s.isExtracting ? 'running' as const : 'error' as const }))
    .filter(item => dismissed[item.pid] !== item.kind)
  const notifCount = notifItems.length

  const dismissNotif = (pid: string, kind: string) =>
    setDismissed(d => ({ ...d, [pid]: kind }))

  const openNotifProject = (pid: string) => {
    const p = projects.find(pr => pr.id === pid)
    if (p) setActiveProject(p)
    setNotifOpen(false)
  }

  return (
    <header className="topbar">
      {activeProject && (
        <>
          <span className="topbar-sep">›</span>
          <span className="topbar-title">{activeProject.name || activeProject.id}</span>
          <span className="topbar-sep">›</span>
          <span className="topbar-screen">{meta.label}</span>
        </>
      )}

      <span className="topbar-spacer" />



      {/* Global search — filters projects; Enter opens the top match */}
      <div className="hdr-search-wrap">
        <div className="hdr-search">
          <Search size={16} className="hdr-search__icon" />
          <input
            ref={searchRef}
            className="hdr-search__input"
            placeholder="Search projects…"
            aria-label="Search"
            value={query}
            onChange={e => { setQuery(e.target.value); setSearchOpen(true) }}
            onFocus={() => setSearchOpen(true)}
            onKeyDown={e => {
              if (e.key === 'Escape') { setQuery(''); setSearchOpen(false); searchRef.current?.blur() }
              if (e.key === 'Enter' && results[0]) pickProject(results[0])
            }}
          />
          {q && (
            <button
              type="button"
              className="hdr-kbd hdr-kbd--enter"
              disabled={!results[0]}
              title={results[0] ? `Open ${results[0].name || results[0].id}` : 'No matches'}
              onClick={() => { if (results[0]) pickProject(results[0]) }}
            >
              ↵ Enter
            </button>
          )}
        </div>
        {searchOpen && q && (
          <div className="hdr-search-results">
            {results.length === 0 ? (
              <div className="hdr-search-empty">No projects match “{query.trim()}”.</div>
            ) : results.map(p => (
              <button key={p.id} className="hdr-search-row" onClick={() => pickProject(p)}>
                <span className="hdr-search-row__name">{p.name || p.id}</span>
                <span className="hdr-search-row__meta">{p.instruments} instr · {p.equipment} equip · {p.drawings} dwg</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Notifications */}
      <div className="hdr-pop-wrap">
        <button
          className="hdr-icon-btn"
          title="Notifications"
          onClick={() => { setNotifOpen(o => !o); setProfileOpen(false) }}
        >
          <Bell size={18} />
          {notifCount > 0 && <span className="hdr-badge">{notifCount}</span>}
        </button>
        {notifOpen && (
          <div className="hdr-popover">
            <div className="hdr-pop-title">Notifications</div>
            {notifItems.length === 0 ? (
              <div className="hdr-pop-empty">You’re all caught up.</div>
            ) : (
              <div className="notif-list">
                {notifItems.map(item => (
                  <div key={item.pid} className="notif-row">
                    <button className="notif-row__main" onClick={() => openNotifProject(item.pid)}>
                      <span className={`notif-row__icon ${item.kind}`}>
                        {item.kind === 'running' ? <Loader2 size={13} className="notif-spin" /> : <AlertTriangle size={13} />}
                      </span>
                      <span className="notif-row__body">
                        <span className="notif-row__name">{nameOf(item.pid)}</span>
                        <span className="notif-row__status">{item.kind === 'running' ? 'Extracting…' : 'Extraction failed'}</span>
                      </span>
                    </button>
                    <button
                      className="notif-row__close"
                      title="Dismiss"
                      aria-label="Dismiss notification"
                      onClick={() => dismissNotif(item.pid, item.kind)}
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} />}
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      {profileEditOpen && <EditProfileModal onClose={() => setProfileEditOpen(false)} />}
      {usageOpen && <UsageModal onClose={() => setUsageOpen(false)} />}

      {/* User avatar — Settings and Help now live here instead of their own
          header icons, so profile-related actions have one entry point. */}
      {user && (
        <div className="hdr-pop-wrap">
          <button
            className="hdr-avatar-btn"
            title={user.name}
            onClick={() => { setProfileOpen(o => !o); setNotifOpen(false) }}
          >
            <span className="hdr-avatar">{user.name.charAt(0).toUpperCase()}</span>
          </button>
          {profileOpen && (
            <div className="hdr-popover hdr-popover--right">
              <button
                className="hdr-pop-user hdr-pop-user--clickable"
                title="Edit profile"
                onClick={() => { setProfileEditOpen(true); setProfileOpen(false) }}
              >
                <div className="hdr-pop-user__name">{user.name}</div>
                <div className="hdr-pop-user__email">{user.email}</div>
              </button>
              <button className="hdr-pop-item" onClick={() => { setUsageOpen(true); setProfileOpen(false) }}>
                <BarChart2 size={14} /> Usage
              </button>
              <button className="hdr-pop-item" onClick={() => { setSettingsOpen(true); setProfileOpen(false) }}>
                <Settings size={14} /> Settings
              </button>
              <button className="hdr-pop-item" onClick={() => { setHelpOpen(true); setProfileOpen(false) }}>
                <HelpCircle size={14} /> Help
              </button>
              <button className="hdr-pop-item hdr-pop-item--danger" onClick={() => logout()}>
                <LogOut size={14} /> Log out
              </button>
            </div>
          )}
        </div>
      )}

      {(notifOpen || profileOpen || (searchOpen && q)) && (
        <div className="hdr-backdrop" onClick={() => { setNotifOpen(false); setProfileOpen(false); setSearchOpen(false) }} />
      )}
    </header>
  )
}
