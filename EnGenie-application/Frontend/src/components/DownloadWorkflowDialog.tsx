import React, { useState } from 'react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';
import {
    Download,
    Copy,
    Check,
    FileJson,
    FileSpreadsheet,
    FileText,
    Layers,
    ArrowDownToLine,
    ArrowUpFromLine,
    Sparkles,
    SlidersHorizontal,
    Box,
    Loader2,
} from 'lucide-react';
import {
    buildSolutionWorkflowExport,
    generateSolutionWorkflowPDF,
    downloadJson,
    downloadBOMCsv,
    copyJsonToClipboard,
    BuildExportParams,
} from '@/utils/workflowExportUtils';

interface DownloadWorkflowDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    exportParams: BuildExportParams;
}

type ExportOption = 'engineering_pdf' | 'bom_csv' | 'full_json' | 'input_json' | 'output_json';

export const DownloadWorkflowDialog: React.FC<DownloadWorkflowDialogProps> = ({
    open,
    onOpenChange,
    exportParams,
}) => {
    const { toast } = useToast();
    const [selectedOption, setSelectedOption] = useState<ExportOption>('engineering_pdf');
    const [pdfItemsLimit, setPdfItemsLimit] = useState<number>(0);
    const [copied, setCopied] = useState(false);
    const [isExporting, setIsExporting] = useState(false);

    const fullExportData = React.useMemo(() => {
        return buildSolutionWorkflowExport(exportParams);
    }, [exportParams]);

    const { projectName, inputData, outputData, summary } = fullExportData;

    const handleDownload = async () => {
        setIsExporting(true);
        try {
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            const safeProjectName = (projectName || 'solution')
                .toLowerCase()
                .replace(/[^a-z0-9_-]/g, '_')
                .replace(/_+/g, '_')
                .slice(0, 35);

            switch (selectedOption) {
                case 'engineering_pdf':
                    await generateSolutionWorkflowPDF(fullExportData, { maxItems: pdfItemsLimit });
                    toast({
                        title: 'PDF Report Generated',
                        description: `Engineering PDF with user input requirements and ${pdfItemsLimit > 0 ? `top ${pdfItemsLimit}` : 'complete'} output BOM downloaded successfully.`,
                    });
                    break;
                case 'bom_csv':
                    downloadBOMCsv(
                        outputData.instruments,
                        outputData.accessories,
                        projectName
                    );
                    toast({
                        title: 'CSV Download Started',
                        description: 'Bill of Materials (BOM) downloaded as CSV spreadsheet.',
                    });
                    break;
                case 'full_json':
                    downloadJson(
                        fullExportData,
                        `solution_workflow_${safeProjectName}_${timestamp}.json`
                    );
                    toast({
                        title: 'JSON Download Started',
                        description: 'Complete workflow input and output data downloaded as JSON.',
                    });
                    break;
                case 'input_json':
                    downloadJson(
                        {
                            workflow: 'solution_workflow_input',
                            version: '1.0',
                            exportedAt: new Date().toISOString(),
                            projectName: projectName,
                            projectId: fullExportData.projectId,
                            sessionId: fullExportData.sessionId,
                            inputData: inputData,
                        },
                        `solution_input_${safeProjectName}_${timestamp}.json`
                    );
                    toast({
                        title: 'JSON Download Started',
                        description: 'Workflow input requirements and configuration downloaded as JSON.',
                    });
                    break;
                case 'output_json':
                    downloadJson(
                        {
                            workflow: 'solution_workflow_output',
                            version: '1.0',
                            exportedAt: new Date().toISOString(),
                            projectName: projectName,
                            projectId: fullExportData.projectId,
                            summary: summary,
                            outputData: outputData,
                        },
                        `solution_output_${safeProjectName}_${timestamp}.json`
                    );
                    toast({
                        title: 'JSON Download Started',
                        description: 'Workflow output BOM, architecture, and P&ID data downloaded as JSON.',
                    });
                    break;
            }
            onOpenChange(false);
        } catch (error: any) {
            console.error('Export failed:', error);
            toast({
                title: 'Export Failed',
                description: error?.message || 'Failed to generate download file.',
                variant: 'destructive',
            });
        } finally {
            setIsExporting(false);
        }
    };

    const handleCopy = async () => {
        let payloadToCopy: any = fullExportData;
        if (selectedOption === 'input_json') {
            payloadToCopy = {
                workflow: 'solution_workflow_input',
                projectName: projectName,
                inputData: inputData,
            };
        } else if (selectedOption === 'output_json') {
            payloadToCopy = {
                workflow: 'solution_workflow_output',
                projectName: projectName,
                outputData: outputData,
            };
        }

        const success = await copyJsonToClipboard(payloadToCopy);
        if (success) {
            setCopied(true);
            toast({
                title: 'Copied to Clipboard',
                description: 'Workflow JSON copied successfully.',
            });
            setTimeout(() => setCopied(false), 2000);
        } else {
            toast({
                title: 'Copy Failed',
                description: 'Could not copy data to clipboard.',
                variant: 'destructive',
            });
        }
    };

    const getDownloadButtonLabel = () => {
        if (isExporting) return 'Generating...';
        switch (selectedOption) {
            case 'engineering_pdf':
                return 'Download PDF Report';
            case 'bom_csv':
                return 'Download CSV';
            case 'full_json':
                return 'Download Complete JSON';
            default:
                return 'Download JSON';
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-xl bg-white/95 dark:bg-slate-900/95 backdrop-blur-xl border border-sky-100 dark:border-slate-800 shadow-2xl rounded-2xl p-6 sm:p-7">
                <DialogHeader className="space-y-1.5 pb-3 border-b border-border/40">
                    <div className="flex items-center gap-2.5">
                        <div className="p-2 rounded-xl bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/20">
                            <Layers className="h-5 w-5" />
                        </div>
                        <div>
                            <DialogTitle className="text-lg font-bold text-foreground">
                                Download Solution Workflow Data
                            </DialogTitle>
                            <DialogDescription className="text-xs text-muted-foreground">
                                Export full engineering input requirements, identified instruments BOM, architecture, and output specifications.
                            </DialogDescription>
                        </div>
                    </div>
                </DialogHeader>

                {/* Workflow Summary Card */}
                <div className="mt-4 p-3.5 rounded-xl bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/70 dark:border-slate-700/50 space-y-2">
                    <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
                            <Sparkles className="h-3.5 w-3.5 text-sky-500" />
                            {projectName || 'Engineering Solution'}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-sky-100 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300 border border-sky-200/50 dark:border-sky-800/50">
                            {summary.intent ? `Intent: ${summary.intent}` : 'Workflow Active'}
                        </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 pt-1 border-t border-slate-200/50 dark:border-slate-700/50 text-[11px]">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                            <Box className="h-3.5 w-3.5 text-sky-500" />
                            <span><strong>{summary.totalInstruments}</strong> Instruments</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                            <SlidersHorizontal className="h-3.5 w-3.5 text-emerald-500" />
                            <span><strong>{summary.totalAccessories}</strong> Accessories</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                            <span className={`w-2 h-2 rounded-full ${summary.standardsApplied ? 'bg-sky-500' : 'bg-slate-400'}`} />
                            <span>Standards: <strong>{summary.standardsApplied ? 'Applied' : 'Skipped'}</strong></span>
                        </div>
                    </div>
                </div>

                {/* Export Options */}
                <div className="mt-4 space-y-2.5">
                    <label className="text-xs font-semibold text-foreground">Select Export Format</label>

                    {/* Featured Option: Engineering PDF Report */}
                    <div
                        onClick={() => setSelectedOption('engineering_pdf')}
                        className={`p-3.5 rounded-xl border cursor-pointer transition-all duration-200 flex items-start gap-3.5 select-none ${
                            selectedOption === 'engineering_pdf'
                                ? 'bg-sky-50/90 dark:bg-sky-950/40 border-sky-500 ring-2 ring-sky-500/80 shadow-md'
                                : 'bg-background hover:bg-muted/40 border-border/70'
                        }`}
                    >
                        <div className={`p-2.5 rounded-xl ${selectedOption === 'engineering_pdf' ? 'bg-sky-600 text-white shadow-sm' : 'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300'}`}>
                            <FileText className="h-5 w-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                                <span className="text-xs font-bold text-foreground">Engineering Report (PDF)</span>
                                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-sky-100 dark:bg-sky-900/60 text-sky-700 dark:text-sky-300 border border-sky-300 dark:border-sky-700">
                                    Recommended
                                </span>
                            </div>
                            <div className="text-[11px] text-muted-foreground leading-tight mt-1">
                                Complete multi-page document with user input requirements, solution architecture narrative, full instrument/accessory BOM, and P&ID specs.
                            </div>

                            {/* Top 3 / Top 5 / All selector */}
                            {selectedOption === 'engineering_pdf' && (
                                <div className="mt-3 pt-2.5 border-t border-sky-200/60 dark:border-sky-800/40 flex items-center justify-between gap-2 flex-wrap text-xs">
                                    <span className="text-slate-600 dark:text-slate-400 text-[11px] font-medium">BOM Items in PDF:</span>
                                    <div className="flex items-center gap-1 bg-white/90 dark:bg-slate-900/90 p-0.5 rounded-lg border border-sky-200 dark:border-sky-800">
                                        {[
                                            { label: 'All Items', value: 0 },
                                            { label: 'Top 3', value: 3 },
                                            { label: 'Top 5', value: 5 },
                                        ].map((opt) => (
                                            <button
                                                key={opt.value}
                                                type="button"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setPdfItemsLimit(opt.value);
                                                }}
                                                className={`px-2.5 py-0.5 text-[10px] font-semibold rounded-md transition-all ${
                                                    pdfItemsLimit === opt.value
                                                        ? 'bg-sky-500 text-white shadow-xs'
                                                        : 'text-slate-600 dark:text-slate-300 hover:bg-sky-50 dark:hover:bg-slate-800'
                                                }`}
                                            >
                                                {opt.label}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                        {/* BOM CSV */}
                        <div
                            onClick={() => setSelectedOption('bom_csv')}
                            className={`p-3 rounded-xl border cursor-pointer transition-all duration-200 flex items-start gap-3 select-none ${
                                selectedOption === 'bom_csv'
                                    ? 'bg-emerald-50/80 dark:bg-emerald-950/30 border-emerald-500 ring-1 ring-emerald-500 shadow-sm'
                                    : 'bg-background hover:bg-muted/40 border-border/70'
                            }`}
                        >
                            <div className={`p-2 rounded-lg ${selectedOption === 'bom_csv' ? 'bg-emerald-500 text-white' : 'bg-muted text-muted-foreground'}`}>
                                <FileSpreadsheet className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-xs font-bold text-foreground">BOM Spreadsheet (CSV)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    Spreadsheet table with specs, standards, vendors, and quantities.
                                </div>
                            </div>
                        </div>

                        {/* Full Package (JSON) */}
                        <div
                            onClick={() => setSelectedOption('full_json')}
                            className={`p-3 rounded-xl border cursor-pointer transition-all duration-200 flex items-start gap-3 select-none ${
                                selectedOption === 'full_json'
                                    ? 'bg-sky-50/80 dark:bg-sky-950/30 border-sky-500 ring-1 ring-sky-500 shadow-sm'
                                    : 'bg-background hover:bg-muted/40 border-border/70'
                            }`}
                        >
                            <div className={`p-2 rounded-lg ${selectedOption === 'full_json' ? 'bg-sky-500 text-white' : 'bg-muted text-muted-foreground'}`}>
                                <FileJson className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-xs font-bold text-foreground">Complete Package (JSON)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    All input requirements, conversation history, BOM, and P&ID.
                                </div>
                            </div>
                        </div>

                        {/* Input Data Only (JSON) */}
                        <div
                            onClick={() => setSelectedOption('input_json')}
                            className={`p-3 rounded-xl border cursor-pointer transition-all duration-200 flex items-start gap-3 select-none ${
                                selectedOption === 'input_json'
                                    ? 'bg-indigo-50/80 dark:bg-indigo-950/30 border-indigo-500 ring-1 ring-indigo-500 shadow-sm'
                                    : 'bg-background hover:bg-muted/40 border-border/70'
                            }`}
                        >
                            <div className={`p-2 rounded-lg ${selectedOption === 'input_json' ? 'bg-indigo-500 text-white' : 'bg-muted text-muted-foreground'}`}>
                                <ArrowUpFromLine className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-xs font-bold text-foreground">Input Data Only (JSON)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    Requirements prompt, standards settings, and chat turns.
                                </div>
                            </div>
                        </div>

                        {/* Output Data Only (JSON) */}
                        <div
                            onClick={() => setSelectedOption('output_json')}
                            className={`p-3 rounded-xl border cursor-pointer transition-all duration-200 flex items-start gap-3 select-none ${
                                selectedOption === 'output_json'
                                    ? 'bg-violet-50/80 dark:bg-violet-950/30 border-violet-500 ring-1 ring-violet-500 shadow-sm'
                                    : 'bg-background hover:bg-muted/40 border-border/70'
                            }`}
                        >
                            <div className={`p-2 rounded-lg ${selectedOption === 'output_json' ? 'bg-violet-500 text-white' : 'bg-muted text-muted-foreground'}`}>
                                <ArrowDownToLine className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-xs font-bold text-foreground">Output Data Only (JSON)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    BOM instruments, accessories, architecture & P&ID graph.
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <DialogFooter className="mt-6 pt-3 border-t border-border/40 flex flex-col-reverse sm:flex-row items-center justify-between gap-2.5">
                    {selectedOption.endsWith('json') ? (
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={handleCopy}
                            className="w-full sm:w-auto text-xs flex items-center gap-1.5 hover:bg-muted/80"
                        >
                            {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
                            <span>{copied ? 'Copied!' : 'Copy JSON'}</span>
                        </Button>
                    ) : (
                        <div className="hidden sm:block" />
                    )}

                    <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => onOpenChange(false)}
                            className="text-xs"
                        >
                            Cancel
                        </Button>
                        <Button
                            type="button"
                            size="sm"
                            onClick={handleDownload}
                            disabled={isExporting}
                            className="text-xs font-semibold bg-sky-600 hover:bg-sky-700 text-white shadow-md flex items-center gap-1.5 cursor-pointer"
                        >
                            {isExporting ? (
                                <>
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    <span>Generating PDF...</span>
                                </>
                            ) : (
                                <>
                                    <Download className="h-3.5 w-3.5" />
                                    <span>{getDownloadButtonLabel()}</span>
                                </>
                            )}
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

export default DownloadWorkflowDialog;
