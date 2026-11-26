import React, { useState } from 'react';
import {
    X,
    Upload,
    FileText,
    CheckCircle2,
    AlertCircle,
    Loader2,
    Eye,
    Cpu,
    ArrowRight
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

interface PIDIngestModalProps {
    isOpen: boolean;
    onClose: () => void;
    sessionId: string;
    onExtracted: (result: any) => void;
}

export default function PIDIngestModal({
    isOpen,
    onClose,
    sessionId,
    onExtracted,
}: PIDIngestModalProps) {
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [statusStage, setStatusStage] = useState<string>('');
    const [error, setError] = useState<string | null>(null);

    if (!isOpen) return null;

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        if (e.dataTransfer.files?.[0]) {
            setFile(e.dataTransfer.files[0]);
            setError(null);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files?.[0]) {
            setFile(e.target.files[0]);
            setError(null);
        }
    };

    const handleExtract = async () => {
        if (!file || isUploading) return;
        setIsUploading(true);
        setError(null);
        setStatusStage('Initializing 9-Agent Vision Pipeline...');

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', sessionId);

        try {
            setStatusStage('Vision-LLM Tiling & Symbol Extraction...');
            const token = localStorage.getItem('auth_token');
            const headers: Record<string, string> = {};
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const response = await fetch('/api/pid/extract', {
                method: 'POST',
                headers,
                credentials: 'include',
                body: formData,
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || errData.detail || 'Extraction failed');
            }

            const data = await response.json();
            setStatusStage('Finalizing Graph & Layout...');
            onExtracted(data.result);
            onClose();
        } catch (err: any) {
            console.error('Ingest extraction error:', err);
            setError(err.message || 'Failed to digitize drawing');
        } finally {
            setIsUploading(false);
            setStatusStage('');
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-200">
            <div className="bg-slate-950 border border-border/50 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-5">
                {/* Modal Header */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                        <div className="w-9 h-9 rounded-xl bg-primary/10 border border-primary/30 flex items-center justify-center text-primary">
                            <Upload className="w-5 h-5" />
                        </div>
                        <div>
                            <h3 className="font-semibold text-base text-foreground">Scanned P&ID Digitization</h3>
                            <p className="text-xs text-muted-foreground">
                                9-Agent Vision-LLM Multimodal Ingestion Pipeline
                            </p>
                        </div>
                    </div>
                    <Button variant="ghost" size="icon" onClick={onClose} disabled={isUploading} className="rounded-xl">
                        <X className="w-4 h-4" />
                    </Button>
                </div>

                {/* Drag & Drop Area */}
                <div
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleDrop}
                    className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
                        file
                            ? 'border-primary/50 bg-primary/5'
                            : 'border-slate-800 hover:border-slate-700 bg-slate-900/30'
                    }`}
                >
                    <input
                        type="file"
                        id="pid-file-input"
                        accept=".pdf,.png,.jpg,.jpeg"
                        onChange={handleFileChange}
                        className="hidden"
                    />
                    <label htmlFor="pid-file-input" className="cursor-pointer flex flex-col items-center gap-2">
                        {file ? (
                            <>
                                <FileText className="w-10 h-10 text-primary" />
                                <span className="text-sm font-medium text-foreground">{file.name}</span>
                                <span className="text-xs text-muted-foreground">
                                    {(file.size / (1024 * 1024)).toFixed(2)} MB
                                </span>
                            </>
                        ) : (
                            <>
                                <Upload className="w-10 h-10 text-muted-foreground" />
                                <span className="text-sm font-medium text-foreground">
                                    Click or drag P&ID drawing / PDF here
                                </span>
                                <span className="text-xs text-muted-foreground">
                                    Supports vector PDFs, multi-page scans, PNG and JPEG
                                </span>
                            </>
                        )}
                    </label>
                </div>

                {/* Pipeline Feature Badges */}
                <div className="flex flex-wrap gap-1.5 justify-center">
                    <Badge variant="outline" className="text-[10px] bg-slate-900 border-slate-800 text-slate-400">
                        Dual-LLM Harness
                    </Badge>
                    <Badge variant="outline" className="text-[10px] bg-slate-900 border-slate-800 text-slate-400">
                        Topological Line Tracing
                    </Badge>
                    <Badge variant="outline" className="text-[10px] bg-slate-900 border-slate-800 text-slate-400">
                        Coordinate Geometry
                    </Badge>
                    <Badge variant="outline" className="text-[10px] bg-slate-900 border-slate-800 text-slate-400">
                        Zero ML Fallback
                    </Badge>
                </div>

                {/* Progress & Error */}
                {statusStage && (
                    <div className="p-3 rounded-xl bg-primary/10 border border-primary/20 flex items-center gap-3 text-xs text-primary">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>{statusStage}</span>
                    </div>
                )}

                {error && (
                    <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/30 flex items-center gap-2 text-xs text-destructive">
                        <AlertCircle className="w-4 h-4 flex-shrink-0" />
                        <span>{error}</span>
                    </div>
                )}

                {/* Action Buttons */}
                <div className="flex justify-end gap-2 pt-2">
                    <Button variant="outline" onClick={onClose} disabled={isUploading} className="rounded-xl">
                        Cancel
                    </Button>
                    <Button
                        onClick={handleExtract}
                        disabled={!file || isUploading}
                        className="rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground gap-2"
                    >
                        {isUploading ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Processing...
                            </>
                        ) : (
                            <>
                                Start Digitization <ArrowRight className="w-4 h-4" />
                            </>
                        )}
                    </Button>
                </div>
            </div>
        </div>
    );
}
