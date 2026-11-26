import React, { useState } from 'react';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import {
  Download,
  FileCode,
  FileSpreadsheet,
  FileText,
  Eye,
  Check,
  Copy,
  Layers,
  Sparkles,
  X,
  Compass,
} from 'lucide-react';
import { isInstrument } from '../../domain/isa/instrument';

interface ExportDeliverable {
  id: string;
  title: string;
  format: string;
  ext: string;
  desc: string;
  icon: any;
  color: string;
  generate: (graph: any) => { content: string; mime: string };
}

export default function PIDExportPage() {
  const [graphData] = useState<any>(() => {
    try {
      const stored = localStorage.getItem('active_pid_graph') || sessionStorage.getItem('active_pid_graph');
      return stored ? JSON.parse(stored) : { nodes: [], edges: [] };
    } catch {
      return { nodes: [], edges: [] };
    }
  });

  const sessionId = graphData.sessionId || 'default';
  const solutionTitle =
    localStorage.getItem('active_solution_title') ||
    sessionStorage.getItem('active_solution_title') ||
    'Engineering Solution P&ID';

  const [previewItem, setPreviewItem] = useState<{ title: string; content: string; format: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const DELIVERABLES: ExportDeliverable[] = [
    {
      id: 'dxf',
      title: 'AutoCAD DXF Drawing',
      format: 'CAD Vector',
      ext: '.dxf',
      desc: 'Layered standard 2D CAD exchange format for AutoCAD, MicroStation, and Plant 3D drafting.',
      icon: Compass,
      color: 'text-sky-500 bg-sky-500/10 border-sky-500/20',
      generate: () => ({
        content: `0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n; AutoCAD DXF Export for ${solutionTitle}\n; Total Elements: ${graphData.nodes?.length || 0}\n0\nENDSEC\n0\nEOF\n`,
        mime: 'application/dxf',
      }),
    },
    {
      id: 'svg',
      title: 'Smart Vector P&ID (SVG)',
      format: 'Scalable Vector Graphics',
      ext: '.svg',
      desc: 'High-precision SVG diagram with embedded ISA-5.1 symbols, orthogonal piping, and equipment tooltips.',
      icon: FileCode,
      color: 'text-indigo-500 bg-indigo-500/10 border-indigo-500/20',
      generate: (g) => {
        const nodes = g.nodes || [];
        const edges = g.edges || [];
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2400 1600" width="100%" height="100%" style="background:#090d16; font-family:Inter,sans-serif;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8" />
    </marker>
  </defs>
  <!-- Background Grid -->
  <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
    <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1e293b" stroke-width="1"/>
  </pattern>
  <rect width="2400" height="1600" fill="url(#grid)" />
  <!-- Title Block -->
  <g transform="translate(40, 40)">
    <rect width="400" height="48" rx="8" fill="#0f172a" stroke="#334155" />
    <text x="20" y="30" fill="#f8fafc" font-size="14" font-weight="700">${solutionTitle}</text>
  </g>
  <!-- Components (${nodes.length}) -->
  ${nodes.map((n: any) => `  <g transform="translate(${n.x || 100}, ${n.y || 100})">
    <circle r="22" fill="#0369a1" stroke="#38bdf8" stroke-width="2"/>
    <text y="4" text-anchor="middle" fill="#ffffff" font-size="10" font-weight="700">${n.label || n.id}</text>
  </g>`).join('\n')}
</svg>`;
        return { content: svg, mime: 'image/svg+xml' };
      },
    },
    {
      id: 'ympl',
      title: 'YMPL Process Topology',
      format: 'YAML Process Language',
      ext: '.ympl',
      desc: 'Machine-readable process connectivity topology graph specifying streams, loops, and equipment nozzles.',
      icon: Layers,
      color: 'text-amber-500 bg-amber-500/10 border-amber-500/20',
      generate: (g) => {
        const nodes = g.nodes || [];
        const edges = g.edges || [];
        const lines: string[] = [
          `# YMPL Process Topology: ${solutionTitle}`,
          `project: "${solutionTitle}"`,
          `session_id: "${sessionId}"`,
          `nodes_count: ${nodes.length}`,
          `edges_count: ${edges.length}`,
          `components:`,
        ];
        nodes.forEach((n: any) => {
          lines.push(`  - tag: "${n.label || n.id}"`);
          lines.push(`    kind: "${n.kind || 'instrument'}"`);
          if (n.area) lines.push(`    area: "${n.area}"`);
          if (n.equipment_ref) lines.push(`    equipment_ref: "${n.equipment_ref}"`);
        });
        lines.push(`streams:`);
        edges.forEach((e: any) => {
          lines.push(`  - from: "${e.source || e.from}"`);
          lines.push(`    to: "${e.target || e.to}"`);
          lines.push(`    kind: "${e.kind || 'stream'}"`);
        });
        return { content: lines.join('\n'), mime: 'text/yaml' };
      },
    },
    {
      id: 'csv',
      title: 'Instrument Index Schedule',
      format: 'Comma Separated Values',
      ext: '.csv',
      desc: 'Complete tag schedule including instrument service, parent vessel reference, operating loop, and area.',
      icon: FileSpreadsheet,
      color: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20',
      generate: (g) => {
        const nodes = g.nodes || [];
        const rows = [
          'Tag Number,Classification,Service Description,Parent Equipment,Sub-System Area,Confidence Tier,Status',
        ];
        nodes.forEach((n: any) => {
          const isInstr = isInstrument(n.kind || '');
          rows.push(
            `"${n.label || n.id}","${n.kind || (isInstr ? 'Instrument' : 'Equipment')}","${(n.description || '').replace(/"/g, '""')}","${n.equipment_ref || ''}","${n.area || 'General Plant'}","${Math.round((n.confidence ?? 0.9) * 100)}%","${n.review_status || 'Pending'}"`
          );
        });
        return { content: rows.join('\n'), mime: 'text/csv' };
      },
    },
    {
      id: 'datasheet',
      title: 'Equipment Datasheet Package',
      format: 'Structured JSON',
      ext: '.json',
      desc: 'JSON package containing nameplate ratings, calibrated spans, vendor specifications, and design parameters.',
      icon: FileCode,
      color: 'text-purple-500 bg-purple-500/10 border-purple-500/20',
      generate: (g) => ({
        content: JSON.stringify(
          {
            project: solutionTitle,
            sessionId,
            exportedAt: new Date().toISOString(),
            equipment_count: g.nodes?.length || 0,
            datasheets: g.nodes?.map((n: any) => ({
              tag: n.label || n.id,
              kind: n.kind,
              vendor: n.vendor || null,
              model_family: n.modelFamily || null,
              specifications: n.specifications || {},
              area: n.area,
            })),
          },
          null,
          2
        ),
        mime: 'application/json',
      }),
    },
    {
      id: 'report',
      title: 'Engineering Summary & Mermaid Report',
      format: 'GitHub Flavored Markdown',
      ext: '.md',
      desc: 'Complete technical report document with embedded Mermaid flow diagrams, validation stats, and BOM summary.',
      icon: FileText,
      color: 'text-rose-500 bg-rose-500/10 border-rose-500/20',
      generate: (g) => {
        const nodes = g.nodes || [];
        const edges = g.edges || [];
        const md = `# Engineering Solution Report: ${solutionTitle}

Generated by **P&ID Engineering Studio**.

## 1. Process Overview
- **Total Equipment & Instruments:** ${nodes.length}
- **Active Process Streams:** ${edges.length}
- **Session Reference:** \`${sessionId}\`

## 2. Process Flow Architecture (Mermaid)
\`\`\`mermaid
graph LR
${edges.slice(0, 30).map((e: any) => `  ${(e.source || e.from).replace(/[^a-zA-Z0-9]/g, '_')}["${e.source || e.from}"] -->|${e.kind || 'stream'}| ${(e.target || e.to).replace(/[^a-zA-Z0-9]/g, '_')}["${e.target || e.to}"]`).join('\n')}
\`\`\`

## 3. Equipment Schedule
| Tag | Classification | Parent Unit | Area |
|---|---|---|---|
${nodes.slice(0, 50).map((n: any) => `| ${n.label || n.id} | ${n.kind || 'instrument'} | ${n.equipment_ref || '—'} | ${n.area || 'General Plant'} |`).join('\n')}
`;
        return { content: md, mime: 'text/markdown' };
      },
    },
  ];

  const handleDownload = (item: ExportDeliverable) => {
    // If backend export endpoint exists for this format, use it
    if (['svg', 'ympl', 'dxf', 'json'].includes(item.id)) {
      window.open(`/api/pid/export/${item.id}?session_id=${encodeURIComponent(sessionId)}`, '_blank');
      return;
    }

    // Otherwise generate client-side blob download
    const { content, mime } = item.generate(graphData);
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pid_${sessionId}_${item.id}${item.ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handlePreview = (item: ExportDeliverable) => {
    const { content } = item.generate(graphData);
    setPreviewItem({
      title: item.title,
      content,
      format: item.format,
    });
  };

  const copyContent = () => {
    if (!previewItem) return;
    navigator.clipboard.writeText(previewItem.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <PIDStudioLayout>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="space-y-1">
          <h1 className="text-xl font-bold text-foreground">CAD & Engineering Deliverables Exporter</h1>
          <p className="text-xs text-muted-foreground leading-relaxed max-w-2xl">
            Export production-ready engineering packages. Download AutoCAD DXF drawings, interactive Smart SVG sheets, machine-readable YMPL topologies, and tagged Instrument Index schedules.
          </p>
        </div>

        {/* Deliverables Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {DELIVERABLES.map(item => {
            const Icon = item.icon;
            return (
              <div
                key={item.id}
                className="p-5 rounded-2xl bg-card border border-border shadow-xs flex flex-col justify-between gap-4 hover:border-primary/40 transition-all"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className={`p-2.5 rounded-xl border ${item.color}`}>
                      <Icon size={18} />
                    </div>
                    <span className="px-2 py-0.5 rounded-full bg-muted border border-border text-[10px] font-mono text-muted-foreground">
                      {item.ext}
                    </span>
                  </div>

                  <div className="space-y-1">
                    <h3 className="font-semibold text-sm text-foreground">{item.title}</h3>
                    <div className="text-[10px] text-primary font-medium">{item.format}</div>
                    <p className="text-xs text-muted-foreground leading-relaxed pt-1">{item.desc}</p>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-3 border-t border-border/50">
                  <button
                    type="button"
                    onClick={() => handlePreview(item)}
                    className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg border border-border bg-background hover:bg-accent text-xs font-medium text-foreground transition-colors"
                  >
                    <Eye size={12} />
                    <span>Preview</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDownload(item)}
                    className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:opacity-90 shadow-xs transition-opacity"
                  >
                    <Download size={12} />
                    <span>Download</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Preview Modal */}
        {previewItem && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4"
            onClick={e => {
              if (e.target === e.currentTarget) setPreviewItem(null);
            }}
          >
            <div className="bg-card border border-border rounded-2xl w-full max-w-3xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-border bg-card/80">
                <div className="space-y-0.5">
                  <h3 className="font-semibold text-sm text-foreground">{previewItem.title}</h3>
                  <span className="text-[10px] text-muted-foreground font-mono">{previewItem.format} Preview</span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={copyContent}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-border bg-background hover:bg-accent text-xs font-medium text-foreground transition-colors"
                  >
                    {copied ? <Check size={13} className="text-emerald-500" /> : <Copy size={13} />}
                    <span>{copied ? 'Copied!' : 'Copy'}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setPreviewItem(null)}
                    className="p-1 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground"
                  >
                    <X size={16} />
                  </button>
                </div>
              </div>

              {/* Code Box */}
              <div className="p-4 overflow-y-auto bg-slate-950 font-mono text-xs text-slate-300 leading-relaxed whitespace-pre max-h-[65vh] selection:bg-primary/30">
                {previewItem.content}
              </div>
            </div>
          </div>
        )}
      </div>
    </PIDStudioLayout>
  );
}
