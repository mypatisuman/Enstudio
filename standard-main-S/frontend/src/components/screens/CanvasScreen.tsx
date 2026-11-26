import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
// Aliased: this file already uses `onGraphChanged` as a child-component prop.
import { onGraphChanged as subscribeGraphChanged, onHierarchyFilter } from '../../shared/graphEvents'
import * as graphService from '../../services/graph'
import * as canvasService from '../../services/canvas'
import {
  ReactFlow, Background, MiniMap, ConnectionMode,
  ReactFlowProvider, useReactFlow,
  useNodesState, useEdgesState, addEdge, reconnectEdge,
  type Node, type Edge, type OnSelectionChangeParams, type Connection,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { Project } from '../../App'
import {
  NODE_TYPES,
  equipColors, instrColors, OFFPAGE_C,
  getNodeType, getNodeSize,
} from '../canvas/ISANodes'
import { Theme } from '../canvas/theme'
import DrawPalette from '../canvas/DrawPalette'
import { processLayout, canUseProcessLayout, plantLayout, type AreaGroup } from '../canvas/processLayout'
import {
  extractedLayout, pixelToNormalized, normalizedPointToPixel, pixelPointToNormalized,
} from '../canvas/extractedLayout'
import { useMountTransition } from '../../useMountTransition'
import { isInstrument, isOffPage } from '../../domain/isa/instrument'
import { computeOffPageDirections } from '../../domain/canvas/offPageDirection'
import { isSoftTag, buildSoftGroups } from '../../domain/graph/softGroups'
import type { GraphNode, GraphData, CData } from '../../features/canvas/types'
import { normalizeGraph, nodeSize, buildAssocEdges, connectedSet, dagreLayout } from '../../features/canvas/utils/layout'
import {
  edgeStyle, edgeFlowType, trustStyle, flowArrow, FLOW_ARROW, BendEdgeContext, pickHandles,
} from '../../features/canvas/utils/edgeHelpers'
import { BendableEdge, WaypointEdge } from '../../features/canvas/components/edges'
import { sanitizeWaypoints, routeKindFor, edgeTrust, buildRoute } from '../../features/canvas/utils/waypoints'
import { checkGraphIntegrity, describeIntegrity, makeEdgeId } from '../../features/canvas/utils/graphIntegrity'
import { FitViewButton } from '../../features/canvas/components/FitViewButton'
import { OrphanStrip } from '../../features/canvas/components/OrphanStrip'
import { SidePanel } from '../../features/canvas/components/SidePanel'
import { DrawSidePanel } from '../../features/canvas/components/DrawSidePanel'
import { TagInputModal } from '../../features/canvas/components/TagInputModal'
import { PidBgNode } from '../../features/canvas/components/PidBgNode'
import { LineLegend } from '../../features/canvas/components/LineLegend'
import { CanvasSearch } from '../../features/canvas/components/CanvasSearch'
import { takePendingFocus } from '../../features/canvas/focusBus'
import { Search } from 'lucide-react'

const EDGE_TYPES_MAP = { bendable: BendableEdge, waypoint: WaypointEdge }
// NODE_TYPES + the background node type (merged once at module load).
const NODE_TYPES_WITH_BG = { ...NODE_TYPES, pidbg: PidBgNode } as typeof NODE_TYPES

export const DEFAULT_PID_CANVAS = { w: 3000, h: 2200 }

// ── Types ─────────────────────────────────────────────────────────────────────

interface Props { project: Project | null }

// ── CanvasFlow: inner component with all React Flow hooks ─────────────────────

interface CanvasFlowProps {
  rfNodes: Node<CData>[]
  rfEdges: Edge[]
  drawMode: boolean
  project: Project | null
  selected: CData | null
  onSelect: (n: CData | null) => void
  placingKind: string | null
  onPlacingDone: () => void
  usePidCoords: boolean
  pidCanvasW: number
  pidCanvasH: number
  pidBgUrl: string | null
  showPidBg: boolean
  setFocusNodeId: (id: string | null) => void
  onGraphChanged: () => void
  pushUndo: (undo: () => Promise<void>, redo?: () => Promise<void>) => void
  undo: () => void
  redo: () => void
}

function CanvasFlow({
  rfNodes, rfEdges, drawMode, project, selected, onSelect, placingKind, onPlacingDone,
  usePidCoords, pidCanvasW, pidCanvasH, pidBgUrl, showPidBg,
  setFocusNodeId, onGraphChanged, pushUndo, undo, redo,
}: CanvasFlowProps) {
  const { screenToFlowPosition, fitView, setCenter } = useReactFlow()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CData>>(rfNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(rfEdges)
  const [drop, setDrop] = useState<{ kind: string; pos: { x: number; y: number } } | null>(null)

  // Stable refs to avoid stale closures in event listeners
  const selRef = useRef(selected)
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  useEffect(() => { selRef.current = selected }, [selected])
  useEffect(() => { nodesRef.current = nodes }, [nodes])
  useEffect(() => { edgesRef.current = edges }, [edges])

  // Sync local state whenever parent rfNodes/rfEdges changes (reload, filter).
  // A background reload (from an earlier, unrelated action) can land right
  // after the user clicks to select something — carry the current selection
  // over by node id so it isn't silently cleared out from under them (which
  // made Delete look like it did nothing: nothing was selected any more).
  useEffect(() => {
    setNodes(prev => {
      const selectedIds = new Set(prev.filter(n => n.selected).map(n => n.id))
      return selectedIds.size ? rfNodes.map(n => selectedIds.has(n.id) ? { ...n, selected: true } : n) : rfNodes
    })
  }, [rfNodes, setNodes])
  useEffect(() => { setEdges(rfEdges) }, [rfEdges, setEdges])

  // Auto-fit after every layout update (view mode only).
  // `drawMode` is deliberately NOT a dependency — this should only re-fit
  // when the layout data itself changes, not merely on a View/Draw toggle
  // (which would introduce a visible re-zoom on every mode switch that
  // doesn't happen today). `fitView` (from useReactFlow) is the standard
  // React Flow omission — it's stable across renders.
  useEffect(() => {
    if (drawMode || !rfNodes.length) return
    const t = setTimeout(() => fitView({ padding: 0.15 }), 100)
    return () => clearTimeout(t)
  }, [rfNodes]) // fitView

  // Re-fit when P&ID background is toggled on — include the image in the
  // viewport. Same `drawMode`/`fitView` omission rationale as above.
  useEffect(() => {
    if (drawMode) return
    const t = setTimeout(() => fitView({ padding: 0.05 }), 50)
    return () => clearTimeout(t)
  }, [showPidBg, pidBgUrl]) // fitView

  // ── Delete key ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!drawMode) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { onPlacingDone(); return }
      const t = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return
      // Ctrl/Cmd+Z = undo; Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y = redo.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault(); if (e.shiftKey) redo(); else undo(); return
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return }
      // Align selected symbols to a shared centerline (H = one horizontal line,
      // V = one vertical line) — like a design tool's "align centers". Snaps the
      // minor axis to the group's average center so a pipe run reads straight.
      if ((e.key === 'h' || e.key === 'H' || e.key === 'v' || e.key === 'V') && project) {
        const sel = nodesRef.current.filter(n => n.selected && n.type !== 'pidbg')
        if (sel.length < 2) return
        e.preventDefault()
        const horizontal = e.key.toLowerCase() === 'h'
        const info = sel.map(n => {
          const d = n.data as CData
          const { w, h } = nodeSize(d.kind, d.label, d.softChildren?.length ?? 0)
          return { id: n.id, w, h, x: n.position.x, y: n.position.y }
        })
        // Target line = average of the selected centers on the axis being snapped.
        const target = horizontal
          ? info.reduce((s, i) => s + i.y + i.h / 2, 0) / info.length
          : info.reduce((s, i) => s + i.x + i.w / 2, 0) / info.length
        const nextXY = new Map(info.map(i => [i.id,
        horizontal ? { x: i.x, y: target - i.h / 2 } : { x: target - i.w / 2, y: i.y }]))
        setNodes(prev => prev.map(n => nextXY.has(n.id) ? { ...n, position: nextXY.get(n.id)! } : n))
        for (const i of info) {
          const p = nextXY.get(i.id)!
          let x = p.x, y = p.y
          if (usePidCoords) { const nrm = pixelToNormalized(x, y, i.w, i.h, pidCanvasW, pidCanvasH); x = nrm.x; y = nrm.y }
          graphService.updateNodePosition(project.id, i.id, x, y).catch(console.error)
        }
        onGraphChanged()
        // Undo restores every symbol's pre-align position; redo re-applies the
        // aligned positions.
        pushUndo(async () => {
          for (const i of info) {
            let x = i.x, y = i.y
            if (usePidCoords) { const nrm = pixelToNormalized(i.x, i.y, i.w, i.h, pidCanvasW, pidCanvasH); x = nrm.x; y = nrm.y }
            await graphService.updateNodePosition(project.id, i.id, x, y)
          }
        }, async () => {
          for (const i of info) {
            const p = nextXY.get(i.id)!
            let x = p.x, y = p.y
            if (usePidCoords) { const nrm = pixelToNormalized(p.x, p.y, i.w, i.h, pidCanvasW, pidCanvasH); x = nrm.x; y = nrm.y }
            await graphService.updateNodePosition(project.id, i.id, x, y)
          }
        })
        return
      }
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      if (!project) return
      // Selected pipe(s) → delete the edge(s), both locally and in the DB.
      // Deletes by the edge's own source/target node ids — not by label —
      // since junction dots are frequently unlabeled/duplicate-labeled and a
      // label lookup can silently resolve to the wrong node.
      const selEdges = edgesRef.current.filter(ed => ed.selected)
      if (selEdges.length) {
        const ids = new Set(selEdges.map(ed => ed.id))
        setEdges(prev => prev.filter(ed => !ids.has(ed.id)))
        for (const ed of selEdges) {
          graphService.deleteEdgeById(project.id, ed.source, ed.target)
            .catch(e => console.error(`[delete] delete_edge_by_id FAILED ${ed.source}->${ed.target}`, e))
            .finally(onGraphChanged)
          const edKind = String((ed.data as Record<string, unknown> | undefined)?.kind ?? 'stream')
          pushUndo(
            () => graphService.insertEdgeById(project.id, ed.source, ed.target, edKind),
            () => graphService.deleteEdgeById(project.id, ed.source, ed.target),
          )
        }
        return
      }
      // Selected symbol(s) — supports a box/shift multi-select, not just one.
      const selNodes = nodesRef.current.filter(n => n.selected)
      const targets = selNodes.length ? selNodes
        : (() => {
          const sel = selRef.current
          if (!sel) return []
          const node = nodesRef.current.find(n => (n.data as CData).label === String(sel.label))
          return node ? [node] : []
        })()
      if (!targets.length) return
      const ids = new Set(targets.map(n => n.id))
      setNodes(prev => prev.filter(n => !ids.has(n.id)))
      setEdges(prev => prev.filter(e => !ids.has(e.source) && !ids.has(e.target)))
      onSelect(null)
      for (const node of targets) {
        graphService.deleteNode(project.id, node.id)
          .catch(e => console.error(`[delete] delete_node FAILED id=${node.id}`, e))
          .finally(onGraphChanged)
      }
    }
    // Capture phase: React Flow attaches its own keydown handling internally
    // and can call stopPropagation (e.g. to block the browser's default
    // Backspace-navigates-back) — a bubble-phase listener here can end up
    // never seeing the event at all. Capture runs before that, so we always do.
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [drawMode, project, onSelect, onPlacingDone, onGraphChanged, pushUndo, undo, redo,
    usePidCoords, pidCanvasW, pidCanvasH, setNodes, setEdges])

  const dragStartNodeRef = useRef<string | null>(null)

  // Shared by drag-to-connect (onConnect) and click-to-connect (onNodeClick
  // in link mode) — both just need a resolved from/to node id pair.
  const connectNodes = useCallback((fromId: string, toId: string) => {
    if (!project || fromId === toId) return
    const src = nodesRef.current.find(n => n.id === fromId)
    const tgt = nodesRef.current.find(n => n.id === toId)
    if (!src || !tgt) return
    const kind = isInstrument(String(src.data.type ?? src.data.kind)) ? 'signal' : 'stream'
    const handles = pickHandles(nodesRef.current, fromId, toId)
    const routeVertical = handles.sourceHandle === 'st' || handles.sourceHandle === 'sb'
    const newEdge: Edge = {
      id: `d${Date.now()}`,
      source: fromId, target: toId,
      ...handles,
      type: edgeFlowType(kind), style: edgeStyle(kind),
      data: { kind, routeVertical },
      markerEnd: FLOW_ARROW,
    }
    setEdges(prev => addEdge(newEdge, prev))
    // By id, not tag — junction dots are frequently unlabeled and a tag-keyed
    // insert silently skips the whole edge when either label is empty.
    graphService.insertEdgeById(project.id, fromId, toId, kind)
      .catch(console.error).finally(onGraphChanged)
    pushUndo(
      () => graphService.deleteEdgeById(project.id, fromId, toId),
      () => graphService.insertEdgeById(project.id, fromId, toId, kind),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, onGraphChanged, pushUndo])

  const onConnect = useCallback((conn: Connection) => {
    const startNodeId = dragStartNodeRef.current
    dragStartNodeRef.current = null

    // React Flow normalizes connections so they always flow from a Source handle
    // to a Target handle. If the user grabs a Target handle and drops on a Source,
    // React Flow silently swaps conn.source and conn.target. We restore the exact
    // physical drag direction using the node we captured in onConnectStart.
    const isReversed = startNodeId && startNodeId !== conn.source
    const fromId = isReversed ? conn.target! : conn.source!
    const toId   = isReversed ? conn.source! : conn.target!
    connectNodes(fromId, toId)
  }, [connectNodes])

  // Find which rendered edge (if any) sits under a screen point — used to tap
  // a new branch into an existing pipe instead of just dropping in space.
  // Reads the actual DOM (rather than recomputing edge geometry ourselves)
  // since step-routed edges' paths are computed internally by React Flow.
  function edgeIdAtPoint(clientX: number, clientY: number): string | null {
    const el = document.elementFromPoint(clientX, clientY)
    const wrapper = el?.closest('.react-flow__edge') as HTMLElement | null
    return wrapper?.getAttribute('data-id') ?? null
  }

  // ── Drop a connection on empty space or an existing pipe ────────────────────
  // On empty space: create a junction there and link the source to it.
  // On an existing pipe: tap into it — splice a junction in, replacing the one
  // tapped edge with two segments (source→junction, junction→target) plus the
  // new branch, same as a real P&ID tee.
  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, connState: { toNode?: unknown; fromNode?: { id: string } | null }) => {
    if (!project || connState.toNode) return   // dropped on a node → onConnect handled it
    const fromId = connState.fromNode?.id
    if (!fromId) return
    const src = nodesRef.current.find(n => n.id === fromId)
    if (!src) return
    const pt = 'changedTouches' in event ? event.changedTouches[0] : event
    const pos = screenToFlowPosition({ x: pt.clientX, y: pt.clientY })
    const label = `jx${Date.now()}`                 // hidden — junctions render no text
    let jx = pos.x, jy = pos.y
    if (usePidCoords) { const n = pixelToNormalized(pos.x, pos.y, 16, 16, pidCanvasW, pidCanvasH); jx = n.x; jy = n.y }
    const kind = isInstrument(String(src.data.type ?? src.data.kind)) ? 'signal' : 'stream'
    const tappedId = edgeIdAtPoint(pt.clientX, pt.clientY)
    const tapped = tappedId ? edgesRef.current.find(e => e.id === tappedId) : undefined

    graphService.batchInsertJunctions(
      project.id, JSON.stringify([{ id: label, x: jx, y: jy }]),
    ).then(res => {
      const nid = res.ids[0]?.id
      if (!nid) return
      const jnode: Node<CData> = {
        id: nid, type: 'junction', position: pos, width: 16, height: 16, selectable: true,
        data: {
          label, kind: 'junction', kind_detail: 'junction', area: '', drawing: 'DRAW',
          equipment_ref: '', category: 'junction', softChildren: [], nodeId: nid
        } as CData,
      }
      setNodes(prev => [...prev, jnode])
      const allNodes = [...nodesRef.current, jnode]
      const branchHandles = pickHandles(allNodes, fromId, nid)
      const branchEdge: Edge = {
        id: `c${Date.now()}`, source: fromId, target: nid,
        ...branchHandles,
        type: edgeFlowType(kind), style: edgeStyle(kind),
        data: { kind, routeVertical: branchHandles.sourceHandle === 'st' || branchHandles.sourceHandle === 'sb' },
      }

      if (tapped) {
        // Splice: drop the tapped edge, add source→junction and junction→target
        // in its place, preserving its original kind/styling.
        const tapKind = String((tapped.data as Record<string, unknown> | undefined)?.kind ?? 'stream')
        const seg1Handles = pickHandles(allNodes, tapped.source, nid)
        const seg1: Edge = {
          id: `c${Date.now()}a`, source: tapped.source, target: nid,
          ...seg1Handles,
          type: edgeFlowType(tapKind), style: edgeStyle(tapKind),
          data: { kind: tapKind, routeVertical: seg1Handles.sourceHandle === 'st' || seg1Handles.sourceHandle === 'sb' },
        }
        const seg2Handles = pickHandles(allNodes, nid, tapped.target)
        const seg2: Edge = {
          id: `c${Date.now()}b`, source: nid, target: tapped.target,
          ...seg2Handles,
          type: edgeFlowType(tapKind), style: edgeStyle(tapKind),
          data: { kind: tapKind, routeVertical: seg2Handles.sourceHandle === 'st' || seg2Handles.sourceHandle === 'sb' },
        }
        setEdges(prev => [...prev.filter(e => e.id !== tapped.id), seg1, seg2, branchEdge])
        graphService.deleteEdgeById(project.id, tapped.source, tapped.target)
          .then(() => Promise.all([
            graphService.insertEdgeById(project.id, tapped.source, nid, tapKind),
            graphService.insertEdgeById(project.id, nid, tapped.target, tapKind),
            graphService.insertEdgeById(project.id, fromId, nid, kind),
          ]))
          .catch(console.error).finally(onGraphChanged)
        // Undo: drop the junction (cascades its 3 edges), restore the original pipe.
        pushUndo(async () => {
          await graphService.deleteNode(project.id, nid)
          await graphService.insertEdgeById(project.id, tapped.source, tapped.target, tapKind)
        })
      } else {
        setEdges(prev => addEdge(branchEdge, prev))
        graphService.insertEdgeById(project.id, fromId, nid, kind)
          .catch(console.error).finally(onGraphChanged)
        // Undo: drop the junction — delete_node cascades its one edge too.
        pushUndo(() => graphService.deleteNode(project.id, nid))
      }
    }).catch(console.error)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, screenToFlowPosition, usePidCoords, pidCanvasW, pidCanvasH, onGraphChanged, pushUndo])

  // ── Reconnect (drag an edge endpoint onto a different symbol) ────────────────
  const onReconnect = useCallback((oldEdge: Edge, conn: Connection) => {
    if (!project) return

    const startNodeId = dragStartNodeRef.current
    dragStartNodeRef.current = null
    const isReversed = startNodeId && startNodeId !== conn.source
    const trueConn = isReversed ? { ...conn, source: conn.target, target: conn.source, sourceHandle: conn.targetHandle, targetHandle: conn.sourceHandle } : conn

    const oldSrc = nodesRef.current.find(n => n.id === oldEdge.source)
    const oldTgt = nodesRef.current.find(n => n.id === oldEdge.target)
    const newSrc = nodesRef.current.find(n => n.id === trueConn.source)
    const newTgt = nodesRef.current.find(n => n.id === trueConn.target)
    if (!oldSrc || !oldTgt || !newSrc || !newTgt) return
    // Kind follows the (possibly new) source, same rule as onConnect.
    const kind = isInstrument(String(newSrc.data.type ?? newSrc.data.kind)) ? 'signal' : 'stream'
    // Drop any custom bend — the old corner no longer matches the new
    // endpoint, so fall back to the default route until re-dragged.
    setEdges(prev => reconnectEdge(
      { ...oldEdge, type: 'bendable', data: { kind }, style: edgeStyle(kind), markerEnd: FLOW_ARROW },
      trueConn, prev,
    ))
    const oldKind = String((oldEdge.data as Record<string, unknown> | undefined)?.kind ?? 'stream')
    graphService.deleteEdgeById(project.id, oldEdge.source, oldEdge.target)
      .then(() => graphService.insertEdgeById(project.id, trueConn.source, trueConn.target, kind))
      .catch(console.error).finally(onGraphChanged)
    pushUndo(async () => {
      await graphService.deleteEdgeById(project.id, trueConn.source, trueConn.target)
      await graphService.insertEdgeById(project.id, oldEdge.source, oldEdge.target, oldKind)
    }, async () => {
      await graphService.deleteEdgeById(project.id, oldEdge.source, oldEdge.target)
      await graphService.insertEdgeById(project.id, trueConn.source, trueConn.target, kind)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, onGraphChanged, pushUndo])

  // ── Drag a pipe's corner to reshape it ───────────────────────────────────────
  // Captures the bend as it was before this drag session (first move event)
  // so a commit can push an undo entry that restores exactly that.
  const bendDragOriginRef = useRef<{ edgeId: string; prevBend?: { x: number; y: number } } | null>(null)
  const onBendDrag = useCallback((edgeId: string, source: string, target: string, clientX: number, clientY: number, commit: boolean) => {
    if (bendDragOriginRef.current?.edgeId !== edgeId) {
      const prevBend = (edgesRef.current.find(e => e.id === edgeId)?.data as { bend?: { x: number; y: number } } | undefined)?.bend
      bendDragOriginRef.current = { edgeId, prevBend }
    }
    const pos = screenToFlowPosition({ x: clientX, y: clientY })
    setEdges(prev => prev.map(e => e.id === edgeId ? { ...e, data: { ...(e.data as object), bend: pos } } : e))
    if (!commit || !project) return
    let x = pos.x, y = pos.y
    if (usePidCoords) { const n = pixelPointToNormalized(pos.x, pos.y, pidCanvasW, pidCanvasH); x = n.x; y = n.y }
    graphService.updateEdgeBend(project.id, source, target, x, y)
      .catch(console.error).finally(onGraphChanged)
    const prevBend = bendDragOriginRef.current?.prevBend
    bendDragOriginRef.current = null
    pushUndo(async () => {
      if (!prevBend) {
        await graphService.clearEdgeBend(project.id, source, target)
        return
      }
      let px = prevBend.x, py = prevBend.y
      if (usePidCoords) { const n = pixelPointToNormalized(prevBend.x, prevBend.y, pidCanvasW, pidCanvasH); px = n.x; py = n.y }
      await graphService.updateEdgeBend(project.id, source, target, px, py)
    }, () => graphService.updateEdgeBend(project.id, source, target, x, y))
  }, [screenToFlowPosition, project, usePidCoords, pidCanvasW, pidCanvasH, onGraphChanged, pushUndo, setEdges])

  const bendEdgeCtx = useMemo(() => ({ drawMode, onBendDrag }), [drawMode, onBendDrag])

  // ── Click-to-place from palette ─────────────────────────────────────────────
  const onPaneClick = useCallback((e: React.MouseEvent) => {
    setFocusNodeId(null)
    if (!placingKind || !drawMode || !project) return
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    setDrop({ kind: placingKind, pos })
    onPlacingDone()
  }, [placingKind, drawMode, project, screenToFlowPosition, onPlacingDone, setFocusNodeId])

  // ── Drag a palette item onto the canvas → place at drop point ───────────────
  const onDragOver = useCallback((e: React.DragEvent) => {
    if (!drawMode) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [drawMode])

  const onDrop = useCallback((e: React.DragEvent) => {
    if (!drawMode || !project) return
    const kind = e.dataTransfer.getData('application/x-palette-kind')
    if (!kind) return
    e.preventDefault()
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    setDrop({ kind, pos })
  }, [drawMode, project, screenToFlowPosition])

  // ── Node drag stop — save position to DB ────────────────────────────────────
  // Position before the current drag — captured on drag start so a stop can
  // push an undo entry that restores it.
  const dragStartPosRef = useRef<{ id: string; x: number; y: number } | null>(null)
  const onNodeDragStart = useCallback((_e: React.MouseEvent, node: Node) => {
    dragStartPosRef.current = { id: node.id, x: node.position.x, y: node.position.y }
  }, [])

  const onNodeDragStop = useCallback((_e: React.MouseEvent, node: Node) => {
    if (!project || !drawMode) return
    const d = node.data as CData
    const { w, h } = nodeSize(d.kind, d.label, (d.softChildren?.length ?? 0))
    let x = node.position.x
    let y = node.position.y
    if (usePidCoords) {
      const norm = pixelToNormalized(x, y, w, h, pidCanvasW, pidCanvasH)
      x = norm.x
      y = norm.y
    }
    graphService.updateNodePosition(project.id, node.id, x, y)
      .catch(console.error).finally(onGraphChanged)

    const start = dragStartPosRef.current
    dragStartPosRef.current = null
    if (start && start.id === node.id) {
      let px = start.x, py = start.y
      if (usePidCoords) { const norm = pixelToNormalized(px, py, w, h, pidCanvasW, pidCanvasH); px = norm.x; py = norm.y }
      pushUndo(
        () => graphService.updateNodePosition(project.id, node.id, px, py),
        () => graphService.updateNodePosition(project.id, node.id, x, y),
      )
    }
  }, [project, drawMode, usePidCoords, pidCanvasW, pidCanvasH, onGraphChanged, pushUndo])

  // ── Selection ───────────────────────────────────────────────────────────────
  const onSelChange = useCallback(({ nodes: sel }: OnSelectionChangeParams) => {
    const picked = sel.length ? sel[0] : null
    onSelect(picked ? picked.data as CData : null)
    setFocusNodeId(picked ? picked.id : null)
  }, [onSelect, setFocusNodeId])

  // ── Canvas search (Ctrl+K) → highlight + animated zoom-to-node ──────────────
  // Uses setCenter (not fitView-to-node) so it actually ZOOMS IN on the symbol:
  // fitView({nodes}) with padding only ever zooms out to *fit* the node, which
  // left the symbol tiny. setCenter puts the node's center in the middle at a
  // fixed, prominent zoom.
  const focusNode = useCallback((id: string) => {
    const n = nodesRef.current.find(x => x.id === id)
    if (!n) return
    setFocusNodeId(id)                          // highlight only (dims unrelated edges)
    const d = n.data as CData
    const { w, h } = nodeSize(d.kind, d.label, d.softChildren?.length ?? 0)
    setCenter(n.position.x + w / 2, n.position.y + h / 2, { zoom: 1.8, duration: 600 })
    // Note: does NOT open the detail side panel — locate/zoom only. Selecting a
    // node (which opens the panel) stays a deliberate click on the canvas.
  }, [setFocusNodeId, setCenter])

  const focusByTag = useCallback((tag: string) => {
    const n = nodesRef.current.find(x => String((x.data as CData).label) === tag)
    if (n) focusNode(n.id)
  }, [focusNode])

  // Consume a pending cross-screen focus request (from the Review table) once
  // the graph's nodes are present, then zoom to it. Reuses focusNode — no
  // duplicated nav logic. Two robustness details:
  //  • The tag is held in a REF, not consumed-then-scheduled in the effect
  //    body: under React StrictMode the effect runs setup→cleanup→setup, and a
  //    consume-then-clearTimeout pattern would eat the tag on the first setup
  //    and cancel its timeout, leaving the second setup with nothing. The ref
  //    is only cleared when the focus actually fires, so it survives.
  //  • The 180ms delay lets the view-mode auto-fit (fit-all at +100ms) run
  //    first, so our zoom-to-node wins — the user sees fit-all, then a zoom in.
  const pendingTagRef = useRef<string | null>(null)
  useEffect(() => {
    if (pendingTagRef.current == null) {
      const t = takePendingFocus()
      if (t) pendingTagRef.current = t
    }
    if (!nodes.length || !pendingTagRef.current) return
    const tag = pendingTagRef.current
    let alive = true
    const id = setTimeout(() => { if (alive) { pendingTagRef.current = null; focusByTag(tag) } }, 180)
    return () => { alive = false; clearTimeout(id) }
  }, [nodes, focusByTag])

  // Also handle the request while already mounted on the canvas (no navigation).
  useEffect(() => {
    const onFocus = () => {
      const tag = takePendingFocus()
      if (tag) { pendingTagRef.current = null; focusByTag(tag) }
    }
    window.addEventListener('enstudio:canvas-focus', onFocus)
    return () => window.removeEventListener('enstudio:canvas-focus', onFocus)
  }, [focusByTag])

  // ── Node added from palette: insert into local state ────────────────────────
  function onTagConfirmed(kind: string, tag: string, nodeId: string, pos: { x: number; y: number }) {
    const type = getNodeType(kind, tag, false)
    const { w, h } = getNodeSize(type, 0)
    const newNode: Node<CData> = {
      id: nodeId, type,
      position: pos,
      width: w, height: h,
      data: {
        label: tag, kind, kind_detail: kind,
        area: '', drawing: 'DRAW', equipment_ref: '',
        softChildren: [],
        nodeId,
      } as CData,
    }
    setNodes(prev => [...prev, newNode])
    setDrop(null)
    // Palette placement only inserted the row (batch_insert_nodes sends no x/y) —
    // save the drop position now so it isn't NULL and doesn't jump on reload.
    if (project) {
      let x = pos.x, y = pos.y
      if (usePidCoords) { const n = pixelToNormalized(pos.x, pos.y, w, h, pidCanvasW, pidCanvasH); x = n.x; y = n.y }
      graphService.updateNodePosition(project.id, nodeId, x, y).catch(console.error).finally(onGraphChanged)
      pushUndo(() => graphService.deleteNode(project.id, nodeId))
    }
  }

  // Plain click selects (and opens the edit panel), same as before. Shift/
  // Ctrl/Cmd-click a second symbol right after selecting a first one connects
  // them — reuses the same multi-select gesture the H/V align shortcut uses,
  // no separate "link mode" needed. nodesRef still holds the pre-click
  // selection here since RF applies the new selection after onNodeClick runs.
  const onNodeClick = useCallback((e: React.MouseEvent, node: Node) => {
    if (drawMode && node.type !== 'pidbg' && (e.shiftKey || e.ctrlKey || e.metaKey)) {
      const prevSel = nodesRef.current.filter(n => n.selected && n.id !== node.id)
      if (prevSel.length === 1) {
        connectNodes(prevSel[0].id, node.id)
        setNodes(prev => prev.map(n => n.selected ? { ...n, selected: false } : n))
        return
      }
    }
    onSelect(node.data as CData)
  }, [drawMode, connectNodes, onSelect, setNodes])

  const nodesForRF = useMemo(() => {
    const base = nodes
    // Inject the P&ID drawing as a background node so it shares React Flow's
    // pan/zoom transform and lines up with the symbol coordinates.
    if (usePidCoords && showPidBg && pidBgUrl) {
      const bg = {
        id: '__pidbg__', type: 'pidbg', position: { x: 0, y: 0 },
        data: { url: pidBgUrl, w: pidCanvasW, h: pidCanvasH },
        draggable: false, selectable: false, connectable: false,
        focusable: false, zIndex: -1,
      } as unknown as Node<CData>
      return [bg, ...base]
    }
    return base
  }, [nodes, usePidCoords, showPidBg, pidBgUrl, pidCanvasW, pidCanvasH])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}
      onDragOver={onDragOver} onDrop={onDrop}>
      {/* Quick-search (Ctrl+K) — jump/zoom to any node by tag/kind */}
      <CanvasSearch nodes={nodes} onPick={focusNode} />
      {/* Place mode banner */}
      {placingKind && (
        <div style={{
          position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)',
          background: '#1d4ed8', color: '#fff', padding: '5px 14px',
          borderRadius: 6, fontSize: 11, fontWeight: 600, zIndex: 50,
          pointerEvents: 'none', whiteSpace: 'nowrap',
          boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
        }}>
          Placing {placingKind.replace(/_/g, ' ')} — click canvas or ESC to cancel
        </div>
      )}
      {drop && project && (
        <TagInputModal
          kind={drop.kind} project={project}
          onDone={(tag, nodeId) => onTagConfirmed(drop.kind, tag, nodeId, drop.pos)}
          onCancel={() => setDrop(null)}
        />
      )}
      <BendEdgeContext.Provider value={bendEdgeCtx}>
        <ReactFlow
          nodes={nodesForRF} edges={edges}
          nodeTypes={NODE_TYPES_WITH_BG}
          edgeTypes={EDGE_TYPES_MAP}
          onNodesChange={drawMode ? onNodesChange : undefined}
          onEdgesChange={drawMode ? onEdgesChange : undefined}
          onSelectionChange={onSelChange}
          onConnectStart={drawMode ? (_, { nodeId }) => { dragStartNodeRef.current = nodeId ?? null } : undefined}
          onConnect={drawMode ? onConnect : undefined}
          onConnectEnd={drawMode ? onConnectEnd : undefined}
          onReconnect={drawMode ? onReconnect : undefined}
          edgesReconnectable={drawMode}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          onNodeDragStart={drawMode ? onNodeDragStart : undefined}
          onNodeDragStop={drawMode ? onNodeDragStop : undefined}
          nodesDraggable={drawMode}
          nodesConnectable={drawMode}
          edgesFocusable={drawMode}
          connectionMode={ConnectionMode.Loose}
          deleteKeyCode={null}
          proOptions={{ hideAttribution: true }}
          fitView fitViewOptions={{ padding: 0.2 }}
          panOnDrag zoomOnScroll zoomOnPinch
          minZoom={0.1} maxZoom={3}
          style={{
            background: '#000000',
            cursor: placingKind ? 'crosshair' : undefined,
            zIndex: 1,
          }}
        >
          {!(showPidBg && pidBgUrl) && <Background color={Theme.grid} gap={24} size={1} style={{ opacity: Theme.gridOpacity }} />}
          <MiniMap
            position="bottom-right" pannable={true} zoomable={true}
            nodeColor={n => {
              const d = n.data as CData
              const dk = String((d as Record<string, unknown>).type ?? d.kind ?? '')
              if (isOffPage(dk, String(d.label), String((d as Record<string, unknown>).category ?? ''))) return OFFPAGE_C.border
              return isInstrument(dk) ? instrColors(String(d.label)).border : equipColors(dk).border
            }}
            style={{ backgroundColor: Theme.canvas, border: `1px solid ${Theme.grid}` }}
            maskColor="rgba(15,23,42,0.75)"
          />
        </ReactFlow>
      </BendEdgeContext.Provider>
    </div>
  )
}

