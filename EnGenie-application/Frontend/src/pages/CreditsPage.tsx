import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import {
    Loader2,
    Wallet,
    TrendingDown,
    Gift,
    Zap,
    ShieldCheck,
    Activity,
} from "lucide-react";
import MainHeader from "@/components/MainHeader";
import { Button } from "@/components/ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/contexts/AuthContext";

const PAGE_SIZE = 25;

interface CreditSummary {
    balance: number;
    total_granted: number;
    total_consumed: number;
    enforcement_enabled: boolean;
    workflow_costs: Record<string, number>;
}

interface CreditTransaction {
    timestamp: string;
    type: string; // charge | grant | topup | adjustment | refund
    amount: number;
    delta: number;
    balance_after: number;
    workflow_type?: string | null;
    stream_id?: string | null;
    description?: string;
    performed_by?: string | null;
}

const TYPE_STYLES: Record<string, string> = {
    charge: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    grant: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    topup: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    refund: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
    adjustment: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
};

const TYPE_LABELS: Record<string, string> = {
    charge: "Charge",
    grant: "Grant",
    topup: "Top-up",
    refund: "Refund",
    adjustment: "Adjustment",
};

const CreditsPage = () => {
    const { user, isLoading: authLoading } = useAuth();

    const [summary, setSummary] = useState<CreditSummary | null>(null);
    const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchCredits = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [balanceRes, historyRes] = await Promise.all([
                axios.get("/api/credits/balance"),
                axios.get(`/api/credits/history?limit=${PAGE_SIZE}&skip=0`),
            ]);
            setSummary(balanceRes.data);
            const txns: CreditTransaction[] = historyRes.data?.transactions || [];
            setTransactions(txns);
            setHasMore(txns.length === PAGE_SIZE);
        } catch (err: any) {
            console.error("Failed to fetch credits:", err);
            setError(err.response?.data?.error || err.message || "Failed to load credits");
        } finally {
            setLoading(false);
        }
    }, []);

    const loadMore = async () => {
        setLoadingMore(true);
        try {
            const res = await axios.get(
                `/api/credits/history?limit=${PAGE_SIZE}&skip=${transactions.length}`,
            );
            const txns: CreditTransaction[] = res.data?.transactions || [];
            setTransactions((prev) => [...prev, ...txns]);
            setHasMore(txns.length === PAGE_SIZE);
        } catch (err: any) {
            console.error("Failed to fetch more transactions:", err);
        } finally {
            setLoadingMore(false);
        }
    };

    useEffect(() => {
        if (user) {
            fetchCredits();
        }
    }, [user, fetchCredits]);

    if (authLoading) {
        return (
            <div className="min-h-screen app-glass-gradient flex items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
            </div>
        );
    }
    if (!user) return null;

    const solutionCost = summary?.workflow_costs?.solution;
    const searchCost = summary?.workflow_costs?.search;

    return (
        <div className="h-screen app-glass-gradient text-foreground relative overflow-y-auto custom-visible-scrollbar-dark">
            <MainHeader showProjectActions={false}>
                <div className="absolute left-1/2 transform -translate-x-1/2 text-center">
                    <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#0F6CBD] to-[#004E8C]">
                        Credits
                    </h1>
                </div>
            </MainHeader>
            <div className="absolute inset-0 bg-gradient-to-br from-ai-primary/10 via-ai-primary/5 to-background pointer-events-none" />

            <div className="relative w-full max-w-6xl mx-auto pt-28 px-6 pb-6">
                {loading ? (
                    <div className="flex items-center justify-center py-12">
                        <Loader2 className="h-8 w-8 animate-spin text-[#0F6CBD]" />
                    </div>
                ) : error ? (
                    <div className="text-center py-8">
                        <p className="text-red-500 mb-2">{error}</p>
                        <Button variant="outline" size="sm" onClick={fetchCredits}>
                            Retry
                        </Button>
                    </div>
                ) : (
                    <>
                        {/* Stat cards */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] transition-transform">
                                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                                    <Wallet className="h-4 w-4" />
                                    Current Balance
                                </div>
                                <div className="text-3xl font-bold text-[#0F6CBD]">
                                    {summary?.balance ?? 0}
                                </div>
                            </div>

                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] transition-transform">
                                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                                    <TrendingDown className="h-4 w-4" />
                                    Total Used
                                </div>
                                <div className="text-3xl font-bold">
                                    {summary?.total_consumed ?? 0}
                                </div>
                            </div>

                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] transition-transform">
                                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                                    <Gift className="h-4 w-4" />
                                    Total Received
                                </div>
                                <div className="text-3xl font-bold">
                                    {summary?.total_granted ?? 0}
                                </div>
                            </div>

                            <div className="p-4 bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl hover:scale-[1.02] transition-transform">
                                <div className="flex items-center gap-2 text-muted-foreground text-sm mb-1">
                                    <Zap className="h-4 w-4" />
                                    Cost per Run
                                </div>
                                <div className="text-sm space-y-1 mt-1">
                                    <div className="flex justify-between">
                                        <span className="text-muted-foreground">Solution agent</span>
                                        <span className="font-semibold">{solutionCost ?? "—"}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-muted-foreground">Search agent</span>
                                        <span className="font-semibold">{searchCost ?? "—"}</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Mode banner */}
                        <div className="flex items-center gap-2 mb-6 text-sm text-muted-foreground">
                            {summary?.enforcement_enabled ? (
                                <>
                                    <ShieldCheck className="h-4 w-4 text-[#0F6CBD]" />
                                    Credits are enforced — runs are blocked when your balance is
                                    too low. Failed runs are never charged.
                                </>
                            ) : (
                                <>
                                    <Activity className="h-4 w-4 text-[#0F6CBD]" />
                                    Usage tracking mode — credits are recorded per workflow run
                                    but never block your work. Failed runs are never charged.
                                </>
                            )}
                        </div>

                        {/* Transaction history */}
                        <div className="bg-slate-50 dark:bg-slate-800 shadow-sm border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
                            <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
                                <h2 className="font-semibold">Transaction History</h2>
                            </div>
                            {transactions.length === 0 ? (
                                <p className="text-muted-foreground text-center py-8">
                                    No credit activity yet. Run a search or solution workflow to
                                    see charges appear here.
                                </p>
                            ) : (
                                <>
                                    <div className="overflow-x-auto">
                                        <Table>
                                            <TableHeader>
                                                <TableRow>
                                                    <TableHead>Date</TableHead>
                                                    <TableHead>Type</TableHead>
                                                    <TableHead>Details</TableHead>
                                                    <TableHead className="text-right">Credits</TableHead>
                                                    <TableHead className="text-right">Balance</TableHead>
                                                </TableRow>
                                            </TableHeader>
                                            <TableBody>
                                                {transactions.map((txn, i) => (
                                                    <TableRow key={`${txn.stream_id || txn.timestamp}-${i}`}>
                                                        <TableCell className="whitespace-nowrap text-muted-foreground">
                                                            {txn.timestamp
                                                                ? new Date(txn.timestamp).toLocaleString()
                                                                : "—"}
                                                        </TableCell>
                                                        <TableCell>
                                                            <span
                                                                className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                                                                    TYPE_STYLES[txn.type] ||
                                                                    "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300"
                                                                }`}
                                                            >
                                                                {TYPE_LABELS[txn.type] || txn.type}
                                                            </span>
                                                        </TableCell>
                                                        <TableCell className="max-w-[320px] truncate">
                                                            {txn.description || "—"}
                                                            {txn.workflow_type && (
                                                                <span className="ml-2 text-xs text-muted-foreground">
                                                                    ({txn.workflow_type})
                                                                </span>
                                                            )}
                                                        </TableCell>
                                                        <TableCell
                                                            className={`text-right font-semibold ${
                                                                txn.delta < 0
                                                                    ? "text-red-600 dark:text-red-400"
                                                                    : "text-emerald-600 dark:text-emerald-400"
                                                            }`}
                                                        >
                                                            {txn.delta > 0 ? `+${txn.delta}` : txn.delta}
                                                        </TableCell>
                                                        <TableCell className="text-right text-muted-foreground">
                                                            {txn.balance_after}
                                                        </TableCell>
                                                    </TableRow>
                                                ))}
                                            </TableBody>
                                        </Table>
                                    </div>
                                    {hasMore && (
                                        <div className="flex justify-center py-3 border-t border-slate-200 dark:border-slate-700">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={loadMore}
                                                disabled={loadingMore}
                                            >
                                                {loadingMore && (
                                                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                                )}
                                                Load more
                                            </Button>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default CreditsPage;
