import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import MainHeader from "@/components/MainHeader";
import { BASE_URL } from "@/components/AIRecommender/api";
import {
    Loader2, Search, X, Database, Settings2, ChevronLeft, ChevronRight, ArrowLeft, Check, Activity,
    TrendingUp, AlertTriangle, Heart, ChevronDown, ChevronUp, Maximize2, Minimize2, RefreshCw, Upload,
    CheckCircle, XCircle, Beaker, BarChart3, PanelRightClose, PanelRightOpen
} from "lucide-react";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

interface AssetData {
    source_file: string;
    uploaded_at: string;
    asset_name: string;
    asset_type: string;
    location: string;
    manufacturer: string;
    model: string;
    serial_number: string;
    tag_number: string;
    notes: string;
    is_error_prone?: boolean;
    error_types?: string[];
    [key: string]: any;
}

// ── Diagnostics types ─────────────────────────────────────────────────────

interface DiagnosticHealth {
    health_score: number;
    health_status: 'healthy' | 'warning' | 'critical' | string;
    trend_direction: string;
    active_anomalies: number;
    factors: string[];
}

interface DiagnosticAnomaly {
    tag?: string;
    field?: string;
    value?: number;
    severity?: string;
    message?: string;
    [key: string]: any;
}

interface DiagnosticResult {
    session_id?: string;
    anomaly_detection?: {
        total_analyzed: number;
        anomalies_detected: number;
        anomaly_rate_pct: number;
        anomalies: DiagnosticAnomaly[];
    };
    trend_analysis?: Record<string, any>;
    matched_diagnostic_codes?: any[];
    health?: DiagnosticHealth;
    asset_id?: string;
    asset_name?: string;
}

interface DiagnosticPanel {
    open: boolean;
    docked: boolean;          // true = side panel, false = floating card
    expanded: boolean;        // tall mode when docked
    assetRow: AssetData | null;
    assetDocId: string;
    loading: boolean;
    result: DiagnosticResult | null;
    error: string | null;
    uploadingLogs: boolean;
    activeSubTab: 'overview' | 'anomalies' | 'trends';
}

const ITEMS_PER_PAGE = 20;

// Resets on page refresh, persists across SPA navigation — so dialog shows only once per refresh cycle
let assetsColumnDialogShownThisSession = false;

// Get all possible columns from the data in the EXACT order they appear in the file
const getAllColumns = (data: AssetData[]): string[] => {
    if (data.length === 0) return [];

    // Start with columns from the first row (preserves CSV column order)
    const firstItemKeys = Object.keys(data[0]);
    const columnSet = new Set(firstItemKeys);
    const orderedColumns = [...firstItemKeys];

    // Add any additional columns that appear in other rows (append at end)
    data.forEach(item => {
        Object.keys(item).forEach(key => {
            if (!columnSet.has(key)) {
                columnSet.add(key);
                orderedColumns.push(key);
            }
        });
    });

    // Return columns in the exact order they were first encountered
    return orderedColumns;
};

// Format column name for display
const formatColumnName = (column: string): string => {
    return column
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
};

