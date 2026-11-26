import { useState, useEffect, useRef, useContext } from 'react'
import { emitGraphChanged } from '../../shared/graphEvents'
import { Wand2 } from 'lucide-react'
import type { Project, Screen } from '../../App'
import * as describeService from '../../services/describe'
import * as llmConfigService from '../../services/llmConfig'
import { addUsageScan } from '../../services/invoke/usage'
import { Ctx as ExtractionCtx } from '../../state/useExtraction'
import { type LlmProvider, isValidProvider, hasCredential as domainHasCredential } from '../../domain/llm/credentials'
import type { CredentialStatus } from '../../services/invoke/config'
import { placeNewNodes, parseDirection, pickFreeSpot } from '../../domain/layout/placement'
import type { ChatEntry, GraphData } from '../../features/describe/types'
import { extractJson } from '../../features/describe/utils/extractJson'
import { callLlm, type LlmCredentials, type ApiMessage } from '../../features/describe/utils/llmClient'
import { resolveIntent } from '../../features/copilot/actions/intents'
import { ask as copilotAsk } from '../../features/copilot/services/copilotService'
import { requestCanvasFocus } from '../../features/canvas/focusBus'
import { useDescribeSessions } from '../../features/describe/hooks/useDescribeSessions'
import { useAutoScroll } from '../../features/describe/hooks/useAutoScroll'
import { ApiKeyModal } from '../../features/describe/components/ApiKeyModal'
import { SessionDeleteModal } from '../../features/describe/components/SessionDeleteModal'
import { SessionToolbar } from '../../features/describe/components/SessionToolbar'
import { MessageList } from '../../features/describe/components/MessageList'
import { MessageComposer } from '../../features/describe/components/MessageComposer'
import { composeWithAttachments } from '../../features/describe/attachments/compose'
import type { PendingAttachment } from '../../features/describe/attachments/types'

interface Props {
  project: Project | null
  setActiveScreen: (s: Screen) => void
}

// Read/navigation intents handled by the Assistant brain (search, focus,
// explain, drawing summary, validation Q&A). Everything else — free-form
// authoring, rename, connect, delete, move — stays on Describe's own
// diagram-editing pipeline below, unchanged.
const READ_INTENTS = new Set(['search', 'focus', 'explain', 'summary', 'validation'])

