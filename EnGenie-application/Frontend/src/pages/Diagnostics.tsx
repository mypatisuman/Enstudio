import { useState, useEffect, useRef } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import MainHeader from "@/components/MainHeader";
import { BASE_URL } from "@/components/AIRecommender/api";
import {
    Loader2, Activity, ArrowLeft, AlertTriangle, TrendingUp, Clock,
    CheckCircle, XCircle, BarChart3, RefreshCw, Radio, PlusCircle, Trash2,
    ToggleLeft, ToggleRight, Upload, Beaker, Heart, ShieldCheck,
} from "lucide-react";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";

// ── Types ──────────────────────────────────────────────────────────────────

interface AssetOption {
    _id: string;
    filename: string;
    entry_count?: number;
    health_score?: number;
    health_status?: string;
    trend_direction?: string;
    active_anomalies?: number;
    last_diagnostic_at?: string;
}

interface MonitorSource {
    _id: string;
    name: string;
    path: string;
    source_type: string;
    poll_interval: number;
    enabled: boolean;
    created_at: string;
    last_polled_at: string | null;
    total_entries_ingested: number;
    last_anomaly_count: number;
    last_error: string | null;
    asset_id?: string;
}

interface MonitorStatus {
    running: boolean;
    active_sources: number;
    total_sources: number;
}

interface DiagnosticStatistics {
    total_logs: number;
    by_type: Record<string, number>;
    by_severity: Record<string, number>;
    anomaly_count: number;
    instruments: { tag: string; log_count: number; last_reading: string | null }[];
    time_range_hours: number;
}

interface AnalysisResult {
    session_id: string;
    anomaly_detection: {
        total_analyzed: number;
        anomalies_detected: number;
        anomaly_rate_pct: number;
        anomalies: any[];
    };
    trend_analysis: Record<string, any>;
    matched_diagnostic_codes: any[];
    health?: {
        health_score: number;
        health_status: string;
        trend_direction: string;
        active_anomalies: number;
        factors: string[];
    };
}

interface DiagnosticSession {
    session_id: string;
    status: string;
    created_at: string;
    anomalies_detected: number;
    analysis_summary?: string;
    asset_id?: string;
}

interface SimulationResult {
    parameter: string;
    change_pct: number;
    scenario: string;
    simulated_health: {
        health_score: number;
        health_status: string;
        trend_direction: string;
        factors: string[];
    };
    anomaly_detection: { anomalies_detected: number; anomaly_rate_pct: number };
    trends: Record<string, any>;
    interpretation: string;
}

