import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import {
  ShieldAlert,
  AlertOctagon,
  AlertTriangle,
  Info,
  CheckCircle2,
  RefreshCw,
  ExternalLink,
  Search,
  Filter,
  EyeOff,
  Check,
  RotateCcw,
} from 'lucide-react';
import { buildContext, runValidation, validationScore } from '../../features/validation/engine';
import { RULES } from '../../features/validation/rules';
import { loadStatuses, saveStatuses, type StatusMap } from '../../features/validation/status';
import type { ValidationIssue, Severity, IssueStatus } from '../../features/validation/types';
import { requestCanvasFocus } from '../../features/canvas/focusBus';
import { isInstrument } from '../../domain/isa/instrument';

export default function PIDValidationPage() {
  const navigate = useNavigate();

  const [graphData, setGraphData] = useState<any>(() => {
    try {
      const stored = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
      return stored ? JSON.parse(stored) : { nodes: [], edges: [] };
    } catch {
      return { nodes: [], edges: [] };
    }
  });

  const sessionId = graphData.sessionId || 'default';
  const [statuses, setStatuses] = useState<StatusMap>(() => loadStatuses(sessionId));

  const [searchQuery, setSearchQuery] = useState('');
  const [sevFilter, setSevFilter] = useState<'all' | Severity>('all');
  const [ruleFilter, setRuleFilter] = useState<'all' | string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | IssueStatus>('all');
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Compute validation issues from current graph
  const { issues, ctx } = useMemo(() => {
    const rawNodes = graphData.nodes || [];
    const rawEdges = graphData.edges || [];

    const nodes = rawNodes.map((n: any) => ({
      id: n.id,
      label: n.label || n.id,
      kind: n.kind || 'instrument',
      x: n.x ?? 0,
      y: n.y ?? 0,
      drawing: n.drawing || 'DRAW-001',
      category: isInstrument(n.kind || '') ? 'instrument' : 'equipment',
      equipment_ref: n.equipment_ref || '',
    }));

    const edges = rawEdges.map((e: any) => ({
      source: e.source || e.from || '',
      target: e.target || e.to || '',
      kind: e.kind || 'stream',
    }));

    const instruments = nodes.filter((n: any) => isInstrument(n.kind)).map((n: any) => ({
      tag: n.label,
      type: n.kind,
      confidence: n.confidence ?? 0.9,
      equipment_ref: n.equipment_ref,
      drawing: n.drawing,
    }));

    const equipment = nodes.filter((n: any) => !isInstrument(n.kind)).map((n: any) => ({
      tag: n.label,
      type: n.kind,
      confidence: n.confidence ?? 0.95,
      drawing: n.drawing,
    }));

    const validationCtx = buildContext(nodes, edges, instruments, equipment);
    const issueList = runValidation(validationCtx);

    return { issues: issueList, ctx: validationCtx };
  }, [graphData]);

  const statusOf = useCallback((id: string): IssueStatus => statuses[id] ?? 'open', [statuses]);

  const updateIssueStatus = (id: string, next: IssueStatus) => {
    setStatuses(prev => {
      const updated = { ...prev, [id]: next };
      saveStatuses(sessionId, updated);
      return updated;
    });
  };

  const openIssues = useMemo(() => issues.filter(i => statusOf(i.id) === 'open'), [issues, statusOf]);
  const score = useMemo(() => validationScore(openIssues, ctx), [openIssues, ctx]);

  // Counts by severity
  const counts = useMemo(() => {
    const c = { critical: 0, warning: 0, info: 0, resolved: 0, ignored: 0 };
    for (const i of issues) {
      const st = statusOf(i.id);
      if (st === 'resolved') {
        c.resolved++;
        continue;
      }
      if (st === 'ignored') {
        c.ignored++;
        continue;
      }
      c[i.severity]++;
    }
    return c;
  }, [issues, statusOf]);

  // Filtered issues
  const filteredIssues = useMemo(() => {
    return issues.filter(i => {
      const st = statusOf(i.id);
      if (statusFilter !== 'all' && st !== statusFilter) return false;
      if (sevFilter !== 'all' && i.severity !== sevFilter) return false;
      if (ruleFilter !== 'all' && i.ruleId !== ruleFilter) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const t = (i.title || '').toLowerCase();
        const d = (i.description || '').toLowerCase();
        const tag = (i.tag || '').toLowerCase();
        if (!t.includes(q) && !d.includes(q) && !tag.includes(q)) return false;
      }

      return true;
    });
  }, [issues, statusOf, statusFilter, sevFilter, ruleFilter, searchQuery]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    try {
      const stored = localStorage.getItem('active_pid_graph');
      if (stored) setGraphData(JSON.parse(stored));
    } catch {}
    setTimeout(() => setIsRefreshing(false), 500);
  };

  const jumpToCanvas = (tag?: string) => {
    if (!tag) return;
    requestCanvasFocus(tag);
    navigate('/pid-studio/canvas');
  };

  return (
    <PIDStudioLayout>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-xl font-bold text-foreground">P&ID Engineering Rules & Validation Audit</h1>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Automated compliance checks across ISA-5.1 standards, line continuity, isolated equipment, and tag consistency.
            </p>
          </div>

          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-border bg-card hover:bg-accent text-foreground text-xs font-semibold shadow-xs transition-colors self-start sm:self-auto"
          >
            <RefreshCw size={13} className={isRefreshing ? 'animate-spin' : ''} />
            <span>Re-run Audit</span>
          </button>
        </div>

        {/* Health Score & Stats Row */}
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-3">
          {/* Health Score Card */}
          <div className="p-4 rounded-2xl bg-card border border-border shadow-xs sm:col-span-2 flex items-center gap-4">
            <div className="relative w-16 h-16 flex items-center justify-center shrink-0">
              <svg className="w-16 h-16 transform -rotate-90" viewBox="0 0 36 36">
                <path
                  className="text-border"
                  strokeWidth="3.5"
                  stroke="currentColor"
                  fill="none"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <path
                  className={score >= 80 ? 'text-emerald-500' : score >= 50 ? 'text-amber-500' : 'text-red-500'}
                  strokeDasharray={`${score}, 100`}
                  strokeWidth="3.5"
                  strokeLinecap="round"
                  stroke="currentColor"
                  fill="none"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              </svg>
              <span className="absolute font-bold text-sm text-foreground">{score}%</span>
            </div>

            <div className="space-y-0.5">
              <div className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">Health Score</div>
              <div className="text-sm font-semibold text-foreground">
                {score >= 90 ? 'Clean Diagram' : score >= 70 ? 'Minor Gaps Identified' : 'Action Required'}
              </div>
              <p className="text-[10px] text-muted-foreground">
                {openIssues.length} active issue{openIssues.length !== 1 ? 's' : ''} detected across {ctx.nodes.length} components
              </p>
            </div>
          </div>

          {/* Counts */}
          <div className="p-3.5 rounded-xl bg-card border border-border shadow-2xs space-y-1">
            <div className="flex items-center gap-1.5 text-red-500 text-[11px] font-semibold">
              <AlertOctagon size={13} /> Critical
            </div>
            <div className="text-2xl font-bold text-foreground">{counts.critical}</div>
            <div className="text-[10px] text-muted-foreground">Duplicate tags, orphan lines</div>
          </div>

          <div className="p-3.5 rounded-xl bg-card border border-border shadow-2xs space-y-1">
            <div className="flex items-center gap-1.5 text-amber-500 text-[11px] font-semibold">
              <AlertTriangle size={13} /> Warnings
            </div>
            <div className="text-2xl font-bold text-foreground">{counts.warning}</div>
            <div className="text-[10px] text-muted-foreground">Isolated nodes, missing tags</div>
          </div>

          <div className="p-3.5 rounded-xl bg-card border border-border shadow-2xs space-y-1">
            <div className="flex items-center gap-1.5 text-emerald-500 text-[11px] font-semibold">
              <CheckCircle2 size={13} /> Resolved
            </div>
            <div className="text-2xl font-bold text-foreground">{counts.resolved}</div>
            <div className="text-[10px] text-muted-foreground">Approved or fixed</div>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="p-3.5 rounded-xl bg-card border border-border shadow-xs flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-background flex-1 min-w-[200px]">
            <Search size={13} className="text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search rule or component tag..."
              className="w-full bg-transparent border-none text-xs text-foreground outline-none"
            />
          </div>

          <select
            value={sevFilter}
            onChange={e => setSevFilter(e.target.value as any)}
            className="px-3 py-1.5 rounded-xl border border-border bg-background text-foreground text-xs outline-none"
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>

          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as any)}
            className="px-3 py-1.5 rounded-xl border border-border bg-background text-foreground text-xs outline-none"
          >
            <option value="all">All Statuses</option>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
            <option value="ignored">Ignored</option>
          </select>

          <select
            value={ruleFilter}
            onChange={e => setRuleFilter(e.target.value as any)}
            className="px-3 py-1.5 rounded-xl border border-border bg-background text-foreground text-xs outline-none max-w-[180px] truncate"
          >
            <option value="all">All Rules</option>
            {RULES.map(r => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        </div>

        {/* Issues List */}
        <div className="space-y-2.5">
          {filteredIssues.length === 0 ? (
            <div className="p-12 text-center rounded-2xl bg-card border border-border text-muted-foreground space-y-2">
              <CheckCircle2 size={32} className="mx-auto text-emerald-500/60" />
              <div className="font-semibold text-sm text-foreground">No issues found</div>
              <p className="text-xs">Your diagram passed all selected engineering compliance criteria.</p>
            </div>
          ) : (
            filteredIssues.map(issue => {
              const currentStatus = statusOf(issue.id);
              const isResolved = currentStatus === 'resolved';
              const isIgnored = currentStatus === 'ignored';

              return (
                <div
                  key={issue.id}
                  className={`p-4 rounded-2xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                    isResolved
                      ? 'bg-muted/30 border-border opacity-60'
                      : isIgnored
                      ? 'bg-muted/20 border-border/60 opacity-50'
                      : issue.severity === 'critical'
                      ? 'bg-red-500/5 border-red-500/30 shadow-2xs'
                      : issue.severity === 'warning'
                      ? 'bg-amber-500/5 border-amber-500/30 shadow-2xs'
                      : 'bg-card border-border shadow-2xs'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 shrink-0">
                      {issue.severity === 'critical' && <AlertOctagon size={16} className="text-red-500" />}
                      {issue.severity === 'warning' && <AlertTriangle size={16} className="text-amber-500" />}
                      {issue.severity === 'info' && <Info size={16} className="text-blue-500" />}
                    </div>

                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-xs text-foreground">{issue.title}</span>
                        {issue.tag && (
                          <span
                            onClick={() => jumpToCanvas(issue.tag)}
                            className="px-2 py-0.2 rounded-full font-mono font-bold text-[10px] bg-primary/10 text-primary border border-primary/20 hover:underline cursor-pointer"
                            title="Click to focus on canvas"
                          >
                            {issue.tag}
                          </span>
                        )}
                        <span className="text-[10px] uppercase font-mono text-muted-foreground px-1.5 py-0.2 rounded bg-muted">
                          {issue.ruleId}
                        </span>
                      </div>

                      <p className="text-xs text-muted-foreground leading-relaxed">{issue.description}</p>
                      {issue.suggestion && (
                        <p className="text-[11px] text-primary/90 font-medium">Suggestion: {issue.suggestion}</p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
                    {issue.tag && (
                      <button
                        type="button"
                        onClick={() => jumpToCanvas(issue.tag)}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-border bg-background hover:bg-accent text-xs text-foreground"
                        title="Focus on canvas"
                      >
                        <ExternalLink size={12} />
                        <span>Locate</span>
                      </button>
                    )}

                    {!isResolved && (
                      <button
                        type="button"
                        onClick={() => updateIssueStatus(issue.id, 'resolved')}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600/10 hover:bg-emerald-600 text-emerald-500 hover:text-white border border-emerald-500/20 text-xs font-medium transition-colors"
                        title="Mark as resolved"
                      >
                        <Check size={12} />
                        <span>Resolve</span>
                      </button>
                    )}

                    {!isIgnored && (
                      <button
                        type="button"
                        onClick={() => updateIssueStatus(issue.id, 'ignored')}
                        className="p-1.5 rounded-lg border border-border bg-background hover:bg-accent text-muted-foreground hover:text-foreground text-xs"
                        title="Ignore issue"
                      >
                        <EyeOff size={12} />
                      </button>
                    )}

                    {(isResolved || isIgnored) && (
                      <button
                        type="button"
                        onClick={() => updateIssueStatus(issue.id, 'open')}
                        className="p-1.5 rounded-lg border border-border bg-background hover:bg-accent text-muted-foreground hover:text-foreground text-xs"
                        title="Reopen issue"
                      >
                        <RotateCcw size={12} />
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </PIDStudioLayout>
  );
}
