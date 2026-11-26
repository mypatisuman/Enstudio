import { useState, useEffect, useRef } from "react";
import axios from "axios";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import MainHeader from "@/components/MainHeader";
import { Button } from "@/components/ui/button";
import {
    ArrowLeft, Users, Zap, Clock, DollarSign, Activity, BarChart3, Loader2,
    Server, Database, Gauge, HardDrive, Heart, TrendingUp, ChevronRight, Globe, Calendar, RefreshCw
} from "lucide-react";
import { BASE_URL } from "@/components/AIRecommender/api";

function formatDuration(ms: number): string {
    const totalSec = ms / 1000;
    if (totalSec < 60) return `${totalSec.toFixed(1)}s`;
    const mins = Math.floor(totalSec / 60);
    const secs = Math.round(totalSec % 60);
    return `${mins}m ${secs}s`;
}

interface UserUtilization {
    id: number;
    username: string;
    email: string;
    first_name: string | null;
    last_name: string | null;
    role: string;
    llm_usage: {
        total_requests: number;
        total_tokens: number;
        total_cost_usd: number;
    };
    sessions: {
        total_sessions: number;
        active_sessions: number;
        total_interactions: number;
    };
}

interface UserDetailData {
    user: {
        id: number;
        username: string;
        email: string;
        first_name: string | null;
        last_name: string | null;
        role: string;
    };
    time_period_hours: number;
    llm_usage: {
        summary: {
            total_requests: number;
            total_tokens: number;
            total_input_tokens: number;
            total_output_tokens: number;
            total_cost_usd: number;
            avg_tokens_per_request: number;
            avg_response_time_ms: number;
        };
        by_agent: Array<{
            agent_type: string;
            request_count: number;
            total_tokens: number;
            total_cost_usd: number;
            avg_tokens_per_request: number;
            avg_response_time_ms: number;
        }>;
        by_feature: Array<{
            feature_type: string;
            request_count: number;
            total_tokens: number;
            total_cost_usd: number;
            avg_tokens_per_request: number;
            avg_response_time_ms: number;
        }>;
        by_model: Array<{
            provider: string;
            model_name: string;
            request_count: number;
            total_tokens: number;
            total_cost_usd: number;
        }>;
    };
    sessions: {
        analytics: {
            total_sessions: number;
            active_sessions: number;
            total_interactions: number;
            avg_duration_minutes: number;
        };
    };
}

// Sub-tabs for "By User" mode (shown after a user is selected)
const userSubTabs = [
    { id: 'llm', label: 'LLM Usage', icon: Zap },
    { id: 'sessions', label: 'Sessions', icon: Users },
];

// Sub-tabs for "By Global" mode
const globalSubTabs = [
    { id: 'sessions', label: 'Sessions', icon: Users },
    { id: 'endpoints', label: 'Endpoints', icon: Activity },
    { id: 'queries', label: 'Queries', icon: Database },
    { id: 'storage', label: 'Storage', icon: HardDrive },
    { id: 'health', label: 'Health', icon: Heart },
];