interface HealthHistoryEntry {
    timestamp: string;
    anomalies_detected: number;
    summary: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const getSeverityColor = (severity: string) => {
    switch (severity?.toLowerCase()) {
        case 'critical': case 'emergency': return 'bg-red-100 text-red-800 border-red-200';
        case 'warning': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
        default: return 'bg-blue-100 text-blue-800 border-blue-200';
    }
};

const getHealthColor = (status: string | undefined) => {
    switch (status) {
        case 'healthy': return 'text-green-600 bg-green-50 border-green-200';
        case 'warning': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
        case 'critical': return 'text-red-600 bg-red-50 border-red-200';
        default: return 'text-gray-500 bg-gray-50 border-gray-200';
    }
};

const getHealthBadge = (status: string | undefined) => {
    switch (status) {
        case 'healthy': return { dot: 'bg-green-500', text: 'Healthy' };
        case 'warning': return { dot: 'bg-yellow-500', text: 'Warning' };
        case 'critical': return { dot: 'bg-red-500', text: 'Critical' };
        default: return { dot: 'bg-gray-400', text: 'Unknown' };
    }
};

const fmt = (ts: string | null | undefined) => {
    if (!ts) return '\u2014';
    try { return new Date(ts).toLocaleString(); } catch { return ts; }
};

// ── Component ──────────────────────────────────────────────────────────────

const Diagnostics = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams] = useSearchParams();
    const { toast } = useToast();

    const getParentPath = () => location.state?.from ?? '/chat';

    // Pre-selected asset from URL (e.g., /diagnostics?asset_id=xxx)
    const preselectedAssetId = searchParams.get('asset_id') || '';

    // Tab state — asset-centric tabs
    const [activeTab, setActiveTab] = useState<'monitor' | 'analysis' | 'simulator' | 'history'>('analysis');

    // Asset selection
    const [assets, setAssets] = useState<AssetOption[]>([]);
    const [selectedAssetId, setSelectedAssetId] = useState(preselectedAssetId);

    // Loading flags
    const [loading, setLoading] = useState(true);
    const [analyzing, setAnalyzing] = useState(false);
    const [addingSource, setAddingSource] = useState(false);
    const [simulating, setSimulating] = useState(false);
    const [uploadingLogs, setUploadingLogs] = useState(false);

    // Data state
    const [monitorStatus, setMonitorStatus] = useState<MonitorStatus | null>(null);
    const [sources, setSources] = useState<MonitorSource[]>([]);
    const [statistics, setStatistics] = useState<DiagnosticStatistics | null>(null);
    const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
    const [sessions, setSessions] = useState<DiagnosticSession[]>([]);
    const [healthHistory, setHealthHistory] = useState<HealthHistoryEntry[]>([]);
    const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);

    // Add-source form
    const [showAddForm, setShowAddForm] = useState(false);
    const [newSource, setNewSource] = useState({ name: '', path: '', poll_interval: 30 });

    // Simulator form
    const [simForm, setSimForm] = useState({ parameter: '', change_pct: 10, description: '' });

    // File upload ref
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Auto-refresh
    const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // ── Fetchers ───────────────────────────────────────────────────────────

    const fetchAssets = async () => {
        try {
            const r = await fetch(`${BASE_URL}/api/assets-data`, { credentials: 'include' });
            if (!r.ok) return;
            const d = await r.json();
            if (!d.success) return;

            // Group by source document — we need document-level assets for the selector
            // The API returns flat rows, but we need document-level for asset_id
            // We'll use the MongoDB documents approach via a separate call
            // For now, build unique "asset documents" from the data
            const docsMap = new Map<string, AssetOption>();
            for (const row of d.data ?? []) {
                const key = row.source_file || 'unknown';
                if (!docsMap.has(key)) {
                    docsMap.set(key, {
                        _id: row._doc_id || key,
                        filename: key,
                        entry_count: 0,
                        health_score: row.health_score,
                        health_status: row.health_status,
                        trend_direction: row.trend_direction,
                        active_anomalies: row.active_anomalies,
                        last_diagnostic_at: row.last_diagnostic_at,
                    });
                }
                docsMap.get(key)!.entry_count = (docsMap.get(key)!.entry_count || 0) + 1;
            }
            setAssets(Array.from(docsMap.values()));
        } catch { /* ignore */ }
    };

    const fetchAll = async () => {
        await Promise.all([fetchAssets(), fetchStatus(), fetchSources(), fetchStatistics(), fetchSessions()]);
    };

    const fetchStatus = async () => {
        try {
            const r = await fetch(`${BASE_URL}/api/diagnostics/monitor/status`, { credentials: 'include' });
            if (r.ok) { const d = await r.json(); if (d.success) setMonitorStatus(d); }
        } catch { /* ignore */ }
    };

    const fetchSources = async () => {
        try {
            const r = await fetch(`${BASE_URL}/api/diagnostics/monitor/sources`, { credentials: 'include' });
            if (r.ok) { const d = await r.json(); if (d.success) setSources(d.sources ?? []); }
        } catch { /* ignore */ }
    };

    const fetchStatistics = async () => {
        try {
            const params = new URLSearchParams({ time_range_hours: '168' });
            if (selectedAssetId) params.set('asset_id', selectedAssetId);
            const r = await fetch(`${BASE_URL}/api/diagnostics/statistics?${params}`, { credentials: 'include' });
            if (r.ok) { const d = await r.json(); if (d.success) setStatistics(d); }
        } catch { /* ignore */ }
    };

    const fetchSessions = async () => {
        try {
            const r = await fetch(`${BASE_URL}/api/diagnostics/sessions?limit=20`, { credentials: 'include' });
            if (r.ok) { const d = await r.json(); if (d.success) setSessions(d.sessions ?? []); }
        } catch { /* ignore */ }
    };

    const fetchHealthHistory = async (assetId: string) => {
        if (!assetId) { setHealthHistory([]); return; }
        try {
            const r = await fetch(`${BASE_URL}/api/assets/${assetId}/health-history?limit=50`, { credentials: 'include' });
            if (r.ok) {
                const d = await r.json();
                if (d.success) setHealthHistory(d.history ?? []);
            }
        } catch { /* ignore */ }
    };

    // ── Lifecycle ──────────────────────────────────────────────────────────

    useEffect(() => {
        (async () => { setLoading(true); await fetchAll(); setLoading(false); })();
        refreshRef.current = setInterval(() => { fetchStatus(); fetchStatistics(); }, 60_000);
        return () => { if (refreshRef.current) clearInterval(refreshRef.current); };
    }, []);

    // Refresh stats when selected asset changes
    useEffect(() => {
        fetchStatistics();
        if (selectedAssetId) fetchHealthHistory(selectedAssetId);
    }, [selectedAssetId]);

    // ── Source management ──────────────────────────────────────────────────

    const handleAddSource = async () => {
        if (!newSource.name.trim() || !newSource.path.trim()) {
            toast({ title: 'Missing fields', description: 'Name and path are required.', variant: 'destructive' });
            return;
        }
        if (!selectedAssetId) {
            toast({ title: 'No asset selected', description: 'Select an asset from the dropdown first.', variant: 'destructive' });
            return;
        }
        setAddingSource(true);
        try {
            const r = await fetch(`${BASE_URL}/api/diagnostics/monitor/sources`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: newSource.name.trim(),
                    path: newSource.path.trim(),
                    poll_interval: newSource.poll_interval,
                    asset_id: selectedAssetId,
                }),
            });
            const d = await r.json();
            if (d.success) {
                toast({ title: 'Source added', description: `Monitoring started for "${newSource.name}"` });
                setNewSource({ name: '', path: '', poll_interval: 30 });
                setShowAddForm(false);
                await fetchSources(); fetchStatus();
            } else {
                toast({ title: 'Failed', description: d.error, variant: 'destructive' });
            }
        } catch (e: any) {
            toast({ title: 'Error', description: String(e), variant: 'destructive' });
        } finally { setAddingSource(false); }
    };

    const handleDeleteSource = async (id: string, name: string) => {
        if (!confirm(`Remove source "${name}" from monitoring?`)) return;
        try {
            const r = await fetch(`${BASE_URL}/api/diagnostics/monitor/sources/${id}`, {
                method: 'DELETE', credentials: 'include',
            });
            const d = await r.json();
            if (d.success) {
                toast({ title: 'Source removed' });
                await fetchSources(); fetchStatus();
            } else {
                toast({ title: 'Failed', description: d.error, variant: 'destructive' });
            }
        } catch (e: any) {
            toast({ title: 'Error', description: String(e), variant: 'destructive' });
        }
    };

    const handleToggleSource = async (id: string, enabled: boolean) => {
        try {
            const r = await fetch(`${BASE_URL}/api/diagnostics/monitor/sources/${id}/toggle`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled }),
            });
            const d = await r.json();
            if (d.success) {
                setSources(prev => prev.map(s => s._id === id ? { ...s, enabled } : s));
                fetchStatus();
            } else {
                toast({ title: 'Failed', description: d.error, variant: 'destructive' });
            }
        } catch (e: any) {
            toast({ title: 'Error', description: String(e), variant: 'destructive' });
        }
    };

    // ── Analysis ───────────────────────────────────────────────────────────

    const runAnalysis = async () => {
        setAnalyzing(true);
        setActiveTab('analysis');
        try {
            const body: any = { time_range_hours: 168 };
            if (selectedAssetId) body.asset_id = selectedAssetId;

            const r = await fetch(`${BASE_URL}/api/diagnostics/analyze`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const d = await r.json();
            if (d.success) {
                setAnalysisResult(d);
                toast({ title: 'Analysis complete', description: `${d.anomaly_detection?.anomalies_detected ?? 0} anomalies found` });
                await fetchSessions();
                if (selectedAssetId) fetchAssets(); // Refresh health scores
            } else {
                toast({ title: 'Analysis failed', description: d.error, variant: 'destructive' });
            }
        } catch (e: any) {
            toast({ title: 'Error', description: String(e), variant: 'destructive' });
        } finally { setAnalyzing(false); }
    };

    // ── Log Upload ─────────────────────────────────────────────────────────

    const handleUploadLogs = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file || !selectedAssetId) return;

        setUploadingLogs(true);
        try {
            const formData = new FormData();
            formData.append('file', file);

            const r = await fetch(`${BASE_URL}/api/assets/${selectedAssetId}/diagnostics/upload-logs`, {
                method: 'POST', credentials: 'include',
                body: formData,
            });
            const d = await r.json();
            if (d.success) {
                toast({ title: 'Logs uploaded', description: `${d.entries_ingested} entries ingested` });
                await fetchStatistics();
            } else {
                toast({ title: 'Upload failed', description: d.error, variant: 'destructive' });
            }
        } catch (e: any) {
            toast({ title: 'Error', description: String(e), variant: 'destructive' });
        } finally {
            setUploadingLogs(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    // ── Simulation ─────────────────────────────────────────────────────────

    const runSimulation = async () => {
        if (!selectedAssetId) {
            toast({ title: 'No asset selected', description: 'Select an asset to simulate.', variant: 'destructive' });
            return;
        }
        setSimulating(true);
        try {
            const r = await fetch(`${BASE_URL}/api/assets/${selectedAssetId}/simulate`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    parameter: simForm.parameter.trim(),
                    change_pct: simForm.change_pct,
                    description: simForm.description.trim(),
                }),
            });
            const d = await r.json();
            if (d.success) {
                setSimulationResult(d.simulation);
                toast({ title: 'Simulation complete' });
            } else {
                toast({ title: 'Simulation failed', description: d.error, variant: 'destructive' });
            }
        } catch (e: any) {
            toast({ title: 'Error', description: String(e), variant: 'destructive' });
        } finally { setSimulating(false); }
    };

    // ── Selected asset info ───────────────────────────────────────────────

    const selectedAsset = assets.find(a => a._id === selectedAssetId);

    // ── Render ─────────────────────────────────────────────────────────────

    return (
        <div className="flex flex-col h-screen app-glass-gradient text-foreground overflow-hidden">
            {/* Decorative background images */}
            <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
                <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
            </div>
            <MainHeader showProjectActions={false}>
                <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
                    <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#0F6CBD] to-[#004E8C]">
                        Asset Diagnostics
                    </h1>
                </div>
            </MainHeader>

            <main className="flex-1 pb-8 px-6 pt-28 overflow-y-auto custom-visible-scrollbar-dark">
                <div className="max-w-[95%] mx-auto">

                    {/* ── Top bar ── */}
                    <div className="flex items-center justify-between gap-3 mb-6">
                        <button
                            onClick={() => navigate(getParentPath(), { replace: true })}
                            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm"
                        >
                            <ArrowLeft className="w-5 h-5" />
                            <span className="font-medium">Back</span>
                        </button>

                        <div className="flex items-center gap-3">
                            {/* Asset selector */}
                            <select
                                value={selectedAssetId}
                                onChange={e => setSelectedAssetId(e.target.value)}
                                className="px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 min-w-[200px]"
                            >
                                <option value="">All Assets</option>
                                {assets.map(a => (
                                    <option key={a._id} value={a._id}>
                                        {a.filename} ({a.entry_count} entries)
                                        {a.health_status ? ` \u2022 ${a.health_status}` : ''}
                                    </option>
                                ))}
                            </select>

                            {/* Health badge for selected asset */}
                            {selectedAsset && selectedAsset.health_status && (
                                <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium border ${getHealthColor(selectedAsset.health_status)}`}>
                                    <span className={`w-2 h-2 rounded-full ${getHealthBadge(selectedAsset.health_status).dot}`} />
                                    {selectedAsset.health_score != null ? `${selectedAsset.health_score}%` : ''} {getHealthBadge(selectedAsset.health_status).text}
                                </div>
                            )}

                            {/* Monitoring status pill */}
                            {monitorStatus && (
                                <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium border ${
                                    monitorStatus.running && monitorStatus.active_sources > 0
                                        ? 'bg-green-50 text-green-700 border-green-200'
                                        : 'bg-gray-50 text-gray-500 border-gray-200'
                                }`}>
                                    <Radio className={`w-4 h-4 ${monitorStatus.running && monitorStatus.active_sources > 0 ? 'animate-pulse text-green-500' : 'text-gray-400'}`} />
                                    {monitorStatus.running && monitorStatus.active_sources > 0
                                        ? `${monitorStatus.active_sources} source${monitorStatus.active_sources !== 1 ? 's' : ''}`
                                        : 'No monitors'}
                                </div>
                            )}


                            {/* Run Analysis Button Removed */}

                            {/* Refresh */}
                            <button
                                onClick={fetchAll}
                                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm"
                            >
                                <RefreshCw className="w-5 h-5" />
                            </button>
                        </div>
                    </div>

                    {/* ── Stats chips ── */}
                    {!loading && statistics && (
                        <div className="mb-6 flex flex-wrap gap-3">
                            <div className="glass-card px-4 py-2 rounded-xl flex items-center gap-3">
                                <span className="text-xs font-medium text-gray-500">Total Logs</span>
                                <span className="font-bold text-gray-700 dark:text-gray-200">{statistics.total_logs}</span>
                            </div>
                            {Object.entries(statistics.by_severity ?? {}).map(([sev, count]) => (
                                <div key={sev} className="glass-card px-4 py-2 rounded-xl flex items-center gap-3">
                                    <span className={`px-2 py-0.5 rounded text-xs font-medium border ${getSeverityColor(sev)}`}>{sev.toUpperCase()}</span>
                                    <span className="font-bold text-gray-700 dark:text-gray-200">{count as number}</span>
                                </div>
                            ))}
                        </div>
                    )}



                    {/* ── Tab content ── */}
                    <div className="glass-card rounded-2xl p-6 shadow-lg">
                        {loading ? (
                            <div className="flex flex-col items-center justify-center py-20">
                                <Loader2 className="h-12 w-12 text-primary animate-spin mb-4" />
                                <p className="text-gray-600">Loading diagnostics data...</p>
                            </div>
                        ) : activeTab === 'monitor' ? (
                            <MonitorTab
                                assets={assets}
                                sources={sources}
                                selectedAssetId={selectedAssetId}
                                instruments={statistics?.instruments ?? []}
                                showAddForm={showAddForm}
                                setShowAddForm={setShowAddForm}
                                newSource={newSource}
                                setNewSource={setNewSource}
                                addingSource={addingSource}
                                onAdd={handleAddSource}
                                onDelete={handleDeleteSource}
                                onToggle={handleToggleSource}
                            />
                        ) : activeTab === 'analysis' ? (
                            <AnalysisTab
                                result={analysisResult}
                                analyzing={analyzing}
                                onRunAnalysis={runAnalysis}
                                selectedAssetId={selectedAssetId}
                            />
                        ) : activeTab === 'simulator' ? (
                            <SimulatorTab
                                selectedAssetId={selectedAssetId}
                                selectedAsset={selectedAsset}
                                simForm={simForm}
                                setSimForm={setSimForm}
                                simulating={simulating}
                                onSimulate={runSimulation}
                                result={simulationResult}
                                instruments={statistics?.instruments ?? []}
                            />
                        ) : (
                            <HistoryTab
                                sessions={sessions}
                                healthHistory={healthHistory}
                                selectedAssetId={selectedAssetId}
                                selectedAsset={selectedAsset}
                            />
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
};

// ── Sub-components ─────────────────────────────────────────────────────────

function MonitorTab({
    assets, sources, selectedAssetId, instruments,
    showAddForm, setShowAddForm, newSource, setNewSource,
    addingSource, onAdd, onDelete, onToggle,
}: {
    assets: AssetOption[];
    sources: MonitorSource[];
    selectedAssetId: string;
    instruments: { tag: string; log_count: number; last_reading: string | null }[];
    showAddForm: boolean;
    setShowAddForm: (v: boolean) => void;
    newSource: { name: string; path: string; poll_interval: number };
    setNewSource: (v: any) => void;
    addingSource: boolean;
    onAdd: () => void;
    onDelete: (id: string, name: string) => void;
    onToggle: (id: string, enabled: boolean) => void;
}) {
    // Filter sources by selected asset
    const filteredSources = selectedAssetId
        ? sources.filter(s => s.asset_id === selectedAssetId)
        : sources;

    return (
        <div>
            {/* Asset Health Overview */}
            {assets.length > 0 && (
                <div className="mb-6">
                    <h3 className="text-lg font-bold text-gray-800 dark:text-gray-200 mb-4 flex items-center gap-2">
                        <Heart className="w-5 h-5 text-[#0F6CBD]" /> Asset Health Overview
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {assets.map(asset => {
                            const badge = getHealthBadge(asset.health_status);
                            return (
                                <div
                                    key={asset._id}
                                    className={`p-4 rounded-xl border transition-all cursor-pointer ${
                                        selectedAssetId === asset._id
                                            ? 'border-[#0F6CBD] bg-blue-50/30 dark:bg-blue-900/10 ring-2 ring-[#0F6CBD]/30'
                                            : 'border-gray-200 dark:border-slate-700 bg-white/50 dark:bg-slate-800/30 hover:border-gray-300'
                                    }`}
                                >
                                    <div className="flex items-start justify-between">
                                        <div className="flex-1 min-w-0">
                                            <p className="font-semibold text-gray-800 dark:text-gray-200 truncate">{asset.filename}</p>
                                            <p className="text-xs text-gray-500 mt-1">{asset.entry_count} entries</p>
                                        </div>
                                        <div className="flex flex-col items-end gap-1">
                                            <div className="flex items-center gap-1.5">
                                                <span className={`w-2 h-2 rounded-full ${badge.dot}`} />
                                                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">{badge.text}</span>
                                            </div>
                                            {asset.health_score != null && (
                                                <span className="text-lg font-bold text-gray-800 dark:text-gray-200">{asset.health_score}%</span>
                                            )}
                                        </div>
                                    </div>
                                    {asset.last_diagnostic_at && (
                                        <p className="text-xs text-gray-400 mt-2">Last checked: {fmt(asset.last_diagnostic_at)}</p>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Instruments for selected asset */}
            {instruments.length > 0 && (
                <div className="mb-6">
                    <h3 className="text-lg font-bold text-gray-800 dark:text-gray-200 mb-4 flex items-center gap-2">
                        <Activity className="w-5 h-5 text-[#0F6CBD]" /> Monitored Instruments
                        {selectedAssetId && <span className="text-sm font-normal text-gray-500">(filtered by selected asset)</span>}
                    </h3>
                    <div className="rounded-xl border border-gray-200/50 overflow-hidden">
                        <Table>
                            <TableHeader>
                                <TableRow className="bg-gradient-to-r from-[#0F6CBD]/20 to-[#5FB3E6]/20">
                                    <TableHead className="font-bold text-[#0F6CBD]">Tag Number</TableHead>
                                    <TableHead className="font-bold text-[#0F6CBD]">Log Count</TableHead>
                                    <TableHead className="font-bold text-[#0F6CBD]">Last Reading</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {instruments.map((inst, i) => (
                                    <TableRow key={i} className="hover:bg-gray-50 dark:hover:bg-slate-800/50">
                                        <TableCell className="font-mono font-medium text-gray-800 dark:text-gray-200">{inst.tag}</TableCell>
                                        <TableCell>
                                            <span className="px-2 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-md text-sm font-medium">
                                                {inst.log_count}
                                            </span>
                                        </TableCell>
                                        <TableCell className="text-gray-600 dark:text-gray-400 text-sm">{fmt(inst.last_reading)}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                </div>
            )}

            {/* Monitor Sources */}
            <div>
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-bold text-gray-800 dark:text-gray-200 flex items-center gap-2">
                        <Radio className="w-5 h-5 text-[#0F6CBD]" /> Log Monitor Sources
                    </h3>
                    <button
                        onClick={() => setShowAddForm(!showAddForm)}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#0F6CBD] hover:bg-[#0a5a9e] text-white text-sm transition-all"
                    >
                        <PlusCircle className="w-4 h-4" /> Add Source
                    </button>
                </div>

                {/* Add form */}
                {showAddForm && (
                    <div className="mb-6 p-4 rounded-xl border border-[#0F6CBD]/30 bg-blue-50/50 dark:bg-blue-900/10">
                        <h4 className="font-semibold text-gray-800 dark:text-gray-200 mb-3">Add Monitor Source for Selected Asset</h4>
                        {!selectedAssetId && (
                            <p className="text-sm text-amber-600 mb-3">Select an asset from the dropdown above first.</p>
                        )}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div>
                                <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1 block">Source Name *</label>
                                <input
                                    type="text" placeholder="e.g. Reactor A \u2014 PI Historian"
                                    value={newSource.name}
                                    onChange={e => setNewSource({ ...newSource, name: e.target.value })}
                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50"
                                />
                            </div>
                            <div>
                                <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1 block">Server File Path *</label>
                                <input
                                    type="text" placeholder="e.g. /data/logs/reactor_a.csv"
                                    value={newSource.path}
                                    onChange={e => setNewSource({ ...newSource, path: e.target.value })}
                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50"
                                />
                            </div>
                            <div>
                                <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1 block">Poll Interval (sec)</label>
                                <input
                                    type="number" min={10}
                                    value={newSource.poll_interval}
                                    onChange={e => setNewSource({ ...newSource, poll_interval: Math.max(10, parseInt(e.target.value) || 30) })}
                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50"
                                />
                            </div>
                        </div>
                        <div className="flex gap-2 mt-4">
                            <button
                                onClick={onAdd}
                                disabled={addingSource || !selectedAssetId}
                                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#0F6CBD] hover:bg-[#0a5a9e] text-white text-sm transition-all disabled:opacity-50"
                            >
                                {addingSource ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlusCircle className="w-4 h-4" />}
                                Start Monitoring
                            </button>
                            <button
                                onClick={() => setShowAddForm(false)}
                                className="px-4 py-2 rounded-lg bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-gray-300 text-sm hover:bg-gray-200 dark:hover:bg-slate-600 transition-all"
                            >
                                Cancel
                            </button>
                        </div>
                    </div>
                )}

                {/* Sources list */}
                {filteredSources.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12">
                        <Radio className="h-10 w-10 text-gray-400 mb-3" />
                        <p className="text-gray-600 font-medium">No monitor sources{selectedAssetId ? ' for this asset' : ''}</p>
                        <p className="text-sm text-gray-500 mt-1">Add a log source to begin continuous monitoring</p>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {filteredSources.map(src => (
                            <div key={src._id} className={`p-4 rounded-xl border transition-all ${
                                src.enabled
                                    ? 'border-green-200 dark:border-green-800 bg-green-50/30 dark:bg-green-900/10'
                                    : 'border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50'
                            }`}>
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <Radio className={`w-4 h-4 flex-shrink-0 ${src.enabled ? 'text-green-500 animate-pulse' : 'text-gray-400'}`} />
                                            <span className="font-semibold text-gray-800 dark:text-gray-200 truncate">{src.name}</span>
                                            {src.last_anomaly_count > 0 && (
                                                <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 border border-red-200 flex-shrink-0">
                                                    {src.last_anomaly_count} anomalies
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-xs font-mono text-gray-500 dark:text-gray-400 truncate ml-6">{src.path}</p>
                                        <div className="flex gap-4 mt-2 ml-6 text-xs text-gray-500">
                                            <span>Every {src.poll_interval}s</span>
                                            <span>{src.total_entries_ingested} entries</span>
                                            <span>Last: {fmt(src.last_polled_at)}</span>
                                        </div>
                                        {src.last_error && <p className="text-xs text-red-500 mt-1 ml-6">{src.last_error}</p>}
                                    </div>
                                    <div className="flex items-center gap-2 flex-shrink-0">
                                        <button onClick={() => onToggle(src._id, !src.enabled)} title={src.enabled ? 'Pause' : 'Resume'} className="text-gray-500 hover:text-[#0F6CBD] transition-colors">
                                            {src.enabled ? <ToggleRight className="w-6 h-6 text-green-500" /> : <ToggleLeft className="w-6 h-6 text-gray-400" />}
                                        </button>
                                        <button onClick={() => onDelete(src._id, src.name)} title="Remove" className="text-gray-400 hover:text-red-500 transition-colors">
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

function AnalysisTab({ result, analyzing, onRunAnalysis, selectedAssetId }: {
    result: AnalysisResult | null; analyzing: boolean; onRunAnalysis: () => void; selectedAssetId: string;
}) {
    if (!result) {
        return (
            <div className="flex flex-col items-center justify-center py-20">
                <BarChart3 className="h-12 w-12 text-gray-400 mb-4" />
                <p className="text-gray-600 font-medium">No analysis results yet</p>
                <p className="text-sm text-gray-500 mt-2">
                    Select an asset to view diagnostics history.
                </p>
                {/* Run Analysis Button Removed */}
            </div>
        );
    }

    const det = result.anomaly_detection;
    const health = result.health;

    return (
        <div>
            {/* Health Score Card (if available) */}
            {health && (
                <div className={`mb-6 p-4 rounded-xl border ${getHealthColor(health.health_status)}`}>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <ShieldCheck className="w-6 h-6" />
                            <div>
                                <p className="text-sm font-medium">Asset Health Score</p>
                                <p className="text-3xl font-bold">{health.health_score}%</p>
                            </div>
                        </div>
                        <div className="text-right">
                            <p className="text-sm">{getHealthBadge(health.health_status).text}</p>
                            <p className="text-xs mt-1">Trend: {health.trend_direction}</p>
                        </div>
                    </div>
                    {health.factors.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-current/10">
                            <p className="text-xs font-medium mb-1">Factors:</p>
                            {health.factors.map((f, i) => (
                                <p key={i} className="text-xs">{f}</p>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Anomaly Detection Summary */}
            <div className="mb-6 p-4 rounded-xl bg-gradient-to-r from-red-50 to-orange-50 dark:from-red-900/20 dark:to-orange-900/20 border border-red-200 dark:border-red-800">
                <h3 className="text-lg font-bold text-red-800 dark:text-red-300 mb-3 flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5" /> Anomaly Detection Results
                </h3>
                <div className="grid grid-cols-3 gap-4">
                    <div><p className="text-sm text-gray-600 dark:text-gray-400">Analyzed</p><p className="text-xl font-bold text-gray-800 dark:text-gray-200">{det.total_analyzed}</p></div>
                    <div><p className="text-sm text-gray-600 dark:text-gray-400">Anomalies</p><p className="text-xl font-bold text-red-600">{det.anomalies_detected}</p></div>
                    <div><p className="text-sm text-gray-600 dark:text-gray-400">Rate</p><p className="text-xl font-bold text-orange-600">{det.anomaly_rate_pct}%</p></div>
                </div>
            </div>

            {/* Anomaly list */}
            {det.anomalies.length > 0 && (
                <div className="mb-6">
                    <h4 className="text-md font-bold text-gray-700 dark:text-gray-300 mb-3">Detected Anomalies</h4>
                    <div className="space-y-2 max-h-72 overflow-y-auto custom-visible-scrollbar-dark">
                        {det.anomalies.slice(0, 20).map((a, i) => (
                            <div key={i} className="p-3 rounded-lg bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800">
                                <div className="flex items-center justify-between">
                                    <span className="font-mono font-medium text-gray-800 dark:text-gray-200">{a.tag_number}</span>
                                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 border border-red-200">{a.anomaly_type?.toUpperCase()}</span>
                                </div>
                                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">Value: {a.value} \u00b7 Score: {(a.anomaly_score * 100).toFixed(1)}%</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Trend analysis */}
            {Object.keys(result.trend_analysis ?? {}).length > 0 && (
                <div>
                    <h4 className="text-md font-bold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2"><TrendingUp className="w-4 h-4" /> Trend Analysis</h4>
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                        {Object.entries(result.trend_analysis).map(([tag, trend]: [string, any]) => (
                            <div key={tag} className="p-3 rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700">
                                <p className="font-mono text-sm font-medium text-gray-800 dark:text-gray-200">{tag}</p>
                                <p className={`text-sm font-medium mt-1 ${
                                    trend.trend === 'stable' ? 'text-green-600' :
                                    trend.trend?.includes('increasing') ? 'text-orange-600' :
                                    trend.trend?.includes('decreasing') ? 'text-blue-600' : 'text-gray-600'
                                }`}>{trend.trend?.replace('_', ' ').toUpperCase()}</p>
                                <p className="text-xs text-gray-500 mt-1">Mean: {trend.mean?.toFixed(2)} \u00b7 Std: {trend.std?.toFixed(2)}</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

function SimulatorTab({
    selectedAssetId, selectedAsset, simForm, setSimForm,
    simulating, onSimulate, result, instruments,
}: {
    selectedAssetId: string;
    selectedAsset: AssetOption | undefined;
    simForm: { parameter: string; change_pct: number; description: string };
    setSimForm: (v: any) => void;
    simulating: boolean;
    onSimulate: () => void;
    result: SimulationResult | null;
    instruments: { tag: string; log_count: number; last_reading: string | null }[];
}) {
    if (!selectedAssetId) {
        return (
            <div className="flex flex-col items-center justify-center py-20">
                <Beaker className="h-12 w-12 text-gray-400 mb-4" />
                <p className="text-gray-600 font-medium">Select an asset to simulate</p>
                <p className="text-sm text-gray-500 mt-2">Choose an asset from the dropdown above to run what-if scenarios</p>
            </div>
        );
    }

    return (
        <div>
            <h3 className="text-lg font-bold text-gray-800 dark:text-gray-200 mb-4 flex items-center gap-2">
                <Beaker className="w-5 h-5 text-[#0F6CBD]" /> What-If Simulation
            </h3>
            <p className="text-sm text-gray-500 mb-4">
                Simulate parameter changes and predict how they affect asset health. Select an instrument tag and apply a percentage change.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <div>
                    <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1 block">Instrument Tag</label>
                    <select
                        value={simForm.parameter}
                        onChange={e => setSimForm({ ...simForm, parameter: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50"
                    >
                        <option value="">All instruments</option>
                        {instruments.map(inst => (
                            <option key={inst.tag} value={inst.tag}>{inst.tag} ({inst.log_count} readings)</option>
                        ))}
                    </select>
                </div>
                <div>
                    <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1 block">Change (%)</label>
                    <input
                        type="number"
                        value={simForm.change_pct}
                        onChange={e => setSimForm({ ...simForm, change_pct: parseFloat(e.target.value) || 0 })}
                        className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50"
                        placeholder="+10 or -15"
                    />
                </div>
                <div>
                    <label className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1 block">Scenario Description</label>
                    <input
                        type="text"
                        value={simForm.description}
                        onChange={e => setSimForm({ ...simForm, description: e.target.value })}
                        placeholder="e.g. Pressure increase due to valve closure"
                        className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-800 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50"
                    />
                </div>
            </div>

            <button
                onClick={onSimulate}
                disabled={simulating}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#0F6CBD] hover:bg-[#0a5a9e] text-white transition-all disabled:opacity-50 mb-6"
            >
                {simulating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Beaker className="w-4 h-4" />}
                Run Simulation
            </button>

            {/* Simulation Results */}
            {result && (
                <div className="space-y-4">
                    {/* Health comparison */}
                    <div className="grid grid-cols-2 gap-4">
                        <div className="p-4 rounded-xl border border-gray-200 dark:border-slate-700 bg-white/50 dark:bg-slate-800/30">
                            <p className="text-xs font-medium text-gray-500 mb-1">Current Health</p>
                            <p className="text-2xl font-bold text-gray-800 dark:text-gray-200">
                                {selectedAsset?.health_score != null ? `${selectedAsset.health_score}%` : 'N/A'}
                            </p>
                            <p className="text-xs text-gray-500">{getHealthBadge(selectedAsset?.health_status).text}</p>
                        </div>
                        <div className={`p-4 rounded-xl border ${getHealthColor(result.simulated_health.health_status)}`}>
                            <p className="text-xs font-medium mb-1">Simulated Health ({result.change_pct >= 0 ? '+' : ''}{result.change_pct}%)</p>
                            <p className="text-2xl font-bold">{result.simulated_health.health_score}%</p>
                            <p className="text-xs">{getHealthBadge(result.simulated_health.health_status).text}</p>
                        </div>
                    </div>

                    {/* LLM Interpretation */}
                    <div className="p-4 rounded-xl bg-blue-50/50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800">
                        <h4 className="text-sm font-bold text-blue-800 dark:text-blue-300 mb-2">Assessment</h4>
                        <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{result.interpretation}</p>
                    </div>

                    {/* Simulation factors */}
                    {result.simulated_health.factors.length > 0 && (
                        <div className="p-3 rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700">
                            <p className="text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">Impact Factors:</p>
                            {result.simulated_health.factors.map((f, i) => (
                                <p key={i} className="text-xs text-gray-600 dark:text-gray-400">{f}</p>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

function HistoryTab({ sessions, healthHistory, selectedAssetId, selectedAsset }: {
    sessions: DiagnosticSession[];
    healthHistory: HealthHistoryEntry[];
    selectedAssetId: string;
    selectedAsset: AssetOption | undefined;
}) {
    const filteredSessions = selectedAssetId
        ? sessions.filter(s => s.asset_id === selectedAssetId)
        : sessions;

    return (
        <div>
            {/* Health History */}
            {selectedAssetId && healthHistory.length > 0 && (
                <div className="mb-6">
                    <h3 className="text-lg font-bold text-gray-800 dark:text-gray-200 mb-4 flex items-center gap-2">
                        <Heart className="w-5 h-5 text-[#0F6CBD]" /> Health Timeline
                        {selectedAsset && <span className="text-sm font-normal text-gray-500">({selectedAsset.filename})</span>}
                    </h3>
                    <div className="space-y-2 max-h-60 overflow-y-auto custom-visible-scrollbar-dark">
                        {healthHistory.map((entry, i) => (
                            <div key={i} className="flex items-center gap-4 p-3 rounded-lg bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700">
                                <div className="text-xs text-gray-500 w-36 flex-shrink-0">{fmt(entry.timestamp)}</div>
                                <div className="flex-1">
                                    <p className="text-sm text-gray-700 dark:text-gray-300">{entry.summary}</p>
                                </div>
                                {entry.anomalies_detected > 0 && (
                                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 border border-red-200 flex-shrink-0">
                                        {entry.anomalies_detected} anomalies
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Diagnostic Sessions */}
            <h3 className="text-lg font-bold text-gray-800 dark:text-gray-200 mb-4 flex items-center gap-2">
                <Clock className="w-5 h-5 text-[#0F6CBD]" /> Diagnostic Sessions
                {selectedAssetId && <span className="text-sm font-normal text-gray-500">(filtered)</span>}
            </h3>

            {filteredSessions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12">
                    <Clock className="h-10 w-10 text-gray-400 mb-3" />
                    <p className="text-gray-600 font-medium">No diagnostic sessions{selectedAssetId ? ' for this asset' : ''}</p>
                    <p className="text-sm text-gray-500 mt-1">Run an analysis to create a session</p>
                </div>
            ) : (
                <div className="space-y-3">
                    {filteredSessions.map(s => (
                        <div key={s.session_id} className="p-4 rounded-xl bg-gray-50 dark:bg-slate-800/50 border border-gray-200 dark:border-slate-700">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    {s.status === 'completed' ? <CheckCircle className="w-5 h-5 text-green-500" /> :
                                     s.status === 'failed' ? <XCircle className="w-5 h-5 text-red-500" /> :
                                     <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />}
                                    <div>
                                        <p className="font-mono text-sm text-gray-600 dark:text-gray-400">{s.session_id.slice(0, 8)}...</p>
                                        <p className="text-xs text-gray-500">{fmt(s.created_at)}</p>
                                    </div>
                                </div>
                                <div className="text-right">
                                    <span className={`px-2 py-1 rounded-md text-xs font-medium ${
                                        s.status === 'completed' ? 'bg-green-100 text-green-800' :
                                        s.status === 'failed' ? 'bg-red-100 text-red-800' : 'bg-blue-100 text-blue-800'
                                    }`}>{s.status}</span>
                                    {s.anomalies_detected > 0 && <p className="text-sm text-red-600 mt-1">{s.anomalies_detected} anomalies</p>}
                                </div>
                            </div>
                            {s.analysis_summary && (
                                <p className="text-sm text-gray-600 dark:text-gray-400 mt-2 pt-2 border-t border-gray-200 dark:border-slate-600">{s.analysis_summary}</p>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default Diagnostics;
