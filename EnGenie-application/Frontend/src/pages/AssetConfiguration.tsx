import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import MainHeader from "@/components/MainHeader";
import {
    Loader2,
    Link2, Send, Sparkles,
    ChevronLeft, ChevronRight, MapPin, Cpu, Image as ImageIcon,
    BookOpen, Radio, Settings2, BarChart2, SlidersHorizontal, Activity,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useToast } from "@/hooks/use-toast";
import ReactMarkdown from "react-markdown";
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import {
    extractFromText,
    getAssetStandards,
    getGenericImage,
    saveAssetConfiguration,
    generateAssetYaml,
    BASE_URL
} from "@/components/AIRecommender/api";
import StreamingProgress from "@/components/AIRecommender/StreamingProgress";

// ── Types ──────────────────────────────────────────────────────────────────

interface AssetInfo {
    source: "existing" | "manual";
    asset_name: string;
    asset_type: string;
    tag_number: string;
    manufacturer: string;
    model: string;
    serial_number: string;
}

interface LocationInfo {
    plant: string;
    site: string;
    area: string;
    unit: string;
}

interface SystemInfo {
    name: string;
    type: string;
    protocol: string;
    details: string;
}

interface RelationshipEntry {
    enabled: boolean;
    notes: string;
}

interface Relationships {
    migration: RelationshipEntry;
    integration: RelationshipEntry;
    configuration_pairing: RelationshipEntry;
}

interface HARTIdentity {
    equipment_category?: string;
    hart_tag: string;
    hart_long_tag: string;
    message: string;
    descriptor: string;
    sensor_serial: string;
    transmitter_serial: string;
    device_revision: string;
}

interface CalibrationValues {
    flow_calibration_factor: string;
    density_coeff_d1: string;
    density_coeff_d2: string;
    density_coeff_d3: string;
    density_coeff_d4: string;
    temperature_coefficient: string;
}

interface PVMapping {
    primary_variable: string;
    secondary_variable: string;
    tertiary_variable: string;
    quaternary_variable: string;
    urv: string;
    lrv: string;
    pv_units: string;
}

interface MeasurementControl {
    damping: string;
    low_flow_cutoff: string;
    flow_direction: string;
    fault_action: string;
    totalizer: string;
    measurement_units: string;
}

interface DiagnosticsHealth {
    smv_frequency: string;
    smv_integrity_enabled: boolean;
    drive_gain_limit: string;
    density_deviation_limit: string;
    temp_high_limit: string;
    electronics_temp_limit: string;
}

interface InstrumentConfig {
    hart_identity: HARTIdentity;
    calibration: CalibrationValues;
    pv_mapping: PVMapping;
    measurement_control: MeasurementControl;
    diagnostics_health: DiagnosticsHealth;
}