// ── Main screen ───────────────────────────────────────────────────────────────

const MAX_AUTO_ALL = 300

export default function CanvasScreen({ project }: Props) {
  const [graph, setGraph] = useState<GraphData | null>(null)
  // Plant-hierarchy filter published by the Sidebar panel: nodes outside the
  // selected system/subsystem are dimmed rather than hidden, so their
  // connections stay readable.
  const [hierarchyFilter, setHierarchyFilter] = useState<Set<string> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<CData | null>(null)
  const [drawing, setDrawing] = useState<string>('all')
  const [drawMode, setDrawMode] = useState(false)
  const [placingKind, setPlacingKind] = useState<string | null>(null)
  const [layoutMode, setLayoutMode] = useState<'extracted' | 'process' | 'dagre'>('extracted')
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null)
  // Which project's sheet image loadGraph has already resolved — stops the
  // background effect from fetching and re-setting it a second time.
  const bgLoadedFor = useRef<string | null>(null)
  const [pidBgUrl, setPidBgUrl] = useState<string | null>(null)
  const [pidCanvasSize, setPidCanvasSize] = useState(DEFAULT_PID_CANVAS)
  // Overlay the source drawing behind the symbols. Everything needed for this
  // already existed -- PidBgNode, the `pidbg` node type, the pidBgUrl fetch and
  // the nodesForRF injection -- but the flag was declared WITHOUT a setter, so
  // it was permanently false and the feature was unreachable from the UI. That
  // made it impossible to check symbol placement against the sheet, which is
  // the one comparison this canvas exists to support. Off by default, so the
  // default view is unchanged.
  const [showPidBg, setShowPidBg] = useState(false)

  const [editingNodeId, setEditingNodeId] = useState<string | null>(null)

  // Side panel enter/exit: keep it mounted through the close animation, and
  // hold the last node so it still renders content while sliding out.
  // Mutating/reading a ref during render (below, and again where this is
  // read in the panel JSX) is technically against React's render-purity
  // contract and is flagged by the newer react-hooks lint rules — but this
  // app doesn't run the React Compiler (plain @vitejs/plugin-react, see
  // vite.config.ts) and doesn't lean on concurrent-rendering features that
  // would make a throwaway/duplicate render observable, so it's not a
  // reachable bug today. Converting this to state would need the "last
  // selected node" write to happen in an effect instead of during render,
  // shifting it by one commit — risking a stale panel-content flash on the
  // close animation that can't be verified without a live app (this
  // environment cannot run/screenshot the Tauri app). Left in place per
  // Phase 11's "don't force a fix that risks behavior" guidance.
  const panelOpen = !!selected && String(selected.kind) !== 'junction'
  const panelTransition = useMountTransition(panelOpen)
  const lastPanelNode = useRef(selected)
  if (selected) lastPanelNode.current = selected

  // ── Undo stack ────────────────────────────────────────────────────────────
  // Each Draw-mode mutation pushes its own inverse (a DB call that reverts
  // it) right after it succeeds. Undo pops and runs the most recent one.
  // ponytail: node deletion has no inverse yet — batch_insert_nodes always
  // mints a fresh id, so "undelete" can't restore the original id (and thus
  // can't cleanly restore edges that pointed at it). Add a "recreate with
  // explicit id" backend command if that's needed later.
  // Each entry pairs an `undo` (inverse) closure with an optional `redo`
  // (forward) closure. Operations whose forward action is cleanly re-appliable
  // (moves, edge insert/delete, reconnect, bend, align) provide `redo` and are
  // redoable; one-way operations whose forward mints a fresh node id (place
  // node, junction split) omit `redo` and stay undo-only — matching what the
  // backend can actually restore (see the id-instability note above).
  type UndoEntry = { undo: () => Promise<void>; redo?: () => Promise<void> }
  const undoStackRef = useRef<UndoEntry[]>([])
  const redoStackRef = useRef<UndoEntry[]>([])
  const [undoCount, setUndoCount] = useState(0)
  const [redoCount, setRedoCount] = useState(0)

  const loadGraph = useCallback(async (pid: string) => {
    setLoading(true); setError(''); setGraph(null); setSelected(null)
    // A full reload invalidates any pending undo/redo (ids/state may differ).
    undoStackRef.current = []; setUndoCount(0)
    redoStackRef.current = []; setRedoCount(0)
    try {
      // Phase 3: fetch the page image ALONGSIDE the graph and apply its
      // dimensions BEFORE `graph` lands. Previously the sheet size arrived in
      // a separate effect that ran after the first paint, so the whole
      // extracted layout — including its O(n^2) collision pass — computed
      // once at the 3000x2200 default and again at the real size, and every
      // node visibly jumped between the two.
      const [g, page] = await Promise.all([
        graphService.getGraph(pid),
        canvasService.getPageImagePath(pid, 1).catch(() => null),
      ])
      if (page && page.width > 0 && page.height > 0) {
        setPidCanvasSize({ w: page.width, h: page.height })
        setPidBgUrl(page.url)
        bgLoadedFor.current = pid
      } else {
        bgLoadedFor.current = null
      }
      setGraph(normalizeGraph(g as unknown as GraphData))
    }
    catch (e: unknown) { setError(typeof e === 'string' ? e : JSON.stringify(e)) }
    finally { setLoading(false) }
  }, [])

  // Draw-mode actions (delete, place, connect…) each want to refresh the graph
  // after their DB write lands. Firing a fetch per action lets independent
  // async round-trips resolve out of order — an older, slower fetch can land
  // last and overwrite newer state with data that predates it (e.g. bringing
  // a just-deleted node back). Serialize instead: never run two fetches at
  // once; if a refresh is requested while one is in flight, queue exactly one
  // more right after — it fires only once all currently known writes have
  // been issued, so it's guaranteed to read a DB state at least as fresh.
  const reloadInFlight = useRef(false)
  const reloadPending = useRef(false)

  // Self-recursive useCallback (calls itself by name in the finally block
  // below) — the newer react-hooks lint flags this as memoization it can't
  // statically verify for a future React Compiler pass, but it's correct
  // under classic React: `useCallback` returns a stable reference per
  // render, and the closure's self-reference resolves to that same binding
  // whenever the async body actually runs. Not a runtime bug; this app
  // doesn't enable the React Compiler (plain @vitejs/plugin-react).
  const softReloadGraph = useCallback(async () => {
    if (!project) return
    if (reloadInFlight.current) { reloadPending.current = true; return }
    reloadInFlight.current = true
    try {
      const g = normalizeGraph(await graphService.getGraph(project.id) as unknown as GraphData)
      setGraph(g)
    }
    catch (e: unknown) { console.error('softReloadGraph:', e) }
    finally {
      reloadInFlight.current = false
      if (reloadPending.current) { reloadPending.current = false; softReloadGraph() }
    }
  }, [project])

  const pushUndo = useCallback((undoFn: () => Promise<void>, redoFn?: () => Promise<void>) => {
    undoStackRef.current.push({ undo: undoFn, redo: redoFn })
    if (undoStackRef.current.length > 50) undoStackRef.current.shift()
    setUndoCount(undoStackRef.current.length)
    // A brand-new edit invalidates the redo timeline (can't redo past a fork).
    if (redoStackRef.current.length) { redoStackRef.current = []; setRedoCount(0) }
  }, [])
  const undo = useCallback(() => {
    const entry = undoStackRef.current.pop()
    setUndoCount(undoStackRef.current.length)
    if (!entry) return
    // Only redoable entries move onto the redo stack; one-way undos are dropped.
    // (It's already bounded by the 50-deep undo stack — you can't redo more
    // than you undid — but the explicit cap keeps the invariant obvious.)
    if (entry.redo) {
      redoStackRef.current.push(entry)
      if (redoStackRef.current.length > 50) redoStackRef.current.shift()
      setRedoCount(redoStackRef.current.length)
    }
    entry.undo().catch(console.error).finally(softReloadGraph)
  }, [softReloadGraph])
  const redo = useCallback(() => {
    const entry = redoStackRef.current.pop()
    setRedoCount(redoStackRef.current.length)
    if (!entry?.redo) return
    undoStackRef.current.push(entry)
    setUndoCount(undoStackRef.current.length)
    entry.redo().catch(console.error).finally(softReloadGraph)
  }, [softReloadGraph])

  // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
  useEffect(() => { if (project) loadGraph(project.id) }, [project?.id, loadGraph])

  useEffect(() => onHierarchyFilter(d => {
    if (!project || d.projectId !== project.id) return
    setHierarchyFilter(d.nodeIds ? new Set(d.nodeIds) : null)
  }), [project])

  // Describe agents write from a spawned backend process; reload when told.
  useEffect(() => subscribeGraphChanged(d => {
    if (project && d.projectId === project.id) softReloadGraph()
  }), [project, softReloadGraph])

  const drawings = useMemo(() => {
    if (!graph) return []
    const s = new Set<string>()
    graph.nodes.forEach(n => { if (n.drawing) s.add(n.drawing) })
    return Array.from(s).sort()
  }, [graph])
  useEffect(() => {
    if (!graph) return
    // Single drawing → use P&ID sheet layout; huge multi-drawing sets pick first sheet
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (drawings.length === 1) setDrawing(drawings[0])
    else if (graph.nodes.length > MAX_AUTO_ALL && drawings.length) setDrawing(drawings[0])
    else setDrawing('all')
    if (graph.nodes.length === 0) setDrawMode(true)
  }, [graph, drawings])

  // ── Derived graph state ───────────────────────────────────────────────────

  const filteredNodes = useMemo(() => {
    if (!graph) return []
    if (drawing === 'all') return graph.nodes
    // Junction nodes (gj_* tap points) are structural connectors — they have
    // no drawing of their own but must be visible on whatever sheet their
    // edges belong to. Without them, every edge routed through a junction
    // (T-branches, instrument taps) is silently dropped by filteredEdges
    // because the junction id is not in the `ids` set.
    return graph.nodes.filter(n => n.drawing === drawing || n.kind === 'junction')
  }, [graph, drawing])

  const filteredEdges = useMemo(() => {
    if (!graph) return []
    const ids = new Set(filteredNodes.map(n => n.id))
    return graph.edges.filter(e => e.source && e.target && ids.has(e.source) && ids.has(e.target))
  }, [graph, filteredNodes])
  const { parentToChildren, unmatchedSoftIds } = useMemo(
    () => buildSoftGroups(filteredNodes), [filteredNodes]
  )

  const absorbedCount = useMemo(() => {
    let n = 0; parentToChildren.forEach(c => { n += c.length }); return n
  }, [parentToChildren])

  const nodesForGraph = useMemo(() =>
    filteredNodes.filter(n =>
      // tee/manifold nodes are still hidden; junction nodes are kept visible
      // as tiny branch dots so edges physically branch at the pipe tap point.
      (n.kind !== 'tee' && n.kind !== 'manifold') &&
      (!isSoftTag(n.label, n.kind) || unmatchedSoftIds.has(n.id))
    ),
    [filteredNodes, unmatchedSoftIds]
  )

  const edgesForGraph = useMemo(() => {
    const incl = new Set(nodesForGraph.map(n => n.id))
    // Re-route edges that passed through HIDDEN tee/manifold nodes only.
    // Junction nodes are kept visible (in nodesForGraph) so their edges
    // must NOT be re-routed — they connect directly to the junction dot.
    const teeNodes = new Set(
      filteredNodes
        .filter(n => n.kind === 'tee' || n.kind === 'manifold')
        .map(n => n.id)
    )
    if (teeNodes.size === 0) {
      return filteredEdges.filter(e => incl.has(e.source) && incl.has(e.target))
    }
    // For each junction, track upstream (→ junction) and downstream (junction →) real nodes
    const teeUpstream = new Map<string, string[]>()  // junctionId → [real nodes pointing IN]
    const teeDownstream = new Map<string, string[]>()  // junctionId → [real nodes pointing OUT]
    for (const e of filteredEdges) {
      if (teeNodes.has(e.target) && incl.has(e.source)) {
        const arr = teeUpstream.get(e.target) ?? []; arr.push(e.source)
        teeUpstream.set(e.target, arr)
      }
      if (teeNodes.has(e.source) && incl.has(e.target)) {
        const arr = teeDownstream.get(e.source) ?? []; arr.push(e.target)
        teeDownstream.set(e.source, arr)
      }
    }
    const result: typeof filteredEdges = []
    const seen = new Set<string>()
    for (const e of filteredEdges) {
      if (!teeNodes.has(e.source) && !teeNodes.has(e.target)) {
        if (incl.has(e.source) && incl.has(e.target)) result.push(e)
        continue
      }
      // Edge touches a junction — re-route upstream → each downstream (star, not clique)
      const teeId = teeNodes.has(e.source) ? e.source : e.target
      const upstreams = teeUpstream.get(teeId) ?? []
      const downstreams = teeDownstream.get(teeId) ?? []
      // If junction has no upstream, treat all neighbours as mutual branches
      const srcs = upstreams.length > 0 ? upstreams : downstreams
      const dsts = upstreams.length > 0 ? downstreams : []
      for (const src of srcs) {
        for (const dst of dsts) {
          if (src === dst) continue
          const key = `${src}|${dst}`
          if (!seen.has(key)) {
            seen.add(key)
            result.push({ ...e, source: src, target: dst })
          }
        }
      }
    }
    return result
  }, [filteredEdges, filteredNodes, nodesForGraph])

  const assocEdges = useMemo(() => buildAssocEdges(nodesForGraph), [nodesForGraph])

  const { dagreNodes, orphanNodes } = useMemo(() => {
    const conn = connectedSet(edgesForGraph, assocEdges)
    return {
      dagreNodes: nodesForGraph.filter(n => conn.has(n.id)),
      orphanNodes: nodesForGraph.filter(n => !conn.has(n.id)),
    }
  }, [nodesForGraph, edgesForGraph, assocEdges])

  const softCounts = useMemo(() => {
    const m = new Map<string, number>()
    parentToChildren.forEach((children, pid) => { m.set(pid, children.length) })
    return m
  }, [parentToChildren])

  // Resolve which layout engine to use.
  const effectiveLayout = useMemo<'extracted' | 'process' | 'dagre'>(() => {
    return layoutMode
  }, [layoutMode])

  // P&ID page image for background + coordinate scale (page 1 for single-drawing view)
  useEffect(() => {
    // A "single sheet" project has no distinct drawing numbers, so the 'all'
    // view IS that one page — load its image so extracted coordinates map onto
    // the real page (correct aspect) and the drawing shows behind the nodes.
    const singleSheet = drawings.length <= 1
    if (!project || (drawing === 'all' && !singleSheet)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPidBgUrl(null)
      setPidCanvasSize(DEFAULT_PID_CANVAS)
      bgLoadedFor.current = null
      return
    }
    // loadGraph already resolved this project's sheet image and dimensions
    // before the graph landed; re-fetching here would set the same state a
    // second time and re-run the whole layout for nothing.
    if (bgLoadedFor.current === project.id) return

    let cancelled = false
    // get_page_image_path returns {url, width, height} — set canvas size
    // atomically with the URL so the layout never computes with wrong dimensions.
    canvasService.getPageImagePath(project.id, 1)
      .then(({ url, width, height }) => {
        if (cancelled) return
        if (width > 0 && height > 0) {
          setPidCanvasSize({ w: width, h: height })
        }
        setPidBgUrl(url)
        bgLoadedFor.current = project.id
      })
      .catch(() => {
        if (!cancelled) {
          setPidBgUrl(null)
          setPidCanvasSize(DEFAULT_PID_CANVAS)
        }
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, drawing, drawings.length])

  // Drawing metadata: most-common area per drawing (not just first node encountered)
  const drawingMeta = useMemo(() => {
    const areaCounts: Record<string, Record<string, number>> = {}
    graph?.nodes.forEach(n => {
      if (!n.drawing || !n.area) return
      if (!areaCounts[n.drawing]) areaCounts[n.drawing] = {}
      areaCounts[n.drawing][n.area] = (areaCounts[n.drawing][n.area] ?? 0) + 1
    })
    const meta: Record<string, { area: string }> = {}
    Object.entries(areaCounts).forEach(([drw, counts]) => {
      const bestArea = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? ''
      meta[drw] = { area: bestArea }
    })
    return meta
  }, [graph])

  // True when we're showing all drawings in process mode (→ plant-wide layout)
  const isPlantView = drawing === 'all' && effectiveLayout === 'process'

  // In process/extracted modes all non-soft nodes go on canvas; in dagre mode only connected ones.
  const rfSourceNodes = useMemo(
    () => effectiveLayout === 'dagre' ? dagreNodes : nodesForGraph,
    [effectiveLayout, nodesForGraph, dagreNodes]
  )

  const layoutResult = useMemo<{ pos: Map<string, { x: number; y: number }>; groups: AreaGroup[]; sizes?: Map<string, { w: number; h: number }> }>(() => {
    const empty = { pos: new Map<string, { x: number; y: number }>(), groups: [] as AreaGroup[] }
    if (!rfSourceNodes.length) return empty

    if (effectiveLayout === 'extracted') {
      const toPl = (n: GraphNode) => ({
        id: n.id, label: n.label, kind: n.kind, type: n.type,
        x: n.x, y: n.y, drawing: n.drawing,   // pass drawing for multi-drawing grid
        equipment_ref: n.equipment_ref,       // pass ref for vendor-package packing
        page_w: n.page_w, page_h: n.page_h,   // real sheet size -> per-drawing cell aspect
      })
      // Always use real image dimensions when available — showPidBg only controls
      // visual display, not the coordinate system. This keeps symbols at their
      // exact extracted positions regardless of whether background is visible.
      // 2× scale so the P&ID background renders at double the source resolution.
      const cw = pidBgUrl ? pidCanvasSize.w : DEFAULT_PID_CANVAS.w
      const ch = pidBgUrl ? pidCanvasSize.h : DEFAULT_PID_CANVAS.h
      const { pos, sizes } = extractedLayout(
        rfSourceNodes.map(toPl),
        n => nodeSize(n.type ?? n.kind, n.label, softCounts.get(n.id) ?? 0),
        cw,
        ch,
        edgesForGraph,
      )
      return { pos, groups: [], sizes }
    }

    if (effectiveLayout === 'process') {
      if (isPlantView) {
        // Plant-wide layout: one backbone per process area, utilities below
        return { ...plantLayout(rfSourceNodes, edgesForGraph, drawingMeta), sizes: undefined }
      }
      if (canUseProcessLayout(rfSourceNodes)) {
        return { pos: processLayout(rfSourceNodes, edgesForGraph), groups: [], sizes: undefined }
      }
    }
    // Dagre fallback
    const dNodes = effectiveLayout === 'process' ? rfSourceNodes : dagreNodes
    const dagrePos = dagreLayout(dNodes, edgesForGraph, assocEdges, softCounts)

    // After dagre positions are computed, fix junction node positions.
    // Dagre places junctions wherever it wants — but they must sit between
    // their upstream and downstream neighbours so the branch looks correct.
    const junctionIds = new Set(
      rfSourceNodes.filter(n => (n.kind === 'junction' || n.type === 'junction')).map(n => n.id)
    )
    if (junctionIds.size > 0) {
      // Build neighbour lookup from edgesForGraph
      const upstream: Map<string, string[]> = new Map()
      const downstream: Map<string, string[]> = new Map()
      for (const e of edgesForGraph) {
        if (junctionIds.has(e.target)) {
          const arr = upstream.get(e.target) ?? []; arr.push(e.source); upstream.set(e.target, arr)
        }
        if (junctionIds.has(e.source)) {
          const arr = downstream.get(e.source) ?? []; arr.push(e.target); downstream.set(e.source, arr)
        }
      }

      // Build a node-kind lookup so we can tell instruments apart from inline symbols
      // NOTE: this is a deliberately separate, narrower classifier from the
      // canonical `isInstrument` imported above (domain/isa/instrument.ts) —
      // confirmed during Phase 6's audit to use a different kind/fragment
      // list (e.g. it excludes "switch", "sensor", "totalizer") for this
      // specific local heuristic (splitting a junction's pipe-neighbours
      // from its instrument-tap neighbours). Not merged; see the comment in
      // domain/isa/instrument.ts for the full rationale.
      const nodeKindMap = new Map(rfSourceNodes.map(n => [n.id, (n.kind ?? n.type ?? '').toLowerCase()]))
      const INSTRUMENT_KINDS = new Set([
        'instrument', 'pressure_indicator', 'temperature_indicator', 'temperature_element',
        'level_gauge', 'differential_temperature', 'temperature_controller',
        'indicator', 'transmitter', 'controller', 'element', 'analyzer', 'recorder', 'meter', 'gauge',
      ])
      const isInstrument = (id: string) => {
        const k = nodeKindMap.get(id) ?? ''
        return INSTRUMENT_KINDS.has(k) ||
          ['indicator', 'element', 'controller', 'transmitter', 'gauge', 'meter', 'analyzer',
            'differential', 'thermocouple'].some(f => k.includes(f))
      }

      for (const jid of junctionIds) {
        const ups = (upstream.get(jid) ?? []).filter(id => !junctionIds.has(id))
        const dns = (downstream.get(jid) ?? []).filter(id => !junctionIds.has(id))

        // Main pipe neighbours = upstream + non-instrument downstream only
        const mainPipeDns = dns.filter(id => !isInstrument(id))
        const pipeNeighbours = [...ups, ...mainPipeDns]
        const candidates = pipeNeighbours.length > 0 ? pipeNeighbours : [...ups, ...dns]
        if (candidates.length === 0) continue

        // Position junction relative to its neighbours.
        let sx = 0, sy = 0, cnt = 0
        for (const nid of candidates) {
          const p = dagrePos.get(nid)
          if (p) { sx += p.x; sy += p.y; cnt++ }
        }
        if (cnt === 0) continue

        const jPos = { x: sx / cnt, y: sy / cnt }
        dagrePos.set(jid, jPos)
      }
    }

    return { pos: dagrePos, groups: [], sizes: undefined }
  }, [rfSourceNodes, edgesForGraph, assocEdges, softCounts, effectiveLayout, dagreNodes, isPlantView, drawingMeta, pidCanvasSize, pidBgUrl])

  const layoutPos = layoutResult.pos
  const areaGroups = layoutResult.groups
  const layoutSizes = layoutResult.sizes

  // ── React Flow nodes (pass nodeId through data for DrawSidePanel) ──────────

  const rfNodes: Node<CData>[] = useMemo(() => {
    // Area group background rects (plant-wide mode only) — rendered behind via zIndex: -1
    const groupNodes: Node<CData>[] = areaGroups.map(g => ({
      id: `_ag_${g.category}`,
      type: 'areagroup',
      position: { x: g.x, y: g.y },
      width: g.width,
      height: g.height,
      selectable: false,
      draggable: false,
      zIndex: -1,
      data: {
        label: g.label, kind: '', kind_detail: '',
        area: '', drawing: '', equipment_ref: '',
        softChildren: [], nodeId: `_ag_${g.category}`,
        color: g.color,      // consumed by AreaGroupNode
      } as CData,
    }))

    // Off-page connector arrows point in the FLOW direction so inlets and outlets
    // read differently:
    //   - inlet  (feed into the process) → points TOWARD the process (into page)
    //   - outlet (stream leaving)        → points AWAY from the process (off page)
    // Use the RENDERED x (layout position), not the raw extracted x — the arrow
    // must orient to where nodes actually sit on the canvas.
    const xById = new Map(rfSourceNodes.map(n => [n.id, layoutPos.get(n.id)?.x ?? n.x]))
    const offDirById = computeOffPageDirections(rfSourceNodes, edgesForGraph, xById)

    const processNodes = rfSourceNodes.map(n => {
      const sc = parentToChildren.get(n.id) ?? []
      const rk = n.type ?? n.kind   // prefer YOLO type for rendering; fall back to kind
      const type = getNodeType(rk, n.label, isOffPage(rk, n.label, n.category))
      // Vendor packages get an expanded size override so the dashed box wraps
      // its children; rendered behind children via lower zIndex.
      const override = layoutSizes?.get(n.id)
      const { w, h } = override ?? nodeSize(rk, n.label, sc.length, n.category)
      const isPackage = type === 'vendor_package'
      return {
        id: n.id, type,
        position: layoutPos.get(n.id) ?? { x: 0, y: 0 },
        width: w, height: h,
        selectable: true,
        zIndex: isPackage ? -1 : 0,
        style: hierarchyFilter && !hierarchyFilter.has(n.id) ? { opacity: 0.18 } : undefined,
        data: {
          label: n.label, kind: n.kind, kind_detail: n.kind_detail,
          area: n.area, drawing: n.drawing, equipment_ref: n.equipment_ref,
          category: n.category ?? '',
          offW: w, offDir: offDirById.get(n.id) ?? 'right',
          softChildren: sc.map(c => ({ id: c.id, label: c.label, kind: c.kind, area: c.area })),
          nodeId: n.id,
        } as CData,
      }
    })

    return [...groupNodes, ...processNodes]
  }, [rfSourceNodes, edgesForGraph, layoutPos, layoutSizes, parentToChildren, areaGroups, hierarchyFilter])

  // Map node id → drawing (for cross-drawing edge detection)
  const nodeDrawingOf = useMemo(() => {
    const m = new Map<string, string>()
    rfSourceNodes.forEach(n => m.set(n.id, n.drawing ?? ''))
    return m
  }, [rfSourceNodes])

  const rfEdges: Edge[] = useMemo(() => {
    const ids = new Set(rfNodes.filter(n => n.type !== 'areagroup').map(n => n.id))
    // One pass to index the nodes, instead of two linear scans per edge for
    // the symbol boxes plus two more inside pickHandles (Phase 4).
    const rfNodeById = new Map(rfNodes.map(n => [n.id, n]))
    // Pipes are frequently chained through junction dots (tap points, corners),
    // so one visual pipe run is often several short real edges — each getting
    // its own arrowhead reads as clutter/contradiction at the junction. Only
    // the longer, meaningful hops get an arrow; short junction stubs don't.
    const nodeCenter = new Map(rfNodes.map(n => [n.id, { x: n.position.x + (n.width ?? 0) / 2, y: n.position.y + (n.height ?? 0) / 2 }]))
    const MIN_ARROW_LEN = 60
    const showArrow = (a: string, b: string) => {
      const p1 = nodeCenter.get(a), p2 = nodeCenter.get(b)
      if (!p1 || !p2) return true
      return Math.hypot(p2.x - p1.x, p2.y - p1.y) >= MIN_ARROW_LEN
    }

    // Phase 3: extracted pipe geometry is used again.
    //
    // It was disabled because an incomplete route drew a visibly TRUNCATED
    // line — the old code drew the stored path as-is, so a route missing its
    // last segment simply stopped in mid-air. WaypointEdge fixes the cause:
    // it anchors to the live source/target handles and treats the stored
    // points as INTERIOR bends only, so an incomplete route degrades to a
    // slightly-wrong corner rather than a pipe that ends nowhere.
    //
    // Priority is: extracted geometry > deterministic elbow > interactive
    // bend. See features/canvas/utils/waypoints.ts for the decision.
    // Stable, endpoint-derived edge ids. Array-index ids (`t0`, `t1`, ...)
    // are unique per render but carry no identity: they shift whenever the
    // drawing filter changes, so React Flow cannot correlate an edge across
    // renders. See utils/graphIntegrity.ts::makeEdgeId.
    const edgeIdSeen = new Map<string, number>()
    const topo: Edge[] = edgesForGraph
      .filter(e => ids.has(e.source) && ids.has(e.target))
      .map((e) => {
        const sd = nodeDrawingOf.get(e.source) ?? ''
        const td = nodeDrawingOf.get(e.target) ?? ''
        const cross = isPlantView && sd && td && sd !== td

        const style: React.CSSProperties = cross
          ? { stroke: '#7c3aed', strokeWidth: 1, strokeDasharray: '6 4', opacity: 0.4 }
          : edgeStyle(e.kind)

        const cw = pidBgUrl ? pidCanvasSize.w : DEFAULT_PID_CANVAS.w
        const ch = pidBgUrl ? pidCanvasSize.h : DEFAULT_PID_CANVAS.h

        // A user-dragged bend (0-1 sheet coords) only means anything in the
        // extracted/P&ID layout, where node positions are similarly persisted.
        const bend = (effectiveLayout === 'extracted' && e.bend_x != null && e.bend_y != null)
          ? normalizedPointToPixel(e.bend_x, e.bend_y, cw, ch)
          : undefined

        // Extracted route: interior bends only, converted through the SAME
        // normalised->pixel transform the nodes use (normalizedPointToPixel),
        // so a route point and a symbol centre cannot drift apart. That
        // transform is unchanged and already validated — Phase 3 does not
        // introduce a second coordinate mapping.
        const interior = sanitizeWaypoints(e.waypoints)
        const wantsRoute = routeKindFor(e, interior, effectiveLayout) === 'waypoint'

        // Clip the route against the RENDERED symbol boxes and take the
        // anchor faces from what survives. The canvas draws symbols at a
        // fixed size and extractedLayout nudges them for alignment, so a bend
        // that cleared the real symbol on the sheet can sit inside the
        // rendered one — drawing to it cuts straight through the symbol.
        // See buildRoute() for the measurements behind this.
        const srcN = rfNodeById.get(e.source)
        const tgtN = rfNodeById.get(e.target)
        const boxOf = (n: typeof srcN) => n ? {
          x1: n.position.x, y1: n.position.y,
          x2: n.position.x + (n.width ?? 80), y2: n.position.y + (n.height ?? 50),
        } : null
        const sBox = boxOf(srcN), tBox = boxOf(tgtN)
        // Inline two-port components (valves, regulators) take their pipes on
        // the left/right ports only — the same rule pickHandles applies.
        const inlinePorts = (n: typeof srcN) => String(n?.type ?? '').includes('valve')
        const built = (wantsRoute && sBox && tBox)
          ? buildRoute(
              interior.map(p => normalizedPointToPixel(p.x, p.y, cw, ch)),
              sBox, tBox,
              { srcHorizontal: inlinePorts(srcN), tgtHorizontal: inlinePorts(tgtN) })
          : null

        const route = built ? 'waypoint' : 'bendable'
        const pts = built?.pts
        const handles = built
          ? { sourceHandle: built.sourceHandle, targetHandle: built.targetHandle }
          : pickHandles(rfNodeById, e.source, e.target)
        const routeVertical = handles.sourceHandle === 'st' || handles.sourceHandle === 'sb'

        // Arrow color matches the pipe stroke so it reads as one element
        const pipeColor = cross ? '#7c3aed' : (style.stroke as string) ?? Theme.processPipe
        const arrow = showArrow(e.source, e.target) ? flowArrow(pipeColor) : undefined

        // How well-established this connection is. Never hidden, never
        // upgraded — an LLM edge must not read as deterministic and an
        // unaudited edge must not read as verified.
        const trust = edgeTrust(e)

        return {
          id: makeEdgeId(e.source, e.target, edgeIdSeen),
          source: e.source, target: e.target,
          ...handles,
          type: edgeFlowType(e.kind, route === 'waypoint'),
          data: { kind: e.kind, bend, routeVertical, pts, trust,
                  // the two symbol boxes, so an interior elbow can avoid them
                  boxes: built && sBox && tBox ? [sBox, tBox] : undefined,
                  provenance: e.provenance, audited: e.audited },
          style: cross ? style : { ...style, ...trustStyle(trust) },
          markerEnd: arrow,
          zIndex: cross ? 5 : 0,
        }
      })

    // Association edges: only show when a node is focused or in 'all' view,
    // otherwise they add clutter with no real pipe route behind them.
    const asc: Edge[] = (focusNodeId)
      ? assocEdges
        .filter(e => ids.has(e.source) && ids.has(e.target))
        .filter(e => !focusNodeId || e.source === focusNodeId || e.target === focusNodeId)
        .map((e) => ({
          id: `assoc:${e.source}->${e.target}`,
          source: e.source, target: e.target, type: 'smoothstep',
          style: edgeStyle('assoc'), zIndex: 1,
        }))
      : []
    return [...topo, ...asc]
  }, [edgesForGraph, assocEdges, rfNodes, nodeDrawingOf, isPlantView, effectiveLayout, pidBgUrl, pidCanvasSize, focusNodeId])

  // Phase 3: verify the graph React Flow is about to receive. React Flow
  // drops duplicate ids and edges pointing at missing nodes SILENTLY, which
  // is indistinguishable from an extraction gap. Warn loudly instead — the
  // phase brief forbids silently hiding topology. Nothing is removed here;
  // the edge list is already filtered to existing node ids above.
  useEffect(() => {
    if (!rfNodes.length) return
    const report = checkGraphIntegrity(rfNodes, rfEdges)
    if (!report.ok) console.warn(describeIntegrity(report), report)
  }, [rfNodes, rfEdges])

  function selectOrphan(n: GraphNode) {
    const sc = (parentToChildren.get(n.id) ?? []).map(c => ({ id: c.id, label: c.label, kind: c.kind, area: c.area }))
    setSelected({
      label: n.label, kind: n.kind, kind_detail: n.kind_detail,
      area: n.area, drawing: n.drawing, equipment_ref: n.equipment_ref,
      softChildren: sc, nodeId: n.id,
    } as CData)
  }

  // ── Placeholders ─────────────────────────────────────────────────────────

  if (!project) return <div className="canvas-placeholder"><div className="canvas-placeholder-icon">⬡</div><div className="canvas-placeholder-title">No project selected</div></div>
  if (loading) return <div className="canvas-placeholder"><div className="canvas-placeholder-sub">Computing layout…</div></div>
  if (error) return <div className="canvas-placeholder"><div style={{ color: 'var(--danger)', fontSize: 13 }}>{error}</div></div>

  // In process/extracted layout mode every node is on canvas; orphan strip is not needed.
  const displayOrphans = effectiveLayout === 'dagre' ? orphanNodes : []
  const showCanvas = rfSourceNodes.length > 0 || drawMode
  const orphCount = displayOrphans.length

  return (
    <ReactFlowProvider>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>

        {/* ── Toolbar ── */}
        <div className="canvas-toolbar" style={{
          height: 44, flexShrink: 0, borderBottom: '1px solid var(--border)',
          background: 'var(--bg-secondary)', display: 'flex', alignItems: 'center',
          padding: '0 14px', gap: 10, fontSize: 12,
        }}>
          <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{project.name}</span>
          <span style={{ color: 'var(--border)' }}>|</span>

          <select value={drawing} onChange={e => { setDrawing(e.target.value); setSelected(null) }}
            style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text-primary)', font: 'inherit', fontSize: 12, padding: '3px 8px', cursor: 'pointer', outline: 'none', maxWidth: 250 }}>
            <option value="all">All drawings ({graph?.nodes.length ?? 0})</option>
            {drawings.map(d => {
              const cnt = graph?.nodes.filter(n => n.drawing === d).length ?? 0
              return <option key={d} value={d}>{d} · {cnt}</option>
            })}
          </select>

          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
            {rfNodes.length} nodes · {rfEdges.length} edges
            {absorbedCount > 0 && <span style={{ color: '#475569' }}> · {absorbedCount} soft collapsed</span>}
            {orphCount > 0 && <span style={{ color: 'var(--warning)' }}> · {orphCount} unlinked</span>}
          </span>

          {drawing === 'all' && (graph?.nodes.length ?? 0) > MAX_AUTO_ALL && (
            <span style={{ color: 'var(--warning)', fontSize: 11 }}>⚠ Select a drawing</span>
          )}

          {/* Layout toggle — only in View mode */}
          {!drawMode && (
            <div style={{ display: 'flex', gap: 2, background: 'var(--bg-tertiary)', borderRadius: 6, padding: 2, border: '1px solid var(--border)' }}>
              {(['extracted', 'process', 'dagre'] as const).map(m => {
                const labels = { extracted: 'P&ID', process: 'Process', dagre: 'Dagre' }
                const active = layoutMode === m
                return (
                  <button key={m} onClick={() => setLayoutMode(m)}
                    title={
                      m === 'extracted' ? 'P&ID sheet positions from extraction'
                        : m === 'process' ? 'Process-aware backbone layout'
                          : 'Dagre hierarchical layout'
                    }
                    style={{
                      padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, border: 'none',
                      background: active ? 'var(--bg-secondary)' : 'transparent',
                      color: active ? 'var(--accent)' : 'var(--text-muted)',
                      cursor: 'pointer',
                    }}>
                    {labels[m]}
                  </button>
                )
              })}
            </div>
          )}

          <span style={{ flex: 1 }} />

          {/* View / Draw toggle */}
          <div style={{ display: 'flex', gap: 2, background: 'var(--bg-tertiary)', borderRadius: 6, padding: 2, border: '1px solid var(--border)' }}>
            {([['view', 'View', '👁'], ['draw', 'Draw', '✏']] as const).map(([mode, label, icon]) => (
              <button key={mode}
                onClick={() => { setDrawMode(mode === 'draw'); setSelected(null); setPlacingKind(null) }}
                style={{
                  padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600, border: 'none',
                  background: (drawMode ? mode === 'draw' : mode === 'view') ? 'var(--bg-secondary)' : 'transparent',
                  color: (drawMode ? mode === 'draw' : mode === 'view') ? 'var(--text-primary)' : 'var(--text-muted)',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                }}>
                <span>{icon}</span> {label}
              </button>
            ))}
          </div>

          {drawMode && (
            <button className="btn btn-ghost tip" data-tip="Undo — Ctrl+Z" style={{ fontSize: 11, padding: '3px 8px' }}
              disabled={undoCount === 0}
              onClick={undo}>
              ↩ Undo{undoCount > 0 ? ` (${undoCount})` : ''}
            </button>
          )}
          {drawMode && (
            <button className="btn btn-ghost tip" data-tip="Redo — Ctrl+Shift+Z" style={{ fontSize: 11, padding: '3px 8px' }}
              disabled={redoCount === 0}
              onClick={redo}>
              ↪ Redo{redoCount > 0 ? ` (${redoCount})` : ''}
            </button>
          )}
          {showCanvas && (
            <button className="btn btn-ghost tip" data-tip="Search — Ctrl+K"
              style={{ fontSize: 11, padding: '3px 8px', display: 'flex', alignItems: 'center', gap: 5 }}
              onClick={() => window.dispatchEvent(new Event('enstudio:canvas-search'))}>
              <Search size={13} /> Search
            </button>
          )}
          {showCanvas && effectiveLayout === 'extracted' && pidBgUrl && (
            <button className="btn btn-ghost tip"
              data-tip={showPidBg ? 'Hide the source drawing' : 'Show the source drawing behind the symbols'}
              style={{
                fontSize: 11, padding: '3px 8px',
                color: showPidBg ? Theme.selection : undefined,
              }}
              onClick={() => setShowPidBg(v => !v)}>
              {showPidBg ? '▣' : '▢'} Sheet
            </button>
          )}
          {showCanvas && <FitViewButton />}
          <button className="btn btn-ghost tip" data-tip="Reload graph" style={{ fontSize: 11, padding: '3px 8px' }}
            onClick={() => loadGraph(project.id)}>↺</button>
          <LineLegend presentKinds={new Set([
            ...edgesForGraph.map(e => e.kind || 'stream'),
            ...assocEdges.map(() => 'assoc'),
            ...(isPlantView && edgesForGraph.some(e => {
              const sd = nodeDrawingOf.get(e.source) ?? ''
              const td = nodeDrawingOf.get(e.target) ?? ''
              return sd && td && sd !== td
            }) ? ['cross-drawing'] : [])
          ])} />
        </div>

        {/* ── Canvas area ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

            {/* Palette (draw mode only) */}
            {drawMode && <DrawPalette onSelectKind={setPlacingKind} placingKind={placingKind} />}

            {/* Canvas */}
            <div style={{ flex: 1, position: 'relative' }}>
              {showCanvas ? (
                <CanvasFlow
                  rfNodes={rfNodes} rfEdges={rfEdges}
                  drawMode={drawMode} project={project}
                  selected={selected} onSelect={setSelected}
                  placingKind={placingKind}
                  onPlacingDone={() => setPlacingKind(null)}
                  usePidCoords={effectiveLayout === 'extracted'}
                  pidCanvasW={pidCanvasSize.w}
                  pidCanvasH={pidCanvasSize.h}
                  pidBgUrl={pidBgUrl}
                  showPidBg={showPidBg}
                  setFocusNodeId={setFocusNodeId}
                  onGraphChanged={softReloadGraph}
                  pushUndo={pushUndo}
                  undo={undo}
                  redo={redo}
                />
              ) : (
                <div className="canvas-placeholder" style={{ height: '100%' }}>
                  <div className="canvas-placeholder-icon">⬡</div>
                  <div className="canvas-placeholder-sub">
                    {graph && graph.nodes.length === 0
                      ? 'Drop equipment from the palette to start drawing.'
                      : 'No connected nodes — all items are unlinked below.'}
                  </div>
                </div>
              )}
            </div>

            {/* Side panel — skipped for junctions, they have nothing to edit.
                Rendered from the persisted node so it can slide out on close. */}
            {panelTransition.mounted && lastPanelNode.current && (() => {
              const panelNode = lastPanelNode.current
              return (drawMode || editingNodeId === panelNode.nodeId) && project
                ? <DrawSidePanel
                  node={panelNode}
                  open={panelTransition.open}
                  projectId={project.id}
                  isExtracted={!('nodeId' in (panelNode as Record<string, unknown>))}
                  onClose={() => { setEditingNodeId(null); setSelected(null) }}
                  onSave={updated => { setEditingNodeId(null); setSelected(updated); softReloadGraph() }}
                  onDelete={() => { setEditingNodeId(null); setSelected(null); loadGraph(project.id) }}
                />
                : <SidePanel node={panelNode} projectId={project.id} open={panelTransition.open} onClose={() => setSelected(null)} onEdit={() => setEditingNodeId(String(panelNode.nodeId))} />
            })()}
          </div>

          <OrphanStrip nodes={displayOrphans} selected={selected} onSelect={selectOrphan} />
        </div>
      </div>
    </ReactFlowProvider>
  )
}
