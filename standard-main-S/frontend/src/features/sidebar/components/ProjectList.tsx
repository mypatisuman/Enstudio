import { Pencil, Trash2 } from 'lucide-react'
import type { Project } from '../../../App'

function badgeClass(status: string) {
  if (status === 'extracted') return 'extracted'
  if (status === 'reviewed') return 'reviewed'
  if (status === 'uploaded') return 'uploaded'
  if (status === 'described') return 'described'
  return 'pending'
}

export function ProjectList({
  projects, loading, error, activeProject, setActiveProject,
  menuOpenId, setMenuOpenId, onNewProject, onRenameClick, onDeleteClick,
}: {
  projects: Project[]
  loading: boolean
  error: string
  activeProject: Project | null
  setActiveProject: (p: Project | null) => void
  menuOpenId: string | null
  setMenuOpenId: (id: string | null) => void
  onNewProject: () => void
  onRenameClick: (p: Project) => void
  onDeleteClick: (p: Project, e: React.MouseEvent) => void
}) {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 12px 4px', marginTop: 10 }}>
        <span className="sidebar-section-label" style={{ margin: 0, padding: 0 }}>Projects</span>
        <button
          className="new-project-btn"
          onClick={onNewProject}
          title="New project"
        >
          + New
        </button>
      </div>

      <div className="project-list">
        {loading && <div className="sidebar-hint">Loading…</div>}

        {!loading && error && (
          <div className="sidebar-hint" style={{ color: 'var(--danger)', fontSize: 11 }}>
            {error}
          </div>
        )}

        {!loading && !error && projects.length === 0 && (
          <div className="sidebar-hint">No projects — click + New to start</div>
        )}

        {projects.map(p => (
          <div
            key={p.id}
            className={`project-item${activeProject?.id === p.id ? ' active' : ''}`}
            onClick={() => setActiveProject(activeProject?.id === p.id ? null : p)}
            style={{ position: 'relative', zIndex: menuOpenId === p.id ? 50 : undefined }}
          >
            <div style={{ position: 'absolute', top: 10, right: 10 }}>
              <button
                className="btn btn-ghost"
                onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === p.id ? null : p.id) }}
                style={{
                  padding: 4, height: 26, width: 26,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  outline: 'none', border: 'none'
                }}
                title="Options"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="1"></circle>
                  <circle cx="12" cy="5" r="1"></circle>
                  <circle cx="12" cy="19" r="1"></circle>
                </svg>
              </button>
              {menuOpenId === p.id && (
                <div style={{
                  position: 'absolute', top: '100%', right: 0, marginTop: 4,
                  background: 'var(--bg-primary)', border: '1px solid var(--border)',
                  borderRadius: 8, padding: 6, boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
                  display: 'flex', flexDirection: 'column', gap: 2, zIndex: 100, minWidth: 120
                }}>
                    <button className="nav-item" style={{ marginBottom: 4 }}
                      onClick={(e) => { e.stopPropagation(); onRenameClick(p); setMenuOpenId(null); }}>
                      <span className="nav-icon" style={{ display: 'flex' }}><Pencil size={13} /></span>
                      Rename
                    </button>
                    <button className="nav-item" style={{ color: 'var(--danger)' }}
                      onClick={(e) => { e.stopPropagation(); onDeleteClick(p, e); setMenuOpenId(null); }}>
                      <span className="nav-icon" style={{ display: 'flex', opacity: 0.8 }}><Trash2 size={13} /></span>
                      Delete
                    </button>
                </div>
              )}
            </div>
            <div className="project-name" style={{ paddingRight: 20 }}>{p.name || p.id}</div>
            <div className="project-meta">
              {p.instruments} instr · {p.equipment} equip · {p.drawings} dwg
            </div>
            <span className={`status-badge ${badgeClass(p.status)}`}>
              {p.status || 'pending'}
            </span>
          </div>
        ))}
      </div>
    </>
  )
}
