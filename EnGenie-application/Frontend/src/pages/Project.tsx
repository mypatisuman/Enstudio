import { useState, useRef, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Send, Loader2, Play, Bot, LogOut, User, Upload, Save, FolderOpen, FileText, Download, X, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Cpu, Wrench, Compass, ListChecks } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/use-toast';
import { BASE_URL } from '../components/AIRecommender/api';
import { callSolutionAgent, classifyRoute, confirmRouteResponse, clearSessionMemory, submitFeedback } from '@/components/AIRecommender/api';
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import StreamingProgress from '@/components/AIRecommender/StreamingProgress';

import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuItem,
    DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import AIRecommender from "@/components/AIRecommender";
import { useAuth } from '@/contexts/AuthContext';
import ProjectListDialog from '@/components/ProjectListDialog';
import DownloadWorkflowDialog from '@/components/DownloadWorkflowDialog';
import MainHeader from '@/components/MainHeader';
import '../components/TabsLayout.css';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { ProfileEditDialog } from '@/components/ProfileEditDialog';

interface IdentifiedInstrument {
    category: string;
    quantity?: number;
    productName: string;
    specifications: Record<string, string>;
    sampleInput: string;
    specifiedVendors?: string[];  // Vendors specified by user for this instrument
    specifiedModelFamilies?: string[];  // Model families specified by user (e.g., "3051", "STT850")
    strategy?: string;            // Procurement strategy from user requirements
    // Standards RAG fields (per-instrument)
    userSpecifiedStandards?: string[];  // Standards explicitly mentioned by user
    skipStandards?: boolean;  // True if user said no standards for this instrument
    standardsSpecs?: Record<string, string>;  // Specifications from standards document
    applicableStandards?: string[];  // List of applicable standard names
    applicableStandardsTitles?: Record<string, string | null>;  // standard code -> title
    standardsSummary?: string;  // Summary of standards requirements
    standardsSource?: string;  // Where standards came from
}

interface IdentifiedAccessory {
    category: string;
    quantity?: number;
    accessoryName: string;
    specifications: Record<string, string>;
    sampleInput: string;
    specifiedVendors?: string[];  // Vendors specified by user for this accessory
    specifiedModelFamilies?: string[];  // Model families inherited from parent instrument
    strategy?: string;            // Procurement strategy from user requirements
    parentInstrumentCategory?: string;  // Link to parent instrument for vendor inheritance
    // Standards RAG fields (per-accessory)
    userSpecifiedStandards?: string[];  // Standards explicitly mentioned by user
    skipStandards?: boolean;  // True if user said no standards for this accessory
    standardsSpecs?: Record<string, string>;  // Specifications from standards document
    applicableStandards?: string[];  // List of applicable standard names
    applicableStandardsTitles?: Record<string, string | null>;  // standard code -> title
    standardsSummary?: string;  // Summary of standards requirements
    standardsSource?: string;  // Where standards came from
}

// Optimized engineering solution from the standalone parallel solution-build agent.
// Returned alongside the BOM on the requirements path (keys camelCased by backend).
interface DesignedSolutionComponentRole {
    name: string;
    category: string;
    purpose: string;
}
interface PIDNode {
    id: string;
    label: string;
    kind: string;
    description?: string;
    area?: string;
    subsystemId?: string;
    subsystem_id?: string;
    isTieIn?: boolean;
    is_tie_in?: boolean;
    tieInLabel?: string;
    tie_in_label?: string;
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
}
interface PIDEdge {
    from: string;
    to: string;
    kind: string;
    label?: string;
}
interface PIDSubsystemArea {
    id: string;
    name: string;
    x: number;
    y: number;
    width: number;
    height: number;
    nodeIds?: string[];
    node_ids?: string[];
}
interface PIDGraph {
    projectType?: 'greenfield' | 'brownfield';
    project_type?: 'greenfield' | 'brownfield';
    nodes: PIDNode[];
    edges: PIDEdge[];
    subsystemAreas?: PIDSubsystemArea[];
    subsystem_areas?: PIDSubsystemArea[];
    summary?: string;
    svgPreview?: string;
    svg_preview?: string;
    // Persisted drawing: a decision the retrofit agent is waiting on, answered
    // in the P&ID Studio (confirm_delete | subsystem_choice).
    sessionId?: string;
    revision?: number;
    pendingAction?: { kind: string; question?: string } | null;
}
interface DesignedSolution {
    projectObjective: string;
    designOverview: string;
    componentRoles: DesignedSolutionComponentRole[];
    optimizations: string[];
    designConsiderations: string[];
    assumptions: string[];
    pidGraph?: PIDGraph;
    pid_graph?: PIDGraph;
}

// Vendor search parameters to pass to Search tabs
interface VendorSearchParams {
    category: string;
    productName: string;
    strategy?: string;
    specifiedVendors?: string[];
    specifiedModelFamilies?: string[];
    applicableStandards?: string[];
    applicableStandardsTitles?: Record<string, string | null>;
    standardsSpecs?: Record<string, string>;
}

// Chat message interface for Project page
interface ProjectChatMessage {
    id: string;
    type: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    metadata?: {
        routerRedirect?: boolean;
        routerUrl?: string;
        routerTargetPage?: string;
        cacheConfirmation?: boolean;
        matchedProjects?: any[];
        projectId?: string;
    };
}

const cleanImageUrl = (url: string | undefined | null): string => {
    if (!url) return '';
    const prefix = "x-raw-image:///";
    if (url.startsWith(prefix)) {
        return url.slice(prefix.length);
    }
    return url;
};

const getAbsoluteImageUrl = (url: string | undefined | null): string | undefined => {
    const clean = cleanImageUrl(url);
    if (!clean) return undefined;
    if (clean.startsWith('http') || clean.startsWith('data:') || clean.startsWith('blob:')) {
        return clean;
    }
    return `${BASE_URL}${clean.startsWith('/') ? '' : '/'}${clean}`;
};

// MessageRow component with animations (same as Dashboard)
interface MessageRowProps {
    message: ProjectChatMessage;
    isHistory: boolean;
    onCacheOpen?: (projectId: string) => void;
    onCachePreview?: (projectId: string) => void;
    onCacheIgnore?: () => void;
    designedSolution?: DesignedSolution | null;
    onDownloadWorkflow?: () => void;
}

