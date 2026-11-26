import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { PIDStudioLayout } from '../../components/PIDStudio/PIDStudioLayout';
import {
  UploadCloud,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Sparkles,
  ArrowRight,
  Layers,
  Network,
  CheckSquare,
  Clock,
  Eye,
  RefreshCw,
} from 'lucide-react';
import { emitGraphChanged } from '../../features/canvas/graphEvents';

interface IngestStage {
  id: string;
  name: string;
  desc: string;
  status: 'idle' | 'running' | 'done' | 'error';
}

const INITIAL_STAGES: IngestStage[] = [
  { id: 'quality', name: '1. Quality Assessment', desc: 'Resolution, noise, and scan angle analysis', status: 'idle' },
  { id: 'symbol', name: '2. Symbol Detection', desc: 'Vision LLM reads equipment and instrument symbols', status: 'idle' },
  { id: 'text', name: '3. Text Reading', desc: 'Vision LLM reads tags, loop numbers, and service titles', status: 'idle' },
  { id: 'line', name: '4. Line & Pipeline Tracing', desc: 'Vision LLM follows pipe runs and signal lines', status: 'idle' },
  { id: 'cv', name: '5. Detection Consolidation', desc: 'LLM merges symbol, text and line readings', status: 'idle' },
  { id: 'relation', name: '6. Relationship Inference', desc: 'Topology connection pairing (Equipment ➔ Instrument ➔ Line)', status: 'idle' },
  { id: 'harness', name: '7. Dual-LLM Harness Audit', desc: 'Verification between specialized models A & B', status: 'idle' },
  { id: 'inference', name: '8. Engineering Logic Verification', desc: 'ISA-5.1 compliance and tag syntax validation', status: 'idle' },
  { id: 'layout', name: '9. Orthogonal Grid Assembly', desc: 'Lock-step coordinate transformation and export packaging', status: 'idle' },
];

/** The passes of the brownfield vision read (backend PROGRESS_STAGES), shown
 *  as they really happen for an uploaded image. */
export const DIGITISE_STAGES: IngestStage[] = [
  { id: 'upload', name: '1. Upload', desc: 'Drawing received and stored as the canvas background', status: 'idle' },
  { id: 'read', name: '2. Tag Reading', desc: 'Two tile grids read every tag, note and line number', status: 'idle' },
  { id: 'verify', name: '3. Tag Verification', desc: 'Doubtful tags re-read in close-up crops', status: 'idle' },
  { id: 'symbols', name: '4. Symbols & Annotations', desc: 'Untagged symbols, inferred valves, ISA names, notes', status: 'idle' },
  { id: 'connect', name: '5. Connection Tracing', desc: 'Pipe runs and signal lines between symbols', status: 'idle' },
  { id: 'headers', name: '6. Headers & Off-Sheet Flags', desc: 'Sheet-wide headers and the lines of off-sheet flags', status: 'idle' },
  { id: 'store', name: '7. Digital P&ID', desc: 'Graph, line labels and review items saved for the canvas', status: 'idle' },
];

/** Stage list with everything before `current` done and `current` running. */
export function stagesAt(current: string, state: 'running' | 'done' | 'error'): IngestStage[] {
  const at = DIGITISE_STAGES.findIndex(s => s.id === current);
  return DIGITISE_STAGES.map((s, i) => ({
    ...s,
    status: state === 'done' ? 'done'
      : i < at ? 'done'
      : i === at ? (state === 'error' ? 'error' : 'running')
      : 'idle',
  }));
}

const isImage = (f: File | null) => !!f && (f.type.startsWith('image/') || /\.(png|jpe?g|bmp|tiff?)$/i.test(f.name));

