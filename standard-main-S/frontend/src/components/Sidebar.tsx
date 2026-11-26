import { useState, useEffect, useRef } from 'react'
import { listen } from '@tauri-apps/api/event'
import { toast } from 'sonner'
import type { Project, Screen } from '../App'
import { storedUserId } from '../services/authApi'
import * as projectService from '../services/project'
import { NewProjectModal } from '../features/sidebar/components/NewProjectModal'
import { RenameProjectModal } from '../features/sidebar/components/RenameProjectModal'
import { DeleteProjectModal } from '../features/sidebar/components/DeleteProjectModal'
import { SidebarNav } from '../features/sidebar/components/SidebarNav'
import { ProjectList } from '../features/sidebar/components/ProjectList'
import { HierarchyPanel } from '../features/hierarchy/HierarchyPanel'

interface Props {
  activeProject: Project | null
  setActiveProject: (p: Project | null) => void
  refreshProject: (p: Project) => void
  activeScreen: Screen
  setActiveScreen: (s: Screen) => void
}

export default function Sidebar({ activeProject, setActiveProject, refreshProject, activeScreen, setActiveScreen }: Props) {
  const [projects,   setProjects]   = useState<Project[]>([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState<string>('')

  // Modal states
  const [showNew,    setShowNew]    = useState(false)
  const [newName,    setNewName]    = useState('')
  const [creating,   setCreating]   = useState(false)
  const [createErr,  setCreateErr]  = useState('')
  const nameInputRef = useRef<HTMLInputElement>(null)

  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null)
  const [projectToRename, setProjectToRename] = useState<Project | null>(null)
  const [renameInput, setRenameInput] = useState('')
  const [renameBusy, setRenameBusy] = useState(false)
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)
  // Profile editing and logout live in the Topbar (EditProfileModal) — the
  // Sidebar's own copy was removed; only the outside-click reset survives.
  const [, setProfileMenuOpen] = useState(false)

  const [collapsed,  setCollapsed]  = useState(false)

  // Close menus when clicking outside
  useEffect(() => {
    const handleClick = () => { setMenuOpenId(null); setProfileMenuOpen(false); }
    document.addEventListener('click', handleClick)
    return () => document.removeEventListener('click', handleClick)
  }, [])

  // Open the New Project modal when the landing "Create Project" quick action fires.
  useEffect(() => {
    const open = () => setShowNew(true)
    window.addEventListener('enstudio:new-project', open)
    return () => window.removeEventListener('enstudio:new-project', open)
  }, [])

  // ── Load projects ───────────────────────────────────────────────────────────

  function loadProjects() {
    projectService.listProjects(storedUserId())
      .then(result => {
        setProjects(result)
        setError('')
        if (activeProject) {
          const updated = result.find(p => p.id === activeProject.id)
          if (updated && (
            updated.instruments !== activeProject.instruments ||
            updated.equipment !== activeProject.equipment ||
            updated.drawings !== activeProject.drawings ||
            updated.status !== activeProject.status
          )) {
            refreshProject(updated)
          }
        }
      })
      .catch((e: unknown) => {
        const msg = typeof e === 'string' ? e : JSON.stringify(e)
        console.error('[list_projects] error:', msg)
        setError(msg); setProjects([])
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadProjects()

    const unlisten = listen('project-updated', () => {
      loadProjects()
    })

    return () => { unlisten.then(f => f()) }
    // loadProjects is a plain function re-created every render (reads
    // activeProject/refreshProject from closure) — deliberately omitted so
    // this effect only re-subscribes on an actual screen change, not on
    // every render.
  }, [activeScreen])

  // Focus the name input whenever the modal opens
  useEffect(() => {
    if (showNew) {
      setNewName(''); setCreateErr('')
      setTimeout(() => nameInputRef.current?.focus(), 50)
    }
  }, [showNew])

  // ── Create project ──────────────────────────────────────────────────────────

  async function handleCreate() {
    const name = newName.trim()
    if (!name || creating) return
    setCreating(true); setCreateErr('')
    try {
      const result = await projectService.createProject(name, storedUserId())
      // Refresh project list, then auto-select the new project
      await new Promise<void>(resolve => {
        projectService.listProjects(storedUserId())
          .then(list => {
            setProjects(list)
            const created = list.find(p => p.id === result.pid)
            if (created) {
              setActiveProject(created)   // triggers App's selectProject → home
              setActiveScreen('describe') // override to describe for new blank projects
            } else {
              // Fallback: construct a minimal Project object
              setActiveProject({ id: result.pid, name: result.name, status: 'pending', instruments: 0, equipment: 0, drawings: 0, last_extraction: null, last_activity: null })
              setActiveScreen('describe')
            }
          })
          .catch(() => {
            // Even if refresh fails, navigate with minimal project
            setActiveProject({ id: result.pid, name: result.name, status: 'pending', instruments: 0, equipment: 0, drawings: 0, last_extraction: null, last_activity: null })
            setActiveScreen('describe')
          })
          .finally(resolve)
      })
      setShowNew(false)
    } catch (e: unknown) {
      setCreateErr(typeof e === 'string' ? e : JSON.stringify(e))
    } finally {
      setCreating(false)
    }
  }

  function handleDeleteProjectClick(p: Project, e: React.MouseEvent) {
    e.stopPropagation()
    setProjectToDelete(p)
  }

  async function confirmDeleteProject() {
    if (!projectToDelete) return
    const p = projectToDelete
    try {
      await projectService.deleteProject(p.id)
      if (activeProject?.id === p.id) {
        setActiveProject(null)
      }
      loadProjects()
    } catch (err) {
      toast.error(`Failed to delete project: ${err}`)
    } finally {
      setProjectToDelete(null)
    }
  }

  async function confirmRenameProject() {
    if (!projectToRename || !renameInput.trim() || renameBusy) return
    setRenameBusy(true)
    try {
      const res = await projectService.renameProject(projectToRename.id, renameInput)
      if (activeProject?.id === projectToRename.id) {
        setActiveProject({ ...activeProject, id: res.new_id, name: res.new_name })
      }
      loadProjects()
      setProjectToRename(null)
    } catch (err) {
      toast.error(`Rename failed: ${err}`)
    } finally {
      setRenameBusy(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <>
      {showNew && (
        <NewProjectModal
          newName={newName} setNewName={setNewName}
          createErr={createErr} setCreateErr={setCreateErr}
          creating={creating} nameInputRef={nameInputRef}
          onCreate={handleCreate}
          onCancel={() => setShowNew(false)}
        />
      )}

      {projectToRename && (
        <RenameProjectModal
          renameInput={renameInput} setRenameInput={setRenameInput}
          renameBusy={renameBusy}
          onConfirm={confirmRenameProject}
          onCancel={() => setProjectToRename(null)}
        />
      )}

      {projectToDelete && (
        <DeleteProjectModal
          project={projectToDelete}
          onConfirm={confirmDeleteProject}
          onCancel={() => setProjectToDelete(null)}
        />
      )}

      <aside className={`sidebar${collapsed ? ' collapsed' : ''}`}>
        <SidebarNav
          collapsed={collapsed} setCollapsed={setCollapsed}
          activeScreen={activeScreen} setActiveScreen={setActiveScreen}
        />

        {!collapsed && (
          <ProjectList
            projects={projects}
            loading={loading}
            error={error}
            activeProject={activeProject}
            setActiveProject={setActiveProject}
            menuOpenId={menuOpenId}
            setMenuOpenId={setMenuOpenId}
            onNewProject={() => setShowNew(true)}
            onRenameClick={p => { setRenameInput(p.name || p.id); setProjectToRename(p) }}
            onDeleteClick={handleDeleteProjectClick}
          />
        )}

        {!collapsed && activeProject && (
          <HierarchyPanel key={activeProject.id} projectId={activeProject.id} />
        )}

      </aside>
    </>
  )
}
