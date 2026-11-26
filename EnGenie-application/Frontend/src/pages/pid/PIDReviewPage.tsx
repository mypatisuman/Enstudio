import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import {
  CheckSquare,
  Search,
  Filter,
  Check,
  X,
  ExternalLink,
  ShieldCheck,
  Building2,
  Cpu,
  Layers,
  Sparkles,
  ArrowRight,
  Edit2,
  Trash2,
  Wrench,
  Loader2,
} from 'lucide-react';
import { confidenceInfo, confidenceBucket, nodeConfidence } from '../../features/review/confidence';
import { requestCanvasFocus } from '../../features/canvas/focusBus';
import { emitGraphChanged } from '../../features/canvas/graphEvents';
import { isInstrument } from '../../domain/isa/instrument';
import { identifyPIDAccessories, type IdentifiedAccessory } from '../../services/pidDescribeService';
import { DigitiseReviewPanel } from '../../features/review/DigitiseReviewPanel';

export default function PIDReviewPage() {
  const navigate = useNavigate();

  const [graphData, setGraphData] = useState<any>(() => {
    try {
      const stored = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
      return stored ? JSON.parse(stored) : { nodes: [], edges: [] };
    } catch {
      return { nodes: [], edges: [] };
    }
  });

  const [activeTab, setActiveTab] = useState<'all' | 'instruments' | 'equipment' | 'accessories' | 'digitise'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'accepted' | 'rejected'>('all');
  const [confFilter, setConfFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [loadingAccessories, setLoadingAccessories] = useState(false);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<{ tag: string; area: string; ref: string; desc: string }>({
    tag: '',
    area: '',
    ref: '',
    desc: '',
  });

  const nodes = graphData.nodes || [];

  // Filtered nodes
  const filteredNodes = useMemo(() => {
    return nodes.filter((n: any) => {
      const isInstr = isInstrument(n.kind || '');
      if (activeTab === 'instruments' && !isInstr) return false;
      if (activeTab === 'equipment' && isInstr) return false;

      const status = n.review_status || 'pending';
      if (statusFilter !== 'all' && status !== statusFilter) return false;

      const conf = nodeConfidence(n, 0.88);
      if (confFilter !== 'all' && confidenceBucket(conf) !== confFilter) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const tag = String(n.label || n.id).toLowerCase();
        const kind = String(n.kind || '').toLowerCase();
        const area = String(n.area || '').toLowerCase();
        const ref = String(n.equipment_ref || '').toLowerCase();
        if (!tag.includes(q) && !kind.includes(q) && !area.includes(q) && !ref.includes(q)) {
          return false;
        }
      }

      return true;
    });
  }, [nodes, activeTab, statusFilter, confFilter, searchQuery]);

  const acceptedCount = nodes.filter((n: any) => n.review_status === 'accepted').length;
  const rejectedCount = nodes.filter((n: any) => n.review_status === 'rejected').length;
  const pendingCount = nodes.length - acceptedCount - rejectedCount;

  // Extract all accessories from nodes
  const allAccessories = useMemo(() => {
    const list: any[] = [];
    nodes.forEach((n: any) => {
      const accs = n.accessories || n.extra_json?.accessories || [];
      const parentTag = n.label || n.tag || n.id;
      accs.forEach((a: any) => {
        list.push({ ...a, parent_tag: a.parent_tag || a.instrument_tag || parentTag });
      });
    });
    return list;
  }, [nodes]);

  const filteredAccessories = useMemo(() => {
    if (!searchQuery.trim()) return allAccessories;
    const q = searchQuery.toLowerCase();
    return allAccessories.filter((a: any) => {
      const name = String(a.name || a.accessory_name || '').toLowerCase();
      const parent = String(a.parent_tag || a.instrument_tag || '').toLowerCase();
      const cat = String(a.category || '').toLowerCase();
      const spec = String(a.specification || a.standard || '').toLowerCase();
      return name.includes(q) || parent.includes(q) || cat.includes(q) || spec.includes(q);
    });
  }, [allAccessories, searchQuery]);

  const handleRunAccessoryInference = async () => {
    const sessionId = localStorage.getItem('active_pid_session_id') || sessionStorage.getItem('active_pid_session_id') || 'default';
    setLoadingAccessories(true);
    try {
      const res = await identifyPIDAccessories(sessionId);
      if (res.success && res.pid_graph) {
        setGraphData(res.pid_graph);
        localStorage.setItem('active_pid_graph', JSON.stringify(res.pid_graph));
        sessionStorage.setItem('active_pid_graph', JSON.stringify(res.pid_graph));
        emitGraphChanged(sessionId);
        setActiveTab('accessories');
      } else {
        alert(res.error || 'Failed to infer accessories from Solution Agent.');
      }
    } catch (e: any) {
      alert(`Error running Solution Agent: ${e.message}`);
    } finally {
      setLoadingAccessories(false);
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredNodes.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredNodes.map((n: any) => n.id)));
    }
  };

  const updateNodeStatus = (ids: string[], newStatus: 'accepted' | 'rejected' | 'pending') => {
    const idSet = new Set(ids);
    const updatedNodes = nodes.map((n: any) =>
      idSet.has(n.id) ? { ...n, review_status: newStatus } : n
    );
    const newGraph = { ...graphData, nodes: updatedNodes };
    setGraphData(newGraph);
    localStorage.setItem('active_pid_graph', JSON.stringify(newGraph));
    sessionStorage.setItem('active_pid_graph', JSON.stringify(newGraph));
    setSelectedIds(new Set());
    emitGraphChanged('default');
  };

  const jumpToCanvas = (tag: string) => {
    requestCanvasFocus(tag);
    navigate('/pid-studio/canvas');
  };

  const startEdit = (node: any) => {
    setEditingId(node.id);
    setEditValues({
      tag: node.label || node.id,
      area: node.area || '',
      ref: node.equipment_ref || '',
      desc: node.description || '',
    });
  };

  const saveEdit = (id: string) => {
    const updatedNodes = nodes.map((n: any) =>
      n.id === id
        ? {
            ...n,
            label: editValues.tag.trim() || n.label,
            area: editValues.area.trim(),
            equipment_ref: editValues.ref.trim(),
            description: editValues.desc.trim(),
          }
        : n
    );
    const newGraph = { ...graphData, nodes: updatedNodes };
    setGraphData(newGraph);
    localStorage.setItem('active_pid_graph', JSON.stringify(newGraph));
    sessionStorage.setItem('active_pid_graph', JSON.stringify(newGraph));
    setEditingId(null);
    emitGraphChanged('default');
  };

  return (
    <PIDStudioLayout>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-xl font-bold text-foreground">Extracted Components Review Table</h1>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Verify and approve parsed instruments, equipment, and piping connections. Confirm tags, edit parent equipment references, and inspect confidence metrics.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleRunAccessoryInference}
              disabled={loadingAccessories}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/40 text-amber-300 font-semibold text-xs shadow-xs transition-colors"
              title="Run Solution Agent workflow to identify mandatory and optional accessories"
            >
              {loadingAccessories ? (
                <>
                  <Loader2 size={13} className="animate-spin" />
                  Inferring Accessories...
                </>
              ) : (
                <>
                  <Sparkles size={13} className="text-amber-400" />
                  Identify Accessories (Solution Agent)
                </>
              )}
            </button>

            <div className="flex items-center gap-2 p-2 rounded-xl bg-card border border-border text-xs">
              <span className="text-emerald-500 font-semibold">{acceptedCount} Accepted</span>
              <span className="text-border">&bull;</span>
              <span className="text-amber-500 font-semibold">{pendingCount} Pending</span>
              <span className="text-border">&bull;</span>
              <span className="text-red-500 font-semibold">{rejectedCount} Rejected</span>
            </div>
          </div>
        </div>

        {/* Filter and Action Bar */}
        <div className="p-4 rounded-2xl bg-card border border-border shadow-xs space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Category tabs */}
            <div className="flex items-center rounded-xl bg-background border border-border p-0.5 text-xs">
              {[
                { id: 'all', label: `All Items (${nodes.length})` },
                { id: 'instruments', label: `Instruments (${nodes.filter((n: any) => isInstrument(n.kind || '')).length})` },
                { id: 'equipment', label: `Equipment (${nodes.filter((n: any) => !isInstrument(n.kind || '')).length})` },
                { id: 'accessories', label: `Accessories (${allAccessories.length})` },
                { id: 'digitise', label: 'Digitisation check' },
              ].map(t => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setActiveTab(t.id as any)}
                  className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                    activeTab === t.id
                      ? 'bg-primary text-primary-foreground font-semibold shadow-xs'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Bulk actions */}
            {selectedIds.size > 0 && (
              <div className="flex items-center gap-2 animate-in fade-in duration-150">
                <span className="text-xs font-semibold text-primary">{selectedIds.size} Selected:</span>
                <button
                  type="button"
                  onClick={() => updateNodeStatus(Array.from(selectedIds), 'accepted')}
                  className="flex items-center gap-1 px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs shadow-xs"
                >
                  <Check size={12} /> Accept Selected
                </button>
                <button
                  type="button"
                  onClick={() => updateNodeStatus(Array.from(selectedIds), 'rejected')}
                  className="flex items-center gap-1 px-3 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold text-xs shadow-xs"
                >
                  <X size={12} /> Reject Selected
                </button>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-border/50 text-xs">
            {/* Search */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border bg-background flex-1 min-w-[200px]">
              <Search size={13} className="text-muted-foreground" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search tag, equipment, or area..."
                className="w-full bg-transparent border-none text-xs text-foreground outline-none"
              />
            </div>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value as any)}
              className="px-3 py-1.5 rounded-xl border border-border bg-background text-foreground text-xs outline-none"
            >
              <option value="all">All Statuses</option>
              <option value="pending">Pending Review</option>
              <option value="accepted">Accepted</option>
              <option value="rejected">Rejected</option>
            </select>

            {/* Confidence Filter */}
            <select
              value={confFilter}
              onChange={e => setConfFilter(e.target.value as any)}
              className="px-3 py-1.5 rounded-xl border border-border bg-background text-foreground text-xs outline-none"
            >
              <option value="all">All Confidence</option>
              <option value="high">High (&gt;85%)</option>
              <option value="medium">Medium (70-84%)</option>
              <option value="low">Low (&lt;70%)</option>
            </select>
          </div>
        </div>

        {/* Data Table */}
        <div className="rounded-2xl border border-border bg-card shadow-xs overflow-hidden">
          <div className="overflow-x-auto">
            {activeTab === 'digitise' ? (
              <DigitiseReviewPanel
                sessionId={localStorage.getItem('active_pid_session_id') || sessionStorage.getItem('active_pid_session_id') || 'default'}
                onGraphChanged={g => {
                  setGraphData(g);
                  try {
                    localStorage.setItem('active_pid_graph', JSON.stringify(g));
                    sessionStorage.setItem('active_pid_graph', JSON.stringify(g));
                  } catch {
                    /* storage full or blocked: the canvas reloads from the server */
                  }
                  emitGraphChanged(localStorage.getItem('active_pid_session_id') || 'default');
                }}
              />
            ) : activeTab === 'accessories' ? (
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/50 border-b border-border text-muted-foreground uppercase text-[10px] tracking-wider">
                  <tr>
                    <th className="p-3 font-semibold">Accessory Name</th>
                    <th className="p-3 font-semibold">Parent Instrument</th>
                    <th className="p-3 font-semibold">Category</th>
                    <th className="p-3 font-semibold">Requirement</th>
                    <th className="p-3 font-semibold">Specification / Standard</th>
                    <th className="p-3 font-semibold text-center">Qty</th>
                    <th className="p-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50 text-foreground">
                  {filteredAccessories.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="p-10 text-center text-muted-foreground">
                        <div className="flex flex-col items-center justify-center gap-2">
                          <Wrench className="w-8 h-8 text-muted-foreground/40 mb-1" />
                          <p className="font-semibold text-sm text-foreground">No accessories found</p>
                          <p className="text-xs text-muted-foreground max-w-md">
                            Run the Solution Agent accessory inference to automatically deduce manifolds, thermowells, positioners, and sunshades for all active P&amp;ID instruments.
                          </p>
                          <button
                            type="button"
                            onClick={handleRunAccessoryInference}
                            disabled={loadingAccessories}
                            className="mt-3 flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/40 text-amber-300 font-semibold text-xs transition-colors"
                          >
                            {loadingAccessories ? (
                              <>
                                <Loader2 size={13} className="animate-spin" />
                                Inferring Accessories...
                              </>
                            ) : (
                              <>
                                <Sparkles size={13} className="text-amber-400" />
                                Identify Accessories Now
                              </>
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    filteredAccessories.map((acc: any, idx: number) => {
                      const isMandatory = acc.is_mandatory !== false;
                      return (
                        <tr key={`${acc.parent_tag}-${acc.name || acc.accessory_name}-${idx}`} className="hover:bg-accent/40 transition-colors">
                          <td className="p-3">
                            <div className="font-medium text-foreground">{acc.name || acc.accessory_name || 'Accessory'}</div>
                            {acc.reasoning && (
                              <div className="text-[10px] text-muted-foreground line-clamp-1">{acc.reasoning}</div>
                            )}
                          </td>
                          <td className="p-3 font-mono font-bold">
                            <span
                              className="text-primary hover:underline cursor-pointer"
                              onClick={() => jumpToCanvas(acc.parent_tag || '')}
                            >
                              {acc.parent_tag || '—'}
                            </span>
                          </td>
                          <td className="p-3">
                            <span className="px-2 py-0.5 rounded-full bg-muted border border-border text-[10px] uppercase font-mono font-medium">
                              {acc.category || 'General'}
                            </span>
                          </td>
                          <td className="p-3">
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                                isMandatory
                                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                                  : 'bg-muted text-muted-foreground border-border'
                              }`}
                            >
                              {isMandatory ? 'Mandatory' : 'Optional'}
                            </span>
                          </td>
                          <td className="p-3 text-muted-foreground font-mono text-[11px]">
                            {acc.specification || acc.standard || '—'}
                          </td>
                          <td className="p-3 text-center font-mono">
                            {acc.quantity || 1}
                          </td>
                          <td className="p-3 text-right">
                            <button
                              type="button"
                              onClick={() => jumpToCanvas(acc.parent_tag || '')}
                              className="p-1 rounded hover:bg-primary/20 text-muted-foreground hover:text-primary"
                              title="Locate Instrument on Canvas"
                            >
                              <ExternalLink size={13} />
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="bg-muted/50 border-b border-border text-muted-foreground uppercase text-[10px] tracking-wider">
                  <tr>
                    <th className="p-3 w-10 text-center">
                      <input
                        type="checkbox"
                        checked={filteredNodes.length > 0 && selectedIds.size === filteredNodes.length}
                        onChange={toggleSelectAll}
                        className="rounded accent-primary"
                      />
                    </th>
                    <th className="p-3 font-semibold">Component Tag</th>
                    <th className="p-3 font-semibold">Classification</th>
                    <th className="p-3 font-semibold">Parent Equipment</th>
                    <th className="p-3 font-semibold">Sub-System Area</th>
                    <th className="p-3 font-semibold">Confidence</th>
                    <th className="p-3 font-semibold">Review Status</th>
                    <th className="p-3 font-semibold text-right">Actions</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-border/50 text-foreground">
                  {filteredNodes.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="p-8 text-center text-muted-foreground">
                        No components match the current search and filter criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredNodes.map((node: any) => {
                      const isSelected = selectedIds.has(node.id);
                      const isEditing = editingId === node.id;
                      const conf = nodeConfidence(node, 0.92);
                      const cInfo = confidenceInfo(conf);
                      const nodeAccessories = node.accessories || node.extra_json?.accessories || [];

                      return (
                        <tr
                          key={node.id}
                          className={`hover:bg-accent/40 transition-colors ${
                            isSelected ? 'bg-primary/5' : ''
                          }`}
                        >
                          <td className="p-3 text-center">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelect(node.id)}
                              className="rounded accent-primary"
                            />
                          </td>

                          {/* Tag */}
                          <td className="p-3 font-mono font-bold text-foreground">
                            {isEditing ? (
                              <input
                                value={editValues.tag}
                                onChange={e => setEditValues(v => ({ ...v, tag: e.target.value }))}
                                className="px-2 py-0.5 rounded border border-primary bg-background text-xs"
                              />
                            ) : (
                              <div className="flex items-center gap-2">
                                <span className="text-primary hover:underline cursor-pointer" onClick={() => jumpToCanvas(node.label || node.id)}>
                                  {node.label || node.id}
                                </span>
                                {nodeAccessories.length > 0 && (
                                  <span
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setActiveTab('accessories');
                                      setSearchQuery(node.label || node.id);
                                    }}
                                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-[10px] text-amber-400 font-mono cursor-pointer hover:bg-amber-500/25"
                                    title={`${nodeAccessories.length} accessories inferred. Click to filter in Accessories tab.`}
                                  >
                                    <Wrench size={10} />
                                    {nodeAccessories.length}
                                  </span>
                                )}
                              </div>
                            )}
                          </td>

                          {/* Classification */}
                          <td className="p-3">
                            <span className="px-2 py-0.5 rounded-full bg-muted border border-border text-[10px] uppercase font-mono font-medium">
                              {node.kind || 'instrument'}
                            </span>
                          </td>

                          {/* Parent Ref */}
                          <td className="p-3 text-muted-foreground">
                            {isEditing ? (
                              <input
                                value={editValues.ref}
                                onChange={e => setEditValues(v => ({ ...v, ref: e.target.value }))}
                                placeholder="e.g. V-101"
                                className="px-2 py-0.5 rounded border border-border bg-background text-xs w-24"
                              />
                            ) : (
                              node.equipment_ref || '—'
                            )}
                          </td>

                          {/* Area */}
                          <td className="p-3 text-muted-foreground">
                            {isEditing ? (
                              <input
                                value={editValues.area}
                                onChange={e => setEditValues(v => ({ ...v, area: e.target.value }))}
                                placeholder="e.g. Feed Treatment"
                                className="px-2 py-0.5 rounded border border-border bg-background text-xs w-28"
                              />
                            ) : (
                              node.area || 'General Plant'
                            )}
                          </td>

                          {/* Confidence */}
                          <td className="p-3">
                            <span
                              className="px-2 py-0.5 rounded-full text-[10px] font-semibold border"
                              style={{
                                color: cInfo.color,
                                borderColor: `${cInfo.color}40`,
                                backgroundColor: `${cInfo.color}15`,
                              }}
                            >
                              {cInfo.pct}% ({cInfo.label})
                            </span>
                          </td>

                          {/* Review Status */}
                          <td className="p-3">
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider ${
                                node.review_status === 'accepted'
                                  ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/30'
                                  : node.review_status === 'rejected'
                                  ? 'bg-red-500/10 text-red-500 border border-red-500/30'
                                  : 'bg-amber-500/10 text-amber-500 border border-amber-500/30'
                              }`}
                            >
                              {node.review_status || 'Pending'}
                            </span>
                          </td>

                          {/* Actions */}
                          <td className="p-3 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {isEditing ? (
                                <button
                                  type="button"
                                  onClick={() => saveEdit(node.id)}
                                  className="p-1 rounded hover:bg-emerald-500/20 text-emerald-500"
                                  title="Save changes"
                                >
                                  <Check size={14} />
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => startEdit(node)}
                                  className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                                  title="Edit details"
                                >
                                  <Edit2 size={13} />
                                </button>
                              )}

                              <button
                                type="button"
                                onClick={() =>
                                  updateNodeStatus(
                                    [node.id],
                                    node.review_status === 'accepted' ? 'pending' : 'accepted'
                                  )
                                }
                                className={`p-1 rounded transition-colors ${
                                  node.review_status === 'accepted'
                                    ? 'bg-emerald-500/20 text-emerald-500'
                                    : 'hover:bg-emerald-500/10 text-muted-foreground hover:text-emerald-500'
                                }`}
                                title="Accept item"
                              >
                                <Check size={13} />
                              </button>

                              <button
                                type="button"
                                onClick={() => jumpToCanvas(node.label || node.id)}
                                className="p-1 rounded hover:bg-primary/20 text-muted-foreground hover:text-primary"
                                title="Locate on Canvas"
                              >
                                <ExternalLink size={13} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </PIDStudioLayout>
  );
}