interface ChatMessage {
    role: "user" | "assistant";
    content: string;
    timestamp?: Date;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const emptyAsset = (): AssetInfo => ({
    source: "manual",
    asset_name: "",
    asset_type: "",
    tag_number: "",
    manufacturer: "",
    model: "",
    serial_number: "",
});

const emptyLocation = (): LocationInfo => ({
    plant: "",
    site: "",
    area: "",
    unit: "",
});

const emptySystem = (): SystemInfo => ({
    name: "",
    type: "",
    protocol: "",
    details: "",
});

const emptyRelationships = (): Relationships => ({
    migration: { enabled: false, notes: "" },
    integration: { enabled: false, notes: "" },
    configuration_pairing: { enabled: false, notes: "" },
});

const emptyInstrumentConfig = (): InstrumentConfig => ({
    hart_identity: {
        hart_tag: "", hart_long_tag: "", message: "", descriptor: "",
        sensor_serial: "", transmitter_serial: "", device_revision: "",
    },
    calibration: {
        flow_calibration_factor: "", density_coeff_d1: "", density_coeff_d2: "",
        density_coeff_d3: "", density_coeff_d4: "", temperature_coefficient: "",
    },
    pv_mapping: {
        primary_variable: "", secondary_variable: "", tertiary_variable: "",
        quaternary_variable: "", urv: "", lrv: "", pv_units: "",
    },
    measurement_control: {
        damping: "", low_flow_cutoff: "", flow_direction: "",
        fault_action: "", totalizer: "", measurement_units: "",
    },
    diagnostics_health: {
        smv_frequency: "", smv_integrity_enabled: false, drive_gain_limit: "",
        density_deviation_limit: "", temp_high_limit: "", electronics_temp_limit: "",
    },
});

// ── Welcome Messages ───────────────────────────────────────────────────────

const ASSET_CONFIG_GREETINGS = [
    "Welcome to Asset Configuration. I am your AI assistant. Describe the asset you want to configure — include the device type, manufacturer, model, location, and any connected systems — and I will extract and structure the configuration for you.",
    "Hello. I am your AI assistant. Share the details of the instrument or asset you need to configure, such as its type, tag number, site location, and connected DCS or SCADA system, and I will build the configuration automatically.",
    "You are now in the Asset Configuration workspace. I am your AI assistant. Provide a description of the field device — including its category, manufacturer, model, and process location — and I will populate the configuration fields and apply relevant engineering standards.",
    "I am your AI assistant. Tell me about the asset you want to configure: its instrument type, tag, plant area, and any integration or migration requirements. I will extract all key parameters and prepare a structured YAML configuration.",
    "Welcome. I am your AI assistant. Enter a description of the asset — such as a flow meter, pressure transmitter, or level sensor — along with its location and system details, and I will generate a complete, standards-compliant configuration."
];

// ── Constants ──────────────────────────────────────────────────────────────

const DEFAULT_LEFT_WIDTH = 21;
const DEFAULT_RIGHT_WIDTH = 40;
const DEFAULT_RIGHT_EXPANDED_WIDTH = 40;
const MIN_WIDTH = 15;
const MAX_WIDTH_LEFT = 45;
const MAX_WIDTH_RIGHT = 55;

// ── Caching ────────────────────────────────────────────────────────────────
const genericImageCache: Record<string, string | null> = {};

// ── Main Component ─────────────────────────────────────────────────────────

const AssetConfiguration = () => {
    const { toast } = useToast();

    // Form state
    const [asset, setAsset] = useState<AssetInfo>(emptyAsset());
    const [loc, setLoc] = useState<LocationInfo>(emptyLocation());
    const [connectedSystem, setConnectedSystem] = useState<SystemInfo>(emptySystem());
    const [targetSystem, setTargetSystem] = useState<SystemInfo>(emptySystem());
    const [relationships, setRelationships] = useState<Relationships>(emptyRelationships());
    const [instrumentConfig, setInstrumentConfig] = useState<InstrumentConfig>(emptyInstrumentConfig());

    // YAML & saved configs
    const [yamlContent, setYamlContent] = useState<string | null>(null);
    const [activeConfigId, setActiveConfigId] = useState<string | null>(null);

    // UI state
    const [generating, setGenerating] = useState(false);

    // Chat state — seeded with a random greeting on first load
    const [messages, setMessages] = useState<ChatMessage[]>(() => [{
        role: "assistant" as const,
        content: ASSET_CONFIG_GREETINGS[Math.floor(Math.random() * ASSET_CONFIG_GREETINGS.length)],
        timestamp: new Date(),
    }]);
    const [chatInput, setChatInput] = useState("");
    const [chatLoading, setChatLoading] = useState(false);
    const chatTextareaRef = useRef<HTMLTextAreaElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // Asset image state
    const [assetImageUrl, setAssetImageUrl] = useState<string | null>(null);
    const [assetImageLoading, setAssetImageLoading] = useState(false);

    // Standards state
    const [standards, setStandards] = useState<{
        found: boolean;
        specifications: Record<string, string>;
        source_document: string | null;
        loading: boolean;
        message: string | null;
    }>({ found: false, specifications: {}, source_document: null, loading: false, message: null });

    // Panel state — both docked initially (Search-screen pattern)
    const [isDocked, setIsDocked] = useState(true);
    const [isRightDocked, setIsRightDocked] = useState(true);
    const [leftWidth, setLeftWidth] = useState(DEFAULT_LEFT_WIDTH);
    const [rightWidth, setRightWidth] = useState(DEFAULT_RIGHT_EXPANDED_WIDTH);
    const [dragging, setDragging] = useState<"left" | "right" | null>(null);
    const dragStartXRef = useRef(0);
    const dragStartLeftRef = useRef(DEFAULT_LEFT_WIDTH);
    const dragStartRightRef = useRef(DEFAULT_RIGHT_EXPANDED_WIDTH);
    const hasAutoUndockedRight = useRef(false);

    // Image hover state
    const [hoveredImage, setHoveredImage] = useState<string | null>(null);
    const hideImageTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

    // ── Handle incoming query parameters (e.g. from P&ID Studio) ────────────
    const [searchParams] = useSearchParams();
    const tagParamProcessed = useRef(false);

    useEffect(() => {
        const tag = searchParams.get('tag');
        if (tag && !tagParamProcessed.current) {
            tagParamProcessed.current = true;
            setAsset(prev => ({
                ...prev,
                tag_number: tag,
                asset_name: prev.asset_name || tag,
            }));
            setMessages(prev => [
                ...prev,
                {
                    role: "assistant",
                    content: `Workspace initialized for tag **${tag}**. Please specify the instrument model, manufacturer, process parameters, or migration requirements.`,
                    timestamp: new Date(),
                }
            ]);
            setIsDocked(false);
        }
    }, [searchParams]);

    // ── Auto-scroll to latest message ───────────────────────────────────────

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    // ── Auto-undock panels when data arrives (Search-screen pattern) ──────
    // Right panel: undock once when the first real extraction populates data
    useEffect(() => {
        if (hasAutoUndockedRight.current) return;
        const hasData = asset.asset_name || asset.tag_number || loc.plant;
        if (hasData) {
            hasAutoUndockedRight.current = true;
            setIsRightDocked(false);
            setIsDocked(false);
        }
    }, [asset.asset_name, asset.tag_number, loc.plant]);

    // ── Fetch standards for display panel when asset type changes ─────────
    // The backend already applies standards to instrument_config during chat
    // extraction. This fetch is purely for showing the "Applied Standards (RAG)"
    // reference panel, not for populating form fields.
    useEffect(() => {
        const category = asset.asset_type || "";
        if (!category || category === "—") {
            setStandards({ found: false, specifications: {}, source_document: null, loading: false, message: null });
            return;
        }

        let cancelled = false;
        setStandards(prev => ({ ...prev, loading: true }));

        const timeoutId = setTimeout(async () => {
            try {
                const data = await getAssetStandards(category);
                if (cancelled) return;
                setStandards({
                    found: data.found ?? false,
                    specifications: data.specifications ?? {},
                    source_document: data.source_document ?? null,
                    loading: false,
                    message: data.message ?? null,
                });
            } catch {
                if (!cancelled) setStandards({ found: false, specifications: {}, source_document: null, loading: false, message: null });
            }
        }, 500);

        return () => {
            cancelled = true;
            clearTimeout(timeoutId);
        };
    }, [asset.asset_type]);

    // ── Fetch asset image when asset type changes ──────────────────────────

    useEffect(() => {
        if (!asset.asset_type || asset.asset_type === "—") {
            setAssetImageUrl(null);
            return;
        }

        const typeKey = asset.asset_type.toLowerCase();
        if (genericImageCache[typeKey] !== undefined) {
            setAssetImageUrl(genericImageCache[typeKey]);
            setAssetImageLoading(false);
            return;
        }

        let cancelled = false;
        setAssetImageLoading(true);
        setAssetImageUrl(null);

        getGenericImage(asset.asset_type)
            .then(data => {
                if (cancelled) return;
                const url = data?.image?.url ?? null;
                genericImageCache[typeKey] = url;
                setAssetImageUrl(url);
            })
            .catch(() => {
                if (!cancelled) {
                    genericImageCache[typeKey] = null;
                    setAssetImageUrl(null);
                }
            })
            .finally(() => {
                if (!cancelled) setAssetImageLoading(false);
            });

        return () => { cancelled = true; };
    }, [asset.asset_type]);


    // ── Chat send ──────────────────────────────────────────────────────────

    const handleChatSend = async () => {
        const text = chatInput.trim();
        if (!text || chatLoading) return;

        // Add user message to history
        const userMessage: ChatMessage = { role: "user", content: text, timestamp: new Date() };
        setMessages((prev) => [...prev, userMessage]);

        setChatInput("");
        if (chatTextareaRef.current) chatTextareaRef.current.style.height = "auto";
        setChatLoading(true);
        setYamlContent(null);

        try {
            const data = await extractFromText(text, {
                asset_type: asset.asset_type || "",
                equipment_category: instrumentConfig.hart_identity.equipment_category || "",
                instrument_config: instrumentConfig,
            });

            if (data.success) {
                // Add assistant response to chat history
                const assistantMessage: ChatMessage = {
                    role: "assistant",
                    content: data.reply || "Configuration processed from your description.",
                    timestamp: new Date(),
                };
                setMessages((prev) => [...prev, assistantMessage]);

                // If backend returned YAML directly (all RAGs ran), use it
                if (data.yaml_content) {
                    setYamlContent(data.yaml_content);
                    setRightTab("asset_manager");
                }

                // Update internal state for save/re-generate use
                const extracted = data.extracted || {};
                if (extracted.asset) setAsset((prev) => ({ ...prev, ...extracted.asset }));
                if (extracted.location) setLoc((prev) => ({ ...prev, ...extracted.location }));
                if (extracted.connected_system) setConnectedSystem((prev) => ({ ...prev, ...extracted.connected_system }));
                if (extracted.target_system) setTargetSystem((prev) => ({ ...prev, ...extracted.target_system }));
                if (extracted.relationships) {
                    setRelationships((prev) => {
                        const updated = { ...prev };
                        for (const key of ["migration", "integration", "configuration_pairing"] as const) {
                            if (extracted.relationships[key]) {
                                updated[key] = { ...prev[key], ...extracted.relationships[key] };
                            }
                        }
                        return updated;
                    });
                }
                if (extracted.instrument_config) {
                    const ic = extracted.instrument_config;
                    // Smart merge: only overwrite a field if the new value is non-empty.
                    // This prevents a follow-up message from blanking out previously-set values.
                    const smartMerge = <T extends object>(prev: T, next: Partial<T>): T => {
                        const result = { ...prev };
                        for (const key in next) {
                            const val = next[key as keyof T];
                            const isEmpty = val === "" || val === null || val === undefined;
                            if (!isEmpty) {
                                (result as any)[key] = val;
                            }
                        }
                        return result;
                    };
                    setInstrumentConfig((prev) => ({
                        hart_identity: smartMerge(prev.hart_identity, (ic.hart_identity || {}) as any),
                        calibration: smartMerge(prev.calibration, (ic.calibration || {}) as any),
                        pv_mapping: smartMerge(prev.pv_mapping, (ic.pv_mapping || {}) as any),
                        measurement_control: smartMerge(prev.measurement_control, (ic.measurement_control || {}) as any),
                        diagnostics_health: smartMerge(prev.diagnostics_health, (ic.diagnostics_health || {}) as any),
                    }));
                }

                toast({
                    title: data.yaml_content ? "YAML Generated" : "Processing complete",
                    description: "Configuration updated",
                    duration: 4000
                });
            } else {
                const isRateLimit = data.status === 503;
                const errorMsg = data.error || (isRateLimit ? "AI service is rate-limited. Please try again in a moment." : "Try rephrasing your description.");

                // Add error message to chat
                const errorMessage: ChatMessage = {
                    role: "assistant",
                    content: `Error: ${errorMsg}`,
                };
                setMessages((prev) => [...prev, errorMessage]);

                toast({
                    title: isRateLimit ? "Service temporarily unavailable" : "Couldn't extract",
                    description: errorMsg,
                    variant: "destructive",
                    duration: isRateLimit ? 6000 : 4000,
                });
            }
        } catch {
            const errorMessage: ChatMessage = {
                role: "assistant",
                content: "Network error. Please try again.",
            };
            setMessages((prev) => [...prev, errorMessage]);

            toast({ title: "Error", description: "Something went wrong. Please try again.", variant: "destructive" });
        } finally {
            setChatLoading(false);
        }
    };

    // ── Drag-resize handlers ───────────────────────────────────────────────

    const handleMouseDownLeft = (e: React.MouseEvent) => {
        e.preventDefault();
        setDragging("left");
        dragStartXRef.current = e.clientX;
        dragStartLeftRef.current = leftWidth;
    };

    const handleMouseDownRight = (e: React.MouseEvent) => {
        e.preventDefault();
        setDragging("right");
        dragStartXRef.current = e.clientX;
        dragStartRightRef.current = rightWidth;
    };

    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!dragging) return;
            const delta = e.clientX - dragStartXRef.current;
            const pct = (delta / window.innerWidth) * 100;
            if (dragging === "left") {
                setLeftWidth(Math.max(MIN_WIDTH, Math.min(dragStartLeftRef.current + pct, MAX_WIDTH_LEFT)));
            } else {
                setRightWidth(Math.max(MIN_WIDTH, Math.min(dragStartRightRef.current - pct, MAX_WIDTH_RIGHT)));
            }
        };
        const handleMouseUp = () => setDragging(null);
        if (dragging) {
            document.addEventListener("mousemove", handleMouseMove);
            document.addEventListener("mouseup", handleMouseUp);
            return () => {
                document.removeEventListener("mousemove", handleMouseMove);
                document.removeEventListener("mouseup", handleMouseUp);
            };
        }
    }, [dragging]);

    // ── CRUD Operations ────────────────────────────────────────────────────

    const handleSave = async () => {
        if (!asset.asset_name && !asset.tag_number) {
            toast({ title: "Validation", description: "Asset name or tag number is required", variant: "destructive" });
            return;
        }

        try {
            const body = {
                asset,
                location: loc,
                connected_system: connectedSystem,
                target_system: targetSystem,
                relationships,
                instrument_config: instrumentConfig,
            };

            const data = await saveAssetConfiguration(activeConfigId, body);
            if (data.success) {
                if (!activeConfigId && data.configuration_id) {
                    setActiveConfigId(data.configuration_id);
                }
                toast({ title: "Saved", description: activeConfigId ? "Configuration updated" : "Configuration created" });
            } else {
                toast({ title: "Error", description: data.error || "Save failed", variant: "destructive" });
            }
        } catch {
            toast({ title: "Error", description: "Failed to save configuration", variant: "destructive" });
        }
    };

    const handleGenerateYaml = async () => {
        // First ensure the config is saved and we have a valid configId
        let configId = activeConfigId;
        if (!configId) {
            // Save first, capture the returned configuration_id directly
            try {
                const body = { asset, location: loc, connected_system: connectedSystem, target_system: targetSystem, relationships };
                const saveData = await saveAssetConfiguration(null, body);
                if (!saveData.success || !saveData.configuration_id) {
                    toast({ title: "Error", description: "Failed to save configuration before generating YAML", variant: "destructive" });
                    return;
                }
                configId = saveData.configuration_id;
                setActiveConfigId(configId);
            } catch {
                toast({ title: "Error", description: "Failed to save configuration", variant: "destructive" });
                return;
            }
        }

        setGenerating(true);
        try {
            const data = await generateAssetYaml(configId);
            if (data.success && data.yaml_content) {
                setYamlContent(data.yaml_content);
                setRightTab("asset_manager");
                toast({
                    title: "YAML Generated",
                    description: data.standards_applied?.length
                        ? `Applied ${data.standards_applied.length} standard(s)`
                        : "Generated (no matching standards found)",
                });
            } else {
                const isRateLimit = data.status === 503;
                toast({
                    title: isRateLimit ? "Service temporarily unavailable" : "Generation failed",
                    description: data.error || (isRateLimit ? "AI service is rate-limited. Please try again in a moment." : "Generation failed"),
                    variant: "destructive",
                    duration: isRateLimit ? 6000 : 4000,
                });
            }
        } catch {
            toast({ title: "Error", description: "Failed to generate YAML", variant: "destructive" });
        } finally {
            setGenerating(false);
        }
    };

    const handleDownloadYaml = () => {
        if (!yamlContent) return;
        const safeName = (asset.asset_name || "asset").replace(/[^\w-]/g, "_");
        const blob = new Blob([yamlContent], { type: "application/x-yaml" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${safeName}_configuration.yaml`;
        a.click();
        URL.revokeObjectURL(url);
    };



    // ── Render ─────────────────────────────────────────────────────────────

    return (
        <div className="flex flex-col h-screen app-glass-gradient animate-in fade-in duration-300 overflow-hidden">
            <MainHeader showProjectActions={false}>
                <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
                    <h1 className="text-2xl md:text-3xl font-bold text-white inline-flex items-center gap-2">
                        Asset Configuration
                    </h1>
                </div>
            </MainHeader>

            {/* Left dock button — only visible once data has been extracted */}
            {(asset.asset_name || asset.tag_number || loc.plant) && (
                <Button
                    variant="ghost"
                    size="icon"
                    className="fixed top-32 left-0 z-20 btn-glass-secondary border-0 shadow-lg rounded-l-none"
                    onClick={() => setIsDocked(!isDocked)}
                    aria-label={isDocked ? "Expand left panel" : "Collapse left panel"}
                >
                    {isDocked ? <ChevronRight /> : <ChevronLeft />}
                </Button>
            )}

            {/* Right dock button — only visible once data has been extracted */}
            {(asset.asset_name || asset.tag_number || loc.plant) && (
                <Button
                    variant="ghost"
                    size="icon"
                    className="fixed top-32 right-0 z-20 btn-glass-secondary border-0 shadow-lg rounded-r-none"
                    onClick={() => setIsRightDocked(!isRightDocked)}
                    aria-label={isRightDocked ? "Expand right panel" : "Collapse right panel"}
                >
                    {isRightDocked ? <ChevronLeft /> : <ChevronRight />}
                </Button>
            )}

            {/* 3-Panel Layout */}
            <div className="flex flex-1 overflow-hidden pt-[96px]">
                {/* ═══════════════════ LEFT PANEL ═══════════════════ */}
                <div
                    className="h-full flex flex-col relative transition-all duration-500 ease-in-out overflow-hidden glass-sidebar"
                    style={{
                        width: isDocked ? "0%" : `${leftWidth}%`,
                        minWidth: isDocked ? "0%" : "7%",
                        opacity: isDocked ? 0 : 1,
                        willChange: "width, opacity",
                    }}
                >
                    <div className="flex-1 overflow-y-auto custom-visible-scrollbar p-4 space-y-4">
                        {/* Section Title */}
                        {(asset.asset_name || asset.asset_type) && (
                            <div className="text-center pb-1">
                                <h2 className="text-xl font-semibold">
                                    <span className="text-gradient-copilot inline-block">
                                        {asset.asset_type || asset.asset_name}
                                    </span>
                                </h2>
                            </div>
                        )}

                        {/* Device Card */}
                        <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                            <div className="flex items-center gap-2 mb-3">
                                <Cpu className="h-4 w-4 text-sky-400" />
                                <h3 className="text-xs font-bold text-sky-400 uppercase tracking-wider">Device</h3>
                            </div>
                            <div className="space-y-1">
                                {[
                                    { label: "Name", value: asset.asset_name },
                                    { label: "Type", value: asset.asset_type },
                                    { label: "Manufacturer", value: asset.manufacturer },
                                    { label: "Model", value: asset.model },
                                    { label: "Serial", value: asset.serial_number },
                                ].map((item) => (
                                    <div key={item.label} className="flex items-start gap-x-2 text-xs">
                                        <span className="font-medium text-muted-foreground shrink-0 min-w-[72px]">{item.label}:</span>
                                        <span className={`break-words ${item.value ? "text-foreground font-mono" : "text-zinc-500"}`}>
                                            {item.value || "—"}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Location Card */}
                        <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                            <div className="flex items-center gap-2 mb-3">
                                <MapPin className="h-4 w-4 text-sky-400" />
                                <h3 className="text-xs font-bold text-sky-400 uppercase tracking-wider">Location</h3>
                            </div>
                            <div className="space-y-1">
                                {[
                                    { label: "Plant", value: loc.plant },
                                    { label: "Site", value: loc.site },
                                    { label: "Area", value: loc.area },
                                    { label: "Unit", value: loc.unit },
                                ].map((item) => (
                                    <div key={item.label} className="flex items-start gap-x-2 text-xs">
                                        <span className="font-medium text-muted-foreground shrink-0 min-w-[40px]">{item.label}:</span>
                                        <span className={`break-words ${item.value ? "text-foreground font-mono" : "text-zinc-500"}`}>
                                            {item.value || "—"}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Connected System Card */}
                        {connectedSystem.name && (
                            <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                                <div className="flex items-center gap-2 mb-3">
                                    <Link2 className="h-4 w-4 text-sky-400" />
                                    <h3 className="text-xs font-bold text-sky-400 uppercase tracking-wider">Connected System</h3>
                                </div>
                                <div className="space-y-1">
                                    {[
                                        { label: "Name", value: connectedSystem.name },
                                        { label: "Type", value: connectedSystem.type },
                                        { label: "Protocol", value: connectedSystem.protocol },
                                        { label: "Details", value: connectedSystem.details },
                                    ].filter(i => i.value).map((item) => (
                                        <div key={item.label} className="flex items-start gap-x-2 text-xs">
                                            <span className="font-medium text-muted-foreground shrink-0 min-w-[52px]">{item.label}:</span>
                                            <span className="break-words text-foreground font-mono">{item.value}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Target System Card */}
                        {targetSystem.name && (
                            <div className="bg-[#171717]/80 backdrop-blur-sm rounded-xl p-4 shadow-md border border-white/10">
                                <div className="flex items-center gap-2 mb-3">
                                    <Link2 className="h-4 w-4 text-sky-400" />
                                    <h3 className="text-xs font-bold text-sky-400 uppercase tracking-wider">Target System</h3>
                                </div>
                                <div className="space-y-1">
                                    {[
                                        { label: "Name", value: targetSystem.name },
                                        { label: "Type", value: targetSystem.type },
                                        { label: "Protocol", value: targetSystem.protocol },
                                        { label: "Details", value: targetSystem.details },
                                    ].filter(i => i.value).map((item) => (
                                        <div key={item.label} className="flex items-start gap-x-2 text-xs">
                                            <span className="font-medium text-muted-foreground shrink-0 min-w-[52px]">{item.label}:</span>
                                            <span className="break-words text-foreground font-mono">{item.value}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                </div>

                {/* Left Drag Separator */}
                {!isDocked && (
                    <div
                        onMouseDown={handleMouseDownLeft}
                        className={`w-1.5 cursor-col-resize transition-colors duration-500 ease-in-out z-10 ${dragging === "left" ? "bg-[#5FB3E6]" : "bg-border hover:bg-[#5FB3E6]"
                            }`}
                        style={{ height: "100%" }}
                    />
                )}

                {/* ═══════════════════ CENTER PANEL ═══════════════════ */}
                <div className="h-full flex flex-col flex-1 overflow-hidden glass-sidebar relative">
                    {/* Decorative background images */}
                    <div className="absolute inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
                        <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none" />
                    </div>
                    <div className="flex flex-col h-full overflow-hidden relative z-10">
                        {/* Chat Messages — pb-24 leaves room for the fixed floating input */}
                        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-no-scrollbar pb-24">
                            {messages.map((msg, idx) => (
                                <div
                                    key={idx}
                                    className={`flex items-start gap-2 ${msg.role === "user" ? "flex-row-reverse" : ""
                                        }`}
                                >
                                    {/* Avatar */}
                                    <div className={`flex-shrink-0 w-16 h-16 flex items-center justify-center ${msg.role === "user" ? "-mt-3" : ""}`}>
                                        {msg.role === "user" ? (
                                            <img src="/icon-user-3d.png" alt="User" className="w-16 h-16 object-contain" />
                                        ) : (
                                            <img src="/engenie icon.jpeg" alt="Assistant" className="w-20 h-20 object-contain rounded-full" />
                                        )}
                                    </div>
                                    {/* Bubble + timestamp */}
                                    <div className="flex-1">
                                        <div className={`max-w-[80%] break-words ${msg.role === "user" ? "glass-bubble-user ml-auto" : "glass-bubble-assistant"
                                            }`}
                                            style={{
                                                transformOrigin: msg.role === "user" ? "top right" : "top left",
                                            }}
                                        >
                                            <div className="prose prose-sm dark:prose-invert">
                                                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                                                    {msg.role === "user" ? msg.content.replace(/\n/g, "  \n") : msg.content}
                                                </ReactMarkdown>
                                            </div>
                                        </div>
                                        <p className={`text-xs text-muted-foreground mt-1 px-1 ${msg.role === "user" ? "text-right" : ""
                                            }`}>
                                            {msg.timestamp instanceof Date
                                                ? msg.timestamp.toLocaleTimeString()
                                                : new Date().toLocaleTimeString()}
                                        </p>
                                    </div>
                                </div>
                            ))}

                            {chatLoading && (
                                <StreamingProgress streamId="local" />
                            )}

                            <div ref={messagesEndRef} />
                        </div>

                        {/* Chat Input — fixed floating pill, matches Search screen exactly */}
                        <div className="fixed bottom-0 left-0 right-0 p-4 bg-transparent z-30 pointer-events-none">
                            <div className="max-w-4xl mx-auto px-2 md:px-8 pointer-events-auto">
                                <form onSubmit={(e) => { e.preventDefault(); handleChatSend(); }}>
                                    <div className="relative group">
                                        <div className="chat-input-wrapper relative w-full rounded-2xl flex items-end transition-all duration-300 bg-[#212121] border border-white/10 hover:border-white/20 focus-within:border-white/30 shadow-2xl p-2"
                                            style={{
                                                WebkitBackdropFilter: 'blur(12px)',
                                                backdropFilter: 'blur(12px)',
                                                color: '#f4f4f5'
                                            }}>
                                            <textarea
                                                ref={chatTextareaRef}
                                                placeholder="Type your message here..."
                                                value={chatInput}
                                                onChange={(e) => setChatInput(e.target.value)}
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter" && !e.shiftKey) {
                                                        e.preventDefault();
                                                        handleChatSend();
                                                    }
                                                }}
                                                onInput={(e) => {
                                                    const target = e.target as HTMLTextAreaElement;
                                                    target.style.height = 'auto';
                                                    target.style.height = `${Math.min(target.scrollHeight, 150)}px`;
                                                }}
                                                className="flex-1 min-w-0 bg-transparent border-0 focus:ring-0 focus:outline-none px-4 py-2.5 text-sm resize-none min-h-[40px] max-h-[150px] leading-relaxed custom-visible-scrollbar-dark text-white placeholder:text-zinc-500"
                                                style={{
                                                    fontSize: '15px',
                                                    fontFamily: 'inherit',
                                                    boxShadow: 'none',
                                                    overflowY: 'auto'
                                                }}
                                                disabled={chatLoading}
                                            />

                                            {/* Action Button */}
                                            <div className="flex-shrink-0 pb-1 pr-1 flex items-center gap-1">
                                                <Button
                                                    type="submit"
                                                    disabled={!chatInput.trim() || chatLoading}
                                                    className={`w-9 h-9 p-0 rounded-xl flex items-center justify-center transition-all duration-200 ${!chatInput.trim() || chatLoading
                                                        ? 'bg-zinc-800 text-zinc-500 opacity-50 cursor-not-allowed'
                                                        : 'bg-sky-500 hover:bg-sky-400 text-white shadow-lg shadow-sky-500/25 active:scale-95'
                                                    }`}
                                                    variant="ghost"
                                                    size="icon"
                                                    title="Submit"
                                                >
                                                    {chatLoading ? (
                                                        <Loader2 className="h-4 w-4 animate-spin text-white" />
                                                    ) : (
                                                        <Send className="h-4 w-4" />
                                                    )}
                                                </Button>
                                            </div>
                                        </div>
                                    </div>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Drag Separator */}
                {!isRightDocked && (
                    <div
                        onMouseDown={handleMouseDownRight}
                        className={`w-1.5 cursor-col-resize transition-colors duration-500 ease-in-out z-10 ${dragging === "right" ? "bg-[#5FB3E6]" : "bg-border hover:bg-[#5FB3E6]"
                            }`}
                        style={{ height: "100%" }}
                    />
                )}

                {/* ═══════════════════ RIGHT PANEL ═══════════════════ */}
                <div
                    className="h-full transition-all duration-500 ease-in-out relative p-2"
                    style={{
                        width: isRightDocked ? "0%" : `${rightWidth}%`,
                        minWidth: isRightDocked ? "0%" : "7%",
                        overflow: "hidden",
                        opacity: isRightDocked ? 0 : 1,
                        willChange: "width, opacity",
                    }}
                >
                    {/* Hover Image Portal */}
                    {hoveredImage && (
                        <div
                            style={{
                                position: "absolute",
                                top: "50%",
                                left: "50%",
                                transform: "translate(-50%, -50%)",
                                backgroundColor: "rgba(255, 255, 255, 0.98)",
                                padding: 16,
                                borderRadius: 16,
                                boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
                                zIndex: 9999,
                                maxWidth: "220px",
                                maxHeight: "220px",
                                display: "flex",
                                justifyContent: "center",
                                alignItems: "center",
                                border: "2px solid rgba(0,0,0,0.1)",
                            }}
                            className="dark:bg-slate-800/98 dark:border-slate-600"
                        >
                            <img
                                src={hoveredImage}
                                alt="Asset preview"
                                style={{
                                    maxWidth: "180px",
                                    maxHeight: "180px",
                                    objectFit: "contain",
                                    borderRadius: 12,
                                }}
                            />
                        </div>
                    )}

                    <div className="flex flex-col h-full overflow-hidden rounded-2xl border border-white/10 bg-[#171717]/80 backdrop-blur-sm shadow-xl relative">
                        {/* Panel Header - Sticky */}
                        <div className="sticky top-0 flex items-center px-4 py-2.5 border-b border-white/10 bg-[#212121]/90 z-40 flex-shrink-0">
                            <span className="text-xs font-bold tracking-wider text-sky-400 uppercase">Asset Manager</span>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto custom-visible-scrollbar overflow-x-hidden bg-transparent">
                                <div className="p-4 space-y-4">
                                    {asset.asset_name || loc.plant || connectedSystem.name ? (
                                        <div className="bg-[#212121]/80 backdrop-blur-md rounded-2xl p-6 shadow-xl border border-white/10 overflow-hidden break-words hover:shadow-2xl transition-all duration-300 transform hover:-translate-y-1 mx-1 mb-1">
                                            {/* Asset Manager Actions */}
                                            <div className="flex justify-end mb-2">
                                                <Button
                                                    onClick={yamlContent ? handleDownloadYaml : handleGenerateYaml}
                                                    disabled={generating || (!asset.asset_name && !asset.tag_number)}
                                                    className={`h-8 w-8 p-0 rounded-full flex items-center justify-center transition-all ${yamlContent
                                                        ? "bg-sky-500 hover:bg-sky-400 text-white shadow-md shadow-sky-500/20"
                                                        : "bg-white/10 hover:bg-white/20 text-zinc-200 border border-white/10 shadow-sm"
                                                        }`}
                                                >
                                                    {generating ? (
                                                        <Loader2 className="h-4 w-4 animate-spin text-white" />
                                                    ) : (
                                                        <svg
                                                            xmlns="http://www.w3.org/2000/svg"
                                                            width="16"
                                                            height="16"
                                                            viewBox="0 0 24 24"
                                                            fill="none"
                                                            stroke="currentColor"
                                                            strokeWidth="2.5"
                                                            strokeLinecap="round"
                                                            strokeLinejoin="round"
                                                            className="h-4 w-4"
                                                        >
                                                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                                            <polyline points="7 10 12 15 17 10"></polyline>
                                                            <line x1="12" y1="15" x2="12" y2="3"></line>
                                                        </svg>
                                                    )}
                                                </Button>
                                            </div>

                                            {/* Asset Info with Image */}
                                            {(asset.asset_name || asset.tag_number || asset.manufacturer) && (
                                                <div className="space-y-2">
                                                    <h4 className="text-xs font-bold text-sky-400 uppercase tracking-wider">Asset</h4>
                                                    <div className="flex gap-3">
                                                        {/* Asset Image */}
                                                        <div className={`flex-shrink-0 w-20 h-20 rounded-lg border border-white/10 flex items-center justify-center overflow-hidden transition-all duration-300 ${assetImageUrl
                                                            ? "bg-white/90 shadow-inner"
                                                            : "bg-white/5"
                                                            }`}>
                                                            {assetImageLoading ? (
                                                                <Loader2 className="h-6 w-6 animate-spin text-sky-400/50" />
                                                            ) : assetImageUrl ? (
                                                                <img
                                                                    src={assetImageUrl}
                                                                    alt={asset.asset_type}
                                                                    onMouseEnter={() => {
                                                                        if (hideImageTimeout.current) clearTimeout(hideImageTimeout.current);
                                                                        setHoveredImage(assetImageUrl);
                                                                    }}
                                                                    onMouseLeave={() => {
                                                                        hideImageTimeout.current = setTimeout(() => setHoveredImage(null), 150);
                                                                    }}
                                                                    className="w-full h-full object-contain p-1.5 cursor-pointer hover:scale-110 transition-transform duration-500"
                                                                    onError={() => setAssetImageUrl(null)}
                                                                />
                                                            ) : (
                                                                <ImageIcon className="h-8 w-8 text-zinc-500" />
                                                            )}
                                                        </div>
                                                        {/* Asset Data */}
                                                        <div className="flex-1 space-y-1.5 text-xs">
                                                            {asset.asset_name && (
                                                                <div className="flex justify-between items-start">
                                                                    <span className="text-zinc-400">Name:</span>
                                                                    <span className="text-sky-300 font-medium text-right">{asset.asset_name}</span>
                                                                </div>
                                                            )}
                                                            {asset.asset_type && (
                                                                <div className="flex justify-between items-start">
                                                                    <span className="text-zinc-400">Type:</span>
                                                                    <span className="text-sky-300 font-medium text-right">{asset.asset_type}</span>
                                                                </div>
                                                            )}
                                                            {asset.tag_number && (
                                                                <div className="flex justify-between items-start">
                                                                    <span className="text-zinc-400">Tag:</span>
                                                                    <span className="text-sky-300 font-medium text-right">{asset.tag_number}</span>
                                                                </div>
                                                            )}
                                                            {asset.manufacturer && (
                                                                <div className="flex justify-between items-start">
                                                                    <span className="text-zinc-400">Manufacturer:</span>
                                                                    <span className="text-sky-300 font-medium text-right">{asset.manufacturer}</span>
                                                                </div>
                                                            )}
                                                            {asset.model && (
                                                                <div className="flex justify-between items-start">
                                                                    <span className="text-zinc-400">Model:</span>
                                                                    <span className="text-sky-300 font-medium text-right">{asset.model}</span>
                                                                </div>
                                                            )}
                                                            {asset.serial_number && (
                                                                <div className="flex justify-between items-start">
                                                                    <span className="text-zinc-400">Serial:</span>
                                                                    <span className="text-sky-300 font-medium text-right truncate">{asset.serial_number}</span>
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {/* Relationships */}
                                            {(relationships.migration.enabled || relationships.integration.enabled || relationships.configuration_pairing.enabled) && (
                                                <div className="space-y-2 pt-2 border-t border-white/20 dark:border-slate-600/20">
                                                    <h4 className="text-xs font-bold text-[#0F6CBD] dark:text-[#5FB3E6] uppercase tracking-wider">Relationships</h4>
                                                    <div className="space-y-1.5 text-xs">
                                                        {relationships.migration.enabled && (
                                                            <div className="flex justify-between items-start">
                                                                <span className="text-slate-600 dark:text-slate-400">Migration:</span>
                                                                <span className="text-[#004E8C] dark:text-[#5FB3E6] font-medium text-right">Enabled</span>
                                                            </div>
                                                        )}
                                                        {relationships.integration.enabled && (
                                                            <div className="flex justify-between items-start">
                                                                <span className="text-slate-600 dark:text-slate-400">Integration:</span>
                                                                <span className="text-[#004E8C] dark:text-[#5FB3E6] font-medium text-right">Enabled</span>
                                                            </div>
                                                        )}
                                                        {relationships.configuration_pairing.enabled && (
                                                            <div className="flex justify-between items-start">
                                                                <span className="text-slate-600 dark:text-slate-400">Config Pairing:</span>
                                                                <span className="text-[#004E8C] dark:text-[#5FB3E6] font-medium text-right">Enabled</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )}

                                            {/* ── Configuration Sections ── */}
                                            <div className="space-y-1 pt-2 border-t border-white/20 dark:border-slate-600/20">
                                                <div className="flex items-center gap-1.5 pb-1">
                                                    <BookOpen className="h-3.5 w-3.5 text-[#0F6CBD]" />
                                                    <h4 className="text-xs font-bold text-[#0F6CBD] dark:text-[#5FB3E6] uppercase tracking-wider">Configurations</h4>
                                                    {standards.loading && <Loader2 className="h-3 w-3 animate-spin text-[#0F6CBD] ml-auto" />}
                                                </div>

                                                {standards.found && Object.keys(standards.specifications || {}).length > 0 && (
                                                    <div className="space-y-0.5 text-xs mb-3">
                                                        <div className="flex items-center gap-1.5 pt-1 pb-1">
                                                            <Sparkles className="h-3 w-3 text-[#0F6CBD]" />
                                                            <span className="text-[10px] font-bold text-[#0F6CBD]/80 dark:text-[#5FB3E6]/80 uppercase tracking-wider">Applied Standards (RAG)</span>
                                                        </div>
                                                        {Object.entries(standards.specifications).map(([key, value]) => (
                                                            <div key={key} className="flex justify-between items-start gap-2 py-0.5">
                                                                <span className="text-slate-500 dark:text-slate-400 shrink-0">
                                                                    {key.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase())}:
                                                                </span>
                                                                <span className="text-[#004E8C] dark:text-[#5FB3E6] font-medium text-right break-words">
                                                                    {String(value)}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {([
                                                    {
                                                        id: "identity",
                                                        icon: <Radio className="h-3 w-3 text-[#0F6CBD]" />,
                                                        title: "Identity & Communication",
                                                        fields: [
                                                            { label: "Equipment Category", value: instrumentConfig.hart_identity.equipment_category },
                                                            { label: "HART Tag", value: instrumentConfig.hart_identity.hart_tag },
                                                            { label: "HART Long Tag", value: instrumentConfig.hart_identity.hart_long_tag },
                                                            { label: "Message", value: instrumentConfig.hart_identity.message },
                                                            { label: "Descriptor", value: instrumentConfig.hart_identity.descriptor },
                                                            { label: "Sensor Serial", value: instrumentConfig.hart_identity.sensor_serial },
                                                            { label: "Transmitter Serial", value: instrumentConfig.hart_identity.transmitter_serial },
                                                            { label: "Device Revision", value: instrumentConfig.hart_identity.device_revision },
                                                        ],
                                                    },
                                                    {
                                                        id: "calibration",
                                                        icon: <Settings2 className="h-3 w-3 text-[#0F6CBD]" />,
                                                        title: "Sensor & Calibration",
                                                        fields: [
                                                            { label: "Flow Cal. Factor", value: instrumentConfig.calibration.flow_calibration_factor },
                                                            { label: "Density Coeff D1", value: instrumentConfig.calibration.density_coeff_d1 },
                                                            { label: "Density Coeff D2", value: instrumentConfig.calibration.density_coeff_d2 },
                                                            { label: "Density Coeff D3", value: instrumentConfig.calibration.density_coeff_d3 },
                                                            { label: "Density Coeff D4", value: instrumentConfig.calibration.density_coeff_d4 },
                                                            { label: "Temp. Coefficient", value: instrumentConfig.calibration.temperature_coefficient },
                                                        ],
                                                    },
                                                    {
                                                        id: "pv_mapping",
                                                        icon: <BarChart2 className="h-3 w-3 text-[#0F6CBD]" />,
                                                        title: "PV Mapping",
                                                        fields: [
                                                            { label: "Primary Variable", value: instrumentConfig.pv_mapping.primary_variable },
                                                            { label: "Secondary Variable", value: instrumentConfig.pv_mapping.secondary_variable },
                                                            { label: "Tertiary Variable", value: instrumentConfig.pv_mapping.tertiary_variable },
                                                            { label: "Quaternary Variable", value: instrumentConfig.pv_mapping.quaternary_variable },
                                                            { label: "URV", value: instrumentConfig.pv_mapping.urv },
                                                            { label: "LRV", value: instrumentConfig.pv_mapping.lrv },
                                                            { label: "PV Units", value: instrumentConfig.pv_mapping.pv_units },
                                                        ],
                                                    },
                                                    {
                                                        id: "measurement_control",
                                                        icon: <SlidersHorizontal className="h-3 w-3 text-[#0F6CBD]" />,
                                                        title: "Measurement & Control",
                                                        fields: [
                                                            { label: "Damping", value: instrumentConfig.measurement_control.damping },
                                                            { label: "Low Flow Cutoff", value: instrumentConfig.measurement_control.low_flow_cutoff },
                                                            { label: "Flow Direction", value: instrumentConfig.measurement_control.flow_direction },
                                                            { label: "Fault Action", value: instrumentConfig.measurement_control.fault_action },
                                                            { label: "Totalizer", value: instrumentConfig.measurement_control.totalizer },
                                                            { label: "Measurement Units", value: instrumentConfig.measurement_control.measurement_units },
                                                        ],
                                                    },
                                                    {
                                                        id: "diagnostics",
                                                        icon: <Activity className="h-3 w-3 text-[#0F6CBD]" />,
                                                        title: "Diagnostics & Health",
                                                        fields: [
                                                            { label: "SMV Frequency", value: instrumentConfig.diagnostics_health.smv_frequency },
                                                            { label: "SMV Integrity", value: instrumentConfig.diagnostics_health.smv_integrity_enabled ? "Enabled" : "Disabled" },
                                                            { label: "Drive Gain Limit", value: instrumentConfig.diagnostics_health.drive_gain_limit },
                                                            { label: "Density Dev. Limit", value: instrumentConfig.diagnostics_health.density_deviation_limit },
                                                            { label: "Temp High Limit", value: instrumentConfig.diagnostics_health.temp_high_limit },
                                                            { label: "Electronics Limit", value: instrumentConfig.diagnostics_health.electronics_temp_limit },
                                                        ],
                                                    },
                                                ] as { id: string; icon: React.ReactNode; title: string; fields: { label: string; value: string | boolean | undefined }[] }[]).map((section) => (
                                                    <div key={section.id} className="space-y-0.5 text-xs">
                                                        {/* Section Header */}
                                                        <div className="flex items-center gap-1.5 pt-2 pb-0.5">
                                                            {section.icon}
                                                            <span className="text-[10px] font-bold text-[#0F6CBD]/80 dark:text-[#5FB3E6]/80 uppercase tracking-wider">{section.title}</span>
                                                        </div>
                                                        {/* Field Rows */}
                                                        {section.fields.map(({ label, value }) => (
                                                            <div key={label} className="flex justify-between items-start gap-2 py-0.5">
                                                                <span className="text-slate-500 dark:text-slate-400 shrink-0">{label}:</span>
                                                                <span className="text-[#004E8C] dark:text-[#5FB3E6] font-medium text-right break-words">
                                                                    {value !== undefined && value !== null && String(value).trim() !== "" && value !== "false"
                                                                        ? String(value)
                                                                        : "—"}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="flex flex-col items-center justify-center py-12">
                                            <Sparkles className="h-10 w-10 mb-3 text-[#0F6CBD]/30" />
                                            <p className="text-sm font-medium text-[#0F6CBD]">No data extracted yet</p>
                                            <p className="text-xs mt-1 text-slate-500 dark:text-slate-400">Start by describing your configuration in the chat</p>
                                        </div>
                                    )}
                                </div>
                        </div>
                    </div>
                </div>
            </div>


        </div>
    );
};

export default AssetConfiguration;