const MessageRow = ({ message, isHistory, onCacheOpen, onCachePreview, onCacheIgnore, designedSolution, onDownloadWorkflow }: MessageRowProps) => {
    const isRecent = useMemo(() => {
        if (!message.timestamp) return false;
        try {
            const tsDate = message.timestamp instanceof Date ? message.timestamp : new Date(message.timestamp);
            const diff = Date.now() - tsDate.getTime();
            return diff >= 0 && diff < 5000;
        } catch {
            return false;
        }
    }, [message.timestamp]);

    const effectiveIsHistory = isHistory || !isRecent;
    const [isVisible, setIsVisible] = useState(effectiveIsHistory);
    const navigate = useNavigate();

    useEffect(() => {
        if (!effectiveIsHistory) {
            const delay = message.type === 'user' ? 200 : 0;
            const timer = setTimeout(() => {
                setIsVisible(true);
            }, delay);
            return () => clearTimeout(timer);
        } else {
            setIsVisible(true);
        }
    }, [effectiveIsHistory, message.type]);

    const formatTimestamp = (ts: Date) => {
        try {
            return ts.toLocaleTimeString();
        } catch {
            return '';
        }
    };

    const handleNavigate = () => {
        if (message.metadata?.routerUrl) {
            window.open(message.metadata.routerUrl, '_blank');
        }
    };

    return (
        <div className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] flex items-start space-x-2 ${message.type === 'user' ? 'flex-row-reverse space-x-reverse' : ''}`}>
                <div className={`flex-shrink-0 w-16 h-16 rounded-full flex items-center justify-center ${message.type === 'user' ? 'bg-transparent text-white -mt-3' : 'bg-transparent'}`}>
                    {message.type === 'user' ? (
                        <img src="/icon-user-3d.png" alt="User" className="w-16 h-16 object-contain" />
                    ) : (
                        <img src="/engenie icon.jpeg" alt="Assistant" className="w-20 h-20 object-contain rounded-full" />
                    )}
                </div>
                <div className="flex-1">
                    <div
                        className={`break-words ${message.type === 'user' ? 'glass-bubble-user' : 'glass-bubble-assistant'} relative`}
                        style={{
                            opacity: isVisible ? 1 : 0,
                            transform: isVisible ? 'scale(1)' : 'scale(0.8)',
                            transformOrigin: message.type === 'user' ? 'top right' : 'top left',
                            transition: 'opacity 0.8s ease-out, transform 0.8s cubic-bezier(0.175, 0.885, 0.32, 1.275)'
                        }}
                    >
                        <div>
                            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{message.content}</ReactMarkdown>
                        </div>

                        {/* Cache confirmation actions */}
                        {message.metadata?.cacheConfirmation && (
                            <div className="mt-3 flex flex-wrap gap-2">
                                <Button
                                    onClick={() => onCacheOpen?.(message.metadata?.projectId || '')}
                                    disabled={!message.metadata?.projectId}
                                    className="bg-blue-600 hover:bg-blue-500 text-white font-semibold shadow-sm"
                                    size="sm"
                                >
                                    Open
                                </Button>
                                <Button
                                    onClick={() => onCachePreview?.(message.metadata?.projectId || '')}
                                    disabled={!message.metadata?.projectId}
                                    className="bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 hover:border-blue-300 font-semibold shadow-sm"
                                    size="sm"
                                >
                                    Preview
                                </Button>
                                <Button
                                    onClick={() => onCacheIgnore?.()}
                                    variant="ghost"
                                    className="text-blue-500 hover:text-blue-700 hover:bg-blue-100"
                                    size="sm"
                                >
                                    Ignore
                                </Button>
                            </div>
                        )}

                        {/* Router redirect button */}
                        {message.metadata?.routerRedirect && message.metadata?.routerUrl && (
                            <div className="mt-3">
                                <Button
                                    onClick={handleNavigate}
                                    className="bg-sky-500 hover:bg-sky-600 text-white"
                                    size="sm"
                                >
                                    Open {message.metadata.routerTargetPage || 'Chat'} Page
                                </Button>
                            </div>
                        )}

                        {/* Designed Solution embedded inside the assistant bubble */}
                        {designedSolution && message.type === 'assistant' && (
                            <div className="mt-4 pt-4 border-t border-primary/20 space-y-3">
                                <div className="text-sm font-semibold text-primary">Designed Solution</div>
                                {designedSolution.projectObjective && (
                                    <p className="text-sm"><span className="font-medium">Objective: </span>{designedSolution.projectObjective}</p>
                                )}
                                {designedSolution.designOverview && (
                                    <p className="text-sm text-muted-foreground">{designedSolution.designOverview}</p>
                                )}
                                {designedSolution.componentRoles?.length > 0 && (
                                    <div>
                                        <p className="text-xs font-semibold uppercase text-muted-foreground mb-1">Component Roles</p>
                                        <ul className="space-y-1">
                                            {designedSolution.componentRoles.map((c, i) => (
                                                <li key={i} className="text-sm"><span className="font-medium">{c.name || c.category}:</span> {c.purpose}</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                                {designedSolution.optimizations?.length > 0 && (
                                    <div>
                                        <p className="text-xs font-semibold uppercase text-muted-foreground mb-1">Optimizations</p>
                                        <ul className="list-disc pl-5 space-y-0.5">
                                            {designedSolution.optimizations.map((o, i) => <li key={i} className="text-sm">{o}</li>)}
                                        </ul>
                                    </div>
                                )}
                                {designedSolution.designConsiderations?.length > 0 && (
                                    <div>
                                        <p className="text-xs font-semibold uppercase text-muted-foreground mb-1">Design Considerations</p>
                                        <ul className="list-disc pl-5 space-y-0.5">
                                            {designedSolution.designConsiderations.map((o, i) => <li key={i} className="text-sm">{o}</li>)}
                                        </ul>
                                    </div>
                                )}
                                {designedSolution.assumptions?.length > 0 && (
                                    <div>
                                        <p className="text-xs font-semibold uppercase text-muted-foreground mb-1">Assumptions</p>
                                        <ul className="list-disc pl-5 space-y-0.5">
                                            {designedSolution.assumptions.map((o, i) => <li key={i} className="text-sm">{o}</li>)}
                                        </ul>
                                    </div>
                                )}

                                {/* P&ID Diagram Preview */}
                                {(designedSolution.pidGraph || designedSolution.pid_graph) && (() => {
                                    const pid = designedSolution.pidGraph || designedSolution.pid_graph;
                                    const svgContent = pid?.svgPreview || pid?.svg_preview;
                                    const projType = (pid?.projectType || pid?.project_type || 'greenfield').toLowerCase();
                                    const isBrownfield = projType === 'brownfield';
                                    const subAreas = pid?.subsystemAreas || pid?.subsystem_areas || [];
                                    return (
                                        <div className="mt-4 pt-3 border-t border-primary/20 space-y-2.5">
                                            <div className="flex items-center justify-between flex-wrap gap-2">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-bold uppercase tracking-wider text-primary">P&ID Process Schematic</span>
                                                    <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full border ${
                                                        isBrownfield 
                                                            ? 'bg-amber-500/10 text-amber-600 border-amber-500/30' 
                                                            : 'bg-sky-500/10 text-sky-600 border-sky-500/30'
                                                    }`}>
                                                        {isBrownfield ? 'BROWNFIELD RETROFIT' : 'GREENFIELD DESIGN'}
                                                    </span>
                                                    <span className="px-2 py-0.5 text-[10px] font-semibold bg-muted text-muted-foreground rounded-full">
                                                        {pid?.nodes?.length || 0} Elements · {pid?.edges?.length || 0} Lines
                                                    </span>
                                                    {pid?.pendingAction && (
                                                        <span
                                                            className="px-2 py-0.5 text-[10px] font-bold rounded-full border bg-amber-500/10 text-amber-600 border-amber-500/40"
                                                            title={pid.pendingAction.question}
                                                        >
                                                            {pid.pendingAction.kind === 'confirm_delete'
                                                                ? 'Removal awaiting your confirmation'
                                                                : 'Choose a subsystem'} · open the studio
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <button
                                                        onClick={(e) => {
                                                            e.preventDefault();
                                                            const sTitle = (designedSolution as any)?.project_name || (designedSolution as any)?.project_objective || 'Engineering Solution P&ID';
                                                            try {
                                                                localStorage.setItem('active_pid_graph', JSON.stringify(pid));
                                                                localStorage.setItem('active_designed_solution', JSON.stringify(designedSolution));
                                                                localStorage.setItem('active_solution_title', sTitle);
                                                            } catch (err) {
                                                                console.error('Failed to save PID state to localStorage:', err);
                                                            }
                                                            window.open('/solution/pid-viewer', '_blank');
                                                        }}
                                                        className="px-2.5 py-1 text-[11px] font-semibold rounded-md bg-primary/10 text-primary hover:bg-primary hover:text-white transition-all duration-200 flex items-center gap-1.5 border border-primary/30 shadow-xs cursor-pointer group"
                                                        title="Open in Dedicated Full-Screen P&ID Studio (New Tab)"
                                                    >
                                                        <Compass className="h-3.5 w-3.5 group-hover:rotate-45 transition-transform duration-300" />
                                                        <span>Open Dedicated P&ID Studio ↗</span>
                                                    </button>
                                                    {svgContent && (
                                                        <button
                                                            onClick={() => {
                                                                const blob = new Blob([svgContent], { type: 'image/svg+xml' });
                                                                const url = URL.createObjectURL(blob);
                                                                const a = document.createElement('a');
                                                                a.href = url;
                                                                a.download = `pid_${projType}_diagram.svg`;
                                                                a.click();
                                                                URL.revokeObjectURL(url);
                                                            }}
                                                            className="text-[11px] font-medium text-muted-foreground hover:text-primary transition-colors flex items-center gap-1 px-1.5 py-1"
                                                            title="Download SVG"
                                                        >
                                                            Download SVG
                                                        </button>
                                                    )}
                                                    {onDownloadWorkflow && (
                                                        <button
                                                            onClick={(e) => {
                                                                e.preventDefault();
                                                                onDownloadWorkflow();
                                                            }}
                                                            className="text-[11px] font-medium text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 transition-colors flex items-center gap-1 px-1.5 py-1"
                                                            title="Download Workflow Input & Output Data"
                                                        >
                                                            <Download className="h-3.5 w-3.5" />
                                                            Download Data
                                                        </button>
                                                    )}
                                                </div>
                                            </div>

                                            {/* Sub-system Area Chips */}
                                            {subAreas.length > 0 && (
                                                <div className="flex items-center gap-1.5 flex-wrap">
                                                    <span className="text-[10px] font-semibold uppercase text-muted-foreground">Sub-systems:</span>
                                                    {subAreas.map((area, sIdx) => (
                                                        <span
                                                            key={sIdx}
                                                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary/5 text-primary text-[10px] font-medium border border-primary/20"
                                                        >
                                                            <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                                                            {area.name}
                                                        </span>
                                                    ))}
                                                </div>
                                            )}

                                            {pid?.summary && (
                                                <p className="text-xs text-muted-foreground italic">{pid.summary}</p>
                                            )}
                                            {svgContent && (
                                                <div className="overflow-x-auto rounded-lg border border-border/60 bg-white p-2 shadow-sm max-h-[390px]">
                                                    <div
                                                        className="min-w-[680px] w-full"
                                                        dangerouslySetInnerHTML={{ __html: svgContent }}
                                                    />
                                                </div>
                                            )}
                                            {pid?.nodes && pid.nodes.length > 0 && (
                                                <div className="space-y-1.5 pt-1">
                                                    <div className="flex items-center justify-between">
                                                        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                                                            Instruments & Connected Accessories ({pid.nodes.length}):
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {pid.nodes.map((n, idx) => {
                                                            const isTie = n.isTieIn || n.is_tie_in || n.kind === 'tie_in';
                                                            const vendorName = n.vendor;
                                                            const modelName = n.model_series || n.modelSeries || n.model_family || n.modelFamily;
                                                            const parentTag = n.parent_instrument_tag || n.parentInstrumentTag;
                                                            const tooltipText = [
                                                                `${n.label} (${isTie ? 'Tie-In Point' : n.kind})`,
                                                                n.description ? `Function: ${n.description}` : '',
                                                                vendorName ? `Vendor: ${vendorName}` : '',
                                                                modelName ? `Model: ${modelName}` : '',
                                                                parentTag ? `Supports: ${parentTag}` : '',
                                                                n.standards && n.standards.length > 0 ? `Standards: ${n.standards.join(', ')}` : '',
                                                            ].filter(Boolean).join('\n');

                                                            return (
                                                                <span
                                                                    key={idx}
                                                                    className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium border transition-all hover:scale-[1.02] cursor-help ${
                                                                        isTie 
                                                                            ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/30' 
                                                                            : 'bg-muted/70 hover:bg-muted text-foreground/90 border-border/60'
                                                                    }`}
                                                                    title={tooltipText}
                                                                >
                                                                    <span className={`font-bold font-mono ${isTie ? 'text-amber-600 dark:text-amber-400' : 'text-primary'}`}>{n.label}</span>
                                                                    {vendorName && (
                                                                        <span className="text-[9px] px-1 py-0.2 rounded bg-primary/10 text-primary font-semibold">
                                                                            {vendorName.split(' ')[0]}
                                                                        </span>
                                                                    )}
                                                                    <span className="text-[9px] text-muted-foreground">
                                                                        ({isTie ? 'Tie-In' : n.kind})
                                                                    </span>
                                                                </span>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })()}
                            </div>
                        )}
                    </div>

                    <p
                        className={`text-xs text-muted-foreground mt-1 px-1 ${message.type === 'user' ? 'text-right' : ''}`}
                        style={{
                            opacity: isVisible ? 1 : 0,
                            transition: 'opacity 0.8s ease 0.3s'
                        }}
                    >
                        {formatTimestamp(message.timestamp)}
                    </p>
                </div>
            </div>
        </div>
    );
};

// IndexedDB configuration for persisting project state (no size limits like localStorage)
const PROJECT_DB_NAME = 'project_page_db';
const PROJECT_STORE_NAME = 'project_state';

const getProjectTabId = () => {
    let tabId = sessionStorage.getItem('project_app_tab_id');
    if (!tabId) {
        tabId = `tab_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        sessionStorage.setItem('project_app_tab_id', tabId);
    }
    return tabId;
};

const getProjectStateKey = () => `current_session_${getProjectTabId()}`;
const getProjectBackupKey = () => `project_state_backup_${getProjectTabId()}`;

// Helper function to open IndexedDB
const openProjectDB = (): Promise<IDBDatabase> => {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(PROJECT_DB_NAME, 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (event) => {
            const db = (event.target as IDBOpenDBRequest).result;
            if (!db.objectStoreNames.contains(PROJECT_STORE_NAME)) {
                db.createObjectStore(PROJECT_STORE_NAME, { keyPath: 'id' });
            }
        };
    });
};

// Helper function to save state to IndexedDB
const saveStateToIndexedDB = async (state: any): Promise<void> => {
    try {
        const db = await openProjectDB();
        const transaction = db.transaction(PROJECT_STORE_NAME, 'readwrite');
        const store = transaction.objectStore(PROJECT_STORE_NAME);

        await new Promise<void>((resolve, reject) => {
            const request = store.put({ id: getProjectStateKey(), ...state });
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });

        db.close();
    } catch (e) {
        console.warn('[PROJECT] Failed to save to IndexedDB:', e);
    }
};

// Helper function to load state from IndexedDB
const loadStateFromIndexedDB = async (): Promise<any | null> => {
    try {
        const db = await openProjectDB();
        const transaction = db.transaction(PROJECT_STORE_NAME, 'readonly');
        const store = transaction.objectStore(PROJECT_STORE_NAME);

        const result = await new Promise<any>((resolve, reject) => {
            const request = store.get(getProjectStateKey());
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });

        db.close();

        if (result) {
            // Restore Date objects for chat messages
            if (result.chatMessages) {
                result.chatMessages = result.chatMessages.map((msg: any) => ({
                    ...msg,
                    timestamp: new Date(msg.timestamp)
                }));
            }
            // Restore Date objects in tabStates messages
            if (result.tabStates) {
                Object.values(result.tabStates).forEach((state: any) => {
                    if (state?.messages) {
                        state.messages = state.messages.map((msg: any) => ({
                            ...msg,
                            timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date()
                        }));
                    }
                });
            }
            return result;
        }
        return null;
    } catch (e) {
        console.warn('[PROJECT] Failed to load from IndexedDB:', e);
        return null;
    }
};

// Helper function to clear IndexedDB state
const clearIndexedDBState = async (): Promise<void> => {
    try {
        const db = await openProjectDB();
        const transaction = db.transaction(PROJECT_STORE_NAME, 'readwrite');
        const store = transaction.objectStore(PROJECT_STORE_NAME);

        await new Promise<void>((resolve, reject) => {
            const request = store.delete(getProjectStateKey());
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });

        db.close();
        console.log('[PROJECT] IndexedDB state cleared');
    } catch (e) {
        console.warn('[PROJECT] Failed to clear IndexedDB:', e);
    }
};

// Synchronous loader that returns cached state (populated by async load on mount)
const cachedSavedState: any = null;

// Helper function to load state synchronously from cache (for initial render)
const loadSavedState = () => {
    return cachedSavedState;
};

// Greeting messages for Solution page (shown when opened from video navigation)
const SOLUTION_GREETINGS = [
    "Welcome to Solution Studio. I am your AI assistant. Please provide your project requirements, and I will analyze them to identify the appropriate instruments and accessories.",

    "Hello. I am your AI assistant. Share your process details or project requirements, and I will determine the suitable instrumentation and supporting components.",

    "You are now in the Solution workspace. I am your AI assistant. Describe your application, operating conditions, and constraints, and I will generate a structured list of required instruments and accessories.",

    "I am your AI assistant. Please enter your project specifications, including process parameters and environmental conditions, and I will evaluate them to recommend the correct instruments and accessories.",

    "Welcome. I am your AI assistant. Provide your greenfield or brownfield project requirements, and I will break them down into a complete and structured Bill of Materials."
];

const Project = () => {
    // Load saved state once on mount
    const savedState = loadSavedState();

    // If opened via fresh routing (from another screen), ignore ALL saved state
    // so we start with a clean slate for the new incoming query
    const isFreshRouting = new URLSearchParams(window.location.search).get('fresh') === 'true';
    const effectiveState = isFreshRouting ? null : savedState;

    const [requirements, setRequirements] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [streamId, setStreamId] = useState<string | null>(null);
    const [instruments, setInstruments] = useState<IdentifiedInstrument[]>(effectiveState?.instruments || []);
    const [accessories, setAccessories] = useState<IdentifiedAccessory[]>(effectiveState?.accessories || []);
    const [designedSolution, setDesignedSolution] = useState<DesignedSolution | null>(effectiveState?.designedSolution || null);
    const [collapsedInstruments, setCollapsedInstruments] = useState<Set<number>>(new Set());
    const [collapsedAccessories, setCollapsedAccessories] = useState<Set<number>>(new Set());
    const [selectedInstruments, setSelectedInstruments] = useState<Set<number>>(new Set());
    const [selectedAccessories, setSelectedAccessories] = useState<Set<number>>(new Set());
    const [showResults, setShowResults] = useState(effectiveState?.showResults || false);
    const [activeTab, setActiveTab] = useState<string>(effectiveState?.activeTab || 'project');
    const [previousTab, setPreviousTab] = useState<string>(effectiveState?.previousTab || 'project');
    const [searchTabs, setSearchTabs] = useState<{ id: string; title: string; input: string; vendorSearchParams?: VendorSearchParams; tabType?: 'instrument' | 'accessory' }[]>(effectiveState?.searchTabs || []);
    const [projectName, setProjectName] = useState<string>(effectiveState?.projectName || 'Project');
    const [editingProjectName, setEditingProjectName] = useState<boolean>(false);
    const [editProjectNameValue, setEditProjectNameValue] = useState<string>(effectiveState?.projectName || 'Project');
    const editNameInputRef = useRef<HTMLInputElement | null>(null);
    const [currentProjectId, setCurrentProjectId] = useState<string | null>(effectiveState?.currentProjectId || null);
    const [duplicateNameDialogOpen, setDuplicateNameDialogOpen] = useState(false);
    const [duplicateProjectName, setDuplicateProjectName] = useState<string | null>(null);
    const [autoRenameSuggestion, setAutoRenameSuggestion] = useState<string | null>(null);
    const [duplicateDialogNameInput, setDuplicateDialogNameInput] = useState<string>('');
    const [duplicateDialogError, setDuplicateDialogError] = useState<string | null>(null);
    const [isProjectListOpen, setIsProjectListOpen] = useState(false);
    const [isProfileEditOpen, setIsProfileEditOpen] = useState(false);
    // Track server banner visibility to adjust layout padding
    const [isServerBannerVisible, setIsServerBannerVisible] = useState(false);

    // Standards toggle - ON by default, user can turn off to skip standards application
    const [standardsEnabled, setStandardsEnabled] = useState<boolean>(effectiveState?.standardsEnabled ?? true);



    // Server Auto-Save states
    // NOTE: Keys are scoped to userSessionId so each login session gets its own choice.
    // userSessionId comes from AuthContext (generated fresh on every login).
    // We resolve the current session's key at runtime via localStorage (same source as AuthContext).
    const getAutosaveChoiceKey = () => {
        const sid = localStorage.getItem('user_session_id') || 'global';
        return `autosave_choice_${sid}`;
    };
    const getAutosaveSkipKey = () => {
        const sid = localStorage.getItem('user_session_id') || 'global';
        return `autosave_skip_${sid}`;
    };

    const [isServerAutoSaveEnabled, setIsServerAutoSaveEnabled] = useState<boolean>(() => {
        // Check the session-scoped key first; fall back to legacy key for backward compat
        const sessionKey = getAutosaveChoiceKey();
        const sessionChoice = localStorage.getItem(sessionKey);
        if (sessionChoice !== null) return sessionChoice === 'true';
        return false; // New session → default off until user chooses
    });
    // Start hidden; a useEffect below will show it once userSessionId is confirmed available
    const [showGoogleSavePopup, setShowGoogleSavePopup] = useState<boolean>(false);
    const [showInitProjectDialog, setShowInitProjectDialog] = useState<boolean>(false);
    const [initProjectName, setInitProjectName] = useState<string>('');
    const [initProjectError, setInitProjectError] = useState<string | null>(null);
    const [isInitializing, setIsInitializing] = useState<boolean>(false);

    // Holds the most recently submitted requirements so the server project can be
    // created lazily once results exist (deferred from submit to avoid empty projects).
    const lastSubmittedRequirementsRef = useRef<string>('');

    // Repeated Request cache confirmation dialog states
    const [cacheConfirmationOpen, setCacheConfirmationOpen] = useState(false);
    const [cacheConfirmationData, setCacheConfirmationData] = useState<any>(null);
    const [selectedCacheProjectId, setSelectedCacheProjectId] = useState<string>('');
    const [previewProjectData, setPreviewProjectData] = useState<any>(null);
    const [isPreviewLoading, setIsPreviewLoading] = useState(false);

    // Right panel dock state
    const [isRightDocked, setIsRightDocked] = useState(effectiveState?.isRightDocked ?? true);
    // Right panel tab state (instruments/accessories)
    const [rightPanelTab, setRightPanelTab] = useState<'instruments' | 'accessories'>('instruments');
    // Right panel resizable width (percentage)
    const [rightPanelWidth, setRightPanelWidth] = useState(47);
    const [draggingResizer, setDraggingResizer] = useState(false);
    const resizerAnimFrameRef = useRef<number | null>(null);

    // State to track image loading/regeneration
    const [loadingImages, setLoadingImages] = useState<Set<string>>(new Set());
    const [regeneratingImages, setRegeneratingImages] = useState<Set<string>>(new Set());

    // Track conversation states for each search tab
    const [tabStates, setTabStates] = useState<Record<string, any>>(effectiveState?.tabStates || {});
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const [hasAutoSubmitted, setHasAutoSubmitted] = useState(false);
    const { toast } = useToast();
    const { user, logout, userSessionId } = useAuth(); // Get user session ID from AuthContext

    const handleSubmitRef = useRef<((overrideRequirements?: string) => void) | null>(null);

    // NEW: For scroll position handling
    const projectScrollRef = useRef<HTMLDivElement | null>(null);
    const rightPanelScrollRef = useRef<HTMLDivElement | null>(null); // For right panel scroll
    const [savedScrollPosition, setSavedScrollPosition] = useState(0);
    // Track current scroll positions continuously (updated on scroll events)
    const currentScrollPositionRef = useRef(0);
    const rightPanelScrollPositionRef = useRef(0); // Right panel scroll position

    // NEW: For generic product type images
    const [genericImages, setGenericImages] = useState<Record<string, string>>(effectiveState?.genericImages || {});

    // Sync currentProjectId with URL query parameters so page refresh/reload works correctly
    useEffect(() => {
        if (currentProjectId) {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('projectId') !== currentProjectId) {
                urlParams.set('projectId', currentProjectId);
                window.history.replaceState(null, '', `${window.location.pathname}?${urlParams.toString()}`);
                console.log('[PROJECT] Synced currentProjectId with URL:', currentProjectId);
            }
        }
    }, [currentProjectId, location.pathname]);

    // Helper to find a generic image URL with robust, case-insensitive, and normalization support
    // Auto-detects and treats expired SAS URLs as cache misses so they get re-fetched fresh
    const findGenericImageUrl = (imageKey: string | undefined | null): string | undefined => {
        if (!imageKey) return undefined;

        const isUrlExpired = (url: string | undefined): boolean => {
            if (!url) return true;
            // Invalidate old incorrect positioner images that don't have the cache buster parameter
            const normKey = imageKey.toLowerCase().replace(/[\s_-]+/g, '');
            if (normKey.includes('positioner') && !url.includes('v=1.1')) {
                return true;
            }
            try {
                // Only direct SAS URLs contain 'sig=' and 'se='
                if (url.includes('sig=') || url.includes('se=')) {
                    const urlObj = new URL(url);
                    const se = urlObj.searchParams.get('se');
                    if (se) {
                        const expiryDate = new Date(se);
                        const now = new Date();
                        // Expired if current time + 5 minutes is past expiry
                        return expiryDate.getTime() <= (now.getTime() + 5 * 60 * 1000);
                    }
                }
            } catch (e) {
                // If parsing fails (e.g. relative url), assume it is not expired
            }
            return false;
        };

        if (genericImages[imageKey] && !isUrlExpired(genericImages[imageKey])) {
            return genericImages[imageKey];
        }

        // Case-insensitive / whitespace-normalized lookup fallback
        const normKey = imageKey.toLowerCase().replace(/[\s_-]+/g, '');
        const foundEntry = Object.entries(genericImages).find(([k, url]) => {
            return k.toLowerCase().replace(/[\s_-]+/g, '') === normKey && !isUrlExpired(url);
        });
        return foundEntry ? foundEntry[1] : undefined;
    };

    // NEW: Chat messages for Project page (replaces responseMessage)
    const [chatMessages, setChatMessages] = useState<ProjectChatMessage[]>(effectiveState?.chatMessages || []);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const isHistoryRef = useRef(true);
    const [showThinking, setShowThinking] = useState(false);

    // NEW: For file upload
    const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
    const [extractedText, setExtractedText] = useState<string>('');
    const [isExtracting, setIsExtracting] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    // Guard against re-processing the same initialQuery when searchTabs.length changes
    const handledInitialQueryRef = useRef<string | null>(null);


    // NEW: Project instance ID for isolating Project tab conversations
    // Each Project tab gets its own unique instance ID to prevent cross-contamination
    const [projectInstanceId, setProjectInstanceId] = useState<string>(() => {
        // If opened fresh via routing (fresh=true in URL / effectiveState is null), always generate a new ID
        if (isFreshRouting || !effectiveState?.projectInstanceId) {
            const newId = `solution_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            console.log('[PROJECT_INSTANCE] Fresh routing - created new instance ID:', newId);
            return newId;
        }
        // Restore saved instance ID if available (for page refresh persistence)
        console.log('[PROJECT_INSTANCE] Restoring saved instance ID:', effectiveState.projectInstanceId);
        return effectiveState.projectInstanceId;
    });

    // Track if this is the first input of the session (for router optimization)
    // First input calls router classifier, subsequent inputs skip it
    const [isFirstInputProcessed, setIsFirstInputProcessed] = useState<boolean>(false);

    // Helper function to generate a new instance ID
    const generateNewInstanceId = () => {
        return `solution_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    };

    // State for solution workflow input and output data download
    const [isDownloadDialogOpen, setIsDownloadDialogOpen] = useState<boolean>(false);
    const [lastIntentResult, setLastIntentResult] = useState<any>(null);

    const exportWorkflowParams = useMemo(() => {
        return {
            projectName: projectName,
            projectId: currentProjectId,
            sessionId: projectInstanceId || userSessionId,
            userRequirements: lastSubmittedRequirementsRef.current || requirements || '',
            standardsEnabled: standardsEnabled,
            chatMessages: chatMessages,
            instruments: instruments,
            accessories: accessories,
            designedSolution: designedSolution,
            intentResult: lastIntentResult,
            streamId: streamId,
        };
    }, [projectName, currentProjectId, projectInstanceId, userSessionId, requirements, standardsEnabled, chatMessages, instruments, accessories, designedSolution, lastIntentResult, streamId]);


    // Auto-scroll to bottom when new messages arrive
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [chatMessages, showThinking]);

    // Set isHistory to false after initial mount so new messages animate
    useEffect(() => {
        const timer = setTimeout(() => {
            isHistoryRef.current = false;
        }, 1000);
        return () => clearTimeout(timer);
    }, []);

    // Show thinking indicator with delay
    useEffect(() => {
        if (isLoading) {
            const timer = setTimeout(() => setShowThinking(true), 600);
            return () => clearTimeout(timer);
        } else {
            setShowThinking(false);
        }
    }, [isLoading]);

    // Sync activeTab with URL on initial load
    // Note: Don't redirect if searchTabs is empty - state might still be loading from IndexedDB
    useEffect(() => {
        const issearchUrl = location.pathname === '/solution/search';
        const queryKey = searchParams.get('queryKey');
        let initialQuery = searchParams.get('initialQuery');

        if (queryKey) {
            const storedQuery = sessionStorage.getItem(queryKey) || localStorage.getItem(queryKey);
            if (storedQuery) {
                initialQuery = storedQuery;
                sessionStorage.removeItem(queryKey);
                localStorage.removeItem(queryKey);
            }
        }

        if (initialQuery) {
            // If we already processed this exact query, skip to avoid duplicate tabs
            // caused by searchTabs.length changing and re-firing this effect
            if (handledInitialQueryRef.current === initialQuery) return;
            handledInitialQueryRef.current = initialQuery;

            console.log('[Project] Handling initialQuery from URL/Storage:', initialQuery);

            // Remove the query param to prevent re-running on refresh
            const newParams = new URLSearchParams(searchParams);
            newParams.delete('initialQuery');
            newParams.delete('queryKey');
            navigate({ pathname: location.pathname, search: newParams.toString() }, { replace: true });

            if (issearchUrl) {
                // Arrived at /solution/search → open a new search tab
                const newTabId = `search_${Date.now()}`;
                const newTab = {
                    id: newTabId,
                    title: 'New Search',
                    input: initialQuery,
                    vendorSearchParams: undefined
                };
                setSearchTabs(prev => [...prev, newTab]);
                setActiveTab(newTabId);
            } else {
                // Arrived at /solution → fill the requirements textbox and switch to project tab
                setRequirements(initialQuery);
                setActiveTab('project');
            }

            return;
        }

        // Reset guard when there's no initialQuery (URL was cleared)
        handledInitialQueryRef.current = null;

        if (issearchUrl) {
            // If URL is /solution/search and we have search tabs, switch to first search tab if needed
            if (searchTabs.length > 0 && activeTab === 'project') {
                setActiveTab(searchTabs[0].id);
            }
            // Don't redirect to /solution if searchTabs is empty - state might still be loading
        } else if (location.pathname === '/solution') {
            // If URL is /solution, make sure we're on the project tab
            if (activeTab !== 'project' && !searchTabs.find(t => t.id === activeTab)) {
                setActiveTab('project');
            }
        }
    }, [searchTabs.length, searchParams, location.pathname]); // Re-run when URL or searchTabs changes

    // TRACK SCROLL POSITION: Update ref continuously on any scroll
    useEffect(() => {
        const handleProjectScroll = () => {
            // Capture scroll from left panel element and window
            const elementScroll = projectScrollRef.current?.scrollTop || 0;
            const windowScroll = window.scrollY || document.documentElement.scrollTop || 0;
            const currentScroll = Math.max(elementScroll, windowScroll);
            currentScrollPositionRef.current = currentScroll;
        };

        const handleRightPanelScroll = () => {
            // Capture scroll from right panel
            const rightScroll = rightPanelScrollRef.current?.scrollTop || 0;
            rightPanelScrollPositionRef.current = rightScroll;
        };

        // Listen to project/left panel scroll
        const projectElement = projectScrollRef.current;
        if (projectElement) {
            projectElement.addEventListener('scroll', handleProjectScroll, { passive: true });
        }
        window.addEventListener('scroll', handleProjectScroll, { passive: true });

        // Listen to right panel scroll
        const rightElement = rightPanelScrollRef.current;
        if (rightElement) {
            rightElement.addEventListener('scroll', handleRightPanelScroll, { passive: true });
        }

        return () => {
            if (projectElement) {
                projectElement.removeEventListener('scroll', handleProjectScroll);
            }
            window.removeEventListener('scroll', handleProjectScroll);
            if (rightElement) {
                rightElement.removeEventListener('scroll', handleRightPanelScroll);
            }
        };
    }, [showResults]); // Re-run when showResults changes (right panel mounts/unmounts)

    // State for tracking if initial load from IndexedDB is complete
    const [isRestoringState, setIsRestoringState] = useState(true);
    // Pending scroll positions to restore after DOM is ready
    const [pendingScrollPosition, setPendingScrollPosition] = useState<number | null>(null);
    const [pendingRightPanelScroll, setPendingRightPanelScroll] = useState<number | null>(null);

    // Feedback state management (for instrument and accessory cards)
    type FeedbackType = "positive" | "negative" | null;
    interface FeedbackEntry {
        type: FeedbackType;
        comment: string;
        loading: boolean;
        submitted: boolean;
        response?: string;
    }
    const [feedbackState, setFeedbackState] = useState<Record<string, FeedbackEntry>>({});
    const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
    const [feedbackModalItem, setFeedbackModalItem] = useState<{ key: string; type: string; name: string; data?: any } | null>(null);

    // Ref to track latest state for immediate save on page close
    const stateRef = useRef({
        chatMessages: [] as ProjectChatMessage[],
        instruments: [] as IdentifiedInstrument[],
        accessories: [] as IdentifiedAccessory[],
        designedSolution: null as DesignedSolution | null,
        showResults: false,
        activeTab: 'project',
        previousTab: 'project',
        searchTabs: [] as { id: string; title: string; input: string }[],
        projectName: 'Project',
        currentProjectId: null as string | null,
        isRightDocked: true,
        tabStates: {} as Record<string, any>,
        genericImages: {} as Record<string, string>,
        projectInstanceId: '', // Session ID for Project tab isolation
        standardsEnabled: true // Standards toggle state
    });

    // Feedback helper functions
    const openFeedbackModal = (
        key: string,
        itemType: string,
        itemName: string,
        initialFeedbackType?: FeedbackType,
        itemData?: any
    ) => {
        setFeedbackModalItem({ key, type: itemType, name: itemName, data: itemData });
        setFeedbackModalOpen(true);
        // Initialize feedback state if not exists, or update with initial type
        if (!feedbackState[key]) {
            setFeedbackState(prev => ({
                ...prev,
                [key]: { type: initialFeedbackType || null, comment: '', loading: false, submitted: false }
            }));
        } else if (initialFeedbackType) {
            // Update existing state with the initial feedback type
            setFeedbackState(prev => ({
                ...prev,
                [key]: { ...prev[key], type: initialFeedbackType }
            }));
        }
    };

    const closeFeedbackModal = () => {
        setFeedbackModalOpen(false);
        // Reset modal item after animation
        setTimeout(() => setFeedbackModalItem(null), 200);
    };

    const setFeedbackType = (key: string, type: FeedbackType) => {
        setFeedbackState(prev => ({
            ...prev,
            [key]: { ...prev[key], type, comment: prev[key]?.comment || '', loading: false, submitted: false }
        }));
    };

    const setFeedbackComment = (key: string, comment: string) => {
        setFeedbackState(prev => ({
            ...prev,
            [key]: { ...prev[key], comment, loading: false, submitted: false }
        }));
    };

    const submitFeedbackForItem = async () => {
        if (!feedbackModalItem) return;

        const { key, type: itemType, name: itemName, data: itemData } = feedbackModalItem;
        const fb = feedbackState[key];
        if (!fb || (!fb.type && !fb.comment.trim())) {
            toast({ title: "No feedback provided", description: "Please select thumbs up/down or add a comment", variant: "destructive" });
            return;
        }

        setFeedbackState(prev => ({ ...prev, [key]: { ...prev[key], loading: true } }));

        try {
            // Build complete item metadata from the card data
            const itemMetadata = {
                // Instrument/Accessory metadata
                itemType: itemType,
                itemName: itemName,  // Instrument/Accessory name
                vendorName: itemData?.vendorName || itemData?.vendor || '',
                category: itemData?.category || '',
                subcategory: itemData?.subcategory || '',
                model: itemData?.model || '',
                modelFamily: itemData?.modelFamily || '',
                subModel: itemData?.subModel || '',
                userQuery: itemData?.userQuery || '',
                recommendationContext: itemData?.recommendationContext || {},
                sessionId: projectInstanceId || currentProjectId || '',
                source: 'solution' // From solution/project tab
            };

            const response = await submitFeedback(
                fb.type,
                fb.comment.trim(),
                currentProjectId || undefined,
                itemMetadata
            );

            setFeedbackState(prev => ({
                ...prev,
                [key]: { ...prev[key], loading: false, submitted: true, response }
            }));
            toast({ title: "Feedback submitted!", description: "Thank you for your feedback." });

            // Close modal after 1 second to show success message
            setTimeout(() => {
                closeFeedbackModal();
            }, 1500);
        } catch (error: any) {
            setFeedbackState(prev => ({ ...prev, [key]: { ...prev[key], loading: false } }));
            toast({ title: "Error", description: error.message || "Failed to submit feedback", variant: "destructive" });
        }
    };

    const handleFeedbackKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submitFeedbackForItem();
        }
    };

    // Keep stateRef in sync with actual state
    useEffect(() => {
        stateRef.current = {
            chatMessages,
            instruments,
            accessories,
            designedSolution,
            showResults,
            activeTab,
            previousTab,
            searchTabs,
            projectName,
            currentProjectId,
            isRightDocked,
            tabStates,
            genericImages,
            projectInstanceId, // Include session ID in state tracking
            standardsEnabled // Include standards toggle in state tracking
        };
    }, [chatMessages, instruments, accessories, designedSolution, showResults, activeTab, previousTab, searchTabs, projectName, currentProjectId, isRightDocked, tabStates, genericImages, projectInstanceId, standardsEnabled]);

    // SESSION MEMORY: Cleared on explicit user actions (Reset, New Project) AND on tab close
    // - Frontend state: Saved in IndexedDB/localStorage, restored on page load
    // - Backend session: Cleared ONLY on actual tab close (NOT on refresh or navigation)
    // - Also cleared on: New Project button, Reset confirmed in conversation
    //
    // HOW IT WORKS (deferred cleanup pattern):
    // - beforeunload: Mark session as "pending cleanup" in localStorage
    // - sessionStorage survives refresh but is LOST on tab close
    // - On page load: If sessionStorage still has the session → it was a refresh → cancel cleanup
    // - On page load: Process any pending cleanups from OTHER closed tabs

    // Keep a ref to projectInstanceId so beforeunload always has the latest value
    const projectInstanceIdRef = useRef(projectInstanceId);
    useEffect(() => {
        projectInstanceIdRef.current = projectInstanceId;
    }, [projectInstanceId]);

    // DEFERRED SESSION CLEANUP: On mount, process any pending cleanups from closed tabs
    useEffect(() => {
        // Mark this tab's session as "alive" in sessionStorage (survives refresh, lost on tab close)
        const currentId = projectInstanceIdRef.current;
        if (currentId) {
            sessionStorage.setItem('project_session_alive', currentId);
        }

        // Helper to process pending cleanups for a given localStorage key
        const processPendingCleanups = (storageKey: string, aliveKey: string, clearEndpoints: string[]) => {
            try {
                const pendingRaw = localStorage.getItem(storageKey);
                if (!pendingRaw) return;

                const pendingCleanups: { sessionId: string; timestamp: number }[] = JSON.parse(pendingRaw);
                const aliveSessionId = sessionStorage.getItem(aliveKey);
                const remainingCleanups: typeof pendingCleanups = [];
                const now = Date.now();
                const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours - expire stale entries

                for (const cleanup of pendingCleanups) {
                    // Expire stale entries (older than 24h)
                    if (now - cleanup.timestamp > MAX_AGE_MS) {
                        console.log('[PROJECT] Expiring stale cleanup:', cleanup.sessionId);
                        continue;
                    }

                    if (cleanup.sessionId === aliveSessionId) {
                        // This session is still alive (page was refreshed, not closed) → cancel cleanup
                        console.log('[PROJECT] Refresh detected - cancelling cleanup for:', cleanup.sessionId);
                        continue;
                    }

                    // This session's tab was closed → perform cleanup
                    console.log('[PROJECT] Cleaning up closed tab session:', cleanup.sessionId);
                    try {
                        for (const endpoint of clearEndpoints) {
                            const payload = JSON.stringify({ session_id: cleanup.sessionId });
                            const fullUrl = endpoint.startsWith('http') ? endpoint : `${BASE_URL}${endpoint}`;
                            navigator.sendBeacon(
                                fullUrl,
                                new Blob([payload], { type: 'text/plain' })
                            );
                        }
                    } catch (e) {
                        // If cleanup fails, keep it for retry on next page load
                        console.warn('[PROJECT] Failed to clean up session, will retry:', cleanup.sessionId, e);
                        remainingCleanups.push(cleanup);
                    }
                }

                // Update localStorage: keep only failed cleanups for retry
                if (remainingCleanups.length > 0) {
                    localStorage.setItem(storageKey, JSON.stringify(remainingCleanups));
                } else {
                    localStorage.removeItem(storageKey);
                }
            } catch (e) {
                console.warn('[PROJECT] Error processing pending cleanups for', storageKey, e);
            }
        };

        // Process pending cleanups for Project sessions
        processPendingCleanups(
            'pending_session_cleanups',
            'project_session_alive',
            ['/api/clear-session-memory']
        );

        // Also process pending cleanups for Chat sessions (cross-page cleanup)
        // This handles the case where user closes Chat tab and only opens Project tab next
        processPendingCleanups(
            'pending_chat_session_cleanups',
            'chat_session_alive',
            ['/api/clear-session-memory', '/api/chat/clear-session']
        );

        // Also process pending cleanups for Search sessions (cross-page cleanup)
        // This handles the case where user closes Search tab and only opens Project tab next
        processPendingCleanups(
            'pending_search_session_cleanups',
            'search_session_alive',
            ['/api/clear-session-memory']
        );
    }, []);

    // Keep sessionStorage in sync when projectInstanceId changes
    useEffect(() => {
        if (projectInstanceId) {
            sessionStorage.setItem('project_session_alive', projectInstanceId);
        }
    }, [projectInstanceId]);

    // SAVE ON PAGE CLOSE/REFRESH: Capture scroll position and save state
    useEffect(() => {
        const handleBeforeUnload = (e: BeforeUnloadEvent) => {
            // Get current scroll positions - check both the element and window
            const elementScroll = projectScrollRef.current?.scrollTop || 0;
            const windowScroll = window.scrollY || document.documentElement.scrollTop || 0;
            const freshScroll = Math.max(elementScroll, windowScroll);
            // Use tracked ref value if fresh value is 0 (might have been reset during unload)
            const scrollPosition = freshScroll > 0 ? freshScroll : currentScrollPositionRef.current;

            // Get right panel scroll position
            const rightPanelFresh = rightPanelScrollRef.current?.scrollTop || 0;
            const rightPanelScroll = rightPanelFresh > 0 ? rightPanelFresh : rightPanelScrollPositionRef.current;

            console.log('[PROJECT] beforeunload - leftScroll:', scrollPosition, 'rightPanelScroll:', rightPanelScroll);

            const stateToSave = {
                ...stateRef.current,
                scrollPosition,
                rightPanelScroll,
                savedAt: new Date().toISOString()
            };

            // Use synchronous localStorage as fallback for immediate save
            // IndexedDB is async and might not complete before page closes
            try {
                localStorage.setItem(getProjectBackupKey(), JSON.stringify(stateToSave));
                console.log('[PROJECT] Saved state to localStorage backup on page close, scroll:', scrollPosition);
            } catch (e) {
                console.warn('[PROJECT] Failed to save backup state:', e);
            }

            // Also try to save to IndexedDB (might not complete)
            saveStateToIndexedDB(stateToSave);

            // Mark session as "pending cleanup" in localStorage
            // On next page load, if sessionStorage still has this session → refresh → cancel cleanup
            // If sessionStorage lost it → tab was closed → cleanup will execute
            const currentInstanceId = projectInstanceIdRef.current;
            if (currentInstanceId) {
                try {
                    const pendingRaw = localStorage.getItem('pending_session_cleanups');
                    const pending: { sessionId: string; timestamp: number }[] = pendingRaw ? JSON.parse(pendingRaw) : [];
                    // Avoid duplicate entries
                    if (!pending.some(p => p.sessionId === currentInstanceId)) {
                        pending.push({ sessionId: currentInstanceId, timestamp: Date.now() });
                    }
                    localStorage.setItem('pending_session_cleanups', JSON.stringify(pending));
                    console.log('[PROJECT] Marked session for pending cleanup:', currentInstanceId);
                } catch (e) {
                    console.warn('[PROJECT] Failed to mark pending cleanup:', e);
                }
            }

            // --- ACCIDENTAL CLOSE PREVENTION ---
            const hasActiveData = 
                (stateRef.current.chatMessages && stateRef.current.chatMessages.length > 0) || 
                (stateRef.current.projectName && stateRef.current.projectName !== 'Project') ||
                (stateRef.current.searchTabs && stateRef.current.searchTabs.length > 0);

            if (hasActiveData) {
                e.preventDefault();
                e.returnValue = 'Are you sure you want to close? Your active project data is saved in local backup, but you will leave this session.';
                return e.returnValue;
            }
        };

        window.addEventListener('beforeunload', handleBeforeUnload);

        return () => {
            window.removeEventListener('beforeunload', handleBeforeUnload);
        };
    }, []); // Empty dependency - only set up once

    // Save state on component unmount (e.g. React Router navigation)
    useEffect(() => {
        return () => {
            const scrollPosition = currentScrollPositionRef.current;
            const rightPanelScroll = rightPanelScrollPositionRef.current;

            // Only save if there is meaningful state to save
            if (!stateRef.current.chatMessages.length && !stateRef.current.instruments.length && !stateRef.current.accessories.length && stateRef.current.projectName === 'Project') {
                return;
            }

            const stateToSave = {
                ...stateRef.current,
                scrollPosition,
                rightPanelScroll,
                savedAt: new Date().toISOString()
            };

            // Synchronous localStorage backup
            try {
                localStorage.setItem(getProjectBackupKey(), JSON.stringify(stateToSave));
                console.log('[PROJECT] Saved state to localStorage backup on unmount');
            } catch (e) {
                console.warn('[PROJECT] Failed to save backup state on unmount:', e);
            }

            // Async IndexedDB save
            saveStateToIndexedDB(stateToSave).catch(e => console.warn('[PROJECT] Failed to save to IndexedDB on unmount:', e));
        };
    }, []);

    // LOAD FROM INDEXEDDB: Restore complete state on mount
    useEffect(() => {
        const loadState = async () => {
            try {
                // Check if opened via MainHeader navigation with fresh=true
                const urlParams = new URLSearchParams(window.location.search);
                const isFresh = urlParams.get('fresh') === 'true';
                // Check if this is a newly opened tab
                if (!sessionStorage.getItem('project_tab_initialized_flag')) {
                    if (!isFresh) {
                        sessionStorage.setItem('project_tab_initialized_flag', 'true');
                        console.log('[PROJECT] New tab detected - not restoring state');

                        // Show greeting for manual URL opens, but NOT when coming from login
                        if (sessionStorage.getItem('from_login')) {
                            sessionStorage.removeItem('from_login');
                            console.log('[PROJECT] Came from login - showing welcome screen');
                        } else {
                            const greetingText = SOLUTION_GREETINGS[Math.floor(Math.random() * SOLUTION_GREETINGS.length)];
                            setChatMessages([{
                                id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                                type: 'assistant',
                                content: greetingText,
                                timestamp: new Date()
                            }]);
                            console.log('[PROJECT] Added greeting message for new tab (manual URL open)');
                        }

                        setIsRestoringState(false);
                        return;
                    }
                }

                if (isFresh) {
                    console.log('[PROJECT] Fresh navigation detected - clearing all state');
                    await clearIndexedDBState();
                    localStorage.removeItem(getProjectBackupKey());
                    sessionStorage.setItem('project_tab_initialized_flag', 'true');
                    
                    // Clear session-scoped auto-save choice for fresh navigation
                    const sid = localStorage.getItem('user_session_id') || 'global';
                    localStorage.removeItem(`autosave_choice_${sid}`);
                    localStorage.removeItem(`autosave_skip_${sid}`);
                    setIsServerAutoSaveEnabled(false);

                    // Remove fresh param from URL to prevent re-clearing on refresh
                    urlParams.delete('fresh');
                    const newUrl = urlParams.toString()
                        ? `${window.location.pathname}?${urlParams.toString()}`
                        : window.location.pathname;
                    window.history.replaceState({}, '', newUrl);

                    // Show a random greeting message from the bot
                    const greetingText = SOLUTION_GREETINGS[Math.floor(Math.random() * SOLUTION_GREETINGS.length)];
                    setChatMessages([{
                        id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                        type: 'assistant',
                        content: greetingText,
                        timestamp: new Date()
                    }]);
                    console.log('[PROJECT] Added greeting message for fresh navigation');

                    setIsRestoringState(false);
                    return; // Don't restore anything
                }

                // First check if there's a localStorage backup (more reliable for scroll position on refresh)
                let backupData: any = null;
                try {
                    const backup = localStorage.getItem(getProjectBackupKey());
                    if (backup) {
                        backupData = JSON.parse(backup);
                        console.log('[PROJECT] Found localStorage backup - leftScroll:', backupData.scrollPosition, 'rightPanelScroll:', backupData.rightPanelScroll);
                        // Clear the backup after reading
                        localStorage.removeItem(getProjectBackupKey());
                    }
                } catch (e) {
                    console.warn('[PROJECT] Failed to read localStorage backup:', e);
                }

                // Load main state from IndexedDB
                const saved = await loadStateFromIndexedDB();

                // Use backup scroll positions if available (they're more recent)
                const scrollToRestore = backupData?.scrollPosition || saved?.scrollPosition || 0;
                const rightPanelScrollToRestore = backupData?.rightPanelScroll || saved?.rightPanelScroll || 0;

                if (saved) {
                    console.log('[PROJECT] Restoring complete state from IndexedDB');

                    // Restore all state - use batch updates where possible
                    if (saved.chatMessages?.length) setChatMessages(saved.chatMessages);
                    if (saved.instruments?.length) setInstruments(saved.instruments);
                    if (saved.accessories?.length) setAccessories(saved.accessories);
                    if (saved.designedSolution) setDesignedSolution(saved.designedSolution);
                    if (saved.showResults !== undefined) setShowResults(saved.showResults);

                    // Restore project name and its edit value
                    if (saved.projectName && saved.projectName !== 'Project') {
                        setProjectName(saved.projectName);
                        setEditProjectNameValue(saved.projectName);
                    }

                    if (saved.currentProjectId) {
                        setCurrentProjectId(saved.currentProjectId);
                        // Silently enable server auto-save for restored projects (no popup needed)
                        setIsServerAutoSaveEnabled(true);
                        const sid = localStorage.getItem('user_session_id') || 'global';
                        const choiceKey = `autosave_choice_${sid}`;
                        if (localStorage.getItem(choiceKey) === null) {
                            localStorage.setItem(choiceKey, 'true');
                        }
                        console.log('[AUTOSAVE] Silently enabled for IndexedDB-restored project:', saved.currentProjectId);
                    }
                    if (saved.isRightDocked !== undefined) setIsRightDocked(saved.isRightDocked);
                    if (saved.standardsEnabled !== undefined) setStandardsEnabled(saved.standardsEnabled);
                    if (saved.genericImages && Object.keys(saved.genericImages).length) setGenericImages(saved.genericImages);

                    // Restore tabStates BEFORE searchTabs to ensure state is available
                    if (saved.tabStates && Object.keys(saved.tabStates).length) {
                        setTabStates(saved.tabStates);
                    }

                    // Restore search tabs and active tab together
                    if (saved.searchTabs?.length) {
                        setSearchTabs(saved.searchTabs);
                    }
                    if (saved.previousTab) setPreviousTab(saved.previousTab);

                    // Restore active tab AFTER search tabs are set
                    // Restore active tab immediately
                    if (saved.activeTab) {
                        setActiveTab(saved.activeTab);
                        console.log('[PROJECT] Restored active tab:', saved.activeTab);
                    }

                    // Store scroll positions to restore after loading screen goes away
                    // Can't restore immediately because DOM isn't mounted while loading screen is shown
                    // Use scrollToRestore which prioritizes localStorage backup (more recent)
                    if (scrollToRestore > 0) {
                        setPendingScrollPosition(scrollToRestore);
                        console.log('[PROJECT] Saved pending left scroll position:', scrollToRestore);
                    }
                    if (rightPanelScrollToRestore > 0) {
                        setPendingRightPanelScroll(rightPanelScrollToRestore);
                        console.log('[PROJECT] Saved pending right panel scroll position:', rightPanelScrollToRestore);
                    }

                    // Mark messages as history so they don't animate
                    isHistoryRef.current = true;
                    setTimeout(() => {
                        isHistoryRef.current = false;
                    }, 1000);

                    console.log('[PROJECT] State restored from IndexedDB:', {
                        chatMessages: saved.chatMessages?.length || 0,
                        instruments: saved.instruments?.length || 0,
                        accessories: saved.accessories?.length || 0,
                        searchTabs: saved.searchTabs?.length || 0,
                        activeTab: saved.activeTab,
                        showResults: saved.showResults,
                        scrollPosition: saved.scrollPosition || 0,
                        tabStatesKeys: Object.keys(saved.tabStates || {}).length,
                        genericImages: Object.keys(saved.genericImages || {}).length
                    });
                } else {
                    console.log('[PROJECT] No saved state found in IndexedDB');
                    // Show greeting message when no state is found
                    // This handles the case when returning from catalog with no prior messages
                    const greetingText = SOLUTION_GREETINGS[Math.floor(Math.random() * SOLUTION_GREETINGS.length)];
                    setChatMessages([{
                        id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                        type: 'assistant',
                        content: greetingText,
                        timestamp: new Date()
                    }]);
                    console.log('[PROJECT] Added greeting message - no saved state found');
                }
            } catch (e) {
                console.warn('[PROJECT] Error restoring state from IndexedDB:', e);
                // On error, also show greeting
                const greetingText = SOLUTION_GREETINGS[Math.floor(Math.random() * SOLUTION_GREETINGS.length)];
                setChatMessages([{
                    id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                    type: 'assistant',
                    content: greetingText,
                    timestamp: new Date()
                }]);
                console.log('[PROJECT] Added greeting message after error');
            } finally {
                setIsRestoringState(false);
            }
        };

        loadState();
    }, []);

    // RESTORE SCROLL POSITION: After loading screen is gone and DOM is ready
    useEffect(() => {
        if (!isRestoringState && pendingScrollPosition !== null && pendingScrollPosition > 0) {
            // Use requestAnimationFrame for instant restore
            requestAnimationFrame(() => {
                let scrollApplied = false;

                // Try element scroll first
                if (projectScrollRef.current) {
                    projectScrollRef.current.scrollTop = pendingScrollPosition;
                    scrollApplied = projectScrollRef.current.scrollTop > 0;
                    console.log('[PROJECT] Applied left scroll:', pendingScrollPosition);
                }

                // If element scroll didn't work, try window scroll
                if (!scrollApplied) {
                    window.scrollTo(0, pendingScrollPosition);
                }

                // Clear the pending position
                setPendingScrollPosition(null);
            });
        }
    }, [isRestoringState, pendingScrollPosition]);

    // RESTORE RIGHT PANEL SCROLL POSITION: After right panel is mounted
    useEffect(() => {
        if (!isRestoringState && pendingRightPanelScroll !== null && pendingRightPanelScroll > 0 && showResults) {
            // Use requestAnimationFrame for instant restore
            requestAnimationFrame(() => {
                if (rightPanelScrollRef.current) {
                    rightPanelScrollRef.current.scrollTop = pendingRightPanelScroll;
                    console.log('[PROJECT] Applied right panel scroll:', pendingRightPanelScroll);
                }
                // Clear the pending position
                setPendingRightPanelScroll(null);
            });
        }
    }, [isRestoringState, pendingRightPanelScroll, showResults]);

    // SESSION-SCOPED AUTO-SAVE POPUP: Show once per login session if user hasn't chosen yet.
    // Fires when userSessionId becomes available (may be async from AuthContext).
    useEffect(() => {
        if (!userSessionId) return; // Wait until session is resolved
        if (isRestoringState) return;

        const urlParams = new URLSearchParams(window.location.search);
        const projectId = urlParams.get('projectId');

        // --- Case 1: An existing project is loaded (navigate away/back, page refresh, ?projectId URL)
        // → No popup, silently enable auto-save in the background
        if (currentProjectId || projectId) {
            setShowGoogleSavePopup(false);
            setIsServerAutoSaveEnabled(true);
            // Persist the silent choice so the setting survives within this session
            const choiceKey = `autosave_choice_${userSessionId}`;
            if (localStorage.getItem(choiceKey) === null) {
                localStorage.setItem(choiceKey, 'true');
            }
            console.log('[AUTOSAVE] Silently enabled for existing project:', currentProjectId || projectId);
            return;
        }

        // --- Case 2: Fresh / new project — check if user has already made a choice this session
        const choiceKey = `autosave_choice_${userSessionId}`;
        const skipKey = `autosave_skip_${userSessionId}`;

        const hasChoice = localStorage.getItem(choiceKey) !== null;
        const skipped = localStorage.getItem(skipKey) === 'true';

        if (!hasChoice && !skipped) {
            // No prior choice this session → show the popup
            setShowGoogleSavePopup(true);
        } else {
            setShowGoogleSavePopup(false);
            // Sync isServerAutoSaveEnabled from the stored session choice
            if (hasChoice) {
                setIsServerAutoSaveEnabled(localStorage.getItem(choiceKey) === 'true');
            }
        }
    }, [userSessionId, isRestoringState, currentProjectId]);

    // Helper to add a message to chat
    const addChatMessage = (type: 'user' | 'assistant', content: string, metadata?: { routerRedirect?: boolean; routerUrl?: string; routerTargetPage?: string; }) => {
        const newMessage: ProjectChatMessage = {
            id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
            type,
            content,
            timestamp: new Date(),
            metadata
        };
        setChatMessages(prev => [...prev, newMessage]);
    };

    // Helper to parse specification values (handles both string and structured formats)
    const parseSpecValue = (value: any): { displayValue: string; source: string | null; confidence: number | null } => {
        // Handle structured Deep Agent format: { value: "...", source: "...", confidence: 0.9 }
        if (value && typeof value === 'object' && !Array.isArray(value) && 'value' in value) {
            return {
                displayValue: value.value || 'Not specified',
                source: value.source || null,
                confidence: value.confidence || null
            };
        }
        // Handle plain string values with embedded [STANDARD] / [INFERRED] tags
        // e.g. "IP66/IP67 [STANDARD]" → displayValue: "IP66/IP67", source: "standard"
        const strValue = String(value ?? '');
        if (strValue.includes('[STANDARD]')) {
            return {
                displayValue: strValue.replace('[STANDARD]', '').trim(),
                source: 'standard',
                confidence: null
            };
        }
        if (strValue.includes('[INFERRED]')) {
            return {
                displayValue: strValue.replace('[INFERRED]', '').trim(),
                source: 'inferred',
                confidence: null
            };
        }
        // No tag → user-specified value, show as-is with no badge
        return {
            displayValue: strValue || 'Not specified',
            source: null,
            confidence: null
        };
    };

    // Helper to get source label for display - now returns bracket format
    const getSourceLabel = (source: string | null): string | null => {
        if (!source) return null;
        if (source.toLowerCase().includes('standard')) return '[Standard]';
        if (source.toLowerCase().includes('infer')) return '[Inferred]';
        if (source.toLowerCase().includes('rag')) return '[Knowledge Base]';
        if (source.toLowerCase().includes('user')) return '[User Input]';
        return source ? `[${source}]` : null;
    };

    const capitalizeFirstLetter = (str?: string): string => {
        if (!str) return "";
        return str.charAt(0).toUpperCase() + str.slice(1);
    };

    // Helper to convert relative image URLs to absolute URLs
    const getAbsoluteImageUrl = (url: string | undefined | null): string | undefined => {
        if (!url) return undefined;

        // Already absolute URL
        if (url.startsWith('http') || url.startsWith('data:')) {
            return url;
        }

        // Convert relative URL to absolute
        const baseUrl = BASE_URL.endsWith('/') ? BASE_URL.slice(0, -1) : BASE_URL;
        const path = url.startsWith('/') ? url : `/${url}`;
        return `${baseUrl}${path}`;
    };

    // Helper to format keys into human-readable text
    const prettifyKey = (key: string) => {
        if (!key) return "";
        return key
            .replace(/([A-Z])/g, ' $1')
            .replace(/_/g, ' ')
            .trim()
            .split(/\s+/)
            .map(part => part.charAt(0).toUpperCase() + part.slice(1))
            .join(' ');
    };

    const getApplicableStandardsEntries = (item: {
        applicableStandards?: string[];
        applicableStandardsTitles?: Record<string, string | null>;
        standardsSpecs?: Record<string, string>;
        specifications?: Record<string, string>;
    }) => {
        const uniqueStandards = Array.from(
            new Set(
                (item.applicableStandards || [])
                    .map(standard => String(standard ?? '').trim())
                    .filter(Boolean)
            )
        );

        return uniqueStandards.map((standardCode) => {
            const rawTitle = item.applicableStandardsTitles?.[standardCode];
            const standardTitle = typeof rawTitle === 'string' ? rawTitle.trim() : '';

            return {
                key: standardCode,
                value: standardTitle && standardTitle.toLowerCase() !== standardCode.toLowerCase()
                    ? standardTitle
                    : 'Applicable'
            };
        });
    };

    const renderApplicableStandardRows = (item: {
        applicableStandards?: string[];
        applicableStandardsTitles?: Record<string, string | null>;
        standardsSpecs?: Record<string, string>;
        specifications?: Record<string, string>;
    }) => {
        return getApplicableStandardsEntries(item).map(({ key, value }) => (
            <div key={`standard-${key}`} className="text-sm group break-words">
                <span className="font-medium">{key}:</span>{' '}
                <span className="text-muted-foreground">{value}</span>
                <span className="ml-1 text-xs text-primary font-medium">
                    [Standard]
                </span>
            </div>
        ));
    };

    /**
     * Format sample input by prettifying field names (removing underscores, etc.)
     * Input: "range: 0-100 bar, Body_Material: 316SS [STANDARD]"
     * Output: "Range: 0-100 bar, Body Material: 316SS [STANDARD]"
     */
    const formatSampleInput = (sampleInput: string) => {
        if (!sampleInput) return "";

        // Split by comma to get individual spec pairs
        const parts = sampleInput.split(',').map(part => part.trim());

        return parts.map(part => {
            // Find the colon that separates key from value
            const colonIndex = part.indexOf(':');
            if (colonIndex === -1) return part;

            const key = part.substring(0, colonIndex).trim();
            const value = part.substring(colonIndex + 1).trim();

            // Prettify the key and recombine
            return `${prettifyKey(key)}: ${value}`;
        }).join(', ');
    };

    /**
     * Extract the base product type from a product name.
     * Handles common naming patterns like:
     * - "X with Y" (e.g., "Temperature Transmitter with RTD Sensor" → "Temperature Transmitter")
     * - "X for Y" (e.g., "Connection Head for Temperature Transmitter" → "Connection Head")
     * - "X including Y", "X featuring Y"
     */
    const extractBaseProductType = (productName: string): string => {
        if (!productName) return productName;
        if (productName.includes(' for ')) return productName.split(' for ')[0].trim();
        if (productName.includes(' with ')) return productName.split(' with ')[0].trim();
        if (productName.includes(' including ')) return productName.split(' including ')[0].trim();
        if (productName.includes(' featuring ')) return productName.split(' featuring ')[0].trim();
        return productName;
    };

    /**
     * Extract the proper image key from an accessory.
     * For accessories named "X for Y", use "X" as the image key.
     */
    const getAccessoryImageKey = (accessory: any): string => {
        const category = accessory.category || '';
        if (category && category.toLowerCase() !== 'accessories' && category.toLowerCase() !== 'accessory' && category.toLowerCase() !== 'unknown accessory') {
            return category;
        }
        return extractBaseProductType(accessory.accessoryName || '');
    };

    /**
     * Extract the proper image key from an instrument.
     * Use the category field since generic images are mapped to category names.
     */
    const getInstrumentImageKey = (instrument: any): string => {
        const category = instrument.category || '';
        if (category) return category;
        return extractBaseProductType(instrument.productName || '');
    };

    // Batched loading: Load images sequentially in small batches
    // Collects ALL images first, then displays them all at once
    // IMPORTANT: Merges with existing images to preserve previously loaded ones
    // Includes retry logic for failed images (rate limit, timeout, etc.)
    const fetchGenericImagesLazy = async (productTypes: string[]) => {
        const uniqueTypes = [...new Set(productTypes)]; // Remove duplicates

        // Filter out images that are already loaded to prevent duplicate fetches
        const typesToFetch = uniqueTypes.filter(type => !findGenericImageUrl(type));

        if (typesToFetch.length === 0) {
            console.log('[IMAGE_PARALLEL] All images already loaded, skipping fetch');
            return;
        }

        // Parallel configuration - fetch all images at once (MongoDB reads are fast, no rate limits)
        console.log(`[IMAGE_PARALLEL] Starting parallel load for ${typesToFetch.length} images (skipped ${uniqueTypes.length - typesToFetch.length} already loaded)...`);

        // Collect all loaded images here - don't update state until ALL are loaded
        const allLoadedImages: Record<string, string> = {};
        let failedTypes: string[] = [];

        // Helper: fetch a single image
        const fetchSingleImage = async (productType: string, index: number, total: number): Promise<{ success: boolean; productType: string }> => {
            try {
                const encodedType = encodeURIComponent(productType);
                console.log(`[IMAGE_PARALLEL] [${index + 1}/${total}] Fetching: ${productType}`);

                const response = await axios.get(`/api/generic_image/${encodedType}`);

                if (response.status === 200) {
                    const data = response.data;
                    if (data.success && data.image) {
                        let absoluteUrl = getAbsoluteImageUrl(data.image.url);
                        if (absoluteUrl) {
                            if (productType.toLowerCase().includes('positioner')) {
                                // Add cache buster parameter to bypass browser caching of the old incorrect image
                                absoluteUrl += (absoluteUrl.includes('?') ? '&' : '?') + 'v=1.1';
                            }
                            allLoadedImages[productType] = absoluteUrl;
                            console.log(`[IMAGE_PARALLEL] ✓ Loaded [${index + 1}/${total}]: ${productType}`);
                            return { success: true, productType };
                        }
                    }
                } else {
                    console.warn(`[IMAGE_PARALLEL] ✗ Failed (${response.status}): ${productType}`);
                }
            } catch (error) {
                console.error(`[IMAGE_PARALLEL] ✗ Error fetching ${productType}:`, error);
            }
            return { success: false, productType };
        };

        // Fetch ALL images in parallel (no batching, no retries)
        console.log(`[IMAGE_PARALLEL] Fetching all ${typesToFetch.length} images in parallel (1 attempt only)...`);

        const allPromises = typesToFetch.map((productType, index) =>
            fetchSingleImage(productType, index, typesToFetch.length)
        );

        const allResults = await Promise.all(allPromises);
        const successCount = allResults.filter(r => r.success).length;
        failedTypes = allResults.filter(r => !r.success).map(r => r.productType);

        console.log(`[IMAGE_PARALLEL] Fetch complete: ${successCount}/${typesToFetch.length} succeeded`);

        if (failedTypes.length > 0) {
            console.warn(`[IMAGE_PARALLEL] Could not load images for: ${failedTypes.join(', ')}`);
        }

        // ALL fetches + retries complete - now MERGE with existing images (don't replace!)
        const newCount = Object.keys(allLoadedImages).length;
        console.log(`[IMAGE_PARALLEL] All complete! Loaded ${newCount} images, merging with existing...`);
        if (newCount > 0) {
            setGenericImages(prevImages => ({
                ...prevImages,  // Keep all previously loaded images
                ...allLoadedImages  // Add/update with new images
            }));
        }
    };

    // Auto-sync generic images when instruments or accessories lists are updated/loaded/restored
    useEffect(() => {
        if ((!instruments || instruments.length === 0) && (!accessories || accessories.length === 0)) return;

        const productNames: string[] = [];
        (instruments || []).forEach((inst: any) => {
            const imageKey = getInstrumentImageKey(inst);
            if (imageKey) productNames.push(imageKey);
        });
        (accessories || []).forEach((acc: any) => {
            const imageKey = getAccessoryImageKey(acc);
            if (imageKey) productNames.push(imageKey);
        });

        const uniqueNames = [...new Set(productNames)];
        // Filter out types that are already loaded in genericImages
        const missingTypes = uniqueNames.filter(type => !findGenericImageUrl(type));

        if (missingTypes.length > 0) {
            console.log(`[IMAGE_AUTO_SYNC] Found ${missingTypes.length} missing generic images in frontend view, loading:`, missingTypes);
            fetchGenericImagesLazy(missingTypes);
        }
    }, [instruments, accessories]);

    // Escape string for use in RegExp
    const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    // Compute next available duplicate name: e.g., if 'Name' exists, suggest 'Name (1)';
    // if 'Name (1)' exists, suggest 'Name (2)', etc.
    const computeNextDuplicateName = (base: string, projects: any[]) => {
        if (!base) return `${base} (1)`;
        const baseTrim = base.trim();

        // Extract the actual base name without any numbering
        // If base is "Distillation Column (1)", extract "Distillation Column"
        const baseNameMatch = baseTrim.match(/^(.*?)(?:\s*\(\d+\))?$/);
        const actualBaseName = baseNameMatch ? baseNameMatch[1].trim() : baseTrim;

        // Create regex to match all variations of the base name with numbers
        const regex = new RegExp(`^${escapeRegExp(actualBaseName)}(?:\\s*\\((\\d+)\\))?$`, 'i');
        let maxNum = 0;
        let foundBase = false;

        for (const p of projects) {
            const pName = (p.projectName || p.project_name || '').trim();
            if (!pName) continue;
            const m = pName.match(regex);
            if (m) {
                if (!m[1]) {
                    foundBase = true;
                } else {
                    const n = parseInt(m[1], 10);
                    if (!isNaN(n) && n > maxNum) maxNum = n;
                }
            }
        }

        if (maxNum > 0) {
            return `${actualBaseName} (${maxNum + 1})`;
        }

        if (foundBase) return `${actualBaseName} (1)`;

        // fallback
        return `${actualBaseName} (1)`;
    };

    useEffect(() => {
        setEditProjectNameValue(projectName);
    }, [projectName]);

    const profileButtonLabel = capitalizeFirstLetter(user?.name || user?.username || "User");
    const profileFullName = user?.name || `${user?.firstName || ''} ${user?.lastName || ''}`.trim() || user?.username || "User";

    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Enforce textarea height when requirements change programmatically (e.g., from URL or BroadcastChannel)
    useEffect(() => {
        if (textareaRef.current) {
            const textarea = textareaRef.current;
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`;
        }
    }, [requirements]);

    const handleSubmit = async (e?: React.FormEvent, overrideRequirements?: string) => {
        if (e) e.preventDefault();

        const effectiveRequirements = (overrideRequirements ?? requirements).trim();
        const effectiveExtractedText = overrideRequirements != null ? '' : extractedText.trim();

        // Check if we have either text requirements or extracted text from file
        if (!effectiveRequirements && !effectiveExtractedText) {
            toast({
                title: "Input Required",
                description: "Please enter your requirements or attach a file",
                variant: "destructive",
            });
            return;
        }

        // Combine manual requirements with extracted text from file
        const finalRequirements = effectiveRequirements && effectiveExtractedText
            ? `${effectiveRequirements}\n\n${effectiveExtractedText}`
            : effectiveRequirements || effectiveExtractedText;

        // Create display message for chat (show file name instead of extracted text)
        const attachedFilesLabel = attachedFiles.length === 1
            ? attachedFiles[0].name
            : `${attachedFiles.length} files`;
        const displayMessage = overrideRequirements != null
            ? effectiveRequirements
            : attachedFiles.length > 0
                ? requirements.trim()
                    ? `${requirements.trim()}\n\n📎 ${attachedFilesLabel}`
                    : `📎 ${attachedFilesLabel}`
                : requirements.trim();

        // Add user message to chat (show file name, not extracted text)
        addChatMessage('user', displayMessage);

        // Only clear the input/file when this submission came from the local textbox
        if (overrideRequirements == null) {
            // Reset textarea height to initial height before clearing
            if (textareaRef.current) {
                textareaRef.current.style.height = 'auto';
            }

            setRequirements('');
            setAttachedFiles([]);
            setExtractedText('');
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        }

        setIsLoading(true);

        // Remember the submitted requirements; the server project is created lazily
        // once the agent returns results (see success path), NOT here — so a submit
        // intercepted as a repeat, or yielding no results, never creates an empty project.
        lastSubmittedRequirementsRef.current = finalRequirements;

        // Generate stream ID immediately so UI can connect to SSE
        const newStreamId = `stream-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
        setStreamId(newStreamId);

        try {
            // =====================================================
            // NEW FLOW: Always call solution agent directly
            // Solution agent handles intent classification internally and calls router if needed
            // =====================================================
            console.log('[API] Calling solution agent directly...');
            let intentResult = await callSolutionAgent(
                finalRequirements,
                instruments.length > 0 ? instruments : undefined,
                accessories.length > 0 ? accessories : undefined,
                false, // awaitingSingleItemConfirmation - deprecated
                projectInstanceId, // Pass session ID for isolation
                userSessionId, // Pass user session ID
                newStreamId, // Pass stream ID for SSE progress tracking
                !standardsEnabled // skip_standards = true when toggle is OFF
            );

            console.log('[API] Solution agent result:', intentResult);
            // Defensively unpack if it is nested
            const unpackedResult = (intentResult as any).result?.intent ? (intentResult as any).result : intentResult;
            const intent = unpackedResult.intent;
            const reasoning = unpackedResult.reasoning;
            // Overwrite the original intentResult with the unpacked version for the rest of the function
            intentResult = unpackedResult;

            if (intent === 'cache_confirmation') {
                console.log('[API] Cache confirmation required, opening dialog:', intentResult);
                console.log('[EPISODIC_RECALL] Repeated request detected — matched saved project(s):',
                    (intentResult.matchedProjects || []).map((p: any) => ({
                        name: p.projectName || p.project_name,
                        similarity: p.similarity,
                        instruments: p.instrumentsCount ?? p.instruments_count,
                        accessories: p.accessoriesCount ?? p.accessories_count,
                        id: p.projectId || p.project_id,
                    }))
                );

                const firstProjId = intentResult.matchedProjects?.[0]?.projectId || intentResult.matchedProjects?.[0]?.project_id || '';
                
                // Add the Repeated request message to the chat with cacheConfirmation metadata
                addChatMessage(
                    'assistant', 
                    intentResult.message || "I've seen this one before! You worked on a similar project recently. Want me to pull up that solution, or shall I build a fresh one from scratch?",
                    {
                        cacheConfirmation: true,
                        matchedProjects: intentResult.matchedProjects,
                        projectId: firstProjId
                    }
                );
                
                setCacheConfirmationData(intentResult);
                setSelectedCacheProjectId(firstProjId);
                setCacheConfirmationOpen(true);
                setIsLoading(false);
                
                // Automatically fetch preview details for the first matched project
                if (firstProjId) {
                    handleCachePreview(firstProjId);
                }
                return;
            }

            // =====================================================
            // HANDLE ERROR RESPONSE (e.g. Timeout from backend)
            // =====================================================
            if (intentResult.success === false || intent === 'error') {
                console.error('[API] Solution agent returned an error:', intentResult.message);
                
                addChatMessage('assistant', intentResult.message || "I'm having trouble processing your request.");
                
                toast({
                    title: "Request Failed",
                    description: intentResult.message || "The request took too long or failed.",
                    variant: "destructive",
                });
                
                setIsLoading(false);
                return;
            }

            // =====================================================
            // HANDLE ROUTER REDIRECT (when input not relevant to solution page)
            // =====================================================
            if (intentResult.responseType === 'router_redirect' || intent === 'router_needed') {
                console.log(`[ROUTE] Solution agent determined routing needed to: ${intentResult.routerTargetPage}`);

                // Determine if we need to redirect
                const routerTarget = intentResult.routerTargetPage?.toLowerCase() || '';
                const targetName = intentResult.routerTargetPage?.charAt(0).toUpperCase() + intentResult.routerTargetPage?.slice(1) || 'Other';

                // Only show button/redirect if target is NOT current page (solution)
                // If router returns 'solution', it means it's just chitchat/out-of-scope handled on current page
                const isSamePage = routerTarget === 'solution';

                const messageToDisplay = intentResult.message || intentResult.routerMessage || (isSamePage ? "I'm not sure how to help with that request here." : `This would be better handled on the ${targetName} page.`);

                // Determine target URL - store query in localStorage (shared across tabs)
                let targetUrl = '';
                if (!isSamePage) {
                    const isChat = routerTarget === 'chat';
                    const queryKey = `route_query_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                    localStorage.setItem(queryKey, finalRequirements);
                    targetUrl = isChat
                        ? `/chat?queryKey=${queryKey}&fresh=true`
                        : `/search?queryKey=${queryKey}&fresh=true`;
                }

                // Pass metadata to render the button properly via MessageRow
                addChatMessage('assistant', messageToDisplay, {
                    routerRedirect: !isSamePage && (intentResult.routerRequiresRouting || true),
                    routerUrl: targetUrl,
                    routerTargetPage: targetName
                });

                setIsLoading(false);
                return;
            }

            // =====================================================
            // HANDLE CLARIFICATION RESPONSE
            // =====================================================
            if (intent === 'clarification' && intentResult.clarificationNeeded) {
                console.log('[CLARIFICATION] Input too vague - asking for details');

                // Add the contextual clarification message from backend
                addChatMessage('assistant', intentResult.message);

                setIsLoading(false);
                return;
            }

            // =====================================================
            // HANDLE RESET CONFIRMATION REQUEST
            // =====================================================
            if (intent === 'reset') {
                console.log('[RESET] LLM detected reset intent - asking for confirmation');

                // Show the confirmation message from backend
                addChatMessage('assistant', intentResult.message);

                setIsLoading(false);
                return;
            }

            // =====================================================
            // HANDLE RESET CONFIRMED - Clear everything
            // =====================================================
            if (intent === 'reset_confirmed') {
                console.log('[RESET] User confirmed reset - clearing everything');

                // Backend already cleared conversation memory
                // Clear frontend state
                setInstruments([]);
                setAccessories([]);
                setShowResults(false);
                setChatMessages([]); // Clear chat history
                setSearchTabs([]);
                setProjectName('Project');
                setTabStates({});
                setGenericImages({});

                // Generate new instance ID for fresh start
                const newInstanceId = generateNewInstanceId();
                setProjectInstanceId(newInstanceId);
                console.log('[RESET] Generated new instance ID:', newInstanceId);

                // Reset first input flag so next input calls router
                setIsFirstInputProcessed(false);

                // Add reset completion message from backend
                addChatMessage('assistant', intentResult.message);

                toast({
                    title: "Fresh Start",
                    description: "All data cleared. Ready for a new project!",
                });

                setIsLoading(false);
                return;
            }

            // =====================================================
            // HANDLE RESET CANCELLED
            // =====================================================
            if (intent === 'reset_cancelled') {
                console.log('[RESET] User cancelled reset - keeping data');

                // Show the cancellation message from backend
                addChatMessage('assistant', intentResult.message);

                setIsLoading(false);
                return;
            }





            // =====================================================
            // Router classifier handles Search page routing
            // Solution agent only handles: requirements, modification, clarification, reset
            // =====================================================

            // =====================================================
            // STEP 2: Process solution agent response
            // =====================================================
            // The solution agent already returned complete data with instruments and accessories
            // No need for additional API calls!

            console.log('[API] Processing solution agent response. Intent:', intent);

            if (intentResult.fromSavedProject && intentResult.projectId) {
                console.log('[EPISODIC_RECALL] Response is from saved project, loading details for:', intentResult.projectId);
                addChatMessage('assistant', intentResult.message);
                await handleOpenProject(intentResult.projectId);
                setIsLoading(false);
                return;
            }

            // Add message from backend
            addChatMessage('assistant', intentResult.message);
            setLastIntentResult(intentResult);
            setInstruments(intentResult.instruments || []);
            setAccessories(intentResult.accessories || []);
            setSelectedInstruments(new Set());
            setSelectedAccessories(new Set());
            // Optimized engineering solution from the parallel solution-build agent (may be absent).
            // A modification turn updates the stored P&ID without rebuilding the designed
            // solution, so its drawing arrives only at the top level: keep the current
            // design and swap in the updated drawing rather than dropping the card.
            const nextDesign = (intentResult as any).designedSolution || null;
            const nextPid = (intentResult as any).pidGraph || null;
            setDesignedSolution(prev => {
                if (nextDesign) {
                    return nextDesign.pidGraph || !nextPid ? nextDesign : { ...nextDesign, pidGraph: nextPid };
                }
                return nextPid ? ({ ...(prev || {}), pidGraph: nextPid } as DesignedSolution) : null;
            });
            setShowResults(true);

            const totalItems = (intentResult.instruments?.length || 0) + (intentResult.accessories?.length || 0);
            if (totalItems >= 2) {
                setIsRightDocked(false);
            }

            if (intentResult.projectName) {
                setProjectName(intentResult.projectName);
            }

            // Now that the agent returned real results, create the server project if one
            // doesn't exist yet (deferred from submit time to avoid empty projects).
            if (!currentProjectId && isServerAutoSaveEnabled && finalRequirements.trim()) {
                initializeProjectInBackground(finalRequirements);
            }

            const productNames: string[] = [];
            (intentResult.instruments || []).forEach((inst: any) => {
                // Use the SAME key extraction as the display (getInstrumentImageKey)
                // so the fetched images map to the correct lookup keys
                const imageKey = getInstrumentImageKey(inst);
                if (imageKey) productNames.push(imageKey);
            });
            (intentResult.accessories || []).forEach((acc: any) => {
                const imageKey = getAccessoryImageKey(acc);
                if (imageKey) productNames.push(imageKey);
            });
            if (productNames.length > 0) {
                fetchGenericImagesLazy(productNames);
            }

            // Show appropriate toast based on intent type
            if (intent === 'modification') {
                toast({
                    title: "List Updated",
                    description: `Applied ${intentResult.changesMade?.length || 0} change(s). You now have ${intentResult.instruments?.length || 0} instruments and ${intentResult.accessories?.length || 0} accessories.`,
                });
            } else if (totalItems > 0) {
                toast({
                    title: "Success",
                    description: `Identified ${intentResult.instruments?.length || 0} instruments and ${intentResult.accessories?.length || 0} accessories`,
                });
            } else {
                // intentResult was technical success but found 0 items
                toast({
                    title: "No Items Found",
                    description: "The AI didn't identify any specific instruments from your input. Try providing more technical details.",
                    variant: "default",
                });
            }

        } catch (error: any) {
            addChatMessage('assistant', `I couldn't process your request. ${error.message || 'Please try again.'}`);

            toast({
                title: "Error",
                description: error.message || "Failed to process request",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        handleSubmitRef.current = (overrideRequirements?: string) => {
            handleSubmit(undefined, overrideRequirements);
        };
    }, [handleSubmit]);

    const handleKeyPress = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    };

    useEffect(() => {
        window.name = 'eng_solution';
    }, []);

    useEffect(() => {
        const channel = new BroadcastChannel('eng-route-handoff');

        const onMessage = (event: MessageEvent) => {
            const data: any = event.data;
            if (!data || typeof data !== 'object') return;
            if (data.type !== 'solution_run_query') return;

            channel.postMessage({
                type: 'solution_ack',
                requestId: data.requestId
            });

            // Focus this window to bring it to front
            window.focus();

            const incomingQuery = String(data.query || '').trim();
            if (!incomingQuery) return;

            // Set requirements but don't auto-submit so the user can manually run it
            setTimeout(() => {
                setRequirements(incomingQuery);
            }, 0);
        };

        channel.addEventListener('message', onMessage);
        return () => {
            channel.removeEventListener('message', onMessage);
            channel.close();
        };
    }, []);

    useEffect(() => {
        if (hasAutoSubmitted) return;
        const queryKey = searchParams.get('queryKey');
        if (!queryKey) return;

        const storedQuery = localStorage.getItem(queryKey);
        if (!storedQuery) {
            setHasAutoSubmitted(true);
            return;
        }

        localStorage.removeItem(queryKey);
        setHasAutoSubmitted(true);

        // Set requirements but don't auto-submit so the user can manually run it
        setTimeout(() => {
            setRequirements(storedQuery);
        }, 0);
    }, [searchParams, hasAutoSubmitted]);

    // Handle file selection and immediately extract text
    const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const selectedFiles = Array.from(event.target.files || []);
        if (!selectedFiles.length) return;

        // Attach files and start extraction immediately (single-file processing in parallel)
        setAttachedFiles(selectedFiles);
        setIsExtracting(true);

        try {
            const formData = new FormData();
            selectedFiles.forEach((file) => formData.append('file', file));

            const response = await axios.post('/api/upload-requirements', formData);
            let data: any = response.data;

            if (response.status !== 200 || !data?.success || !data?.extracted_text) {
                throw new Error(data?.error || 'Failed to extract text from file(s)');
            }

            // Backend returns a single combined extraction across all files
            setExtractedText(String(data.extracted_text));

            toast({
                title: "Files Extracted",
                description: `${selectedFiles.length} file(s) combined and extracted successfully.`,
            });
        } catch (error: any) {
            toast({
                title: "Extraction Failed",
                description: error.message || "Failed to extract text from file",
                variant: "destructive",
            });
            // Clear files if extraction failed
            setAttachedFiles([]);
            setExtractedText('');
        } finally {
            setIsExtracting(false);
            // Reset file input so the same file can be selected again if needed
            if (fileInputRef.current) {
                fileInputRef.current.value = '';
            }
        }
    };

    // Handle removing attached file and its extracted text
    const handleRemoveFile = () => {
        setAttachedFiles([]);
        setExtractedText('');
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    const addSearchTab = (input: string, categoryName?: string, vendorSearchParams?: VendorSearchParams, tabType?: 'instrument' | 'accessory') => {
        // Save current scroll position before switching tabs
        if (activeTab === 'project' && projectScrollRef.current) {
            setSavedScrollPosition(projectScrollRef.current.scrollTop);
        }

        const title = categoryName || `Search ${searchTabs.length + 1}`;
        const existingTabIndex = searchTabs.findIndex(tab => tab.title === title);

        if (existingTabIndex !== -1) {
            const updatedTabs = [...searchTabs];
            updatedTabs[existingTabIndex] = { ...updatedTabs[existingTabIndex], input, vendorSearchParams, tabType };
            setSearchTabs(updatedTabs);

            setTimeout(() => {
                setPreviousTab(activeTab);
                setActiveTab(updatedTabs[existingTabIndex].id);
                // Navigate to search URL
                if (location.pathname !== '/solution/search') {
                    navigate('/solution/search', { replace: true });
                }
            }, 0);

            return;
        }

        const nextIndex = searchTabs.length + 1;
        const id = `search-${Date.now()}-${nextIndex}`;
        const newTabs = [...searchTabs, { id, title, input, vendorSearchParams, tabType }];
        setSearchTabs(newTabs);

        setTimeout(() => {
            setPreviousTab(activeTab);
            setActiveTab(id);
            // Navigate to search URL
            if (location.pathname !== '/solution/search') {
                navigate('/solution/search', { replace: true });
            }
        }, 0);
    };

    const closeSearchTab = (id: string) => {
        const remaining = searchTabs.filter(t => t.id !== id);
        setSearchTabs(remaining);
        if (activeTab === id) {
            const targetTab = remaining.find(t => t.id === previousTab)
                ? previousTab
                : remaining.length > 0
                    ? remaining[remaining.length - 1].id
                    : 'project';

            // If returning to project tab, restore scroll position
            setPreviousTab(activeTab);
            setActiveTab(targetTab);

            // Navigate based on target tab
            if (targetTab === 'project') {
                if (location.pathname !== '/solution') {
                    navigate('/solution', { replace: true });
                }
            } else {
                if (location.pathname !== '/solution/search') {
                    navigate('/solution/search', { replace: true });
                }
            }
        }
    };

    const toggleInstrumentCollapse = (index: number) => {
        setCollapsedInstruments(prev => {
            const newSet = new Set(prev);
            if (newSet.has(index)) {
                newSet.delete(index);
            } else {
                newSet.add(index);
            }
            return newSet;
        });
    };

    const toggleAccessoryCollapse = (index: number) => {
        setCollapsedAccessories(prev => {
            const newSet = new Set(prev);
            if (newSet.has(index)) {
                newSet.delete(index);
            } else {
                newSet.add(index);
            }
            return newSet;
        });
    };

    const handleRun = (instrument: IdentifiedInstrument, index: number) => {
        const qty = instrument.quantity ? ` (${instrument.quantity})` : '';

        // Prepare vendor search parameters to pass to Search tab
        const vendorParams: VendorSearchParams = {
            category: instrument.category,
            productName: instrument.productName,
            strategy: instrument.strategy,
            specifiedVendors: instrument.specifiedVendors,
            specifiedModelFamilies: instrument.specifiedModelFamilies,
            applicableStandards: instrument.applicableStandards,
            applicableStandardsTitles: instrument.applicableStandardsTitles,
            standardsSpecs: instrument.standardsSpecs
        };

        // Open new search tab with vendor search params for background search after validation
        console.log(`[SEARCH] Opening search tab for: ${instrument.category} - ${instrument.productName}`);
        addSearchTab(instrument.sampleInput, `${index + 1}. ${instrument.category}${qty}`, vendorParams, 'instrument');
    };

    const handleRunAccessory = (accessory: IdentifiedAccessory, index: number) => {
        const qty = accessory.quantity ? ` (${accessory.quantity})` : '';

        // Prepare vendor search parameters to pass to Search tab
        const vendorParams: VendorSearchParams = {
            category: accessory.category,
            productName: accessory.accessoryName,
            strategy: accessory.strategy,
            specifiedVendors: accessory.specifiedVendors,
            specifiedModelFamilies: accessory.specifiedModelFamilies,
            applicableStandards: accessory.applicableStandards,
            applicableStandardsTitles: accessory.applicableStandardsTitles,
            standardsSpecs: accessory.standardsSpecs
        };

        // Open new search tab with vendor search params for background search after validation
        console.log(`[SEARCH] Opening search tab for accessory: ${accessory.category} - ${accessory.accessoryName}`);
        addSearchTab(accessory.sampleInput, `${index + 1}. ${accessory.category}${qty}`, vendorParams, 'accessory');
    };

    // ── Instrument & Accessory Selection Helpers ──────────────────────────────
    const isAccessoryDerivedFromInstrument = (accessory: IdentifiedAccessory, instrument: IdentifiedInstrument): boolean => {
        if (!accessory || !instrument) return false;
        const parentCat = (accessory.parentInstrumentCategory || '').trim().toLowerCase();
        const instCat = (instrument.category || '').trim().toLowerCase();
        if (!parentCat || !instCat) return false;
        return parentCat === instCat || instCat.includes(parentCat) || parentCat.includes(instCat);
    };

    const getDerivedAccessoriesForInstrument = (
        instrumentIndex: number,
        currentInstruments: IdentifiedInstrument[],
        currentAccessories: IdentifiedAccessory[]
    ): number[] => {
        const inst = currentInstruments[instrumentIndex];
        if (!inst) return [];
        return currentAccessories
            .map((acc, accIdx) => ({ acc, accIdx }))
            .filter(({ acc }) => isAccessoryDerivedFromInstrument(acc, inst))
            .map(({ accIdx }) => accIdx);
    };

    const isAccessoryDerivedFromSelectedInstrument = (accessory: IdentifiedAccessory): boolean => {
        if (!accessory || !accessory.parentInstrumentCategory) return false;
        return Array.from(selectedInstruments).some(instIdx => {
            const inst = instruments[instIdx];
            return inst ? isAccessoryDerivedFromInstrument(accessory, inst) : false;
        });
    };

    const handleToggleInstrument = (index: number) => {
        setSelectedInstruments(prev => {
            const next = new Set(prev);
            const isNowSelected = !next.has(index);
            if (isNowSelected) {
                next.add(index);
            } else {
                next.delete(index);
            }

            // Auto-select / auto-deselect derived accessories
            const derivedAccIndices = getDerivedAccessoriesForInstrument(index, instruments, accessories);
            if (derivedAccIndices.length > 0) {
                setSelectedAccessories(prevAcc => {
                    const nextAcc = new Set(prevAcc);
                    if (isNowSelected) {
                        derivedAccIndices.forEach(idx => nextAcc.add(idx));
                    } else {
                        // When unchecking, only remove if no other selected instrument also derives this accessory
                        derivedAccIndices.forEach(accIdx => {
                            const acc = accessories[accIdx];
                            const hasOtherSelectedParent = Array.from(next).some(otherInstIdx => {
                                const otherInst = instruments[otherInstIdx];
                                return otherInst ? isAccessoryDerivedFromInstrument(acc, otherInst) : false;
                            });
                            if (!hasOtherSelectedParent) {
                                nextAcc.delete(accIdx);
                            }
                        });
                    }
                    return nextAcc;
                });
            }

            return next;
        });
    };

    const handleToggleAccessory = (index: number) => {
        setSelectedAccessories(prev => {
            const next = new Set(prev);
            if (next.has(index)) {
                next.delete(index);
            } else {
                next.add(index);
            }
            return next;
        });
    };

    const handleSelectAllTab = (tab: 'instruments' | 'accessories') => {
        if (tab === 'instruments') {
            const allSelected = instruments.length > 0 && selectedInstruments.size === instruments.length;
            if (allSelected) {
                setSelectedInstruments(new Set());
                // Also clear derived accessories
                setSelectedAccessories(new Set());
            } else {
                const allInst = new Set(instruments.map((_, i) => i));
                setSelectedInstruments(allInst);
                // Also auto-select all accessories derived from any instrument
                const allDerived = new Set<number>();
                accessories.forEach((acc, accIdx) => {
                    const hasParent = instruments.some(inst => isAccessoryDerivedFromInstrument(acc, inst));
                    if (hasParent) allDerived.add(accIdx);
                });
                setSelectedAccessories(allDerived);
            }
        } else {
            const allSelected = accessories.length > 0 && selectedAccessories.size === accessories.length;
            if (allSelected) {
                setSelectedAccessories(new Set());
            } else {
                setSelectedAccessories(new Set(accessories.map((_, i) => i)));
            }
        }
    };

    const handleSelectAllBOM = () => {
        const allInst = new Set(instruments.map((_, i) => i));
        const allAcc = new Set(accessories.map((_, i) => i));
        setSelectedInstruments(allInst);
        setSelectedAccessories(allAcc);
    };

    const handleClearAllSelection = () => {
        setSelectedInstruments(new Set());
        setSelectedAccessories(new Set());
    };

    // ── Batch Search Execution ───────────────────────────────────────────────
    interface BatchSearchItem {
        input: string;
        title: string;
        vendorParams: VendorSearchParams;
        tabType: 'instrument' | 'accessory';
    }

    const addMultipleSearchTabs = (items: BatchSearchItem[]) => {
        if (!items || items.length === 0) return;

        // Save current scroll position before switching tabs
        if (activeTab === 'project' && projectScrollRef.current) {
            setSavedScrollPosition(projectScrollRef.current.scrollTop);
        }

        let updatedTabs = [...searchTabs];
        let firstActiveId = '';
        const now = Date.now();

        items.forEach((item, idx) => {
            const title = item.title;
            const existingTabIndex = updatedTabs.findIndex(tab => tab.title === title);
            if (existingTabIndex !== -1) {
                updatedTabs[existingTabIndex] = {
                    ...updatedTabs[existingTabIndex],
                    input: item.input,
                    vendorSearchParams: item.vendorParams,
                    tabType: item.tabType
                };
                if (!firstActiveId) {
                    firstActiveId = updatedTabs[existingTabIndex].id;
                }
            } else {
                const nextIndex = updatedTabs.length + 1;
                const id = `search-${now}-${nextIndex}-${idx}`;
                updatedTabs.push({
                    id,
                    title,
                    input: item.input,
                    vendorSearchParams: item.vendorParams,
                    tabType: item.tabType
                });
                if (!firstActiveId) {
                    firstActiveId = id;
                }
            }
        });

        setSearchTabs(updatedTabs);

        if (firstActiveId) {
            setTimeout(() => {
                setPreviousTab(activeTab);
                setActiveTab(firstActiveId);
                if (location.pathname !== '/solution/search') {
                    navigate('/solution/search', { replace: true });
                }
            }, 0);
        }

        toast({
            title: `Opened ${items.length} Search ${items.length === 1 ? 'Tab' : 'Tabs'}`,
            description: `Running recommendations for ${items.length} ${items.length === 1 ? 'item' : 'items'}.`,
        });
    };

    const handleRunSelected = () => {
        const itemsToRun: BatchSearchItem[] = [];

        // Collect selected instruments
        Array.from(selectedInstruments).sort((a, b) => a - b).forEach(index => {
            const instrument = instruments[index];
            if (!instrument) return;
            const qty = instrument.quantity ? ` (${instrument.quantity})` : '';
            const vendorParams: VendorSearchParams = {
                category: instrument.category,
                productName: instrument.productName,
                strategy: instrument.strategy,
                specifiedVendors: instrument.specifiedVendors,
                specifiedModelFamilies: instrument.specifiedModelFamilies,
                applicableStandards: instrument.applicableStandards,
                applicableStandardsTitles: instrument.applicableStandardsTitles,
                standardsSpecs: instrument.standardsSpecs
            };
            itemsToRun.push({
                input: instrument.sampleInput,
                title: `${index + 1}. ${instrument.category}${qty}`,
                vendorParams,
                tabType: 'instrument'
            });
        });

        // Collect selected accessories
        Array.from(selectedAccessories).sort((a, b) => a - b).forEach(index => {
            const accessory = accessories[index];
            if (!accessory) return;
            const qty = accessory.quantity ? ` (${accessory.quantity})` : '';
            const vendorParams: VendorSearchParams = {
                category: accessory.category,
                productName: accessory.accessoryName,
                strategy: accessory.strategy,
                specifiedVendors: accessory.specifiedVendors,
                specifiedModelFamilies: accessory.specifiedModelFamilies,
                applicableStandards: accessory.applicableStandards,
                applicableStandardsTitles: accessory.applicableStandardsTitles,
                standardsSpecs: accessory.standardsSpecs
            };
            itemsToRun.push({
                input: accessory.sampleInput,
                title: `${index + 1}. ${accessory.category}${qty}`,
                vendorParams,
                tabType: 'accessory'
            });
        });

        if (itemsToRun.length === 0) {
            toast({
                title: "No Items Selected",
                description: "Please select at least one instrument or accessory to run.",
                variant: "destructive"
            });
            return;
        }

        addMultipleSearchTabs(itemsToRun);
    };

    const handleRunAll = (scope: 'all' | 'tab' = 'all') => {
        const itemsToRun: BatchSearchItem[] = [];

        if (scope === 'all' || (scope === 'tab' && rightPanelTab === 'instruments')) {
            instruments.forEach((instrument, index) => {
                const qty = instrument.quantity ? ` (${instrument.quantity})` : '';
                const vendorParams: VendorSearchParams = {
                    category: instrument.category,
                    productName: instrument.productName,
                    strategy: instrument.strategy,
                    specifiedVendors: instrument.specifiedVendors,
                    specifiedModelFamilies: instrument.specifiedModelFamilies,
                    applicableStandards: instrument.applicableStandards,
                    applicableStandardsTitles: instrument.applicableStandardsTitles,
                    standardsSpecs: instrument.standardsSpecs
                };
                itemsToRun.push({
                    input: instrument.sampleInput,
                    title: `${index + 1}. ${instrument.category}${qty}`,
                    vendorParams,
                    tabType: 'instrument'
                });
            });
        }

        if (scope === 'all' || (scope === 'tab' && rightPanelTab === 'accessories')) {
            accessories.forEach((accessory, index) => {
                const qty = accessory.quantity ? ` (${accessory.quantity})` : '';
                const vendorParams: VendorSearchParams = {
                    category: accessory.category,
                    productName: accessory.accessoryName,
                    strategy: accessory.strategy,
                    specifiedVendors: accessory.specifiedVendors,
                    specifiedModelFamilies: accessory.specifiedModelFamilies,
                    applicableStandards: accessory.applicableStandards,
                    applicableStandardsTitles: accessory.applicableStandardsTitles,
                    standardsSpecs: accessory.standardsSpecs
                };
                itemsToRun.push({
                    input: accessory.sampleInput,
                    title: `${index + 1}. ${accessory.category}${qty}`,
                    vendorParams,
                    tabType: 'accessory'
                });
            });
        }

        if (itemsToRun.length === 0) {
            toast({
                title: "No Items Available",
                description: "No instruments or accessories to run.",
                variant: "destructive"
            });
            return;
        }

        addMultipleSearchTabs(itemsToRun);
    };

    const handleNewProject = async () => {
        // Clear conversation memory for the old project instance
        try {
            await clearSessionMemory(projectInstanceId);
            console.log('[PROJECT_INSTANCE] Cleared session memory for old instance:', projectInstanceId);
        } catch (error) {
            console.warn('[PROJECT_INSTANCE] Failed to clear session memory:', error);
        }

        // Clear current project ID to create a new project instead of updating
        setCurrentProjectId(null);

        // Reset all project state
        setShowResults(false);
        setInstruments([]);
        setAccessories([]);
        setSelectedInstruments(new Set());
        setSelectedAccessories(new Set());
        setRequirements('');
        setChatMessages([]); // Clear chat messages
        setSearchTabs([]);
        setPreviousTab('project');
        setActiveTab('project');
        setProjectName('Project'); // Reset project name to default
        setTabStates({});
        setGenericImages({}); // Clear cached images
        setIsRightDocked(true); // Reset right panel to docked

        // Generate new instance ID for the fresh project (ensures isolated backend state)
        const newInstanceId = generateNewInstanceId();
        setProjectInstanceId(newInstanceId);
        console.log('[PROJECT_INSTANCE] Generated new instance ID for new project:', newInstanceId);

        // Reset first input flag so next input triggers router classifier
        setIsFirstInputProcessed(false);

        // Clear IndexedDB state for fresh start
        await clearIndexedDBState();

        // Clear session-scoped auto-save choice so the popup is shown again for the new project.
        // This allows the user to choose whether to save this new project independently.
        const sid = localStorage.getItem('user_session_id') || 'global';
        localStorage.removeItem(`autosave_choice_${sid}`);
        localStorage.removeItem(`autosave_skip_${sid}`);
        setIsServerAutoSaveEnabled(false);
        setShowGoogleSavePopup(true);
        console.log('Started new project - cleared project ID, IndexedDB, autosave choice, and showing popup');

        toast({
            title: "New Project Started",
            description: "You can now create a fresh project",
        });
    };

    // Handle state updates from AIRecommender instances
    const handleTabStateChange = (tabId: string, state: any) => {
        setTabStates(prev => {
            // Only update if state has actually changed
            if (JSON.stringify(prev[tabId]) !== JSON.stringify(state)) {
                return {
                    ...prev,
                    [tabId]: state
                };
            }
            return prev;
        });
    };

    const handleSaveProject = async (
        overrideName?: string,
        options?: { skipDuplicateDialog?: boolean; isAutoSave?: boolean }
    ) => {
        // Use detected product type if available; do NOT fallback to projectName.
        // Do not call validation during Save to avoid blocking the save operation.
        let detectedProductType = tabStates['project']?.currentProductType || '';
        const effectiveProjectName = ((overrideName ?? projectName) || '').trim() || 'Project';

        // Auto-save guard: with no detected product type yet (e.g. the solution
        // session is sitting on an episodic-recall offer and the BOM is empty),
        // the backend rejects the save with 400 (product_type required). Skip
        // silently instead of firing a request guaranteed to fail; the next
        // state change after a real BOM exists re-triggers the auto-save.
        if (options?.isAutoSave && !detectedProductType) {
            console.log('[PROJECT] Auto-save skipped: no product type detected yet (nothing to save)');
            return;
        }

        try {
            // Collect all current project data including chat states
            const conversationHistories: Record<string, any> = {};
            const collectedDataAll: Record<string, any> = {};
            const analysisResults: Record<string, any> = {};

            // Collect data from each search tab
            const allFieldDescriptions: Record<string, string> = {};
            Object.entries(tabStates).forEach(([tabId, state]) => {
                if (state) {
                    conversationHistories[tabId] = {
                        messages: state.messages || [],
                        currentStep: state.currentStep || 'greeting',
                        searchSessionId: state.searchSessionId,
                        // Extended state for complete restoration
                        requirementSchema: state.requirementSchema || null,
                        validationResult: state.validationResult || null,
                        currentProductType: state.currentProductType || null,
                        inputValue: state.inputValue || '',
                        advancedParameters: state.advancedParameters || null,
                        selectedAdvancedParams: state.selectedAdvancedParams || {},
                        fieldDescriptions: state.fieldDescriptions || {}
                    };

                    if (state.collectedData) {
                        collectedDataAll[tabId] = state.collectedData;
                    }

                    if (state.analysisResult) {
                        analysisResults[tabId] = state.analysisResult;
                    }

                    // Merge field descriptions from all tabs
                    if (state.fieldDescriptions) {
                        Object.assign(allFieldDescriptions, state.fieldDescriptions);
                    }
                }
            });

            // Create field descriptions for better data understanding
            const baseFieldDescriptions = {
                project_name: 'Name/title of the project',
                project_description: 'Detailed description of the project purpose and scope',
                initial_requirements: 'Original user requirements and specifications provided at project start',
                product_type: 'Type/category of product being developed or analyzed',
                identified_instruments: 'List of instruments identified as suitable for the project requirements',
                identified_accessories: 'List of accessories and supporting equipment identified for the project',
                search_tabs: 'Individual search sessions created by user for different aspects of the project',
                conversation_histories: 'Complete conversation threads for each search tab including AI interactions',
                collected_data: 'Data collected during conversations and analysis for each search tab',
                current_step: 'Current workflow step in the project (greeting, requirements, analysis, etc.)',
                active_tab: 'The tab that was active when the project was last saved',
                analysis_results: 'Results from AI analysis and recommendations for each search tab',
                workflow_position: 'Detailed position in workflow to enable exact continuation',
                user_interactions: 'Summary of user actions and decisions made during the project',
                project_metadata: 'Additional metadata about project creation, updates, and usage patterns'
            };

            // Merge field descriptions from tabs with base descriptions
            const fieldDescriptions = { ...baseFieldDescriptions, ...allFieldDescriptions };

            // Use detected product type if available; do NOT fallback to projectName.
            // Do not call validation during Save to avoid blocking the save operation.
            detectedProductType = tabStates['project']?.currentProductType || '';

            // Check for duplicate project name on the client by looking at existing projects.
            // This ensures we can prompt even if the backend does not enforce unique names.
            if (!options?.skipDuplicateDialog) {
                try {
                    const listResponse = await axios.get('/api/projects');

                    if (listResponse.status === 200) {
                        const data = listResponse.data;
                        const projects: any[] = data.projects || [];

                        const nameLower = effectiveProjectName.toLowerCase();
                        const hasDuplicate = projects.some((p: any) => {
                            const pName = (p.projectName || p.project_name || '').trim();
                            const pId = p.id || p._id || null;
                            if (!pName) return false;
                            // Same name (case-insensitive) and not the very same project we are updating
                            const isSameName = pName.toLowerCase() === nameLower;
                            const isSameProject = currentProjectId && pId === currentProjectId;
                            return isSameName && !isSameProject;
                        });

                        if (hasDuplicate) {
                            const projectsList: any[] = data.projects || [];
                            const suggested = computeNextDuplicateName(effectiveProjectName, projectsList);
                            setDuplicateProjectName(effectiveProjectName);
                            setAutoRenameSuggestion(suggested);
                            setDuplicateNameDialogOpen(true);
                            return;
                        }
                    }
                } catch (e) {
                    // If duplicate check fails, continue with normal save flow.
                }
            }

            // Combine manual requirements with extracted text from file (same logic as submit)
            const finalRequirements = requirements.trim() && extractedText.trim()
                ? `${requirements}\n\n${extractedText}`
                : requirements.trim() || extractedText.trim();

            const projectData: any = {
                project_name: effectiveProjectName,
                project_description: `Project for ${effectiveProjectName} - Created on ${new Date().toLocaleDateString()}`,
                project_instance_id: projectInstanceId, // Save the project instance ID
                session_id: projectInstanceId || userSessionId, // Link this save to its chat session for memory TTL exemption
                source_page: 'solution', // Explicitly label the source page
                initial_requirements: finalRequirements,
                product_type: detectedProductType,
                detected_product_type: detectedProductType,
                identified_instruments: instruments,
                identified_accessories: accessories,
                search_tabs: searchTabs,
                conversation_histories: conversationHistories,
                collected_data: collectedDataAll,
                generic_images: genericImages,
                project_chat_messages: chatMessages, // Save Project page chat messages
                designed_solution: designedSolution,
                // awaiting_single_item_confirmation is already set above
                current_step: activeTab === 'project' ? (showResults ? 'showSummary' : 'initialInput') : 'search',
                active_tab: activeTab === 'project' ? 'Project' : (searchTabs.find(t => t.id === activeTab)?.title || activeTab), // Save tab name instead of ID
                analysis_results: analysisResults,
                field_descriptions: fieldDescriptions,
                workflow_position: {
                    current_tab: activeTab,
                    has_results: showResults,
                    total_search_tabs: searchTabs.length,
                    last_interaction: new Date().toISOString(),
                    project_phase: showResults ? 'results_review' : 'requirements_gathering'
                },
                user_interactions: {
                    tabs_created: searchTabs.length,
                    conversations_count: Object.keys(conversationHistories).length,
                    has_analysis: Object.keys(analysisResults).length > 0,
                    last_save: new Date().toISOString()
                }
            };

            // Include client-side pricing and feedback entries if present in local state
            // `pricing` may be assembled by the frontend or analysisResult; include if available
            if ((analysisResults && Object.keys(analysisResults).length > 0) || (tabStates && Object.keys(tabStates).length > 0)) {
                try {
                    // Try to collect pricing info from tab states (from RightPanel)
                    const pricingDataFromTabs: any = {};
                    Object.entries(tabStates).forEach(([tabId, tabState]: [string, any]) => {
                        if (tabState && tabState.pricingData && Object.keys(tabState.pricingData).length > 0) {
                            console.log(`[SAVE_PROJECT] Collecting pricing data from tab ${tabId}:`, Object.keys(tabState.pricingData).length, 'products');
                            pricingDataFromTabs[tabId] = tabState.pricingData;
                        }
                    });

                    if (Object.keys(pricingDataFromTabs).length > 0) {
                        projectData.pricing = pricingDataFromTabs;
                        console.log(`[SAVE_PROJECT] Included pricing data from`, Object.keys(pricingDataFromTabs).length, 'tabs');
                    }

                    // Also try to collect pricing info embedded in analysisResults for the active tab (fallback)
                    const activeAnalysis = analysisResults[activeTab] || analysisResults['project'] || null;
                    if (activeAnalysis && activeAnalysis.pricing && !projectData.pricing) {
                        projectData.pricing = activeAnalysis.pricing;
                    }
                } catch (e) {
                    console.error('[SAVE_PROJECT] Error collecting pricing data:', e);
                }
            }

            // If UI has any feedback objects (from RightPanel interactions), include them
            // We expect feedback entries to be stored in `tabStates` under each tab's user interactions
            try {
                const feedbackEntries: any[] = [];
                Object.values(tabStates).forEach((s: any) => {
                    if (s && s.feedbackEntries && Array.isArray(s.feedbackEntrieshy)) {
                        feedbackEntries.push(...s.feedbackEntries);
                    }
                });
                if (feedbackEntries.length > 0) projectData.feedback_entries = feedbackEntries;
            } catch (e) {
                // ignore
            }

            // If we have a current project ID, include it to update the existing project
            if (currentProjectId) {
                projectData.project_id = currentProjectId;
                console.log('Updating existing project:', currentProjectId);
            } else {
                console.log('Creating new project');
            }
            console.log('Saving project with comprehensive data and descriptions:', {
                fieldCount: Object.keys(projectData).length,
                hasFieldDescriptions: !!projectData.field_descriptions,
                descriptionsCount: projectData.field_descriptions ? Object.keys(projectData.field_descriptions).length : 0,
                hasWorkflowPosition: !!projectData.workflow_position,
                hasUserInteractions: !!projectData.user_interactions
            });

            const response = await axios.post('/api/projects/save', {
                ...projectData,
                displayed_media_map: (() => {
                        try {
                            const map: Record<string, any> = {};
                            const activeState = tabStates[activeTab];
                            if (!activeState || !activeState.analysisResult) return map;

                            const ranked = (activeState.analysisResult?.overallRanking?.rankedProducts) || [];
                            ranked.forEach((product: any) => {
                                try {
                                    // Save ALL products (both exact and approximate matches)
                                    if (!product) return;
                                    const vendor = product.vendor || product.vendorName || product.vendor_name || '';
                                    const pname = product.productName || product.product_name || product.name || '';
                                    if (!vendor && !pname) return;
                                    const key = `${vendor}-${pname}`.trim();
                                    const entry: any = {};

                                    const top = product.topImage || product.top_image || product.top_image_url || product.topImageUrl || null;
                                    const vendorLogo = product.vendorLogo || product.vendor_logo || product.logo || null;

                                    const resolveUrl = (obj: any) => {
                                        if (!obj) return null;
                                        if (typeof obj === 'string') return obj;
                                        return obj.url || obj.src || null;
                                    };

                                    const topUrl = resolveUrl(top);
                                    const vLogoUrl = resolveUrl(vendorLogo);

                                    if (topUrl) entry.top_image = { url: topUrl };
                                    if (vLogoUrl) entry.vendor_logo = { url: vLogoUrl };

                                    // Add matchType metadata
                                    entry.matchType = product.requirementsMatch ? 'exact' : 'approximate';

                                    if (Object.keys(entry).length > 0) map[key] = entry;
                                } catch (e) {
                                    // Continue on minor errors
                                }
                            });
                            return map;
                        } catch (e) {
                            return {};
                        }
                    })()
            });

            if (response.status !== 200) {
                let errorData: any = response.data;
                const errorMessage = errorData?.error || 'Failed to save project';
                const errorCode = errorData?.code || errorData?.errorCode;

                const looksLikeDuplicateNameError =
                    response.status === 409 ||
                    errorCode === 'DUPLICATE_PROJECT_NAME' ||
                    /already exists|already present|duplicate project name/i.test(errorMessage);

                if (!options?.skipDuplicateDialog && looksLikeDuplicateNameError) {
                    const nameInErrorMatch = errorMessage.match(/"([^"]+)"/);
                    const nameFromError = nameInErrorMatch ? nameInErrorMatch[1] : effectiveProjectName;
                    // Compute smarter suggestion based on existing projects
                    let suggested = `${nameFromError} (1)`;
                    try {
                        const listResp = await axios.get('/api/projects');
                        if (listResp.status === 200) {
                            const listData = listResp.data;
                            suggested = computeNextDuplicateName(nameFromError, listData.projects || []);
                        }
                    } catch (e) {
                        // fallback remains
                    }

                    setDuplicateProjectName(nameFromError);
                    setAutoRenameSuggestion(suggested);
                    setDuplicateDialogNameInput(nameFromError);
                    setDuplicateDialogError(null);
                    setDuplicateNameDialogOpen(true);

                    // Do not show generic error toast here; the dialog will guide the user.
                    return;
                }

                throw new Error(errorMessage);
            }

            const result = response.data;

            // Extract project_id from the response
            // Backend returns: { message: "...", project: { project_id: "...", ... } }
            const savedProjectId = result.project?.project_id || result.project_id;

            // If we didn't have a project ID before, set it now for future updates
            if (!currentProjectId && savedProjectId) {
                setCurrentProjectId(savedProjectId);
                console.log('Set currentProjectId for future updates:', savedProjectId);
            }

            // Ensure local state reflects the name we actually saved
            if (overrideName && overrideName.trim()) {
                setProjectName(overrideName.trim());
            }

            if (!options?.isAutoSave) {
                toast({
                    title: currentProjectId ? "Project Updated" : "Project Saved",
                    description: currentProjectId
                        ? `"${effectiveProjectName}" has been updated successfully`
                        : `"${effectiveProjectName}" has been saved successfully`,
                });
            }

        } catch (error: any) {
            // Check if this is a duplicate name error from backend
            const errorMessage = error.message || "";
            if (errorMessage.includes("already exists") && errorMessage.includes("Please choose a different name")) {
                // Extract the project name from the error message
                const nameMatch = errorMessage.match(/Project name '([^']+)' already exists/);
                const duplicateName = nameMatch ? nameMatch[1] : effectiveProjectName;

                // Get current projects to compute suggestion
                try {
                    const listResp = await axios.get('/api/projects');
                    if (listResp.status === 200) {
                        const listData = listResp.data;
                        const suggested = computeNextDuplicateName(duplicateName, listData.projects || []);
                        setDuplicateProjectName(duplicateName);
                        setAutoRenameSuggestion(suggested);
                        setDuplicateDialogNameInput(duplicateName);
                        setDuplicateDialogError(null);
                        setDuplicateNameDialogOpen(true);
                        return; // Don't show the generic error toast
                    }
                } catch (e) {
                    // If we can't get projects list, fall back to default behavior
                }
            }

            if (!options?.isAutoSave) {
                toast({
                    title: "Save Failed",
                    description: error.message || "Failed to save project",
                    variant: "destructive",
                });
            } else {
                console.warn('[PROJECT] Auto-save failed silently:', error);
            }
        }
    };

    const handleProjectDelete = (deletedProjectId: string) => {
        // Check if the deleted project was the currently active one
        if (currentProjectId === deletedProjectId) {
            console.log('Current project was deleted, starting new project...');
            handleNewProject();
        }
    };

    const handleCacheOpen = async (projectId: string) => {
        console.log('[EPISODIC_RECALL] Open clicked → recalling saved project from DB:', projectId);
        setCacheConfirmationOpen(false);
        // Resolve the pending recall on the backend so the next message isn't
        // interpreted as a reply to the Open/Ignore question, then retrieve the project.
        try {
            await axios.post('/api/projects/recall/dismiss', {
                session_id: projectInstanceId || userSessionId,
            });
            console.log('[EPISODIC_RECALL] Pending recall dismissed on backend');
        } catch (e) {
            console.warn('[EPISODIC_RECALL] Failed to dismiss pending recall (non-fatal):', e);
        }
        await handleOpenProject(projectId);
        console.log('[EPISODIC_RECALL] Saved project recall complete:', projectId);
    };

    const handleCachePreview = async (projectId: string) => {
        if (!projectId) return;
        console.log('[EPISODIC_RECALL] Preview clicked → fetching saved project (no recall):', projectId);
        setIsPreviewLoading(true);
        setPreviewProjectData(null);
        try {
            const response = await axios.get(`/api/projects/${projectId}`);
            if (response.status === 200) {
                setPreviewProjectData(response.data.project || response.data);
            } else {
                toast({
                    title: "Preview Failed",
                    description: "Failed to fetch project specifications.",
                    variant: "destructive",
                });
            }
        } catch (err: any) {
            console.error("Preview project specs error:", err);
            toast({
                title: "Preview Failed",
                description: err.message || "Failed to load project details.",
                variant: "destructive",
            });
        } finally {
            setIsPreviewLoading(false);
        }
    };

    const handleCacheIgnore = async () => {
        console.log('[EPISODIC_RECALL] Ignore clicked → declining recall, re-analyzing fresh');
        setCacheConfirmationOpen(false);
        setIsLoading(true);

        addChatMessage('user', 'Ignore & run fresh');

        const newStreamId = `stream-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
        setStreamId(newStreamId);

        try {
            const ignoreResponse = await axios.post('/api/projects/recall/ignore', {
                session_id: projectInstanceId || userSessionId,
            });
            const originalQuery = (
                ignoreResponse.data?.originalQuery ||
                ignoreResponse.data?.original_query ||
                lastSubmittedRequirementsRef.current ||
                ''
            ).trim();

            if (!originalQuery) {
                addChatMessage('assistant', ignoreResponse.data?.message || "Okay — I'll analyze your request from scratch.");
                setIsLoading(false);
                return;
            }

            console.log('[API] Declining recall, calling solution agent fresh...');
            const intentResult = await callSolutionAgent(
                originalQuery,
                instruments.length > 0 ? instruments : undefined,
                accessories.length > 0 ? accessories : undefined,
                false,
                projectInstanceId,
                userSessionId,
                newStreamId,
                !standardsEnabled
            );

            console.log('[API] Fresh solution agent result:', intentResult);
            const unpackedResult = (intentResult as any).result?.intent ? (intentResult as any).result : intentResult;
            
            if (unpackedResult.success === false || unpackedResult.intent === 'error') {
                addChatMessage('assistant', unpackedResult.message || "I'm having trouble processing your request.");
                toast({
                    title: "Request Failed",
                    description: unpackedResult.message || "The request took too long or failed.",
                    variant: "destructive",
                });
                setIsLoading(false);
                return;
            }

            // Process solution agent response exactly like in the normal path
            addChatMessage('assistant', unpackedResult.message);
            setLastIntentResult(unpackedResult);
            setInstruments(unpackedResult.instruments || []);
            setAccessories(unpackedResult.accessories || []);
            setDesignedSolution(unpackedResult.designedSolution || null);
            setShowResults(true);

            const totalItems = (unpackedResult.instruments?.length || 0) + (unpackedResult.accessories?.length || 0);
            if (totalItems >= 2) {
                setIsRightDocked(false);
            }

            if (unpackedResult.projectName) {
                setProjectName(unpackedResult.projectName);
            }

            // Fresh re-analysis produced results — create the server project if needed
            // (the submit-time eager init was removed to avoid empty projects).
            if (!currentProjectId && isServerAutoSaveEnabled && lastSubmittedRequirementsRef.current.trim()) {
                initializeProjectInBackground(lastSubmittedRequirementsRef.current);
            }

            const productNames: string[] = [];
            (unpackedResult.instruments || []).forEach((inst: any) => {
                const imageKey = getInstrumentImageKey(inst);
                if (imageKey) productNames.push(imageKey);
            });
            (unpackedResult.accessories || []).forEach((acc: any) => {
                const imageKey = getAccessoryImageKey(acc);
                if (imageKey) productNames.push(imageKey);
            });
            if (productNames.length > 0) {
                fetchGenericImagesLazy(productNames);
            }

            toast({
                title: "Success",
                description: `Identified ${unpackedResult.instruments?.length || 0} instruments and ${unpackedResult.accessories?.length || 0} accessories`,
            });

        } catch (error: any) {
            addChatMessage('assistant', `I couldn't process your request. ${error.message || 'Please try again.'}`);
            toast({
                title: "Error",
                description: error.message || "Failed to process request fresh",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    const handleOpenProject = async (projectId: string) => {
        setIsRestoringState(true); // Prevent auto-save and triggers during load
        try {
            const response = await axios.get(`/api/projects/${projectId}`);

            if (response.status !== 200) {
                const errorData = response.data;
                throw new Error(errorData.error || 'Failed to load project');
            }

            const data = response.data;
            const project = data.project;
            console.log('Loading project data:', project);

            // Set current project ID to ensure updates save to this project
            setCurrentProjectId(projectId);

            // Clear IndexedDB state since we're loading a project from backend
            // This ensures the loaded project data takes precedence on subsequent refreshes
            await clearIndexedDBState();
            console.log('[PROJECT] Cleared IndexedDB - loading from backend');

            // Restore project state with debugging
            // Restore product type from loaded project
            const restoredProductType = project.productType || project.product_type || projectName;
            setProjectName(project.projectName || project.project_name || 'Project');
            setRequirements(project.initialRequirements || project.initial_requirements || '');
            setInstruments(project.identifiedInstruments || project.identified_instruments || []);
            setAccessories(project.identifiedAccessories || project.identified_accessories || []);
            setSelectedInstruments(new Set());
            setSelectedAccessories(new Set());
            setDesignedSolution(project.designedSolution || project.designed_solution || null);
            setLastIntentResult({
                intent: 'requirements',
                message: project.initialRequirements || 'Loaded from saved project',
                instruments: project.identifiedInstruments || project.identified_instruments || [],
                accessories: project.identifiedAccessories || project.identified_accessories || [],
                designedSolution: project.designedSolution || project.designed_solution || null,
                standardsApplied: true,
            });

            // Restore project instance ID if available
            if (project.projectInstanceId || project.project_instance_id) {
                const savedId = project.projectInstanceId || project.project_instance_id;
                console.log('[PROJECT] Restoring projectInstanceId:', savedId);
                setProjectInstanceId(savedId);
            }

            // Define restoredTabStates and pre-populate with the solution ('project') tab state
            // to ensure it doesn't get overridden by search tabs or set to empty
            const restoredTabStates: Record<string, any> = {
                project: {
                    currentProductType: restoredProductType
                }
            };

            console.log('Restoring project name:', project.projectName || project.project_name);
            setProjectName(project.projectName || project.project_name || 'Project');

            console.log('Restoring requirements:', (project.initialRequirements || project.initial_requirements || '').substring(0, 100));
            setRequirements(project.initialRequirements || project.initial_requirements || '');

            console.log('Restoring instruments count:', (project.identifiedInstruments || project.identified_instruments || []).length);
            setInstruments(project.identifiedInstruments || project.identified_instruments || []);

            console.log('Restoring accessories count:', (project.identifiedAccessories || project.identified_accessories || []).length);
            setAccessories(project.identifiedAccessories || project.identified_accessories || []);

            // Restore generic images
            const savedGenericImages = project.genericImages || project.generic_images || {};
            if (Object.keys(savedGenericImages).length > 0) {
                console.log('Restoring generic images:', Object.keys(savedGenericImages).length);
                // Convert all relative URLs to absolute URLs for deployment compatibility
                const absoluteGenericImages: Record<string, string> = {};
                Object.entries(savedGenericImages).forEach(([key, url]) => {
                    const absoluteUrl = getAbsoluteImageUrl(url as string);
                    if (absoluteUrl) {
                        absoluteGenericImages[key] = absoluteUrl;
                    }
                });
                setGenericImages(absoluteGenericImages);
            } else {
                setGenericImages({});
            }

            // Restore Project page chat messages
            let savedChatMessages = project.projectChatMessages || project.project_chat_messages || [];
            
            // Fallback: if empty, check if we have a 'search' conversation history (from Search page save)
            if (savedChatMessages.length === 0) {
                const convHistories = project.conversationHistories || project.conversation_history || {};
                if (convHistories['search'] && convHistories['search'].messages) {
                    savedChatMessages = convHistories['search'].messages;
                    console.log('[PROJECT] Fallback: loaded chat messages from search history');
                }
            }

            if (savedChatMessages.length > 0) {
                console.log('Restoring Project page chat messages:', savedChatMessages.length);
                // Convert timestamp strings back to Date objects
                const restoredMessages = savedChatMessages.map((msg: any) => ({
                    ...msg,
                    timestamp: msg.timestamp ? new Date(msg.timestamp) : new Date()
                }));
                setChatMessages(restoredMessages);
                // Mark as history so messages don't animate on load
                isHistoryRef.current = true;

                // Allow new messages to animate after load
                setTimeout(() => {
                    isHistoryRef.current = false;
                }, 1000);
            } else {
                setChatMessages([]);
            }

            // Show results if we have instruments/accessories
            const instruments = project.identifiedInstruments || project.identified_instruments || [];
            const accessories = project.identifiedAccessories || project.identified_accessories || [];
            console.log('Checking results - instruments:', instruments.length, 'accessories:', accessories.length);
            console.log(`[EPISODIC_RECALL] Loaded project "${project.projectName || project.project_name}" from DB → ${instruments.length} instruments, ${accessories.length} accessories restored`);
            const hasResults = instruments.length > 0 || accessories.length > 0;
            if (hasResults) {
                console.log('Setting showResults to true');
                setShowResults(true);
            } else {
                console.log('No results to show, keeping showResults false');
            }

            // Restore single item confirmation state
            // Restore Right Panel Dock state based on item count
            const totalItems = (project.identifiedInstruments || project.identified_instruments || []).length +
                (project.identifiedAccessories || project.identified_accessories || []).length;

            const savedAwaitingConfirmation = project.awaitingSingleItemConfirmation || project.awaiting_single_item_confirmation;

            if (savedAwaitingConfirmation) {
                // If waiting for confirmation (single item flow), keep docked
                setIsRightDocked(true);
            } else if (totalItems >= 2) {
                // If 2 or more items, undock panel to show list
                setIsRightDocked(false);
            } else {
                // Default docked for 0 or 1 item (unless user manually opens it later)
                setIsRightDocked(true);
            }

            // Restore search tabs and conversation states
            const savedSearchTabs = project.searchTabs || project.search_tabs || [];
            console.log('Saved search tabs:', savedSearchTabs);

            if (savedSearchTabs.length > 0) {
                console.log('Restoring search tabs...');
                setSearchTabs(savedSearchTabs);

                // Restore conversation histories for each tab
                const conversationHistories = project.conversationHistories || project.conversation_histories || project.conversationHistory || project.conversation_history || {};

                console.log('Conversation histories:', conversationHistories);

                savedSearchTabs.forEach((tab: any) => {
                    console.log(`Processing tab ${tab.id}:`, tab);

                    if (conversationHistories[tab.id]) {
                        const tabHistory = conversationHistories[tab.id];
                        console.log(`Restoring conversation for tab ${tab.id}:`, tabHistory);

                        restoredTabStates[tab.id] = {
                            messages: tabHistory.messages || [],
                            currentStep: tabHistory.currentStep || 'greeting',
                            searchSessionId: tabHistory.searchSessionId || tab.id,
                            collectedData: (project.collectedData || project.collected_data)?.[tab.id] || {},
                            analysisResult: (project.analysisResults || project.analysis_results)?.[tab.id] || null,
                            // Extended state restoration
                            requirementSchema: tabHistory.requirementSchema || null,
                            validationResult: tabHistory.validationResult || null,
                            currentProductType: tabHistory.currentProductType || null,
                            inputValue: tabHistory.inputValue || '',
                            advancedParameters: tabHistory.advancedParameters || null,
                            selectedAdvancedParams: tabHistory.selectedAdvancedParams || {},
                            fieldDescriptions: tabHistory.fieldDescriptions || (project.fieldDescriptions || project.field_descriptions) || {}
                        };

                        console.log(`Restored state for tab ${tab.id}:`, restoredTabStates[tab.id]);
                    } else {
                        // Create default state for tabs without conversation history
                        restoredTabStates[tab.id] = {
                            messages: [],
                            currentStep: 'greeting',
                            searchSessionId: tab.id,
                            collectedData: {},
                            analysisResult: null,
                            fieldDescriptions: (project.fieldDescriptions || project.field_descriptions) || {}
                        };
                    }
                });

                // Inject project_id into each tab's analysisResult for downstream components
                Object.keys(restoredTabStates).forEach((tabId) => {
                    if (tabId === 'project') return;
                    const ar = restoredTabStates[tabId].analysisResult;
                    if (ar && !ar.projectId) {
                        ar.projectId = projectId;
                    }

                    // Embed pricing data into analysisResult for RightPanel to use
                    if (ar && project.pricing) {
                        // Check if we have pricing data for this specific tab
                        const tabPricing = project.pricing[tabId];
                        if (tabPricing) {
                            console.log(`[LOAD_PROJECT] Embedding pricing data for tab ${tabId}:`, Object.keys(tabPricing).length, 'products');

                            // Embed pricing data into the ranked products
                            if (ar.overallRanking && ar.overallRanking.rankedProducts) {
                                ar.overallRanking.rankedProducts.forEach((product: any) => {
                                    const key = `${product.vendor || product.vendorName || product.vendor_name || ''}-${product.productName || product.product_name || product.name || ''}`.trim();
                                    if (tabPricing[key]) {
                                        console.log(`[LOAD_PROJECT] Embedding pricing for product: ${key}`);
                                        product.priceReview = tabPricing[key];
                                        product.pricing = tabPricing[key];
                                    }
                                });
                            }
                        } else {
                            // If no tab-specific pricing, check if we have general pricing data
                            if (typeof project.pricing === 'object' && !Array.isArray(project.pricing)) {
                                console.log(`[LOAD_PROJECT] Checking general pricing data for tab ${tabId}`);
                                if (ar.overallRanking && ar.overallRanking.rankedProducts) {
                                    ar.overallRanking.rankedProducts.forEach((product: any) => {
                                        const key = `${product.vendor || product.vendorName || product.vendor_name || ''}-${product.productName || product.product_name || product.name || ''}`.trim();
                                        if (project.pricing[key]) {
                                            console.log(`[LOAD_PROJECT] Embedding general pricing for product: ${key}`);
                                            product.priceReview = project.pricing[key];
                                            product.pricing = project.pricing[key];
                                        }
                                    });
                                }
                            }
                        }
                    }
                });
            } else {
                console.log('No search tabs to restore');
            }

            // Save the merged solution & search tab states
            setTabStates(restoredTabStates);

            // Restore the active tab that was saved
            const savedActiveTab = project.activeTab || project.active_tab;
            if (savedActiveTab) {
                console.log('Restoring saved active tab:', savedActiveTab);

                if (savedActiveTab === 'Project' || savedActiveTab === 'project') {
                    setActiveTab('project');
                    setPreviousTab('project');
                } else {
                    // Try to find tab by title first (new behavior)
                    const tabByTitle = savedSearchTabs.find((t: any) => t.title === savedActiveTab);
                    if (tabByTitle) {
                        setActiveTab(tabByTitle.id);
                        setPreviousTab('project');
                    } else {
                        // Fallback: try to find by ID (legacy behavior)
                        const tabById = savedSearchTabs.find((t: any) => t.id === savedActiveTab);
                        if (tabById) {
                            setActiveTab(tabById.id);
                            setPreviousTab('project');
                        } else {
                            // Default if not found
                            if (savedSearchTabs.length > 0) {
                                setActiveTab(savedSearchTabs[0].id);
                                setPreviousTab('project');
                            } else {
                                setActiveTab('project');
                                setPreviousTab('project');
                            }
                        }
                    }
                }
            } else if (savedSearchTabs.length > 0) {
                console.log('No saved active tab, setting to first search tab:', savedSearchTabs[0].id);
                setActiveTab(savedSearchTabs[0].id);
                setPreviousTab('project');
            } else {
                console.log('No search tabs and no saved active tab, setting active tab to project');
                setActiveTab('project');
                setPreviousTab('project');
            }

            console.log('Project loading completed successfully');

            // Log field descriptions and metadata if available
            const fieldDescriptions = project.fieldDescriptions || project.field_descriptions;
            if (fieldDescriptions) {
                console.log('Project field descriptions loaded:', Object.keys(fieldDescriptions).length, 'fields documented');
            }

            const workflowPosition = project.workflowPosition || project.workflow_position;
            if (workflowPosition) {
                console.log('Project workflow position:', workflowPosition);
            }

            const userInteractions = project.userInteractions || project.user_interactions;
            if (userInteractions) {
                console.log('Project user interactions summary:', userInteractions);
            }

            const projectMetadata = project.projectMetadata || project.project_metadata;
            if (projectMetadata) {
                console.log('Project metadata loaded:', projectMetadata);
            }

            // Set the current project ID for future saves (so it updates instead of creating new)
            console.log('Setting current project ID for updates:', projectId);
            setCurrentProjectId(projectId);

            // Also restore the project's current step if available
            const projectCurrentStep = project.currentStep || project.current_step;
            if (projectCurrentStep) {
                console.log('Project was at step:', projectCurrentStep);
            }

            // Silently enable server auto-save for this loaded project — no popup needed
            const sid = localStorage.getItem('user_session_id') || 'global';
            const choiceKey = `autosave_choice_${sid}`;
            localStorage.setItem(choiceKey, 'true');
            setIsServerAutoSaveEnabled(true);
            console.log('[AUTOSAVE] Silently enabled for project loaded from backend:', projectId);

            toast({
                title: "Project Loaded",
                description: `"${project.projectName || project.project_name}" has been loaded successfully. ${savedSearchTabs.length} search tabs restored.`,
            });
        } catch (error: any) {
            toast({
                title: "Load Failed",
                description: error.message || "Failed to load project",
                variant: "destructive",
            });
        } finally {
            setIsRestoringState(false);
        }
    };

    // ✅ Save scroll position before leaving Project tab and sync URL
    const handleTabChange = (newTab: string) => {
        if (activeTab === 'project' && projectScrollRef.current) {
            setSavedScrollPosition(projectScrollRef.current.scrollTop);
        }
        setPreviousTab(activeTab);
        setActiveTab(newTab);

        // Sync URL with tab state
        if (newTab === 'project') {
            // Navigate to /solution when switching to project tab
            if (location.pathname !== '/solution') {
                navigate('/solution', { replace: true });
            }
        } else {
            // Navigate to /solution/search when switching to any search tab
            if (location.pathname !== '/solution/search') {
                navigate('/solution/search', { replace: true });
            }
        }
    };

    // ✅ Restore scroll position when returning to Project tab
    useEffect(() => {
        if (activeTab === 'project' && projectScrollRef.current && savedScrollPosition > 0) {
            // Use requestAnimationFrame for more reliable DOM timing
            requestAnimationFrame(() => {
                if (projectScrollRef.current) {
                    projectScrollRef.current.scrollTop = savedScrollPosition;
                }
                // Double-check with a small delay as fallback
                setTimeout(() => {
                    if (projectScrollRef.current && projectScrollRef.current.scrollTop !== savedScrollPosition) {
                        projectScrollRef.current.scrollTop = savedScrollPosition;
                    }
                }, 50);
            });
        }
    }, [activeTab, savedScrollPosition]);

    // Additional effect to handle scroll position restoration after content changes
    useEffect(() => {
        if (activeTab === 'project' && projectScrollRef.current && savedScrollPosition > 0) {
            const timer = setTimeout(() => {
                if (projectScrollRef.current) {
                    projectScrollRef.current.scrollTop = savedScrollPosition;
                }
            }, 150); // Longer delay to ensure content including images is loaded

            return () => clearTimeout(timer);
        }
    }, [activeTab, showResults, instruments, accessories]);

    const resetDuplicateDialog = () => {
        setDuplicateNameDialogOpen(false);
        setDuplicateProjectName(null);
        setAutoRenameSuggestion(null);
        setDuplicateDialogError(null);
    };

    const handleDuplicateNameChangeConfirm = () => {
        const trimmed = (duplicateDialogNameInput || '').trim();
        if (!trimmed) {
            setDuplicateDialogError('Project name is required');
            return;
        }

        resetDuplicateDialog();
        handleSaveProject(trimmed);
    };

    const handleDuplicateNameAutoRename = async () => {
        const baseName = (duplicateProjectName || projectName || '').trim() || 'Project';
        let suggested = autoRenameSuggestion || `${baseName} (1)`;
        try {
            // Try to compute next available suggestion based on existing projects
            const listResp = await axios.get('/api/projects');
            if (listResp.status === 200) {
                const listData = listResp.data;
                suggested = computeNextDuplicateName(baseName, listData.projects || []);
            }
        } catch (e) {
            // ignore and use fallback
        }

        resetDuplicateDialog();

        // Save immediately with the suggested name, and avoid showing the duplicate dialog again for this attempt
        handleSaveProject(suggested, { skipDuplicateDialog: true });
    };

    const handleInitializeProject = async () => {
        const trimmedName = initProjectName.trim();
        if (!trimmedName) {
            setInitProjectError('Project name is required');
            return;
        }

        setIsInitializing(true);
        setInitProjectError(null);

        try {
            const newInstanceId = generateNewInstanceId();

            const projectData = {
                project_name: trimmedName,
                project_description: `Solution project for ${trimmedName} - Created on ${new Date().toLocaleDateString()}`,
                initial_requirements: 'Project initialized',
                source_page: 'solution',
                is_initialization: true,
                project_instance_id: newInstanceId,
                session_id: newInstanceId, // Link this save to its chat session for memory TTL exemption
                conversation_histories: {
                    'project': {
                        messages: [],
                        currentStep: 'initialInput',
                        projectInstanceId: newInstanceId,
                    }
                },
                product_type: 'unknown',
                current_step: 'initialInput',
                workflow_position: {
                    current_tab: 'project',
                    has_results: false,
                    last_interaction: new Date().toISOString(),
                    project_phase: 'requirements_gathering'
                },
                user_interactions: {
                    conversations_count: 0,
                    has_analysis: false,
                    last_save: new Date().toISOString()
                }
            };

            const response = await axios.post('/api/projects/save', projectData);

            const result = response.data;
            const newProjectId = result.project?.project_id || result.project?.id;

            if (!newProjectId) {
                throw new Error('Project ID was not returned');
            }

            toast({
                title: "Project Initialized",
                description: `"${trimmedName}" has been created and will be auto-saved.`,
            });

            setProjectName(trimmedName);
            setEditProjectNameValue(trimmedName);
            setCurrentProjectId(newProjectId);
            setProjectInstanceId(newInstanceId);
            setIsServerAutoSaveEnabled(true);
            // Persist session-scoped choice
            const choiceKey = getAutosaveChoiceKey();
            localStorage.setItem(choiceKey, 'true');
            setShowInitProjectDialog(false);

        } catch (err: any) {
            console.error('Failed to initialize project:', err);
            setInitProjectError(err.response?.data?.error || err.message || 'Failed to initialize project');
        } finally {
            setIsInitializing(false);
        }
    };

    const handleSkipInitialization = () => {
        const skipKey = getAutosaveSkipKey();
        localStorage.setItem(skipKey, 'true');
        const choiceKey = getAutosaveChoiceKey();
        localStorage.setItem(choiceKey, 'false');
        setIsServerAutoSaveEnabled(false);
        setShowInitProjectDialog(false);
    };

    const initializeProjectInBackground = async (firstRequirements: string) => {
        try {
            console.log('[PROJECT] Auto-initializing project in background...');
            const nameResponse = await axios.post('/api/projects/generate-name', {
                requirements: firstRequirements
            });
            let generatedName = nameResponse.data.project_name || 'Solution Project';

            // Deduplicate name against existing projects to avoid backend duplicate name save rejection
            try {
                const listResp = await axios.get('/api/projects');
                if (listResp.status === 200) {
                    const projectsList = listResp.data.projects || [];
                    const nameLower = generatedName.toLowerCase();
                    const hasDuplicate = projectsList.some((p: any) => {
                        const pName = (p.projectName || p.project_name || '').trim();
                        return pName.toLowerCase() === nameLower;
                    });
                    if (hasDuplicate) {
                        generatedName = computeNextDuplicateName(generatedName, projectsList);
                        console.log('[PROJECT] Auto-initialized name deduplicated to:', generatedName);
                    }
                }
            } catch (e) {
                // Ignore errors fetching project list, fallback to backend handling
            }
            
            const newInstanceId = projectInstanceId || generateNewInstanceId();
            const projectData = {
                project_name: generatedName,
                project_description: `Solution project for ${generatedName} - Created on ${new Date().toLocaleDateString()}`,
                initial_requirements: firstRequirements,
                source_page: 'solution',
                is_initialization: true,
                project_instance_id: newInstanceId,
                session_id: newInstanceId, // Link this save to its chat session for memory TTL exemption
                conversation_histories: {
                    'project': {
                        messages: [],
                        currentStep: 'initialInput',
                        projectInstanceId: newInstanceId,
                    }
                },
                product_type: 'unknown',
                current_step: 'initialInput',
                workflow_position: {
                    current_tab: 'project',
                    has_results: false,
                    last_interaction: new Date().toISOString(),
                    project_phase: 'requirements_gathering'
                },
                user_interactions: {
                    conversations_count: 0,
                    has_analysis: false,
                    last_save: new Date().toISOString()
                }
            };

            const response = await axios.post('/api/projects/save', projectData);
            const result = response.data;
            const newProjectId = result.project?.project_id || result.project?.id;

            if (newProjectId) {
                setProjectName(generatedName);
                setEditProjectNameValue(generatedName);
                setCurrentProjectId(newProjectId);
                setProjectInstanceId(newInstanceId);
                setIsServerAutoSaveEnabled(true);
                localStorage.setItem(getAutosaveChoiceKey(), 'true');
                toast({
                    title: "Project Auto-Initialized",
                    description: `"${generatedName}" has been created in the background.`,
                });
            } else {
                console.error('[PROJECT] Project ID was not returned during auto-initialization');
            }
        } catch (err) {
            console.error('[PROJECT] Background project initialization failed:', err);
        }
    };

    // AUTO-SAVE: Persist COMPLETE state to IndexedDB (and Server if enabled) whenever data changes
    const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    // Server auto-save gets its own, much longer debounce than IndexedDB.
    // IndexedDB is a local write and stays responsive; the server save is a
    // full ~200KB Azure Blob PUT + old-blob DELETE. During an active
    // multi-minute streaming response, tabStates/instruments/accessories can
    // update every few seconds, which previously re-armed a single 1500ms
    // timer and still fired a full server save on nearly every update. A
    // separate, longer window coalesces those into far fewer server round-trips
    // without slowing down local persistence.
    const serverSaveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const SERVER_AUTOSAVE_DEBOUNCE_MS = 8000;

    useEffect(() => {
        // Skip saving during initial load/restore
        if (isRestoringState) return;

        // Skip saving if nothing meaningful to save
        if (!chatMessages.length && !instruments.length && !accessories.length && projectName === 'Project') {
            return;
        }

        // Debounce local IndexedDB saves to avoid too many writes
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current);
        }

        saveTimeoutRef.current = setTimeout(async () => {
            const scrollPosition = currentScrollPositionRef.current;

            const stateToSave = {
                chatMessages,
                instruments,
                accessories,
                showResults,
                activeTab,
                previousTab,
                searchTabs,
                projectName,
                currentProjectId,
                isRightDocked,
                tabStates,
                genericImages,
                projectInstanceId,
                standardsEnabled,
                scrollPosition,
                rightPanelScroll: rightPanelScrollPositionRef.current,
                savedAt: new Date().toISOString()
            };

            await saveStateToIndexedDB(stateToSave);
            console.log(`[PROJECT] Complete state auto-saved to IndexedDB`);
        }, 1500);

        // Debounce server saves separately, with a much longer window, so a
        // fast-moving stream coalesces into one save shortly after it settles
        // instead of a save per intermediate update.
        if (isServerAutoSaveEnabled && currentProjectId) {
            if (serverSaveTimeoutRef.current) {
                clearTimeout(serverSaveTimeoutRef.current);
            }
            serverSaveTimeoutRef.current = setTimeout(async () => {
                try {
                    await handleSaveProject(projectName, { skipDuplicateDialog: true, isAutoSave: true });
                    console.log(`[PROJECT] Complete state auto-saved to Server`);
                } catch (e) {
                    console.warn(`[PROJECT] Server auto-save failed:`, e);
                }
            }, SERVER_AUTOSAVE_DEBOUNCE_MS);
        }

        return () => {
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current);
            }
            if (serverSaveTimeoutRef.current) {
                clearTimeout(serverSaveTimeoutRef.current);
            }
        };
    }, [
        chatMessages,
        instruments,
        accessories,
        showResults,
        activeTab,
        previousTab,
        searchTabs,
        projectName,
        currentProjectId,
        isRightDocked,
        tabStates,
        genericImages,
        projectInstanceId,
        standardsEnabled,
        isRestoringState,
        isServerAutoSaveEnabled
    ]);

    // Show loading indicator while restoring state from IndexedDB
    if (isRestoringState) {
        return (
            <div className="min-h-screen w-full app-glass-gradient flex items-center justify-center animate-in fade-in duration-300">
                <div className="text-center animate-in zoom-in-95 duration-500">
                    <div className="w-20 h-20 rounded-full overflow-hidden shadow-xl border-2 border-white/50 mx-auto mb-4 animate-pulse bg-white">
                        <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover" />
                    </div>
                    <p className="text-muted-foreground text-lg font-medium">Restoring your session...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-screen w-full app-glass-gradient flex flex-col animate-in fade-in duration-300 overflow-hidden custom-visible-scrollbar-dark">
            {/* Decorative background images */}
            <div className="absolute inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
                <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
            </div>
            {/* Header - uses MainHeader with clickable video navigation */}
            <MainHeader
                onSave={() => handleSaveProject()}
                onNew={handleNewProject}
                onDownloadWorkflow={() => setIsDownloadDialogOpen(true)}
                onProjectSelect={handleOpenProject}
                onProjectDelete={handleProjectDelete}
            >
                {searchTabs.length > 0 && (
                    <div className="max-w-[calc(100vw-330px)] min-w-0">
                        <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
                            <TabsList className="w-full bg-transparent p-0 h-auto">
                                <div className="flex items-center gap-2 overflow-x-auto whitespace-nowrap">
                                    <div className="flex items-center gap-2">
                                        <TabsTrigger
                                            value="project"
                                            className="rounded-lg px-4 py-2 text-base font-bold text-foreground border-2 border-transparent bg-transparent data-[state=active]:border-white/30 data-[state=active]:bg-white/20 data-[state=active]:backdrop-blur-md whitespace-nowrap flex-shrink-0"
                                        >
                                            {!editingProjectName ? (
                                                <span className="inline-flex items-center gap-2">
                                                    <span className="block">{projectName}</span>
                                                    {currentProjectId && (
                                                        <span className="ml-2 text-[10px] text-sky-400 uppercase tracking-wider font-semibold">
                                                            Saved
                                                        </span>
                                                    )}
                                                    <span
                                                        onClick={(e) => {
                                                            // Prevent tab switch when clicking edit
                                                            e.stopPropagation();
                                                            e.preventDefault();
                                                            setEditingProjectName(true);
                                                            setTimeout(() => editNameInputRef.current?.focus(), 0);
                                                        }}
                                                        title="Edit project name"
                                                        className="ml-2 text-muted-foreground hover:text-foreground text-sm px-2 py-1 rounded cursor-pointer"
                                                        role="button"
                                                        tabIndex={0}
                                                        aria-label="Edit project name"
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter' || e.key === ' ') {
                                                                e.preventDefault();
                                                                setEditingProjectName(true);
                                                                setTimeout(() => editNameInputRef.current?.focus(), 0);
                                                            }
                                                        }}
                                                    >
                                                        ✎
                                                    </span>
                                                </span>
                                            ) : (
                                                <input
                                                    ref={editNameInputRef}
                                                    value={editProjectNameValue}
                                                    onChange={(e) => setEditProjectNameValue(e.target.value)}
                                                    onBlur={() => {
                                                        const v = (editProjectNameValue || '').trim() || 'Project';
                                                        setProjectName(v);
                                                        setEditingProjectName(false);
                                                    }}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') {
                                                            e.preventDefault();
                                                            const v = (editProjectNameValue || '').trim() || 'Project';
                                                            setProjectName(v);
                                                            setEditingProjectName(false);
                                                        } else if (e.key === 'Escape') {
                                                            setEditProjectNameValue(projectName);
                                                            setEditingProjectName(false);
                                                        }
                                                    }}
                                                    className="text-sm px-2 py-1 rounded-md border border-border bg-background min-w-[160px]"
                                                    autoFocus
                                                />
                                            )}
                                        </TabsTrigger>
                                    </div>
                                    {searchTabs.map((tab, index) => (
                                        <div key={tab.id} className="flex items-center min-w-0 flex-shrink">
                                            <TabsTrigger
                                                value={tab.id}
                                                className={`rounded-lg px-3 py-2 text-sm min-w-0 flex items-center gap-1.5 ${tab.tabType === 'accessory'
                                                    ? 'border-l-[3px] border-l-sky-400 data-[state=active]:bg-sky-500/20 data-[state=active]:text-sky-300'
                                                    : 'border-l-[3px] border-l-sky-500 data-[state=active]:bg-sky-500/20 data-[state=active]:text-sky-200'
                                                    }`}
                                            >
                                                <span className="truncate block">{tab.title}</span>
                                                <span
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); closeSearchTab(tab.id); }}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter' || e.key === ' ') {
                                                            e.stopPropagation();
                                                            closeSearchTab(tab.id);
                                                        }
                                                    }}
                                                    className="ml-0.5 text-muted-foreground hover:text-foreground text-lg flex-shrink-0 leading-none cursor-pointer"
                                                    aria-label={`Close ${tab.title}`}
                                                >
                                                    ×
                                                </span>
                                            </TabsTrigger>
                                        </div>
                                    ))}
                                </div>
                            </TabsList>
                        </Tabs>
                    </div>
                )}
            </MainHeader>

