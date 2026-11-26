import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  ReactFlow,
  Background,
  MiniMap,
  ConnectionMode,
  ReactFlowProvider,
  useReactFlow,
  useNodesState,
  useEdgesState,
  addEdge,
  reconnectEdge,
  type Node,
  type Edge,
  type Connection,
  type OnSelectionChangeParams,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  NODE_TYPES,
  equipColors,
  instrColors,
  OFFPAGE_C,
  getNodeType,
  getNodeSize,
} from '../canvas/ISANodes';
import { Theme } from '../canvas/theme';
import DrawPalette from '../canvas/DrawPalette';
import { isInstrument, isOffPage } from '../../domain/isa/instrument';
import type { GraphNode, GraphEdge, GraphData, CData } from '../../features/canvas/types';
import { nodeSize, dagreLayout } from '../../features/canvas/utils/layout';
import {
  edgeStyle,
  edgeFlowType,
  FLOW_ARROW,
  BendEdgeContext,
  pickHandles,
} from '../../features/canvas/utils/edgeHelpers';
import { BendableEdge, WaypointEdge } from '../../features/canvas/components/edges';
import { checkGraphIntegrity } from '../../features/canvas/utils/graphIntegrity';
import { FitViewButton } from '../../features/canvas/components/FitViewButton';
import { OrphanStrip } from '../../features/canvas/components/OrphanStrip';
import { SidePanel } from '../../features/canvas/components/SidePanel';
import { DrawSidePanel } from '../../features/canvas/components/DrawSidePanel';
import { TagInputModal } from '../../features/canvas/components/TagInputModal';
import { PidBgNode } from '../../features/canvas/components/PidBgNode';
import { LineLegend } from '../../features/canvas/components/LineLegend';
import { CanvasSearch } from '../../features/canvas/components/CanvasSearch';
import { takePendingFocus } from '../../features/canvas/focusBus';
import { onGraphChanged, emitGraphChanged } from '../../features/canvas/graphEvents';
import * as graphService from '../../services/pidGraphService';
import { identifyPIDAccessories } from '../../services/pidDescribeService';

import {
  MousePointer,
  PenTool,
  Search,
  Layers,
  Eye,
  EyeOff,
  Sliders,
  Sparkles,
  Maximize2,
  FileText,
} from 'lucide-react';

const EDGE_TYPES_MAP = { bendable: BendableEdge, waypoint: WaypointEdge };
const NODE_TYPES_WITH_BG = { ...NODE_TYPES, pidbg: PidBgNode } as typeof NODE_TYPES;

/** Canvas px per unit of the digitiser's frame (x 0..1000). At 5 an instrument
 *  bubble (~11 units on a scanned sheet) is the size of the canvas bubble (52px),
 *  so neighbouring symbols do not overlap and the scan lines up underneath. */
const PAGE_SCALE = 5;

/** The digitised sheet's frame, when the graph came from a drawing. */
function pageFrame(graph: { page_w?: number; page_h?: number }) {
  const w = Number(graph.page_w), h = Number(graph.page_h);
  return w > 0 && h > 0 ? { w, h } : null;
}

/** The printed line label of a connection: its line number, else size / spec. */
export function edgeLabel(e: Record<string, any>): string {
  const printed = String(e.printed_line_no || '').trim();
  if (printed) return printed;
  return [e.size, e.spec].filter(Boolean).join(' ');
}

/** How a symbol was obtained, when it was not simply read off the drawing. */
export function provenanceStyle(n: Record<string, any>): React.CSSProperties | undefined {
  if (n.inferred) return { outline: '2px dashed #f59e0b', outlineOffset: 3, borderRadius: 10 };
  if (n.recovered) return { outline: '2px dashed #38bdf8', outlineOffset: 3, borderRadius: 10 };
  if (n.untagged) return { outline: '2px dotted #94a3b8', outlineOffset: 3, borderRadius: 10, opacity: 0.85 };
  if (n.placeholder) return { outline: '1px dashed #64748b', outlineOffset: 3, borderRadius: 10 };
  return undefined;
}