const UtilizationPage = () => {
    const { user, isLoading: authLoading, isAuthenticated } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    const getParentPath = () => {
        if (location.state?.from) return location.state.from;
        const path = location.pathname;
        if (path.endsWith('/usage')) {
            const parentPath = path.slice(0, -6); // Remove '/usage'
            return parentPath || '/chat';
        }
        return '/chat';
    };

    const [viewMode, setViewMode] = useState<'byUser' | 'byGlobal'>('byUser'); // Top-level mode
    const [activeTab, setActiveTab] = useState(''); // Sub-tab within the mode
    const [users, setUsers] = useState<UserUtilization[]>([]);
    const [selectedUser, setSelectedUser] = useState<UserDetailData | null>(null);
    const [selectedComponent, setSelectedComponent] = useState<'solution' | 'search' | 'chat' | null>(null); // Track selected component
    const [loading, setLoading] = useState(true); // Start with loading true
    const [detailLoading, setDetailLoading] = useState(false);
    const [isRefreshing, setIsRefreshing] = useState(false); // Track manual refresh clicks
    const [timePeriod, setTimePeriod] = useState(876000); // ~100 years = all-time default
    const [error, setError] = useState<string | null>(null);
    const [hasFetched, setHasFetched] = useState(false);
    const lastUsersFetchTimePeriod = useRef(0);

    // Tab-specific state
    const [sessions, setSessions] = useState<any[]>([]);
    const [sessionAnalytics, setSessionAnalytics] = useState<any>(null);
    const [activityPatterns, setActivityPatterns] = useState<any>(null);
    const [endpointSummary, setEndpointSummary] = useState<any>(null);
    const [slowestEndpoints, setSlowestEndpoints] = useState<any[]>([]);
    const [endpointErrors, setEndpointErrors] = useState<any[]>([]);
    const [errorSummary, setErrorSummary] = useState<any>(null);
    const [queryStats, setQueryStats] = useState<any>(null);
    const [slowQueries, setSlowQueries] = useState<any[]>([]);
    const [storage, setStorage] = useState<any>(null);
    const [storageBreakdown, setStorageBreakdown] = useState<any>(null);
    const [health, setHealth] = useState<any>(null);
    const [tabError, setTabError] = useState<string | null>(null);
    const [showTimeDropdown, setShowTimeDropdown] = useState(false);
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [hourFrom, setHourFrom] = useState('00');
    const [minuteFrom, setMinuteFrom] = useState('00');
    const [hourTo, setHourTo] = useState('23');
    const [minuteTo, setMinuteTo] = useState('59');
    const [selectedDateRange, setSelectedDateRange] = useState<{ from: string; to: string } | null>(null);

    useEffect(() => {
        if (!authLoading && !isAuthenticated) {
            navigate('/');
        }
    }, [authLoading, isAuthenticated, navigate]);

    // Auto-load logged-in user's data if not admin
    useEffect(() => {
        if (!authLoading && user && user.role !== 'admin' && !selectedUser) {
            // For non-admin users, automatically load their own data
            fetchMyUsage();
        }
    }, [authLoading, user, timePeriod]);

    // Fetch user list when in "By User" mode and no user selected
    useEffect(() => {
        if (!authLoading && user?.role === 'admin' && viewMode === 'byUser' && !selectedUser) {
            if (!hasFetched || lastUsersFetchTimePeriod.current !== timePeriod) {
                lastUsersFetchTimePeriod.current = timePeriod;
                fetchUsers();
            }
        }
    }, [authLoading, user, timePeriod, viewMode, selectedUser, hasFetched]);

    // Fetch global tab data when in "By Global" mode
    useEffect(() => {
        if (!authLoading && user?.role === 'admin' && viewMode === 'byGlobal') {
            if (activeTab === 'sessions') fetchSessions();
            else if (activeTab === 'endpoints') fetchEndpoints();
            else if (activeTab === 'queries') fetchQueries();
            else if (activeTab === 'storage') fetchStorage();
            else if (activeTab === 'health') fetchHealth();
            else if (activeTab === 'users') fetchUsers();
        }
    }, [authLoading, user, timePeriod, viewMode, activeTab]);

    // Fetch user tab-specific data when a user is selected
    useEffect(() => {
        if (!user || !selectedUser) return;

        // User-specific tabs
        if (activeTab === 'sessions') {
            if (user.role === 'admin') {
                fetchUserSessions(selectedUser.user.id);
            } else {
                fetchMySessions();
            }
        }
        // LLM data is already loaded with selectedUser
    }, [activeTab, user, selectedUser]);

    // Re-fetch user detail when timePeriod changes (for LLM data update)
    const prevTimePeriod = useRef(timePeriod);
    useEffect(() => {
        if (!user || !selectedUser) return;

        // Only re-fetch if timePeriod actually changed (not on initial mount)
        if (prevTimePeriod.current !== timePeriod) {
            prevTimePeriod.current = timePeriod;
            if (user.role === 'admin') {
                fetchUserDetail(selectedUser.user.id);
            } else {
                fetchMyUsage();
            }
        }
    }, [timePeriod, user, selectedUser]);

    const fetchUsers = async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await axios.get(`/api/admin/utilization/users?hours=${timePeriod}`);
            setUsers(response.data.users || []);
        } catch (err: any) {
            console.error('Failed to fetch users:', err);
            setError(err.response?.data?.error || err.message || 'Failed to load users');
        } finally {
            setLoading(false);
            setHasFetched(true);
        }
    };

    const fetchUserDetail = async (userId: number) => {
        setDetailLoading(true);
        setActiveTab('llm'); // Set tab immediately for instant UI feedback
        try {
            const response = await axios.get(`/api/admin/utilization/user/${userId}?hours=${timePeriod}`);
            const data = response.data;
            console.log('=== Admin User Detail API Response ===');
            console.log('Full response:', data);
            console.log('LLM Usage:', data.llm_usage);
            setSelectedUser(data);
        } catch (err: any) {
            console.error('Failed to fetch user detail:', err);
            setTabError(err.response?.data?.error || err.message || 'Failed to load user detail');
            setActiveTab(''); // Reset tab on error
        } finally {
            setDetailLoading(false);
        }
    };

    const fetchMyUsage = async () => {
        setDetailLoading(true);
        setActiveTab('llm'); // Set tab immediately for instant UI feedback
        try {
            const response = await axios.get(`/api/utilization/me?hours=${timePeriod}`);
            const data = response.data;
            console.log('=== My Usage API Response ===');
            console.log('Full response:', data);
            setSelectedUser(data);
        } catch (err: any) {
            console.error('Failed to fetch my utilization:', err);
            setTabError(err.response?.data?.error || err.message || 'Failed to load utilization data');
            setActiveTab('');
        } finally {
            setDetailLoading(false);
        }
    };

    const fetchSessions = async () => {
        setLoading(true);
        setTabError(null);
        try {
            const [analyticsRes, recentRes, patternsRes] = await Promise.all([
                axios.get(`/api/analytics/sessions/all?hours=${timePeriod}`),
                axios.get(`/api/analytics/sessions/recent?hours=${timePeriod}&limit=5&active_only=true`),
                axios.get(`/api/analytics/sessions/activity-patterns?hours=${timePeriod}`),
            ]);
            
            setSessionAnalytics(analyticsRes.data.analytics || null);
            setSessions(recentRes.data.sessions || []);
            setActivityPatterns(patternsRes.data.patterns || null);
        } catch (err: any) {
            console.error('Failed to fetch sessions:', err);
            setTabError('Failed to load session data');
        } finally {
            setLoading(false);
        }
    };

    const fetchUserSessions = async (userId: number) => {
        setLoading(true);
        setTabError(null);
        try {
            const response = await axios.get(`/api/analytics/sessions/user/${userId}?hours=${timePeriod}&limit=5&active_only=true`);
            setSessionAnalytics(response.data.analytics || null);
            setSessions(response.data.sessions || []);
            setActivityPatterns(null); // Not relevant for user-specific view
        } catch (err: any) {
            console.error('Failed to fetch user sessions:', err);
            setTabError('Failed to load user session data');
        } finally {
            setLoading(false);
        }
    };

    const fetchMySessions = async () => {
        setLoading(true);
        setTabError(null);
        try {
            const response = await axios.get(`/api/analytics/sessions/me?hours=${timePeriod}&limit=5&active_only=true`);
            setSessionAnalytics(response.data.analytics || null);
            setSessions(response.data.sessions || []);
            setActivityPatterns(null);
        } catch (err: any) {
            console.error('Failed to fetch my sessions:', err);
            setTabError('Failed to load session data');
        } finally {
            setLoading(false);
        }
    };

    const fetchEndpoints = async () => {
        setLoading(true);
        setTabError(null);
        try {
            const [summaryRes, slowestRes, errorsRes] = await Promise.all([
                axios.get(`/api/analytics/endpoints/summary?hours=${timePeriod}`),
                axios.get(`/api/analytics/endpoints/slowest?hours=${timePeriod}&limit=10`),
                axios.get(`/api/analytics/endpoints/errors?hours=${timePeriod}&limit=10`),
            ]);
            const summaryData = summaryRes.data;
            const slowestData = slowestRes.data;
            const errorsData = errorsRes.data;

            // Extract endpoints list from summary
            const summaryObj = summaryData.summary || summaryData;
            const endpointsList = summaryObj.endpoints || [];

            // Calculate aggregated stats from endpoints list
            let totalRequests = 0;
            let totalResponseTime = 0;
            let requestCount = 0;

            if (Array.isArray(endpointsList)) {
                endpointsList.forEach((ep: any) => {
                    totalRequests += ep.total_requests || 0;
                    if (ep.avg_response_time_ms) {
                        totalResponseTime += (ep.avg_response_time_ms * (ep.total_requests || 1));
                        requestCount += ep.total_requests || 1;
                    }
                });
            }

            // Get error stats from the errors endpoint
            const errorsRaw = errorsData.error_statistics || errorsData;
            const errorStats = Array.isArray(errorsRaw) ? null : errorsRaw;

            // Build aggregated summary with proper field names
            const aggregatedSummary = {
                total_requests: errorStats?.total_requests || totalRequests,
                avg_response_time: requestCount > 0 ? Math.round(totalResponseTime / requestCount) : 0,
                error_rate: errorStats?.error_rate ? errorStats.error_rate / 100 : 0, // Convert percentage to decimal
                total_errors: errorStats?.total_errors || 0,
                client_errors: errorStats?.client_errors || 0,
                server_errors: errorStats?.server_errors || 0,
                endpoints: endpointsList
            };

            setEndpointSummary(aggregatedSummary);
            const slowestRaw = slowestData.slowest_endpoints || slowestData.endpoints || slowestData;
            setSlowestEndpoints(Array.isArray(slowestRaw) ? slowestRaw : []);

            if (Array.isArray(errorsRaw)) {
                setEndpointErrors(errorsRaw);
                setErrorSummary(null);
            } else {
                setEndpointErrors([]);
                setErrorSummary(errorsRaw);
            }
        } catch (error) {
            console.error('Failed to fetch endpoints:', error);
            setTabError('Failed to load endpoint data');
        } finally {
            setLoading(false);
        }
    };

    const fetchQueries = async () => {
        setLoading(true);
        setTabError(null);
        try {
            const [statsRes, slowRes] = await Promise.all([
                axios.get(`/api/analytics/queries/statistics?hours=${timePeriod}`),
                axios.get(`/api/analytics/queries/slow?hours=${timePeriod}&limit=10`),
            ]);
            const statsData = statsRes.data;
            const slowData = slowRes.data;
            const rawStats = statsData.statistics || statsData;

            // Map backend field names to frontend expected names
            const mappedStats = {
                total_queries: rawStats.total_slow_queries || 0,
                avg_execution_time: rawStats.avg_execution_time_ms || 0,
                slow_query_count: rawStats.total_slow_queries || 0,
                max_execution_time: rawStats.max_execution_time_ms || 0,
                min_execution_time: rawStats.min_execution_time_ms || 0,
                total_documents_processed: rawStats.total_documents_processed || 0
            };

            setQueryStats(mappedStats);
            setSlowQueries(slowData.slow_queries || []);
        } catch (error) {
            console.error('Failed to fetch queries:', error);
            setTabError('Failed to load query data');
        } finally {
            setLoading(false);
        }
    };

    const fetchStorage = async (refresh: boolean = false) => {
        setLoading(true);
        setTabError(null);
        try {
            const query = refresh ? '?refresh=true' : '';
            const [currentRes, breakdownRes] = await Promise.all([
                axios.get(`/api/analytics/storage/current${query}`),
                axios.get(`/api/analytics/storage/breakdown${query}`),
            ]);
            const currentData = currentRes.data;
            const breakdownData = breakdownRes.data;
            setStorage(currentData.storage || currentData);
            setStorageBreakdown(breakdownData.breakdown || breakdownData);
        } catch (err: any) {
            console.error('Failed to fetch storage:', err);
            setTabError('Failed to load storage data');
        } finally {
            setLoading(false);
        }
    };

    const fetchHealth = async () => {
        setLoading(true);
        setTabError(null);
        try {
            const response = await axios.get(`/api/health`);
            setHealth(response.data);
        } catch (err: any) {
            console.error('Failed to fetch health:', err);
            setTabError('Failed to load health data');
        } finally {
            setLoading(false);
        }
    };

    const handleRefresh = async () => {
        console.log('[REFRESH] Manual refresh triggered');
        setIsRefreshing(true);
        setError(null);
        setTabError(null);

        try {
            // If a user is selected, refresh their detail data
            if (selectedUser) {
                if (user?.role === 'admin') {
                    console.log('[REFRESH] Refreshing admin user detail:', selectedUser.user.id);
                    await fetchUserDetail(selectedUser.user.id);
                } else {
                    console.log('[REFRESH] Refreshing my usage');
                    await fetchMyUsage();
                }

                // Also refresh the active tab data
                if (activeTab === 'sessions') {
                    if (user?.role === 'admin') {
                        await fetchUserSessions(selectedUser.user.id);
                    } else {
                        await fetchMySessions();
                    }
                }
            }
            // If no user selected, refresh based on current view mode
            else if (viewMode === 'byUser') {
                if (user?.role === 'admin') {
                    console.log('[REFRESH] Refreshing users list');
                    await fetchUsers();
                } else {
                    console.log('[REFRESH] Refreshing my usage (regular user)');
                    await fetchMyUsage();
                }
            }
            // In "By Global" mode, refresh the active tab
            else if (viewMode === 'byGlobal') {
                console.log('[REFRESH] Refreshing global tab:', activeTab);
                if (activeTab === 'sessions') await fetchSessions();
                else if (activeTab === 'endpoints') await fetchEndpoints();
                else if (activeTab === 'queries') await fetchQueries();
                else if (activeTab === 'storage') await fetchStorage(true);
                else if (activeTab === 'health') await fetchHealth();
            }
        } finally {
            // Always stop the refresh spinner after 1 second minimum
            setTimeout(() => setIsRefreshing(false), 1000);
        }
    };

    const formatNumber = (num: number | null | undefined) => {
        if (num == null || isNaN(num)) return '0';
        if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
        if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
        return num.toLocaleString();
    };

    const formatCost = (cost: number | null | undefined) => {
        if (cost == null || isNaN(cost) || cost === 0) return '$0.0000';
        return `$${cost.toFixed(4)}`;
    };

    const getUserDisplayName = (u: UserUtilization | UserDetailData['user']) => {
        if (u.first_name && u.last_name) return `${u.first_name} ${u.last_name}`;
        return u.username;
    };

    const getStatusColor = (status: string) => {
        // Green statuses - everything is working well
        if (['healthy', 'available', 'connected', 'monitored'].includes(status)) {
            return 'text-green-600';
        }
        // Blue statuses - configured but not live tested (still good)
        if (['configured', 'configured_untested'].includes(status)) {
            return 'text-blue-600';
        }
        // Gray statuses - not configured (neutral, not an error for optional services)
        if (['not_configured'].includes(status)) {
            return 'text-gray-500';
        }
        // Orange statuses - degraded or warning
        if (['degraded', 'empty'].includes(status)) {
            return 'text-orange-600';
        }
        // Red statuses - errors and failures
        return 'text-red-600';
    };

    const formatDateTime = (dateString: string) => {
        try {
            if (!dateString) return 'N/A';
            let parseStr = dateString;
            // Many backends return naive UTC strings like "2026-03-24 03:49:43"
            // We ensure it is parsed as UTC by changing space to T and appending Z
            if (!parseStr.endsWith('Z') && !parseStr.includes('+')) {
                parseStr = parseStr.replace(' ', 'T') + 'Z';
            }
            const date = new Date(parseStr);
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            });
        } catch {
            return dateString;
        }
    };

    const getStatusBg = (status: string) => {
        // Green backgrounds - everything is working well
        if (['healthy', 'available', 'connected', 'monitored'].includes(status)) {
            return 'bg-green-100 dark:bg-green-900/30';
        }
        // Blue backgrounds - configured but not live tested (still good)
        if (['configured', 'configured_untested'].includes(status)) {
            return 'bg-blue-100 dark:bg-blue-900/30';
        }
        // Gray backgrounds - not configured (neutral)
        if (['not_configured'].includes(status)) {
            return 'bg-gray-100 dark:bg-gray-800/30';
        }
        // Orange backgrounds - degraded or warning
        if (['degraded', 'empty'].includes(status)) {
            return 'bg-orange-100 dark:bg-orange-900/30';
        }
        // Red backgrounds - errors and failures
        return 'bg-red-100 dark:bg-red-900/30';
    };

    if (authLoading) {
        return (
            <div className="min-h-screen app-glass-gradient flex items-center justify-center text-foreground">
                Loading...
            </div>
        );
    }

    if (!user) return null;

    /* ========================= TAB RENDERERS ========================= */

    const renderLLMTab = () => {
        if (!selectedUser && !detailLoading) return null;

        // Show loading state immediately
        if (detailLoading) {
            return (
                <div className="flex flex-col items-center justify-center py-16">
                    <Loader2 className="h-12 w-12 animate-spin text-[#0F6CBD] mb-4" />
                    <p className="text-sm text-muted-foreground">Loading user details...</p>
                </div>
            );
        }

        if (!selectedUser) return null;

        const summary = selectedUser.llm_usage?.summary;
        const hasError = summary && 'error' in summary;
        const isAdmin = user?.role === 'admin';

        // If a component is selected, show component details
        if (selectedComponent) {
            // Create default data structure
            const defaultComponentData = {
                agent_type: selectedComponent,
                request_count: 0,
                total_tokens: 0,
                total_cost_usd: 0,
                avg_tokens_per_request: 0,
                avg_response_time_ms: 0
            };

            // Find data for the selected component or use defaults
            console.log('=== Component Data Debug ===');
            console.log('Selected Component:', selectedComponent);
            console.log('Available by_agent data:', selectedUser.llm_usage.by_agent);
            console.log('Agent types:', selectedUser.llm_usage.by_agent?.map(a => a.agent_type));

            const componentData = selectedUser.llm_usage.by_agent?.find(a =>
                a.agent_type?.toLowerCase() === selectedComponent
            ) || defaultComponentData;

            console.log('Found componentData:', componentData);
            console.log('Is using default?', componentData === defaultComponentData);

            const componentColors = {
                solution: { bg: 'from-blue-100 to-blue-200 dark:from-blue-900/40 dark:to-blue-800/40', border: 'border-blue-300 dark:border-blue-600', text: 'text-blue-800 dark:text-blue-200' },
                search: { bg: 'from-purple-100 to-purple-200 dark:from-purple-900/40 dark:to-purple-800/40', border: 'border-purple-300 dark:border-purple-600', text: 'text-purple-800 dark:text-purple-200' },
                chat: { bg: 'from-green-100 to-green-200 dark:from-green-900/40 dark:to-green-800/40', border: 'border-green-300 dark:border-green-600', text: 'text-green-800 dark:text-green-200' }
            };
            const colors = componentColors[selectedComponent];

            return (
                <div className="space-y-4">
                    {/* Back button and title */}
                    <div className="flex items-center justify-center relative">
                        <button
                            onClick={() => setSelectedComponent(null)}
                            className="absolute left-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm"
                            title="Back to Modules"
                        >
                            <ArrowLeft className="w-5 h-5" />
                        </button>
                        <h3 className={`font-semibold capitalize text-lg ${colors.text}`}>{selectedComponent} Usage</h3>
                    </div>

                    {/* Component stats */}
                    <div className={`p-6 bg-gradient-to-br ${colors.bg} rounded-xl border ${colors.border}`}>
                        <div className={`grid grid-cols-1 ${isAdmin ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-4`}>
                            {/* Tokens */}
                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-2">
                                    <Zap className="h-5 w-5 text-orange-500" />
                                    <span className="text-sm font-medium text-muted-foreground">Tokens</span>
                                </div>
                                <p className="text-3xl font-bold">{formatNumber(componentData.total_tokens)}</p>
                            </div>

                            {/* Requests */}
                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-2">
                                    <Activity className="h-5 w-5 text-[#0F6CBD]" />
                                    <span className="text-sm font-medium text-muted-foreground">Requests</span>
                                </div>
                                <p className="text-3xl font-bold">{componentData.request_count}</p>
                            </div>

                            {/* Cost */}
                            {isAdmin && (
                                <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                    <div className="flex items-center gap-2 mb-2">
                                        <DollarSign className="h-5 w-5 text-green-500" />
                                        <span className="text-sm font-medium text-muted-foreground">Cost</span>
                                    </div>
                                    <p className="text-3xl font-bold text-green-600">{formatCost(componentData.total_cost_usd)}</p>
                                </div>
                            )}

                            {/* Admin-only averages */}
                            {isAdmin && (
                                <>
                                    {/* Avg Time */}
                                    <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <div className="flex items-center gap-2 mb-2">
                                            <Clock className="h-5 w-5 text-purple-500" />
                                            <span className="text-sm font-medium text-muted-foreground">Avg Time</span>
                                        </div>
                                        <p className="text-3xl font-bold">{formatDuration(componentData.avg_response_time_ms)}</p>
                                    </div>

                                    {/* Avg Tokens */}
                                    <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <div className="flex items-center gap-2 mb-2">
                                            <TrendingUp className="h-5 w-5 text-blue-500" />
                                            <span className="text-sm font-medium text-muted-foreground">Avg Tokens</span>
                                        </div>
                                        <p className="text-3xl font-bold">{Math.round(componentData.avg_tokens_per_request)}</p>
                                    </div>

                                    {/* Avg Cost */}
                                    <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <div className="flex items-center gap-2 mb-2">
                                            <DollarSign className="h-5 w-5 text-green-500" />
                                            <span className="text-sm font-medium text-muted-foreground">Avg Cost</span>
                                        </div>
                                        <p className="text-3xl font-bold text-green-600">
                                            {formatCost(componentData.request_count > 0 ? componentData.total_cost_usd / componentData.request_count : 0)}
                                        </p>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            );
        }

        // Otherwise show component selection
        return (
            <div className="space-y-4">
                {hasError ? (
                    <div className="text-center py-8">
                        <p className="text-red-500 mb-2">Failed to load LLM usage data</p>
                        <p className="text-sm text-muted-foreground">{(summary as any).error}</p>
                    </div>
                ) : (
                    <>
                        {/* Back to Users button */}
                        <div className="flex items-center justify-center mb-2 relative">
                            {user?.role === 'admin' && (
                                <button
                                    onClick={() => {
                                        setSelectedUser(null);
                                        setActiveTab('');
                                    }}
                                    className="absolute left-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm"
                                    title="Back to Users"
                                >
                                    <ArrowLeft className="w-5 h-5" />
                                </button>
                            )}
                            <h3 className="font-semibold text-lg">Select a Module</h3>
                        </div>

                        {/* Component Selection - 3 clickable cards */}
                        {(() => {
                            // Create default data for all components
                            const defaultComponentData = {
                                agent_type: '',
                                request_count: 0,
                                total_tokens: 0,
                                total_cost_usd: 0,
                                avg_tokens_per_request: 0,
                                avg_response_time_ms: 0
                            };

                            // Find data for each agent type (case-insensitive) or use defaults
                            const solutionAgent = selectedUser.llm_usage.by_agent?.find(a =>
                                a.agent_type?.toLowerCase() === 'solution'
                            ) || { ...defaultComponentData, agent_type: 'solution' };

                            const searchAgent = selectedUser.llm_usage.by_agent?.find(a =>
                                a.agent_type?.toLowerCase() === 'search'
                            ) || { ...defaultComponentData, agent_type: 'search' };

                            const chatAgent = selectedUser.llm_usage.by_agent?.find(a =>
                                a.agent_type?.toLowerCase() === 'chat'
                            ) || { ...defaultComponentData, agent_type: 'chat' };

                            // Calculate totals directly from the summary instead of summing agents
                            // This guarantees all tokens are counted even if they lack a specific agent_type
                            const summary = selectedUser.llm_usage?.summary;
                            const totalCost = summary?.total_cost_usd || 0;
                            const totalTokens = summary?.total_tokens || 0;
                            const totalRequests = summary?.total_requests || 0;

                            return (
                                <div className="space-y-4">
                                    {/* Total Summary Section */}
                                    <div className="p-4 bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-800/50 dark:to-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-700">
                                        <h3 className="font-semibold text-sm text-muted-foreground mb-3">Total Across All Modules</h3>
                                        <div className={`grid ${isAdmin ? 'grid-cols-3' : 'grid-cols-2'} gap-4`}>
                                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                                <div className="flex items-center gap-2 mb-1">
                                                    <Zap className="h-4 w-4 text-orange-500" />
                                                    <span className="text-xs font-medium text-muted-foreground">Total Tokens</span>
                                                </div>
                                                <p className="text-2xl font-bold">{formatNumber(totalTokens)}</p>
                                            </div>
                                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                                <div className="flex items-center gap-2 mb-1">
                                                    <Activity className="h-4 w-4 text-blue-500" />
                                                    <span className="text-xs font-medium text-muted-foreground">Total Requests</span>
                                                </div>
                                                <p className="text-2xl font-bold text-blue-600">{formatNumber(totalRequests)}</p>
                                            </div>
                                            {isAdmin && (
                                                <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                                    <div className="flex items-center gap-2 mb-1">
                                                        <DollarSign className="h-4 w-4 text-green-500" />
                                                        <span className="text-xs font-medium text-muted-foreground">Total Cost</span>
                                                    </div>
                                                    <p className="text-2xl font-bold text-green-600">{formatCost(totalCost)}</p>
                                                </div>
                                            )}
                                        </div>

                                        {/* Admin-only Averages */}
                                        {isAdmin && totalRequests > 0 && (
                                            <>
                                                <div className="border-t border-slate-300 dark:border-slate-600 my-3"></div>
                                                <h4 className="font-medium text-xs text-muted-foreground mb-3">Averages</h4>
                                                <div className="grid grid-cols-3 gap-4">
                                                    <div className="p-3 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                                        <div className="flex items-center gap-2 mb-1">
                                                            <Zap className="h-4 w-4 text-orange-400" />
                                                            <span className="text-xs font-medium text-muted-foreground">Avg Tokens/Request</span>
                                                        </div>
                                                        <p className="text-xl font-bold">{formatNumber(Math.round(totalTokens / totalRequests))}</p>
                                                    </div>
                                                    <div className="p-3 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                                        <div className="flex items-center gap-2 mb-1">
                                                            <Activity className="h-4 w-4 text-blue-400" />
                                                            <span className="text-xs font-medium text-muted-foreground">Avg Requests/Module</span>
                                                        </div>
                                                        <p className="text-xl font-bold text-blue-600">{formatNumber(Math.round(totalRequests / 3))}</p>
                                                    </div>
                                                    <div className="p-3 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                                        <div className="flex items-center gap-2 mb-1">
                                                            <DollarSign className="h-4 w-4 text-green-400" />
                                                            <span className="text-xs font-medium text-muted-foreground">Avg Cost/Request</span>
                                                        </div>
                                                        <p className="text-xl font-bold text-green-600">{formatCost(totalCost / totalRequests)}</p>
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>

                                    <h3 className="font-semibold flex items-center gap-2">
                                        <TrendingUp className="h-4 w-4" /> Usage by Module
                                    </h3>
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        {/* Solution Card */}
                                        <button
                                            onClick={() => setSelectedComponent('solution')}
                                            className="p-6 bg-gradient-to-br from-blue-100 to-blue-200 dark:from-blue-900/40 dark:to-blue-800/40 rounded-xl border-2 border-blue-300 dark:border-blue-600 hover:scale-105 hover:shadow-lg transition-all cursor-pointer text-left animate-fadeIn"
                                            style={{ animationDelay: '0.1s' }}
                                        >
                                            <div className="flex flex-col items-center justify-center gap-4">
                                                <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-full">
                                                    <TrendingUp className="h-8 w-8 text-blue-600 dark:text-blue-400" />
                                                </div>
                                                <h4 className="font-bold text-xl text-blue-700 dark:text-blue-300">
                                                    Solution
                                                </h4>
                                                <p className="text-sm text-muted-foreground text-center">
                                                    Click to view detailed statistics
                                                </p>
                                            </div>
                                        </button>

                                        {/* Search Card */}
                                        <button
                                            onClick={() => setSelectedComponent('search')}
                                            className="p-6 bg-gradient-to-br from-purple-100 to-purple-200 dark:from-purple-900/40 dark:to-purple-800/40 rounded-xl border-2 border-purple-300 dark:border-purple-600 hover:scale-105 hover:shadow-lg transition-all cursor-pointer text-left animate-fadeIn"
                                            style={{ animationDelay: '0.2s' }}
                                        >
                                            <div className="flex flex-col items-center justify-center gap-4">
                                                <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-full">
                                                    <BarChart3 className="h-8 w-8 text-purple-600 dark:text-purple-400" />
                                                </div>
                                                <h4 className="font-bold text-xl text-purple-700 dark:text-purple-300">
                                                    Search
                                                </h4>
                                                <p className="text-sm text-muted-foreground text-center">
                                                    Click to view detailed statistics
                                                </p>
                                            </div>
                                        </button>

                                        {/* Chat Card */}
                                        <button
                                            onClick={() => setSelectedComponent('chat')}
                                            className="p-6 bg-gradient-to-br from-green-100 to-green-200 dark:from-green-900/40 dark:to-green-800/40 rounded-xl border-2 border-green-300 dark:border-green-600 hover:scale-105 hover:shadow-lg transition-all cursor-pointer text-left animate-fadeIn"
                                            style={{ animationDelay: '0.3s' }}
                                        >
                                            <div className="flex flex-col items-center justify-center gap-4">
                                                <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-full">
                                                    <Activity className="h-8 w-8 text-green-600 dark:text-green-400" />
                                                </div>
                                                <h4 className="font-bold text-xl text-green-700 dark:text-green-300">
                                                    Chat
                                                </h4>
                                                <p className="text-sm text-muted-foreground text-center">
                                                    Click to view detailed statistics
                                                </p>
                                            </div>
                                        </button>
                                    </div>
                                </div>
                            );
                        })()}

                        {/* Usage by Model */}
                        {selectedUser.llm_usage.by_model.length > 0 && (
                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                                <h3 className="font-semibold mb-3">Usage by Model</h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {selectedUser.llm_usage.by_model.map((model, idx) => (
                                        <div key={idx} className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                            <div className="flex items-center justify-between mb-1">
                                                <span className="font-semibold text-sm capitalize">{model.provider}</span>
                                                <span className="text-xs text-muted-foreground">{model.request_count} calls</span>
                                            </div>
                                            <p className="text-xs text-muted-foreground mb-1">{model.model_name}</p>
                                            <div className={`flex items-center ${isAdmin ? 'justify-between' : 'justify-start'}`}>
                                                <span className="font-bold text-sm">{formatNumber(model.total_tokens)} tokens</span>
                                                {isAdmin && (
                                                    <span className="text-sm text-green-600">{formatCost(model.total_cost_usd)}</span>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        );
    };

    const renderSessionsTab = () => {
        // Use sessionAnalytics for summary cards (works for both global and user-specific)
        const analytics = selectedUser
            ? selectedUser.sessions?.analytics || sessionAnalytics
            : sessionAnalytics;

        return (
            <div className="space-y-4">
                {loading ? (
                    <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                    </div>
                ) : tabError ? (
                    <div className="text-center py-8">
                        <p className="text-red-500 mb-2">{tabError}</p>
                        <Button variant="outline" size="sm" onClick={() => {
                            if (selectedUser) fetchUserSessions(selectedUser.user.id);
                            else fetchSessions();
                        }}>
                            Retry
                        </Button>
                    </div>
                ) : (
                    <>
                        {/* Summary Cards */}
                        {analytics && (
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                                <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                    <div className="flex items-center gap-2 mb-1">
                                        <Users className="h-4 w-4 text-[#0F6CBD]" />
                                        <span className="text-xs text-muted-foreground">Total Sessions</span>
                                    </div>
                                    <p className="text-xl font-bold">{analytics.total_sessions || 0}</p>
                                </div>
                                <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                    <div className="flex items-center gap-2 mb-1">
                                        <Activity className="h-4 w-4 text-green-600" />
                                        <span className="text-xs text-muted-foreground">Active Sessions</span>
                                    </div>
                                    <p className="text-xl font-bold">{analytics.active_sessions || 0}</p>
                                </div>
                                <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                    <div className="flex items-center gap-2 mb-1">
                                        <Zap className="h-4 w-4 text-orange-500" />
                                        <span className="text-xs text-muted-foreground">Interactions</span>
                                    </div>
                                    <p className="text-xl font-bold">{formatNumber(analytics.total_interactions)}</p>
                                </div>
                                <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                    <div className="flex items-center gap-2 mb-1">
                                        <Clock className="h-4 w-4 text-purple-500" />
                                        <span className="text-xs text-muted-foreground">Avg Duration</span>
                                    </div>
                                    <p className="text-xl font-bold">
                                        {analytics.avg_duration_minutes
                                            ? `${Math.round(analytics.avg_duration_minutes)}m`
                                            : analytics.avg_duration_seconds
                                                ? `${Math.round(analytics.avg_duration_seconds / 60)}m`
                                                : '0m'}
                                    </p>
                                </div>
                            </div>
                        )}

                        {/* Recent Sessions List */}
                        <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow">
                            <h3 className="font-semibold mb-3">
                                {selectedUser ? `Sessions for ${getUserDisplayName(selectedUser.user)}` : 'Recent Sessions'}
                            </h3>
                            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2 pb-4">
                                {sessions.length === 0 ? (
                                    <p className="text-muted-foreground text-center py-4">No session data</p>
                                ) : (
                                    sessions.slice(0, 5).map((session: any, idx: number) => (
                                        <div key={idx} className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg flex items-center justify-between hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                            <div className="flex items-center gap-3">
                                                <span className="w-7 h-7 rounded-full bg-gradient-to-br from-[#0F6CBD] to-[#004E8C] flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                                                    {idx + 1}
                                                </span>
                                                <div>
                                                    <p className="font-medium text-sm">{selectedUser ? getUserDisplayName(selectedUser.user) : (session.username || session.user_id)}</p>
                                                    <p className="text-xs text-muted-foreground">
                                                        {session.browser || session.metadata?.browser || 'Unknown'} on {session.os || session.metadata?.os || 'Unknown'}
                                                    </p>
                                                </div>
                                            </div>
                                            <div className="text-right">
                                                <p className="text-sm font-medium">
                                                    {session.is_active
                                                        ? 'Active'
                                                        : session.duration_seconds
                                                            ? `${Math.round(session.duration_seconds / 60)} min`
                                                            : 'N/A'}
                                                </p>
                                                <p className="text-xs text-muted-foreground">
                                                    {formatDateTime(session.start_time || session.login_time)}
                                                </p>
                                            </div>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    </>
                )}
            </div>
        );
    };

    const renderEndpointsTab = () => (
        <div className="space-y-4">
            {loading ? (
                <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                </div>
            ) : (
                <>
                    {endpointSummary && (
                        <div className="grid grid-cols-3 gap-2 sm:gap-3">
                            <div className="p-2 sm:p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mt-2 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <Server className="h-4 w-4 text-[#0F6CBD] flex-shrink-0" />
                                    <span className="text-xs text-muted-foreground truncate">Total Requests</span>
                                </div>
                                <p className="text-lg sm:text-xl font-bold truncate">{formatNumber(endpointSummary.total_requests || 0)}</p>
                            </div>
                            <div className="p-2 sm:p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mt-2 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <Clock className="h-4 w-4 text-orange-500 flex-shrink-0" />
                                    <span className="text-xs text-muted-foreground truncate">Avg Response</span>
                                </div>
                                <p className="text-lg sm:text-xl font-bold truncate">{formatDuration(endpointSummary.avg_response_time || 0)}</p>
                            </div>
                            <div className="p-2 sm:p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mt-2 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <Activity className="h-4 w-4 text-red-600 flex-shrink-0" />
                                    <span className="text-xs text-muted-foreground truncate">Error Rate</span>
                                </div>
                                <p className="text-lg sm:text-xl font-bold truncate">{endpointSummary.error_rate ? `${(endpointSummary.error_rate * 100).toFixed(2)}%` : '0%'}</p>
                            </div>
                        </div>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                            <h3 className="font-semibold mb-3">Slowest Endpoints</h3>
                            <div className="space-y-2">
                                {slowestEndpoints.length === 0 ? (
                                    <p className="text-muted-foreground text-center py-4">No data</p>
                                ) : (
                                    slowestEndpoints.map((endpoint: any, idx: number) => (
                                        <div key={idx} className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg flex items-center justify-between hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                            <div>
                                                <p className="font-mono text-xs">{endpoint.endpoint}</p>
                                                <p className="text-xs text-muted-foreground">{endpoint.total_requests} requests</p>
                                            </div>
                                            <p className="text-lg font-bold text-orange-600">{formatDuration(endpoint.avg_response_time_ms || endpoint.avg_response_time || 0)}</p>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                        <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                            <h3 className="font-semibold mb-3">Error Summary</h3>
                            {errorSummary ? (
                                <div className="space-y-3">
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg text-center hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                            <p className="text-2xl font-bold text-red-600">{errorSummary.total_errors ?? 0}</p>
                                            <p className="text-xs text-muted-foreground">Total Errors</p>
                                        </div>
                                        <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg text-center hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                            <p className="text-2xl font-bold text-orange-600">{errorSummary.error_rate ?? 0}%</p>
                                            <p className="text-xs text-muted-foreground">Error Rate</p>
                                        </div>
                                    </div>
                                    <div className="flex justify-between text-sm p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <span className="text-muted-foreground">Client Errors (4xx)</span>
                                        <span className="font-semibold text-yellow-600">{errorSummary.client_errors ?? 0}</span>
                                    </div>
                                    <div className="flex justify-between text-sm p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <span className="text-muted-foreground">Server Errors (5xx)</span>
                                        <span className="font-semibold text-red-600">{errorSummary.server_errors ?? 0}</span>
                                    </div>
                                </div>
                            ) : endpointErrors.length === 0 ? (
                                <p className="text-muted-foreground text-center py-4">No errors</p>
                            ) : (
                                <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2">
                                    {endpointErrors.map((endpoint: any, idx: number) => (
                                        <div key={idx} className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg flex items-center justify-between hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                            <div>
                                                <p className="font-mono text-xs">{endpoint.method} {endpoint.endpoint}</p>
                                                <p className="text-xs text-muted-foreground">{endpoint.request_count} requests</p>
                                            </div>
                                            <div className="text-right">
                                                <p className="text-lg font-bold text-red-600">{endpoint.error_count} errors</p>
                                                <p className="text-xs text-muted-foreground">
                                                    {((endpoint.error_count / endpoint.request_count) * 100).toFixed(1)}%
                                                </p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    );

    const renderQueriesTab = () => (
        <div className="space-y-4">
            {loading ? (
                <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                </div>
            ) : (
                <>
                    {queryStats && (
                        <div className="grid grid-cols-3 gap-2 sm:gap-3">
                            <div className="flex flex-col h-full p-2 sm:p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mt-2 min-w-0">
                                <div className="flex items-start gap-2 mb-1">
                                    <Database className="h-4 w-4 text-[#0F6CBD] flex-shrink-0 mt-0.5" />
                                    <span className="text-xs text-muted-foreground">Total Queries</span>
                                </div>
                                <p className="text-lg sm:text-xl font-bold mt-auto truncate">{formatNumber(queryStats.total_queries || 0)}</p>
                            </div>
                            <div className="flex flex-col h-full p-2 sm:p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mt-2 min-w-0">
                                <div className="flex items-start gap-2 mb-1">
                                    <Clock className="h-4 w-4 text-orange-500 flex-shrink-0 mt-0.5" />
                                    <span className="text-xs text-muted-foreground">Avg Query Time</span>
                                </div>
                                <p className="text-lg sm:text-xl font-bold mt-auto truncate">{formatDuration(queryStats.avg_execution_time || 0)}</p>
                            </div>
                            <div className="flex flex-col h-full p-2 sm:p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mt-2 min-w-0">
                                <div className="flex items-start gap-2 mb-1">
                                    <Gauge className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
                                    <span className="text-xs text-muted-foreground">Slow Queries</span>
                                </div>
                                <p className="text-lg sm:text-xl font-bold mt-auto truncate">{queryStats.slow_query_count || 0}</p>
                            </div>
                        </div>
                    )}
                    <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                        <h3 className="font-semibold mb-3">Slowest Queries</h3>
                        <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2">
                            {slowQueries.length === 0 ? (
                                <p className="text-muted-foreground text-center py-4">No slow queries</p>
                            ) : (
                                slowQueries.map((query: any, idx: number) => (
                                    <div key={idx} className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg flex items-center justify-between hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <div>
                                            <p className="font-medium text-sm">{query.collection}</p>
                                            <p className="text-xs text-muted-foreground font-mono">{query.query_type} | {query.documents_returned} docs</p>
                                        </div>
                                        <p className="text-lg font-bold text-orange-600">{Math.round(query.execution_time_ms)}ms</p>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    );

    const renderStorageTab = () => (
        <div className="space-y-4">
            {loading ? (
                <div className="flex items-center justify-center py-12">
                    <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                </div>
            ) : (
                <>
                    {storage && (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <HardDrive className="h-4 w-4 text-[#0F6CBD]" />
                                    <span className="text-xs text-muted-foreground">MongoDB Size</span>
                                </div>
                                <p className="text-xl font-bold">
                                    {storage.database?.size_gb !== undefined ? `${storage.database.size_gb.toFixed(2)} GB` : '0 GB'}
                                </p>
                            </div>
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <Server className="h-4 w-4 text-orange-500" />
                                    <span className="text-xs text-muted-foreground">Collections</span>
                                </div>
                                <p className="text-xl font-bold">{storage.database?.collection_count || 0}</p>
                            </div>
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <Database className="h-4 w-4 text-blue-600" />
                                    <span className="text-xs text-muted-foreground">Blobs</span>
                                </div>
                                <p className="text-xl font-bold">{formatNumber(storage.blob_storage?.blob_count || 0)}</p>
                            </div>
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <Activity className="h-4 w-4 text-green-600" />
                                    <span className="text-xs text-muted-foreground">Containers</span>
                                </div>
                                <p className="text-xl font-bold">{storage.blob_storage?.container_count || 0}</p>
                            </div>
                        </div>
                    )}
                    {storageBreakdown?.collections && (
                        <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                            <h3 className="font-semibold mb-3">Storage by Collection</h3>
                            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2">
                                {storageBreakdown.collections.map((coll: any, idx: number) => (
                                    <div key={idx} className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg space-y-1 hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <div className="flex items-center justify-between text-sm">
                                            <span className="font-medium">{coll.name || coll.collection}</span>
                                            <div className="flex gap-3">
                                                <span className="text-muted-foreground">{formatNumber(coll.document_count)} docs</span>
                                                <span className="font-semibold">{coll.size_mb?.toFixed(2)} MB</span>
                                            </div>
                                        </div>
                                        <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                                            <div
                                                className="bg-gradient-to-r from-blue-700 to-blue-900 h-1.5 rounded-full"
                                                style={{ width: `${Math.min(coll.percentage || ((coll.size_mb / (storageBreakdown.total_size_mb || storage?.database?.size_mb || 1)) * 100), 100)}%` }}
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );

    const renderHealthTab = () => {
        // Extract system resources from components for metrics display
        const systemResources = health?.components?.system_resources;

        return (
            <div className="space-y-4">
                {loading ? (
                    <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                    </div>
                ) : health ? (
                    <>
                        {/* Overall Status */}
                        <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                            <div className="flex items-center gap-3">
                                <Heart className={`h-6 w-6 ${getStatusColor(health.status)}`} />
                                <div>
                                    <h2 className="text-lg font-bold">System Status</h2>
                                    <p className={`font-semibold capitalize ${getStatusColor(health.status)}`}>
                                        {health.status || 'Unknown'}
                                    </p>
                                </div>
                            </div>
                        </div>

                        {/* Components (was "Dependencies") */}
                        {health.components && (
                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                                <h3 className="font-semibold mb-3">Components</h3>
                                <div className="grid grid-cols-2 gap-2 max-h-[400px] overflow-y-auto pr-2">
                                    {Object.entries(health.components)
                                        .filter(([name]) => name !== 'system_resources') // Show system_resources separately
                                        .map(([name, comp]: [string, any]) => (
                                            <div key={name} className={`p-2 rounded-lg border shadow-sm ${getStatusBg(comp.status)} hover:scale-[1.02] hover:shadow-md transition-all cursor-pointer mx-3 mt-2`}>
                                                <div className="flex items-center justify-between">
                                                    <span className="font-medium capitalize text-sm">{name.replace(/_/g, ' ')}</span>
                                                    <span className={`text-xs font-bold uppercase ${getStatusColor(comp.status)}`}>
                                                        {comp.status}
                                                    </span>
                                                </div>
                                                {comp.error && <p className="text-xs text-red-600 mt-1">{comp.error}</p>}
                                                {comp.note && <p className="text-xs text-muted-foreground mt-1">{comp.note}</p>}
                                            </div>
                                        ))}
                                </div>
                            </div>
                        )}

                        {/* System Resources (Performance Metrics) */}
                        {systemResources && (
                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-shadow overflow-hidden">
                                <h3 className="font-semibold mb-3">System Resources</h3>
                                <div className="grid grid-cols-3 gap-3">
                                    <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <p className="text-xs text-muted-foreground mb-1">CPU Usage</p>
                                        <p className="text-lg font-bold">
                                            {systemResources.cpu_percent !== undefined ? `${systemResources.cpu_percent}%` : 'N/A'}
                                        </p>
                                    </div>
                                    <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <p className="text-xs text-muted-foreground mb-1">Memory Usage</p>
                                        <p className="text-lg font-bold">
                                            {systemResources.memory_percent !== undefined ? `${systemResources.memory_percent}%` : 'N/A'}
                                        </p>
                                    </div>
                                    <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <p className="text-xs text-muted-foreground mb-1">Disk Usage</p>
                                        <p className="text-lg font-bold">
                                            {systemResources.disk_percent !== undefined ? `${systemResources.disk_percent}%` : 'N/A'}
                                        </p>
                                    </div>
                                    <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <p className="text-xs text-muted-foreground mb-1">Memory Available</p>
                                        <p className="text-lg font-bold">
                                            {systemResources.memory_available_mb !== undefined ? `${systemResources.memory_available_mb} MB` : 'N/A'}
                                        </p>
                                    </div>
                                    <div className="p-2 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 rounded-lg hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer mx-3 mt-2">
                                        <p className="text-xs text-muted-foreground mb-1">Disk Free</p>
                                        <p className="text-lg font-bold">
                                            {systemResources.disk_free_gb !== undefined ? `${systemResources.disk_free_gb} GB` : 'N/A'}
                                        </p>
                                    </div>
                                    {systemResources.warning && (
                                        <div className="p-3 bg-orange-100 dark:bg-orange-900/30 rounded-lg">
                                            <p className="text-xs text-orange-600 font-semibold">Warning</p>
                                            <p className="text-sm text-orange-700">{systemResources.warning}</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </>
                ) : (
                    <p className="text-center text-muted-foreground py-8">Failed to load health data</p>
                )}
            </div>
        );
    };

    /* ========================= USER LIST VIEW ========================= */

    const renderUserList = () => {
        // Calculate organization totals from all users
        const orgTotals = users.reduce(
            (acc, u) => ({
                totalTokens: acc.totalTokens + (u.llm_usage.total_tokens || 0),
                totalRequests: acc.totalRequests + (u.llm_usage.total_requests || 0),
                totalCost: acc.totalCost + (u.llm_usage.total_cost_usd || 0),
            }),
            { totalTokens: 0, totalRequests: 0, totalCost: 0 }
        );

        const isAdmin = user?.role === 'admin';

        return (
            <div className="space-y-3">
                {/* Admin-only Organization Summary */}
                {isAdmin && users.length > 0 && (
                    <div className="p-4 bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-800/20 rounded-xl border-2 border-blue-200 dark:border-blue-700 mb-4">
                        <h3 className="font-semibold text-sm text-muted-foreground mb-3 flex items-center gap-2">
                            <Users className="h-4 w-4" />
                            Organization Totals ({users.length} users)
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer sm:mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <Zap className="h-4 w-4 text-orange-500" />
                                    <span className="text-xs font-medium text-muted-foreground">Total Tokens</span>
                                </div>
                                <p className="text-xl sm:text-2xl font-bold truncate">{formatNumber(orgTotals.totalTokens)}</p>
                            </div>
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer sm:mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <Activity className="h-4 w-4 text-blue-500" />
                                    <span className="text-xs font-medium text-muted-foreground">Total Requests</span>
                                </div>
                                <p className="text-xl sm:text-2xl font-bold text-blue-600 truncate">{formatNumber(orgTotals.totalRequests)}</p>
                            </div>
                            <div className="p-3 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] hover:shadow-md hover:border-slate-400 dark:hover:border-slate-500 transition-all cursor-pointer sm:mx-3 mt-2">
                                <div className="flex items-center gap-2 mb-1">
                                    <DollarSign className="h-4 w-4 text-green-500" />
                                    <span className="text-xs font-medium text-muted-foreground">Total Cost</span>
                                </div>
                                <p className="text-xl sm:text-2xl font-bold text-green-600 truncate">{formatCost(orgTotals.totalCost)}</p>
                            </div>
                        </div>
                    </div>
                )}

                {loading || !hasFetched ? (
                    <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                    </div>
                ) : error ? (
                    <div className="text-center py-8">
                        <p className="text-red-500 mb-2">{error}</p>
                        <Button variant="outline" size="sm" onClick={fetchUsers}>
                            Retry
                        </Button>
                    </div>
                ) : users.length === 0 ? (
                    <p className="text-center text-muted-foreground py-8">No users found</p>
                ) : (
                    users.map((u) => (
                    <div
                        key={u.id}
                        onClick={() => fetchUserDetail(u.id)}
                        className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl border border-white/30 dark:border-slate-700/30 hover:shadow-lg transition-all cursor-pointer hover:scale-[1.01] group"
                    >
                        <div className="flex items-center gap-3 min-w-0">
                            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[#0F6CBD] to-[#004E8C] flex items-center justify-center text-white font-bold flex-shrink-0">
                                {getUserDisplayName(u).charAt(0).toUpperCase()}
                            </div>
                            <div className="min-w-0">
                                <p className="font-medium truncate">{getUserDisplayName(u)}</p>
                                <p className="text-sm text-muted-foreground truncate">{u.email}</p>
                            </div>
                        </div>
                        <div className="flex items-center justify-between sm:justify-end gap-4 pl-[52px] sm:pl-0">
                            <div className="flex items-center gap-4 text-sm">
                                <div className="text-center">
                                    <p className="font-semibold">{formatNumber(u.llm_usage.total_tokens)}</p>
                                    <p className="text-muted-foreground text-xs">Tokens</p>
                                </div>
                                <div className="text-center">
                                    <p className="font-semibold">{u.llm_usage.total_requests}</p>
                                    <p className="text-muted-foreground text-xs">Requests</p>
                                </div>
                                <div className="text-center">
                                    <p className="font-semibold text-green-600">{formatCost(u.llm_usage.total_cost_usd)}</p>
                                    <p className="text-muted-foreground text-xs">Cost</p>
                                </div>
                            </div>
                            <ChevronRight className="w-5 h-5 text-muted-foreground group-hover:text-[#0F6CBD] transition-colors flex-shrink-0" />
                        </div>
                    </div>
                ))
            )}
        </div>
        );
    };

    /* ========================= PAGE LAYOUT ========================= */

    // Determine which sub-tabs to show
    const currentSubTabs = viewMode === 'byUser'
        ? (selectedUser ? userSubTabs : []) // Show sub-tabs only after selecting a user
        : globalSubTabs;

    return (
        <div className="h-screen app-glass-gradient text-foreground relative overflow-y-auto custom-visible-scrollbar-dark">
            {/* Decorative background images */}
            <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
                <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
            </div>
            <MainHeader showProjectActions={false}>
                <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
                    <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#0F6CBD] to-[#004E8C]">
                        Utilization
                    </h1>
                </div>
            </MainHeader>

            {/* Subtle gradient background */}
            <div className="absolute inset-0 bg-gradient-to-br from-ai-primary/10 via-ai-primary/5 to-background pointer-events-none" />

            {/* Main Content */}
            <div className="relative w-full max-w-6xl mx-auto pt-28 px-6 pb-6">

                {/* ========== TOP-LEVEL MODE SELECTOR: By User / By Global (Admin Only) ========== */}
                {user?.role === 'admin' ? (
                    <div className="flex items-center justify-between mb-6">
                        <div className="flex bg-white/70 dark:bg-slate-800/70 rounded-xl p-1 border border-gray-200 dark:border-slate-700 shadow-sm">
                            <button
                                onClick={() => {
                                    setViewMode('byUser');
                                    setActiveTab('');
                                    setSelectedUser(null);
                                    setTabError(null);
                                }}
                                className={`flex items-center gap-2 px-6 py-2.5 rounded-lg font-semibold transition-all text-sm ${viewMode === 'byUser'
                                    ? 'bg-gradient-to-r from-[#0F6CBD] to-[#004E8C] text-white shadow-lg'
                                    : 'text-foreground hover:bg-white/80 dark:hover:bg-slate-700/80'
                                    }`}
                            >
                                <Users className="w-4 h-4" />
                                By User
                            </button>
                            <button
                                onClick={() => {
                                    setViewMode('byGlobal');
                                    setActiveTab('sessions');
                                    setSelectedUser(null);
                                    setTabError(null);
                                }}
                                className={`flex items-center gap-2 px-6 py-2.5 rounded-lg font-semibold transition-all text-sm ${viewMode === 'byGlobal'
                                    ? 'bg-gradient-to-r from-[#0F6CBD] to-[#004E8C] text-white shadow-lg'
                                    : 'text-foreground hover:bg-white/80 dark:hover:bg-slate-700/80'
                                    }`}
                            >
                                <Globe className="w-4 h-4" />
                                By Global
                            </button>
                        </div>

                        {/* Refresh and Back buttons */}
                        <div className="flex items-center gap-3">
                            {/* Refresh button */}
                            <button
                                onClick={handleRefresh}
                                disabled={isRefreshing}
                                className="flex items-center gap-2 px-2.5 sm:px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                                title="Refresh Data"
                            >
                                <RefreshCw className={`w-5 h-5 ${isRefreshing ? 'animate-spin' : ''}`} />
                                <span className="hidden sm:inline font-medium">Refresh</span>
                            </button>

                        </div>
                    </div>
                ) : (
                    /* For regular users, show refresh button */
                    <div className="flex items-center justify-end gap-3 mb-6">
                        {/* Refresh button */}
                        <button
                            onClick={handleRefresh}
                            disabled={isRefreshing}
                            className="flex items-center gap-2 px-2.5 sm:px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
                            title="Refresh Data"
                        >
                            <RefreshCw className={`w-5 h-5 ${isRefreshing ? 'animate-spin' : ''}`} />
                            <span className="hidden sm:inline font-medium">Refresh</span>
                        </button>
                    </div>
                )}

                {/* ========== SUB-TAB NAVIGATION ========== */}
                {currentSubTabs.length > 0 && (
                    <div className="flex items-center justify-between mb-5">
                        <div className="flex gap-2 flex-wrap">
                            {currentSubTabs.map((tab) => {
                                const Icon = tab.icon;
                                return (
                                    <button
                                        key={tab.id}
                                        onClick={() => { setActiveTab(tab.id); setTabError(null); }}
                                        className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm ${activeTab === tab.id
                                            ? 'bg-[#0F6CBD] text-white shadow-lg'
                                            : 'bg-white/70 dark:bg-slate-800/70 text-foreground hover:bg-white dark:hover:bg-slate-800 border border-gray-200 dark:border-slate-700'
                                            }`}
                                    >
                                        <Icon className="w-4 h-4" />
                                        {tab.label}
                                    </button>
                                );
                            })}
                        </div>

                        {/* Back to Users button - aligned with sub-tabs when user is selected */}
                        {selectedUser && user?.role === 'admin' && (
                            <button
                                onClick={() => {
                                    setSelectedUser(null);
                                    setActiveTab('');
                                }}
                                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-slate-700 hover:text-slate-900 border border-gray-200 dark:border-slate-700 dark:text-slate-400 dark:hover:text-slate-100 transition-all hover:scale-105 shadow-sm"
                                title="Back to Users"
                            >
                                <ArrowLeft className="w-5 h-5" />
                                <span className="font-medium">Users</span>
                            </button>
                        )}
                    </div>
                )}

                {/* Time Period Selector */}
                {((viewMode === 'byGlobal' && activeTab !== 'health') || (viewMode === 'byUser')) && (
                    <div className="flex gap-2 mb-5 relative">
                        <div className="relative">
                            <button
                                onClick={() => setShowTimeDropdown(!showTimeDropdown)}
                                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/70 dark:bg-slate-800/70 text-foreground border border-gray-200 dark:border-slate-700 hover:bg-white dark:hover:bg-slate-800 transition-all shadow-sm"
                            >
                                <Calendar className="w-4 h-4 text-[#0F6CBD]" />
                                <span className="font-medium">
                                    {selectedDateRange
                                        ? `${selectedDateRange.from} - ${selectedDateRange.to}`
                                        : 'All Time'}
                                </span>
                                <ChevronRight className={`w-4 h-4 transition-transform ${showTimeDropdown ? 'rotate-90' : ''}`} />
                            </button>

                            {showTimeDropdown && (
                                <div className="absolute top-full left-0 mt-2 w-80 bg-slate-100 dark:bg-slate-800 shadow-sm border border-slate-300 dark:border-slate-600 backdrop-blur-xl rounded-xl border border-white/30 dark:border-slate-700/30 shadow-2xl z-50 overflow-hidden">
                                    <div className="p-4">
                                        <p className="text-xs text-muted-foreground mb-3 font-semibold">Select Date & Time Range</p>
                                        <div className="space-y-4">
                                            {/* From Date & Time */}
                                            <div className="space-y-2">
                                                <p className="text-xs font-medium text-foreground">From</p>
                                                <div className="space-y-2">
                                                    <div>
                                                        <label className="text-xs text-muted-foreground mb-1 block">Date *</label>
                                                        <input
                                                            type="date"
                                                            value={dateFrom}
                                                            onChange={(e) => setDateFrom(e.target.value)}
                                                            max={dateTo || new Date().toISOString().split('T')[0]}
                                                            required
                                                            className="w-full px-2 py-1.5 rounded-lg border border-white/30 dark:border-slate-600/30 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm text-xs focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="text-xs text-muted-foreground mb-1 block">Time</label>
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <select
                                                                value={hourFrom}
                                                                onChange={(e) => setHourFrom(e.target.value)}
                                                                className="w-full px-2 py-1.5 rounded-lg border border-white/30 dark:border-slate-600/30 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm text-xs focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]"
                                                            >
                                                                {Array.from({ length: 24 }, (_, i) => (
                                                                    <option key={i} value={i.toString().padStart(2, '0')}>
                                                                        {i.toString().padStart(2, '0')} hr
                                                                    </option>
                                                                ))}
                                                            </select>
                                                            <select
                                                                value={minuteFrom}
                                                                onChange={(e) => setMinuteFrom(e.target.value)}
                                                                className="w-full px-2 py-1.5 rounded-lg border border-white/30 dark:border-slate-600/30 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm text-xs focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]"
                                                            >
                                                                {Array.from({ length: 60 }, (_, i) => (
                                                                    <option key={i} value={i.toString().padStart(2, '0')}>
                                                                        {i.toString().padStart(2, '0')} min
                                                                    </option>
                                                                ))}
                                                            </select>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* To Date & Time */}
                                            <div className="space-y-2">
                                                <p className="text-xs font-medium text-foreground">To</p>
                                                <div className="space-y-2">
                                                    <div>
                                                        <label className="text-xs text-muted-foreground mb-1 block">Date *</label>
                                                        <input
                                                            type="date"
                                                            value={dateTo}
                                                            onChange={(e) => setDateTo(e.target.value)}
                                                            min={dateFrom}
                                                            max={new Date().toISOString().split('T')[0]}
                                                            required
                                                            className="w-full px-2 py-1.5 rounded-lg border border-white/30 dark:border-slate-600/30 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm text-xs focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="text-xs text-muted-foreground mb-1 block">Time</label>
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <select
                                                                value={hourTo}
                                                                onChange={(e) => setHourTo(e.target.value)}
                                                                className="w-full px-2 py-1.5 rounded-lg border border-white/30 dark:border-slate-600/30 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm text-xs focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]"
                                                            >
                                                                {Array.from({ length: 24 }, (_, i) => (
                                                                    <option key={i} value={i.toString().padStart(2, '0')}>
                                                                        {i.toString().padStart(2, '0')} hr
                                                                    </option>
                                                                ))}
                                                            </select>
                                                            <select
                                                                value={minuteTo}
                                                                onChange={(e) => setMinuteTo(e.target.value)}
                                                                className="w-full px-2 py-1.5 rounded-lg border border-white/30 dark:border-slate-600/30 bg-white/60 dark:bg-slate-700/60 backdrop-blur-sm text-xs focus:outline-none focus:ring-2 focus:ring-[#0F6CBD]"
                                                            >
                                                                {Array.from({ length: 60 }, (_, i) => (
                                                                    <option key={i} value={i.toString().padStart(2, '0')}>
                                                                        {i.toString().padStart(2, '0')} min
                                                                    </option>
                                                                ))}
                                                            </select>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>

                                            <Button
                                                size="sm"
                                                onClick={() => {
                                                    if (dateFrom && dateTo) {
                                                        // Combine date and time
                                                        const fromTime = `${hourFrom}:${minuteFrom}`;
                                                        const toTime = `${hourTo}:${minuteTo}`;
                                                        const fromDateTime = new Date(`${dateFrom}T${fromTime}`);
                                                        const toDateTime = new Date(`${dateTo}T${toTime}`);

                                                        const now = new Date();
                                                        const endDate = toDateTime > now ? now : toDateTime;
                                                        const diffMs = endDate.getTime() - fromDateTime.getTime();
                                                        const diffHours = Math.ceil(diffMs / (1000 * 60 * 60));

                                                        if (diffHours > 0) {
                                                            setTimePeriod(diffHours);
                                                            const formatDateTime = (d: Date) => d.toLocaleString('en-GB', {
                                                                day: '2-digit', month: '2-digit', year: 'numeric',
                                                                hour: '2-digit', minute: '2-digit', hour12: false
                                                            });
                                                            setSelectedDateRange({
                                                                from: formatDateTime(fromDateTime),
                                                                to: formatDateTime(toDateTime)
                                                            });
                                                            setShowTimeDropdown(false);
                                                        }
                                                    }
                                                }}
                                                disabled={!dateFrom || !dateTo}
                                                className="w-full bg-[#0F6CBD] hover:bg-[#004E8C]"
                                            >
                                                Apply Date & Time Range
                                            </Button>
                                            <p className="text-xs text-muted-foreground text-center">* Required fields</p>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Click outside to close dropdown */}
                        {showTimeDropdown && (
                            <div
                                className="fixed inset-0 z-40"
                                onClick={() => setShowTimeDropdown(false)}
                            />
                        )}
                    </div>
                )}

                {/* Content Area */}
                <div className="bg-white/50 dark:bg-slate-900/50 backdrop-blur-xl rounded-2xl p-8 border border-white/30 dark:border-slate-700/30 shadow-lg min-h-[100px] transition-all duration-300 hover:shadow-xl overflow-visible">

                    {/* Show tab-level error */}
                    {tabError && activeTab !== 'users' && activeTab !== 'llm' && activeTab !== 'sessions' && (
                        <div className="text-center py-8">
                            <p className="text-red-500 mb-2">{tabError}</p>
                            <Button variant="outline" size="sm" onClick={() => {
                                if (activeTab === 'endpoints') fetchEndpoints();
                                else if (activeTab === 'queries') fetchQueries();
                                else if (activeTab === 'storage') fetchStorage();
                                else if (activeTab === 'health') fetchHealth();
                            }}>
                                Retry
                            </Button>
                        </div>
                    )}

                    {/* ===== BY USER MODE ===== */}
                    {viewMode === 'byUser' && !selectedUser && !detailLoading && (
                        // Show user list
                        renderUserList()
                    )}
                    {viewMode === 'byUser' && detailLoading && !selectedUser && (
                        // Loading state when fetching user details
                        <div className="flex flex-col items-center justify-center py-20">
                            <Loader2 className="h-16 w-16 animate-spin text-[#0F6CBD] mb-4" />
                            <p className="text-lg font-medium text-foreground">Loading user details...</p>
                            <p className="text-sm text-muted-foreground mt-2">Please wait</p>
                        </div>
                    )}
                    {viewMode === 'byUser' && selectedUser && (
                        // User-specific sub-tab content
                        <>
                            {activeTab === 'llm' && renderLLMTab()}
                            {activeTab === 'sessions' && renderSessionsTab()}
                        </>
                    )}

                    {/* ===== BY GLOBAL MODE ===== */}
                    {viewMode === 'byGlobal' && (
                        <>
                            {activeTab === 'sessions' && renderSessionsTab()}
                            {activeTab === 'endpoints' && !tabError && renderEndpointsTab()}
                            {activeTab === 'queries' && !tabError && renderQueriesTab()}
                            {activeTab === 'storage' && !tabError && renderStorageTab()}
                            {activeTab === 'health' && !tabError && renderHealthTab()}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default UtilizationPage;