export default function DescribeScreen({ project, setActiveScreen }: Props) {
  const extractionCtx = useContext(ExtractionCtx)
  // Booleans, not secrets — see the credential-loading effect below.
  const [credStatus,  setCredStatus]  = useState<CredentialStatus | null>(null)
  const [showModal,   setShowModal]   = useState(false)
  // A "Start retrofit" from the Ingest screen leaves a starter prompt behind.
  const [input,       setInput]       = useState(() => {
    try {
      const prefill = sessionStorage.getItem('describe.prefill') ?? ''
      sessionStorage.removeItem('describe.prefill')
      return prefill
    } catch { return '' }
  })
  const [loading,     setLoading]     = useState(false)
  const [attachments, setAttachments] = useState<PendingAttachment[]>([])

  // Agent mode routes the turn to the BACKEND's eight Describe specialists
  // (query, authoring, update, deletion, validation, solution, greenfield,
  // brownfield) instead of the client-side LLM turn below. Those agents
  // shipped with the backend but had no way into the UI at all, so nobody
  // could use them. Off by default: the existing client-side path is
  // unchanged, and this is opt-in per browser.
  const [agentMode, setAgentMode] = useState<boolean>(() => {
    try { return localStorage.getItem('describe.agentMode') === '1' }
    catch { return false }
  })

  function toggleAgentMode() {
    setAgentMode(prev => {
      const next = !prev
      try { localStorage.setItem('describe.agentMode', next ? '1' : '0') }
      catch { /* private mode / blocked storage — the toggle still works */ }
      return next
    })
  }

  const {
    sessions, activeSessionId, setActiveSessionId, chat, setChat,
    sessionMenuOpen, setSessionMenuOpen,
    sessionToDelete, setSessionToDelete,
    editingSessionId, setEditingSessionId,
    editingTitle, setEditingTitle,
    loadSessions, loadSession, startNewChat, confirmDeleteSession, saveSessionTitle,
  } = useDescribeSessions(project)

  // Describe mode calls whatever LLM provider is configured app-wide (set on
  // the Ingest screen) instead of always hardcoding Anthropic.
  const [provider,   setProvider]   = useState<LlmProvider>('anthropic')
  const [anthropicModel, setAnthropicModel] = useState('')
  const [geminiModel, setGeminiModel] = useState('')
  const [openaiModel, setOpenaiModel] = useState('')
  const [customModel, setCustomModel] = useState('')

  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Load the active provider + its credentials whenever project changes.
  // (Session/chat loading for the same project change lives in useDescribeSessions.)
  // Phase 0: this screen used to pull every provider's plaintext key into
  // component state. It only ever needed two things from them — "is one
  // configured?" (to decide whether to show the key modal) and "hand it to
  // callLlm". The Rust proxy resolves the key itself now, so all we load is
  // a set of booleans.
  useEffect(() => {
    llmConfigService.getCredentialStatus()
      .then(s => setCredStatus(s))
      .catch(() => setCredStatus(null))
    llmConfigService.getLlmProvider().then(async p => {
      if (!isValidProvider(p)) return
      setProvider(p)
      if (p.startsWith('custom:')) {
        const presetId = p.slice('custom:'.length)
        const rows = await llmConfigService.getCustomProviders().catch(() => [])
        setCustomModel(rows.find(r => r.id === presetId)?.model ?? '')
      }
    }).catch(() => setProvider('anthropic'))
    llmConfigService.getModels().then(m => setAnthropicModel(m.anthropic ?? '')).catch(() => setAnthropicModel(''))
    llmConfigService.getGeminiModel().then(m => setGeminiModel(m.gemini ?? '')).catch(() => setGeminiModel(''))
    llmConfigService.getOpenaiModel().then(m => setOpenaiModel(m.openai ?? '')).catch(() => setOpenaiModel(''))
  }, [project?.id])

  useAutoScroll(bottomRef, chat, loading)

  // Saving a key is still a one-way trip into the encrypted store; we just
  // re-read the boolean status afterwards instead of caching the value.
  const confirmApiKey = async (key: string) => {
    if (provider === 'gemini') {
      await llmConfigService.saveGeminiKey(key)
    } else if (provider === 'openai') {
      await llmConfigService.saveOpenaiKey(key)
    } else if (provider.startsWith('custom:')) {
      await llmConfigService.saveCustomProvider(provider.slice('custom:'.length), key, customModel)
    } else {
      await llmConfigService.saveApiKey(key)
    }
    await llmConfigService.getCredentialStatus().then(setCredStatus).catch(() => {})
    setShowModal(false)
  }

  // ── Delete confirmation ──────────────────────────────────────────────────────

  async function confirmDeletes(entryIndex: number, tags: string[]) {
    if (!project) return
    let deleted = 0
    if (agentMode) {
      // The Deletion agent is paused on a checkpointed interrupt and performs
      // the delete itself on resume — deleting here as well would double-apply
      // and bypass the agent's own auditing.
      const res = await describeService
        .describeAgentResolve(project.id, true, `ui-${activeSessionId}`)
        .catch(() => null)
      deleted = res?.ops?.length ?? tags.length
      if (deleted) emitGraphChanged(project.id)
    } else {
      for (const tag of tags) {
        try { await describeService.deleteNodeByTag(project.id, tag); deleted++ }
        catch { /* tag already gone or not found — skip */ }
      }
    }
    const dbId = chat[entryIndex]?.dbId
    if (dbId != null) {
      await describeService.resolveDescribeDelete(dbId, 'confirmed', deleted).catch(() => {})
    }
    setChat(prev => prev.map((e, i) => i === entryIndex
      ? { ...e, deleteResolution: 'confirmed', nodesDeleted: deleted }
      : e))
  }

  async function cancelDeletes(entryIndex: number) {
    if (agentMode && project) {
      // Release the agent's interrupt too, or its thread stays parked and the
      // next confirm/cancel resolves a stale pause.
      await describeService
        .describeAgentResolve(project.id, false, `ui-${activeSessionId}`)
        .catch(() => {})
    }
    const dbId = chat[entryIndex]?.dbId
    if (dbId != null) {
      await describeService.resolveDescribeDelete(dbId, 'cancelled', 0).catch(() => {})
    }
    setChat(prev => prev.map((e, i) => i === entryIndex
      ? { ...e, deleteResolution: 'cancelled' }
      : e))
  }

  // ── LLM call — routes to whichever provider is configured app-wide ──────────

  function hasCredential(): boolean {
    return domainHasCredential(provider, credStatus)
  }

  // ── Send ─────────────────────────────────────────────────────────────────────

  // Assistant path: answer a read/nav request (search, explain, summary,
  // validation, focus) via the shared Copilot service. Renders a markdown
  // answer + clickable results; never touches the diagram.
  async function handleAsk(text: string) {
    if (!project) return
    setInput('')
    const userEntry: ChatEntry = { role: 'user', display: text, apiContent: text }
    setChat(prev => [...prev, userEntry])
    setLoading(true)
    let sid = activeSessionId
    try {
      if (sid == null) { const r = await describeService.createDescribeSession(project.id); sid = r.id; setActiveSessionId(sid) }
      const creds: LlmCredentials = { provider, anthropicModel, geminiModel, openaiModel, customModel }
      const res = await copilotAsk(text, {
        projectId: project.id, projectName: project.name, history: [], creds,
        focus: tag => requestCanvasFocus(tag),
        onToken: () => { /* Describe renders the full answer, not streamed */ },
      })
      setChat(prev => [...prev, {
        role: 'assistant', display: res.content, apiContent: res.content,
        answerMarkdown: true, results: res.results,
      }])
      if (res.navigate) setActiveScreen('canvas')
      describeService.saveDescribeMessage({ sessionId: sid, projectId: project.id, role: 'user', display: text, apiContent: text, nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0, pendingDeletes: null, isError: false }).catch(() => {})
      describeService.saveDescribeMessage({ sessionId: sid, projectId: project.id, role: 'assistant', display: res.content, apiContent: res.content, nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0, pendingDeletes: null, isError: false }).catch(() => {})
      loadSessions(project.id)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setChat(prev => [...prev, { role: 'assistant', display: `Error: ${msg}`, apiContent: `Error: ${msg}`, isError: true }])
    } finally {
      setLoading(false)
      textareaRef.current?.focus()
    }
  }

  /** One turn through the backend Describe agents. They own their tools and
   *  write to the graph server-side, so there are no ops to apply here — the
   *  canvas just re-reads the graph afterwards. */
  async function handleAgentSend(text: string) {
    if (!project) return
    setInput('')
    setLoading(true)

    let sid = activeSessionId
    const userEntry: ChatEntry = { role: 'user', display: text, apiContent: text }
    setChat(prev => [...prev, userEntry])

    try {
      if (sid == null) {
        const r = await describeService.createDescribeSession(project.id)
        sid = r.id
        setActiveSessionId(sid)
      }

      describeService.saveDescribeMessage({
        sessionId: sid, projectId: project.id, role: 'user', display: text,
        apiContent: text, nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0,
        pendingDeletes: null, isError: false,
      }).catch(() => {})

      const res = await describeService.describeAgentTurn(
        project.id, text, `ui-${sid}`)

      // The Deletion agent pauses on a checkpointed interrupt. Surface its
      // tags through the same confirm/cancel banner the client-side path uses.
      const pendingDeletes = res.status === 'pending_delete'
        ? (res.pending_delete?.tags ?? [])
        : undefined

      const reply = res.reply
        ?? (pendingDeletes?.length
              ? `Confirm deletion of ${pendingDeletes.join(', ')}?`
              : 'The agent returned no reply.')

      // Writes happened server-side; count them for the activity feed and
      // tell the Canvas and hierarchy panel to reload.
      const writeOps = (res.ops ?? []).length
      if (writeOps) emitGraphChanged(project.id)
      const agentEntry: ChatEntry = {
        role: 'assistant',
        display: res.agent ? `[${res.agent}] ${reply}` : reply,
        apiContent: JSON.stringify(res),
        pendingDeletes: pendingDeletes?.length ? pendingDeletes : undefined,
      }
      setChat(prev => [...prev, agentEntry])

      const r = await describeService.saveDescribeMessage({
        sessionId: sid, projectId: project.id, role: 'assistant',
        display: agentEntry.display, apiContent: agentEntry.apiContent,
        nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0,
        pendingDeletes: pendingDeletes?.length ? JSON.stringify(pendingDeletes) : null,
        isError: false,
      }).catch(() => null)
      if (r) setChat(prev => prev.map(e => e === agentEntry ? { ...e, dbId: r.id } : e))

      if (res.title?.trim()) {
        await describeService.renameDescribeSession(sid, res.title.trim()).catch(() => {})
      }
      if (writeOps) {
        extractionCtx?.logActivity(project.id, {
          stage: 'describe', label: `Described via ${res.agent ?? 'agent'}`,
          detail: `${writeOps} operation${writeOps === 1 ? '' : 's'}`,
          status: 'complete', startedAt: Date.now(),
        })
      }
      loadSessions(project.id)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setChat(prev => [...prev, {
        role: 'assistant', display: `Error: ${msg}`,
        apiContent: `Error: ${msg}`, isError: true,
      }])
      if (sid != null) {
        describeService.saveDescribeMessage({
          sessionId: sid, projectId: project.id, role: 'assistant',
          display: `Error: ${msg}`, apiContent: `Error: ${msg}`,
          nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0,
          pendingDeletes: null, isError: true,
        }).catch(() => {})
      }
      loadSessions(project.id)
    } finally {
      setLoading(false)
      textareaRef.current?.focus()
    }
  }

  async function handleSend() {
    const text = input.trim()
    const attachmentsForTurn = attachments
    if ((!text && attachmentsForTurn.length === 0) || loading || !project) return
    if (!hasCredential()) { setShowModal(true); return }

    // Attachments need the vision-capable authoring pipeline below — the
    // Assistant brain (copilotAsk) doesn't take images/documents — so a
    // message with an attachment always goes through here even if its text
    // alone would otherwise read as a read/navigation request.
    if (attachmentsForTurn.length === 0 && READ_INTENTS.has(resolveIntent(text).kind)) { handleAsk(text); return }

    // Agent mode owns the whole turn, including read-only questions (the Query
    // specialist handles those). Attachments stay on the client-side path:
    // the agents take a text message only.
    if (agentMode && attachmentsForTurn.length === 0 && text) {
      handleAgentSend(text)
      return
    }

    setInput('')
    setAttachments([])
    setLoading(true)

    // Declared outside the try so the catch block can still use it to persist
    // an error message against the right session.
    let sid = activeSessionId

    // Show the user's own message immediately — independent of whether the
    // session/graph/API calls below succeed — so it never silently disappears
    // behind a stuck "Thinking…" indicator.
    const newUserEntry: ChatEntry = {
      role: 'user', display: text, apiContent: text,
      attachments: attachmentsForTurn.length ? attachmentsForTurn.map(a => ({ name: a.name, kind: a.kind })) : undefined,
    }
    setChat(prev => [...prev, newUserEntry])

    // Build the message list Claude will see using history as-is; the state
    // block gets spliced into this entry's apiContent below once available.
    const allMessages: ChatEntry[] = [...chat, newUserEntry]

    try {
      // Ensure there's a session to persist into — create one lazily on first send.
      if (sid == null) {
        const r = await describeService.createDescribeSession(project.id)
        sid = r.id
        setActiveSessionId(sid)
      }

      // Fresh graph snapshot so Claude sees current state
      let graph: GraphData = { nodes: [], edges: [] }
      try { graph = await describeService.getGraph(project.id) as unknown as GraphData }
      catch { /* proceed with empty */ }

      const idToLabel = new Map(graph.nodes.map(n => [n.id, n.label || n.id]))
      const nodeCtx = graph.nodes.slice(0, 100)
        .map(n => `${n.label}(${n.kind}${n.area ? ',' + n.area : ''})`)
        .join(', ')
      const edgeCtx = graph.edges.slice(0, 80)
        .map(e => `${idToLabel.get(e.source) ?? e.source}→${idToLabel.get(e.target) ?? e.target}(${e.kind || 'stream'})`)
        .join(', ')

      const stateBlock =
        `CURRENT STATE:\n` +
        `Equipment (${graph.nodes.length}): ${nodeCtx || 'none'}\n` +
        `Connections (${graph.edges.length}): ${edgeCtx || 'none'}`

      const rawUserApiContent = `${stateBlock}\n\nUser: "${text}"`
      // Fold in any attachments: text/docx get inlined as plain text (safe to
      // persist below); image/PDF become real content parts sent ONLY for
      // this request — never written to the database, so history never
      // balloons with base64 and future turns don't resend it.
      const { text: userApiContent, parts: attachmentParts } = composeWithAttachments(rawUserApiContent, attachmentsForTurn)
      newUserEntry.apiContent = userApiContent
      allMessages[allMessages.length - 1] = newUserEntry

      describeService.saveDescribeMessage({
        sessionId: sid, projectId: project.id, role: 'user', display: text, apiContent: userApiContent,
        nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0, pendingDeletes: null, isError: false,
      }).then(r => {
        newUserEntry.dbId = r.id
        setChat(prev => prev.map(e => e === newUserEntry ? { ...e, dbId: r.id } : e))
      }).catch(() => {})

      const apiMessages: ApiMessage[] = allMessages.map((m, i) => ({
        role: m.role,
        content: i === allMessages.length - 1 && attachmentParts ? attachmentParts : m.apiContent,
      }))

      const { text: rawText, usage } = await callLlm(apiMessages, { provider, anthropicModel, geminiModel, openaiModel, customModel })
      addUsageScan(project.id, usage.provider, usage.model, usage.tokensIn, usage.tokensOut, usage.costUsd).catch(console.error)
      const parsed  = extractJson(rawText)

      let nodesAdded   = 0
      let edgesAdded   = 0
      let nodesUpdated = 0

      if (parsed?.add_nodes?.length || parsed?.add_junctions?.length) {
        const junctionIds = (parsed.add_junctions ?? []).map(j => j.id)
        const posMap = placeNewNodes(
          graph.nodes, parsed.add_nodes ?? [], parsed.add_edges ?? [], parseDirection(text), junctionIds
        )

        if (parsed?.add_nodes?.length) {
          const nodesWithPos = parsed.add_nodes.map(n => ({ ...n, ...posMap.get(n.tag) }))
          const r = await describeService.batchInsertNodes(project.id, JSON.stringify(nodesWithPos))
          nodesAdded = r.inserted
        }

        // Only insert a junction if some edge actually anchored it to a
        // known position — an unreferenced junction id has nothing to
        // connect to and would just sit at a meaningless default spot.
        const junctionsWithPos = junctionIds
          .map(id => ({ id, ...posMap.get(id) }))
          .filter((j): j is { id: string; x: number; y: number; drawing?: string } => j.x !== undefined)
        if (junctionsWithPos.length) {
          await describeService.batchInsertJunctions(project.id, JSON.stringify(junctionsWithPos)).catch(() => {})
        }
      }

      if (parsed?.add_edges?.length) {
        const r = await describeService.batchInsertEdges(project.id, JSON.stringify(parsed.add_edges))
        edgesAdded = r.inserted
      }

      if (parsed?.update_nodes?.length) {
        const byLabel = new Map(graph.nodes.map(n => [n.label, n]))
        const moveDir = parseDirection(text)
        for (const u of parsed.update_nodes) {
          try {
            await describeService.updateNodeByTag(project.id, u.tag, u.new_tag, u.kind, u.area, u.description)
            nodesUpdated++
          } catch { /* skip tags that fail to resolve/rename */ }

          // Reposition: place the node beside its anchor on the side the user
          // asked for, reusing the same free-spot logic the add path uses. id
          // is stable across a rename, so look it up by the original tag.
          if (u.move_near) {
            const node   = byLabel.get(u.tag)
            const anchor = byLabel.get(u.move_near)
            if (node && anchor) {
              const occupied = graph.nodes.filter(n => n.id !== node.id).map(n => ({ x: n.x, y: n.y }))
              const spot = pickFreeSpot({ x: anchor.x, y: anchor.y }, occupied, moveDir)
              await describeService.updateNodePosition(project.id, node.id, spot.x, spot.y).catch(() => {})
            }
          }
        }
      }

      // Deletes are destructive — stage them for explicit confirmation instead
      // of executing immediately.
      const pendingDeletes = parsed?.delete_nodes?.length ? parsed.delete_nodes : undefined

      const reply = parsed?.reply ?? (rawText.slice(0, 400))

      // Surface this turn in the Home screen's Latest Activity feed — that
      // panel only ever sourced from extraction's own progress events, so a
      // project built purely through Describe never showed anything there.
      if (nodesAdded || edgesAdded || nodesUpdated) {
        const parts = [
          nodesAdded   ? `+${nodesAdded} node${nodesAdded === 1 ? '' : 's'}` : '',
          edgesAdded   ? `+${edgesAdded} edge${edgesAdded === 1 ? '' : 's'}` : '',
          nodesUpdated ? `${nodesUpdated} updated` : '',
        ].filter(Boolean).join(' · ')
        extractionCtx?.logActivity(project.id, {
          stage: 'describe', label: 'Described via chat', detail: parts,
          status: 'complete', startedAt: Date.now(),
        })
      }

      const assistantEntry: ChatEntry = {
        role: 'assistant',
        display: reply,
        apiContent: rawText,
        nodesAdded,
        edgesAdded,
        nodesUpdated,
        pendingDeletes,
      }
      setChat(prev => [...prev, assistantEntry])

      const r = await describeService.saveDescribeMessage({
        sessionId: sid, projectId: project.id, role: 'assistant', display: reply, apiContent: rawText,
        nodesAdded, edgesAdded, nodesUpdated,
        pendingDeletes: pendingDeletes ? JSON.stringify(pendingDeletes) : null,
        isError: false,
      }).catch(() => null)
      if (parsed?.title?.trim()) {
        await describeService.renameDescribeSession(sid, parsed.title.trim()).catch(() => {})
      }

      if (r) {
        setChat(prev => prev.map(e => e === assistantEntry ? { ...e, dbId: r.id } : e))
      }
      loadSessions(project.id)

    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setChat(prev => [...prev, {
        role: 'assistant',
        display: `Error: ${msg}`,
        apiContent: `Error: ${msg}`,
        isError: true,
      }])
      describeService.saveDescribeMessage({
        sessionId: sid, projectId: project.id, role: 'assistant', display: `Error: ${msg}`, apiContent: `Error: ${msg}`,
        nodesAdded: 0, edgesAdded: 0, nodesUpdated: 0, pendingDeletes: null, isError: true,
      }).catch(() => {})
      loadSessions(project.id)
    } finally {
      setLoading(false)
      textareaRef.current?.focus()
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  if (!project) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 12 }}>
        <Wand2 size={40} strokeWidth={1.2} style={{ opacity: 0.25 }} />
        <span style={{ color: 'var(--text-muted)', fontSize: 14 }}>Select a project to use Describe mode</span>
      </div>
    )
  }

  return (
    <>
      {showModal && <ApiKeyModal provider={provider} onConfirm={confirmApiKey} onClose={() => setShowModal(false)} />}
      {sessionToDelete && (
        <SessionDeleteModal
          session={sessionToDelete}
          onClose={() => setSessionToDelete(null)}
          onConfirm={() => { confirmDeleteSession(sessionToDelete); setSessionToDelete(null) }}
        />
      )}

      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 0, overflow: 'hidden' }}>

        <SessionToolbar
          sessions={sessions}
          activeSessionId={activeSessionId}
          sessionMenuOpen={sessionMenuOpen}
          setSessionMenuOpen={setSessionMenuOpen}
          editingSessionId={editingSessionId}
          setEditingSessionId={setEditingSessionId}
          editingTitle={editingTitle}
          setEditingTitle={setEditingTitle}
          onSelectSession={loadSession}
          onSaveTitle={saveSessionTitle}
          onRequestDelete={setSessionToDelete}
          onNewChat={startNewChat}
        />

        <button
          type="button"
          onClick={toggleAgentMode}
          title={agentMode
            ? 'Agent mode ON — turns go to the backend Describe specialists (query, authoring, update, deletion, validation, solution, greenfield, brownfield)'
            : 'Agent mode OFF — turns use the in-app LLM call'}
          style={{
            alignSelf: 'flex-start',
            margin: '0 12px 6px',
            padding: '3px 10px',
            fontSize: 11,
            lineHeight: 1.6,
            borderRadius: 999,
            cursor: 'pointer',
            border: '1px solid var(--border, #3a3a3a)',
            background: agentMode ? 'var(--accent, #2d6cdf)' : 'transparent',
            color: agentMode ? '#fff' : 'var(--text-muted, #888)',
          }}
        >
          {agentMode ? 'Agent mode: on' : 'Agent mode: off'}
        </button>

        <MessageList
          chat={chat}
          loading={loading}
          bottomRef={bottomRef}
          onCancelDeletes={cancelDeletes}
          onConfirmDeletes={confirmDeletes}
          onFocusTag={tag => { requestCanvasFocus(tag); setActiveScreen('canvas') }}
        />

        <MessageComposer
          input={input}
          setInput={setInput}
          onKeyDown={handleKeyDown}
          onSend={handleSend}
          loading={loading}
          textareaRef={textareaRef}
          attachments={attachments}
          setAttachments={setAttachments}
        />
      </div>
    </>
  )
}