export default function PIDIngestPage() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [stages, setStages] = useState<IngestStage[]>(INITIAL_STAGES);
  const [isExtracting, setIsExtracting] = useState<boolean>(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [extractedResult, setExtractedResult] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFile(e.target.files[0]);
    }
  };

  const processFile = (file: File) => {
    setSelectedFile(file);
    setErrorMsg(null);
    setExtractedResult(null);
    setStages(isImage(file) ? DIGITISE_STAGES : INITIAL_STAGES);

    if (file.type.startsWith('image/')) {
      const reader = new FileReader();
      reader.onload = () => setPreviewUrl(reader.result as string);
      reader.readAsDataURL(file);
    } else {
      setPreviewUrl(null);
    }
  };

  const authHeaders = (): Record<string, string> => {
    const token = localStorage.getItem('auth_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  /** An image goes to the brownfield vision digitiser as a background job; the
   *  page follows its real stages and loads the stored graph when it is done. */
  const runDigitise = async (file: File) => {
    const sessionId = 'default';
    setStages(stagesAt('upload', 'running'));
    const form = new FormData();
    form.append('file', file);
    form.append('session_id', sessionId);
    const start = await fetch('/api/pid/digitise', {
      method: 'POST', headers: authHeaders(), credentials: 'include', body: form,
    });
    if (!start.ok && start.status !== 409) {
      const err = await start.json().catch(() => ({}));
      throw new Error(err.error || err.detail || `Server returned ${start.status}`);
    }
    for (;;) {
      await new Promise(r => setTimeout(r, 3000));
      const res = await fetch(`/api/pid/digitise/status?session_id=${encodeURIComponent(sessionId)}`, {
        headers: authHeaders(), credentials: 'include',
      });
      if (!res.ok) throw new Error(`Status check failed (${res.status})`);
      const job = await res.json();
      if (job.state === 'error') {
        setStages(stagesAt(job.stage || 'read', 'error'));
        throw new Error(job.error || 'The drawing could not be digitised');
      }
      if (job.state === 'done') {
        setStages(stagesAt('store', 'done'));
        const graph = job.pid_graph;
        if (graph) {
          const g = { ...graph, sessionId, projectType: 'brownfield' };
          localStorage.setItem('active_pid_graph', JSON.stringify(g));
          sessionStorage.setItem('active_pid_graph', JSON.stringify(g));
          emitGraphChanged(sessionId);
        }
        setExtractedResult({
          digitised: true,
          counts: job.counts || {},
          warnings: job.warnings || [],
          summary: job.summary,
          seconds: job.finished && job.started ? Math.round(job.finished - job.started) : undefined,
        });
        return;
      }
      setStages(stagesAt(job.stage || 'read', 'running'));
    }
  };

  const runExtraction = async () => {
    if (!selectedFile || isExtracting) return;

    setIsExtracting(true);
    setErrorMsg(null);

    if (isImage(selectedFile)) {
      try {
        await runDigitise(selectedFile);
      } catch (err: unknown) {
        setErrorMsg(err instanceof Error ? err.message : String(err));
      } finally {
        setIsExtracting(false);
      }
      return;
    }

    // Reset stages
    setStages(prev => prev.map(s => ({ ...s, status: 'idle' })));

    // Animate stage sequence while uploading
    let currentIdx = 0;
    const interval = setInterval(() => {
      setStages(prev =>
        prev.map((s, idx) => {
          if (idx < currentIdx) return { ...s, status: 'done' };
          if (idx === currentIdx) return { ...s, status: 'running' };
          return { ...s, status: 'idle' };
        })
      );
      currentIdx++;
      if (currentIdx >= INITIAL_STAGES.length) {
        clearInterval(interval);
      }
    }, 1800);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('session_id', 'default');

      const token = localStorage.getItem('auth_token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const resp = await fetch('/api/pid/extract', {
        method: 'POST',
        headers,
        credentials: 'include',
        body: formData,
      });

      clearInterval(interval);

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || err.detail || `Server returned ${resp.status}`);
      }

      const data = await resp.json();
      setExtractedResult(data.result);

      // All stages marked done
      setStages(prev => prev.map(s => ({ ...s, status: 'done' })));

      // Save graph into local storage
      if (data.result?.verified_nodes) {
        const newGraph = {
          sessionId: 'default',
          projectType: 'brownfield',
          nodes: data.result.verified_nodes,
          edges: data.result.verified_edges || [],
          pageImage: previewUrl || undefined,
        };
        localStorage.setItem('active_pid_graph', JSON.stringify(newGraph));
        sessionStorage.setItem('active_pid_graph', JSON.stringify(newGraph));
        emitGraphChanged('default');
      }
    } catch (err: unknown) {
      clearInterval(interval);
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      setStages(prev =>
        prev.map(s => (s.status === 'running' ? { ...s, status: 'error' } : s))
      );
    } finally {
      setIsExtracting(false);
    }
  };

  return (
    <PIDStudioLayout>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        {/* Title */}
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded-full bg-sky-500/10 border border-sky-500/20 text-sky-500 text-[10px] font-bold uppercase tracking-wider">
              Multimodal Vision Ingestion
            </span>
          </div>
          <h1 className="text-xl font-bold text-foreground">Scanned P&ID Digitize & Extraction</h1>
          <p className="text-xs text-muted-foreground leading-relaxed max-w-2xl">
            Upload legacy scanned engineering drawings, PDF sheets, or raster diagrams. The 9-agent multimodal pipeline parses equipment, detects ISA-5.1 tags, traces process lines, and constructs a CAD-grade vector topology.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Upload & Preview (7 cols) */}
          <div className="lg:col-span-7 space-y-4">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp"
              className="hidden"
            />

            {/* Drag & Drop Zone */}
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={handleFileDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`p-8 rounded-2xl border-2 border-dashed transition-all cursor-pointer text-center flex flex-col items-center justify-center gap-3 ${
                selectedFile
                  ? 'border-primary/50 bg-primary/5'
                  : 'border-border bg-card/60 hover:bg-card hover:border-primary/40'
              }`}
            >
              <div className="w-14 h-14 rounded-2xl bg-sky-500/10 border border-sky-500/20 text-sky-500 flex items-center justify-center shadow-inner">
                <UploadCloud size={28} />
              </div>

              <div className="space-y-1">
                <h3 className="font-semibold text-sm text-foreground">
                  {selectedFile ? selectedFile.name : 'Drop engineering drawing sheet here'}
                </h3>
                <p className="text-xs text-muted-foreground">
                  Supports PDF, PNG, JPG, TIFF, or DWG raster prints up to 50MB
                </p>
              </div>

              {selectedFile && (
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span>{(selectedFile.size / (1024 * 1024)).toFixed(2)} MB</span>
                  <span>&bull;</span>
                  <span className="text-primary font-medium">Ready to extract</span>
                </div>
              )}
            </div>

            {/* Preview image if available */}
            {previewUrl && (
              <div className="p-3 rounded-2xl bg-card border border-border shadow-xs space-y-2">
                <div className="flex items-center justify-between text-xs font-semibold text-foreground px-1">
                  <span>Document Preview</span>
                  <span className="text-[10px] text-muted-foreground font-mono">1:1 Aspect</span>
                </div>
                <div className="rounded-xl overflow-hidden border border-border bg-black max-h-64 flex items-center justify-center">
                  <img src={previewUrl} alt="P&ID Scan Preview" className="object-contain max-h-64 w-full" />
                </div>
              </div>
            )}

            {/* Action Button */}
            {selectedFile && !extractedResult && (
              <button
                type="button"
                onClick={runExtraction}
                disabled={isExtracting}
                className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-primary text-primary-foreground font-semibold text-xs shadow-md hover:opacity-90 disabled:opacity-50 transition-all cursor-pointer"
              >
                {isExtracting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    <span>{isImage(selectedFile)
                      ? 'Digitising the drawing (a few minutes)...'
                      : 'Executing 9-Agent Vision Pipeline...'}</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={14} />
                    <span>Start Extraction Pipeline</span>
                  </>
                )}
              </button>
            )}

            {/* Extraction Result Summary */}
            {extractedResult && (
              <div className="p-5 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-500 space-y-3 shadow-xs">
                <div className="flex items-center gap-2 font-bold text-sm">
                  <CheckCircle2 size={18} />
                  <span>Extraction Finished Successfully!</span>
                </div>
                {extractedResult.digitised ? (
                  <div className="space-y-2 text-xs text-foreground/80">
                    <p className="leading-relaxed">
                      Digitised {extractedResult.counts.equipment ?? 0} equipment, {extractedResult.counts.instruments ?? 0} instruments
                      and {extractedResult.counts.headers ?? 0} headers / flags, with {extractedResult.counts.connections ?? 0} connections
                      ({extractedResult.counts.labelled_lines ?? 0} carrying their printed line number)
                      {extractedResult.seconds ? ` in ${Math.round(extractedResult.seconds / 60)} min` : ''}.
                      The canvas opens over the scanned sheet so every symbol can be checked in place.
                    </p>
                    {extractedResult.warnings?.length > 0 && (
                      <ul className="list-disc pl-4 space-y-0.5 text-amber-600 dark:text-amber-300">
                        {extractedResult.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                      </ul>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-foreground/80 leading-relaxed">
                    Extracted {extractedResult.verified_nodes?.length || 0} equipment items and {extractedResult.verified_edges?.length || 0} process connections. Graph is saved to your workspace.
                  </p>
                )}

                <div className="flex items-center gap-2 pt-2 border-t border-emerald-500/20">
                  <button
                    type="button"
                    onClick={() => navigate('/pid-studio/review')}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs shadow-xs transition-colors"
                  >
                    <CheckSquare size={13} /> Review Components
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/pid-studio/canvas')}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-background border border-emerald-500/40 text-foreground hover:bg-accent font-medium text-xs transition-colors"
                  >
                    <Network size={13} /> Open in Canvas
                  </button>
                </div>
              </div>
            )}

            {errorMsg && (
              <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-500 flex items-start gap-2.5 text-xs">
                <AlertCircle size={16} className="shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <span className="font-semibold">Extraction Error:</span>
                  <p className="text-muted-foreground">{errorMsg}</p>
                </div>
              </div>
            )}
          </div>

          {/* Right Column: 9-Agent Pipeline Status (5 cols) */}
          <div className="lg:col-span-5 p-5 rounded-2xl bg-card border border-border shadow-xs space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-border">
              <h3 className="font-semibold text-xs text-foreground tracking-tight flex items-center gap-1.5">
                <Layers size={14} className="text-primary" />
                Extraction Pipeline Stages
              </h3>
              <span className="text-[10px] text-muted-foreground font-mono">
                {isImage(selectedFile) ? 'Brownfield Vision Digitiser' : '9 Specialized Agents'}
              </span>
            </div>

            <div className="space-y-2">
              {stages.map((stage, idx) => (
                <div
                  key={stage.id}
                  className={`p-2.5 rounded-xl border transition-all flex items-center justify-between ${
                    stage.status === 'running'
                      ? 'bg-primary/10 border-primary text-primary shadow-xs'
                      : stage.status === 'done'
                      ? 'bg-emerald-500/5 border-emerald-500/30 text-emerald-500'
                      : stage.status === 'error'
                      ? 'bg-red-500/10 border-red-500/30 text-red-500'
                      : 'bg-background/40 border-border text-muted-foreground'
                  }`}
                >
                  <div className="space-y-0.5 pr-2 truncate">
                    <div className="font-medium text-xs text-foreground truncate">{stage.name}</div>
                    <div className="text-[10px] text-muted-foreground truncate">{stage.desc}</div>
                  </div>

                  <div className="shrink-0">
                    {stage.status === 'running' && <Loader2 size={14} className="animate-spin text-primary" />}
                    {stage.status === 'done' && <CheckCircle2 size={14} className="text-emerald-500" />}
                    {stage.status === 'error' && <AlertCircle size={14} className="text-red-500" />}
                    {stage.status === 'idle' && <Clock size={13} className="text-muted-foreground/40" />}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </PIDStudioLayout>
  );
}
