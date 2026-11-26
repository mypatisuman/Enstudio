import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import {
  UploadCloud,
  CheckSquare,
  Network,
  MessageSquareCode,
  ShieldAlert,
  Download,
  Activity,
  Layers,
  Sparkles,
  ArrowRight,
  TrendingUp,
  FileText,
  Cpu,
  CheckCircle2,
  Clock,
  Compass,
} from 'lucide-react';
import { isInstrument } from '../../domain/isa/instrument';

export default function PIDHomeScreen() {
  const navigate = useNavigate();

  const [graphData, setGraphData] = useState<any>(() => {
    try {
      const stored = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const solutionTitle =
    localStorage.getItem('active_solution_title') ||
    sessionStorage.getItem('active_solution_title') ||
    'Engineering Solution P&ID';

  const nodes = graphData?.nodes || [];
  const edges = graphData?.edges || [];

  const instruments = nodes.filter((n: any) => isInstrument(n.kind || ''));
  const equipment = nodes.filter((n: any) => !isInstrument(n.kind || ''));

  const ratio = nodes.length > 0 ? (edges.length / nodes.length).toFixed(2) : '0';
  const qualityPct = Math.round(Math.min(Number(ratio) / 1.2, 1) * 100);

  const acceptedCount = nodes.filter((n: any) => n.review_status === 'accepted').length;
  const pendingCount = nodes.filter((n: any) => n.review_status !== 'accepted' && n.review_status !== 'rejected').length;

  const FEATURES = [
    {
      title: 'Vision Ingest Suite',
      desc: 'Digitize scanned P&IDs, PDFs, and DWGs through the 9-agent vision extraction pipeline.',
      icon: UploadCloud,
      to: '/pid-studio/ingest',
      color: 'text-sky-500 bg-sky-500/10 border-sky-500/20',
      badge: '9 Vision Agents',
    },
    {
      title: 'Component Review Table',
      desc: 'Verify detected instruments and equipment with inline editing, confidence tiers, and canvas jump.',
      icon: CheckSquare,
      to: '/pid-studio/review',
      color: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20',
      badge: `${nodes.length} Items`,
    },
    {
      title: 'Interactive Vector CAD Canvas',
      desc: 'Full-bleed diagram editor with authentic ISA-5.1 vector symbols, orthogonal routing, and scan overlay.',
      icon: Network,
      to: '/pid-studio/canvas',
      color: 'text-indigo-500 bg-indigo-500/10 border-indigo-500/20',
      badge: 'ISA-5.1 Vector',
    },
    {
      title: 'Describe Multi-Agent Copilot',
      desc: 'Conversational 8-specialist agent engine for greenfield design, brownfield retrofits, and loop authoring.',
      icon: MessageSquareCode,
      to: '/pid-studio/describe',
      color: 'text-purple-500 bg-purple-500/10 border-purple-500/20',
      badge: '8 Specialists',
    },
    {
      title: 'Rule Compliance & Validation',
      desc: 'Automated engineering rule verification: isolated nodes, relief protection, and duplicate tags.',
      icon: ShieldAlert,
      to: '/pid-studio/validation',
      color: 'text-amber-500 bg-amber-500/10 border-amber-500/20',
      badge: 'Automated Audit',
    },
    {
      title: 'CAD & Deliverables Export',
      desc: 'Generate layered AutoCAD DXF, Smart SVG, YMPL process topology, and Instrument Index schedules.',
      icon: Download,
      to: '/pid-studio/export',
      color: 'text-rose-500 bg-rose-500/10 border-rose-500/20',
      badge: 'AutoCAD DXF & SVG',
    },
  ];

  return (
    <PIDStudioLayout>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Project Header Banner */}
        <div className="p-6 rounded-2xl bg-card border border-border shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary text-[10px] font-bold uppercase tracking-wider">
                {graphData?.projectType === 'brownfield' ? 'Brownfield Retrofit' : 'Greenfield Clean-Sheet'}
              </span>
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Clock size={12} /> Active Workspace
              </span>
            </div>
            <h1 className="text-xl font-bold text-foreground tracking-tight">{solutionTitle}</h1>
            <p className="text-xs text-muted-foreground leading-relaxed max-w-xl">
              Unified process flow and piping instrumentation studio. Digitize, review, model, and validate engineering drawings in one synchronized workspace.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate('/pid-studio/canvas')}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-primary text-primary-foreground font-semibold text-xs shadow-sm hover:opacity-90 transition-opacity"
            >
              <Network size={14} /> Open Canvas
            </button>
            <button
              type="button"
              onClick={() => navigate('/pid-studio/describe')}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl border border-border bg-background hover:bg-accent text-foreground text-xs font-semibold shadow-xs transition-colors"
            >
              <Sparkles size={14} className="text-amber-500" /> Describe Copilot
            </button>
          </div>
        </div>

        {/* Metric Cards Row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-4 rounded-xl bg-card border border-border shadow-2xs">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Total Equipment</div>
            <div className="text-2xl font-bold text-foreground mt-1">{equipment.length}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">Pumps, Vessels, Valves</div>
          </div>

          <div className="p-4 rounded-xl bg-card border border-border shadow-2xs">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Instruments & Loops</div>
            <div className="text-2xl font-bold text-foreground mt-1">{instruments.length}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">Transmitters, Controllers, Alarms</div>
          </div>

          <div className="p-4 rounded-xl bg-card border border-border shadow-2xs">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Process Streams</div>
            <div className="text-2xl font-bold text-foreground mt-1">{edges.length}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">Piping, Pneumatics, Signals</div>
          </div>

          <div className="p-4 rounded-xl bg-card border border-border shadow-2xs">
            <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Connectivity Ratio</div>
            <div className="text-2xl font-bold text-emerald-500 mt-1">{ratio} <span className="text-xs font-normal text-muted-foreground">lines/node</span></div>
            <div className="text-[10px] text-emerald-500/80 mt-0.5">{qualityPct}% Topology Integrity</div>
          </div>
        </div>

        {/* Feature Navigation Grid */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Studio Workspaces & Deliverables
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {FEATURES.map((feat, idx) => {
              const Icon = feat.icon;
              return (
                <div
                  key={idx}
                  onClick={() => navigate(feat.to)}
                  className="group p-5 rounded-2xl bg-card border border-border hover:border-primary/50 shadow-xs hover:shadow-md transition-all cursor-pointer flex flex-col justify-between"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className={`p-2.5 rounded-xl border ${feat.color}`}>
                        <Icon size={18} />
                      </div>
                      <span className="px-2 py-0.5 rounded-full bg-muted border border-border text-[10px] font-medium text-muted-foreground">
                        {feat.badge}
                      </span>
                    </div>

                    <div className="space-y-1">
                      <h3 className="font-semibold text-sm text-foreground group-hover:text-primary transition-colors flex items-center gap-1.5">
                        {feat.title}
                        <ArrowRight size={13} className="opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all" />
                      </h3>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {feat.desc}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 pt-3 border-t border-border/50 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>Open workspace</span>
                    <span className="text-primary font-medium">Launch &rarr;</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </PIDStudioLayout>
  );
}
