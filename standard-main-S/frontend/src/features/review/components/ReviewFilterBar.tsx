import { FilterSelect } from '../../../shared/components/select/FilterSelect'

const STATUSES = ['all', 'pending', 'accepted', 'rejected'] as const
const CONF = ['all', 'high', 'medium', 'low'] as const

export function ReviewFilterBar({
  search, setSearch,
  filterStatus, setFilterStatus,
  filterConf, setFilterConf,
  filterType, setFilterType,
  typeOptions,
  showConfidence,
}: {
  search: string
  setSearch: (v: string) => void
  filterStatus: string
  setFilterStatus: (v: typeof STATUSES[number]) => void
  filterConf: string
  setFilterConf: (v: typeof CONF[number]) => void
  filterType: string
  setFilterType: (v: string) => void
  typeOptions: string[]
  showConfidence: boolean
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
      {/* Search + status side by side */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          type="text"
          placeholder="Search tag, type, drawing, equipment ref…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            flex: 1, minWidth: 0, background: 'var(--bg-secondary)',
            border: '1px solid var(--border)', borderRadius: 6,
            color: 'var(--text-primary)', font: 'inherit',
            fontSize: 13, padding: '7px 12px', outline: 'none',
          }}
        />

        {/* Review status — segmented control */}
        <div className="rv-seg" role="group" aria-label="Filter by review status">
          {STATUSES.map(s => (
            <button
              key={s}
              className={`rv-seg__btn${filterStatus === s ? ' active' : ''}`}
              onClick={() => setFilterStatus(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Confidence — only when the data model actually carries it */}
      {showConfidence && (
        <FilterSelect
          style={{ width: '100%' }}
          value={filterConf} onChange={v => setFilterConf(v as typeof CONF[number])}
          ariaLabel="Filter by confidence"
          options={[
            { value: 'all', label: 'All confidence' },
            { value: 'high', label: 'High (≥85%)' },
            { value: 'medium', label: 'Medium (70–84%)' },
            { value: 'low', label: 'Low (<70%)' },
          ]}
        />
      )}

      {/* Type — options derived from the actual instrument data */}
      <FilterSelect
        style={{ width: '100%' }}
        value={filterType} onChange={setFilterType}
        ariaLabel="Filter by type"
        options={[{ value: 'all', label: 'All types' }, ...typeOptions.map(t => ({ value: t, label: t }))]}
      />
    </div>
  )
}