{/* Standards Toggle - Below Server Status Banner */}
            {chatMessages.length === 0 && (
                <div className="fixed left-0 right-0 z-[39] flex justify-end px-4 py-2 transition-all duration-300" style={{ top: 'calc(var(--banner-height, 0px) + 96px)', pointerEvents: 'none' }}>
                    <div style={{ pointerEvents: 'auto' }}>
                    <div
                        className="flex items-center gap-3 px-3 py-1.5 rounded-xl"
                        style={{
                            background: 'rgba(255,255,255,0.22)',
                            backdropFilter: 'blur(14px)',
                            WebkitBackdropFilter: 'blur(14px)',
                            border: '1px solid rgba(255,255,255,0.40)',
                            boxShadow: '0 4px 16px 0 rgba(31,38,135,0.10)'
                        }}
                    >
                        <div className="flex items-center gap-1">
                            <label
                                htmlFor="standards-toggle-main"
                                className="hidden md:inline text-[12px] text-slate-600 cursor-pointer select-none font-semibold tracking-wide whitespace-nowrap"
                            >
                                Apply standards
                            </label>
                            <Switch
                                id="standards-toggle-main"
                                checked={standardsEnabled}
                                onCheckedChange={setStandardsEnabled}
                                className="data-[state=checked]:bg-sky-500 scale-[0.8] origin-right"
                            />
                        </div>
                    </div>
                    </div>
                </div>
            )}

            {/* Floating Google-style non-blocking Cloud Auto-Save popup */}
            {showGoogleSavePopup && (
                <div className="fixed top-16 right-4 z-50 w-[360px] bg-white rounded-2xl border border-slate-100 shadow-[0_10px_40px_rgba(0,0,0,0.12)] overflow-hidden animate-in fade-in slide-in-from-top-5 duration-300 text-slate-800">
                    {/* Header Graphic */}
                    <div className="relative h-28 bg-[#f1f3f4] flex items-center justify-center">
                        <div className="absolute right-3 top-3">
                            <button
                                onClick={() => {
                                    setShowGoogleSavePopup(false);
                                    // Record session-scoped skip so it doesn't re-appear this session
                                    if (userSessionId) {
                                        localStorage.setItem(`autosave_skip_${userSessionId}`, 'true');
                                        localStorage.setItem(`autosave_choice_${userSessionId}`, 'false');
                                    }
                                }}
                                className="text-slate-400 hover:text-slate-600 transition-colors p-1 hover:bg-slate-200/50 rounded-full"
                            >
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                        <svg className="w-20 h-20" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M30 65 A 15 15 0 0 1 35 36 A 25 25 0 0 1 80 45 A 18 18 0 0 1 70 79 Z" fill="#e8eaed" />
                            <rect x="35" y="30" width="30" height="40" rx="3" fill="#ffffff" stroke="#1a73e8" strokeWidth="3" />
                            <line x1="42" y1="42" x2="58" y2="42" stroke="#1a73e8" strokeWidth="2.5" strokeLinecap="round" />
                            <line x1="42" y1="52" x2="54" y2="52" stroke="#1a73e8" strokeWidth="2.5" strokeLinecap="round" />
                            <circle cx="68" cy="62" r="12" fill="#34a853" />
                            <path d="M63 62 L67 66 L74 58" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
                        </svg>
                    </div>

                    {/* Content */}
                    <div className="p-5">
                        <h3 className="text-[16px] font-semibold text-slate-900 leading-tight">
                            Enable cloud auto-save?
                        </h3>
                        <p className="text-[13px] text-slate-600 mt-2 leading-relaxed">
                            Continuous cloud auto-saving keeps your requirement definitions, chat, and Bill of Materials safe in the secure server database.
                        </p>

                        {/* Actions */}
                        <div className="flex items-center justify-between mt-6 pt-2">
                            <div className="text-slate-400 hover:text-slate-600 cursor-pointer">
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                                </svg>
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => {
                                        setShowGoogleSavePopup(false);
                                        // Session-scoped: record that user explicitly skipped this session
                                        if (userSessionId) {
                                            localStorage.setItem(`autosave_skip_${userSessionId}`, 'true');
                                            localStorage.setItem(`autosave_choice_${userSessionId}`, 'false');
                                        }
                                    }}
                                    className="px-4 py-2 text-[13px] font-semibold text-[#1a73e8] bg-[#e8f0fe] hover:bg-[#d2e3fc] rounded-full transition-colors"
                                >
                                    No thanks
                                </button>
                                <button
                                    onClick={() => {
                                        setShowGoogleSavePopup(false);
                                        setIsServerAutoSaveEnabled(true);
                                        // Session-scoped: record enabled choice
                                        if (userSessionId) {
                                            localStorage.setItem(`autosave_choice_${userSessionId}`, 'true');
                                        }
                                        toast({
                                            title: "Auto-Save Enabled",
                                            description: "Your work will be automatically saved to the cloud."
                                        });
                                        // If requirements have already been submitted, initialize project now!
                                        const lastUserMsg = chatMessages.find(msg => msg.type === 'user')?.content;
                                        if (!currentProjectId && lastUserMsg) {
                                            initializeProjectInBackground(lastUserMsg);
                                        }
                                    }}
                                    className="px-4 py-2 text-[13px] font-semibold text-white bg-[#1a73e8] hover:bg-[#1557b0] rounded-full transition-colors shadow-sm"
                                >
                                    Enable
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Duplicate project name dialog */}
            <AlertDialog
                open={duplicateNameDialogOpen}
                onOpenChange={(open) => {
                    if (!open) {
                        resetDuplicateDialog();
                    } else {
                        setDuplicateNameDialogOpen(open);
                    }
                }}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Project name already exists</AlertDialogTitle>
                        <AlertDialogDescription>
                            {duplicateProjectName
                                ? `"${duplicateProjectName}" is already present. Do you want to change the project name, or save it as "${(autoRenameSuggestion || `${duplicateProjectName} (1)`)}"?`
                                : 'A project with this name is already present. Do you want to change the project name, or save it with a default suffix (1)?'}
                        </AlertDialogDescription>
                        <div className="mt-4 space-y-2">
                            <label htmlFor="duplicate-project-name-input" className="text-sm font-medium">
                                New project name
                            </label>
                            <input
                                id="duplicate-project-name-input"
                                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                                value={duplicateDialogNameInput}
                                onChange={(e) => {
                                    setDuplicateDialogNameInput(e.target.value);
                                    if (duplicateDialogError) {
                                        setDuplicateDialogError(null);
                                    }
                                }}
                                autoFocus
                            />
                            {duplicateDialogError && (
                                <p className="text-xs text-destructive">{duplicateDialogError}</p>
                            )}
                        </div>
                    </AlertDialogHeader>
                    <button
                        type="button"
                        onClick={resetDuplicateDialog}
                        className="absolute right-3 top-3 rounded-full p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
                        aria-label="Close duplicate name dialog"
                    >
                        <X className="h-4 w-4" />
                    </button>
                    <AlertDialogFooter>
                        <AlertDialogAction
                            onClick={handleDuplicateNameAutoRename}
                        >
                            Use suggested name
                        </AlertDialogAction>
                        <AlertDialogAction onClick={handleDuplicateNameChangeConfirm}>
                            Save new name
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>

            {/* Repeated Request Dialog */}
            <Dialog open={cacheConfirmationOpen} onOpenChange={setCacheConfirmationOpen}>
                <DialogContent className="max-w-3xl bg-white border-slate-200 text-slate-900 shadow-2xl overflow-hidden rounded-xl">
                    <DialogHeader className="border-b border-slate-100 pb-4">
                        <DialogTitle className="text-xl font-bold flex items-center gap-2 text-sky-600">
                            <span className="flex h-3 w-3 relative">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                                <span className="relative inline-flex rounded-full h-3 w-3 bg-sky-500"></span>
                            </span>
                            Repeated Request Detected
                        </DialogTitle>
                        <DialogDescription className="text-slate-500 text-sm">
                            {cacheConfirmationData?.message || "I see that you saved a similar project recently. How would you like to proceed?"}
                        </DialogDescription>
                    </DialogHeader>
 
                    <div className="py-6 grid grid-cols-1 md:grid-cols-2 gap-6 min-h-[300px] max-h-[500px] overflow-y-auto pr-2 custom-visible-scrollbar-dark">
                        {/* Matches List */}
                        <div className="space-y-3">
                            <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Matching Projects</h3>
                            <div className="space-y-2">
                                {cacheConfirmationData?.matchedProjects?.map((proj: any) => {
                                    const projId = proj.projectId || proj.project_id;
                                    const isSelected = selectedCacheProjectId === projId;
                                    return (
                                        <div
                                            key={projId}
                                            onClick={() => {
                                                setSelectedCacheProjectId(projId);
                                                handleCachePreview(projId);
                                            }}
                                            className={`p-3 rounded-lg border cursor-pointer transition-all duration-200 ${
                                                isSelected
                                                    ? "bg-sky-50 border-sky-500 shadow-md shadow-sky-500/10"
                                                    : "bg-slate-50/50 border-slate-200 hover:bg-slate-100/50 hover:border-slate-300"
                                            }`}
                                        >
                                            <div className="flex justify-between items-start">
                                                <div className="font-semibold text-slate-800 truncate max-w-[180px]">
                                                    {proj.projectName || proj.project_name || "Untitled Project"}
                                                </div>
                                                {proj.similarity !== undefined && (
                                                    <span className="text-[10px] px-2 py-0.5 rounded bg-sky-100 text-sky-700 border border-sky-200">
                                                        {Math.round(proj.similarity * 100)}% Match
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-xs text-slate-500 mt-1 flex flex-col gap-0.5">
                                                <span>Category: {proj.productType || proj.product_type || "N/A"}</span>
                                                <span>Saved: {proj.updatedAt || proj.updated_at ? new Date(proj.updatedAt || proj.updated_at).toLocaleString() : "Unknown"}</span>
                                            </div>
                                        </div>
                                    );
                                })}
                                {(!cacheConfirmationData?.matchedProjects || cacheConfirmationData.matchedProjects.length === 0) && (
                                    <div className="text-slate-400 text-xs py-4 text-center">No projects found.</div>
                                )}
                            </div>
                        </div>
 
                        {/* Preview Section */}
                        <div className="bg-slate-50/50 rounded-xl border border-slate-200 p-4 flex flex-col h-full min-h-[250px]">
                            <h3 className="text-sm font-semibold text-slate-500 mb-3 uppercase tracking-wider">Project Preview</h3>
                            {isPreviewLoading ? (
                                <div className="flex-1 flex flex-col items-center justify-center text-slate-500 gap-2">
                                    <span className="h-6 w-6 animate-spin rounded-full border-2 border-sky-500 border-t-transparent" />
                                    <span className="text-xs">Fetching specifications...</span>
                                </div>
                            ) : previewProjectData ? (
                                <div className="flex-1 overflow-y-auto text-xs space-y-3 custom-visible-scrollbar-dark pr-1">
                                    <div>
                                        <span className="text-slate-500 block font-medium">Project Name:</span>
                                        <span className="text-slate-800 text-sm font-semibold">{previewProjectData.projectName || previewProjectData.project_name || "Untitled"}</span>
                                    </div>
                                    
                                    {previewProjectData.productType || previewProjectData.product_type ? (
                                        <div>
                                            <span className="text-slate-500 block font-medium">Product Type:</span>
                                            <span className="text-slate-800 font-semibold">{previewProjectData.productType || previewProjectData.product_type}</span>
                                        </div>
                                    ) : null}
 
                                    {/* If Solution project (instruments/accessories) */}
                                    {((previewProjectData.identified_instruments || previewProjectData.instruments || []).length > 0 ||
                                      (previewProjectData.identified_accessories || previewProjectData.accessories || []).length > 0) ? (
                                        <div className="space-y-3 pt-3 border-t border-slate-200">
                                            {(previewProjectData.identified_instruments || previewProjectData.instruments || []).length > 0 && (
                                                <div className="space-y-1.5">
                                                    <span className="text-slate-500 font-semibold text-[11px] uppercase tracking-wider block">Instruments ({(previewProjectData.identified_instruments || previewProjectData.instruments).length}):</span>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {(previewProjectData.identified_instruments || previewProjectData.instruments).map((inst: any, idx: number) => (
                                                            <div 
                                                                key={idx} 
                                                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-100/70 shadow-sm transition-all hover:bg-sky-100 hover:scale-[1.02]"
                                                            >
                                                                <Cpu className="h-3 w-3 text-sky-500 flex-shrink-0" />
                                                                <span className="max-w-[150px] truncate" title={inst.productName || inst.product_name || inst.category}>
                                                                    {inst.productName || inst.product_name || inst.category}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {(previewProjectData.identified_accessories || previewProjectData.accessories || []).length > 0 && (
                                                <div className="space-y-1.5 pt-1">
                                                    <span className="text-slate-500 font-semibold text-[11px] uppercase tracking-wider block">Accessories ({(previewProjectData.identified_accessories || previewProjectData.accessories).length}):</span>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {(previewProjectData.identified_accessories || previewProjectData.accessories).map((acc: any, idx: number) => (
                                                            <div 
                                                                key={idx} 
                                                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-100/70 shadow-sm transition-all hover:bg-emerald-100 hover:scale-[1.02]"
                                                            >
                                                                <Wrench className="h-3 w-3 text-emerald-500 flex-shrink-0" />
                                                                <span className="max-w-[150px] truncate" title={acc.accessoryName || acc.accessory_name || acc.category}>
                                                                    {acc.accessoryName || acc.accessory_name || acc.category}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    ) : null}
 
                                    {/* If Search project (search tabs) */}
                                    {((previewProjectData.search_tabs || previewProjectData.searchTabs || []).length > 0) ? (
                                        <div className="space-y-1 pt-2 border-t border-slate-200">
                                            <span className="text-slate-500 font-medium block">Search Tabs ({(previewProjectData.search_tabs || previewProjectData.searchTabs).length}):</span>
                                            <ul className="list-disc list-inside text-sky-600 pl-1 space-y-1">
                                                {(previewProjectData.search_tabs || previewProjectData.searchTabs).map((tab: any, idx: number) => (
                                                    <li key={idx} className="truncate">
                                                        {tab.title || `Tab ${idx + 1}`} ({tab.input || "No query"})
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    ) : null}
 
                                    {previewProjectData.initial_requirements || previewProjectData.initialRequirements ? (
                                        <div className="pt-2 border-t border-slate-200">
                                            <span className="text-slate-500 block font-medium">Initial Requirements:</span>
                                            <p className="text-slate-700 italic text-[11px] line-clamp-3 bg-slate-100 p-2 rounded mt-1 border border-slate-200">
                                                "{previewProjectData.initial_requirements || previewProjectData.initialRequirements}"
                                            </p>
                                        </div>
                                    ) : null}

                                    {/* Conversation History */}
                                    {((previewProjectData.project_chat_messages || previewProjectData.projectChatMessages || []).length > 0) ? (
                                        <div className="space-y-2 pt-3 border-t border-slate-200">
                                            <span className="text-slate-500 font-semibold text-[11px] uppercase tracking-wider block">Conversation History:</span>
                                            <div className="space-y-2 max-h-[180px] overflow-y-auto bg-slate-100 p-2.5 rounded border border-slate-200 text-[11px] custom-visible-scrollbar-dark pr-1">
                                                {(previewProjectData.project_chat_messages || previewProjectData.projectChatMessages).map((msg: any, idx: number) => {
                                                    const isUser = msg.role === 'user';
                                                    return (
                                                        <div key={idx} className="space-y-0.5">
                                                            <span className={`font-semibold block ${isUser ? 'text-sky-700' : 'text-slate-600'}`}>
                                                                {isUser ? 'User' : 'Assistant'}:
                                                            </span>
                                                            <p className="text-slate-700 whitespace-pre-wrap leading-relaxed">
                                                                {msg.content}
                                                            </p>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    ) : null}
                                </div>
                            ) : (
                                <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
                                    <span className="text-xs text-center px-4">Select a project and click Preview to view its configuration.</span>
                                    {selectedCacheProjectId && (
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            className="mt-2 bg-sky-50 text-sky-600 hover:bg-sky-100 border-sky-200 text-xs"
                                            onClick={() => handleCachePreview(selectedCacheProjectId)}
                                        >
                                            Preview Details
                                        </Button>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
 
                    <DialogFooter className="border-t border-slate-200 pt-4 flex gap-2 sm:justify-end">
                        <Button
                            variant="ghost"
                            onClick={handleCacheIgnore}
                            className="text-slate-500 hover:text-slate-700 hover:bg-slate-100"
                        >
                            Ignore & Run Fresh
                        </Button>
                        {selectedCacheProjectId && (
                            <Button
                                variant="outline"
                                onClick={() => handleCachePreview(selectedCacheProjectId)}
                                className="bg-white hover:bg-slate-100 text-slate-700 border-slate-200"
                            >
                                Preview
                            </Button>
                        )}
                        <Button
                            onClick={() => handleCacheOpen(selectedCacheProjectId)}
                            disabled={!selectedCacheProjectId}
                            className="bg-sky-600 hover:bg-sky-500 text-white font-semibold shadow-sm"
                        >
                            Open Project
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Main Content */}
            <div className="flex-1 relative">
                {/* Right corner dock button - only show on project tab when results are available */}
                {activeTab === 'project' && showResults && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="fixed right-0 z-50 btn-glass-secondary border-0 shadow-lg rounded-r-none"
                        style={{ top: 'calc(var(--banner-height, 0px) + 9rem)', transition: 'top 0.2s ease' }}
                        onClick={() => setIsRightDocked(!isRightDocked)}
                        aria-label={isRightDocked ? "Expand right panel" : "Collapse right panel"}
                    >
                        {isRightDocked ? <ChevronLeft /> : <ChevronRight />}
                    </Button>
                )}

                <div className="w-full h-full flex">
                    {/* Main Content Area - Always mounted, use CSS to show/hide */}
                    <div className={`${activeTab === 'project' ? 'contents' : 'hidden'}`}>
                        <>
                            {/* Centered Input Section */}
                            <div className={`transition-all duration-500 ease-in-out ${!isRightDocked && showResults ? '' : 'w-full'} h-screen overflow-y-auto custom-no-scrollbar ${chatMessages.length === 0 ? 'pt-36' : 'pt-24'}`} ref={projectScrollRef}
                                style={!isRightDocked && showResults ? { width: `${100 - rightPanelWidth}%` } : undefined}
                            >
                                {/* Initial Welcome Screen - with glass-card wrapper */}
                                {chatMessages.length === 0 ? (
                                    <div className="mx-auto max-w-[900px] px-4 md:px-6 min-h-full flex items-center justify-center">
                                        <div className="w-full p-4 md:p-6 glass-card animate-in fade-in duration-500 my-6">

                                            {/* Header - Only show when no chat messages */}
                                            {chatMessages.length === 0 && (
                                                <>
                                                    <div className="text-center mb-6">
                                                        <div className="flex items-center justify-center gap-4 mb-4 w-full">
                                                            <div className="w-16 h-16 rounded-full overflow-hidden shadow flex-shrink-0 bg-white">
                                                                <img src="/engenie logo.jpeg" alt="Logo" className="w-full h-full object-cover pointer-events-none" />
                                                            </div>
                                                            <h1 className="text-2xl md:text-4xl font-bold text-foreground whitespace-nowrap">
                                                                Solution Studio
                                                            </h1>
                                                        </div>
                                                    </div>

                                                    {!showResults && (
                                                        <div className="text-center space-y-4 mb-8">
                                                            <h2 className="text-3xl font-normal text-muted-foreground">
                                                                Welcome, {user?.firstName || user?.username || 'User'}! what are your requirements
                                                            </h2>
                                                        </div>
                                                    )}
                                                </>
                                            )}


                                            {/* Streaming Progress when loading */}
                                            {showThinking && streamId && (
                                                <div className="mb-4">
                                                    <StreamingProgress
                                                        streamId={streamId}
                                                        onComplete={() => console.log('[STREAMING] Complete')}
                                                        onError={(err) => console.error('[STREAMING] Error:', err)}
                                                    />
                                                </div>
                                            )}

                                            {/* Input Form */}
                                            <form onSubmit={handleSubmit}>
                                                <div className="relative group">
                                                    <div className={`relative w-full rounded-[26px] transition-all duration-300 focus-within:ring-2 focus-within:ring-primary/50 focus-within:border-transparent hover:scale-[1.01] flex flex-col`}
                                                        style={{
                                                            boxShadow: '0 8px 32px 0 rgba(31, 38, 135, 0.15)',
                                                            WebkitBackdropFilter: 'blur(12px)',
                                                            backdropFilter: 'blur(12px)',
                                                            backgroundColor: 'rgba(255, 255, 255, 0.3)',
                                                            border: '1px solid rgba(255, 255, 255, 0.4)',
                                                            color: 'rgba(0, 0, 0, 0.8)'
                                                        }}>
                                                        <Textarea
                                                            ref={textareaRef}
                                                            value={requirements}
                                                            onChange={(e) => setRequirements(e.target.value)}
                                                            onKeyDown={handleKeyPress}
                                                            className={`w-full bg-transparent border-0 focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/70 resize-none text-base p-4 md:p-6 text-lg leading-relaxed shadow-none custom-no-scrollbar ${showResults ? 'min-h-[80px]' : 'min-h-[120px]'}`}
                                                            style={{
                                                                backgroundColor: 'transparent',
                                                                boxShadow: 'none',
                                                                color: 'inherit'
                                                            }}
                                                            placeholder="Describe the product you are looking for..."
                                                            disabled={isLoading}
                                                        />

                                                        {/* File Display & Buttons Bar - Footer inside the glass box */}
                                                        <div className="flex items-center justify-between px-4 pb-4 md:px-6 md:pb-6 pt-2">
                                                            <div className="flex items-center gap-2">
                                                                {/* Attached File Badge - visible before submit */}
                                                                {attachedFiles.length > 0 && (
                                                                    <div className="flex items-center gap-2 p-1.5 px-3 glass-card bg-primary/10 border-0 rounded-full text-xs">
                                                                        {isExtracting ? (
                                                                            <Loader2 className="h-3 w-3 text-primary animate-spin" />
                                                                        ) : (
                                                                            <FileText className="h-3 w-3 text-primary" />
                                                                        )}
                                                                        <span className="text-primary truncate max-w-[120px]">
                                                                            {attachedFiles.length === 1 ? attachedFiles[0].name : `${attachedFiles.length} files`}
                                                                        </span>
                                                                        <button
                                                                            type="button"
                                                                            onClick={handleRemoveFile}
                                                                            className="text-primary/70 hover:text-primary"
                                                                            title="Remove file"
                                                                        >
                                                                            <X className="h-3 w-3" />
                                                                        </button>
                                                                    </div>
                                                                )}

                                                                {/* Hidden file input */}
                                                                <input
                                                                    ref={fileInputRef}
                                                                    type="file"
                                                                    accept=".pdf,.docx,.doc,.txt,.jpg,.jpeg,.png,.bmp,.tiff"
                                                                    onChange={handleFileSelect}
                                                                    multiple
                                                                    className="hidden"
                                                                />
                                                            </div>

                                                            {/* Action Buttons */}
                                                            <div className="flex items-center gap-1">
                                                                {/* Attach Button */}
                                                                <Button
                                                                    type="button"
                                                                    onClick={() => fileInputRef.current?.click()}
                                                                    disabled={isLoading || isExtracting}
                                                                    className="w-8 h-8 rounded-full hover:bg-transparent transition-all duration-300 flex-shrink-0 text-muted-foreground hover:text-primary hover:scale-110"
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    title="Attach file"
                                                                >
                                                                    <Upload className="h-4 w-4" />
                                                                </Button>

                                                                {/* Submit Button */}
                                                                <Button
                                                                    type="submit"
                                                                    disabled={isLoading || isExtracting || (!requirements.trim() && !extractedText.trim())}
                                                                    className={`w-8 h-8 p-0 rounded-full transition-all duration-300 flex-shrink-0 hover:bg-transparent ${(!requirements.trim() && !extractedText.trim()) ? 'text-muted-foreground' : 'text-primary hover:scale-110'}`}
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    title="Submit"
                                                                >
                                                                    {isLoading || isExtracting ? (
                                                                        <Loader2 className="h-4 w-4 animate-spin text-primary" />
                                                                    ) : (
                                                                        <Send className="h-4 w-4" />
                                                                    )}
                                                                </Button>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            </form>
                                        </div>
                                    </div>
                                ) : (
                                    /* Full Screen Chat Mode - Matching ChatInterface layout exactly */
                                    <div className="flex-1 flex flex-col h-full bg-transparent relative">
                                        {/* Header with Logo and page title - 3-column flex: spacer | center title | toggle */}
                                        <div className="flex-none py-0 border-b border-white/10 bg-transparent z-20 relative flex items-center p-2 min-h-[64px]">
                                            {/* Left spacer - matches toggle width for centering */}
                                            <div className="flex-1 min-w-0" />

                                            {/* Centered title */}
                                            <div className="flex items-center gap-0 min-w-0 overflow-hidden">
                                                <div className="flex items-center justify-center flex-shrink-0">
                                                    <img src="/engenie logo.jpeg" alt="Logo" className="w-14 h-14 md:w-24 md:h-24 object-contain" />
                                                </div>
                                                <h1 className="text-xl md:text-3xl font-bold text-white inline-flex items-center gap-2 whitespace-nowrap truncate -ml-4 md:-ml-6">
                                                    Solution Studio
                                                </h1>
                                            </div>

                                            {/* Standards & Confirm Close Toggles - right side, flexes with available space */}
                                            <div className="flex-1 min-w-0 flex justify-end">
                                                <div
                                                    className="flex items-center gap-3 px-3 py-1.5 rounded-xl flex-shrink-0 ml-2"
                                                    style={{
                                                        background: 'rgba(255,255,255,0.22)',
                                                        backdropFilter: 'blur(14px)',
                                                        WebkitBackdropFilter: 'blur(14px)',
                                                        border: '1px solid rgba(255,255,255,0.40)',
                                                        boxShadow: '0 4px 16px 0 rgba(31,38,135,0.10)'
                                                    }}
                                                >
                                                    <div className="flex items-center gap-1">
                                                        <label
                                                            htmlFor="standards-toggle-solution"
                                                            className="hidden md:inline text-[12px] text-slate-600 cursor-pointer select-none font-semibold tracking-wide whitespace-nowrap"
                                                        >
                                                            Apply standards
                                                        </label>
                                                        <Switch
                                                            id="standards-toggle-solution"
                                                            checked={standardsEnabled}
                                                            onCheckedChange={setStandardsEnabled}
                                                            className="data-[state=checked]:bg-sky-500 scale-[0.8] origin-right"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Chat Messages Area - Same padding as ChatInterface */}
                                        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-no-scrollbar pb-32">
                                            {chatMessages.map((message, idx) => (
                                                <MessageRow
                                                    key={message.id}
                                                    message={message}
                                                    isHistory={isHistoryRef.current}
                                                    onCacheOpen={handleCacheOpen}
                                                    onCachePreview={(projId) => {
                                                        setSelectedCacheProjectId(projId);
                                                        setCacheConfirmationOpen(true);
                                                        handleCachePreview(projId);
                                                    }}
                                                    onCacheIgnore={handleCacheIgnore}
                                                    designedSolution={message.type === 'assistant' && idx === chatMessages.length - 1 ? designedSolution : null}
                                                    onDownloadWorkflow={() => setIsDownloadDialogOpen(true)}
                                                />
                                            ))}

                                            {/* Streaming Progress */}
                                            {showThinking && streamId && (
                                                <StreamingProgress
                                                    streamId={streamId}
                                                    onComplete={() => console.log('[STREAMING] Complete')}
                                                    onError={(err) => console.error('[STREAMING] Error:', err)}
                                                />
                                            )}


                                            <div ref={messagesEndRef} />
                                        </div>

                                        {/* Input Form - Fixed at bottom like ChatInterface */}
                                        <div className="fixed bottom-0 left-0 right-0 p-4 bg-transparent z-30 pointer-events-none">
                                            <div className="max-w-4xl mx-auto px-2 md:px-8 pointer-events-auto">
                                                <form onSubmit={handleSubmit}>
                                                    <div className="relative group">
                                                        {/* ponytail: transparent at rest, solid on hover/focus or once text is typed */}
                                                        <div className={`relative w-full rounded-[26px] transition-all duration-300 focus-within:ring-2 focus-within:ring-primary/50 focus-within:border-transparent hover:scale-[1.02] flex items-end ${requirements.trim() ? 'bg-white shadow-[0_8px_32px_0_rgba(31,38,135,0.15)]' : 'bg-transparent shadow-none hover:bg-white hover:shadow-[0_8px_32px_0_rgba(31,38,135,0.15)] focus-within:bg-white focus-within:shadow-[0_8px_32px_0_rgba(31,38,135,0.15)]'}`}
                                                            style={{
                                                                WebkitBackdropFilter: 'blur(12px)',
                                                                backdropFilter: 'blur(12px)',
                                                                border: '1px solid rgba(255, 255, 255, 0.4)',
                                                                color: 'rgba(0, 0, 0, 0.8)'
                                                            }}>
                                                            <textarea
                                                                ref={textareaRef}
                                                                value={requirements}
                                                                onChange={(e) => setRequirements(e.target.value)}
                                                                onKeyDown={handleKeyPress}
                                                                onInput={(e) => {
                                                                    const target = e.target as HTMLTextAreaElement;
                                                                    target.style.height = 'auto';
                                                                    target.style.height = `${Math.min(target.scrollHeight, 150)}px`;
                                                                }}
                                                                className="flex-1 min-w-0 bg-transparent border-0 focus:ring-0 focus:outline-none px-4 py-2.5 text-sm resize-none min-h-[40px] max-h-[150px] leading-relaxed custom-visible-scrollbar-dark"
                                                                style={{
                                                                    fontSize: '16px',
                                                                    fontFamily: 'inherit',
                                                                    boxShadow: 'none',
                                                                    overflowY: 'auto'
                                                                }}
                                                                placeholder="Type your message here..."
                                                                disabled={isLoading}
                                                            />

                                                            {/* Attached File Badge */}
                                                            {attachedFiles.length > 0 && (
                                                                <div className="absolute bottom-1.5 left-3 flex items-center gap-2 p-1 px-2 bg-primary/10 rounded-full text-xs">
                                                                    {isExtracting ? (
                                                                        <Loader2 className="h-3 w-3 text-primary animate-spin" />
                                                                    ) : (
                                                                        <FileText className="h-3 w-3 text-primary" />
                                                                    )}
                                                                    <span className="text-primary truncate max-w-[110px]">
                                                                        {attachedFiles.length === 1 ? attachedFiles[0].name : `${attachedFiles.length} files`}
                                                                    </span>
                                                                    <button
                                                                        type="button"
                                                                        onClick={handleRemoveFile}
                                                                        className="text-primary/70 hover:text-primary"
                                                                        title="Remove file"
                                                                    >
                                                                        <X className="h-3 w-3" />
                                                                    </button>
                                                                </div>
                                                            )}

                                                            {/* Action Buttons - flex sibling so scrollbar appears to their left */}
                                                            <div className="flex-shrink-0 pb-1.5 pr-1.5 flex items-center gap-0.5">
                                                                {/* Attach Button */}
                                                                <Button
                                                                    type="button"
                                                                    onClick={() => fileInputRef.current?.click()}
                                                                    disabled={isLoading || isExtracting}
                                                                    className="w-8 h-8 rounded-full hover:bg-transparent transition-all duration-300 flex-shrink-0 text-muted-foreground hover:text-primary hover:scale-110"
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    title="Attach file"
                                                                >
                                                                    <Upload className="h-4 w-4" />
                                                                </Button>

                                                                {/* Submit Button */}
                                                                <Button
                                                                    type="submit"
                                                                    disabled={isLoading || isExtracting || (!requirements.trim() && !extractedText.trim())}
                                                                    className={`w-8 h-8 p-0 rounded-full transition-all duration-300 flex-shrink-0 hover:bg-transparent ${(!requirements.trim() && !extractedText.trim()) ? 'text-muted-foreground' : 'text-primary hover:scale-110'}`}
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    title="Submit"
                                                                >
                                                                    {isLoading || isExtracting ? (
                                                                        <Loader2 className="h-4 w-4 animate-spin text-primary" />
                                                                    ) : (
                                                                        <Send className="h-4 w-4" />
                                                                    )}
                                                                </Button>
                                                            </div>
                                                        </div>

                                                    </div>

                                                    {/* Hidden file input */}
                                                    <input
                                                        ref={fileInputRef}
                                                        type="file"
                                                        accept=".pdf,.docx,.doc,.txt,.jpg,.jpeg,.png,.bmp,.tiff"
                                                        onChange={handleFileSelect}
                                                        multiple
                                                        className="hidden"
                                                    />
                                                </form>

                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Resize Handle between Chat and Right Panel */}
                            {showResults && !isRightDocked && (
                                <div
                                    className={`w-1.5 h-screen cursor-col-resize transition-colors duration-500 ease-in-out flex-shrink-0 ${draggingResizer ? 'bg-[#5FB3E6]' : 'bg-border hover:bg-[#5FB3E6]'
                                        }`}
                                    style={{ zIndex: 20 }}
                                    onMouseDown={(e) => {
                                        e.preventDefault();
                                        setDraggingResizer(true);
                                        const startX = e.clientX;
                                        const startWidth = rightPanelWidth;
                                        const containerWidth = window.innerWidth;

                                        const handleMouseMove = (moveEvent: MouseEvent) => {
                                            const deltaX = moveEvent.clientX - startX;
                                            const deltaPercent = (deltaX / containerWidth) * 100;
                                            const newWidth = Math.max(25, Math.min(65, startWidth - deltaPercent));

                                            if (resizerAnimFrameRef.current) {
                                                cancelAnimationFrame(resizerAnimFrameRef.current);
                                            }
                                            resizerAnimFrameRef.current = requestAnimationFrame(() => {
                                                setRightPanelWidth(newWidth);
                                            });
                                        };

                                        const handleMouseUp = () => {
                                            document.removeEventListener('mousemove', handleMouseMove);
                                            document.removeEventListener('mouseup', handleMouseUp);
                                            setDraggingResizer(false);
                                            if (resizerAnimFrameRef.current) {
                                                cancelAnimationFrame(resizerAnimFrameRef.current);
                                                resizerAnimFrameRef.current = null;
                                            }
                                        };

                                        document.addEventListener('mousemove', handleMouseMove);
                                        document.addEventListener('mouseup', handleMouseUp);
                                    }}
                                />
                            )}

                            {/* Right Panel - Results */}
                            {showResults && (
                                <div
                                    ref={rightPanelScrollRef}
                                    className={`
                                    h-[calc(100vh-8rem)] mt-32 mr-1
                                    overflow-y-auto custom-visible-scrollbar
                                    transition-all duration-500 ease-in-out origin-right
                                    ${!isRightDocked ? 'opacity-100' : 'w-0 opacity-0 overflow-hidden'}
                                `}
                                    style={!isRightDocked ? { width: `${rightPanelWidth}%` } : undefined}
                                >
                                    <div className="h-fit ml-4 mb-2
                                        bg-white/60 dark:bg-slate-900/60 
                                        backdrop-blur-md border-2 border-[#45A4DE] shadow-xl rounded-2xl
                                        p-6">
                                        <div className="w-full">
                                            {/* Tabs for Instruments and Accessories + Download Action */}
                                            <Tabs value={rightPanelTab} onValueChange={(value) => setRightPanelTab(value as 'instruments' | 'accessories')} className="w-full">
                                                <div className="flex items-center justify-between gap-3 mb-8">
                                                    <TabsList className="grid flex-1 grid-cols-2">
                                                        <TabsTrigger value="instruments" className="data-[state=active]:bg-primary data-[state=active]:text-white">
                                                            Instruments ({instruments.length})
                                                        </TabsTrigger>
                                                        <TabsTrigger value="accessories" className="data-[state=active]:bg-primary data-[state=active]:text-white">
                                                            Accessories ({accessories.length})
                                                        </TabsTrigger>
                                                    </TabsList>
                                                    <Button
                                                        type="button"
                                                        variant="outline"
                                                        size="sm"
                                                        onClick={() => setIsDownloadDialogOpen(true)}
                                                        className="h-10 px-3.5 rounded-lg border-sky-300 dark:border-sky-700/60 bg-sky-50/80 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 hover:bg-sky-100 hover:text-sky-800 transition-all flex items-center gap-1.5 shadow-xs shrink-0 cursor-pointer font-medium text-xs"
                                                        title="Download Workflow Input & Output Data (JSON / CSV)"
                                                    >
                                                        <Download className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                                                        <span>Download Data</span>
                                                    </Button>
                                                </div>

                                                {/* Selection & Batch Action Toolbar */}
                                                {(instruments.length > 0 || accessories.length > 0) && (
                                                    <div className="flex flex-wrap items-center justify-between gap-2.5 p-3 mb-6 rounded-xl bg-sky-50/60 dark:bg-slate-800/50 border border-sky-100 dark:border-slate-700/60 backdrop-blur-sm shadow-xs">
                                                        <div className="flex items-center gap-2.5">
                                                            <Checkbox
                                                                id="select-all-current-tab"
                                                                checked={
                                                                    rightPanelTab === 'instruments'
                                                                        ? instruments.length > 0 && selectedInstruments.size === instruments.length
                                                                        : accessories.length > 0 && selectedAccessories.size === accessories.length
                                                                }
                                                                onCheckedChange={() => handleSelectAllTab(rightPanelTab)}
                                                                className="h-4 w-4 rounded-sm border-sky-500 data-[state=checked]:bg-sky-500 data-[state=checked]:border-sky-500 cursor-pointer"
                                                            />
                                                            <label
                                                                htmlFor="select-all-current-tab"
                                                                className="text-xs font-semibold text-slate-700 dark:text-slate-300 cursor-pointer select-none"
                                                            >
                                                                Select All {rightPanelTab === 'instruments' ? `Instruments (${instruments.length})` : `Accessories (${accessories.length})`}
                                                            </label>

                                                            {(selectedInstruments.size > 0 || selectedAccessories.size > 0) && (
                                                                <div className="flex items-center gap-1.5 ml-2">
                                                                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-sky-100 text-sky-700 dark:bg-sky-900/60 dark:text-sky-300 border border-sky-200 dark:border-sky-800">
                                                                        {selectedInstruments.size} inst, {selectedAccessories.size} acc selected
                                                                    </span>
                                                                    <button
                                                                        type="button"
                                                                        onClick={handleClearAllSelection}
                                                                        className="text-[11px] text-muted-foreground hover:text-foreground underline cursor-pointer ml-1"
                                                                    >
                                                                        Clear
                                                                    </button>
                                                                </div>
                                                            )}
                                                        </div>

                                                        <div className="flex items-center gap-2">
                                                            {/* Run Selected Button */}
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                onClick={handleRunSelected}
                                                                disabled={selectedInstruments.size === 0 && selectedAccessories.size === 0}
                                                                className="h-8 px-3 rounded-lg bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 text-white font-medium text-xs flex items-center gap-1.5 shadow-sm transition-all hover:scale-[1.02] disabled:opacity-40 disabled:hover:scale-100 cursor-pointer disabled:cursor-not-allowed"
                                                                title="Run Search Agent for all selected instruments and accessories"
                                                            >
                                                                <Play className="h-3.5 w-3.5 fill-current" />
                                                                <span>Run Selected ({selectedInstruments.size + selectedAccessories.size})</span>
                                                            </Button>

                                                            {/* Run All Dropdown / Action */}
                                                            <DropdownMenu>
                                                                <DropdownMenuTrigger asChild>
                                                                    <Button
                                                                        type="button"
                                                                        variant="outline"
                                                                        size="sm"
                                                                        className="h-8 px-2.5 rounded-lg border-sky-300 dark:border-sky-700/60 bg-white/80 dark:bg-slate-900/80 text-sky-700 dark:text-sky-300 hover:bg-sky-50 hover:text-sky-800 text-xs font-medium flex items-center gap-1 cursor-pointer"
                                                                        title="Run all instruments and accessories"
                                                                    >
                                                                        <Play className="h-3 w-3" />
                                                                        <span>Run All</span>
                                                                        <ChevronDown className="h-3 w-3 opacity-60" />
                                                                    </Button>
                                                                </DropdownMenuTrigger>
                                                                <DropdownMenuContent align="end" className="w-56">
                                                                    <DropdownMenuItem
                                                                        onClick={() => handleRunAll('all')}
                                                                        className="text-xs cursor-pointer flex items-center justify-between"
                                                                    >
                                                                        <span>Run Entire BOM (All)</span>
                                                                        <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                                                            {instruments.length + accessories.length} items
                                                                        </span>
                                                                    </DropdownMenuItem>
                                                                    <DropdownMenuSeparator />
                                                                    <DropdownMenuItem
                                                                        onClick={() => handleRunAll('tab')}
                                                                        className="text-xs cursor-pointer flex items-center justify-between"
                                                                    >
                                                                        <span>Run All {rightPanelTab === 'instruments' ? 'Instruments' : 'Accessories'}</span>
                                                                        <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                                                            {rightPanelTab === 'instruments' ? instruments.length : accessories.length} items
                                                                        </span>
                                                                    </DropdownMenuItem>
                                                                </DropdownMenuContent>
                                                            </DropdownMenu>
                                                        </div>
                                                    </div>
                                                )}

                                                {/* Instruments Tab Content */}
                                                {rightPanelTab === 'instruments' && (
                                                    <div className="space-y-6">
                                                        {instruments.length > 0 ? (
                                                            <div className="space-y-8">
                                                                {instruments.map((instrument, index) => (
                                                                    <div
                                                                        key={index}
                                                                        className={`rounded-xl bg-gradient-to-br from-[#F5FAFC]/90 to-[#EAF6FB]/90 dark:from-slate-900/90 dark:to-slate-900/50 backdrop-blur-2xl border transition-all duration-300 ease-in-out hover:shadow-3xl hover:scale-[1.01] p-8 space-y-6 ${
                                                                            selectedInstruments.has(index)
                                                                                ? 'border-sky-400 dark:border-sky-500 shadow-xl ring-2 ring-sky-400/30'
                                                                                : 'border-white/20 dark:border-slate-700/30 shadow-2xl'
                                                                        }`}
                                                                    >
                                                                        {/* Category (primary) and Product Name (secondary) - smart category display */}
                                                                        <div className="flex items-start justify-between">
                                                                            <div className="space-y-1">
                                                                                <div className="flex items-center gap-3">
                                                                                    <Checkbox
                                                                                        id={`inst-check-${index}`}
                                                                                        checked={selectedInstruments.has(index)}
                                                                                        onCheckedChange={() => handleToggleInstrument(index)}
                                                                                        className="h-5 w-5 rounded-md border-sky-400 data-[state=checked]:bg-sky-500 data-[state=checked]:border-sky-500 cursor-pointer transition-transform hover:scale-110 shrink-0"
                                                                                        title="Select instrument (auto-selects derived accessories)"
                                                                                    />
                                                                                    <h3 className="text-xl font-semibold">
                                                                                        {index + 1}. {(() => {
                                                                                            const cat = instrument.category || '';
                                                                                            const name = instrument.productName || '';
                                                                                            const isGeneric = cat.toLowerCase() === 'accessories' || cat.toLowerCase() === 'accessory';
                                                                                            if (isGeneric && name) {
                                                                                                const parts = name.split(' for ');
                                                                                                return parts[0] || name;
                                                                                            }
                                                                                            return cat || name;
                                                                                        })()}{instrument.quantity ? ` (${instrument.quantity})` : ''}
                                                                                    </h3>
                                                                                    {(() => {
                                                                                        const derivedCount = getDerivedAccessoriesForInstrument(index, instruments, accessories).length;
                                                                                        if (derivedCount === 0) return null;
                                                                                        return (
                                                                                            <Tooltip>
                                                                                                <TooltipTrigger asChild>
                                                                                                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-sky-100/80 dark:bg-sky-950/80 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800 cursor-default">
                                                                                                        🔗 {derivedCount} derived {derivedCount === 1 ? 'accessory' : 'accessories'}
                                                                                                    </span>
                                                                                                </TooltipTrigger>
                                                                                                <TooltipContent>
                                                                                                    <p className="text-xs">Selecting this instrument automatically selects its {derivedCount} linked {derivedCount === 1 ? 'accessory' : 'accessories'}.</p>
                                                                                                </TooltipContent>
                                                                                            </Tooltip>
                                                                                        );
                                                                                    })()}
                                                                                    {(() => {
                                                                                        const imageKey = getInstrumentImageKey(instrument);
                                                                                        const imageUrl = findGenericImageUrl(imageKey);

                                                                                        if (imageUrl) {
                                                                                            return (
                                                                                                <Tooltip>
                                                                                                    <TooltipTrigger asChild>
                                                                                                        <div className="w-10 h-10 rounded-md overflow-hidden border border-border/50 bg-white flex-shrink-0 cursor-pointer hover:border-primary/50 transition-colors shadow-sm">
                                                                                                            <img
                                                                                                                src={imageUrl}
                                                                                                                alt={imageKey}
                                                                                                                className="w-full h-full object-contain p-1 mix-blend-multiply"
                                                                                                            />
                                                                                                        </div>
                                                                                                    </TooltipTrigger>
                                                                                                    <TooltipContent side="bottom" align="center" className="p-0 border-none bg-transparent shadow-none" sideOffset={10}>
                                                                                                        <div className="w-64 h-64 bg-white rounded-xl shadow-2xl border border-border/50 p-4 overflow-hidden flex items-center justify-center animate-in fade-in zoom-in-95 duration-200">
                                                                                                            <img
                                                                                                                src={imageUrl}
                                                                                                                alt={imageKey}
                                                                                                                className="max-w-full max-h-full object-contain mix-blend-multiply"
                                                                                                            />
                                                                                                        </div>
                                                                                                    </TooltipContent>
                                                                                                </Tooltip>
                                                                                            );
                                                                                        }

                                                                                        if (loadingImages.has(imageKey) || regeneratingImages.has(imageKey)) {
                                                                                            return (
                                                                                                <div className="w-10 h-10 rounded-md flex items-center justify-center bg-muted/20 border border-border/50 flex-shrink-0 shadow-sm">
                                                                                                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                                                                                                </div>
                                                                                            );
                                                                                        }

                                                                                        return (
                                                                                            <div className="w-10 h-10 rounded-md flex items-center justify-center bg-muted/30 border border-border/50 flex-shrink-0 text-muted-foreground/30 shadow-sm">
                                                                                                <span className="text-[10px]">Img</span>
                                                                                            </div>
                                                                                        );
                                                                                    })()}
                                                                                </div>

                                                                                <p className="text-muted-foreground">
                                                                                    {instrument.productName}
                                                                                </p>
                                                                            </div>
                                                                            <div className="flex flex-col gap-2">
                                                                                <Button
                                                                                    onClick={() => handleRun(instrument, index)}
                                                                                    className="rounded-xl w-10 h-10 p-0 flex items-center justify-center bg-primary/40 hover:bg-primary text-primary hover:text-white transition-all duration-300 hover:scale-110"
                                                                                    variant="ghost"
                                                                                >
                                                                                    <Play className="h-4 w-4" />
                                                                                </Button>
                                                                                <button
                                                                                    onClick={() => toggleInstrumentCollapse(index)}
                                                                                    className="w-10 h-10 flex items-center justify-center text-muted-foreground hover:text-foreground transition-all duration-200 cursor-pointer group"
                                                                                >
                                                                                    {collapsedInstruments.has(index) ? (
                                                                                        <ChevronDown className="h-4 w-4 group-hover:scale-125 transition-transform" />
                                                                                    ) : (
                                                                                        <ChevronUp className="h-4 w-4 group-hover:scale-125 transition-transform" />
                                                                                    )}
                                                                                </button>
                                                                            </div>
                                                                        </div>

                                                                        {/* Specifications */}
                                                                        {!collapsedInstruments.has(index) && (Object.keys(instrument.specifications).length > 0 || getApplicableStandardsEntries(instrument).length > 0) && (
                                                                            <div className="space-y-2">
                                                                                <h4 className="font-medium text-sm text-muted-foreground">
                                                                                    Specifications:
                                                                                </h4>

                                                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                                                    {Object.entries(instrument.specifications).map(([key, value]) => {
                                                                                        const prettyKey = prettifyKey(key);
                                                                                        const { displayValue, source: tagSource, confidence } = parseSpecValue(value);
                                                                                        // If this key is in standardsSpecs (from uploaded document), always show Standards badge
                                                                                        // regardless of whether it was a new key or already existed in specifications
                                                                                        const isInStandardsSpecs = instrument.standardsSpecs &&
                                                                                            Object.keys(instrument.standardsSpecs).some(k => k.toLowerCase() === key.toLowerCase());
                                                                                        const sourceLabel = getSourceLabel(isInStandardsSpecs ? 'standard' : tagSource);

                                                                                        return (
                                                                                            <div key={key} className="text-sm group break-words">
                                                                                                <span className="font-medium">{prettyKey}:</span>{' '}
                                                                                                <span className="text-muted-foreground">{displayValue}</span>
                                                                                                {sourceLabel && (
                                                                                                    <span className="ml-1 text-xs text-primary font-medium">
                                                                                                        {sourceLabel}
                                                                                                    </span>
                                                                                                )}
                                                                                                {confidence && confidence < 0.7 && (
                                                                                                    <span className="ml-1 text-xs text-amber-600" title={`Confidence: ${Math.round(confidence * 100)}%`}>
                                                                                                        ⚠️
                                                                                                    </span>
                                                                                                )}
                                                                                            </div>
                                                                                        );
                                                                                    })}
                                                                                    {renderApplicableStandardRows(instrument)}
                                                                                </div>
                                                                            </div>
                                                                        )}

                                                                        {/* Sample Input Preview */}
                                                                        {!collapsedInstruments.has(index) && (
                                                                            <div className="pt-3 border-t">
                                                                                <p className="text-xs text-muted-foreground mb-2">Sample Input:</p>
                                                                                <p className="text-sm bg-muted p-3 rounded-lg font-mono">
                                                                                    {formatSampleInput(instrument.sampleInput)}
                                                                                </p>
                                                                            </div>
                                                                        )}

                                                                        {/* Feedback Icons */}
                                                                        {!collapsedInstruments.has(index) && (
                                                                            <div className="-mt-2 flex justify-end gap-3">
                                                                                <button
                                                                                    onClick={() => openFeedbackModal(`instrument_${index}`, instrument.category || 'Instrument', instrument.productName, 'positive', instrument)}
                                                                                    className="transition-transform duration-300 hover:scale-125"
                                                                                >
                                                                                    <img
                                                                                        src="/icon-thumbs-3d.png"
                                                                                        alt="Thumbs Up"
                                                                                        className="h-12 w-12 object-contain"
                                                                                    />
                                                                                </button>
                                                                                <button
                                                                                    onClick={() => openFeedbackModal(`instrument_${index}`, instrument.category || 'Instrument', instrument.productName, 'negative', instrument)}
                                                                                    className="transition-transform duration-300 hover:scale-125"
                                                                                >
                                                                                    <img
                                                                                        src="/icon-thumbsdown-3d.png"
                                                                                        alt="Thumbs Down"
                                                                                        className="h-12 w-12 object-contain"
                                                                                    />
                                                                                </button>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-center py-8 text-muted-foreground">
                                                                No instruments identified
                                                            </div>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Accessories Tab Content */}
                                                {rightPanelTab === 'accessories' && (
                                                    <div className="space-y-6">
                                                        {accessories.length > 0 ? (
                                                            <div className="space-y-8">
                                                                {accessories.map((accessory, index) => (
                                                                    <div
                                                                        key={index}
                                                                        className={`rounded-xl bg-gradient-to-br from-[#F5FAFC]/90 to-[#EAF6FB]/90 dark:from-slate-900/90 dark:to-slate-900/50 backdrop-blur-2xl border transition-all duration-300 ease-in-out hover:shadow-3xl hover:scale-[1.01] p-6 space-y-4 ${
                                                                            selectedAccessories.has(index)
                                                                                ? 'border-sky-400 dark:border-sky-500 shadow-xl ring-2 ring-sky-400/30'
                                                                                : 'border-white/20 dark:border-slate-700/30 shadow-2xl'
                                                                        }`}
                                                                    >
                                                                        {/* Accessory Category (primary) and Name (secondary) - extract type from name if category is generic */}
                                                                        <div className="flex items-start justify-between">
                                                                            <div className="space-y-1">
                                                                                <div className="flex items-center gap-3">
                                                                                    <Checkbox
                                                                                        id={`acc-check-${index}`}
                                                                                        checked={selectedAccessories.has(index)}
                                                                                        onCheckedChange={() => handleToggleAccessory(index)}
                                                                                        className="h-5 w-5 rounded-md border-sky-400 data-[state=checked]:bg-sky-500 data-[state=checked]:border-sky-500 cursor-pointer transition-transform hover:scale-110 shrink-0"
                                                                                        title="Select accessory"
                                                                                    />
                                                                                    <h3 className="text-xl font-semibold">
                                                                                        {index + 1}. {(() => {
                                                                                            const cat = accessory.category || '';
                                                                                            const name = accessory.accessoryName || '';
                                                                                            const isGeneric = cat.toLowerCase() === 'accessories' || cat.toLowerCase() === 'accessory';
                                                                                            if (isGeneric && name) {
                                                                                                const parts = name.split(' for ');
                                                                                                return parts[0] || name;
                                                                                            }
                                                                                            return cat || name;
                                                                                        })()}{accessory.quantity ? ` (${accessory.quantity})` : ''}
                                                                                    </h3>
                                                                                    {accessory.parentInstrumentCategory && (
                                                                                        <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium border transition-colors ${
                                                                                            isAccessoryDerivedFromSelectedInstrument(accessory)
                                                                                                ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-800'
                                                                                                : 'bg-slate-100 dark:bg-slate-800/60 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700'
                                                                                        }`}>
                                                                                            {isAccessoryDerivedFromSelectedInstrument(accessory)
                                                                                                ? '✓ Linked to Selected Instrument'
                                                                                                : `Parent: ${accessory.parentInstrumentCategory}`}
                                                                                        </span>
                                                                                    )}
                                                                                    {(() => {
                                                                                        const imageKey = getAccessoryImageKey(accessory);
                                                                                        const imageUrl = findGenericImageUrl(imageKey);

                                                                                        if (imageUrl) {
                                                                                            return (
                                                                                                <Tooltip>
                                                                                                    <TooltipTrigger asChild>
                                                                                                        <div className="w-10 h-10 rounded-md overflow-hidden border border-border/50 bg-white flex-shrink-0 cursor-pointer hover:border-primary/50 transition-colors shadow-sm">
                                                                                                            <img
                                                                                                                src={imageUrl}
                                                                                                                alt={imageKey}
                                                                                                                className="w-full h-full object-contain p-1 mix-blend-multiply"
                                                                                                            />
                                                                                                        </div>
                                                                                                    </TooltipTrigger>
                                                                                                    <TooltipContent side="bottom" align="center" className="p-0 border-none bg-transparent shadow-none" sideOffset={10}>
                                                                                                        <div className="w-64 h-64 bg-white rounded-xl shadow-2xl border border-border/50 p-4 overflow-hidden flex items-center justify-center animate-in fade-in zoom-in-95 duration-200">
                                                                                                            <img
                                                                                                                src={imageUrl}
                                                                                                                alt={imageKey}
                                                                                                                className="max-w-full max-h-full object-contain mix-blend-multiply"
                                                                                                            />
                                                                                                        </div>
                                                                                                    </TooltipContent>
                                                                                                </Tooltip>
                                                                                            );
                                                                                        }

                                                                                        if (loadingImages.has(imageKey) || regeneratingImages.has(imageKey)) {
                                                                                            return (
                                                                                                <div className="w-10 h-10 rounded-md flex items-center justify-center bg-muted/20 border border-border/50 flex-shrink-0 shadow-sm">
                                                                                                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                                                                                                </div>
                                                                                            );
                                                                                        }

                                                                                        return (
                                                                                            <div className="w-10 h-10 rounded-md flex items-center justify-center bg-muted/30 border border-border/50 flex-shrink-0 text-muted-foreground/30 shadow-sm">
                                                                                                <span className="text-[10px]">Img</span>
                                                                                            </div>
                                                                                        );
                                                                                    })()}
                                                                                </div>

                                                                                <p className="text-muted-foreground">
                                                                                    {accessory.accessoryName}
                                                                                </p>
                                                                            </div>
                                                                            <div className="flex flex-col gap-2">
                                                                                <Button
                                                                                    onClick={() => handleRunAccessory(accessory, index)}
                                                                                    className="rounded-xl w-10 h-10 p-0 flex items-center justify-center bg-primary/40 hover:bg-primary text-primary hover:text-white transition-all duration-300 hover:scale-110"
                                                                                    variant="ghost"
                                                                                >
                                                                                    <Play className="h-4 w-4" />
                                                                                </Button>
                                                                                <button
                                                                                    onClick={() => toggleAccessoryCollapse(index)}
                                                                                    className="w-10 h-10 flex items-center justify-center text-muted-foreground hover:text-foreground transition-all duration-200 cursor-pointer group"
                                                                                >
                                                                                    {collapsedAccessories.has(index) ? (
                                                                                        <ChevronDown className="h-4 w-4 group-hover:scale-125 transition-transform" />
                                                                                    ) : (
                                                                                        <ChevronUp className="h-4 w-4 group-hover:scale-125 transition-transform" />
                                                                                    )}
                                                                                </button>
                                                                            </div>
                                                                        </div>

                                                                        {/* Specifications */}
                                                                        {!collapsedAccessories.has(index) && (Object.keys(accessory.specifications).length > 0 || getApplicableStandardsEntries(accessory).length > 0) && (
                                                                            <div className="space-y-2">
                                                                                <h4 className="font-medium text-sm text-muted-foreground">
                                                                                    Specifications:
                                                                                </h4>

                                                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                                                    {Object.entries(accessory.specifications).map(([key, value]) => {
                                                                                        const prettyKey = prettifyKey(key);
                                                                                        const { displayValue, source: tagSource, confidence } = parseSpecValue(value);
                                                                                        const isInStandardsSpecs = accessory.standardsSpecs &&
                                                                                            Object.keys(accessory.standardsSpecs).some(k => k.toLowerCase() === key.toLowerCase());
                                                                                        const sourceLabel = getSourceLabel(isInStandardsSpecs ? 'standard' : tagSource);

                                                                                        return (
                                                                                            <div key={key} className="text-sm group break-words">
                                                                                                <span className="font-medium">{prettyKey}:</span>{' '}
                                                                                                <span className="text-muted-foreground">{displayValue}</span>
                                                                                                {sourceLabel && (
                                                                                                    <span className="ml-1 text-xs text-primary font-medium">
                                                                                                        {sourceLabel}
                                                                                                    </span>
                                                                                                )}
                                                                                                {confidence && confidence < 0.7 && (
                                                                                                    <span className="ml-1 text-xs text-amber-600" title={`Confidence: ${Math.round(confidence * 100)}%`}>
                                                                                                        ⚠️
                                                                                                    </span>
                                                                                                )}
                                                                                            </div>
                                                                                        );
                                                                                    })}
                                                                                    {renderApplicableStandardRows(accessory)}
                                                                                </div>
                                                                            </div>
                                                                        )}

                                                                        {/* Sample Input Preview */}
                                                                        {!collapsedAccessories.has(index) && (
                                                                            <div className="pt-3 border-t">
                                                                                <p className="text-xs text-muted-foreground mb-2">Sample Input:</p>
                                                                                <p className="text-sm bg-muted p-3 rounded-lg font-mono">
                                                                                    {formatSampleInput(accessory.sampleInput)}
                                                                                </p>
                                                                            </div>
                                                                        )}

                                                                        {/* Feedback Icons */}
                                                                        {!collapsedAccessories.has(index) && (
                                                                            <div className="-mt-2 flex justify-end gap-3">
                                                                                <button
                                                                                    onClick={() => openFeedbackModal(`accessory_${index}`, accessory.category || 'Accessory', accessory.accessoryName, 'positive', accessory)}
                                                                                    className="transition-transform duration-300 hover:scale-125"
                                                                                >
                                                                                    <img
                                                                                        src="/icon-thumbs-3d.png"
                                                                                        alt="Thumbs Up"
                                                                                        className="h-12 w-12 object-contain"
                                                                                    />
                                                                                </button>
                                                                                <button
                                                                                    onClick={() => openFeedbackModal(`accessory_${index}`, accessory.category || 'Accessory', accessory.accessoryName, 'negative', accessory)}
                                                                                    className="transition-transform duration-300 hover:scale-125"
                                                                                >
                                                                                    <img
                                                                                        src="/icon-thumbsdown-3d.png"
                                                                                        alt="Thumbs Down"
                                                                                        className="h-12 w-12 object-contain"
                                                                                    />
                                                                                </button>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        ) : (
                                                            <div className="text-center py-8 text-muted-foreground">
                                                                No accessories identified
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                            </Tabs>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </>
                    </div>
                </div>
            </div>

            {/* Search Tabs - positioned absolutely relative to the flex-1 relative container */}
            {searchTabs.map((tab) => {
                const savedState = tabStates[tab.id];
                console.log(`Rendering AIRecommender for tab ${tab.id} with saved state:`, savedState);
                return (
                    <div
                        key={tab.id}
                        className={`absolute inset-0 top-24 ${activeTab === tab.id ? 'block' : 'hidden'}`}
                    >
                        <AIRecommender
                            key={tab.id}
                            initialInput={tab.input}
                            fillParent
                            onStateChange={(state) => handleTabStateChange(tab.id, state)}
                            savedMessages={savedState?.messages}
                            savedCollectedData={savedState?.collectedData}
                            savedCurrentStep={savedState?.currentStep}
                            savedAnalysisResult={savedState?.analysisResult}
                            savedRequirementSchema={savedState?.requirementSchema}
                            savedValidationResult={savedState?.validationResult}
                            savedCurrentProductType={savedState?.currentProductType}
                            savedInputValue={savedState?.inputValue}
                            savedAdvancedParameters={savedState?.advancedParameters}
                            savedSelectedAdvancedParams={savedState?.selectedAdvancedParams}
                            savedFieldDescriptions={savedState?.fieldDescriptions}
                            savedPricingData={savedState?.pricingData}
                            savedScrollPositions={savedState?.scrollPositions}
                            savedDockingState={savedState?.dockingState}
                            savedSearchInstanceId={savedState?.searchInstanceId}
                            savedStandardsEnabled={savedState?.standardsEnabled}
                            vendorSearchParams={tab.vendorSearchParams}
                        />
                    </div>
                );
            })}

            {/* Feedback Modal - Matching OTP Popup Styling */}
            {feedbackModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-6 animate-in fade-in duration-200">
                    <div className="max-w-sm w-full relative animate-in zoom-in-95 duration-300 acrylic-glass-pill p-6" style={{ backdropFilter: 'blur(80px)', backgroundColor: 'rgba(255, 255, 255, 0.65)' }}>
                        {/* Close Button */}
                        <button
                            onClick={closeFeedbackModal}
                            className="absolute top-5 right-8 text-muted-foreground hover:text-foreground hover:scale-125 transition-all duration-200"
                            title="Close"
                        >
                            <span className="text-lg">✕</span>
                        </button>

                        {/* Header */}
                        <div className="text-center mb-4">
                            <div className="flex items-center justify-center gap-2 mb-1">
                                <span className="text-3xl opacity-80">💬</span>
                                <h2 className="text-xl font-bold">Feedback</h2>
                            </div>
                            <p className="text-muted-foreground text-xs">
                                Help us improve by sharing your thoughts on
                                <br />
                                <span className="font-semibold">
                                    {feedbackModalItem?.name || "this item"}
                                </span>
                            </p>
                        </div>

                        {feedbackModalItem && (() => {
                            const fb = feedbackState[feedbackModalItem.key] || { type: null, comment: '', loading: false, submitted: false };

                            return (
                                <div className="space-y-3">
                                    {/* Thumbs Buttons */}
                                    <div className="flex items-center justify-center gap-6">
                                        <button
                                            onClick={() => setFeedbackType(feedbackModalItem.key, "positive")}
                                            className="transition-all duration-300 hover:scale-110 cursor-pointer p-2 rounded-full"
                                        >
                                            <img
                                                src="/icon-thumbs-3d.png"
                                                alt="Thumbs Up"
                                                className={`h-16 w-16 object-contain transition-all duration-300 ${fb.type === "positive"
                                                        ? "brightness-100 saturate-150 drop-shadow-lg scale-110"
                                                        : "brightness-75 opacity-60"
                                                    }`}
                                            />
                                        </button>
                                        <button
                                            onClick={() => setFeedbackType(feedbackModalItem.key, "negative")}
                                            className="transition-all duration-300 hover:scale-110 cursor-pointer p-2 rounded-full"
                                        >
                                            <img
                                                src="/icon-thumbsdown-3d.png"
                                                alt="Thumbs Down"
                                                className={`h-16 w-16 object-contain transition-all duration-300 ${fb.type === "negative"
                                                        ? "brightness-100 saturate-150 drop-shadow-lg scale-110"
                                                        : "brightness-75 opacity-60"
                                                    }`}
                                            />
                                        </button>
                                    </div>

                                    {/* Success Message */}
                                    {fb.submitted ? (
                                        <p className="text-xs text-green-500 text-center flex items-center justify-center gap-1 py-2">
                                            <span className="text-base">✓</span>
                                            {fb.response || "Thanks for your feedback!"}
                                        </p>
                                    ) : (
                                        <>
                                            {/* Comment Textarea */}
                                            <div className="space-y-2">
                                                <label className="text-sm font-medium text-muted-foreground">
                                                    Additional Comments (Optional)
                                                </label>
                                                <Textarea
                                                    value={fb.comment}
                                                    onChange={(e) => setFeedbackComment(feedbackModalItem.key, e.target.value)}
                                                    onKeyDown={handleFeedbackKeyDown}
                                                    className="form-glass-input rounded-xl min-h-[100px] transition-all duration-300 focus:ring-2 focus:ring-[#5FB3E6] resize-none"
                                                    placeholder="Tell us what you think..."
                                                    disabled={fb.loading}
                                                />
                                            </div>

                                            {/* Action Buttons */}
                                            <div className="flex gap-2 pt-1">
                                                <Button
                                                    type="button"
                                                    onClick={closeFeedbackModal}
                                                    variant="ghost"
                                                    disabled={fb.loading}
                                                    className="flex-1 rounded-xl py-2.5 text-muted-foreground hover:text-foreground"
                                                >
                                                    Cancel
                                                </Button>
                                                <Button
                                                    type="button"
                                                    onClick={submitFeedbackForItem}
                                                    disabled={fb.loading || (!fb.type && !fb.comment.trim())}
                                                    className={`flex-1 rounded-xl py-2.5 font-semibold transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${fb.loading || (!fb.type && !fb.comment.trim())
                                                        ? 'btn-glass-primary opacity-50 cursor-not-allowed'
                                                        : 'btn-glass-primary'
                                                        }`}
                                                >
                                                    {fb.loading ? (
                                                        <>
                                                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                                            Submitting...
                                                        </>
                                                    ) : (
                                                        "Submit Feedback"
                                                    )}
                                                </Button>
                                            </div>
                                        </>
                                    )}
                                </div>
                            );
                        })()}
                    </div>
                </div>
            )}

            {/* Download Solution Workflow Data Dialog */}
            <DownloadWorkflowDialog
                open={isDownloadDialogOpen}
                onOpenChange={setIsDownloadDialogOpen}
                exportParams={exportWorkflowParams}
            />
        </div>
    );
};

export default Project;