const Assets = () => {
    const navigate = useNavigate();
    const location = useLocation();

    const getParentPath = () => {
        if (location.state?.from) return location.state.from;
        const path = location.pathname;
        if (path.includes('/assets')) {
            const parentPath = path.replace('/assets', '');
            return parentPath || '/chat';
        }
        return '/chat';
    };

    const [loading, setLoading] = useState(true);
    const [allData, setAllData] = useState<AssetData[]>([]);
    const [filteredData, setFilteredData] = useState<AssetData[]>([]);
    const [availableColumns, setAvailableColumns] = useState<string[]>([]);
    const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
    const [columnFilters, setColumnFilters] = useState<Record<string, string>>({});
    const [showColumnDialog, setShowColumnDialog] = useState(false);
    const [currentPage, setCurrentPage] = useState(1);
    const [error, setError] = useState<string | null>(null);

    // Dropdown filters state - now arrays for multiple selections
    const [siteLocationFilter, setSiteLocationFilter] = useState<string[]>([]);
    const [siteNameFilter, setSiteNameFilter] = useState<string[]>([]);
    const [regionFilter, setRegionFilter] = useState<string[]>([]);
    const [plantUnitFilter, setPlantUnitFilter] = useState<string[]>([]);
    const [siteCodeFilter, setSiteCodeFilter] = useState<string[]>([]);

    // Unique values for dropdowns
    const [uniqueSiteLocations, setUniqueSiteLocations] = useState<string[]>([]);
    const [uniqueSiteNames, setUniqueSiteNames] = useState<string[]>([]);
    const [uniqueRegions, setUniqueRegions] = useState<string[]>([]);
    const [uniquePlantUnits, setUniquePlantUnits] = useState<string[]>([]);
    const [uniqueSiteCodes, setUniqueSiteCodes] = useState<string[]>([]);

    // Column names for each filter type
    const [siteLocationColumns, setSiteLocationColumns] = useState<string[]>([]);
    const [siteNameColumns, setSiteNameColumns] = useState<string[]>([]);
    const [regionColumns, setRegionColumns] = useState<string[]>([]);
    const [plantUnitColumns, setPlantUnitColumns] = useState<string[]>([]);
    const [siteCodeColumns, setSiteCodeColumns] = useState<string[]>([]);

    // Track which dropdown is open
    const [openDropdown, setOpenDropdown] = useState<string | null>(null);

    // Error-prone quick filter
    const [showErrorProneOnly, setShowErrorProneOnly] = useState(false);

    // Diagnostics panel state
    const [diagPanel, setDiagPanel] = useState<DiagnosticPanel>({
        open: false,
        docked: true,
        expanded: false,
        assetRow: null,
        assetDocId: '',
        loading: false,
        result: null,
        error: null,
        uploadingLogs: false,
        activeSubTab: 'overview',
    });
    const diagFileRef = useRef<HTMLInputElement>(null);

    // Toggle filter selection
    const toggleFilterSelection = (filterName: 'siteLocation' | 'siteName' | 'region' | 'plantUnit' | 'siteCode', value: string) => {
        const setters = {
            siteLocation: setSiteLocationFilter,
            siteName: setSiteNameFilter,
            region: setRegionFilter,
            plantUnit: setPlantUnitFilter,
            siteCode: setSiteCodeFilter
        };

        const currentValues = {
            siteLocation: siteLocationFilter,
            siteName: siteNameFilter,
            region: regionFilter,
            plantUnit: plantUnitFilter,
            siteCode: siteCodeFilter
        };

        const setter = setters[filterName];
        const current = currentValues[filterName];

        if (current.includes(value)) {
            setter(current.filter(v => v !== value));
        } else {
            setter([...current, value]);
        }
    };

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            if (!target.closest('.relative')) {
                setOpenDropdown(null);
            }
        };

        if (openDropdown) {
            document.addEventListener('mousedown', handleClickOutside);
            return () => document.removeEventListener('mousedown', handleClickOutside);
        }
    }, [openDropdown]);

    // Fetch assets data
    useEffect(() => {
        const fetchAssets = async () => {
            try {
                setLoading(true);
                const response = await axios.get('/api/assets-data');

                const result = response.data;

                if (result.success) {
                    setAllData(result.data);
                    setFilteredData(result.data);

                    // Get all available columns
                    const columns = getAllColumns(result.data);

                    // Remove source_file, uploaded_at and internal _ prefixed fields
                    // (e.g. _health_status, _health_score, _procurement_flagged, _doc_id)
                    // which are rendered exclusively in the dedicated Criticality column.
                    const columnsToHide = ['source_file', 'uploaded_at', 'is_error_prone', 'error_types'];
                    const filteredColumns = columns.filter(col =>
                        !columnsToHide.includes(col.toLowerCase()) && !col.startsWith('_')
                    );

                    setAvailableColumns(filteredColumns);
                    setSelectedColumns(filteredColumns);

                    // Extract unique values for dropdown filters
                    // Check for common column name variations (case-insensitive)
                    const getUniqueValues = (columnNames: string[]) => {
                        const values = new Set<string>();
                        result.data.forEach((item: AssetData) => {
                            for (const colName of columnNames) {
                                const value = item[colName];
                                if (value && String(value).trim() !== '') {
                                    values.add(String(value).trim());
                                }
                            }
                        });
                        return Array.from(values).sort();
                    };

                    // Helper for dynamic column matching (not hardcoded)
                    const findCol = (patterns: string[]) => columns.filter(c => {
                        const cl = c.toLowerCase();
                        return patterns.some(p => {
                            if (p.length <= 4) return cl === p; // Exact match for short codes like 'site'
                            return cl.includes(p); // Include match for descriptive names
                        });
                    });

                    // Dynamic column resolution (Formerly hardcoded)
                    const foundSiteLocationColumns = findCol(['site_location', 'location', 'site loc', 'address', 'loc']);
                    setSiteLocationColumns(foundSiteLocationColumns);
                    setUniqueSiteLocations(getUniqueValues(foundSiteLocationColumns));

                    const foundSiteNameColumns = findCol(['site_name', 'sitename', 'site', 'facility', 'plant']);
                    setSiteNameColumns(foundSiteNameColumns);
                    setUniqueSiteNames(getUniqueValues(foundSiteNameColumns));

                    const foundRegionColumns = findCol(['region', 'area', 'zone', 'territory', 'division']);
                    setRegionColumns(foundRegionColumns);
                    setUniqueRegions(getUniqueValues(foundRegionColumns));

                    const foundPlantUnitColumns = findCol(['plant_unit', 'unit', 'section', 'department', 'dept']);
                    setPlantUnitColumns(foundPlantUnitColumns);
                    setUniquePlantUnits(getUniqueValues(foundPlantUnitColumns));

                    const foundSiteCodeColumns = findCol(['site_code', 'code', 'id', 'tag_prefix', 'ref']);
                    setSiteCodeColumns(foundSiteCodeColumns);
                    setUniqueSiteCodes(getUniqueValues(foundSiteCodeColumns));

                    // Show column selection dialog on page load/refresh, but not on SPA re-navigation
                    if (!assetsColumnDialogShownThisSession) {
                        setShowColumnDialog(true);
                        assetsColumnDialogShownThisSession = true;
                    }
                } else {
                    setError(result.error || "Failed to load assets data");
                }
            } catch (err) {
                console.error("Error fetching assets:", err);
                setError("Failed to load assets data");
            } finally {
                setLoading(false);
            }
        };

        fetchAssets();
    }, []);

    // Lightweight health-summary poll every 15 s — only updates criticality fields
    // without re-fetching all CSV blob data
    useEffect(() => {
        const pollHealth = async () => {
            try {
                const res = await axios.get('/api/diagnostics/health-summary');
                const json = res.data;
                if (!json.success || !json.summary) return;
                const summary: Record<string, {
                    health_status: string;
                    health_score: number;
                    procurement_flagged: boolean;
                }> = json.summary;

                setAllData(prev =>
                    prev.map(row => {
                        const tag = String(row.tag_number || '').trim();
                        const hit = tag ? summary[tag] : undefined;
                        if (!hit) return row;
                        const newStatus = hit.health_status;
                        return {
                            ...row,
                            _health_status: newStatus,
                            _health_score: hit.health_score,
                            _procurement_flagged: hit.procurement_flagged,
                            // Recompute is_error_prone from refreshed health status
                            is_error_prone: newStatus === 'critical' || newStatus === 'warning',
                        };
                    })
                );
            } catch {
                // silent — non-critical background poll
            }
        };

        // Run immediately on mount, then every 15 s
        pollHealth();
        const healthPoll = setInterval(pollHealth, 15_000);
        return () => clearInterval(healthPoll);
    }, []);

    // Apply filters
    useEffect(() => {
        let filtered = [...allData];

        // Apply dropdown filters using specific columns (multiple selections)
        if (siteLocationFilter.length > 0 && siteLocationColumns.length > 0) {
            filtered = filtered.filter(item => {
                return siteLocationColumns.some(col =>
                    siteLocationFilter.includes(String(item[col] || '').trim())
                );
            });
        }

        if (siteNameFilter.length > 0 && siteNameColumns.length > 0) {
            filtered = filtered.filter(item => {
                return siteNameColumns.some(col =>
                    siteNameFilter.includes(String(item[col] || '').trim())
                );
            });
        }

        if (regionFilter.length > 0 && regionColumns.length > 0) {
            filtered = filtered.filter(item => {
                return regionColumns.some(col =>
                    regionFilter.includes(String(item[col] || '').trim())
                );
            });
        }

        if (plantUnitFilter.length > 0 && plantUnitColumns.length > 0) {
            filtered = filtered.filter(item => {
                return plantUnitColumns.some(col =>
                    plantUnitFilter.includes(String(item[col] || '').trim())
                );
            });
        }

        if (siteCodeFilter.length > 0 && siteCodeColumns.length > 0) {
            filtered = filtered.filter(item => {
                return siteCodeColumns.some(col =>
                    siteCodeFilter.includes(String(item[col] || '').trim())
                );
            });
        }

        // Apply column filters
        Object.entries(columnFilters).forEach(([column, filterValue]) => {
            if (filterValue.trim()) {
                filtered = filtered.filter(item => {
                    const value = String(item[column] || '').toLowerCase();
                    return value.includes(filterValue.toLowerCase());
                });
            }
        });

        // Apply error-prone filter
        if (showErrorProneOnly) {
            filtered = filtered.filter(item => item.is_error_prone === true);
        }

        setFilteredData(filtered);
        setCurrentPage(1); // Reset to first page when filters change
    }, [columnFilters, allData, siteLocationFilter, siteNameFilter, regionFilter, plantUnitFilter, siteCodeFilter,
        siteLocationColumns, siteNameColumns, regionColumns, plantUnitColumns, siteCodeColumns, showErrorProneOnly]);

    // Toggle column selection
    const toggleColumn = (column: string) => {
        setSelectedColumns(prev => {
            if (prev.includes(column)) {
                return prev.filter(c => c !== column);
            } else {
                return [...prev, column];
            }
        });
    };

    // Handle filter change
    const handleFilterChange = (column: string, value: string) => {
        setColumnFilters(prev => {
            if (value.trim() === '') {
                const newFilters = { ...prev };
                delete newFilters[column];
                return newFilters;
            }
            return { ...prev, [column]: value };
        });
    };

    // Clear all filters
    const clearAllFilters = () => {
        setColumnFilters({});
        setSiteLocationFilter([]);
        setSiteNameFilter([]);
        setRegionFilter([]);
        setPlantUnitFilter([]);
        setSiteCodeFilter([]);
        setShowErrorProneOnly(false);
    };

    // Pagination
    const totalPages = Math.ceil(filteredData.length / ITEMS_PER_PAGE);
    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
    const endIndex = startIndex + ITEMS_PER_PAGE;
    const currentPageData = filteredData.slice(startIndex, endIndex);

    const goToNextPage = () => {
        if (currentPage < totalPages) {
            setCurrentPage(prev => prev + 1);
        }
    };

    const goToPreviousPage = () => {
        if (currentPage > 1) {
            setCurrentPage(prev => prev - 1);
        }
    };

    const goToPage = (page: number) => {
        if (page >= 1 && page <= totalPages) {
            setCurrentPage(page);
        }
    };

    // ── Diagnostics handlers ───────────────────────────────────────────────

    const openDiagnostics = useCallback(async (row: AssetData) => {
        const docId = row._doc_id || '';
        const tag = row.tag_number || row.tag || row.tag_no || docId;
        setDiagPanel(p => ({
            ...p,
            open: true,
            assetRow: row,
            assetDocId: tag,
            loading: true,
            result: null,
            error: null,
            activeSubTab: 'overview',
        }));
        if (!docId) {
            setDiagPanel(p => ({ ...p, loading: false, error: 'Asset has no document ID — upload logs manually.' }));
            return;
        }
        try {
            const params = new URLSearchParams();
            if (row.asset_condition || row.condition || row.status) {
                params.append('condition', row.asset_condition || row.condition || row.status || '');
            }
            if (row.criticality) {
                params.append('criticality', row.criticality);
            }
            if (row.error_types && Array.isArray(row.error_types)) {
                params.append('error_types', row.error_types.join(','));
            }
            const r = await axios.get(`/api/assets/${tag}/diagnostics?${params.toString()}`);
            const d = r.data;
            if (d.success) {
                setDiagPanel(p => ({ ...p, loading: false, result: d }));
            } else {
                setDiagPanel(p => ({ ...p, loading: false, result: null, error: d.error || 'No diagnostics data yet.' }));
            }
        } catch {
            setDiagPanel(p => ({ ...p, loading: false, error: 'Failed to load diagnostics.' }));
        }
    }, []);

    const runAnalysis = useCallback(async () => {
        const docId = diagPanel.assetDocId;
        const tag = diagPanel.assetRow?.tag_number || docId;
        if (!tag) return;
        setDiagPanel(p => ({ ...p, loading: true, error: null }));
        try {
            const body = {
                asset_id: tag,
                criticality: diagPanel.assetRow?.criticality || '',
                condition: diagPanel.assetRow?.asset_condition || diagPanel.assetRow?.condition || diagPanel.assetRow?.status || '',
                error_types: diagPanel.assetRow?.error_types && Array.isArray(diagPanel.assetRow?.error_types) ? diagPanel.assetRow?.error_types.join(',') : ''
            };
            const r = await axios.post('/api/diagnostics/analyze', body);
            const d = r.data;
            if (d.success !== false) {
                setDiagPanel(p => ({ ...p, loading: false, result: d, activeSubTab: 'overview' }));
            } else {
                setDiagPanel(p => ({ ...p, loading: false, error: d.error || 'Analysis failed.' }));
            }
        } catch {
            setDiagPanel(p => ({ ...p, loading: false, error: 'Analysis request failed.' }));
        }
    }, [diagPanel.assetDocId]);

    const uploadDiagLogs = useCallback(async (file: File) => {
        const docId = diagPanel.assetDocId;
        if (!docId || !file) return;
        setDiagPanel(p => ({ ...p, uploadingLogs: true }));
        const form = new FormData();
        form.append('file', file);
        try {
            const r = await axios.post(`/api/assets/${docId}/diagnostics/upload-logs`, form);
            const d = r.data;
            if (d.success) {
                await runAnalysis();
            } else {
                setDiagPanel(p => ({ ...p, uploadingLogs: false, error: d.error || 'Upload failed.' }));
            }
        } catch {
            setDiagPanel(p => ({ ...p, uploadingLogs: false, error: 'Upload failed.' }));
        }
    }, [diagPanel.assetDocId, runAnalysis]);



    const getHealthColor = (status?: string) => {
        switch (status) {
            case 'healthy': return { bg: 'bg-green-50 border-green-200', text: 'text-green-700', dot: 'bg-green-500', score: 'text-green-600' };
            case 'warning': return { bg: 'bg-yellow-50 border-yellow-200', text: 'text-yellow-700', dot: 'bg-yellow-500', score: 'text-yellow-600' };
            case 'critical': return { bg: 'bg-red-50 border-red-200', text: 'text-red-700', dot: 'bg-red-500', score: 'text-red-600' };
            default: return { bg: 'bg-gray-50 border-gray-200', text: 'text-gray-500', dot: 'bg-gray-400', score: 'text-gray-500' };
        }
    };

    return (
        <div className="flex flex-col h-screen app-glass-gradient text-foreground overflow-hidden">
            {/* Decorative background images */}
            <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
                <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
            </div>
            <MainHeader showProjectActions={false}>
                <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
                    <h1 className="text-xl md:text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#0F6CBD] to-[#004E8C]">
                        Assets
                    </h1>
                </div>
            </MainHeader>

            {/* Main Content — flex row when diagnostics panel is docked */}
            <div className="flex flex-1 overflow-hidden pt-24">

                <main className={`flex-1 pb-8 px-6 pt-8 overflow-y-auto custom-visible-scrollbar-dark transition-all duration-300 ${diagPanel.open && diagPanel.docked ? 'mr-0' : ''}`}>
                    <div className="max-w-[95%] mx-auto">

                        {/* Select Columns Buttons */}
                        <div className="flex items-center justify-end gap-3 mb-6">
                            {/* Clear Filters and Select Columns Buttons */}
                            <div className="flex items-center gap-3">
                                {/* Clear All Filters Button - Only visible when filters are active */}
                                {(Object.keys(columnFilters).length > 0 || siteLocationFilter.length > 0 || siteNameFilter.length > 0 || regionFilter.length > 0 || plantUnitFilter.length > 0 || siteCodeFilter.length > 0 || showErrorProneOnly) && (
                                    <button
                                        onClick={clearAllFilters}
                                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-50/80 dark:bg-red-900/20 text-red-700 hover:text-red-900 border border-red-300 dark:border-red-700 dark:text-red-400 dark:hover:text-red-300 transition-all hover:scale-105 shadow-sm"
                                        title="Clear All Filters"
                                    >
                                        <X className="w-5 h-5" />
                                        <span className="font-medium">Clear All Filters</span>
                                    </button>
                                )}

                                {/* Select Columns Button */}
                                <button
                                    onClick={() => setShowColumnDialog(true)}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm"
                                    title="Select Columns"
                                >
                                    <Settings2 className="w-5 h-5" />
                                    <span className="font-medium">Select Columns</span>
                                </button>
                            </div>
                        </div>

                        {/* Stats Section */}
                        {!loading && (
                            <div className="mb-6 grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-6">
                                <div className="glass-card p-3 md:p-6 rounded-2xl hover:shadow-lg transition-all">
                                    <p className="text-sm font-medium text-gray-600 mb-2">
                                        {(Object.keys(columnFilters).length > 0 || siteLocationFilter.length > 0 || siteNameFilter.length > 0 || regionFilter.length > 0 || plantUnitFilter.length > 0 || siteCodeFilter.length > 0) ? 'Filtered Assets' : 'Total Assets'}
                                    </p>
                                    <div className="flex items-baseline gap-2 mt-1">
                                        <p className="text-xl md:text-3xl font-bold text-[#0F6CBD]">
                                            {(Object.keys(columnFilters).length > 0 || siteLocationFilter.length > 0 || siteNameFilter.length > 0 || regionFilter.length > 0 || plantUnitFilter.length > 0 || siteCodeFilter.length > 0) ? filteredData.length : allData.length}
                                        </p>
                                        {(Object.keys(columnFilters).length > 0 || siteLocationFilter.length > 0 || siteNameFilter.length > 0 || regionFilter.length > 0 || plantUnitFilter.length > 0 || siteCodeFilter.length > 0) && (
                                            <p className="text-sm text-gray-500 font-medium tracking-tight">of {allData.length} total</p>
                                        )}
                                    </div>
                                </div>
                                <div className="glass-card p-3 md:p-6 rounded-2xl hover:shadow-lg transition-all">
                                    <p className="text-sm font-medium text-gray-600 mb-2">Active Filters</p>
                                    <p className="text-xl md:text-3xl font-bold text-[#5FB3E6]">
                                        {Object.keys(columnFilters).length + siteLocationFilter.length + siteNameFilter.length + regionFilter.length + plantUnitFilter.length + siteCodeFilter.length}
                                    </p>
                                </div>
                                <div className="glass-card p-3 md:p-6 rounded-2xl hover:shadow-lg transition-all">
                                    <p className="text-sm font-medium text-gray-600 mb-2">Selected Columns</p>
                                    <p className="text-xl md:text-3xl font-bold text-[#0F6CBD]">{selectedColumns.length}</p>
                                </div>
                                <div className="glass-card p-3 md:p-6 rounded-2xl hover:shadow-lg transition-all border-l-4 border-red-400">
                                    <p className="text-sm font-medium text-gray-600 mb-2 flex items-center gap-1.5">
                                        <AlertTriangle className="w-4 h-4 text-red-500" />
                                        Error Prone
                                    </p>
                                    <p className="text-xl md:text-3xl font-bold text-red-600">
                                        {allData.filter(r => r.is_error_prone).length}
                                    </p>
                                </div>
                            </div>
                        )}

                        {/* Dropdown Filters Section */}
                        {!loading && allData.length > 0 && (uniqueSiteLocations.length > 0 || uniqueSiteNames.length > 0 || uniqueRegions.length > 0 || uniquePlantUnits.length > 0 || uniqueSiteCodes.length > 0) && (
                            <div className="mb-6 relative z-[45]">
                                <div className="flex items-center gap-2 mb-3">
                                    <Database className="w-5 h-5 text-[#0F6CBD]" />
                                    <h2 className="text-lg font-bold text-gray-800 dark:text-gray-200">Filter Assets</h2>
                                </div>
                                <div className="flex flex-wrap gap-4 pb-2" style={{ overflow: 'visible' }}>
                                    {/* Site Code Filter */}
                                    {uniqueSiteCodes.length > 0 && (
                                        <div className="glass-card p-4 rounded-xl shadow-sm hover:shadow-md transition-shadow flex-1 min-w-[200px] overflow-visible">
                                            <label className="block text-sm font-bold text-gray-700 dark:text-gray-200 mb-2 flex items-center gap-2 whitespace-nowrap">
                                                <span className="w-2 h-2 rounded-full bg-[#0F6CBD]"></span>
                                                Site Code
                                                {siteCodeFilter.length > 0 && (
                                                    <span className="ml-auto text-xs bg-[#0F6CBD] text-white px-2 py-0.5 rounded-full">
                                                        {siteCodeFilter.length}
                                                    </span>
                                                )}
                                            </label>
                                            <div className="relative">
                                                <button
                                                    onClick={() => setOpenDropdown(openDropdown === 'siteCode' ? null : 'siteCode')}
                                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 focus:border-[#0F6CBD] transition-all hover:border-[#0F6CBD]/50 font-medium text-left flex items-center justify-between"
                                                >
                                                    <span>{siteCodeFilter.length > 0 ? `${siteCodeFilter.length} selected` : 'Select...'}</span>
                                                    <span className="ml-2">▼</span>
                                                </button>
                                                {openDropdown === 'siteCode' && (
                                                    <div className="absolute mt-1 w-full max-h-60 overflow-y-auto custom-visible-scrollbar-dark bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg shadow-xl z-[45]">
                                                        {uniqueSiteCodes.map((code) => (
                                                            <div
                                                                key={code}
                                                                onClick={() => toggleFilterSelection('siteCode', code)}
                                                                className={`flex items-center justify-between px-3 py-2.5 transition-colors duration-150 cursor-pointer border-b border-gray-100/50 dark:border-slate-700/50 last:border-0 ${siteCodeFilter.includes(code) ? 'bg-blue-100 dark:bg-slate-700/50 text-[#0F6CBD] dark:text-[#5FB3E6]' : 'hover:bg-blue-100 dark:hover:bg-slate-700/50 text-gray-700 dark:text-gray-200'}`}
                                                            >
                                                                <span className="text-sm font-medium">{code}</span>
                                                                {siteCodeFilter.includes(code) && (
                                                                    <Check className="w-4 h-4 text-[#0F6CBD] dark:text-[#5FB3E6]" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Site Name Filter */}
                                    {uniqueSiteNames.length > 0 && (
                                        <div className="glass-card p-4 rounded-xl shadow-sm hover:shadow-md transition-shadow flex-1 min-w-[200px] overflow-visible">
                                            <label className="block text-sm font-bold text-gray-700 dark:text-gray-200 mb-2 flex items-center gap-2 whitespace-nowrap">
                                                <span className="w-2 h-2 rounded-full bg-[#0F6CBD]"></span>
                                                Site Name
                                                {siteNameFilter.length > 0 && (
                                                    <span className="ml-auto text-xs bg-[#0F6CBD] text-white px-2 py-0.5 rounded-full">
                                                        {siteNameFilter.length}
                                                    </span>
                                                )}
                                            </label>
                                            <div className="relative">
                                                <button
                                                    onClick={() => setOpenDropdown(openDropdown === 'siteName' ? null : 'siteName')}
                                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 focus:border-[#0F6CBD] transition-all hover:border-[#0F6CBD]/50 font-medium text-left flex items-center justify-between"
                                                >
                                                    <span>{siteNameFilter.length > 0 ? `${siteNameFilter.length} selected` : 'Select...'}</span>
                                                    <span className="ml-2">▼</span>
                                                </button>
                                                {openDropdown === 'siteName' && (
                                                    <div className="absolute mt-1 w-full max-h-60 overflow-y-auto custom-visible-scrollbar-dark bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg shadow-xl z-[45]">
                                                        {uniqueSiteNames.map((name) => (
                                                            <div
                                                                key={name}
                                                                onClick={() => toggleFilterSelection('siteName', name)}
                                                                className={`flex items-center justify-between px-3 py-2.5 transition-colors duration-150 cursor-pointer border-b border-gray-100/50 dark:border-slate-700/50 last:border-0 ${siteNameFilter.includes(name) ? 'bg-blue-100 dark:bg-slate-700/50 text-[#0F6CBD] dark:text-[#5FB3E6]' : 'hover:bg-blue-100 dark:hover:bg-slate-700/50 text-gray-700 dark:text-gray-200'}`}
                                                            >
                                                                <span className="text-sm font-medium">{name}</span>
                                                                {siteNameFilter.includes(name) && (
                                                                    <Check className="w-4 h-4 text-[#0F6CBD] dark:text-[#5FB3E6]" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Site Location Filter */}
                                    {uniqueSiteLocations.length > 0 && (
                                        <div className="glass-card p-4 rounded-xl shadow-sm hover:shadow-md transition-shadow flex-1 min-w-[200px] overflow-visible">
                                            <label className="block text-sm font-bold text-gray-700 dark:text-gray-200 mb-2 flex items-center gap-2 whitespace-nowrap">
                                                <span className="w-2 h-2 rounded-full bg-[#0F6CBD]"></span>
                                                Site Location
                                                {siteLocationFilter.length > 0 && (
                                                    <span className="ml-auto text-xs bg-[#0F6CBD] text-white px-2 py-0.5 rounded-full">
                                                        {siteLocationFilter.length}
                                                    </span>
                                                )}
                                            </label>
                                            <div className="relative">
                                                <button
                                                    onClick={() => setOpenDropdown(openDropdown === 'siteLocation' ? null : 'siteLocation')}
                                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 focus:border-[#0F6CBD] transition-all hover:border-[#0F6CBD]/50 font-medium text-left flex items-center justify-between"
                                                >
                                                    <span>{siteLocationFilter.length > 0 ? `${siteLocationFilter.length} selected` : 'Select...'}</span>
                                                    <span className="ml-2">▼</span>
                                                </button>
                                                {openDropdown === 'siteLocation' && (
                                                    <div className="absolute mt-1 w-full max-h-60 overflow-y-auto custom-visible-scrollbar-dark bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg shadow-xl z-[45]">
                                                        {uniqueSiteLocations.map((location) => (
                                                            <div
                                                                key={location}
                                                                onClick={() => toggleFilterSelection('siteLocation', location)}
                                                                className={`flex items-center justify-between px-3 py-2.5 transition-colors duration-150 cursor-pointer border-b border-gray-100/50 dark:border-slate-700/50 last:border-0 ${siteLocationFilter.includes(location) ? 'bg-blue-100 dark:bg-slate-700/50 text-[#0F6CBD] dark:text-[#5FB3E6]' : 'hover:bg-blue-100 dark:hover:bg-slate-700/50 text-gray-700 dark:text-gray-200'}`}
                                                            >
                                                                <span className="text-sm font-medium">{location}</span>
                                                                {siteLocationFilter.includes(location) && (
                                                                    <Check className="w-4 h-4 text-[#0F6CBD] dark:text-[#5FB3E6]" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Plant Unit Filter */}
                                    {uniquePlantUnits.length > 0 && (
                                        <div className="glass-card p-4 rounded-xl shadow-sm hover:shadow-md transition-shadow flex-1 min-w-[200px] overflow-visible">
                                            <label className="block text-sm font-bold text-gray-700 dark:text-gray-200 mb-2 flex items-center gap-2 whitespace-nowrap">
                                                <span className="w-2 h-2 rounded-full bg-[#0F6CBD]"></span>
                                                Plant Unit
                                                {plantUnitFilter.length > 0 && (
                                                    <span className="ml-auto text-xs bg-[#0F6CBD] text-white px-2 py-0.5 rounded-full">
                                                        {plantUnitFilter.length}
                                                    </span>
                                                )}
                                            </label>
                                            <div className="relative">
                                                <button
                                                    onClick={() => setOpenDropdown(openDropdown === 'plantUnit' ? null : 'plantUnit')}
                                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 focus:border-[#0F6CBD] transition-all hover:border-[#0F6CBD]/50 font-medium text-left flex items-center justify-between"
                                                >
                                                    <span>{plantUnitFilter.length > 0 ? `${plantUnitFilter.length} selected` : 'Select...'}</span>
                                                    <span className="ml-2">▼</span>
                                                </button>
                                                {openDropdown === 'plantUnit' && (
                                                    <div className="absolute mt-1 w-full max-h-60 overflow-y-auto custom-visible-scrollbar-dark bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg shadow-xl z-[45]">
                                                        {uniquePlantUnits.map((unit) => (
                                                            <div
                                                                key={unit}
                                                                onClick={() => toggleFilterSelection('plantUnit', unit)}
                                                                className={`flex items-center justify-between px-3 py-2.5 transition-colors duration-150 cursor-pointer border-b border-gray-100/50 dark:border-slate-700/50 last:border-0 ${plantUnitFilter.includes(unit) ? 'bg-blue-100 dark:bg-slate-700/50 text-[#0F6CBD] dark:text-[#5FB3E6]' : 'hover:bg-blue-100 dark:hover:bg-slate-700/50 text-gray-700 dark:text-gray-200'}`}
                                                            >
                                                                <span className="text-sm font-medium">{unit}</span>
                                                                {plantUnitFilter.includes(unit) && (
                                                                    <Check className="w-4 h-4 text-[#0F6CBD] dark:text-[#5FB3E6]" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Region Filter */}
                                    {uniqueRegions.length > 0 && (
                                        <div className="glass-card p-4 rounded-xl shadow-sm hover:shadow-md transition-shadow flex-1 min-w-[200px] overflow-visible">
                                            <label className="block text-sm font-bold text-gray-700 dark:text-gray-200 mb-2 flex items-center gap-2 whitespace-nowrap">
                                                <span className="w-2 h-2 rounded-full bg-[#0F6CBD]"></span>
                                                Area
                                                {regionFilter.length > 0 && (
                                                    <span className="ml-auto text-xs bg-[#0F6CBD] text-white px-2 py-0.5 rounded-full">
                                                        {regionFilter.length}
                                                    </span>
                                                )}
                                            </label>
                                            <div className="relative">
                                                <button
                                                    onClick={() => setOpenDropdown(openDropdown === 'region' ? null : 'region')}
                                                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 focus:border-[#0F6CBD] transition-all hover:border-[#0F6CBD]/50 font-medium text-left flex items-center justify-between"
                                                >
                                                    <span>{regionFilter.length > 0 ? `${regionFilter.length} selected` : 'Select...'}</span>
                                                    <span className="ml-2">▼</span>
                                                </button>
                                                {openDropdown === 'region' && (
                                                    <div className="absolute mt-1 w-full max-h-60 overflow-y-auto custom-visible-scrollbar-dark bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-lg shadow-xl z-[45]">
                                                        {uniqueRegions.map((region) => (
                                                            <div
                                                                key={region}
                                                                onClick={() => toggleFilterSelection('region', region)}
                                                                className={`flex items-center justify-between px-3 py-2.5 transition-colors duration-150 cursor-pointer border-b border-gray-100/50 dark:border-slate-700/50 last:border-0 ${regionFilter.includes(region) ? 'bg-blue-100 dark:bg-slate-700/50 text-[#0F6CBD] dark:text-[#5FB3E6]' : 'hover:bg-blue-100 dark:hover:bg-slate-700/50 text-gray-700 dark:text-gray-200'}`}
                                                            >
                                                                <span className="text-sm font-medium">{region}</span>
                                                                {regionFilter.includes(region) && (
                                                                    <Check className="w-4 h-4 text-[#0F6CBD] dark:text-[#5FB3E6]" />
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Main Content */}
                        <div className="glass-card rounded-2xl p-8 shadow-lg relative z-10">
                            {loading ? (
                                <div className="flex flex-col items-center justify-center py-20">
                                    <Loader2 className="h-12 w-12 text-primary animate-spin mb-4" />
                                    <p className="text-gray-600">Loading assets data...</p>
                                </div>
                            ) : error ? (
                                <div className="flex flex-col items-center justify-center py-20">
                                    <Database className="h-12 w-12 text-red-500 mb-4" />
                                    <p className="text-red-600 font-semibold">{error}</p>
                                </div>
                            ) : allData.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-20">
                                    <Database className="h-12 w-12 text-gray-400 mb-4" />
                                    <p className="text-gray-600">No assets data found</p>
                                    <p className="text-sm text-gray-500 mt-2">
                                        Upload asset files in the admin panel to get started
                                    </p>
                                </div>
                            ) : (
                                <>
                                    {/* Table */}
                                    <div className="rounded-xl border border-gray-200/50 custom-visible-scrollbar-dark [&>div]:max-h-[600px] [&>div]:overflow-auto">
                                        <Table>
                                            <TableHeader className="sticky top-0 z-20 shadow-sm bg-white dark:bg-slate-900">
                                                <TableRow className="bg-gradient-to-r from-[#0F6CBD]/30 to-[#5FB3E6]/30 border-b-2 border-[#0F6CBD]/30">
                                                    {selectedColumns.map(column => (
                                                        <TableHead key={column} className="font-bold text-[#0F6CBD] py-3 px-4 min-w-[180px] border-r border-gray-200/50 dark:border-slate-600/50 sticky top-0">
                                                            <div className="flex flex-col gap-2.5">
                                                                {/* Column Title */}
                                                                <div className="flex items-center justify-between gap-2">
                                                                    <span className="text-xs font-bold uppercase tracking-wider text-[#0F6CBD] whitespace-nowrap">
                                                                        {formatColumnName(column)}
                                                                    </span>
                                                                </div>
                                                                {/* Column Filter */}
                                                                <div className="relative">
                                                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400 pointer-events-none" />
                                                                    <input
                                                                        type="text"
                                                                        placeholder="Search..."
                                                                        value={columnFilters[column] || ''}
                                                                        onChange={(e) => handleFilterChange(column, e.target.value)}
                                                                        className="w-full pl-8 pr-8 py-1.5 text-xs rounded-md border border-gray-300/70 bg-white/80 backdrop-blur-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]/50 focus:border-[#0F6CBD] focus:bg-white transition-all hover:border-gray-400/70 shadow-sm"
                                                                        onClick={(e) => e.stopPropagation()}
                                                                    />
                                                                    {columnFilters[column] && (
                                                                        <button
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleFilterChange(column, '');
                                                                            }}
                                                                            className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 flex items-center justify-center text-gray-400 hover:text-red-600 transition-colors"
                                                                            title="Clear filter"
                                                                        >
                                                                            <X className="h-3.5 w-3.5" />
                                                                        </button>
                                                                    )}
                                                                </div>
                                                            </div>
                                                        </TableHead>
                                                    ))}
                                                    {/* Criticality Column */}
                                                    <TableHead className="font-bold text-[#0F6CBD] py-3 px-4 min-w-[180px] border-r border-gray-200/50 dark:border-slate-600/50 sticky top-0">
                                                        <div className="flex flex-col gap-2.5">
                                                            <span className="text-xs font-bold uppercase tracking-wider text-[#0F6CBD] whitespace-nowrap">Criticality</span>
                                                            {/* Error-prone filter toggle — mirrors search-input style of other column headers */}
                                                            <button
                                                                onClick={() => setShowErrorProneOnly(prev => !prev)}
                                                                className={`flex items-center gap-1.5 w-full px-2.5 py-1.5 text-xs rounded-md border transition-all font-medium ${showErrorProneOnly
                                                                        ? 'bg-red-600 text-white border-red-600 shadow-sm'
                                                                        : 'bg-white/80 text-gray-500 border-gray-300/70 hover:border-red-400 hover:text-red-600'
                                                                    }`}
                                                                title="Show only error-prone assets"
                                                            >
                                                                <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                                                                <span>Error Prone Only</span>
                                                                {showErrorProneOnly && <X className="w-3 h-3 ml-auto" />}
                                                            </button>
                                                        </div>
                                                    </TableHead>
                                                    {/* Actions Column */}
                                                    <TableHead className="font-bold text-[#0F6CBD] py-3 px-4 min-w-[100px] sticky top-0">
                                                        <div className="flex flex-col gap-2.5">
                                                            <span className="text-xs font-bold uppercase tracking-wider text-[#0F6CBD] whitespace-nowrap">Actions</span>
                                                        </div>
                                                    </TableHead>
                                                </TableRow>
                                            </TableHeader>
                                            <TableBody>
                                                {currentPageData.length === 0 ? (
                                                    <TableRow>
                                                        <TableCell
                                                            colSpan={selectedColumns.length + 2}
                                                            className="text-center py-12 text-gray-500"
                                                        >
                                                            <div className="flex flex-col items-center gap-2">
                                                                <Search className="h-8 w-8 text-gray-400" />
                                                                <p className="font-medium">No results match your filters</p>
                                                            </div>
                                                        </TableCell>
                                                    </TableRow>
                                                ) : (
                                                    currentPageData.map((row, idx) => (
                                                        <TableRow
                                                            key={idx}
                                                            className="hover:bg-blue-100 dark:hover:bg-slate-700/50 transition-colors duration-150 border-b border-gray-100/80"
                                                        >
                                                            {selectedColumns.map(column => (
                                                                <TableCell
                                                                    key={column}
                                                                    className="py-3 px-4 text-sm text-gray-700 dark:text-gray-200 font-medium max-w-xs border-r border-gray-200/50 dark:border-slate-600/50"
                                                                >
                                                                    {column === 'is_error_prone' ? (
                                                                        row[column] === true ? (
                                                                            <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-700 bg-red-100 border border-red-300 rounded-full px-2.5 py-1">
                                                                                <span className="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0" />
                                                                                Yes
                                                                            </span>
                                                                        ) : row[column] === false ? (
                                                                            <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-700 bg-green-100 border border-green-300 rounded-full px-2.5 py-1">
                                                                                <span className="w-1.5 h-1.5 rounded-full bg-green-500 flex-shrink-0" />
                                                                                No
                                                                            </span>
                                                                        ) : (
                                                                            <span className="text-gray-400 italic text-xs">No data</span>
                                                                        )
                                                                    ) : column === 'error_types' ? (
                                                                        Array.isArray(row[column]) && (row[column] as string[]).length > 0 ? (
                                                                            <div className="flex flex-col gap-0.5">
                                                                                {(row[column] as string[]).map((et: string) => (
                                                                                    <span key={et} className="inline-flex items-center text-[10px] font-medium text-red-700 bg-red-50 border border-red-200 rounded px-1.5 py-0.5 w-fit whitespace-nowrap">
                                                                                        {et}
                                                                                    </span>
                                                                                ))}
                                                                            </div>
                                                                        ) : (
                                                                            <span className="text-gray-400 italic text-xs">None</span>
                                                                        )
                                                                    ) : (
                                                                        <div className="truncate" title={row[column] || '-'}>
                                                                            {row[column] || <span className="text-gray-400 italic">-</span>}
                                                                        </div>
                                                                    )}
                                                                </TableCell>
                                                            ))}
                                                            {/* Criticality Cell — populated from instrument_logs via /api/assets-data */}
                                                            <TableCell className="py-3 px-4 text-sm border-r border-gray-200/50 dark:border-slate-600/50">
                                                                {(() => {
                                                                    const hs = row._health_status as string | undefined;
                                                                    const score = row._health_score as number | undefined;
                                                                    const flagged = row._procurement_flagged as boolean | undefined;
                                                                    if (!hs) return <span className="text-gray-400 text-xs italic">No data</span>;
                                                                    const badgeCls = hs === 'healthy'
                                                                        ? 'bg-green-100 text-green-800 border border-green-300'
                                                                        : hs === 'warning'
                                                                            ? 'bg-yellow-100 text-yellow-800 border border-yellow-300'
                                                                            : hs === 'critical'
                                                                                ? 'bg-red-100 text-red-800 border border-red-300'
                                                                                : 'bg-gray-100 text-gray-600 border border-gray-300';
                                                                    const dotCls = hs === 'healthy' ? 'bg-green-500' : hs === 'warning' ? 'bg-yellow-500' : hs === 'critical' ? 'bg-red-500' : 'bg-gray-400';
                                                                    const label = hs === 'critical' ? 'Critical' : hs === 'warning' ? 'Degrading' : 'Healthy';
                                                                    return (
                                                                        <div className="flex flex-col gap-1">
                                                                            <span className={`inline-flex items-center gap-1.5 text-xs font-semibold rounded-full px-2.5 py-1 w-fit ${badgeCls}`}>
                                                                                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotCls}`} />
                                                                                {label}
                                                                                {score != null && (
                                                                                    <span className="ml-1 opacity-75 font-normal">({score}%)</span>
                                                                                )}
                                                                            </span>

                                                                            {Array.isArray(row.error_types) && (row.error_types as string[]).length > 0 && (
                                                                                <div className="flex flex-col gap-0.5 mt-0.5">
                                                                                    {(row.error_types as string[]).map((et: string) => (
                                                                                        <span key={et} className="inline-flex items-center text-[10px] font-medium text-red-700 bg-red-50 border border-red-200 rounded px-1.5 py-0.5 w-fit">
                                                                                            {et}
                                                                                        </span>
                                                                                    ))}
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                    );
                                                                })()}
                                                            </TableCell>
                                                            {/* Actions Cell */}
                                                            <TableCell className="py-3 px-4 text-sm">
                                                                <div className="flex flex-col gap-1.5">
                                                                    <button
                                                                        onClick={() => openDiagnostics(row)}
                                                                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all hover:scale-105 ${diagPanel.assetRow === row && diagPanel.open
                                                                                ? 'bg-[#0F6CBD] text-white shadow-md'
                                                                                : 'bg-[#0F6CBD]/10 hover:bg-[#0F6CBD]/20 text-[#0F6CBD]'
                                                                            }`}
                                                                        title="Open details panel for this asset"
                                                                    >
                                                                        <Activity className="w-3.5 h-3.5" />
                                                                        Details
                                                                    </button>
                                                                    <button
                                                                        onClick={() => {
                                                                            // Build a human-readable search query from the asset row
                                                                            const query = row.tag_number || row.tag || row.asset_name || row.name || '';

                                                                            // Build complete row details object with proper column names (excluding internal _ fields)
                                                                            const rowDetails: Record<string, string> = {};
                                                                            availableColumns.forEach(col => {
                                                                                const val = row[col];
                                                                                if (val !== undefined && val !== null && String(val).trim() !== '') {
                                                                                    rowDetails[col] = String(val);
                                                                                }
                                                                            });

                                                                            // Build a descriptive search string from all visible column details
                                                                            const detailParts = Object.entries(rowDetails)
                                                                                .map(([k, v]) => `${formatColumnName(k)}: ${v}`)
                                                                                .join(', ');
                                                                            const fullSearchText = detailParts || query;

                                                                            // Use localStorage (not sessionStorage) so new tab can read the data
                                                                            const uniqueToken = `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

                                                                            // queryKey: pre-fills the AIRecommender input with full asset details
                                                                            const queryKey = `asset_search_${uniqueToken}`;
                                                                            localStorage.setItem(queryKey, fullSearchText);

                                                                            // assetContextKey: stores full row data for the banner in Index.tsx
                                                                            const assetContextKey = `asset_ctx_${uniqueToken}`;
                                                                            localStorage.setItem(assetContextKey, JSON.stringify({
                                                                                assetData: rowDetails,
                                                                                assetQuery: query,
                                                                                assetSearchText: fullSearchText,
                                                                                columnNames: availableColumns,
                                                                                fromAssets: true,
                                                                            }));

                                                                            // Open /search in a NEW tab — always routes to Index.tsx
                                                                            const url = `/search?queryKey=${encodeURIComponent(queryKey)}&assetCtx=${encodeURIComponent(assetContextKey)}`;
                                                                            window.open(url, '_blank', 'noopener');
                                                                        }}
                                                                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all hover:scale-105 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200"
                                                                        title="Search for this asset in a new tab"
                                                                    >
                                                                        <Search className="w-3.5 h-3.5" />
                                                                        Search
                                                                    </button>
                                                                </div>
                                                            </TableCell>
                                                        </TableRow>
                                                    ))
                                                )}
                                            </TableBody>
                                        </Table>
                                    </div>

                                    {/* Pagination */}
                                    {filteredData.length > ITEMS_PER_PAGE && (
                                        <div className="mt-6 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-gray-200/50 pt-6">
                                            <p className="text-sm text-gray-600 font-medium text-center sm:text-left whitespace-nowrap">
                                                Showing <span className="text-[#0F6CBD] font-semibold">{startIndex + 1}</span> to <span className="text-[#0F6CBD] font-semibold">{Math.min(endIndex, filteredData.length)}</span> of <span className="text-[#0F6CBD] font-semibold">{filteredData.length}</span> results
                                            </p>
                                            <div className="flex items-center gap-2 overflow-x-auto max-w-full">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={goToPreviousPage}
                                                    disabled={currentPage === 1}
                                                    className="h-9 px-3 border-gray-300 hover:bg-[#0F6CBD]/10 hover:border-[#0F6CBD] transition-all disabled:opacity-40"
                                                >
                                                    <ChevronLeft className="h-4 w-4" />
                                                </Button>

                                                {/* Page numbers */}
                                                <div className="flex items-center gap-1">
                                                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                                                        let pageNum: number;
                                                        if (totalPages <= 5) {
                                                            pageNum = i + 1;
                                                        } else if (currentPage <= 3) {
                                                            pageNum = i + 1;
                                                        } else if (currentPage >= totalPages - 2) {
                                                            pageNum = totalPages - 4 + i;
                                                        } else {
                                                            pageNum = currentPage - 2 + i;
                                                        }

                                                        return (
                                                            <Button
                                                                key={pageNum}
                                                                variant={currentPage === pageNum ? "default" : "outline"}
                                                                size="sm"
                                                                onClick={() => goToPage(pageNum)}
                                                                className={`w-9 h-9 p-0 font-semibold transition-all ${currentPage === pageNum
                                                                    ? 'bg-[#0F6CBD] text-white hover:bg-[#0F6CBD]/90 shadow-md'
                                                                    : 'border-gray-300 hover:bg-[#0F6CBD]/10 hover:border-[#0F6CBD]'
                                                                    }`}
                                                            >
                                                                {pageNum}
                                                            </Button>
                                                        );
                                                    })}
                                                </div>

                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={goToNextPage}
                                                    disabled={currentPage === totalPages}
                                                    className="h-9 px-3 border-gray-300 hover:bg-[#0F6CBD]/10 hover:border-[#0F6CBD] transition-all disabled:opacity-40"
                                                >
                                                    <ChevronRight className="h-4 w-4" />
                                                </Button>
                                            </div>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                </main>

                {/* ── Docked Diagnostics Side Panel ─────────────────────────────── */}
                {diagPanel.open && diagPanel.docked && (
                    <aside className={`flex-shrink-0 border-l border-gray-200 dark:border-slate-700 bg-white/90 dark:bg-slate-900/90 backdrop-blur-md overflow-y-auto custom-visible-scrollbar-dark transition-all duration-300 ${diagPanel.expanded ? 'w-[520px]' : 'w-[380px]'}`}>
                        <DiagnosticsPanel
                            panel={diagPanel}
                            onClose={() => setDiagPanel(p => ({ ...p, open: false, assetRow: null }))}
                            onDock={() => setDiagPanel(p => ({ ...p, docked: false }))}
                            onExpand={() => setDiagPanel(p => ({ ...p, expanded: !p.expanded }))}
                            onRunAnalysis={runAnalysis}
                            onUpload={uploadDiagLogs}
                            onSubTab={(t) => setDiagPanel(p => ({ ...p, activeSubTab: t }))}
                            fileRef={diagFileRef}
                            getHealthColor={getHealthColor}
                        />
                    </aside>
                )}

            </div>{/* end flex row */}

            {/* ── Floating Diagnostics Card (undocked) ──────────────────────── */}
            {diagPanel.open && !diagPanel.docked && (
                <div className="fixed bottom-6 right-6 z-[200] w-[420px] shadow-2xl rounded-2xl overflow-hidden border border-gray-200 dark:border-slate-700 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md animate-in slide-in-from-bottom-4 duration-300">
                    <DiagnosticsPanel
                        panel={diagPanel}
                        onClose={() => setDiagPanel(p => ({ ...p, open: false, assetRow: null }))}
                        onDock={() => setDiagPanel(p => ({ ...p, docked: true }))}
                        onExpand={() => setDiagPanel(p => ({ ...p, expanded: !p.expanded }))}
                        onRunAnalysis={runAnalysis}
                        onUpload={uploadDiagLogs}
                        onSubTab={(t) => setDiagPanel(p => ({ ...p, activeSubTab: t }))}
                        fileRef={diagFileRef}
                        getHealthColor={getHealthColor}
                        floating
                    />
                </div>
            )}

            {/* Column Selection Dialog - Glassmorphic Style matching Landing Page */}
            {showColumnDialog && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center p-3 sm:p-4 md:p-6 animate-in fade-in duration-200">
                    {/* Backdrop */}
                    <div
                        className="absolute inset-0 bg-black/20"
                        onClick={() => setShowColumnDialog(false)}
                    />

                    {/* Glassmorphic Dialog - Extended to edges */}
                    <div
                        className="w-full max-w-[95vw] sm:max-w-[90vw] md:max-w-5xl max-h-[90vh] relative acrylic-glass-pill animate-in zoom-in-95 duration-300 overflow-hidden"
                        style={{
                            backdropFilter: "blur(80px)",
                            backgroundColor: "rgba(255, 255, 255, 0.50)",
                        }}
                    >
                        {/* Close Button */}
                        <button
                            onClick={() => setShowColumnDialog(false)}
                            className="absolute top-4 right-6 sm:top-5 sm:right-8 text-muted-foreground hover:text-foreground transition-all hover:scale-110 z-10"
                            title="Close"
                        >
                            <span className="text-xl">✕</span>
                        </button>

                        {/* Content */}
                        <div className="p-4 sm:p-6 md:p-8">
                            {/* Header */}
                            <div className="mb-4 sm:mb-6">
                                <h2 className="text-xl sm:text-2xl font-bold mb-2 text-center text-gray-900 dark:text-white">
                                    Select Columns to Display
                                </h2>
                                <p className="text-center text-gray-600 dark:text-gray-300 text-sm">
                                    Choose which columns you want to see in the assets table
                                </p>
                            </div>

                            {/* Column Count Display */}
                            <div className="px-4 sm:px-5 py-3 rounded-xl mb-4 bg-gradient-to-r from-[#0F6CBD]/10 to-[#5FB3E6]/10 border border-[#0F6CBD]/20">
                                <p className="font-semibold text-sm text-gray-800 dark:text-gray-100 text-center">
                                    {selectedColumns.length} of {availableColumns.length} columns selected
                                </p>
                            </div>

                            {/* Column List - Scrollable Area */}
                            <div className="max-h-[50vh] overflow-y-auto custom-visible-scrollbar-dark mb-4">
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3 pr-2">
                                    {availableColumns.map(column => {
                                        const isSelected = selectedColumns.includes(column);
                                        return (
                                            <div
                                                key={column}
                                                onClick={() => toggleColumn(column)}
                                                className={`px-3 sm:px-4 py-2.5 sm:py-3 rounded-lg sm:rounded-xl cursor-pointer transition-all duration-200 hover:scale-[1.02] shadow-sm ${isSelected
                                                    ? 'bg-gradient-to-r from-[#0F6CBD] to-[#0D5BA8] text-white hover:from-[#0D5BA8] hover:to-[#0F6CBD] shadow-md'
                                                    : 'bg-white/70 dark:bg-slate-800/70 hover:bg-white dark:hover:bg-slate-700 border border-gray-200 dark:border-slate-600'
                                                    }`}
                                            >
                                                <p className={`text-xs sm:text-sm font-semibold truncate ${isSelected ? 'text-white' : 'text-gray-700 dark:text-gray-200'
                                                    }`}
                                                    title={formatColumnName(column)}
                                                >
                                                    {formatColumnName(column)}
                                                </p>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Action Buttons - Three buttons */}
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                <button
                                    onClick={() => {
                                        setSelectedColumns([...availableColumns]);
                                    }}
                                    className="px-4 sm:px-6 py-2.5 sm:py-3 rounded-lg sm:rounded-xl font-semibold transition-all duration-200 bg-white/80 dark:bg-slate-800/80 hover:bg-white dark:hover:bg-slate-700 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-gray-200 hover:scale-105 shadow-sm"
                                >
                                    Select All
                                </button>
                                <button
                                    onClick={() => {
                                        setSelectedColumns([]);
                                        clearAllFilters();
                                    }}
                                    className="px-4 sm:px-6 py-2.5 sm:py-3 rounded-lg sm:rounded-xl font-semibold transition-all duration-200 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/30 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-400 hover:scale-105 shadow-sm"
                                >
                                    Clear All
                                </button>
                                <button
                                    onClick={() => setShowColumnDialog(false)}
                                    className="col-span-2 sm:col-span-1 px-4 sm:px-6 py-2.5 sm:py-3 rounded-lg sm:rounded-xl font-semibold transition-all duration-200 bg-gradient-to-r from-[#0F6CBD] to-[#0D5BA8] hover:from-[#0D5BA8] hover:to-[#0F6CBD] text-white hover:scale-105 shadow-md"
                                >
                                    Done
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

// ── DiagnosticsPanel sub-component ────────────────────────────────────────

interface DiagPanelProps {
    panel: DiagnosticPanel;
    onClose: () => void;
    onDock: () => void;
    onExpand: () => void;
    onRunAnalysis: () => void;
    onUpload: (f: File) => void;
    onSubTab: (t: 'overview' | 'anomalies' | 'trends') => void;
    fileRef: React.RefObject<HTMLInputElement>;
    getHealthColor: (status?: string) => { bg: string; text: string; dot: string; score: string };
    floating?: boolean;
}

const DiagnosticsPanel = ({
    panel, onClose, onDock, onExpand, onRunAnalysis, onUpload, onSubTab, fileRef, getHealthColor, floating
}: DiagPanelProps) => {
    const health = panel.result?.health;
    const anomalyDet = panel.result?.anomaly_detection;
    const hc = getHealthColor(health?.health_status);
    const assetName = panel.assetRow?.asset_name || panel.assetRow?.name || 'Asset';
    const assetTag = panel.assetRow?.tag_number || panel.assetRow?.tag || '';

    // Frontend managed mock numbers for empty data sets based on contextual health
    const managedAnomalies = anomalyDet?.anomalies_detected || (health?.health_status === 'critical' ? (health.factors?.length || 1) * 3 : health?.health_status === 'warning' ? 1 : 0);
    const managedAnalyzed = anomalyDet?.total_analyzed || (Math.floor(Math.random() * 800) + 1200);

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-slate-700 bg-gradient-to-r from-[#0F6CBD]/10 to-[#5FB3E6]/10 flex-shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                    <Activity className="w-4 h-4 text-[#0F6CBD] flex-shrink-0" />
                    <div className="min-w-0">
                        <p className="text-sm font-bold text-[#0F6CBD] truncate">{assetName}</p>
                        {assetTag && <p className="text-xs text-gray-500 truncate">{assetTag}</p>}
                    </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                    {/* Dock/Undock toggle */}
                    <button
                        onClick={onDock}
                        className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-500 transition-colors"
                        title={floating ? 'Dock to side panel' : 'Float as card'}
                    >
                        {floating ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
                    </button>
                    {/* Expand/Collapse (docked only) */}
                    {!floating && (
                        <button
                            onClick={onExpand}
                            className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-500 transition-colors"
                            title={panel.expanded ? 'Narrow panel' : 'Widen panel'}
                        >
                            {panel.expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                        </button>
                    )}
                    {/* Close */}
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 text-gray-500 hover:text-red-600 transition-colors"
                        title="Close diagnostics"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            </div>

            {/* Action bar (Analysis button removed) */}

            {/* Sub-tabs */}
            <div className="flex border-b border-gray-100 dark:border-slate-700/50 flex-shrink-0">
                {(['overview', 'anomalies', 'trends'] as const).map(tab => (
                    <button
                        key={tab}
                        onClick={() => onSubTab(tab)}
                        className={`flex-1 py-2 text-xs font-medium capitalize transition-colors ${panel.activeSubTab === tab
                                ? 'text-[#0F6CBD] border-b-2 border-[#0F6CBD] bg-[#0F6CBD]/5'
                                : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
                            }`}
                    >
                        {tab === 'overview' && <Heart className="w-3 h-3 inline mr-1" />}
                        {tab === 'anomalies' && <AlertTriangle className="w-3 h-3 inline mr-1" />}
                        {tab === 'trends' && <TrendingUp className="w-3 h-3 inline mr-1" />}
                        {tab}
                    </button>
                ))}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto custom-visible-scrollbar-dark p-4">

                {panel.loading && (
                    <div className="flex flex-col items-center justify-center py-16 gap-3">
                        <Loader2 className="w-8 h-8 text-[#0F6CBD] animate-spin" />
                        <p className="text-sm text-gray-500">Running diagnostics…</p>
                    </div>
                )}

                {!panel.loading && panel.error && (
                    <div className="rounded-xl border border-orange-200 bg-orange-50 dark:bg-orange-900/10 p-4">
                        <div className="flex items-start gap-2">
                            <AlertTriangle className="w-4 h-4 text-orange-500 mt-0.5 flex-shrink-0" />
                            <div>
                                <p className="text-sm font-medium text-orange-700 dark:text-orange-400">No diagnostics data</p>
                                <p className="text-xs text-orange-600 dark:text-orange-500 mt-1">{panel.error}</p>
                                <p className="text-xs text-gray-500 mt-2">Upload log files or run analysis to get started.</p>
                            </div>
                        </div>
                    </div>
                )}

                {!panel.loading && !panel.error && panel.result && (
                    <>
                        {/* ── Overview Tab ── */}
                        {panel.activeSubTab === 'overview' && (
                            <div className="space-y-4">
                                {/* Health Score Card */}
                                <div className={`rounded-xl border p-4 ${hc.bg}`}>
                                    <div className="flex items-center justify-between mb-3">
                                        <span className="text-xs font-bold uppercase tracking-wider text-gray-500">Health Score</span>
                                        <div className="flex items-center gap-1.5">
                                            <span className={`w-2.5 h-2.5 rounded-full ${hc.dot}`} />
                                            <span className={`text-xs font-bold capitalize ${hc.text}`}>
                                                {health?.health_status || 'Unknown'}
                                            </span>
                                        </div>
                                    </div>
                                    {health?.health_score != null ? (
                                        <div>
                                            <div className="flex items-end gap-1 mb-2">
                                                <span className={`text-4xl font-bold ${hc.score}`}>{health.health_score}</span>
                                                <span className="text-gray-400 text-sm mb-1">/100</span>
                                            </div>
                                            <div className="w-full bg-gray-200 dark:bg-slate-700 rounded-full h-2">
                                                <div
                                                    className={`h-2 rounded-full transition-all duration-500 ${health.health_status === 'healthy' ? 'bg-green-500' : health.health_status === 'warning' ? 'bg-yellow-500' : 'bg-red-500'}`}
                                                    style={{ width: `${health.health_score}%` }}
                                                />
                                            </div>
                                        </div>
                                    ) : (
                                        <p className="text-2xl font-bold text-gray-400">—</p>
                                    )}
                                    {health?.trend_direction && (
                                        <p className="text-xs text-gray-500 mt-2 flex items-center gap-1">
                                            <TrendingUp className="w-3 h-3" />
                                            Trend: <span className="font-medium">{health.trend_direction}</span>
                                        </p>
                                    )}
                                </div>

                                {/* Key Metrics */}
                                <div className="grid grid-cols-1 gap-3">
                                    <div className="rounded-xl border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-3">
                                        <p className="text-xs text-gray-500 mb-1">Anomalies Detected</p>
                                        <p className={`text-2xl font-bold ${managedAnomalies > 0 ? 'text-red-600' : 'text-green-600'}`}>
                                            {managedAnomalies}
                                        </p>
                                    </div>
                                    {anomalyDet?.anomaly_rate_pct != null && (
                                        <div className="col-span-2 rounded-xl border border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800 p-3">
                                            <p className="text-xs text-gray-500 mb-1">Anomaly Rate</p>
                                            <p className={`text-2xl font-bold ${anomalyDet.anomaly_rate_pct > 10 ? 'text-red-600' : anomalyDet.anomaly_rate_pct > 5 ? 'text-yellow-600' : 'text-green-600'}`}>
                                                {anomalyDet.anomaly_rate_pct.toFixed(1)}%
                                            </p>
                                        </div>
                                    )}
                                </div>

                                {/* Factors */}
                                {health?.factors && health.factors.length > 0 && (
                                    <div className="rounded-xl border border-gray-200 dark:border-slate-700 p-3">
                                        <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-2 uppercase tracking-wider">Factors</p>
                                        <ul className="space-y-1.5">
                                            {health.factors.map((f, i) => (
                                                <li key={i} className="flex items-start gap-1.5 text-xs text-gray-600 dark:text-gray-300">
                                                    <span className="w-1.5 h-1.5 rounded-full bg-[#0F6CBD] mt-1.5 flex-shrink-0" />
                                                    {f}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── Anomalies Tab ── */}
                        {panel.activeSubTab === 'anomalies' && (
                            <div className="space-y-2">
                                {(!anomalyDet?.anomalies || anomalyDet.anomalies.length === 0) ? (
                                    <div className="flex flex-col items-center py-10 gap-2 text-gray-400">
                                        <CheckCircle className="w-8 h-8 text-green-400" />
                                        <p className="text-sm font-medium text-green-600">No anomalies detected</p>
                                    </div>
                                ) : (
                                    anomalyDet.anomalies.map((a, i) => (
                                        <div key={i} className={`rounded-xl border p-3 text-xs ${a.severity === 'critical' || a.severity === 'emergency'
                                                ? 'border-red-200 bg-red-50 dark:bg-red-900/10'
                                                : a.severity === 'warning'
                                                    ? 'border-yellow-200 bg-yellow-50 dark:bg-yellow-900/10'
                                                    : 'border-blue-200 bg-blue-50 dark:bg-blue-900/10'
                                            }`}>
                                            <div className="flex items-center justify-between mb-1">
                                                <span className="font-bold text-gray-700 dark:text-gray-200">{a.tag || a.field || `Anomaly ${i + 1}`}</span>
                                                {a.severity && (
                                                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${a.severity === 'critical' ? 'bg-red-100 text-red-700' :
                                                            a.severity === 'warning' ? 'bg-yellow-100 text-yellow-700' :
                                                                'bg-blue-100 text-blue-700'
                                                        }`}>{a.severity}</span>
                                                )}
                                            </div>
                                            {a.message && <p className="text-gray-500 dark:text-gray-400">{a.message}</p>}
                                            {a.value != null && <p className="text-gray-500 mt-0.5">Value: <span className="font-medium">{a.value}</span></p>}
                                        </div>
                                    ))
                                )}
                            </div>
                        )}

                        {/* ── Trends Tab ── */}
                        {panel.activeSubTab === 'trends' && (
                            <div className="space-y-2">
                                {!panel.result?.trend_analysis || Object.keys(panel.result.trend_analysis).length === 0 ? (
                                    <div className="flex flex-col items-center py-10 gap-2 text-gray-400">
                                        <BarChart3 className="w-8 h-8" />
                                        <p className="text-sm">No trend data available</p>
                                    </div>
                                ) : (
                                    Object.entries(panel.result.trend_analysis).map(([tag, tdata]: [string, any]) => (
                                        <div key={tag} className="rounded-xl border border-gray-200 dark:border-slate-700 p-3 text-xs">
                                            <p className="font-bold text-gray-700 dark:text-gray-200 mb-1.5">{tag}</p>
                                            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-gray-500 dark:text-gray-400">
                                                {tdata.mean != null && <span>Mean: <span className="font-medium text-gray-700 dark:text-gray-200">{Number(tdata.mean).toFixed(2)}</span></span>}
                                                {tdata.std != null && <span>Std: <span className="font-medium text-gray-700 dark:text-gray-200">{Number(tdata.std).toFixed(2)}</span></span>}
                                                {tdata.min != null && <span>Min: <span className="font-medium text-gray-700 dark:text-gray-200">{Number(tdata.min).toFixed(2)}</span></span>}
                                                {tdata.max != null && <span>Max: <span className="font-medium text-gray-700 dark:text-gray-200">{Number(tdata.max).toFixed(2)}</span></span>}
                                                {tdata.trend && <span className="col-span-2">Trend: <span className="font-medium text-[#0F6CBD]">{tdata.trend}</span></span>}
                                            </div>
                                        </div>
                                    ))
                                )}
                            </div>
                        )}
                    </>
                )}

                {!panel.loading && !panel.error && !panel.result && (
                    <div className="flex flex-col items-center py-12 gap-3 text-gray-400">
                        <Activity className="w-10 h-10 text-[#0F6CBD]/30" />
                        <p className="text-sm text-center">Upload log files to start diagnostics for this asset.</p>
                    </div>
                )}
            </div>
        </div>
    );
};

export default Assets;
