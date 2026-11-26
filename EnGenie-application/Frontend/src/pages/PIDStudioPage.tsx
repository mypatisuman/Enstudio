import React, { useState, useRef, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { 
    ArrowLeft, 
    ZoomIn, 
    ZoomOut, 
    RotateCcw, 
    Download, 
    Sliders, 
    Layers, 
    Search,
    Compass,
    ExternalLink,
    Copy,
    Check,
    FileText,
    Settings,
    Maximize2,
    MousePointer,
    Move,
    Activity,
    Building2,
    ShieldCheck,
    Cpu,
    Gauge,
    Wrench,
    Zap,
    Link2,
    Sparkles,
    UploadCloud,
    Network
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import PIDDecisionPanel, { specSourceLabel } from '@/components/PIDStudio/PIDDecisionPanel';
import { getActivePid } from '@/components/AIRecommender/api';
import PIDCanvasView from '@/components/PIDStudio/PIDCanvasView';
import PIDDescribeDrawer from '@/components/PIDStudio/PIDDescribeDrawer';
import PIDIngestModal from '@/components/PIDStudio/PIDIngestModal';


interface PIDNode {
    id: string;
    label: string;
    kind: string;
    description?: string;
    area?: string;
    isTieIn?: boolean;
    is_tie_in?: boolean;
    vendor?: string;
    modelFamily?: string;
    model_family?: string;
    modelSeries?: string;
    model_series?: string;
    modelNumber?: string;
    model_number?: string;
    standards?: string[];
    parentInstrumentTag?: string;
    parent_instrument_tag?: string;
    specifications?: Record<string, any>;
    categorizedSpecs?: Record<string, Record<string, any>>;
    categorized_specs?: Record<string, Record<string, any>>;
    // Where the specifications came from: asset_inventory | stated |
    // bom_selection | unspecified (never invented).
    specStatus?: string;
    spec_status?: string;
    loop?: string;
    x?: number;
    y?: number;
}

interface PIDEdge {
    from: string;
    to: string;
    kind?: string;
    label?: string;
}

interface PIDSubsystemArea {
    name: string;
    min_x?: number;
    max_x?: number;
    min_y?: number;
    max_y?: number;
    node_count?: number;
}

interface PIDGraph {
    projectType?: string;
    project_type?: string;
    summary?: string;
    nodes: PIDNode[];
    edges: PIDEdge[];
    svgPreview?: string;
    svg_preview?: string;
    subsystemAreas?: PIDSubsystemArea[];
    subsystem_areas?: PIDSubsystemArea[];
    // Persisted drawing: decisions (confirm / clarify) name the revision.
    sessionId?: string;
    revision?: number;
    pendingAction?: Record<string, any> | null;
    generationPath?: string;
    validation?: Record<string, any>;
    specStatusCounts?: Record<string, number>;
    notes?: string[];
}

export default function PIDStudioPage() {
    const location = useLocation();
    const navigate = useNavigate();

    // Ingest state from navigation, localStorage, or sessionStorage
    const navState = location.state as {
        pidGraph?: PIDGraph;
        designedSolution?: any;
        solutionTitle?: string;
    } | null;

    const [pidGraph, setPidGraph] = useState<PIDGraph | null>(() => {
        if (navState?.pidGraph) return navState.pidGraph;
        try {
            const fromLocal = localStorage.getItem('active_pid_graph');
            if (fromLocal) return JSON.parse(fromLocal);
            const fromSession = sessionStorage.getItem('active_pid_graph');
            if (fromSession) return JSON.parse(fromSession);
        } catch (e) {
            console.error('Failed to parse saved P&ID graph:', e);
        }
        return null;
    });

    const [solutionTitle, setSolutionTitle] = useState<string>(() => {
        if (navState?.solutionTitle) return navState.solutionTitle;
        return localStorage.getItem('active_solution_title') || sessionStorage.getItem('active_solution_title') || 'Engineering Solution P&ID';
    });

    const [zoom, setZoom] = useState<number>(1);
    const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
    const [isPanMode, setIsPanMode] = useState<boolean>(false);
    const [isDragging, setIsDragging] = useState<boolean>(false);
    const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
    const [selectedNode, setSelectedNode] = useState<PIDNode | null>(null);
    const [isInspectorOpen, setIsInspectorOpen] = useState<boolean>(true);
    const [activeAreaFilter, setActiveAreaFilter] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState<string>('');
    const [copiedTag, setCopiedTag] = useState<string | null>(null);
    const [viewMode, setViewMode] = useState<'flow' | 'svg'>('flow');
    const [isDescribeOpen, setIsDescribeOpen] = useState<boolean>(false);
    const [isIngestOpen, setIsIngestOpen] = useState<boolean>(false);
    const [quickPrompt, setQuickPrompt] = useState<string>('');

    const containerRef = useRef<HTMLDivElement>(null);
    const svgWrapperRef = useRef<HTMLDivElement>(null);
    const isDragCandidate = useRef<boolean>(false);
    const hasMoved = useRef<boolean>(false);

    // Save to session & local storage for refresh persistence
    useEffect(() => {
        if (navState?.pidGraph) {
            sessionStorage.setItem('active_pid_graph', JSON.stringify(navState.pidGraph));
            localStorage.setItem('active_pid_graph', JSON.stringify(navState.pidGraph));
        }
        if (navState?.solutionTitle) {
            sessionStorage.setItem('active_solution_title', navState.solutionTitle);
            localStorage.setItem('active_solution_title', navState.solutionTitle);
        }
    }, [navState]);

    const [highlightUnspecified, setHighlightUnspecified] = useState<boolean>(false);

    // The one place the drawing is replaced after an engineer decision or a
    // refresh: state, the storage a reload reads, and the selection (which is
    // dropped if its node was removed).
    const updatePidGraph = React.useCallback((next: PIDGraph) => {
        setPidGraph(next);
        setSelectedNode(prev => (prev && next.nodes?.find(n => n.id === prev.id)) || null);
        try {
            const json = JSON.stringify(next);
            sessionStorage.setItem('active_pid_graph', json);
            localStorage.setItem('active_pid_graph', json);
        } catch (e) {
            console.error('Failed to save P&ID graph:', e);
        }
    }, []);

    // A persisted drawing may have moved on since this tab's copy was stored
    // (a later solution turn, another tab, a decision taken elsewhere), so the
    // current revision is fetched once when the studio opens.
    const persistedSessionId = pidGraph?.sessionId;
    useEffect(() => {
        if (!persistedSessionId) return;
        let cancelled = false;
        getActivePid(persistedSessionId).then(res => {
            if (!cancelled && res.success && res.pidGraph &&
                typeof res.pidGraph.revision === 'number' && res.pidGraph.revision !== pidGraph?.revision) {
                updatePidGraph(res.pidGraph);
            }
        });
        return () => { cancelled = true; };
        // Only on open / when the session changes; decisions update the graph directly.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [persistedSessionId]);

// High-Precision Vector ISA-5.1 SVG Generator with Strict 3-Layer Z-Index Architecture
function generateCleanPIDDiagramSvg(
    nodes: PIDNode[],
    edges: PIDEdge[],
    subsystemAreas: any[],
    projectType: string = 'greenfield'
): string {
    const nodeMap = new Map<string, PIDNode>();
    nodes.forEach(n => {
        if (n.id) {
            nodeMap.set(n.id, n);
            nodeMap.set(n.id.toLowerCase(), n);
            nodeMap.set(n.id.toUpperCase(), n);
        }
        if (n.label) {
            nodeMap.set(n.label, n);
            nodeMap.set(n.label.toLowerCase(), n);
            nodeMap.set(n.label.toUpperCase(), n);
        }
    });

    const nodeXs = nodes.map(n => n.x ?? 0).filter(x => x > 0);
    const nodeYs = nodes.map(n => n.y ?? 0).filter(y => y > 0);
    const areaMaxXs = (subsystemAreas || []).map(a => (a.x || 0) + (a.width || 0));
    const areaMaxYs = (subsystemAreas || []).map(a => (a.y || 0) + (a.height || 0));

    const maxX = Math.max(...nodeXs, ...areaMaxXs, 900);
    const maxY = Math.max(...nodeYs, ...areaMaxYs, 540);

    const width = Math.round(maxX + 80);
    const height = Math.round(maxY + 60);

    const isBrownfield = projectType.toLowerCase() === 'brownfield';
    const badgeBg = isBrownfield ? '#fef3c7' : '#e0f2fe';
    const badgeBorder = isBrownfield ? '#d97706' : '#0284c7';
    const badgeTextColor = isBrownfield ? '#92400e' : '#0369a1';
    const badgeLabel = isBrownfield ? 'BROWNFIELD RETROFIT (ASSETS BOUND)' : 'GREENFIELD DESIGN (CLEAN-SHEET P&ID)';

    const svgParts: string[] = [
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" style="width:100%; height:auto; background:#ffffff; font-family:Inter, ui-sans-serif, system-ui, sans-serif; user-select:none;">`,
        `<defs>`,
        `  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">`,
        `    <path d="M 0 1 L 10 5 L 0 9 z" fill="#0f172a" />`,
        `  </marker>`,
        `  <marker id="arrow-impulse" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">`,
        `    <path d="M 0 1 L 10 5 L 0 9 z" fill="#0284c7" />`,
        `  </marker>`,
        `  <filter id="shadow" x="-8%" y="-8%" width="120%" height="120%">`,
        `    <feDropShadow dx="1" dy="2" stdDeviation="2" flood-color="#0f172a" flood-opacity="0.08" />`,
        `  </filter>`,
        `</defs>`,
        `<pattern id="grid-pat" width="40" height="40" patternUnits="userSpaceOnUse">`,
        `  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#f1f5f9" stroke-width="1"/>`,
        `</pattern>`,
        `<rect width="${width}" height="${height}" fill="url(#grid-pat)" />`,
        `<g transform="translate(30, 20)">`,
        `  <rect width="330" height="28" rx="6" fill="${badgeBg}" stroke="${badgeBorder}" stroke-width="1.2" />`,
        `  <circle cx="16" cy="14" r="4.5" fill="${badgeBorder}" />`,
        `  <text x="30" y="18.5" font-size="11" font-weight="700" fill="${badgeTextColor}" letter-spacing="0.5">${badgeLabel}</text>`,
        `</g>`,
        `<!-- Sub-system Area Bounding Boxes -->`
    ];

    for (const area of (subsystemAreas || [])) {
        const ax = area.x || 0;
        const ay = area.y || 68;
        const aw = area.width || 220;
        const ah = area.height || 600;
        const aname = area.name || 'Sub-system';
        const aid = (area.id || '').toUpperCase();
        const cleanTitle = `${aid}: ${aname.toUpperCase().slice(0, 28)}`;
        const pillW = Math.min(cleanTitle.length * 7.2 + 20, aw - 24);

        svgParts.push(
            `<rect x="${ax}" y="${ay}" width="${aw}" height="${ah}" rx="12" fill="#f8fafc" fill-opacity="0.45" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="6,4" />`,
            `<rect x="${ax + 10}" y="${ay + 10}" width="${pillW}" height="22" rx="4" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1" />`,
            `<text x="${ax + 16}" y="${ay + 25}" font-size="9.5" font-weight="700" fill="#475569" letter-spacing="0.3">${cleanTitle}</text>`
        );
    }

    svgParts.push(`<!-- Process & Signal Edges (Layer 1: Base Stream & Signal Paths) -->`);
    const edgePaths: string[] = [];
    const edgeLabels: string[] = [];

    for (const e of edges) {
        const fromKey = String((e as any).from || (e as any).from_id || (e as any).fromId || (e as any).source || '').trim();
        const toKey = String((e as any).to || (e as any).to_id || (e as any).toId || (e as any).target || '').trim();
        if (!fromKey || !toKey) continue;

        const fNode = nodeMap.get(fromKey) || nodeMap.get(fromKey.toLowerCase()) || nodeMap.get(fromKey.toUpperCase());
        const tNode = nodeMap.get(toKey) || nodeMap.get(toKey.toLowerCase()) || nodeMap.get(toKey.toUpperCase());
        if (!fNode || !tNode) continue;

        const fx = fNode.x ?? 0;
        const fy = fNode.y ?? 0;
        const tx = tNode.x ?? 0;
        const ty = tNode.y ?? 0;
        const kind = e.kind || 'stream';

        let stroke = '#64748b';
        let strokeWidth = '2';
        let dash = 'stroke-dasharray="4,4"';
        let marker = '';

        if (kind === 'stream') {
            stroke = '#0f172a';
            strokeWidth = '3.5';
            dash = '';
            marker = 'marker-end="url(#arrow)"';
        } else if (kind === 'impulse') {
            stroke = '#0284c7';
            strokeWidth = '1.75';
            dash = '';
            marker = 'marker-end="url(#arrow-impulse)"';
        } else if (kind === 'signal') {
            stroke = '#d97706';
            strokeWidth = '1.75';
            dash = 'stroke-dasharray="5,4"';
            marker = '';
        } else if (kind === 'pneumatic') {
            stroke = '#059669';
            strokeWidth = '1.75';
            dash = 'stroke-dasharray="8,3,2,3"';
            marker = '';
        } else if (kind === 'relief') {
            stroke = '#dc2626';
            strokeWidth = '2.5';
            dash = 'stroke-dasharray="4,2"';
            marker = 'marker-end="url(#arrow)"';
        }

        let d = '';
        let mx = 0;
        let my = 0;

        if (Math.abs(fy - ty) < 5) {
            d = `M ${fx} ${fy} L ${tx} ${ty}`;
            mx = (fx + tx) / 2;
            my = fy - 22; // Clear 22px buffer above line
        } else if (Math.abs(fx - tx) < 5) {
            d = `M ${fx} ${fy} L ${tx} ${ty}`;
            mx = fx + 24;
            my = (fy + ty) / 2;
        } else {
            const midX = fx + (tx - fx) * 0.5;
            d = `M ${fx} ${fy} L ${midX} ${fy} L ${midX} ${ty} L ${tx} ${ty}`;
            mx = midX;
            my = (fy + ty) / 2;
        }

        edgePaths.push(`<path d="${d}" fill="none" stroke="${stroke}" stroke-width="${strokeWidth}" ${dash} ${marker} />`);

        if (e.label) {
            const rawLabel = String(e.label).trim();
            const displayLabel = rawLabel.slice(0, 28);
            const lblW = displayLabel.length * 6.8 + 18;

            edgeLabels.push(
                `<g class="edge-label">` +
                `<rect x="${mx - lblW / 2}" y="${my - 10}" width="${lblW}" height="20" rx="4" fill="#ffffff" stroke="${stroke}" stroke-width="1.2" opacity="1" filter="url(#shadow)" />` +
                `<text x="${mx}" y="${my + 3.5}" font-size="9" fill="${stroke}" text-anchor="middle" font-weight="700">${displayLabel}</text>` +
                `</g>`
            );
        }
    }

    svgParts.push(...edgePaths);
    svgParts.push(`<!-- Edge Labels & Stream Badges (Layer 2: Rendered Over Paths to Prevent Line Clipping) -->`);
    svgParts.push(...edgeLabels);

    svgParts.push(`<!-- P&ID Nodes (Layer 3: Solid-Filled Equipment & Sensing Elements on Top) -->`);

    for (const n of nodes) {
        const x = n.x ?? 0;
        const y = n.y ?? 0;
        const tag = n.label || '';
        const kind = n.kind || 'transmitter';
        const isTieIn = n.isTieIn || n.is_tie_in || kind === 'tie_in';
        const specs = n.specifications || {};

        const tooltipLines = [`TAG: ${tag} [${kind.toUpperCase()}]`];
        if (n.description) tooltipLines.push(`Function: ${n.description}`);
        // A device bound from the Assets Table keeps its own nameplate in
        // specifications (BOM enrichment leaves it alone), so fall back to it.
        const vendor = n.vendor || specs.manufacturer;
        const modelSeries = n.modelSeries || n.model_series || specs.model;
        const specStatus = n.specStatus || n.spec_status || '';
        if (vendor) tooltipLines.push(`Vendor (OEM): ${vendor}`);
        if (n.modelFamily || n.model_family) tooltipLines.push(`Model Family: ${n.modelFamily || n.model_family}`);
        if (modelSeries) tooltipLines.push(`Model Series: ${modelSeries}`);
        if (n.parentInstrumentTag || n.parent_instrument_tag) tooltipLines.push(`Supporting: ${n.parentInstrumentTag || n.parent_instrument_tag}`);
        if (n.standards && n.standards.length > 0) tooltipLines.push(`Standards: ${n.standards.slice(0, 3).join(', ')}`);
        if (n.loop) tooltipLines.push(`Loop: ${n.loop}`);
        if (specStatus) tooltipLines.push(`Specs source: ${specSourceLabel(specStatus)}`);

        const tooltipStr = tooltipLines.join('\n').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

        svgParts.push(`<g class="pid-node" data-id="${n.id}" data-tag="${tag}" data-kind="${kind}" data-spec-status="${specStatus}" style="cursor:pointer;">`);
        svgParts.push(`  <title>${tooltipStr}</title>`);

        if (isTieIn || kind === 'tie_in') {
            svgParts.push(
                `<polygon points="${x - 32},${y - 16} ${x + 20},${y - 16} ${x + 32},${y} ${x + 20},${y + 16} ${x - 32},${y + 16}" fill="#fffbeb" stroke="#d97706" stroke-width="2.5" filter="url(#shadow)" />`,
                `<text x="${x - 4}" y="${y + 4}" font-size="11" font-weight="800" fill="#92400e" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'off_page_connector') {
            svgParts.push(
                `<polygon points="${x - 40},${y - 16} ${x + 25},${y - 16} ${x + 40},${y} ${x + 25},${y + 16} ${x - 40},${y + 16}" fill="#f8fafc" stroke="#334155" stroke-width="2" filter="url(#shadow)" />`,
                `<text x="${x - 5}" y="${y + 4}" font-size="11" font-weight="700" fill="#1e293b" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'manifold') {
            const tagW = tag.length * 6.5 + 10;
            svgParts.push(
                `<rect x="${x - 24}" y="${y - 12}" width="48" height="24" rx="4" fill="#f0fdf4" stroke="#16a34a" stroke-width="1.8" filter="url(#shadow)" />`,
                `<circle cx="${x - 14}" cy="${y}" r="3" fill="#16a34a" />`,
                `<circle cx="${x}" cy="${y}" r="3" fill="#16a34a" />`,
                `<circle cx="${x + 14}" cy="${y}" r="3" fill="#16a34a" />`,
                `<rect x="${x - tagW / 2}" y="${y + 16}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#bbf7d0" stroke-width="0.8" />`,
                `<text x="${x}" y="${y + 28}" font-size="10" font-weight="700" fill="#15803d" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'siphon') {
            const tagW = tag.length * 6.5 + 10;
            svgParts.push(
                `<circle cx="${x}" cy="${y}" r="14" fill="#ffffff" stroke="#0284c7" stroke-width="2" />`,
                `<line x1="${x}" y1="${y - 14}" x2="${x}" y2="${y - 20}" stroke="#0284c7" stroke-width="2" />`,
                `<line x1="${x}" y1="${y + 14}" x2="${x}" y2="${y + 20}" stroke="#0284c7" stroke-width="2" />`,
                `<rect x="${x + 18}" y="${y - 7}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#bae6fd" stroke-width="0.8" />`,
                `<text x="${x + 23 + tagW / 2 - 5}" y="${y + 5}" font-size="10" font-weight="700" fill="#0369a1" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'thermowell') {
            const tagW = tag.length * 6.5 + 10;
            svgParts.push(
                `<line x1="${x}" y1="${y - 18}" x2="${x}" y2="${y + 18}" stroke="#475569" stroke-width="3" />`,
                `<rect x="${x - 8}" y="${y - 18}" width="16" height="6" fill="#475569" />`,
                `<rect x="${x + 16}" y="${y - 7}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" />`,
                `<text x="${x + 21 + tagW / 2 - 5}" y="${y + 5}" font-size="10" font-weight="700" fill="#334155" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'positioner') {
            const tagW = tag.length * 6.5 + 12;
            svgParts.push(
                `<rect x="${x - 22}" y="${y - 16}" width="44" height="32" rx="4" fill="#eff6ff" stroke="#2563eb" stroke-width="1.8" filter="url(#shadow)" />`,
                `<text x="${x}" y="${y + 4}" font-size="9.5" font-weight="800" fill="#1d4ed8" text-anchor="middle">POS</text>`,
                `<rect x="${x - tagW / 2}" y="${y + 21}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#bfdbfe" stroke-width="0.8" />`,
                `<text x="${x}" y="${y + 33}" font-size="10" font-weight="700" fill="#1e40af" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'actuator') {
            const tagW = tag.length * 6.5 + 10;
            svgParts.push(
                `<path d="M ${x - 18} ${y} A 18 18 0 0 1 ${x + 18} ${y} Z" fill="#e2e8f0" stroke="#0f172a" stroke-width="2" />`,
                `<line x1="${x}" y1="${y}" x2="${x}" y2="${y + 16}" stroke="#0f172a" stroke-width="2" />`,
                `<rect x="${x - tagW / 2}" y="${y - 32}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" />`,
                `<text x="${x}" y="${y - 20}" font-size="10" font-weight="700" fill="#0f172a" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'regulator') {
            const tagW = tag.length * 6.5 + 10;
            svgParts.push(
                `<polygon points="${x},${y - 14} ${x + 14},${y} ${x},${y + 14} ${x - 14},${y}" fill="#f0fdfa" stroke="#0d9488" stroke-width="1.8" />`,
                `<rect x="${x - tagW / 2}" y="${y + 18}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#99f6e4" stroke-width="0.8" />`,
                `<text x="${x}" y="${y + 30}" font-size="10" font-weight="700" fill="#0f766e" text-anchor="middle">${tag}</text>`
            );
        } else if (['vessel', 'column', 'reactor'].includes(kind)) {
            const desc = (n.description || kind).slice(0, 14);
            svgParts.push(
                `<rect x="${x - 45}" y="${y - 45}" width="90" height="90" rx="16" fill="#f8fafc" stroke="#0f172a" stroke-width="2.5" filter="url(#shadow)" />`,
                `<text x="${x}" y="${y - 6}" font-size="13" font-weight="700" fill="#0f172a" text-anchor="middle">${tag}</text>`,
                `<text x="${x}" y="${y + 12}" font-size="9" fill="#64748b" text-anchor="middle">${desc}</text>`
            );
        } else if (kind === 'pump') {
            svgParts.push(
                `<circle cx="${x}" cy="${y}" r="28" fill="#f8fafc" stroke="#0f172a" stroke-width="2.5" filter="url(#shadow)" />`,
                `<polygon points="${x + 18},${y - 18} ${x + 34},${y - 18} ${x + 24},${y - 2}" fill="#0f172a" />`,
                `<text x="${x}" y="${y + 4}" font-size="12" font-weight="700" fill="#0f172a" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'heat_exchanger') {
            svgParts.push(
                `<circle cx="${x}" cy="${y}" r="32" fill="#f8fafc" stroke="#0f172a" stroke-width="2.5" filter="url(#shadow)" />`,
                `<path d="M ${x - 22} ${y} Q ${x - 11} ${y - 16} ${x} ${y} T ${x + 22} ${y}" fill="none" stroke="#0f172a" stroke-width="2" />`,
                `<text x="${x}" y="${y + 18}" font-size="11" font-weight="700" fill="#0f172a" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'valve') {
            const tagW = tag.length * 6.5 + 12;
            let valveExtras = '';
            if (['PCV', 'FCV', 'TCV', 'LCV', 'CV', 'DIV'].some(v => tag.includes(v))) {
                valveExtras = `<line x1="${x}" y1="${y}" x2="${x}" y2="${y - 20}" stroke="#0f172a" stroke-width="2" /><path d="M ${x - 14} ${y - 20} A 14 14 0 0 1 ${x + 14} ${y - 20} Z" fill="#e2e8f0" stroke="#0f172a" stroke-width="1.5" />`;
            }
            svgParts.push(
                `<polygon points="${x - 20},${y - 14} ${x},${y} ${x - 20},${y + 14}" fill="#ffffff" stroke="#0f172a" stroke-width="2" />`,
                `<polygon points="${x + 20},${y - 14} ${x},${y} ${x + 20},${y + 14}" fill="#ffffff" stroke="#0f172a" stroke-width="2" />`,
                valveExtras,
                `<rect x="${x - tagW / 2}" y="${y + 18}" width="${tagW}" height="17" rx="3" fill="#ffffff" stroke="#cbd5e1" stroke-width="0.8" />`,
                `<text x="${x}" y="${y + 30}" font-size="11" font-weight="700" fill="#0f172a" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'relief') {
            const tagW = tag.length * 6.5 + 10;
            svgParts.push(
                `<polygon points="${x - 14},${y - 10} ${x},${y} ${x - 14},${y + 10}" fill="#fee2e2" stroke="#dc2626" stroke-width="2" />`,
                `<line x1="${x}" y1="${y}" x2="${x}" y2="${y - 16}" stroke="#dc2626" stroke-width="2" />`,
                `<rect x="${x - tagW / 2}" y="${y + 18}" width="${tagW}" height="16" rx="3" fill="#ffffff" stroke="#fecaca" stroke-width="0.8" />`,
                `<text x="${x}" y="${y + 30}" font-size="11" font-weight="700" fill="#dc2626" text-anchor="middle">${tag}</text>`
            );
        } else if (kind === 'controller') {
            const r = tag.length > 6 ? 30 : 26;
            const parts = tag.split(/[-_]/);
            let textSnippet = '';
            if (parts.length >= 2) {
                const topText = parts.slice(0, -1).join('-');
                const bottomText = parts[parts.length - 1];
                const topFs = topText.length > 5 ? '9' : '10';
                const bottomFs = bottomText.length > 4 ? '9.5' : '10.5';
                textSnippet = `<text x="${x}" y="${y - 4}" font-size="${topFs}" font-weight="700" fill="#92400e" text-anchor="middle">${topText}</text><text x="${x}" y="${y + 14}" font-size="${bottomFs}" font-weight="600" fill="#92400e" text-anchor="middle">${bottomText}</text>`;
            } else {
                const m = tag.match(/([A-Za-z]+)(\d+)/);
                if (m) {
                    textSnippet = `<text x="${x}" y="${y - 4}" font-size="10" font-weight="700" fill="#92400e" text-anchor="middle">${m[1]}</text><text x="${x}" y="${y + 14}" font-size="10" font-weight="600" fill="#92400e" text-anchor="middle">${m[2]}</text>`;
                } else {
                    textSnippet = `<text x="${x}" y="${y - 4}" font-size="9" font-weight="700" fill="#92400e" text-anchor="middle">${tag.slice(0, 5)}</text><text x="${x}" y="${y + 14}" font-size="9" font-weight="600" fill="#92400e" text-anchor="middle">${tag.slice(5)}</text>`;
                }
            }
            svgParts.push(
                `<circle cx="${x}" cy="${y}" r="${r}" fill="#fef3c7" stroke="#b45309" stroke-width="2" filter="url(#shadow)" />`,
                `<line x1="${x - r}" y1="${y}" x2="${x + r}" y2="${y}" stroke="#b45309" stroke-width="1.5" />`,
                textSnippet
            );
        } else {
            // Transmitter (Field circle)
            const r = tag.length > 6 ? 28 : 24;
            const parts = tag.split(/[-_]/);
            let textSnippet = '';
            if (parts.length >= 2) {
                const topText = parts.slice(0, -1).join('-');
                const bottomText = parts[parts.length - 1];
                const topFs = topText.length > 5 ? '9' : '10';
                const bottomFs = bottomText.length > 4 ? '9.5' : '10.5';
                textSnippet = `<text x="${x}" y="${y - 3}" font-size="${topFs}" font-weight="700" fill="#075985" text-anchor="middle">${topText}</text><text x="${x}" y="${y + 13}" font-size="${bottomFs}" font-weight="600" fill="#075985" text-anchor="middle">${bottomText}</text>`;
            } else {
                const m = tag.match(/([A-Za-z]+)(\d+)/);
                if (m) {
                    textSnippet = `<text x="${x}" y="${y - 3}" font-size="10" font-weight="700" fill="#075985" text-anchor="middle">${m[1]}</text><text x="${x}" y="${y + 13}" font-size="10" font-weight="600" fill="#075985" text-anchor="middle">${m[2]}</text>`;
                } else {
                    textSnippet = `<text x="${x}" y="${y + 4}" font-size="10" font-weight="700" fill="#075985" text-anchor="middle">${tag}</text>`;
                }
            }
            let subBadge = '';
            const calRng = specs.calibrated_range || specs.calibratedRange;
            if (calRng && calRng !== '0 - 100%') {
                const displayRng = String(calRng).slice(0, 14);
                const rw = displayRng.length * 5.8 + 8;
                subBadge = `<rect x="${x - rw / 2}" y="${y + 28}" width="${rw}" height="14" rx="3" fill="#ffffff" stroke="#bae6fd" stroke-width="0.6" opacity="0.95" /><text x="${x}" y="${y + 38}" font-size="8.5" font-weight="600" fill="#0284c7" text-anchor="middle">${displayRng}</text>`;
            }
            svgParts.push(
                `<circle cx="${x}" cy="${y}" r="${r}" fill="#e0f2fe" stroke="#0369a1" stroke-width="2" filter="url(#shadow)" />`,
                textSnippet,
                subBadge
            );
        }
        svgParts.push(`</g>`);
    }

    svgParts.push(`</svg>`);
    return svgParts.join('\n');
}
    const projType = (pidGraph?.projectType || pidGraph?.project_type || 'greenfield').toLowerCase();
    const isBrownfield = projType === 'brownfield';
    const subAreas = pidGraph?.subsystemAreas || pidGraph?.subsystem_areas || [];
    const nodes = pidGraph?.nodes || [];
    const edges = pidGraph?.edges || [];

    const svgContent = React.useMemo(() => {
        if (nodes && nodes.length > 0 && nodes[0]?.x !== undefined) {
            return generateCleanPIDDiagramSvg(nodes, edges, subAreas, projType);
        }
        return pidGraph?.svgPreview || pidGraph?.svg_preview || '';
    }, [pidGraph, nodes, edges, subAreas, projType]);

    // Extract SVG natural dimensions from viewBox for exact canvas scaling
    const svgDimensions = React.useMemo(() => {
        if (!svgContent) return { width: 1600, height: 960 };
        const match = svgContent.match(/viewBox=["']0\s+0\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)["']/i);
        if (match) {
            return { width: parseFloat(match[1]), height: parseFloat(match[2]) };
        }
        return { width: 1600, height: 960 };
    }, [svgContent]);

    // Filter nodes based on search & area filter
    const filteredNodes = nodes.filter(n => {
        const matchesArea = !activeAreaFilter || n.area === activeAreaFilter;
        const matchesSearch = !searchQuery || 
            n.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (n.description && n.description.toLowerCase().includes(searchQuery.toLowerCase())) ||
            n.kind.toLowerCase().includes(searchQuery.toLowerCase());
        return matchesArea && matchesSearch;
    });

    // Auto-Fit diagram to Viewport on initial load and resize
    const handleFitToView = React.useCallback(() => {
        const container = containerRef.current;
        if (!container) return;
        const { width: containerWidth, height: containerHeight } = container.getBoundingClientRect();
        const { width: svgWidth, height: svgHeight } = svgDimensions;

        if (containerWidth <= 0 || containerHeight <= 0) return;

        const padding = 36;
        const scaleX = (containerWidth - padding * 2) / svgWidth;
        const scaleY = (containerHeight - padding * 2) / svgHeight;
        const fitZoom = Math.min(Math.max(Math.min(scaleX, scaleY), 0.2), 2.5);

        const fitPanX = (containerWidth - svgWidth * fitZoom) / 2;
        const fitPanY = (containerHeight - svgHeight * fitZoom) / 2;

        setZoom(Number(fitZoom.toFixed(3)));
        setPan({ x: Number(fitPanX.toFixed(1)), y: Number(fitPanY.toFixed(1)) });
    }, [svgDimensions]);

    // Initial Fit on mount, diagram update, window resize, or inspector toggle
    useEffect(() => {
        if (!svgContent) return;
        handleFitToView();
        const timer = setTimeout(() => {
            handleFitToView();
        }, 80);

        const handleResize = () => {
            handleFitToView();
        };

        window.addEventListener('resize', handleResize);
        return () => {
            clearTimeout(timer);
            window.removeEventListener('resize', handleResize);
        };
    }, [svgContent, handleFitToView, isInspectorOpen]);

    // Viewport-Centered Zoom for HUD / Navbar Buttons
    const zoomAtViewportCenter = (factor: number) => {
        const container = containerRef.current;
        if (!container) return;
        const rect = container.getBoundingClientRect();
        const cx = rect.width / 2;
        const cy = rect.height / 2;

        setZoom(currentZoom => {
            const nextZoom = Math.min(Math.max(Number((currentZoom * factor).toFixed(3)), 0.4), 4.0);
            if (nextZoom === currentZoom) return currentZoom;

            const scaleRatio = nextZoom / currentZoom;
            setPan(currentPan => ({
                x: Number((cx - (cx - currentPan.x) * scaleRatio).toFixed(1)),
                y: Number((cy - (cy - currentPan.y) * scaleRatio).toFixed(1)),
            }));

            return nextZoom;
        });
    };

    const handleZoomIn = () => zoomAtViewportCenter(1.2);
    const handleZoomOut = () => zoomAtViewportCenter(1 / 1.2);

    const handleResetZoom = () => {
        const container = containerRef.current;
        if (!container) {
            setZoom(1);
            setPan({ x: 0, y: 0 });
            return;
        }
        const { width: containerWidth, height: containerHeight } = container.getBoundingClientRect();
        const { width: svgWidth, height: svgHeight } = svgDimensions;
        const newPanX = (containerWidth - svgWidth) / 2;
        const newPanY = (containerHeight - svgHeight) / 2;
        setZoom(1);
        setPan({ x: Number(newPanX.toFixed(1)), y: Number(newPanY.toFixed(1)) });
    };

    // Native Non-Passive Wheel & Gesture Listener to isolate diagram zoom and prevent browser page-level zoom
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const handleNativeWheel = (e: WheelEvent) => {
            e.preventDefault();
            e.stopPropagation();

            const rect = container.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            // Trackpad pinch zoom (ctrlKey) vs standard mouse wheel scroll steps
            const zoomDelta = e.ctrlKey 
                ? Math.exp(-e.deltaY * 0.01) 
                : (e.deltaY < 0 ? 1.15 : 1 / 1.15);

            setZoom(currentZoom => {
                const nextZoom = Math.min(Math.max(Number((currentZoom * zoomDelta).toFixed(3)), 0.4), 4.0);
                if (nextZoom === currentZoom) return currentZoom;

                const scaleRatio = nextZoom / currentZoom;

                setPan(currentPan => {
                    const nextPanX = mouseX - (mouseX - currentPan.x) * scaleRatio;
                    const nextPanY = mouseY - (mouseY - currentPan.y) * scaleRatio;
                    return { 
                        x: Number(nextPanX.toFixed(1)), 
                        y: Number(nextPanY.toFixed(1)) 
                    };
                });

                return nextZoom;
            });
        };

        const preventGesture = (e: Event) => {
            e.preventDefault();
        };

        container.addEventListener('wheel', handleNativeWheel, { passive: false });
        container.addEventListener('gesturestart', preventGesture, { passive: false });
        container.addEventListener('gesturechange', preventGesture, { passive: false });

        return () => {
            container.removeEventListener('wheel', handleNativeWheel);
            container.removeEventListener('gesturestart', preventGesture);
            container.removeEventListener('gesturechange', preventGesture);
        };
    }, []);

    // Fluid Panning Handlers
    const handleMouseDown = (e: React.MouseEvent) => {
        const isMiddleClick = e.button === 1;
        const isLeftClick = e.button === 0;

        if (isMiddleClick || isLeftClick) {
            isDragCandidate.current = true;
            hasMoved.current = false;
            setIsDragging(true);
            setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
        }
    };

    const handleMouseMove = (e: React.MouseEvent) => {
        if (isDragging && isDragCandidate.current) {
            const dx = e.clientX - dragStart.x;
            const dy = e.clientY - dragStart.y;
            if (Math.abs(dx - pan.x) > 3 || Math.abs(dy - pan.y) > 3) {
                hasMoved.current = true;
            }
            setPan({ x: Number(dx.toFixed(1)), y: Number(dy.toFixed(1)) });
        }
    };

    const handleMouseUp = () => {
        isDragCandidate.current = false;
        if (isDragging) {
            setIsDragging(false);
        }
    };

    const handleDownloadSvg = () => {
        if (!svgContent) return;
        const blob = new Blob([svgContent], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `pid_${projType}_full_diagram.svg`;
        a.click();
        URL.revokeObjectURL(url);
    };

    const handleExportFormat = (fmt: 'svg' | 'dxf' | 'ympl' | 'json') => {
        const sid = pidGraph?.sessionId || 'default';
        window.open(`/api/pid/export/${fmt}?session_id=${encodeURIComponent(sid)}`, '_blank');
    };


    // Copy Tag to Clipboard
    const handleCopyTag = (text: string) => {
        navigator.clipboard.writeText(text);
        setCopiedTag(text);
        setTimeout(() => setCopiedTag(null), 2000);
    };

    // Hyperlink Actions
    const handleOpenCatalogSearch = (tag: string, category: string = '') => {
        const query = category ? `${tag} ${category}` : tag;
        window.open(`/search?q=${encodeURIComponent(query)}`, '_blank');
    };

    const handleOpenAssetConfig = (tag: string) => {
        window.open(`/configure?tag=${encodeURIComponent(tag)}`, '_blank');
    };

    const handleOpenDatasheetSearch = (node: PIDNode) => {
        const mfg = node.specifications?.manufacturer || node.specifications?.vendor || '';
        const model = node.specifications?.model || '';
        const query = `${mfg} ${model} ${node.label} datasheet technical specifications pdf`.trim();
        window.open(`https://www.google.com/search?q=${encodeURIComponent(query)}`, '_blank');
    };

    // Interactive SVG Click Listener (Selects Node on clean click without pan jitter)
    useEffect(() => {
        const wrapper = svgWrapperRef.current;
        if (!wrapper) return;

        const handleSvgClick = (e: MouseEvent) => {
            // Ignore click if user was dragging/panning
            if (hasMoved.current) return;

            const target = e.target as HTMLElement | SVGElement;
            const nodeGroup = target.closest('g.pid-node') || target.closest('g[data-id]') || target.closest('g[data-tag]') || target.closest('g');
            if (nodeGroup) {
                const dataId = nodeGroup.getAttribute('data-id');
                const dataTag = nodeGroup.getAttribute('data-tag');
                const textElem = nodeGroup.querySelector('text');
                const titleElem = nodeGroup.querySelector('title');
                const tagText = (dataTag || textElem?.textContent || '').trim();
                
                let matched: PIDNode | undefined = undefined;
                if (dataId) {
                    matched = nodes.find(n => n.id === dataId);
                }
                if (!matched && tagText) {
                    matched = nodes.find(n => 
                        n.label.toUpperCase() === tagText.toUpperCase() || 
                        tagText.toUpperCase().includes(n.label.toUpperCase()) ||
                        n.label.toUpperCase().includes(tagText.toUpperCase())
                    );
                }
                if (!matched && titleElem?.textContent) {
                    matched = nodes.find(n => titleElem.textContent?.includes(n.label));
                }
                if (matched) {
                    setSelectedNode(matched);
                    setIsInspectorOpen(true);
                }
            }
        };

        wrapper.addEventListener('click', handleSvgClick);
        return () => wrapper.removeEventListener('click', handleSvgClick);
    }, [nodes, svgContent]);

    if (!pidGraph) {
        return (
            <div className="flex h-screen w-full flex-col items-center justify-center bg-slate-950 p-6 text-center text-slate-100">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-400 mb-4 border border-amber-500/30 shadow-lg">
                    <Compass className="h-8 w-8 animate-spin-slow" />
                </div>
                <h2 className="text-xl font-bold text-slate-100">No Active P&ID Schematic In Memory</h2>
                <p className="mt-2 max-w-md text-sm text-slate-400">
                    Generate an engineering solution in Solution Studio to construct and launch its dedicated P&ID Process Schematic in this window.
                </p>
                <Button 
                    onClick={() => navigate('/solution')} 
                    className="mt-6 gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold"
                >
                    <ArrowLeft className="h-4 w-4" /> Return to Solution Studio
                </Button>
            </div>
        );
    }

    return (
        <div className="flex h-screen w-full flex-col overflow-hidden bg-slate-950 text-slate-100">
            {/* Top Navigation Bar */}
            <header className="flex h-14 items-center justify-between border-b border-slate-800 bg-slate-900/90 px-4 backdrop-blur-md z-20 shrink-0">
                <div className="flex items-center gap-3">
                    <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={() => {
                            if (window.opener) {
                                window.close();
                            } else {
                                navigate('/solution');
                            }
                        }}
                        className="gap-1.5 text-slate-300 hover:bg-slate-800 hover:text-white"
                        title="Close Tab"
                    >
                        <ArrowLeft className="h-4 w-4" />
                        <span className="hidden sm:inline">Close Studio</span>
                    </Button>
                    <div className="h-4 w-[1px] bg-slate-700" />
                    <div>
                        <div className="flex items-center gap-2">
                            <h1 className="text-sm font-bold tracking-tight text-slate-100 truncate max-w-[280px] sm:max-w-md">
                                {solutionTitle}
                            </h1>
                            <Badge 
                                variant="outline" 
                                className={`text-[10px] uppercase font-bold tracking-wider ${
                                    isBrownfield 
                                        ? 'bg-amber-500/10 text-amber-400 border-amber-500/30' 
                                        : 'bg-sky-500/10 text-sky-400 border-sky-500/30'
                                }`}
                            >
                                {isBrownfield ? 'Brownfield Retrofit' : 'Greenfield Design'}
                            </Badge>
                        </div>
                        <p className="text-[11px] text-slate-400">
                            {nodes.length} Components · {edges.length} Process & Signal Streams · Fixed Viewport
                        </p>
                    </div>
                </div>

                {/* Toolbar Controls */}
                <div className="flex items-center gap-1.5 sm:gap-2">
                    {/* View Mode Toggle: Interactive Flow Canvas vs Vector SVG */}
                    <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900/90 p-0.5 shadow-sm">
                        <Button
                            variant="ghost"
                            size="sm"
                            className={`h-8 px-2.5 gap-1.5 text-xs font-medium ${
                                viewMode === 'flow'
                                    ? 'bg-primary text-primary-foreground font-semibold shadow-sm'
                                    : 'text-slate-400 hover:text-white hover:bg-slate-800'
                            }`}
                            onClick={() => setViewMode('flow')}
                            title="Interactive React Flow Canvas"
                        >
                            <Network className="h-3.5 w-3.5" />
                            <span className="hidden sm:inline">Flow Canvas</span>
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            className={`h-8 px-2.5 gap-1.5 text-xs font-medium ${
                                viewMode === 'svg'
                                    ? 'bg-sky-500 text-white font-semibold shadow-sm'
                                    : 'text-slate-400 hover:text-white hover:bg-slate-800'
                            }`}
                            onClick={() => setViewMode('svg')}
                            title="Engineered Static Vector SVG"
                        >
                            <FileText className="h-3.5 w-3.5" />
                            <span className="hidden sm:inline">SVG Sheet</span>
                        </Button>
                    </div>

                    {/* AI Copilot & Ingest Buttons */}
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setIsDescribeOpen(true)}
                        className="h-8 gap-1.5 text-xs font-medium bg-gradient-to-r from-amber-500/15 to-primary/15 border border-primary/30 text-primary hover:bg-primary/20 shadow-sm"
                        title="Open Conversational Describe Copilot"
                    >
                        <Sparkles className="h-3.5 w-3.5 text-amber-400" />
                        <span className="hidden sm:inline">Describe Copilot</span>
                    </Button>

                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setIsIngestOpen(true)}
                        className="h-8 gap-1.5 text-xs font-medium border border-slate-800 text-slate-300 hover:bg-slate-800 hover:text-white"
                        title="Ingest & Extract Scanned P&ID Drawing"
                    >
                        <UploadCloud className="h-3.5 w-3.5 text-sky-400" />
                        <span className="hidden sm:inline">Ingest Scan</span>
                    </Button>

                    {/* Tool Mode: Select vs Pan */}
                    {viewMode === 'svg' && (
                        <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900/90 p-0.5 shadow-sm">
                            <Button 
                                variant="ghost" 
                                size="sm" 
                                className={`h-8 px-2.5 gap-1.5 text-xs font-medium ${
                                    !isPanMode 
                                        ? 'bg-primary text-primary-foreground font-semibold shadow-sm' 
                                        : 'text-slate-400 hover:text-white hover:bg-slate-800'
                                }`}
                                onClick={() => {
                                    setIsPanMode(false);
                                    setPan({ x: 0, y: 0 });
                                }}
                                title="Select & Inspect Mode"
                            >
                                <MousePointer className="h-3.5 w-3.5" />
                                <span className="hidden sm:inline">Select</span>
                            </Button>
                            <Button 
                                variant="ghost" 
                                size="sm" 
                                className={`h-8 px-2.5 gap-1.5 text-xs font-medium ${
                                    isPanMode 
                                        ? 'bg-sky-500 text-white font-semibold shadow-sm' 
                                        : 'text-slate-400 hover:text-white hover:bg-slate-800'
                                }`}
                                onClick={() => setIsPanMode(true)}
                                title="Pan Mode"
                            >
                                <Move className="h-3.5 w-3.5" />
                                <span className="hidden sm:inline">Pan</span>
                            </Button>
                        </div>
                    )}

                    {/* In-Place Zoom Controls (for SVG view) */}
                    {viewMode === 'svg' && (
                        <div className="flex items-center rounded-lg border border-slate-800 bg-slate-900/90 p-0.5 shadow-sm">
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-8 w-8 text-slate-400 hover:text-white hover:bg-slate-800" 
                                onClick={handleZoomOut}
                                title="Zoom Out"
                            >
                                <ZoomOut className="h-4 w-4" />
                            </Button>
                            <span className="px-2 text-xs font-mono font-bold text-sky-400 min-w-[52px] text-center select-none">
                                {Math.round(zoom * 100)}%
                            </span>
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-8 w-8 text-slate-400 hover:text-white hover:bg-slate-800" 
                                onClick={handleZoomIn}
                                title="Zoom In"
                            >
                                <ZoomIn className="h-4 w-4" />
                            </Button>
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-8 w-8 text-slate-400 hover:text-white hover:bg-slate-800" 
                                onClick={handleResetZoom}
                                title="Reset 100% Zoom"
                            >
                                <RotateCcw className="h-3.5 w-3.5" />
                            </Button>
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-8 w-8 text-slate-400 hover:text-white hover:bg-slate-800" 
                                onClick={handleFitToView}
                                title="Fit Diagram to View"
                            >
                                <Maximize2 className="h-3.5 w-3.5" />
                            </Button>
                        </div>
                    )}

                    {/* Inspector Toggle Button */}
                    <Button 
                        variant="ghost" 
                        size="sm"
                        onClick={() => setIsInspectorOpen(prev => !prev)}
                        className={`h-8 gap-1.5 text-xs font-medium border border-slate-800 ${
                            isInspectorOpen 
                                ? 'bg-slate-800 text-white font-semibold shadow-sm' 
                                : 'text-slate-400 hover:text-white hover:bg-slate-800'
                        }`}
                        title="Toggle Component Inspector Panel"
                    >
                        <Sliders className="h-3.5 w-3.5 text-primary" />
                        <span className="hidden sm:inline">Inspector ({filteredNodes.length})</span>
                    </Button>

                    {/* Export Menu */}
                    <div className="flex items-center gap-1">
                        <Button 
                            onClick={handleDownloadSvg} 
                            size="sm"
                            className="gap-1.5 bg-primary hover:bg-primary/90 text-primary-foreground font-medium shadow-sm h-8"
                        >
                            <Download className="h-3.5 w-3.5" />
                            <span className="hidden sm:inline">Export SVG</span>
                        </Button>
                        <Button
                            onClick={() => handleExportFormat('dxf')}
                            size="sm"
                            variant="outline"
                            className="h-8 text-xs border-slate-700 bg-slate-900 text-slate-300 hover:text-white hover:bg-slate-800"
                            title="Export AutoCAD DXF"
                        >
                            DXF
                        </Button>
                        <Button
                            onClick={() => handleExportFormat('ympl')}
                            size="sm"
                            variant="outline"
                            className="h-8 text-xs border-slate-700 bg-slate-900 text-slate-300 hover:text-white hover:bg-slate-800"
                            title="Export YMPL Topology"
                        >
                            YMPL
                        </Button>
                    </div>
                </div>
            </header>

            {/* "Show unspecified": glow nodes with no specification data, fade the rest */}
            <style>{`
                .pid-highlight-unspecified g.pid-node[data-spec-status="unspecified"] {
                    filter: drop-shadow(0 0 3px #f59e0b) drop-shadow(0 0 6px #f59e0b);
                }
                .pid-highlight-unspecified g.pid-node:not([data-spec-status="unspecified"]) {
                    opacity: 0.4;
                }
            `}</style>

            {/* Pending engineer decision, build path, validation, spec provenance */}
            <PIDDecisionPanel
                pidGraph={pidGraph}
                onGraphUpdated={updatePidGraph}
                highlightUnspecified={highlightUnspecified}
                onToggleHighlight={() => setHighlightUnspecified(v => !v)}
            />

            {/* Sub-system Area Quick Filter Ribbon */}
            {subAreas.length > 0 && (
                <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900/60 px-4 py-2 overflow-x-auto text-xs z-10 shrink-0">
                    <span className="font-semibold text-slate-400 uppercase tracking-wider text-[10px] flex items-center gap-1">
                        <Layers className="h-3.5 w-3.5 text-primary" /> Sub-systems:
                    </span>
                    <button
                        onClick={() => setActiveAreaFilter(null)}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-all ${
                            activeAreaFilter === null
                                ? 'bg-primary text-primary-foreground shadow-sm'
                                : 'bg-slate-800/80 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                        }`}
                    >
                        All Sub-systems ({nodes.length})
                    </button>
                    {subAreas.map((area, idx) => (
                        <button
                            key={idx}
                            onClick={() => {
                                const nextFilter = activeAreaFilter === area.name ? null : area.name;
                                setActiveAreaFilter(nextFilter);
                                if (nextFilter) {
                                    const firstInArea = nodes.find(n => n.area === nextFilter);
                                    if (firstInArea) {
                                        setSelectedNode(firstInArea);
                                        setIsInspectorOpen(true);
                                    }
                                }
                            }}
                            className={`rounded-full px-2.5 py-0.5 text-xs font-medium transition-all ${
                                activeAreaFilter === area.name
                                    ? 'bg-sky-500 text-white shadow-sm'
                                    : 'bg-slate-800/80 text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-slate-700/40'
                            }`}
                        >
                            {area.name} {area.node_count ? `(${area.node_count})` : ''}
                        </button>
                    ))}
                </div>
            )}

            {/* Main Studio Viewport (Dynamic Canvas with Pointer-Focused Zoom & Pan) */}
            <div className="relative flex flex-1 min-h-0 overflow-hidden">
                {viewMode === 'flow' ? (
                    <div className="relative flex-1 min-w-0 h-full p-2 overflow-hidden bg-slate-950">
                        <PIDCanvasView
                            graph={pidGraph || { nodes: [], edges: [] }}
                            onSelectNode={(node) => {
                                setSelectedNode(node);
                                setIsInspectorOpen(true);
                            }}
                            selectedNodeId={selectedNode?.id}
                            onGraphUpdate={updatePidGraph}
                        />
                    </div>
                ) : (
                    /* Dynamic Canvas Board (SVG) */
                    <div 
                        ref={containerRef}
                        className="relative flex-1 min-w-0 overflow-hidden select-none"
                        onMouseDown={handleMouseDown}
                        onMouseMove={handleMouseMove}
                        onMouseUp={handleMouseUp}
                        onMouseLeave={handleMouseUp}
                        style={{
                            cursor: isDragging ? 'grabbing' : isPanMode ? 'grab' : 'default',
                            backgroundImage: `radial-gradient(#475569 1.2px, transparent 1.2px)`,
                            backgroundSize: `${24 * Math.min(Math.max(zoom, 0.5), 2)}px ${24 * Math.min(Math.max(zoom, 0.5), 2)}px`,
                            backgroundPosition: `${pan.x}px ${pan.y}px`,
                            backgroundColor: '#090d16',
                            touchAction: 'none',
                            overscrollBehavior: 'contain',
                        }}
                    >
                        {/* Dynamic Diagram Canvas Layer (Pointer-Centered Transform) */}
                        <div 
                            className="absolute top-0 left-0"
                            style={{
                                transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
                                transformOrigin: '0 0',
                                willChange: 'transform',
                                transition: isDragging ? 'none' : 'transform 0.04s ease-out',
                            }}
                        >
                            {svgContent ? (
                                <div
                                    ref={svgWrapperRef}
                                    className={`cursor-pointer select-none rounded-xl shadow-2xl border border-slate-700/80 bg-white overflow-hidden ${highlightUnspecified ? 'pid-highlight-unspecified' : ''}`}
                                    style={{
                                        width: `${svgDimensions.width}px`,
                                        height: `${svgDimensions.height}px`,
                                    }}
                                    dangerouslySetInnerHTML={{ __html: svgContent }}
                                />
                            ) : (
                                <div className="flex h-[600px] w-[900px] items-center justify-center text-slate-400 font-medium">
                                    Generating Vector Diagram...
                                </div>
                            )}
                        </div>

                    {/* Quick Floating Node Details Badge on Canvas when Clicked */}
                    {selectedNode && (
                        <div className="absolute top-4 right-4 z-20 max-w-xs sm:max-w-sm rounded-xl border border-slate-200/90 bg-white/95 p-3.5 shadow-2xl backdrop-blur-md animate-in fade-in slide-in-from-top-2 duration-200 text-slate-800">

                            <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-2">
                                <div className="flex items-center gap-2">
                                    <span className="font-mono text-sm font-bold text-sky-600">{selectedNode.label}</span>
                                    <Badge variant="outline" className="text-[10px] uppercase font-semibold text-slate-700 bg-slate-50">
                                        {selectedNode.kind}
                                    </Badge>
                                </div>
                                <button 
                                    onClick={() => setSelectedNode(null)} 
                                    className="text-slate-400 hover:text-slate-700 p-1 rounded-md hover:bg-slate-100 transition-colors text-xs font-bold"
                                    title="Close Overlay"
                                >
                                    ✕
                                </button>
                            </div>

                            {/* Vendor & Model Badge */}
                            {(selectedNode.vendor || selectedNode.model_family || selectedNode.modelFamily || selectedNode.model_series || selectedNode.modelSeries) && (
                                <div className="mt-2 rounded-md bg-sky-50/90 border border-sky-200/70 p-2 space-y-0.5 text-[11px]">
                                    {selectedNode.vendor && (
                                        <div className="flex items-center gap-1 font-semibold text-sky-900">
                                            <Building2 className="h-3 w-3 text-sky-600 shrink-0" />
                                            <span>{selectedNode.vendor}</span>
                                        </div>
                                    )}
                                    {(selectedNode.model_series || selectedNode.modelSeries || selectedNode.model_family || selectedNode.modelFamily) && (
                                        <div className="text-[10.5px] text-sky-700 font-medium truncate">
                                            {selectedNode.model_series || selectedNode.modelSeries || selectedNode.model_family || selectedNode.modelFamily}
                                        </div>
                                    )}
                                </div>
                            )}

                            {(selectedNode.parent_instrument_tag || selectedNode.parentInstrumentTag) && (
                                <div className="mt-1.5 flex items-center gap-1 text-[10.5px] font-medium text-amber-800 bg-amber-50 px-2 py-0.5 rounded border border-amber-200/60">
                                    <Link2 className="h-3 w-3 text-amber-600 shrink-0" />
                                    <span>Supports: <strong>{selectedNode.parent_instrument_tag || selectedNode.parentInstrumentTag}</strong></span>
                                </div>
                            )}

                            {selectedNode.description && (
                                <p className="mt-2 text-xs text-slate-600 leading-relaxed font-medium">
                                    {selectedNode.description}
                                </p>
                            )}
                            {selectedNode.specifications && Object.keys(selectedNode.specifications).length > 0 && (
                                <div className="mt-2 rounded-lg bg-slate-50 p-2 space-y-1 text-[11px] border border-slate-100">
                                    {Object.entries(selectedNode.specifications).slice(0, 3).map(([k, v]) => (
                                        <div key={k} className="flex justify-between text-slate-600">
                                            <span className="capitalize font-medium text-slate-500">{k.replace(/_/g, ' ')}:</span>
                                            <span className="font-mono font-semibold text-slate-800">{String(v)}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                            <div className="mt-3 flex items-center gap-1.5 pt-1">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-7 text-[11px] gap-1 flex-1 border-slate-200 text-sky-700 hover:bg-sky-50"
                                    onClick={() => handleOpenCatalogSearch(selectedNode.label, selectedNode.kind)}
                                >
                                    <Search className="h-3 w-3" /> Catalog
                                </Button>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-7 text-[11px] gap-1 flex-1 border-slate-200 text-amber-700 hover:bg-amber-50"
                                    onClick={() => handleOpenAssetConfig(selectedNode.label)}
                                >
                                    <Settings className="h-3 w-3" /> Asset Config
                                </Button>
                            </div>
                        </div>
                    )}

                    {/* Floating HUD Controls (Zoom In/Out, Fit, Mode Indicator) */}
                    <div className="absolute bottom-4 left-4 flex items-center gap-3 z-10">
                        {/* Interactive Zoom Toolbar Pill */}
                        <div className="flex items-center gap-1 rounded-xl border border-slate-200/80 bg-white/95 px-2 py-1.5 shadow-lg backdrop-blur-md text-slate-700">
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-7 w-7 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg"
                                onClick={handleZoomOut}
                                title="Zoom Out"
                            >
                                <ZoomOut className="h-3.5 w-3.5" />
                            </Button>
                            <button 
                                onClick={handleResetZoom}
                                className="px-2 py-0.5 rounded-md hover:bg-slate-100 text-xs font-mono font-bold text-slate-800 min-w-[45px] text-center"
                                title="Click to Reset 100%"
                            >
                                {Math.round(zoom * 100)}%
                            </button>
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-7 w-7 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg"
                                onClick={handleZoomIn}
                                title="Zoom In"
                            >
                                <ZoomIn className="h-3.5 w-3.5" />
                            </Button>
                            <div className="h-4 w-[1px] bg-slate-200 mx-0.5" />
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-7 w-7 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg"
                                onClick={handleFitToView}
                                title="Fit to View"
                            >
                                <Maximize2 className="h-3.5 w-3.5" />
                            </Button>
                            <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-7 w-7 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg"
                                onClick={handleResetZoom}
                                title="Reset Center & Zoom"
                            >
                                <RotateCcw className="h-3 w-3" />
                            </Button>
                        </div>

                        {/* Interactive Mode Tooltip */}
                        <div className="hidden md:flex items-center gap-1.5 rounded-xl border border-slate-200/80 bg-white/90 px-3 py-1.5 text-xs text-slate-600 shadow-md backdrop-blur-md">
                            <Compass className="h-3.5 w-3.5 text-sky-600" />
                            <span>
                                {isPanMode 
                                    ? 'Pan Mode Active: Drag to move schematic · Scroll to zoom' 
                                    : 'Select Mode: Click any bubble to inspect · Scroll to zoom in-place'}
                            </span>
                        </div>

                        {/* Quick Inspector Toggle Button in HUD */}
                        <button
                            onClick={() => setIsInspectorOpen(prev => !prev)}
                            className="flex items-center gap-1.5 rounded-xl border border-slate-200/80 bg-white/90 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-md backdrop-blur-md hover:bg-slate-50 transition-colors"
                        >
                            <Sliders className="h-3.5 w-3.5 text-primary" />
                            <span>{isInspectorOpen ? 'Hide Inspector' : 'Show Inspector'}</span>
                        </button>
                    </div>
                </div>
            )}

            {/* Floating Claude & Gemini Prompt Bar */}
            <div className="absolute bottom-5 left-1/2 -translate-x-1/2 z-30 max-w-xl w-[92%] sm:w-[580px]">
                <div className="bg-slate-900/95 backdrop-blur-2xl border border-slate-700/80 rounded-2xl p-2 shadow-2xl flex items-center gap-2">
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-gradient-to-r from-amber-500/15 via-primary/15 to-blue-500/15 border border-primary/30 text-[11px] font-mono text-primary font-semibold">
                        <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                        <span className="hidden sm:inline">Claude / Gemini</span>
                    </div>
                    <input 
                        type="text"
                        value={quickPrompt}
                        onChange={(e) => setQuickPrompt(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && quickPrompt.trim()) {
                                setIsDescribeOpen(true);
                            }
                        }}
                        placeholder="Ask Describe Copilot: e.g. Add bypass valve around PCV-1111..."
                        className="flex-1 bg-transparent border-none text-xs text-slate-100 placeholder:text-slate-400 focus:outline-none px-2"
                    />
                    <Button 
                        size="sm"
                        onClick={() => setIsDescribeOpen(true)}
                        className="rounded-xl h-8 px-3 bg-primary hover:bg-primary/90 text-primary-foreground text-xs gap-1.5 font-medium"
                    >
                        <Sparkles className="w-3.5 h-3.5" />
                        <span>Copilot</span>
                    </Button>
                </div>
            </div>

            {/* Right Component Inspector Sidebar */}
            {isInspectorOpen && (
                    <aside className="w-80 sm:w-96 flex flex-col border-l border-slate-800 bg-slate-900/95 backdrop-blur-md overflow-hidden z-10 shrink-0 animate-in slide-in-from-right-4 duration-200">
                        <div className="flex items-center justify-between border-b border-slate-800 p-3 bg-slate-900">
                            <div className="flex items-center gap-1.5 font-bold text-xs uppercase tracking-wider text-slate-200">
                                <Sliders className="h-4 w-4 text-primary" />
                                <span>Component Inspector</span>
                            </div>
                            <div className="flex items-center gap-1">
                                {selectedNode && (
                                    <Button 
                                        variant="ghost" 
                                        size="sm" 
                                        onClick={() => setSelectedNode(null)}
                                        className="h-6 text-[10px] text-slate-400 hover:text-white"
                                    >
                                        Clear Selection
                                    </Button>
                                )}
                                <Button 
                                    variant="ghost" 
                                    size="sm" 
                                    onClick={() => setIsInspectorOpen(false)}
                                    className="h-6 px-1.5 text-[11px] text-slate-400 hover:text-white"
                                    title="Collapse Panel"
                                >
                                    ✕
                                </Button>
                            </div>
                        </div>

                    {/* Selected Node Details & Hyperlink Actions */}
                    {selectedNode ? (
                        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
                            {/* Primary Identity & Hardware Nameplate Card */}
                            <div className="rounded-lg border border-primary/30 bg-primary/5 p-3.5 space-y-2.5">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-1.5">
                                        <span className="text-base font-bold text-primary font-mono">{selectedNode.label}</span>
                                        <button 
                                            onClick={() => handleCopyTag(selectedNode.label)}
                                            className="text-slate-400 hover:text-white p-0.5 rounded transition-colors"
                                            title="Copy Tag"
                                        >
                                            {copiedTag === selectedNode.label ? (
                                                <Check className="h-3.5 w-3.5 text-emerald-400" />
                                            ) : (
                                                <Copy className="h-3.5 w-3.5" />
                                            )}
                                        </button>
                                    </div>
                                    <Badge variant="outline" className="text-[10px] uppercase font-semibold">
                                        {selectedNode.kind}
                                    </Badge>
                                </div>

                                {/* Where this node's specifications came from; nothing is invented */}
                                {(selectedNode.specStatus || selectedNode.spec_status || selectedNode.loop) && (
                                    <div className="flex items-center gap-2 text-[11px] text-slate-400">
                                        {(selectedNode.specStatus || selectedNode.spec_status) && (
                                            <span title="Where this node's specifications came from">
                                                Specs: <span className="font-semibold text-slate-200">
                                                    {specSourceLabel(selectedNode.specStatus || selectedNode.spec_status)}
                                                </span>
                                            </span>
                                        )}
                                        {selectedNode.loop && <span>· Loop <span className="font-mono text-slate-200">{selectedNode.loop}</span></span>}
                                    </div>
                                )}

                                {/* Hardware Nameplate: Vendor, Model Family, Model Series */}
                                <div className="rounded-md border border-slate-800 bg-slate-950/80 p-2.5 space-y-1.5 text-xs">
                                    {selectedNode.vendor && (
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400 text-[11px] flex items-center gap-1 font-medium">
                                                <Building2 className="h-3 w-3 text-sky-400" /> Vendor (OEM):
                                            </span>
                                            <span className="font-semibold text-slate-100 text-right">{selectedNode.vendor}</span>
                                        </div>
                                    )}
                                    {(selectedNode.model_family || selectedNode.modelFamily) && (
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400 text-[11px] flex items-center gap-1 font-medium">
                                                <Layers className="h-3 w-3 text-indigo-400" /> Model Family:
                                            </span>
                                            <span className="font-medium text-indigo-300 text-right">{selectedNode.model_family || selectedNode.modelFamily}</span>
                                        </div>
                                    )}
                                    {(selectedNode.model_series || selectedNode.modelSeries) && (
                                        <div className="flex items-center justify-between">
                                            <span className="text-slate-400 text-[11px] flex items-center gap-1 font-medium">
                                                <Cpu className="h-3 w-3 text-emerald-400" /> Model Series:
                                            </span>
                                            <span className="font-mono font-medium text-emerald-300 text-right">{selectedNode.model_series || selectedNode.modelSeries}</span>
                                        </div>
                                    )}
                                    {(selectedNode.parent_instrument_tag || selectedNode.parentInstrumentTag) && (
                                        <div className="flex items-center justify-between pt-1 border-t border-slate-900">
                                            <span className="text-amber-400 text-[11px] flex items-center gap-1 font-medium">
                                                <Link2 className="h-3 w-3" /> Supports Instrument:
                                            </span>
                                            <span className="font-mono font-bold text-amber-300">{selectedNode.parent_instrument_tag || selectedNode.parentInstrumentTag}</span>
                                        </div>
                                    )}
                                </div>

                                {selectedNode.description && (
                                    <p className="text-slate-300 text-xs leading-relaxed">{selectedNode.description}</p>
                                )}
                                {selectedNode.area && (
                                    <div className="flex items-center gap-1 text-[11px] text-slate-400">
                                        <Layers className="h-3.5 w-3.5 text-primary" />
                                        <span>Process Area: <strong className="text-slate-200">{selectedNode.area}</strong></span>
                                    </div>
                                )}
                            </div>

                            {/* Applicable Standards Badges */}
                            {selectedNode.standards && selectedNode.standards.length > 0 && (
                                <div className="space-y-1.5">
                                    <h4 className="font-bold text-[11px] uppercase tracking-wider text-slate-400 flex items-center gap-1">
                                        <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" /> Applicable Engineering Standards
                                    </h4>
                                    <div className="flex flex-wrap gap-1.5">
                                        {selectedNode.standards.map((std, sIdx) => (
                                            <span
                                                key={sIdx}
                                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-mono font-medium border border-emerald-500/30"
                                            >
                                                ✓ {std}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Categorized Technical Specifications */}
                            {(selectedNode.categorized_specs || selectedNode.categorizedSpecs) && Object.keys(selectedNode.categorized_specs || selectedNode.categorizedSpecs || {}).length > 0 ? (
                                <div className="space-y-2.5">
                                    <h4 className="font-bold text-[11px] uppercase tracking-wider text-slate-400 flex items-center gap-1">
                                        <Gauge className="h-3.5 w-3.5 text-sky-400" /> Technical Specifications
                                    </h4>
                                    {Object.entries(selectedNode.categorized_specs || selectedNode.categorizedSpecs || {}).map(([catKey, catValues]) => (
                                        <div key={catKey} className="rounded-lg border border-slate-800 bg-slate-950 p-2.5 space-y-1.5">
                                            <div className="text-[10px] font-bold uppercase tracking-wider text-sky-400 border-b border-slate-900 pb-1 flex items-center gap-1">
                                                {catKey === 'process' && <Gauge className="h-3 w-3" />}
                                                {catKey === 'mechanical' && <Wrench className="h-3 w-3" />}
                                                {catKey === 'electrical' && <Zap className="h-3 w-3" />}
                                                {catKey === 'safety' && <ShieldCheck className="h-3 w-3" />}
                                                {catKey === 'certifications' && <FileText className="h-3 w-3" />}
                                                <span>{catKey} Parameters</span>
                                            </div>
                                            {Object.entries(catValues as Record<string, any>).map(([key, val]) => (
                                                <div key={key} className="flex justify-between text-[11px] py-0.5">
                                                    <span className="text-slate-400 capitalize font-medium">{key.replace(/_/g, ' ')}:</span>
                                                    <span className="font-mono text-slate-200 font-semibold text-right">{String(val)}</span>
                                                </div>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            ) : selectedNode.specifications && Object.keys(selectedNode.specifications).length > 0 ? (
                                <div className="space-y-2">
                                    <h4 className="font-bold text-[11px] uppercase tracking-wider text-slate-400 flex items-center gap-1">
                                        <Gauge className="h-3.5 w-3.5 text-sky-400" /> Technical Specifications
                                    </h4>
                                    <div className="rounded-lg border border-slate-800 bg-slate-950 p-3 space-y-1.5">
                                        {Object.entries(selectedNode.specifications).map(([key, val]) => (
                                            <div key={key} className="flex justify-between py-1 border-b border-slate-900 last:border-0 text-[11px]">
                                                <span className="text-slate-400 capitalize font-medium">{key.replace(/_/g, ' ')}:</span>
                                                <span className="font-mono text-slate-200 font-semibold text-right">{String(val)}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ) : null}

                            {/* Hyperlink Actions Panel */}
                            <div className="space-y-2">
                                <h4 className="font-bold text-[11px] uppercase tracking-wider text-slate-400 flex items-center gap-1">
                                    <ExternalLink className="h-3.5 w-3.5 text-primary" /> Hyperlink Actions
                                </h4>
                                <div className="grid grid-cols-1 gap-1.5">
                                    <button
                                        onClick={() => handleOpenCatalogSearch(selectedNode.label, selectedNode.kind)}
                                        className="w-full text-left rounded-md border border-slate-800 bg-slate-950/90 hover:bg-slate-800/80 p-2 text-xs flex items-center justify-between transition-colors group"
                                    >
                                        <div className="flex items-center gap-2">
                                            <Search className="h-3.5 w-3.5 text-sky-400" />
                                            <span className="text-slate-200 font-medium">Search Catalog for {selectedNode.label}</span>
                                        </div>
                                        <ExternalLink className="h-3 w-3 text-slate-500 group-hover:text-white" />
                                    </button>

                                    <button
                                        onClick={() => handleOpenAssetConfig(selectedNode.label)}
                                        className="w-full text-left rounded-md border border-slate-800 bg-slate-950/90 hover:bg-slate-800/80 p-2 text-xs flex items-center justify-between transition-colors group"
                                    >
                                        <div className="flex items-center gap-2">
                                            <Settings className="h-3.5 w-3.5 text-amber-400" />
                                            <span className="text-slate-200 font-medium">View in Asset Configurator</span>
                                        </div>
                                        <ExternalLink className="h-3 w-3 text-slate-500 group-hover:text-white" />
                                    </button>

                                    <button
                                        onClick={() => handleOpenDatasheetSearch(selectedNode)}
                                        className="w-full text-left rounded-md border border-slate-800 bg-slate-950/90 hover:bg-slate-800/80 p-2 text-xs flex items-center justify-between transition-colors group"
                                    >
                                        <div className="flex items-center gap-2">
                                            <FileText className="h-3.5 w-3.5 text-emerald-400" />
                                            <span className="text-slate-200 font-medium">Lookup Technical Datasheet</span>
                                        </div>
                                        <ExternalLink className="h-3 w-3 text-slate-500 group-hover:text-white" />
                                    </button>
                                </div>
                            </div>

                            {/* Connected Topology Streams */}
                            <div className="space-y-2">
                                <h4 className="font-bold text-[11px] uppercase tracking-wider text-slate-400">
                                    Connected Signal & Process Streams
                                </h4>
                                <div className="space-y-1.5">
                                    {edges.filter(e => e.from === selectedNode.id || e.to === selectedNode.id).map((edge, eIdx) => {
                                        const isOutbound = edge.from === selectedNode.id;
                                        const otherNode = nodes.find(n => n.id === (isOutbound ? edge.to : edge.from));
                                        return (
                                            <div key={eIdx} className="rounded-md border border-slate-800/80 bg-slate-950/80 p-2 text-[11px] flex items-center justify-between">
                                                <div className="flex items-center gap-1.5">
                                                    <Activity className="h-3.5 w-3.5 text-sky-400" />
                                                    <span>{isOutbound ? 'To' : 'From'}: <strong className="text-slate-200">{otherNode?.label || (isOutbound ? edge.to : edge.from)}</strong></span>
                                                </div>
                                                <Badge variant="secondary" className="text-[9px] font-mono">
                                                    {edge.kind || 'stream'}
                                                </Badge>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="flex flex-col flex-1 overflow-y-auto">
                            {/* Search Box */}
                            <div className="p-3 border-b border-slate-800">
                                <div className="relative">
                                    <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
                                    <input 
                                        type="text" 
                                        placeholder="Search components or tags..." 
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="w-full rounded-md border border-slate-800 bg-slate-950 pl-8 pr-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:border-primary focus:outline-none"
                                    />
                                </div>
                            </div>

                            {/* Node Component List with Quick Action Hyperlinks */}
                            <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
                                {filteredNodes.map((n, idx) => {
                                    const isTie = n.isTieIn || n.is_tie_in || n.kind === 'tie_in';
                                    return (
                                        <div
                                            key={idx}
                                            className="w-full rounded-lg border border-slate-800/60 bg-slate-950/40 p-2.5 transition-colors hover:border-primary/50 hover:bg-slate-900/80 flex items-center justify-between group"
                                        >
                                            <div 
                                                onClick={() => setSelectedNode(n)}
                                                className="flex-1 cursor-pointer"
                                            >
                                                <div className="flex items-center gap-2">
                                                    <span className={`font-mono font-bold text-xs ${isTie ? 'text-amber-400' : 'text-primary'}`}>
                                                        {n.label}
                                                    </span>
                                                    <span className="text-[10px] text-slate-500 uppercase">({n.kind})</span>
                                                </div>
                                                {n.description && (
                                                    <p className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">{n.description}</p>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-1 pl-2">
                                                <button
                                                    onClick={() => handleOpenCatalogSearch(n.label, n.kind)}
                                                    className="p-1 text-slate-500 hover:text-sky-400 rounded hover:bg-slate-800 transition-colors"
                                                    title="Search in Catalog (New Tab)"
                                                >
                                                    <ExternalLink className="h-3 w-3" />
                                                </button>
                                                <Badge 
                                                    onClick={() => setSelectedNode(n)}
                                                    variant="outline" 
                                                    className="text-[9px] text-slate-400 border-slate-800 group-hover:border-primary/30 cursor-pointer"
                                                >
                                                    Inspect
                                                </Badge>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </aside>
            )}

            {/* AI Describe Copilot Drawer */}
            <PIDDescribeDrawer
                isOpen={isDescribeOpen}
                onClose={() => setIsDescribeOpen(false)}
                sessionId={pidGraph?.sessionId || 'default'}
                onGraphUpdated={(newGraph) => {
                    if (newGraph) updatePidGraph(newGraph);
                }}
            />

            {/* Ingest Scanned Drawing Modal */}
            <PIDIngestModal
                isOpen={isIngestOpen}
                onClose={() => setIsIngestOpen(false)}
                sessionId={pidGraph?.sessionId || 'default'}
                onExtracted={(result) => {
                    if (result?.verified_nodes) {
                        updatePidGraph({
                            ...(pidGraph || { nodes: [], edges: [] }),
                            nodes: result.verified_nodes,
                            edges: result.verified_edges || [],
                        });
                    }
                }}
            />
        </div>
    </div>
);
}

