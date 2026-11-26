import { useState, useEffect, useCallback } from 'react'
import type { Project, Screen } from '../../App'
import { getInstruments, getGaps } from '../../services/review'
import { getExportStatus } from '../../services/export'
import { getSources } from '../../services/ingest'
import { getProjectStats } from '../../services/project'
import { exportFilename } from '../../domain/export/filenames'
import { ErrorBanner } from '../../shared/components/error/ErrorBanner'
import type { HomeData } from '../../features/home/types'
import { SkeletonRow } from '../../features/home/components/SkeletonRow'
import { Onboarding } from '../../features/home/components/Onboarding'
import { ProjectHeader } from '../../features/home/components/ProjectHeader'
import { HomeStats } from '../../features/home/components/HomeStats'
import { FeatureGrid } from '../../features/home/components/FeatureGrid'

interface Props {
  project: Project | null
  setActiveScreen: (s: Screen) => void
  setActiveProject: (p: Project | null) => void
}

export default function HomeScreen({ project, setActiveScreen, setActiveProject }: Props) {
  const [data, setData] = useState<HomeData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (pid: string) => {
    setLoading(true); setError(''); setData(null)
    try {
      const [instruments, gaps, exportFiles, sources, stats] = await Promise.all([
        getInstruments(pid),
        getGaps(pid),
        getExportStatus(pid),
        getSources(pid),
        getProjectStats(pid),
      ])
      setData({ instruments, gaps, exportFiles, sources, stats })
    } catch (e: unknown) {
      setError(typeof e === 'string' ? e : JSON.stringify(e))
    } finally {
      setLoading(false)
    }
  }, [])

  // Reload keyed by project id, not the project object — see ExportScreen's
  // load effect for the full rationale (same pattern across every screen
  // keyed by project).
  useEffect(() => {
    if (project) load(project.id)
  }, [project?.id, load])

  if (!project) return <Onboarding setActiveScreen={setActiveScreen} setActiveProject={setActiveProject} />
  if (loading) return <SkeletonRow />

  if (error) {
    return <ErrorBanner message={error} padding="20px 24px" />
  }

  // ── Derived stats ──────────────────────────────────────────────────────────

  const instr = data?.instruments ?? []
  const accepted = instr.filter(i => i.review_status === 'accepted').length
  const rejected = instr.filter(i => i.review_status === 'rejected').length
  const pending = instr.filter(i => i.review_status === 'pending').length
  const totalI = instr.length

  const orphans = data?.gaps.orphans.length ?? 0
  const lowConf = data?.gaps.low_confidence.length ?? 0
  const lonelyEquip = data?.gaps.lonely_equipment.length ?? 0

  const pid = project.id
  const exportedSet = new Set(data?.exportFiles ?? [])
  const hasVids = exportedSet.has(exportFilename('vids', pid))
  const hasYmpl = exportedSet.has(exportFilename('ympl', pid))
  const hasMd = exportedSet.has(exportFilename('markdown', pid))
  const hasMermaid = exportedSet.has(exportFilename('mermaid', pid))
  const hasSvg = exportedSet.has(exportFilename('svg', pid)) || exportedSet.has(`${pid}.svg`)
  const hasDxf = exportedSet.has(exportFilename('dxf', pid))

  const sources = data?.sources ?? []
  const sourceCount = sources.length
  const lastExtracted = sources.length > 0 ? sources[0].uploaded?.slice(0, 10) ?? '' : ''

  const nodeCount = data?.stats.node_count ?? 0
  const edgeCount = data?.stats.edge_count ?? 0
  const ratio = nodeCount > 0 ? edgeCount / nodeCount : 0
  const qualityPct = Math.round(Math.min(ratio / 1.2, 1) * 100)
  const qualityColor = ratio >= 0.7 ? 'var(--success)' : ratio >= 0.35 ? 'var(--warning)' : 'var(--danger)'

  const reviewPct = totalI > 0 ? Math.round((accepted / totalI) * 100) : 0
  const reviewColor = reviewPct >= 80 ? 'var(--success)' : reviewPct >= 40 ? '#eab308' : 'var(--accent)'

  const exportsReady = [hasVids, hasYmpl, hasMd, hasMermaid, hasSvg, hasDxf].filter(Boolean).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      <ProjectHeader project={project} nodeCount={nodeCount} edgeCount={edgeCount} lastExtracted={lastExtracted} />

      <HomeStats
        totalI={totalI} accepted={accepted} rejected={rejected} pending={pending}
        drawings={project.drawings}
        qualityPct={qualityPct} ratio={ratio} exportsReady={exportsReady}
        reviewPct={reviewPct} reviewColor={reviewColor} qualityColor={qualityColor}
      />

      <FeatureGrid
        project={project} setActiveScreen={setActiveScreen}
        sourceCount={sourceCount} lastExtracted={lastExtracted} sources={sources}
        totalI={totalI} accepted={accepted} rejected={rejected} pending={pending}
        edgeCount={edgeCount} nodeCount={nodeCount}
        orphans={orphans} lowConf={lowConf} lonelyEquip={lonelyEquip}
        hasVids={hasVids} hasYmpl={hasYmpl} hasMd={hasMd} hasMermaid={hasMermaid}
      />
    </div>
  )
}
