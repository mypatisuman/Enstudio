import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import MainHeader from "@/components/MainHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/use-toast";
import { Gauge, Play, Download, Loader2, RefreshCw, X, Trash2, AlertTriangle, Star, GitCompare, Cpu, Trophy } from "lucide-react";

interface ModelStat {
  model_name: string;
  provider: string;
  llm_calls: number;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  cost_per_1k_tokens: number;
  avg_tokens_per_call: number;
  avg_response_time_ms: number;
  max_response_time_ms: number;
  success_rate: number;
  last_used: string | null;
}

interface BenchmarkRun {
  run_id: string;
  suite_key: string;
  suite_name: string;
  agent_type: string;
  source?: "suite" | "live";
  input?: string;
  is_baseline?: boolean;
  status: "running" | "completed" | "failed" | "cancelled";
  started_at: string | null;
  duration_ms: number;
  total_tests: number;
  passed: number;
  failed: number;
  summary?: {
    total_llm_calls?: number;
    total_tokens?: number;
    total_cost_usd?: number;
    avg_response_time_ms?: number;
  };
  environment?: Record<string, unknown>;
}

const POLL_MS = 4000;

export default function Benchmarks() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [suites, setSuites] = useState<string[]>([]);
  const [selectedSuite, setSelectedSuite] = useState<string>("");
  const [provider, setProvider] = useState<string>("");
  const [activeModels, setActiveModels] = useState<Record<string, string>>({});

  // Per-model leaderboard state.
  const [modelStats, setModelStats] = useState<ModelStat[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelDays, setModelDays] = useState<string>("30");
  const [modelAgent, setModelAgent] = useState<string>("all");
  const [modelSource, setModelSource] = useState<string>("all");
  const [modelA, setModelA] = useState<string>("");
  const [modelB, setModelB] = useState<string>("");
  const [modelComparing, setModelComparing] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [modelCompareResult, setModelCompareResult] = useState<any | null>(null);
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [sourceFilter, setSourceFilter] = useState<"all" | "suite" | "live">("all");
  const [starting, setStarting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Compare panel state.
  const [compareNew, setCompareNew] = useState<string>("");
  const [compareBaseline, setCompareBaseline] = useState<string>("");
  const [comparing, setComparing] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [compareResult, setCompareResult] = useState<any | null>(null);

  // run_ids we are actively polling; auto-download fires once when they complete.
  const activeRuns = useRef<Set<string>>(new Set());
  const autoDownloaded = useRef<Set<string>>(new Set());

  const fetchSuites = useCallback(async () => {
    try {
      const res = await axios.get("/api/benchmarks/suites");
      const list: string[] = res.data?.suites ?? [];
      setSuites(list);
      setProvider(res.data?.provider ?? "unknown");
      setActiveModels(res.data?.models ?? {});
      // Default to "all" so a single click runs every workflow with no input.
      setSelectedSuite((prev) => prev || "all");
    } catch {
      toast({ title: "Error", description: "Failed to load suites.", variant: "destructive" });
    }
  }, [toast]);

  const fetchRuns = useCallback(async () => {
    try {
      const params: Record<string, unknown> = { limit: 50 };
      if (sourceFilter !== "all") params.source = sourceFilter;
      const res = await axios.get("/api/benchmarks/runs", { params });
      const list: BenchmarkRun[] = res.data ?? [];
      setRuns(list);
      // Track any still-running runs so the poller keeps them alive across reloads.
      list.forEach((r) => {
        if (r.status === "running") activeRuns.current.add(r.run_id);
      });
    } catch {
      toast({ title: "Error", description: "Failed to load runs.", variant: "destructive" });
    }
  }, [toast, sourceFilter]);

  const fetchModelStats = useCallback(async () => {
    setModelsLoading(true);
    try {
      const params: Record<string, unknown> = { days: modelDays };
      if (modelAgent !== "all") params.agent_type = modelAgent;
      if (modelSource !== "all") params.source = modelSource;
      const res = await axios.get("/api/benchmarks/models", { params });
      setModelStats(res.data?.models ?? []);
    } catch {
      toast({ title: "Error", description: "Failed to load model stats.", variant: "destructive" });
    } finally {
      setModelsLoading(false);
    }
  }, [toast, modelDays, modelAgent, modelSource]);

  const runModelCompare = async () => {
    if (!modelA || !modelB || modelA === modelB) {
      toast({ title: "Pick two different models", variant: "destructive" });
      return;
    }
    setModelComparing(true);
    setModelCompareResult(null);
    try {
      const res = await axios.post("/api/benchmarks/models/compare", {
        model_a: modelA, model_b: modelB, days: Number(modelDays),
      });
      setModelCompareResult(res.data);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } catch (e: any) {
      toast({
        title: "Compare failed",
        description: e?.response?.data?.error || "Could not compare models.",
        variant: "destructive",
      });
    } finally {
      setModelComparing(false);
    }
  };

  useEffect(() => {
    fetchSuites();
  }, [fetchSuites]);

  useEffect(() => {
    fetchModelStats();
  }, [fetchModelStats]);

  // Reload the runs list on mount and whenever the source filter changes.
  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Poll active runs; refresh list + auto-download on completion.
  useEffect(() => {
    const id = setInterval(async () => {
      if (activeRuns.current.size === 0) return;
      const ids = Array.from(activeRuns.current);
      let anyFinished = false;
      await Promise.all(
        ids.map(async (runId) => {
          try {
            const res = await axios.get(`/api/benchmarks/runs/${runId}/status`);
            const status = res.data?.status;
            if (status === "completed" || status === "failed") {
              activeRuns.current.delete(runId);
              anyFinished = true;
              if (status === "completed" && !autoDownloaded.current.has(runId)) {
                autoDownloaded.current.add(runId);
                downloadReport(runId, true);
              }
            }
          } catch {
            /* keep polling; transient error */
          }
        }),
      );
      if (anyFinished) fetchRuns();
    }, POLL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchRuns]);

  const startRun = async () => {
    if (!selectedSuite) return;
    setStarting(true);
    try {
      const res = await axios.post("/api/benchmarks/run", { suite: selectedSuite });
      // "all" returns several run_ids; a single suite returns one.
      const runIds: string[] = res.data?.run_ids ?? (res.data?.run_id ? [res.data.run_id] : []);
      if (runIds.length) {
        runIds.forEach((id) => activeRuns.current.add(id));
        toast({
          title: runIds.length > 1 ? "Benchmarks started" : "Benchmark started",
          description: `Running ${selectedSuite === "all" ? "all workflows" : `"${selectedSuite}"`}. Report${runIds.length > 1 ? "s" : ""} download automatically when each completes.`,
        });
        fetchRuns();
      }
    } catch (e: any) {
      toast({
        title: "Failed to start",
        description: e?.response?.data?.error || "Could not start the benchmark run.",
        variant: "destructive",
      });
    } finally {
      setStarting(false);
    }
  };

  const downloadReport = async (runId: string, auto = false) => {
    setDownloadingId(runId);
    try {
      // Prefer the detailed server-side PDF (reportlab). Fall back to the simple
      // client-side jsPDF report if the server can't produce it (e.g. 501).
      try {
        const res = await axios.get(`/api/benchmarks/runs/${runId}/report.pdf`, { responseType: "blob" });
        const url = window.URL.createObjectURL(res.data as Blob);
        const a = document.createElement("a");
        a.href = url;
        a.setAttribute("download", `benchmark_${runId}.pdf`);
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      } catch {
        const res = await axios.get(`/api/benchmarks/runs/${runId}`);
        await generatePdf(res.data);
      }
      if (!auto) toast({ title: "Downloaded", description: `Report for ${runId} saved.` });
    } catch {
      toast({ title: "Download failed", description: `Could not build report for ${runId}.`, variant: "destructive" });
    } finally {
      setDownloadingId(null);
    }
  };

  const cancelRun = async (runId: string) => {
    setBusyId(runId);
    try {
      await axios.post(`/api/benchmarks/runs/${runId}/cancel`);
      activeRuns.current.delete(runId);
      toast({ title: "Cancelled", description: `Stopped tracking ${runId}.` });
      fetchRuns();
    } catch {
      toast({ title: "Cancel failed", description: `Could not cancel ${runId}.`, variant: "destructive" });
    } finally {
      setBusyId(null);
    }
  };

  const deleteRun = async (runId: string) => {
    setBusyId(runId);
    try {
      await axios.delete(`/api/benchmarks/runs/${runId}`);
      activeRuns.current.delete(runId);
      autoDownloaded.current.delete(runId);
      toast({ title: "Deleted", description: `Removed ${runId}.` });
      fetchRuns();
    } catch {
      toast({ title: "Delete failed", description: `Could not delete ${runId}.`, variant: "destructive" });
    } finally {
      setBusyId(null);
    }
  };

  const cleanupStale = async () => {
    try {
      const res = await axios.post("/api/benchmarks/runs/cleanup", { max_age_minutes: 30 });
      const n = res.data?.cleaned ?? 0;
      toast({ title: "Clean-up done", description: n ? `Flagged ${n} stuck run(s) as failed.` : "No stuck runs found." });
      fetchRuns();
    } catch {
      toast({ title: "Clean-up failed", description: "Could not clean up stuck runs.", variant: "destructive" });
    }
  };

  const toggleBaseline = async (run: BenchmarkRun) => {
    setBusyId(run.run_id);
    try {
      await axios.post(`/api/benchmarks/runs/${run.run_id}/baseline`, { is_baseline: !run.is_baseline });
      toast({ title: run.is_baseline ? "Baseline cleared" : "Baseline set", description: run.run_id });
      fetchRuns();
    } catch {
      toast({ title: "Failed", description: "Could not update baseline.", variant: "destructive" });
    } finally {
      setBusyId(null);
    }
  };

  const runCompare = async () => {
    if (!compareNew || !compareBaseline || compareNew === compareBaseline) {
      toast({ title: "Pick two different runs", variant: "destructive" });
      return;
    }
    setComparing(true);
    setCompareResult(null);
    try {
      const res = await axios.post("/api/benchmarks/compare", {
        run_new: compareNew,
        run_baseline: compareBaseline,
        threshold_pct: 5.0,
      });
      setCompareResult(res.data);
    } catch (e: any) {
      toast({ title: "Compare failed", description: e?.response?.data?.error || "Could not compare runs.", variant: "destructive" });
    } finally {
      setComparing(false);
    }
  };

  const fmtCost = (c?: number) => (c == null ? "-" : `$${c.toFixed(6)}`);
  const fmtNum = (n?: number) => (n == null ? "-" : n.toLocaleString());
  const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleString() : "-");

  const statusBadge = (s: BenchmarkRun["status"]) => {
    const map: Record<string, string> = {
      running: "bg-blue-100 text-blue-700",
      completed: "bg-green-100 text-green-700",
      failed: "bg-red-100 text-red-700",
      cancelled: "bg-amber-100 text-amber-700",
    };
    return <Badge className={map[s] || ""}>{s}</Badge>;
  };

  return (
    <div className="min-h-screen bg-background">
      <MainHeader />
      <div className="max-w-6xl mx-auto p-6">
        <div className="flex items-center gap-3 mb-6">
          <Gauge className="h-7 w-7 text-primary" />
          <div className="flex-1">
            <h1 className="text-2xl font-bold">Benchmarks</h1>
            <p className="text-sm text-muted-foreground">
              Measure model performance across the chat, search and solution agent workflows.
            </p>
          </div>
          {provider && (
            <Badge className="bg-blue-100 text-blue-700" title="LLM provider in-process runs will use">
              Provider: {provider}
            </Badge>
          )}
        </div>

        {/* Active models — what a run started right now would actually benchmark */}
        {Object.keys(activeModels).length > 0 && (
          <div className="mb-6 flex flex-wrap items-center gap-2 rounded-md border border-blue-200 bg-blue-50 dark:border-blue-900/40 dark:bg-blue-900/20 p-3 text-sm">
            <Cpu className="h-4 w-4 text-blue-600 dark:text-blue-400 shrink-0" />
            <span className="text-muted-foreground">Runs started now will benchmark:</span>
            {Object.entries(activeModels).map(([tier, model]) => (
              <Badge key={tier} variant="outline" className="font-mono text-xs">
                {tier}: {model}
              </Badge>
            ))}
          </div>
        )}

        {/* Per-model leaderboard */}
        <Card className="mb-6">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 flex-wrap gap-2">
            <CardTitle className="text-lg flex items-center gap-2">
              <Trophy className="h-5 w-5" /> Model leaderboard
            </CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={modelAgent} onValueChange={setModelAgent}>
                <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All agents</SelectItem>
                  <SelectItem value="solution">Solution</SelectItem>
                  <SelectItem value="search">Search</SelectItem>
                  <SelectItem value="chat">Chat</SelectItem>
                </SelectContent>
              </Select>
              <Select value={modelSource} onValueChange={setModelSource}>
                <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All runs</SelectItem>
                  <SelectItem value="live">Live only</SelectItem>
                  <SelectItem value="suite">Suite only</SelectItem>
                </SelectContent>
              </Select>
              <Select value={modelDays} onValueChange={setModelDays}>
                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="7">Last 7 days</SelectItem>
                  <SelectItem value="30">Last 30 days</SelectItem>
                  <SelectItem value="90">Last 90 days</SelectItem>
                  <SelectItem value="365">Last year</SelectItem>
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={fetchModelStats}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {modelsLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : modelStats.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No model data in this window yet. Every real search / solution / chat request is
                captured automatically — run one, or start a suite above.
              </p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Model</TableHead>
                        <TableHead>Provider</TableHead>
                        <TableHead className="text-right">Calls</TableHead>
                        <TableHead className="text-right">Runs</TableHead>
                        <TableHead className="text-right">Tokens</TableHead>
                        <TableHead className="text-right">Avg latency</TableHead>
                        <TableHead className="text-right">Cost</TableHead>
                        <TableHead className="text-right">$/1K tok</TableHead>
                        <TableHead className="text-right">Success</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {modelStats.map((m) => (
                        <TableRow key={`${m.provider}-${m.model_name}`}>
                          <TableCell className="font-mono text-xs max-w-[240px] truncate" title={m.model_name}>
                            {m.model_name}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-xs">{m.provider}</Badge>
                          </TableCell>
                          <TableCell className="text-right">{m.llm_calls.toLocaleString()}</TableCell>
                          <TableCell className="text-right">{m.runs.toLocaleString()}</TableCell>
                          <TableCell className="text-right">{m.total_tokens.toLocaleString()}</TableCell>
                          <TableCell className="text-right">
                            {(m.avg_response_time_ms / 1000).toFixed(2)}s
                          </TableCell>
                          <TableCell className="text-right">${m.total_cost_usd.toFixed(4)}</TableCell>
                          <TableCell className="text-right">${m.cost_per_1k_tokens.toFixed(5)}</TableCell>
                          <TableCell className="text-right">
                            <span className={m.success_rate >= 90 ? "text-emerald-600 dark:text-emerald-400"
                              : m.success_rate >= 70 ? "text-amber-600 dark:text-amber-400"
                              : "text-red-600 dark:text-red-400"}>
                              {m.success_rate}%
                            </span>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>

                {/* Head-to-head */}
                {modelStats.length > 1 && (
                  <div className="mt-4 pt-4 border-t">
                    <div className="flex flex-wrap items-end gap-3">
                      <div className="w-56">
                        <label className="text-xs text-muted-foreground mb-1 block">Model A</label>
                        <Select value={modelA} onValueChange={setModelA}>
                          <SelectTrigger><SelectValue placeholder="Select model" /></SelectTrigger>
                          <SelectContent>
                            {modelStats.map((m) => (
                              <SelectItem key={m.model_name} value={m.model_name}>{m.model_name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="w-56">
                        <label className="text-xs text-muted-foreground mb-1 block">Model B</label>
                        <Select value={modelB} onValueChange={setModelB}>
                          <SelectTrigger><SelectValue placeholder="Select model" /></SelectTrigger>
                          <SelectContent>
                            {modelStats.map((m) => (
                              <SelectItem key={m.model_name} value={m.model_name}>{m.model_name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <Button onClick={runModelCompare} disabled={modelComparing}>
                        {modelComparing
                          ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          : <GitCompare className="h-4 w-4 mr-2" />}
                        Compare models
                      </Button>
                    </div>

                    {modelCompareResult && !modelCompareResult.error && (
                      <div className="mt-4">
                        <p className="text-sm mb-2">
                          Verdict:{" "}
                          <strong className="text-primary font-mono">{modelCompareResult.verdict}</strong>
                          <span className="text-muted-foreground">
                            {" "}wins {modelCompareResult.wins?.[modelCompareResult.verdict] ?? 0} of{" "}
                            {modelCompareResult.comparison?.length ?? 0} metrics
                            {" "}(last {modelCompareResult.days} days)
                          </span>
                        </p>
                        <div className="overflow-x-auto">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>Metric</TableHead>
                                <TableHead className="text-right font-mono text-xs">{modelA}</TableHead>
                                <TableHead className="text-right font-mono text-xs">{modelB}</TableHead>
                                <TableHead>Winner</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                              {modelCompareResult.comparison?.map((c: any) => (
                                <TableRow key={c.metric}>
                                  <TableCell className="text-sm">
                                    {c.metric.replace(/_/g, " ")}
                                    <span className="text-muted-foreground text-xs ml-1">
                                      ({c.lower_is_better ? "lower better" : "higher better"})
                                    </span>
                                  </TableCell>
                                  <TableCell className="text-right">{Number(c[modelA]).toLocaleString()}</TableCell>
                                  <TableCell className="text-right">{Number(c[modelB]).toLocaleString()}</TableCell>
                                  <TableCell>
                                    <Badge
                                      variant="outline"
                                      className={c.winner === "tie" ? "" : "border-emerald-500 text-emerald-700 dark:text-emerald-400"}
                                    >
                                      {c.winner === "tie" ? "tie" : c.winner}
                                    </Badge>
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

        {/* Trigger */}
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-lg">Run a benchmark</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-end gap-4">
            <div className="w-56">
              <label className="text-xs text-muted-foreground mb-1 block">Suite</label>
              <Select value={selectedSuite} onValueChange={setSelectedSuite}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a suite" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All agents</SelectItem>
                  {suites.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s.charAt(0).toUpperCase() + s.slice(1)} agent
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={startRun} disabled={starting || !selectedSuite}>
              {starting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Play className="h-4 w-4 mr-2" />}
              Run benchmark
            </Button>
            <Button variant="outline" onClick={fetchRuns}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <Button variant="outline" onClick={cleanupStale} title="Flag runs stuck for >30 min as failed">
              <AlertTriangle className="h-4 w-4 mr-2" />
              Clean up stuck
            </Button>
            <p className="text-xs text-muted-foreground basis-full">
              Runs the live search / solution / chat workflows using the backend's configured
              models shown above — to benchmark a different model, restart the backend with a
              different LLM_PROVIDER / model env and run again, then compare them in the
              leaderboard. Live per-test metrics stream to the backend terminal; the PDF report
              downloads automatically when each run completes, and Download fetches it anytime.
            </p>
          </CardContent>
        </Card>

        {/* Runs */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-lg">Recent runs</CardTitle>
            <Select value={sourceFilter} onValueChange={(v) => setSourceFilter(v as "all" | "suite" | "live")}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All sources</SelectItem>
                <SelectItem value="suite">Suite runs</SelectItem>
                <SelectItem value="live">Live runs</SelectItem>
              </SelectContent>
            </Select>
          </CardHeader>
          <CardContent>
            {runs.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">
                No runs yet. Start one above.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Suite</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Tests</TableHead>
                    <TableHead>Tokens</TableHead>
                    <TableHead>Cost</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((r) => (
                    <TableRow key={r.run_id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span className="font-medium capitalize">{r.agent_type}</span>
                          {r.source === "live" && (
                            <Badge className="bg-purple-100 text-purple-700">live</Badge>
                          )}
                          {r.is_baseline && (
                            <Badge className="bg-yellow-100 text-yellow-800">baseline</Badge>
                          )}
                        </div>
                        {r.source === "live" && r.input && (
                          <p className="text-xs text-muted-foreground max-w-xs truncate" title={r.input}>
                            {r.input}
                          </p>
                        )}
                      </TableCell>
                      <TableCell>{statusBadge(r.status)}</TableCell>
                      <TableCell>
                        {r.status === "running"
                          ? `${r.passed + r.failed}/${r.total_tests}`
                          : `${r.passed} pass / ${r.failed} fail`}
                      </TableCell>
                      <TableCell>{fmtNum(r.summary?.total_tokens)}</TableCell>
                      <TableCell>{fmtCost(r.summary?.total_cost_usd)}</TableCell>
                      <TableCell className="text-xs">{fmtDate(r.started_at)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            title="Download PDF report"
                            disabled={r.status !== "completed" || downloadingId === r.run_id}
                            onClick={() => downloadReport(r.run_id)}
                          >
                            {downloadingId === r.run_id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Download className="h-4 w-4" />
                            )}
                          </Button>
                          {r.status === "completed" && (
                            <Button
                              size="sm"
                              variant="outline"
                              title={r.is_baseline ? "Clear baseline" : "Set as baseline"}
                              disabled={busyId === r.run_id}
                              onClick={() => toggleBaseline(r)}
                            >
                              <Star className={`h-4 w-4 ${r.is_baseline ? "fill-yellow-400 text-yellow-500" : ""}`} />
                            </Button>
                          )}
                          {r.status === "running" && (
                            <Button
                              size="sm"
                              variant="outline"
                              title="Cancel run"
                              disabled={busyId === r.run_id}
                              onClick={() => cancelRun(r.run_id)}
                            >
                              {busyId === r.run_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            title="Delete run"
                            disabled={busyId === r.run_id}
                            onClick={() => deleteRun(r.run_id)}
                          >
                            <Trash2 className="h-4 w-4 text-red-600" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Compare */}
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <GitCompare className="h-5 w-5" /> Compare runs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-end gap-3 mb-4">
              <div className="w-64">
                <label className="text-xs text-muted-foreground mb-1 block">New run</label>
                <Select value={compareNew} onValueChange={setCompareNew}>
                  <SelectTrigger><SelectValue placeholder="Select run" /></SelectTrigger>
                  <SelectContent>
                    {runs.filter((r) => r.status === "completed").map((r) => (
                      <SelectItem key={r.run_id} value={r.run_id}>
                        {r.agent_type} · {r.run_id.slice(-15)}{r.is_baseline ? " ★" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-64">
                <label className="text-xs text-muted-foreground mb-1 block">Baseline run</label>
                <Select value={compareBaseline} onValueChange={setCompareBaseline}>
                  <SelectTrigger><SelectValue placeholder="Select baseline" /></SelectTrigger>
                  <SelectContent>
                    {runs.filter((r) => r.status === "completed").map((r) => (
                      <SelectItem key={r.run_id} value={r.run_id}>
                        {r.agent_type} · {r.run_id.slice(-15)}{r.is_baseline ? " ★" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={runCompare} disabled={comparing}>
                {comparing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <GitCompare className="h-4 w-4 mr-2" />}
                Compare
              </Button>
            </div>

            {compareResult && (
              <div>
                <div className="mb-3">
                  {compareResult.has_regressions ? (
                    <Badge className="bg-red-100 text-red-700">
                      {compareResult.regressions.length} regression(s)
                    </Badge>
                  ) : (
                    <Badge className="bg-green-100 text-green-700">No regressions</Badge>
                  )}
                  {compareResult.improvements?.length > 0 && (
                    <Badge className="bg-green-100 text-green-700 ml-2">
                      {compareResult.improvements.length} improvement(s)
                    </Badge>
                  )}
                </div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Metric</TableHead>
                      <TableHead>New</TableHead>
                      <TableHead>Baseline</TableHead>
                      <TableHead>Change</TableHead>
                      <TableHead>Verdict</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    {compareResult.metrics?.map((m: any) => (
                      <TableRow key={m.metric}>
                        <TableCell>{m.metric}</TableCell>
                        <TableCell>{m.new}</TableCell>
                        <TableCell>{m.baseline}</TableCell>
                        <TableCell className={m.verdict === "regression" ? "text-red-600" : m.verdict === "improvement" ? "text-green-600" : ""}>
                          {m.change_pct > 0 ? "+" : ""}{m.change_pct}%
                        </TableCell>
                        <TableCell>
                          <Badge className={
                            m.verdict === "regression" ? "bg-red-100 text-red-700"
                              : m.verdict === "improvement" ? "bg-green-100 text-green-700"
                              : "bg-slate-100 text-slate-600"
                          }>{m.verdict}</Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {compareResult.test_flips?.length > 0 && (
                  <p className="text-sm mt-3 text-muted-foreground">
                    Test status changes:{" "}
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    {compareResult.test_flips.map((f: any) => `${f.test_id} (${f.from}→${f.to})`).join(", ")}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ── Client-side PDF generation (jsPDF) ─────────────────────────────────── */
async function generatePdf(report: { run: BenchmarkRun; results: any[] }) {
  const { default: jsPDF } = await import("jspdf");
  const doc = new jsPDF();
  const { run, results } = report;
  const left = 14;
  let y = 18;

  const line = (text: string, size = 10, bold = false) => {
    doc.setFontSize(size);
    doc.setFont("helvetica", bold ? "bold" : "normal");
    if (y > 280) {
      doc.addPage();
      y = 18;
    }
    doc.text(text, left, y);
    y += size * 0.55 + 2;
  };

  line("Benchmark Report", 16, true);
  line(`Run: ${run.run_id}`);
  line(`Suite: ${run.suite_name} (${run.agent_type} agent)`);
  line(`Status: ${run.status}    Started: ${run.started_at ? new Date(run.started_at).toLocaleString() : "-"}`);
  const provider = (run.environment?.provider as string) || "-";
  line(`Provider: ${provider}    Duration: ${(run.duration_ms / 1000).toFixed(1)}s`);
  y += 2;

  const s = run.summary || {};
  line("Summary", 13, true);
  line(`Tests: ${run.total_tests}    Passed: ${run.passed}    Failed: ${run.failed}`);
  line(`LLM calls: ${s.total_llm_calls ?? 0}    Tokens: ${(s.total_tokens ?? 0).toLocaleString()}`);
  line(`Total cost: $${(s.total_cost_usd ?? 0).toFixed(6)}    Avg resp: ${(s.avg_response_time_ms ?? 0).toFixed(0)}ms`);
  y += 2;

  line("Per-test results", 13, true);
  doc.setFontSize(9);
  doc.setFont("helvetica", "bold");
  line("Test                Status    ms      calls   tokens     cost", 9, true);
  results.forEach((r) => {
    const m = r.llm_metrics || {};
    const row =
      `${(r.test_id || "").padEnd(18).slice(0, 18)} ` +
      `${(r.status || "").padEnd(8).slice(0, 8)} ` +
      `${String(Math.round(r.execution_time_ms || 0)).padStart(6)} ` +
      `${String(m.total_llm_calls ?? 0).padStart(6)} ` +
      `${String(m.total_tokens ?? 0).padStart(9)} ` +
      `$${(m.total_cost_usd ?? 0).toFixed(6)}`;
    line(row, 9);
  });

  doc.save(`benchmark_report_${run.run_id}.pdf`);
}