interface PIDCanvasViewProps {
  graph: {
    sessionId?: string;
    projectType?: string;
    nodes: Array<{
      id: string;
      label: string;
      kind?: string;
      vendor?: string;
      area?: string;
      description?: string;
      specifications?: Record<string, any>;
      specStatus?: string;
      x?: number;
      y?: number;
      [key: string]: any;
    }>;
    edges: Array<{
      from?: string;
      source?: string;
      to?: string;
      target?: string;
      kind?: string;
      label?: string;
      bend_x?: number;
      bend_y?: number;
      [key: string]: any;
    }>;
    pageImage?: string;
    /** the digitiser's frame (x 0..page_w, y 0..page_h) when read from a drawing */
    page_w?: number;
    page_h?: number;
    warnings?: string[];
    [key: string]: any;
  };
  onSelectNode?: (node: any) => void;
  selectedNodeId?: string | null;
  bgImageUrl?: string | null;
  onGraphUpdate?: (updated: any) => void;
}

// ── Inner Canvas Component with ReactFlow Hooks ──────────────────────────────

function CanvasFlowInner({
  graph,
  onSelectNode,
  selectedNodeId,
  bgImageUrl,
  onGraphUpdate,
}: PIDCanvasViewProps) {
  const { screenToFlowPosition, fitView, setCenter } = useReactFlow();

  const sessionId = graph.sessionId || 'default';
  const [drawMode, setDrawMode] = useState<boolean>(false);
  const [placingKind, setPlacingKind] = useState<string | null>(null);
  const [selectedCData, setSelectedCData] = useState<CData | null>(null);
  const [editingNode, setEditingNode] = useState<CData | null>(null);
  const [drop, setDrop] = useState<{ kind: string; pos: { x: number; y: number } } | null>(null);

  // Background overlay options
  const [showPidBg, setShowPidBg] = useState<boolean>(false);
  const [bgOpacity, setBgOpacity] = useState<number>(0.65);
  const [showLegend, setShowLegend] = useState<boolean>(false);
  const [searchOpen, setSearchOpen] = useState<boolean>(false);

  // Layout mode
  const [layoutMode, setLayoutMode] = useState<'extracted' | 'dagre'>('extracted');
  const [inferringAccessories, setInferringAccessories] = useState<boolean>(false);

  const handleIdentifyAccessories = async (tag: string) => {
    if (!sessionId) return;
    setInferringAccessories(true);
    try {
      const res = await identifyPIDAccessories(sessionId, [tag]);
      if (res.success && res.pid_graph) {
        if (onGraphUpdate) {
          onGraphUpdate(res.pid_graph);
        }
        emitGraphChanged(sessionId);
        const updatedNode = res.pid_graph.nodes?.find((n: any) => (n.label || n.tag || n.id) === tag);
        if (updatedNode) {
          setSelectedCData(updatedNode);
        }
      }
    } catch (e: any) {
      console.error('Failed to infer accessories via Solution Agent:', e);
    } finally {
      setInferringAccessories(false);
    }
  };

  // Convert raw graph nodes & edges to React Flow elements
  const computedElements = useMemo(() => {
    const rawNodes = graph.nodes || [];
    const rawEdges = graph.edges || [];

    // Map of nodes for connection resolution
    const nodeMap = new Map<string, any>();
    rawNodes.forEach(n => {
      nodeMap.set(n.id, n);
      if (n.label) nodeMap.set(n.label, n);
    });

    // Check if layout needs to be computed
    const hasCoordinates = rawNodes.length > 0 && rawNodes.some(n => (n.x ?? 0) > 0 || (n.y ?? 0) > 0);
    // A digitised drawing: x/y are the symbol's centre on the sheet, in the
    // digitiser's frame. Place each node's centre there, at PAGE_SCALE.
    const frame = pageFrame(graph);

    let positions = new Map<string, { x: number; y: number }>();

    if (!hasCoordinates || layoutMode === 'dagre') {
      const gNodes: GraphNode[] = rawNodes.map(n => ({
        id: n.id,
        label: n.label || n.id,
        kind: n.kind || 'instrument',
        x: n.x ?? 0,
        y: n.y ?? 0,
        area: n.area,
      }));
      const gEdges: GraphEdge[] = rawEdges.map(e => ({
        source: e.source || e.from || '',
        target: e.target || e.to || '',
        kind: e.kind || 'stream',
      }));
      positions = dagreLayout(gNodes, gEdges, [], new Map());
    }

    const rfNodes: Node<CData>[] = rawNodes.map((n, idx) => {
      const tag = n.label || n.id;
      const kind = n.kind || 'transmitter';
      const type = getNodeType(kind, tag, isOffPage(kind, tag));
      let nodePos = positions.get(n.id);
      if (!nodePos && frame && n.x != null && n.y != null) {
        const size = getNodeSize(type);
        nodePos = { x: n.x * PAGE_SCALE - size.w / 2, y: n.y * PAGE_SCALE - size.h / 2 };
      }
      nodePos = nodePos || {
        x: n.x ?? (idx % 6) * 160 + 80,
        y: n.y ?? Math.floor(idx / 6) * 140 + 80,
      };

      const cData: CData = {
        nodeId: n.id,
        id: n.id,
        label: tag,
        kind,
        kind_detail: n.kind_detail || kind,
        area: n.area || '',
        drawing: 'DRAW',
        equipment_ref: n.equipment_ref || '',
        softChildren: [],
        vendor: n.vendor,
        specifications: n.specifications,
        specStatus: n.specStatus,
        description: n.description,
        loop: n.loop,
        inferred: !!n.inferred,
        untagged: !!n.untagged,
        placeholder: !!n.placeholder,
        snapped: !!n.snapped,
        recovered: !!n.recovered,
        source: n.source,
      };

      const isNodeSelected = n.id === selectedNodeId || selectedCData?.id === n.id;

      return {
        id: n.id,
        type,
        position: { x: nodePos.x, y: nodePos.y },
        selected: isNodeSelected,
        data: cData,
        style: provenanceStyle(n),
      };
    });

    // Ensure nodes never collide or overlap visually on the canvas. A digitised
    // drawing keeps its measured positions: they are where the symbols are printed.
    if (layoutMode === 'extracted' && !frame) {
      const adjustedPositions = new Map<string, { x: number; y: number }>();
      rfNodes.forEach(n => adjustedPositions.set(n.id, { x: n.position.x, y: n.position.y }));

      for (let iter = 0; iter < 10; iter++) {
        let moved = false;
        for (let i = 0; i < rfNodes.length; i++) {
          for (let j = i + 1; j < rfNodes.length; j++) {
            const n1 = rfNodes[i];
            const n2 = rfNodes[j];
            const p1 = adjustedPositions.get(n1.id)!;
            const p2 = adjustedPositions.get(n2.id)!;
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            // Vessels and columns need larger vertical separation
            const isLarge1 = n1.data.kind === 'column' || n1.data.kind === 'vessel';
            const isLarge2 = n2.data.kind === 'column' || n2.data.kind === 'vessel';
            const minSeparation = isLarge1 && isLarge2 ? 150 : 85;

            if (dist < minSeparation) {
              moved = true;
              const diff = minSeparation - dist;
              const angle = dist > 0 ? Math.atan2(dy, dx) : (i * 1.2);
              const shiftX = (Math.cos(angle) * diff) / 2;
              const shiftY = (Math.sin(angle) * diff) / 2;
              p1.x -= shiftX;
              p1.y -= shiftY;
              p2.x += shiftX;
              p2.y += shiftY;
            }
          }
        }
        if (!moved) break;
      }

      rfNodes.forEach(n => {
        const adj = adjustedPositions.get(n.id);
        if (adj) {
          n.position = { x: Math.round(adj.x), y: Math.round(adj.y) };
        }
      });
    }

    const rfEdges: Edge[] = rawEdges
      .map((e, idx) => {
        const fromId = String(e.source || e.from || '').trim();
        const toId = String(e.target || e.to || '').trim();
        if (!fromId || !toId) return null;

        const kind = e.kind || 'stream';
        const handles = pickHandles(rfNodes, fromId, toId);

        const edgeData: Record<string, any> = {
          kind,
          routeVertical: handles.sourceHandle === 'st' || handles.sourceHandle === 'sb',
          label: edgeLabel(e),
          lineId: e.line_id || e.label,
          size: e.size,
          spec: e.spec,
          fluid: e.fluid,
          note: e.note,
        };

        if (e.bend_x != null && e.bend_y != null) {
          edgeData.bend = { x: e.bend_x, y: e.bend_y };
        }

        return {
          id: `e-${fromId}-${toId}-${idx}`,
          source: fromId,
          target: toId,
          ...handles,
          type: 'bendable',
          style: edgeStyle(kind),
          data: edgeData,
          markerEnd: FLOW_ARROW,
        };
      })
      .filter((e): e is Edge => e !== null);

    return { rfNodes, rfEdges };
  }, [graph, selectedNodeId, selectedCData?.id, layoutMode]);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CData>>(computedElements.rfNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(computedElements.rfEdges);

  // Sync state when elements change
  useEffect(() => {
    setNodes(computedElements.rfNodes);
    setEdges(computedElements.rfEdges);
  }, [computedElements, setNodes, setEdges]);

  // Initial fit view
  useEffect(() => {
    const timer = setTimeout(() => {
      fitView({ padding: 0.15, duration: 400 });
    }, 120);
    return () => clearTimeout(timer);
  }, [fitView, graph.sessionId]);

  // Listen to camera focus requests (from search or Copilot tags)
  useEffect(() => {
    const handleFocus = () => {
      const tag = takePendingFocus();
      if (!tag) return;
      const targetNode = nodes.find(
        n =>
          n.id.toLowerCase() === tag.toLowerCase() ||
          String(n.data?.label).toLowerCase() === tag.toLowerCase()
      );
      if (targetNode) {
        setCenter(targetNode.position.x + 40, targetNode.position.y + 30, {
          zoom: 1.4,
          duration: 600,
        });
        setNodes(nds =>
          nds.map(n => ({
            ...n,
            selected: n.id === targetNode.id,
          }))
        );
        setSelectedCData(targetNode.data as CData);
        if (onSelectNode) onSelectNode(targetNode.data);
      }
    };

    window.addEventListener('engenie:canvas-focus', handleFocus);
    return () => window.removeEventListener('engenie:canvas-focus', handleFocus);
  }, [nodes, setCenter, setNodes, onSelectNode]);

  // Listen to graph changed events
  useEffect(() => {
    const unsubscribe = onGraphChanged(() => {
      // Reload graph from storage if available
      try {
        const stored = localStorage.getItem('active_pid_graph');
        if (stored && onGraphUpdate) {
          onGraphUpdate(JSON.parse(stored));
        }
      } catch {}
    });
    return unsubscribe;
  }, [onGraphUpdate]);

  // Connecting pipes in Draw Mode
  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      const handles = pickHandles(nodes, conn.source, conn.target);
      const kind = 'stream';
      const newEdge: Edge = {
        id: `e-${conn.source}-${conn.target}-${Date.now()}`,
        source: conn.source,
        target: conn.target,
        ...handles,
        type: 'bendable',
        style: edgeStyle(kind),
        data: { kind },
        markerEnd: FLOW_ARROW,
      };
      setEdges(eds => addEdge(newEdge, eds));
      graphService.insertEdgeById(sessionId, conn.source, conn.target, kind).catch(console.error);
    },
    [nodes, sessionId, setEdges]
  );

  // Dragging bend corners
  const onBendDrag = useCallback(
    (edgeId: string, source: string, target: string, clientX: number, clientY: number, commit: boolean) => {
      const pos = screenToFlowPosition({ x: clientX, y: clientY });
      setEdges(prev =>
        prev.map(e => (e.id === edgeId ? { ...e, data: { ...(e.data as object), bend: pos } } : e))
      );
      if (commit) {
        graphService.updateEdgeBend(sessionId, source, target, pos.x, pos.y).catch(console.error);
      }
    },
    [screenToFlowPosition, sessionId, setEdges]
  );

  const bendCtx = useMemo(() => ({ drawMode, onBendDrag }), [drawMode, onBendDrag]);

  // Click on node to inspect
  const onNodeClick = useCallback(
    (_: any, node: Node) => {
      if (node.type === 'pidbg') return;
      const cdata = node.data as CData;
      setSelectedCData(cdata);
      if (onSelectNode) onSelectNode(cdata);
    },
    [onSelectNode]
  );

  // Click on empty pane
  const onPaneClick = useCallback(
    (e: React.MouseEvent) => {
      if (placingKind && drawMode) {
        const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY });
        setDrop({ kind: placingKind, pos });
        setPlacingKind(null);
      } else {
        setSelectedCData(null);
      }
    },
    [placingKind, drawMode, screenToFlowPosition]
  );

  // Tag confirm after drop
  const onTagConfirmed = (kind: string, tag: string, nodeId: string, pos: { x: number; y: number }) => {
    const cData: CData = {
      nodeId,
      id: nodeId,
      label: tag,
      kind,
      kind_detail: kind,
      area: '',
      drawing: 'DRAW',
      equipment_ref: '',
      softChildren: [],
    };
    const newNode: Node<CData> = {
      id: nodeId,
      type: getNodeType(kind, tag, isOffPage(kind, tag)),
      position: pos,
      data: cData,
    };
    setNodes(nds => [...nds, newNode]);
    graphService.updateNodePosition(sessionId, nodeId, pos.x, pos.y).catch(console.error);
    setDrop(null);
  };

  // Integrity Check for orphans
  const integrity = useMemo(() => {
    const gNodes: GraphNode[] = nodes
      .filter(n => n.type !== 'pidbg')
      .map(n => ({
        id: n.id,
        label: String(n.data?.label || n.id),
        kind: String(n.data?.kind || 'instrument'),
        x: n.position.x,
        y: n.position.y,
      }));
    const gEdges: GraphEdge[] = edges.map(e => ({
      source: e.source,
      target: e.target,
      kind: String(e.data?.kind || 'stream'),
    }));
    return checkGraphIntegrity(gNodes, gEdges);
  }, [nodes, edges]);

  // Compute unconnected / orphan nodes
  const orphanNodes = useMemo(() => {
    const connectedNodeIds = new Set<string>();
    edges.forEach(e => {
      if (e.source) connectedNodeIds.add(e.source);
      if (e.target) connectedNodeIds.add(e.target);
    });

    return nodes
      .filter(n => n.type !== 'pidbg' && !connectedNodeIds.has(n.id))
      .map(n => ({
        id: n.id,
        label: String(n.data?.label || n.id),
        kind: String(n.data?.kind || 'instrument'),
        x: n.position.x,
        y: n.position.y,
        area: n.data?.area,
      } as GraphNode));
  }, [nodes, edges]);

  // A digitised drawing opens over its own scan, so each symbol can be checked
  // against what is printed beneath it.
  const frame = pageFrame(graph);
  const bgUrl = bgImageUrl || graph.pageImage;
  useEffect(() => {
    if (frame && bgUrl) {
      setShowPidBg(true);
      setBgOpacity(0.35);
    }
  }, [graph.sessionId, graph.pid, !!frame, bgUrl]);

  // Inject background node if showPidBg is active
  const nodesForRF = useMemo(() => {
    const base = nodes;
    const activeBgUrl = bgUrl;
    if (showPidBg && activeBgUrl) {
      // the scan is stretched to the digitiser's frame, which is where the
      // node positions were measured; older graphs keep the legacy size
      const w = frame ? frame.w * PAGE_SCALE : 2800;
      const h = frame ? frame.h * PAGE_SCALE : 2000;
      const bgNode = {
        id: '__pidbg__',
        type: 'pidbg',
        position: { x: 0, y: 0 },
        data: { url: activeBgUrl, w, h, opacity: bgOpacity },
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
        zIndex: -1,
      } as unknown as Node<CData>;
      return [bgNode, ...base];
    }
    return base;
  }, [nodes, showPidBg, bgUrl, bgOpacity, frame?.w, frame?.h]);

  const presentKinds = useMemo(
    () => new Set(edges.map(e => String((e.data as any)?.kind || 'process'))),
    [edges],
  );
  const warnings: string[] = Array.isArray(graph.warnings) ? graph.warnings : [];
  const [warningsOpen, setWarningsOpen] = useState<boolean>(true);

  return (
    <div className="relative w-full h-full bg-[#050914] overflow-hidden select-none flex">
      {/* Optional Draw Palette sidebar on the left */}
      {drawMode && (
        <DrawPalette
          onSelectKind={kind => setPlacingKind(kind)}
          placingKind={placingKind}
        />
      )}

      {/* Main React Flow Canvas Area */}
      <div className="relative flex-1 h-full min-w-0">
        {/* Floating Top Controls Toolbar */}
        <div className="absolute top-3 left-4 z-20 flex items-center gap-1.5 p-1 rounded-xl bg-slate-900/90 border border-slate-700/80 shadow-2xl backdrop-blur-md text-xs">
          {/* Mode Switch: View vs Draw */}
          <div className="flex items-center rounded-lg bg-slate-950/80 p-0.5 border border-slate-800">
            <button
              type="button"
              onClick={() => {
                setDrawMode(false);
                setPlacingKind(null);
              }}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                !drawMode
                  ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                  : 'text-slate-400 hover:text-white'
              }`}
              title="Pan, Zoom & Inspect Mode"
            >
              <MousePointer size={13} />
              <span>Inspect</span>
            </button>
            <button
              type="button"
              onClick={() => setDrawMode(true)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                drawMode
                  ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                  : 'text-slate-400 hover:text-white'
              }`}
              title="Place Equipment & Draw Process Lines"
            >
              <PenTool size={13} />
              <span>Draw</span>
            </button>
          </div>

          <div className="h-4 w-[1px] bg-slate-700 mx-0.5" />

          {/* Search Trigger */}
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
            title="Search Equipment (Ctrl+K)"
          >
            <Search size={13} className="text-sky-400" />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden sm:inline px-1 py-0.2 text-[9px] bg-slate-800 border border-slate-700 rounded font-mono text-slate-400">
              ⌘K
            </kbd>
          </button>

          {/* Line Legend Toggle */}
          <button
            type="button"
            onClick={() => setShowLegend(v => !v)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg transition-colors ${
              showLegend ? 'bg-slate-800 text-white font-medium' : 'text-slate-400 hover:text-white'
            }`}
            title="Piping & Signal Line Legend"
          >
            <Layers size={13} />
            <span className="hidden sm:inline">Legend</span>
          </button>

          {/* Background Overlay Toggle */}
          <button
            type="button"
            onClick={() => setShowPidBg(v => !v)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg transition-colors ${
              showPidBg
                ? 'bg-sky-500/20 border border-sky-500/40 text-sky-400 font-medium'
                : 'text-slate-400 hover:text-white'
            }`}
            title="Toggle Scanned P&ID Background Overlay"
          >
            {showPidBg ? <Eye size={13} /> : <EyeOff size={13} />}
            <span className="hidden sm:inline">Background Scan</span>
          </button>

          {/* Opacity slider when background scan is on */}
          {showPidBg && (
            <div className="flex items-center gap-1.5 px-2 text-[11px] text-slate-400">
              <span>Dim:</span>
              <input
                type="range"
                min="0.1"
                max="1"
                step="0.05"
                value={bgOpacity}
                onChange={e => setBgOpacity(parseFloat(e.target.value))}
                className="w-16 h-1 accent-primary cursor-pointer"
              />
            </div>
          )}

          {/* Layout Switcher */}
          <button
            type="button"
            onClick={() => setLayoutMode(m => (m === 'dagre' ? 'extracted' : 'dagre'))}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-slate-400 hover:text-white transition-colors ${
              layoutMode === 'dagre' ? 'bg-slate-800 text-amber-400' : ''
            }`}
            title="Toggle Auto Hierarchical Layout"
          >
            <Maximize2 size={13} />
            <span className="hidden sm:inline">{layoutMode === 'dagre' ? 'Auto Hierarchical' : 'Schematic Layout'}</span>
          </button>
        </div>

        {/* Placing Banner */}
        {placingKind && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 z-30 px-3.5 py-1.5 rounded-full bg-primary text-primary-foreground font-semibold text-xs shadow-xl animate-in fade-in slide-in-from-top-2 duration-200">
            Click anywhere on the canvas to place {placingKind.replace(/_/g, ' ')}
          </div>
        )}

        {/* Orphan Equipment Strip */}
        <OrphanStrip
          nodes={orphanNodes}
          selected={selectedCData}
          onSelect={node => {
            const target = nodes.find(n => n.id === node.id);
            if (target) {
              setCenter(target.position.x + 30, target.position.y + 20, { zoom: 1.3, duration: 500 });
              setSelectedCData(target.data as CData);
              if (onSelectNode) onSelectNode(target.data);
            }
          }}
        />

        {/* Quick Search Modal */}
        <CanvasSearch
          nodes={nodes}
          isOpen={searchOpen}
          onClose={() => setSearchOpen(false)}
          onPick={tag => {
            const node = nodes.find(n => n.data?.label === tag || n.id === tag);
            if (node) {
              setCenter(node.position.x + 30, node.position.y + 20, { zoom: 1.3, duration: 500 });
              setSelectedCData(node.data as CData);
              if (onSelectNode) onSelectNode(node.data);
            }
            setSearchOpen(false);
          }}
        />

        {/* Line Style Legend */}
        {showLegend && (
          <div className="absolute top-16 left-4 z-30">
            <LineLegend presentKinds={presentKinds} open />
          </div>
        )}

        {/* What the digitiser asks the engineer to confirm (inferred valves, unread areas) */}
        {warnings.length > 0 && warningsOpen && (
          <div className="absolute bottom-4 left-4 z-30 max-w-md p-3 rounded-xl bg-amber-950/90 border border-amber-500/40 text-[11px] text-amber-100 shadow-2xl">
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-bold text-amber-300 uppercase tracking-wider text-[10px]">
                Please review ({warnings.length})
              </span>
              <button type="button" onClick={() => setWarningsOpen(false)}
                className="text-amber-300 hover:text-white" title="Hide">×</button>
            </div>
            <ul className="space-y-1 list-disc pl-4">
              {warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        )}

        {/* Tag Input Modal on Placement */}
        {drop && (
          <TagInputModal
            kind={drop.kind}
            sessionId={sessionId}
            onDone={(tag, nodeId) => onTagConfirmed(drop.kind, tag, nodeId, drop.pos)}
            onCancel={() => setDrop(null)}
          />
        )}

        {/* React Flow Component */}
        <BendEdgeContext.Provider value={bendCtx}>
          <ReactFlow
            nodes={nodesForRF}
            edges={edges}
            nodeTypes={NODE_TYPES_WITH_BG}
            edgeTypes={EDGE_TYPES_MAP}
            onNodesChange={drawMode ? onNodesChange : undefined}
            onEdgesChange={drawMode ? onEdgesChange : undefined}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onConnect={drawMode ? onConnect : undefined}
            nodesDraggable={drawMode}
            nodesConnectable={drawMode}
            connectionMode={ConnectionMode.Loose}
            deleteKeyCode={null}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.1}
            maxZoom={4}
            className="bg-[#050914]"
          >
            <Background color="#1e293b" gap={28} size={1} />
            <MiniMap
              nodeColor={n => {
                const d = n.data as CData;
                const k = String(d?.kind || '');
                if (isInstrument(k)) return instrColors(String(d?.label || '')).border;
                return equipColors(k).border;
              }}
              style={{
                backgroundColor: '#090d16',
                border: '1px solid #1e293b',
                borderRadius: 12,
                overflow: 'hidden',
              }}
              maskColor="rgba(5, 9, 20, 0.75)"
            />
            <FitViewButton />
          </ReactFlow>
        </BendEdgeContext.Provider>
      </div>

      {/* Inspector Side Panel */}
      {selectedCData && !editingNode && (
        <SidePanel
          node={selectedCData}
          sessionId={sessionId}
          open={!!selectedCData}
          onClose={() => setSelectedCData(null)}
          onEdit={() => setEditingNode(selectedCData)}
          onIdentifyAccessories={handleIdentifyAccessories}
          inferringAccessories={inferringAccessories}
          connections={edges
            .filter(e => e.source === selectedCData.id || e.target === selectedCData.id)
            .map(e => {
              const outgoing = e.source === selectedCData.id;
              const otherId = outgoing ? e.target : e.source;
              const other = nodes.find(n => n.id === otherId);
              return {
                other: String(other?.data?.label || otherId),
                kind: String((e.data as any)?.kind || 'process'),
                label: (e.data as any)?.label,
                outgoing,
              };
            })}
        />
      )}

      {/* Property Edit Side Panel */}
      {editingNode && (
        <DrawSidePanel
          node={editingNode}
          sessionId={sessionId}
          open={!!editingNode}
          onClose={() => setEditingNode(null)}
          onSave={updated => {
            setNodes(nds =>
              nds.map(n => (n.id === updated.id ? { ...n, data: updated } : n))
            );
            setSelectedCData(updated);
            setEditingNode(null);
            emitGraphChanged(sessionId);
          }}
          onDelete={() => {
            setNodes(nds => nds.filter(n => n.id !== editingNode.id));
            setEdges(eds => eds.filter(e => e.source !== editingNode.id && e.target !== editingNode.id));
            setSelectedCData(null);
            setEditingNode(null);
            emitGraphChanged(sessionId);
          }}
        />
      )}
    </div>
  );
}

// ── Exported Wrapper with ReactFlowProvider ──────────────────────────────────

export default function PIDCanvasView(props: PIDCanvasViewProps) {
  return (
    <ReactFlowProvider>
      <CanvasFlowInner {...props} />
    </ReactFlowProvider>
  );
}
