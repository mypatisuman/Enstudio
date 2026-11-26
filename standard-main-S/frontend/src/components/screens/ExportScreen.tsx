import { useState, useEffect, useCallback } from 'react'
import * as exportService from '../../services/export'
import { getGraph } from '../../services/invoke/graph'
import { extractedLayout, normalizedPointToPixel } from '../canvas/extractedLayout'
import { nodeSize } from '../../features/canvas/utils/layout'
import { sanitizeWaypoints, buildRoute } from '../../features/canvas/utils/waypoints'
import { DEFAULT_PID_CANVAS } from './CanvasScreen'
import { save } from '@tauri-apps/plugin-dialog'
import type { Project } from '../../App'
import { NoProjectState } from '../../shared/components/empty/NoProjectState'
import { CARDS, type CardDef } from '../../features/export/constants'
import { ExportCard } from '../../features/export/components/ExportCard'
import { ExportPreviewModal, type ViewFile } from '../../features/export/components/ExportPreviewModal'

interface Props { project: Project | null }

export default function ExportScreen({ project }: Props) {
  const [existingFiles, setExistingFiles] = useState<string[]>([])
  const [loading,  setLoading]  = useState<Record<string, boolean>>({})
  const [errors,   setErrors]   = useState<Record<string, string>>({})
  const [success,  setSuccess]  = useState<Record<string, string>>({})

  // SVG state (generated on demand, not auto-loaded)
  const [svgContent,    setSvgContent]    = useState<string>('')
  const [svgGenerating, setSvgGenerating] = useState(false)
  const [svgError,      setSvgError]      = useState('')

  // DXF state (generated on demand, not auto-loaded) — same pattern as SVG
  const [dxfContent,    setDxfContent]    = useState<string>('')
  const [dxfGenerating, setDxfGenerating] = useState(false)
  const [dxfError,      setDxfError]      = useState('')

  // View modal state
  const [viewFile,    setViewFile]    = useState<ViewFile | null>(null)
  const [viewLoading, setViewLoading] = useState<Record<string, boolean>>({})
  const [svgZoom,     setSvgZoom]     = useState(1)

  // Positions AND pipe routes for the SVG export, computed with the Canvas's
  // OWN engines — extractedLayout (its default layout mode) and buildRoute —
  // rather than a Python port that would drift from the screen.
  //
  // This is what makes the exported drawing match the Canvas. buildRoute in
  // particular is not reproducible by re-deriving routes: it treats the stored
  // waypoints as INTERIOR bends, clips the ones swallowed by a symbol box,
  // drops single-bend jog artifacts, and picks each handle from the direction
  // of the surviving route. Re-routing independently gave visibly different
  // pipe runs for the same data.
  //
  // Any failure returns undefined and the renderer falls back to its own
  // layout and routing — an export is never blocked on this.
  const canvasLayout = useCallback(async (pid: string): Promise<string | undefined> => {
    try {
      const graph = await getGraph(pid)
      if (!graph.nodes.length) return undefined

      const cw = DEFAULT_PID_CANVAS.w
      const ch = DEFAULT_PID_CANVAS.h
      const plNodes = graph.nodes.map(n => ({
        id: n.id, label: n.label, kind: n.kind, type: n.type,
        x: n.x, y: n.y, drawing: n.drawing,
        equipment_ref: n.equipment_ref,
        page_w: n.page_w, page_h: n.page_h,
      }))
      const { pos, sizes } = extractedLayout(
        plNodes,
        n => nodeSize(n.type ?? n.kind, n.label ?? '', 0),
        cw, ch,
        graph.edges.map(e => ({ source: e.source, target: e.target })),
      )
      if (!pos.size) return undefined

      const positions: Record<string, [number, number]> = {}
      pos.forEach((p, id) => { positions[id] = [p.x, p.y] })

      const sizeOf = (id: string) => {
        const s = sizes?.get(id)
        if (s) return s
        const n = plNodes.find(v => v.id === id)
        return n ? nodeSize(n.type ?? n.kind, n.label ?? '', 0) : { w: 80, h: 50 }
      }
      const boxOf = (id: string) => {
        const p = pos.get(id); if (!p) return null
        const { w, h } = sizeOf(id)
        return { x1: p.x, y1: p.y, x2: p.x + w, y2: p.y + h }
      }
      const inlinePorts = (id: string) => {
        const n = plNodes.find(v => v.id === id)
        return String(n?.type ?? n?.kind ?? '').toLowerCase().includes('valve')
      }

      const routes: { from: string; to: string; pts: [number, number][] }[] = []
      for (const e of graph.edges) {
        const interior = sanitizeWaypoints(e.waypoints)
        if (!interior.length) continue
        const sBox = boxOf(e.source), tBox = boxOf(e.target)
        if (!sBox || !tBox) continue
        const built = buildRoute(
          interior.map(p => normalizedPointToPixel(p.x, p.y, cw, ch)),
          sBox, tBox,
          { srcHorizontal: inlinePorts(e.source), tgtHorizontal: inlinePorts(e.target) },
        )
        if (built?.pts?.length) {
          // buildRoute returns the INTERIOR bends plus the handle each end
          // anchors to; React Flow supplies the anchor points from those
          // handles. The exporter draws a plain polyline, so resolve the
          // handles to points here — otherwise the pipe would start and end
          // at its first and last bend, floating clear of both symbols.
          const anchor = (box: { x1: number; y1: number; x2: number; y2: number },
                          handle: string) => {
            const face = handle.slice(-1)
            const cx = (box.x1 + box.x2) / 2, cy = (box.y1 + box.y2) / 2
            if (face === 'l') return [box.x1, cy] as [number, number]
            if (face === 'r') return [box.x2, cy] as [number, number]
            if (face === 't') return [cx, box.y1] as [number, number]
            return [cx, box.y2] as [number, number]
          }
          routes.push({
            from: e.source, to: e.target,
            pts: [
              anchor(sBox, built.sourceHandle),
              ...built.pts.map(p => [p.x, p.y] as [number, number]),
              anchor(tBox, built.targetHandle),
            ],
          })
        }
      }

      return JSON.stringify({ positions, routes })
    } catch {
      return undefined
    }
  }, [])

  const refreshFiles = useCallback(async (pid: string) => {
    const files = await exportService.getExportStatus(pid)
    setExistingFiles(files)
  }, [])

  // Reload keyed by project id (not the project object) — the object gets a
  // new reference whenever its stats refresh (e.g. Sidebar's loadProjects
  // picking up updated counts) without a new project actually being
  // selected; tracking the id keeps this from re-firing on every such
  // refresh. Same pattern repeated across every screen keyed by project.
  useEffect(() => {
    if (!project) return
    setExistingFiles([])
    setErrors({})
    setSuccess({})
    setSvgContent('')
    setSvgError('')
    setDxfContent('')
    setDxfError('')
    refreshFiles(project.id)
  }, [project?.id, refreshFiles])

  // Preview the ISA-5.1 vector SVG from the Studio server — never writes a
  // file to disk. Preview and export call the same source, so what's shown is
  // what gets saved.
  const previewSvg = useCallback(async (pid: string) => {
    if (svgContent) { setViewFile({ name: `${pid}_pid.svg`, content: svgContent }); return }
    if (!project) return
    setSvgGenerating(true)
    setSvgError('')
    try {
      const content = await exportService.fetchSvgExport(
        project.id, 'control', 'light', await canvasLayout(project.id))
      setSvgContent(content)
      setViewFile({ name: `${pid}_pid.svg`, content })
    } catch (e: unknown) {
      setSvgError(typeof e === 'string' ? e : e instanceof Error ? e.message : String(e))
    } finally {
      setSvgGenerating(false)
    }
  }, [svgContent, project, canvasLayout])

  // Preview DXF — generate content in memory only, never writes a file to disk.
  const previewDxf = useCallback(async (pid: string) => {
    if (dxfContent) { setViewFile({ name: `${pid}_pid.dxf`, content: dxfContent }); return }
    setDxfGenerating(true)
    setDxfError('')
    try {
      const content = await exportService.previewDxfNative(pid)
      setDxfContent(content)
      setViewFile({ name: `${pid}_pid.dxf`, content })
    } catch (e: unknown) {
      setDxfError(typeof e === 'string' ? e : String(e))
    } finally {
      setDxfGenerating(false)
    }
  }, [dxfContent])

  const handleExport = async (card: CardDef): Promise<string | null> => {
    if (!project) return null
    setLoading(prev => ({ ...prev, [card.key]: true }))
    setErrors(prev => ({ ...prev, [card.key]: '' }))

    try {
      let content = ''
      let defaultFileName = ''

      if (card.key === 'svg') {
        // ISA-5.1 vector SVG from the Studio server. This used to capture the
        // live Canvas via html-to-image, which produces a <foreignObject>
        // holding a copy of the DOM — valid SVG, identical to the Canvas, but
        // Inkscape/Illustrator/CAD render it blank and none of it is editable
        // geometry. The server draws real <path>/<circle>/<text> symbols.
        content = svgContent || await exportService.fetchSvgExport(
          project.id, 'control', 'light', await canvasLayout(project.id))
        setSvgContent(content)
        defaultFileName = `${project.id}_pid.svg`
      } else if (card.key === 'dxf') {
        await exportService.exportDxfNative(project.id)
        content = await exportService.getExportContent(project.id, `${project.id}_pid.dxf`)
        setDxfContent(content)
        defaultFileName = `${project.id}_pid.dxf`
      } else if (card.key === 'connectivity' || card.key === 'connectivity_hierarchy') {
        const schema = card.key === 'connectivity' ? '2.0.0' : '2.1.0'
        content = await exportService.previewConnectivity(project.id, schema)
        defaultFileName = card.key === 'connectivity'
          ? `${project.id}_connectivity.json`
          : `${project.id}_connectivity_2_1_0.json`
      } else {
        content = await exportService.previewExport(project.id, card.key)
        if (card.key === 'vids') defaultFileName = `${project.id}_vids.yaml`
        else if (card.key === 'ympl') defaultFileName = `${project.id}.ympl`
        else if (card.key === 'markdown') defaultFileName = `${project.id}_report.md`
        else if (card.key === 'mermaid') defaultFileName = `${project.id}_pid.mmd`
      }

      const savePath = await save({ defaultPath: defaultFileName, title: `Save ${card.title}` })
      if (!savePath) return null

      await exportService.saveExportToPath(content, savePath)
      setSuccess(prev => ({ ...prev, [card.key]: savePath }))
      await refreshFiles(project.id)
      return savePath
    } catch (e: unknown) {
      const msg = typeof e === 'string' ? e : JSON.stringify(e)
      setErrors(prev => ({ ...prev, [card.key]: msg }))
      return null
    } finally {
      setLoading(prev => ({ ...prev, [card.key]: false }))
    }
  }

  if (!project) {
    return (
      <NoProjectState icon="↑" title="No project selected" body="Pick a project from the sidebar to export." />
    )
  }

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .svg-preview-wrapper svg { width: 100%; height: 100%; }
      `}</style>

      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="section-heading" style={{ margin: 0 }}>Export — {project.name}</span>
      </div>

      <div className="card-grid-2x2">
        {CARDS.map(card => {
          const existingFile = card.matchFn(existingFiles)
          const isLoading    = !!loading[card.key]
          const errMsg       = errors[card.key] || ''
          const successFile  = success[card.key] || ''
          const isSvg        = card.key === 'svg'
          const isDxf        = card.key === 'dxf'
          const isNative     = isSvg || isDxf
          const nativeGenerating = isSvg ? svgGenerating : dxfGenerating
          const nativeError      = isSvg ? svgError      : dxfError
          const previewNative    = isSvg ? previewSvg    : previewDxf

          return (
            <ExportCard
              key={card.key}
              card={card}
              existingFile={existingFile}
              isLoading={isLoading}
              errMsg={errMsg}
              successFile={successFile}
              isNative={isNative}
              nativeGenerating={nativeGenerating}
              nativeError={nativeError}
              viewLoading={viewLoading[card.key] ?? false}
              onPreviewNative={() => previewNative(project.id)}
              onPreviewGeneric={async () => {
                try {
                  setViewLoading(prev => ({ ...prev, [card.key]: true }))
                  const content = await exportService.previewExport(project.id, card.key)
                  setViewFile({ name: `${card.title} (preview)`, content })
                } catch (e) {
                  alert(`Preview failed: ${e}`)
                } finally {
                  setViewLoading(prev => ({ ...prev, [card.key]: false }))
                }
              }}
              onExport={() => handleExport(card)}
            />
          )
        })}
      </div>

      {/* Full-screen view modal */}
      {viewFile && (
        <ExportPreviewModal
          viewFile={viewFile} setViewFile={setViewFile}
          svgZoom={svgZoom} setSvgZoom={setSvgZoom}
        />
      )}
    </>
  )
}
