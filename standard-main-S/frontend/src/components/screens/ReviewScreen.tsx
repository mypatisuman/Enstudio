import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { ClipboardCheck } from 'lucide-react'
import type { Project, Screen } from '../../App'
import * as reviewService from '../../services/review'
import type { Instrument, Equipment } from '../../services/review'
import { optimisticUpdate } from '../../domain/mutation/optimistic'
import { ErrorBanner } from '../../shared/components/error/ErrorBanner'
import { NoProjectState } from '../../shared/components/empty/NoProjectState'
import { ReviewStats } from '../../features/review/components/ReviewStats'
import { ReviewToolbar } from '../../features/review/components/ReviewToolbar'
import { ReviewFilterBar } from '../../features/review/components/ReviewFilterBar'
import { InstrumentTable, type EditField, type EditCell } from '../../features/review/components/InstrumentTable'
import { confidenceBucket } from '../../features/review/confidence'
import { requestCanvasFocus } from '../../features/canvas/focusBus'
import ConfirmModal from '../ConfirmModal'

interface Props { project: Project | null; setActiveScreen?: (s: Screen) => void }

export default function ReviewScreen({ project, setActiveScreen }: Props) {
  const [instruments, setInstruments] = useState<Instrument[]>([])
  const [equipment,   setEquipment]   = useState<Equipment[]>([])
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState('')
  const [search,      setSearch]      = useState('')
  const [filterStatus, setFilterStatus] = useState<string>('all')
  const [filterConf,   setFilterConf]   = useState<string>('all')
  const [filterType,   setFilterType]   = useState<string>('all')

  // Optimistic review status overrides (cleared on project switch)
  const [localStatus, setLocalStatus] = useState<Record<string, string>>({})
  // Row selection for bulk actions (tags)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Pending bulk confirmation
  const [confirm, setConfirm] = useState<{ action: 'accepted' | 'rejected'; tags: string[] } | null>(null)
  // Inline edit state
  const [editCell,  setEditCell]  = useState<EditCell | null>(null)
  const [editValue, setEditValue] = useState('')
  const editRef = useRef<HTMLInputElement>(null)
  // Bulk op loading
  const [bulkLoading, setBulkLoading] = useState(false)

  // Effective status: localStatus takes priority over what the DB returned
  const eff = useCallback((i: Instrument) => ({
    ...i,
    review_status: localStatus[i.tag] ?? i.review_status,
  }), [localStatus])

  // ── Data loading ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!project) return
    setLoading(true)
    setError('')
    setSearch(''); setFilterStatus('all'); setFilterConf('all'); setFilterType('all')
    setLocalStatus({}); setSelected(new Set()); setEditCell(null)

    Promise.all([
      reviewService.getInstruments(project.id),
      reviewService.getEquipment(project.id),
    ])
      .then(([instr, equip]) => { setInstruments(instr); setEquipment(equip) })
      .catch((e: unknown) => setError(typeof e === 'string' ? e : JSON.stringify(e)))
      .finally(() => setLoading(false))
  }, [project?.id])

  // Focus inline edit input when it appears
  useEffect(() => {
    if (editCell) { editRef.current?.focus(); editRef.current?.select() }
  }, [editCell])

  // ── Type filter options (from real data) ────────────────────────────────────
  const typeOptions = useMemo(() => {
    const set = new Set<string>()
    instruments.forEach(i => { const t = i.kind_detail || i.type; if (t) set.add(t) })
    return [...set].sort()
  }, [instruments])

  // ── Filtered list (search + status + confidence + type all combine) ─────────
  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return instruments.filter(i => {
      const effStatus = localStatus[i.tag] ?? i.review_status
      const matchSearch = !q ||
        i.tag.toLowerCase().includes(q) ||
        i.type.toLowerCase().includes(q) ||
        i.drawing.toLowerCase().includes(q) ||
        i.equipment_ref.toLowerCase().includes(q) ||
        i.area.toLowerCase().includes(q)
      const matchStatus = filterStatus === 'all' || effStatus === filterStatus
      const matchConf   = filterConf === 'all' || (i.confidence > 0 && confidenceBucket(i.confidence) === filterConf)
      const matchType   = filterType === 'all' || (i.kind_detail || i.type) === filterType
      return matchSearch && matchStatus && matchConf && matchType
    })
  }, [instruments, search, filterStatus, filterConf, filterType, localStatus])

  // ── Derived counts (effective status + confidence tiers) ────────────────────
  const statusCount = useCallback((s: string) =>
    instruments.filter(i => (localStatus[i.tag] ?? i.review_status) === s).length, [instruments, localStatus])
  const accepted = useMemo(() => statusCount('accepted'), [statusCount])
  const rejected = useMemo(() => statusCount('rejected'), [statusCount])
  const pending  = useMemo(() => statusCount('pending'),  [statusCount])

  const withConf = useMemo(() => instruments.filter(i => i.confidence > 0), [instruments])
  // Confidence isn't stored on instruments in every project (the extraction
  // pipeline keeps it on detected nodes, not instrument rows). Only surface the
  // confidence card / filter / column when there's actually data to show —
  // otherwise it's an empty control. Appears automatically if data lands later.
  const hasConfidence = withConf.length > 0
  // Same reasoning for the read-only extraction columns: this project's
  // instruments carry no drawing/area (the drawing didn't yield them), so
  // showing columns of all "—" is noise. Hide them when fully empty; they
  // reappear if any row has data. Equip-ref & description stay visible because
  // they're double-click-editable (you add them there).
  const hasDrawing = useMemo(() => instruments.some(i => i.drawing), [instruments])
  const hasArea    = useMemo(() => instruments.some(i => i.area),    [instruments])
  const avgConf  = withConf.length
    ? Math.round(withConf.reduce((s, i) => s + i.confidence, 0) / withConf.length * 100)
    : 0
  const highConf = useMemo(() => withConf.filter(i => confidenceBucket(i.confidence) === 'high').length, [withConf])
  const medConf  = useMemo(() => withConf.filter(i => confidenceBucket(i.confidence) === 'medium').length, [withConf])
  const lowConf  = useMemo(() => withConf.filter(i => confidenceBucket(i.confidence) === 'low').length, [withConf])
  const completionPct = instruments.length ? Math.round((accepted + rejected) / instruments.length * 100) : 0

  // ── Selection ───────────────────────────────────────────────────────────────
  const toggleSelect = useCallback((tag: string) => {
    setSelected(prev => { const n = new Set(prev); if (n.has(tag)) n.delete(tag); else n.add(tag); return n })
  }, [])
  const allFilteredSelected = filtered.length > 0 && filtered.every(i => selected.has(i.tag))
  const toggleAll = useCallback(() => {
    setSelected(prev => {
      const allSel = filtered.length > 0 && filtered.every(i => prev.has(i.tag))
      if (allSel) { const n = new Set(prev); filtered.forEach(i => n.delete(i.tag)); return n }
      const n = new Set(prev); filtered.forEach(i => n.add(i.tag)); return n
    })
  }, [filtered])
  const clearSelection = useCallback(() => setSelected(new Set()), [])

  // ── Review actions ──────────────────────────────────────────────────────────
  async function handleReview(tag: string, action: 'accepted' | 'rejected') {
    if (!project) return
    const current = localStatus[tag] ?? (instruments.find(i => i.tag === tag)?.review_status ?? 'pending')
    const next = current === action ? 'pending' : action  // toggle
    await optimisticUpdate({
      apply: () => setLocalStatus(prev => ({ ...prev, [tag]: next })),
      commit: () => reviewService.updateReviewStatus(project.id, tag, next),
      onError: () => setLocalStatus(prev => ({ ...prev, [tag]: current })),
    })
  }

  // Bulk apply the confirmed action to the selected tags.
  async function runBulk() {
    if (!project || !confirm) return
    const { action, tags } = confirm
    setConfirm(null)
    if (tags.length === 0) return
    const snapshot: Record<string, string> = {}
    tags.forEach(t => { snapshot[t] = localStatus[t] ?? (instruments.find(i => i.tag === t)?.review_status ?? 'pending') })
    await optimisticUpdate({
      apply: () => setLocalStatus(prev => { const n = { ...prev }; tags.forEach(t => { n[t] = action }); return n }),
      commit: () => { setBulkLoading(true); return reviewService.bulkUpdateReview(project.id, tags, action) },
      onError: () => setLocalStatus(prev => { const n = { ...prev }; Object.assign(n, snapshot); return n }),
      onSettled: () => { setBulkLoading(false); clearSelection() },
    })
  }

  // ── Inline edit ─────────────────────────────────────────────────────────────
  function startEdit(tag: string, field: EditField, current: string) { setEditCell({ tag, field }); setEditValue(current) }
  function cancelEdit() { setEditCell(null) }
  async function commitEdit() {
    if (!editCell || !project) { setEditCell(null); return }
    const { tag, field } = editCell
    const value = editValue.trim()
    setEditCell(null)
    await optimisticUpdate({
      apply: () => setInstruments(prev => prev.map(i => i.tag === tag ? { ...i, [field]: value } : i)),
      commit: () => reviewService.updateInstrument(project.id, tag, field, value),
      onError: (e) => console.error('update_instrument:', e),
    })
  }
  function handleEditKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); commitEdit() }
    if (e.key === 'Escape') { e.preventDefault(); cancelEdit() }
  }

  // ── Canvas navigation ───────────────────────────────────────────────────────
  const onRowFocus = useCallback((tag: string) => {
    requestCanvasFocus(tag)
    setActiveScreen?.('canvas')
  }, [setActiveScreen])

  // ── Contextual empty state ──────────────────────────────────────────────────
  const emptyState = useMemo(() => {
    if (instruments.length === 0) return { title: 'No instruments yet', body: 'Run extraction on the Upload screen to populate this project.' }
    if (search.trim()) return { title: 'No search results', body: `No instruments match “${search.trim()}”.` }
    if (filterConf === 'low') return { title: 'No low-confidence items', body: 'Excellent — no low-confidence detections to review.' }
    if (filterStatus === 'pending') return { title: 'No pending items', body: 'All items matching these filters have been reviewed.' }
    return { title: 'No matching items', body: 'No instruments match the current filters.' }
  }, [instruments.length, search, filterConf, filterStatus])

  // ── Render guards ───────────────────────────────────────────────────────────
  if (!project) {
    return (
      <NoProjectState
        icon={<ClipboardCheck size={42} strokeWidth={1.3} />} iconOpacity={0.3}
        title="No project selected" body="Pick a project from the sidebar to review its instruments."
      />
    )
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', gap: 12 }}>
          {[1,2,3,4].map(i => <div key={i} className="skeleton" style={{ flex: 1, height: 80, borderRadius: 8 }} />)}
        </div>
        <div className="skeleton" style={{ height: 10, borderRadius: 6 }} />
        <div style={{ display: 'flex', gap: 10 }}>
          <div className="skeleton" style={{ width: 200, height: 34, borderRadius: 8 }} />
          <div className="skeleton" style={{ flex: 1, height: 34, borderRadius: 8 }} />
        </div>
        <div className="skeleton" style={{ height: 400, borderRadius: 8 }} />
      </div>
    )
  }

  if (error) return <ErrorBanner message={error} />

  // ── Main render ─────────────────────────────────────────────────────────────
  return (
    <>
      <ReviewStats
        instrumentCount={instruments.length}
        equipmentCount={equipment.length}
        accepted={accepted}
        rejected={rejected}
        pending={pending}
        avgConf={avgConf}
        showingCount={filtered.length}
        highConf={highConf}
        medConf={medConf}
        lowConf={lowConf}
        completionPct={completionPct}
        hasConfidence={hasConfidence}
      />

      <ReviewToolbar
        bulkLoading={bulkLoading}
        filteredCount={filtered.length}
        selectedCount={selected.size}
        accepted={accepted}
        instrumentCount={instruments.length}
        onSelectAllFiltered={toggleAll}
        onClearSelection={clearSelection}
        onAcceptSelected={() => setConfirm({ action: 'accepted', tags: [...selected] })}
        onRejectSelected={() => setConfirm({ action: 'rejected', tags: [...selected] })}
      />

      <ReviewFilterBar
        search={search} setSearch={setSearch}
        filterStatus={filterStatus} setFilterStatus={setFilterStatus}
        filterConf={filterConf} setFilterConf={setFilterConf}
        filterType={filterType} setFilterType={setFilterType}
        typeOptions={typeOptions}
        showConfidence={hasConfidence}
      />

      <InstrumentTable
        filtered={filtered}
        eff={eff}
        editCell={editCell}
        editValue={editValue}
        setEditValue={setEditValue}
        editRef={editRef}
        startEdit={startEdit}
        commitEdit={commitEdit}
        handleEditKey={handleEditKey}
        onReview={handleReview}
        selected={selected}
        onToggleSelect={toggleSelect}
        allFilteredSelected={allFilteredSelected}
        onToggleAll={toggleAll}
        emptyTitle={emptyState.title}
        emptyBody={emptyState.body}
        onRowFocus={onRowFocus}
        showConfidence={hasConfidence}
        showDrawing={hasDrawing}
        showArea={hasArea}
      />

      {confirm && (
        <ConfirmModal
          title={`${confirm.action === 'accepted' ? 'Accept' : 'Reject'} ${confirm.tags.length} item${confirm.tags.length === 1 ? '' : 's'}?`}
          confirmLabel={bulkLoading ? 'Applying…' : (confirm.action === 'accepted' ? 'Accept' : 'Reject')}
          confirmDisabled={bulkLoading}
          confirmDanger={confirm.action === 'rejected'}
          onConfirm={runBulk}
          onCancel={() => setConfirm(null)}
          body={
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              This will mark {confirm.tags.length} selected instrument{confirm.tags.length === 1 ? '' : 's'} as{' '}
              <strong style={{ color: confirm.action === 'accepted' ? 'var(--success)' : 'var(--danger)' }}>{confirm.action}</strong>.
              You can change individual items afterward.
            </div>
          }
        />
      )}
    </>
  )
}
