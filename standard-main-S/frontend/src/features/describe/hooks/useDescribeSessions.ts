import { useState, useCallback, useEffect } from 'react'
import type { Project } from '../../../App'
import * as describeService from '../../../services/describe'
import { rowToEntry } from '../utils/rowToEntry'
import type { ChatEntry, DescribeSession } from '../types'

// Session list + active-session/chat state, and the CRUD flows around them
// (new chat, delete, rename, switch). Loading the app-wide LLM
// provider/credentials on project change is a separate concern and stays
// in DescribeScreen's own effect — this hook only owns session/chat state.
export function useDescribeSessions(project: Project | null) {
  const [sessions, setSessions] = useState<DescribeSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null)
  const [chat, setChat] = useState<ChatEntry[]>([])
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false)
  const [sessionToDelete, setSessionToDelete] = useState<DescribeSession | null>(null)
  const [editingSessionId, setEditingSessionId] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState('')

  const loadSessions = useCallback(async (projectId: string) => {
    const list = await describeService.listDescribeSessions(projectId).catch(() => [])
    setSessions(list)
    return list
  }, [])

  const loadSession = useCallback(async (sessionId: number) => {
    const rows = await describeService.getDescribeMessages(sessionId).catch(() => [])
    setChat(rows.map(rowToEntry))
    setActiveSessionId(sessionId)
  }, [])

  // Creates the session row immediately (rather than waiting for the first
  // message) so "New chat" survives a refresh — otherwise nothing was ever
  // saved, and reloading just reopened whatever session was last used.
  const startNewChat = useCallback(async () => {
    setChat([])
    setActiveSessionId(null)
    if (!project) return
    const r = await describeService.createDescribeSession(project.id).catch(() => null)
    if (r) {
      setActiveSessionId(r.id)
      loadSessions(project.id)
    }
  }, [project, loadSessions])

  const confirmDeleteSession = useCallback(async (session: DescribeSession) => {
    if (!project) return
    await describeService.deleteDescribeSession(session.id).catch(() => {})
    const list = await loadSessions(project.id)
    if (session.id === activeSessionId) {
      if (list.length) loadSession(list[0].id)
      else { setActiveSessionId(null); setChat([]) }
    }
  }, [project, activeSessionId, loadSessions, loadSession])

  const saveSessionTitle = useCallback(async (session: DescribeSession) => {
    setEditingSessionId(null)
    const title = editingTitle.trim()
    if (!project || !title || title === session.title) return
    await describeService.renameDescribeSession(session.id, title).catch(() => {})
    loadSessions(project.id)
  }, [project, editingTitle, loadSessions])

  // Load the session list whenever project changes; open the most recent
  // session. Keyed by project id, not the project object — see
  // ExportScreen's load effect for the full rationale (same pattern across
  // every screen keyed by project).
  useEffect(() => {
    setChat([])
    setActiveSessionId(null)
    setSessions([])
    if (!project) return
    loadSessions(project.id).then(list => {
      if (list.length) loadSession(list[0].id)
    })
  }, [project?.id, loadSessions, loadSession])

  return {
    sessions, activeSessionId, setActiveSessionId, chat, setChat,
    sessionMenuOpen, setSessionMenuOpen,
    sessionToDelete, setSessionToDelete,
    editingSessionId, setEditingSessionId,
    editingTitle, setEditingTitle,
    loadSessions, loadSession, startNewChat, confirmDeleteSession, saveSessionTitle,
  }
}
