import React, { useState, useEffect, useRef } from "react";
import {
    Activity,
    AlertCircle,
    ArrowRight,
    CheckCircle2,
    ChevronDown,
    ChevronRight,
    Cpu,
    Download,
    FileCode,
    FileSpreadsheet,
    Layers,
    Link2,
    Loader2,
    Radio,
    RefreshCw,
    Sliders,
    SlidersHorizontal,
    Workflow,
    X,
    Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import {
    inferExperionStrategy,
    exportControlBuilderXml,
    exportPointBuilderCsv,
    connectExperionOpc,
    getExperionOpcTags,
    writeExperionOpcTag,
} from "@/components/AIRecommender/api";

interface ExperionStudioDrawerProps {
    isOpen: boolean;
    onClose: () => void;
    pidGraph: any;
    solutionTitle?: string;
}

export const ExperionStudioDrawer: React.FC<ExperionStudioDrawerProps> = ({
    isOpen,
    onClose,
    pidGraph,
    solutionTitle,
}) => {
    const { toast } = useToast();

    // Strategy state
    const [strategy, setStrategy] = useState<any | null>(null);
    const [inferring, setInferring] = useState<boolean>(false);
    const [controllerName, setControllerName] = useState<string>("CEE01_C300");
    const [activeTab, setActiveTab] = useState<"modules" | "opc" | "export">("modules");
    const [selectedCmName, setSelectedCmName] = useState<string | null>(null);

    // Export loading state
    const [exportingXml, setExportingXml] = useState<boolean>(false);
    const [exportingCsv, setExportingCsv] = useState<boolean>(false);

    // OPC UA Live state
    const [opcEndpoint, setOpcEndpoint] = useState<string>("opc.tcp://localhost:4840");
    const [isOpcConnected, setIsOpcConnected] = useState<boolean>(false);
    const [isConnectingOpc, setIsConnectingOpc] = useState<boolean>(false);
    const [opcTags, setOpcTags] = useState<Record<string, any>>({});
    const [pollingActive, setPollingActive] = useState<boolean>(false);
    const pollingTimerRef = useRef<any>(null);

    // Run inference whenever drawer opens with new pidGraph
    useEffect(() => {
        if (isOpen && pidGraph && (!strategy || strategy.target_controller !== controllerName)) {
            handleInfer();
        }
    }, [isOpen, pidGraph, controllerName]);

    // Cleanup polling on unmount
    useEffect(() => {
        return () => {
            if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
        };
    }, []);

    const handleInfer = async () => {
        if (!pidGraph) return;
        setInferring(true);
        try {
            const res = await inferExperionStrategy(pidGraph, controllerName);
            if (res.success && res.strategy) {
                setStrategy(res.strategy);
                if (res.strategy.control_modules?.length > 0 && !selectedCmName) {
                    setSelectedCmName(res.strategy.control_modules[0].cm_name);
                }
            } else {
                toast({
                    title: "Experion Inference Error",
                    description: res.error || "Failed to parse loops for Experion DCS",
                    variant: "destructive",
                });
            }
        } catch (err: any) {
            toast({
                title: "Inference Failed",
                description: err.message,
                variant: "destructive",
            });
        } finally {
            setInferring(false);
        }
    };

    const handleExportXml = async () => {
        if (!strategy) return;
        setExportingXml(true);
        try {
            await exportControlBuilderXml(strategy);
            toast({
                title: "Control Builder XML Exported",
                description: "Honeywell C300 CEE strategy XML ready for import into Control Builder.",
            });
        } catch (err: any) {
            toast({
                title: "XML Export Failed",
                description: err.message,
                variant: "destructive",
            });
        } finally {
            setExportingXml(false);
        }
    };

    const handleExportCsv = async () => {
        if (!strategy) return;
        setExportingCsv(true);
        try {
            await exportPointBuilderCsv(strategy);
            toast({
                title: "Point Builder CSV Exported",
                description: "Honeywell Point Builder / Quick Builder tag database downloaded.",
            });
        } catch (err: any) {
            toast({
                title: "CSV Export Failed",
                description: err.message,
                variant: "destructive",
            });
        } finally {
            setExportingCsv(false);
        }
    };

    // OPC Connect / Toggle
    const handleToggleOpc = async () => {
        if (isOpcConnected) {
            if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
            setIsOpcConnected(false);
            setPollingActive(false);
            toast({ title: "OPC UA Disconnected" });
            return;
        }

        setIsConnectingOpc(true);
        try {
            const res = await connectExperionOpc({
                endpoint_url: opcEndpoint,
                simulation_mode: true,
            });
            if (res.connected) {
                setIsOpcConnected(true);
                setPollingActive(true);
                toast({
                    title: "Connected to Experion OPC UA",
                    description: "Virtual C300 CEE controller session established.",
                });
                startTagPolling();
            }
        } catch (err: any) {
            toast({
                title: "OPC Connection Failed",
                description: err.message,
                variant: "destructive",
            });
        } finally {
            setIsConnectingOpc(false);
        }
    };

    const startTagPolling = () => {
        if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
        const poll = async () => {
            try {
                const res = await getExperionOpcTags();
                if (res.success && res.tags) {
                    const tagMap: Record<string, any> = {};
                    res.tags.forEach((t: any) => {
                        tagMap[t.tag] = t;
                    });
                    setOpcTags(tagMap);
                }
            } catch (e) {
                console.error("Polling error:", e);
            }
        };
        poll();
        pollingTimerRef.current = setInterval(poll, 1000);
    };

    const handleWriteParam = async (
        cmName: string,
        blockTag: string,
        param: string,
        val: any
    ) => {
        try {
            const res = await writeExperionOpcTag(cmName, blockTag, param, val);
            if (res.success) {
                toast({
                    title: "Experion Parameter Written",
                    description: `${blockTag}.${param} = ${val}`,
                });
                // Update local tag map immediately
                setOpcTags((prev) => ({
                    ...prev,
                    [`${blockTag}.${param}`]: {
                        ...(prev[`${blockTag}.${param}`] || {}),
                        value: val,
                    },
                }));
            }
        } catch (e: any) {
            toast({
                title: "Write Failed",
                description: e.message,
                variant: "destructive",
            });
        }
    };

    if (!isOpen) return null;

    const controlModules = strategy?.control_modules || [];
    const selectedCm = controlModules.find((cm: any) => cm.cm_name === selectedCmName) || controlModules[0];

    return (
        <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-4xl shadow-2xl transition-all duration-300">
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity"
                onClick={onClose}
            />

            {/* Main Drawer Window */}
            <div className="relative flex flex-col w-full h-full bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 z-10 overflow-hidden shadow-2xl">
                {/* ── Header ── */}
                <div className="flex items-center justify-between px-6 py-4 bg-gradient-to-r from-[#0F6CBD]/10 via-transparent to-transparent border-b border-slate-200 dark:border-slate-800">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#0F6CBD] to-[#115EA3] flex items-center justify-center text-white shadow-md shadow-[#0F6CBD]/20">
                            <Workflow className="h-5 w-5" />
                        </div>
                        <div>
                            <div className="flex items-center gap-2">
                                <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
                                    Honeywell Experion PKS Integration
                                </h2>
                                <Badge
                                    variant="outline"
                                    className="text-[11px] font-semibold bg-blue-50 text-[#0F6CBD] border-[#0F6CBD]/30 dark:bg-blue-950/40 dark:text-blue-300"
                                >
                                    C300 CEE
                                </Badge>
                            </div>
                            <p className="text-xs text-slate-500 dark:text-slate-400">
                                Inferred DCS Control Strategy &amp; CEE Execution Environment
                            </p>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={handleInfer}
                            disabled={inferring}
                            className="h-8 gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-200 border-slate-200 dark:border-slate-700"
                        >
                            <RefreshCw className={`h-3.5 w-3.5 ${inferring ? "animate-spin" : ""}`} />
                            Re-Infer
                        </Button>
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={onClose}
                            className="h-8 w-8 text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
                        >
                            <X className="h-4 w-4" />
                        </Button>
                    </div>
                </div>

                {/* ── Controller & Stats Ribbon ── */}
                <div className="grid grid-cols-4 gap-3 px-6 py-3 bg-slate-50 dark:bg-slate-800/40 border-b border-slate-200 dark:border-slate-800">
                    <div className="flex flex-col">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Controller</span>
                        <div className="flex items-center gap-1.5 mt-0.5">
                            <Cpu className="h-3.5 w-3.5 text-[#0F6CBD]" />
                            <span className="text-xs font-bold text-slate-900 dark:text-slate-100">
                                {strategy?.target_controller || controllerName}
                            </span>
                        </div>
                    </div>

                    <div className="flex flex-col">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Control Modules</span>
                        <div className="flex items-center gap-1.5 mt-0.5">
                            <Layers className="h-3.5 w-3.5 text-indigo-500" />
                            <span className="text-xs font-bold text-slate-900 dark:text-slate-100">
                                {strategy?.total_loops ?? controlModules.length} Modules
                            </span>
                        </div>
                    </div>

                    <div className="flex flex-col">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Function Blocks</span>
                        <div className="flex items-center gap-1.5 mt-0.5">
                            <Zap className="h-3.5 w-3.5 text-amber-500" />
                            <span className="text-xs font-bold text-slate-900 dark:text-slate-100">
                                {strategy?.total_blocks ?? 0} CEE Blocks
                            </span>
                        </div>
                    </div>

                    <div className="flex flex-col">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">I/O Channels</span>
                        <div className="flex items-center gap-1.5 mt-0.5">
                            <Radio className="h-3.5 w-3.5 text-emerald-500" />
                            <span className="text-xs font-bold text-slate-900 dark:text-slate-100">
                                {strategy?.total_io_points ?? 0} Points
                            </span>
                        </div>
                    </div>
                </div>

                {/* ── Sub Navigation Tabs ── */}
                <div className="flex border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6">
                    <button
                        onClick={() => setActiveTab("modules")}
                        className={`flex items-center gap-2 py-3 px-4 text-xs font-bold border-b-2 transition-all cursor-pointer ${
                            activeTab === "modules"
                                ? "border-[#0F6CBD] text-[#0F6CBD] dark:border-[#5FB3E6] dark:text-[#5FB3E6]"
                                : "border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-300"
                        }`}
                    >
                        <Layers className="h-4 w-4" />
                        Control Modules ({controlModules.length})
                    </button>

                    <button
                        onClick={() => setActiveTab("opc")}
                        className={`flex items-center gap-2 py-3 px-4 text-xs font-bold border-b-2 transition-all cursor-pointer ${
                            activeTab === "opc"
                                ? "border-[#0F6CBD] text-[#0F6CBD] dark:border-[#5FB3E6] dark:text-[#5FB3E6]"
                                : "border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-300"
                        }`}
                    >
                        <Radio className="h-4 w-4" />
                        OPC UA &amp; Loop Test
                        {isOpcConnected && (
                            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                        )}
                    </button>

                    <button
                        onClick={() => setActiveTab("export")}
                        className={`flex items-center gap-2 py-3 px-4 text-xs font-bold border-b-2 transition-all cursor-pointer ${
                            activeTab === "export"
                                ? "border-[#0F6CBD] text-[#0F6CBD] dark:border-[#5FB3E6] dark:text-[#5FB3E6]"
                                : "border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-300"
                        }`}
                    >
                        <Download className="h-4 w-4" />
                        Experion Export Center
                    </button>
                </div>

                {/* ── Tab Body ── */}
                <div className="flex-1 overflow-y-auto p-6 bg-slate-50/50 dark:bg-slate-950/50 custom-visible-scrollbar">
                    {inferring ? (
                        <div className="flex flex-col items-center justify-center h-64 gap-3">
                            <Loader2 className="h-8 w-8 text-[#0F6CBD] animate-spin" />
                            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                                Inferring Experion C300 Control Strategies from P&amp;ID...
                            </p>
                        </div>
                    ) : activeTab === "modules" ? (
                        /* ── TAB 1: Control Modules & Block Inspector ── */
                        <div className="grid grid-cols-12 gap-6 h-full">
                            {/* Left: CM List */}
                            <div className="col-span-4 space-y-2">
                                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                                    Inferred Modules
                                </h3>
                                <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                                    {controlModules.map((cm: any) => {
                                        const isSelected = cm.cm_name === selectedCm?.cm_name;
                                        return (
                                            <button
                                                key={cm.cm_name}
                                                onClick={() => setSelectedCmName(cm.cm_name)}
                                                className={`w-full text-left p-3 rounded-xl border transition-all cursor-pointer ${
                                                    isSelected
                                                        ? "bg-white dark:bg-slate-800 border-[#0F6CBD] dark:border-[#5FB3E6] shadow-sm ring-1 ring-[#0F6CBD]/20"
                                                        : "bg-white/60 dark:bg-slate-800/60 border-slate-200 dark:border-slate-800 hover:border-slate-300"
                                                }`}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <span className="text-xs font-bold text-slate-900 dark:text-slate-100">
                                                        {cm.cm_name}
                                                    </span>
                                                    <Badge
                                                        variant="secondary"
                                                        className="text-[10px] px-1.5 py-0 font-semibold uppercase"
                                                    >
                                                        {cm.loop_type}
                                                    </Badge>
                                                </div>
                                                <p className="text-[11px] text-slate-500 mt-1 line-clamp-1">
                                                    {cm.description}
                                                </p>
                                                <div className="flex items-center gap-3 mt-2 text-[10px] text-slate-400">
                                                    <span>{cm.blocks?.length || 0} Blocks</span>
                                                    <span>·</span>
                                                    <span>{cm.period_ms}ms Scan</span>
                                                </div>
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Right: Selected CM Inspector & Block Signal Flow */}
                            <div className="col-span-8 space-y-4">
                                {selectedCm ? (
                                    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-5">
                                        <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-700/60 pb-3">
                                            <div>
                                                <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                                                    {selectedCm.cm_name}
                                                </h4>
                                                <p className="text-xs text-slate-500 mt-0.5">
                                                    {selectedCm.description}
                                                </p>
                                            </div>
                                            <div className="flex items-center gap-2">
                                                <Badge className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 text-xs">
                                                    {selectedCm.controller} ({selectedCm.period_ms}ms)
                                                </Badge>
                                            </div>
                                        </div>

                                        {/* Block Signal Chain Diagram */}
                                        <div>
                                            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                                                CEE Execution Flow &amp; Pin Interconnects
                                            </span>
                                            <div className="flex items-center gap-3 mt-3 overflow-x-auto pb-2">
                                                {selectedCm.blocks?.map((b: any, idx: number) => (
                                                    <React.Fragment key={b.tag}>
                                                        <div className="flex-1 min-w-[170px] p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/60">
                                                            <div className="flex items-center justify-between mb-1">
                                                                <span className="text-xs font-bold text-[#0F6CBD] dark:text-[#5FB3E6]">
                                                                    {b.block_type}
                                                                </span>
                                                                <span className="text-[10px] text-slate-400">
                                                                    #{b.execution_order}
                                                                </span>
                                                            </div>
                                                            <div className="text-xs font-mono font-semibold text-slate-800 dark:text-slate-200 truncate">
                                                                {b.tag}
                                                            </div>
                                                            <div className="mt-2 space-y-1 text-[11px]">
                                                                {b.parameters?.PVEUHI !== undefined && (
                                                                    <div className="flex justify-between text-slate-500">
                                                                        <span>Range:</span>
                                                                        <span className="font-mono text-slate-700 dark:text-slate-300">
                                                                            {b.parameters.PVEULO}..{b.parameters.PVEUHI} {b.parameters.EUDESC}
                                                                        </span>
                                                                    </div>
                                                                )}
                                                                {b.parameters?.GAIN !== undefined && (
                                                                    <div className="flex justify-between text-slate-500">
                                                                        <span>Gain / Ti:</span>
                                                                        <span className="font-mono text-slate-700 dark:text-slate-300">
                                                                            {b.parameters.GAIN} / {b.parameters.TI}m
                                                                        </span>
                                                                    </div>
                                                                )}
                                                                {b.parameters?.FAILACT && (
                                                                    <div className="flex justify-between text-slate-500">
                                                                        <span>Fail Action:</span>
                                                                        <span className="font-mono font-semibold text-rose-500">
                                                                            {b.parameters.FAILACT}
                                                                        </span>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </div>
                                                        {idx < (selectedCm.blocks?.length || 0) - 1 && (
                                                            <div className="flex flex-col items-center">
                                                                <ArrowRight className="h-4 w-4 text-slate-400" />
                                                                <span className="text-[9px] font-mono text-slate-400">
                                                                    WIRE
                                                                </span>
                                                            </div>
                                                        )}
                                                    </React.Fragment>
                                                ))}
                                            </div>
                                        </div>

                                        {/* Parameters Table */}
                                        <div>
                                            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                                                Function Block Parameters &amp; Thresholds
                                            </span>
                                            <div className="mt-2 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
                                                <table className="w-full text-left text-xs">
                                                    <thead className="bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold">
                                                        <tr>
                                                            <th className="p-2.5">Block Tag</th>
                                                            <th className="p-2.5">Parameter</th>
                                                            <th className="p-2.5">Configured Value</th>
                                                            <th className="p-2.5">Type</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                                        {selectedCm.blocks?.flatMap((b: any) =>
                                                            Object.entries(b.parameters || {}).map(([pName, pVal]) => (
                                                                <tr key={`${b.tag}-${pName}`} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40">
                                                                    <td className="p-2.5 font-mono text-[#0F6CBD] dark:text-[#5FB3E6]">{b.tag}</td>
                                                                    <td className="p-2.5 font-semibold text-slate-700 dark:text-slate-200">{pName}</td>
                                                                    <td className="p-2.5 font-mono font-bold text-slate-900 dark:text-slate-100">{String(pVal)}</td>
                                                                    <td className="p-2.5 text-slate-400">{typeof pVal}</td>
                                                                </tr>
                                                            ))
                                                        )}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="flex items-center justify-center h-48 text-slate-400 text-xs">
                                        Select a control module on the left to view its parameters.
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : activeTab === "opc" ? (
                        /* ── TAB 2: Live OPC UA Runtime & Loop Verification ── */
                        <div className="space-y-6">
                            {/* Connection Control Card */}
                            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2.5">
                                        <Radio className="h-5 w-5 text-[#0F6CBD]" />
                                        <div>
                                            <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                                                Honeywell Experion OPC UA Runtime Bridge
                                            </h4>
                                            <p className="text-xs text-slate-500">
                                                Live loop inspection, setpoint tuning, and process variable monitoring
                                            </p>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-2">
                                        <Badge
                                            className={`text-xs px-2.5 py-1 ${
                                                isOpcConnected
                                                    ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                                                    : "bg-slate-100 text-slate-500 border-slate-200"
                                            }`}
                                        >
                                            {isOpcConnected ? "Active Session" : "Disconnected"}
                                        </Badge>
                                        <Button
                                            onClick={handleToggleOpc}
                                            disabled={isConnectingOpc}
                                            size="sm"
                                            className={`h-8 gap-1.5 text-xs font-semibold ${
                                                isOpcConnected
                                                    ? "bg-rose-600 hover:bg-rose-700 text-white"
                                                    : "bg-[#0F6CBD] hover:bg-[#115EA3] text-white"
                                            }`}
                                        >
                                            {isConnectingOpc ? (
                                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                            ) : isOpcConnected ? (
                                                "Disconnect"
                                            ) : (
                                                "Connect to Experion"
                                            )}
                                        </Button>
                                    </div>
                                </div>

                                <div className="flex items-center gap-3">
                                    <div className="flex-1">
                                        <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block mb-1">
                                            OPC UA Server Endpoint URL
                                        </label>
                                        <input
                                            type="text"
                                            value={opcEndpoint}
                                            onChange={(e) => setOpcEndpoint(e.target.value)}
                                            disabled={isOpcConnected}
                                            className="w-full text-xs font-mono px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-[#0F6CBD]"
                                            placeholder="opc.tcp://localhost:4840"
                                        />
                                    </div>
                                </div>
                            </div>

                            {/* Live Loop Controllers */}
                            <div className="space-y-4">
                                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                                    Active Regulatory Control Loops
                                </h3>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {controlModules
                                        .filter((cm: any) => cm.blocks.some((b: any) => b.block_type === "PID"))
                                        .map((cm: any) => {
                                            const pidBlock = cm.blocks.find((b: any) => b.block_type === "PID");
                                            const aiBlock = cm.blocks.find((b: any) => b.block_type === "DATAACQ");
                                            const aoBlock = cm.blocks.find((b: any) => b.block_type === "AO");

                                            const spTag = `${pidBlock?.tag}.SP`;
                                            const pvTag = `${pidBlock?.tag}.PV`;
                                            const opTag = `${pidBlock?.tag}.OP`;
                                            const modeTag = `${pidBlock?.tag}.MODE`;

                                            const currentSp = opcTags[spTag]?.value ?? pidBlock?.parameters?.SP ?? 50.0;
                                            const currentPv = opcTags[pvTag]?.value ?? pidBlock?.parameters?.PV ?? 50.0;
                                            const currentOp = opcTags[opTag]?.value ?? pidBlock?.parameters?.OP ?? 50.0;
                                            const currentMode = opcTags[modeTag]?.value ?? pidBlock?.parameters?.MODE ?? "AUTO";
                                            const eu = pidBlock?.parameters?.EUDESC || "%";
                                            const spanHi = pidBlock?.parameters?.PVEUHI || 100.0;
                                            const spanLo = pidBlock?.parameters?.PVEULO || 0.0;

                                            return (
                                                <div
                                                    key={cm.cm_name}
                                                    className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4"
                                                >
                                                    <div className="flex items-center justify-between">
                                                        <div>
                                                            <div className="flex items-center gap-2">
                                                                <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                                                                    {cm.cm_name}
                                                                </h4>
                                                                <Badge className="text-[10px] bg-blue-500/10 text-blue-500 border-blue-500/20">
                                                                    {cm.loop_type}
                                                                </Badge>
                                                            </div>
                                                            <p className="text-xs text-slate-400 mt-0.5">
                                                                {cm.primary_sp_tag} ({cm.primary_pv_tag} ➔ {cm.primary_op_tag})
                                                            </p>
                                                        </div>

                                                        {/* Mode Switcher */}
                                                        <div className="flex items-center bg-slate-100 dark:bg-slate-900 p-1 rounded-lg">
                                                            {["MAN", "AUTO", "CAS"].map((m) => (
                                                                <button
                                                                    key={m}
                                                                    onClick={() => handleWriteParam(cm.cm_name, pidBlock.tag, "MODE", m)}
                                                                    className={`px-2 py-1 text-[11px] font-bold rounded-md transition-all cursor-pointer ${
                                                                        currentMode === m
                                                                            ? "bg-[#0F6CBD] text-white shadow-sm"
                                                                            : "text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
                                                                    }`}
                                                                >
                                                                    {m}
                                                                </button>
                                                            ))}
                                                        </div>
                                                    </div>

                                                    {/* Process Visual Bars */}
                                                    <div className="space-y-3">
                                                        {/* PV Indicator */}
                                                        <div>
                                                            <div className="flex justify-between text-xs mb-1">
                                                                <span className="font-semibold text-slate-600 dark:text-slate-300">
                                                                    Process Variable (PV):
                                                                </span>
                                                                <span className="font-mono font-bold text-[#0F6CBD] dark:text-[#5FB3E6]">
                                                                    {currentPv} {eu}
                                                                </span>
                                                            </div>
                                                            <div className="w-full h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden relative">
                                                                <div
                                                                    className="h-full bg-gradient-to-r from-blue-500 to-[#0F6CBD] transition-all duration-300"
                                                                    style={{
                                                                        width: `${Math.max(
                                                                            0,
                                                                            Math.min(100, ((currentPv - spanLo) / (spanHi - spanLo || 1)) * 100)
                                                                        )}%`,
                                                                    }}
                                                                />
                                                            </div>
                                                        </div>

                                                        {/* Setpoint (SP) Adjuster */}
                                                        <div>
                                                            <div className="flex justify-between text-xs mb-1">
                                                                <span className="font-semibold text-slate-600 dark:text-slate-300">
                                                                    Setpoint (SP):
                                                                </span>
                                                                <div className="flex items-center gap-1.5">
                                                                    <button
                                                                        onClick={() =>
                                                                            handleWriteParam(
                                                                                cm.cm_name,
                                                                                pidBlock.tag,
                                                                                "SP",
                                                                                Number((Number(currentSp) - 1.0).toFixed(1))
                                                                            )
                                                                        }
                                                                        className="w-5 h-5 rounded bg-slate-200 dark:bg-slate-700 text-xs font-bold hover:bg-slate-300"
                                                                    >
                                                                        -
                                                                    </button>
                                                                    <span className="font-mono font-bold text-slate-900 dark:text-slate-100">
                                                                        {currentSp} {eu}
                                                                    </span>
                                                                    <button
                                                                        onClick={() =>
                                                                            handleWriteParam(
                                                                                cm.cm_name,
                                                                                pidBlock.tag,
                                                                                "SP",
                                                                                Number((Number(currentSp) + 1.0).toFixed(1))
                                                                            )
                                                                        }
                                                                        className="w-5 h-5 rounded bg-slate-200 dark:bg-slate-700 text-xs font-bold hover:bg-slate-300"
                                                                    >
                                                                        +
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        </div>

                                                        {/* Output (OP) */}
                                                        <div>
                                                            <div className="flex justify-between text-xs mb-1">
                                                                <span className="font-semibold text-slate-600 dark:text-slate-300">
                                                                    Valve Command (OP):
                                                                </span>
                                                                <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">
                                                                    {currentOp}%
                                                                </span>
                                                            </div>
                                                            <div className="w-full h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                                                                <div
                                                                    className="h-full bg-emerald-500 transition-all duration-300"
                                                                    style={{ width: `${Math.max(0, Math.min(100, currentOp))}%` }}
                                                                />
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                </div>
                            </div>
                        </div>
                    ) : (
                        /* ── TAB 3: Export Center ── */
                        <div className="space-y-6 max-w-2xl mx-auto">
                            <div className="text-center space-y-2 py-4">
                                <Download className="h-10 w-10 mx-auto text-[#0F6CBD]" />
                                <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
                                    Export for Honeywell Experion PKS
                                </h3>
                                <p className="text-xs text-slate-500 max-w-md mx-auto">
                                    Download production-ready Control Builder strategy XML or Point Builder CSV files for direct import into Honeywell C300 controllers.
                                </p>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {/* Option A: Control Builder XML */}
                                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm flex flex-col justify-between space-y-4 hover:border-[#0F6CBD]/40 transition-all">
                                    <div className="space-y-2">
                                        <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/50 flex items-center justify-center text-[#0F6CBD]">
                                            <FileCode className="h-5 w-5" />
                                        </div>
                                        <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                                            Control Builder XML
                                        </h4>
                                        <p className="text-xs text-slate-500 leading-relaxed">
                                            Honeywell C300 CEE Control Modules, Function Blocks (DATAACQ, PID, AO), parameters, and internal wire connections.
                                        </p>
                                    </div>
                                    <Button
                                        onClick={handleExportXml}
                                        disabled={exportingXml}
                                        className="w-full gap-2 text-xs font-bold bg-[#0F6CBD] hover:bg-[#115EA3] text-white"
                                    >
                                        {exportingXml ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <Download className="h-4 w-4" />
                                        )}
                                        Download Control Builder XML
                                    </Button>
                                </div>

                                {/* Option B: Point Builder CSV */}
                                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm flex flex-col justify-between space-y-4 hover:border-emerald-500/40 transition-all">
                                    <div className="space-y-2">
                                        <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 flex items-center justify-center text-emerald-600">
                                            <FileSpreadsheet className="h-5 w-5" />
                                        </div>
                                        <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                                            Point Builder / QB CSV
                                        </h4>
                                        <p className="text-xs text-slate-500 leading-relaxed">
                                            Bulk tag database spreadsheet with ranges, engineering units, alarm limits, execution order, and controller assignment.
                                        </p>
                                    </div>
                                    <Button
                                        onClick={handleExportCsv}
                                        disabled={exportingCsv}
                                        className="w-full gap-2 text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white"
                                    >
                                        {exportingCsv ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <Download className="h-4 w-4" />
                                        )}
                                        Download Point Builder CSV
                                    </Button>
                                </div>
                            </div>

                            {/* Experion Import Instructions */}
                            <div className="bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-2">
                                <h5 className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider">
                                    Import Procedure into Experion PKS
                                </h5>
                                <ol className="list-decimal list-inside text-xs text-slate-600 dark:text-slate-400 space-y-1">
                                    <li>Open <strong>Honeywell Experion Control Builder</strong>.</li>
                                    <li>Right-click on the project tree and select <strong>Import ➔ Strategy XML...</strong></li>
                                    <li>Select the downloaded <code>.xml</code> file and map to your target C300 controller (<code>CEE01_C300</code>).</li>
                                    <li>Verify blocks in the Chart view and click <strong>Load ➔ To Controller</strong>.</li>
                                </ol>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
export default ExperionStudioDrawer;
