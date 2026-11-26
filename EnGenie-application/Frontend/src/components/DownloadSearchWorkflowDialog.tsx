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
    Search,
    ArrowDownToLine,
    ArrowUpFromLine,
    Sparkles,
    Trophy,
    Building2,
    Loader2,
} from 'lucide-react';
import {
    buildSearchWorkflowExport,
    generateSearchWorkflowPDF,
    downloadSearchBOMCsv,
    downloadJson,
    copyJsonToClipboard,
    BuildSearchExportParams,
} from '@/utils/workflowExportUtils';

interface DownloadSearchWorkflowDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    exportParams: BuildSearchExportParams;
}

type ExportOption = 'engineering_pdf' | 'bom_csv' | 'full_json' | 'input_json' | 'output_json';

export const DownloadSearchWorkflowDialog: React.FC<DownloadSearchWorkflowDialogProps> = ({
    open,
    onOpenChange,
    exportParams,
}) => {
    const { toast } = useToast();
    const [selectedOption, setSelectedOption] = useState<ExportOption>('engineering_pdf');
    const [pdfItemsLimit, setPdfItemsLimit] = useState<number>(5);
    const [copied, setCopied] = useState(false);
    const [isExporting, setIsExporting] = useState(false);

    const fullExportData = React.useMemo(() => {
        return buildSearchWorkflowExport(exportParams);
    }, [exportParams]);

    const { productType, projectName, inputData, outputData, summary } = fullExportData;

    const handleDownload = async () => {
        setIsExporting(true);
        try {
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
            const safeName = (productType || projectName || 'search')
                .toLowerCase()
                .replace(/[^a-z0-9_-]/g, '_')
                .replace(/_+/g, '_')
                .slice(0, 35);

            switch (selectedOption) {
                case 'engineering_pdf':
                    await generateSearchWorkflowPDF(fullExportData, { maxItems: pdfItemsLimit });
                    toast({
                        title: 'PDF Report Generated',
                        description: `Search engineering report with ${pdfItemsLimit > 0 ? `top ${pdfItemsLimit}` : 'all'} ranked vendor models downloaded as PDF.`,
                    });
                    break;
                case 'bom_csv':
                    downloadSearchBOMCsv(
                        outputData.analysisResult?.rankedProducts || [],
                        productType || 'search'
                    );
                    toast({
                        title: 'CSV Download Started',
                        description: 'Ranked products downloaded as CSV spreadsheet.',
                    });
                    break;
                case 'full_json':
                    downloadJson(
                        fullExportData,
                        `search_workflow_${safeName}_${timestamp}.json`
                    );
                    toast({
                        title: 'JSON Download Started',
                        description: 'Complete search workflow input and output data downloaded as JSON.',
                    });
                    break;
                case 'input_json':
                    downloadJson(
                        {
                            workflow: 'search_workflow_input',
                            version: '1.0',
                            exportedAt: new Date().toISOString(),
                            productType: productType,
                            projectName: projectName,
                            sessionId: fullExportData.sessionId,
                            inputData: inputData,
                        },
                        `search_input_${safeName}_${timestamp}.json`
                    );
                    toast({
                        title: 'JSON Download Started',
                        description: 'Search input specifications and configuration downloaded as JSON.',
                    });
                    break;
                case 'output_json':
                    downloadJson(
                        {
                            workflow: 'search_workflow_output',
                            version: '1.0',
                            exportedAt: new Date().toISOString(),
                            productType: productType,
                            projectName: projectName,
                            sessionId: fullExportData.sessionId,
                            summary: summary,
                            outputData: outputData,
                        },
                        `search_output_${safeName}_${timestamp}.json`
                    );
                    toast({
                        title: 'JSON Download Started',
                        description: 'Search vendor analysis and ranked products downloaded as JSON.',
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
                workflow: 'search_workflow_input',
                productType: productType,
                projectName: projectName,
                inputData: inputData,
            };
        } else if (selectedOption === 'output_json') {
            payloadToCopy = {
                workflow: 'search_workflow_output',
                productType: productType,
                projectName: projectName,
                outputData: outputData,
            };
        }

        const success = await copyJsonToClipboard(payloadToCopy);
        if (success) {
            setCopied(true);
            toast({
                title: 'Copied to Clipboard',
                description: 'Search workflow JSON copied successfully.',
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
                            <Search className="h-5 w-5" />
                        </div>
                        <div>
                            <DialogTitle className="text-lg font-bold text-foreground">
                                Download Search Workflow Data
                            </DialogTitle>
                            <DialogDescription className="text-xs text-muted-foreground">
                                Export technical process specifications, vendor evaluation criteria, and ranked product recommendations.
                            </DialogDescription>
                        </div>
                    </div>
                </DialogHeader>

                {/* Workflow Summary Card */}
                <div className="mt-4 p-3.5 rounded-xl bg-slate-50/80 dark:bg-slate-800/50 border border-slate-200/70 dark:border-slate-700/50 space-y-2">
                    <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
                            <Sparkles className="h-3.5 w-3.5 text-sky-500" />
                            {productType || projectName || 'Industrial Product Search'}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-sky-100 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300 border border-sky-200/50 dark:border-sky-800/50">
                            Search Workflow
                        </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 pt-1 border-t border-slate-200/50 dark:border-slate-700/50 text-[11px]">
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                            <Trophy className="h-3.5 w-3.5 text-amber-500" />
                            <span><strong>{summary.totalRankedProducts}</strong> Ranked Products</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-muted-foreground">
                            <Building2 className="h-3.5 w-3.5 text-sky-500" />
                            <span><strong>{summary.totalVendorsAnalyzed}</strong> Vendors Evaluated</span>
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
                                Comprehensive multi-page document with input requirements, collected technical specifications, AI comparison narrative, and ranked vendor models.
                            </div>

                            {/* Top 3 / Top 5 / All selector */}
                            {selectedOption === 'engineering_pdf' && (
                                <div className="mt-3 pt-2.5 border-t border-sky-200/60 dark:border-sky-800/40 flex items-center justify-between gap-2 flex-wrap text-xs">
                                    <span className="text-slate-600 dark:text-slate-400 text-[11px] font-medium">Include in PDF:</span>
                                    <div className="flex items-center gap-1 bg-white/90 dark:bg-slate-900/90 p-0.5 rounded-lg border border-sky-200 dark:border-sky-800">
                                        {[
                                            { label: 'Top 3', value: 3 },
                                            { label: 'Top 5', value: 5 },
                                            { label: 'All', value: 0 },
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
                        {/* Ranked Products CSV */}
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
                                <div className="text-xs font-bold text-foreground">Ranked Products (CSV)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    Spreadsheet table of vendor models, scores, strengths, and reasoning.
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
                                    All input specs, conversation history, and vendor ranking results.
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
                                <div className="text-xs font-bold text-foreground">Input Specs Only (JSON)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    Search query, collected technical parameters, and preferences.
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
                                <div className="text-xs font-bold text-foreground">Output Rankings Only (JSON)</div>
                                <div className="text-[11px] text-muted-foreground leading-tight mt-0.5">
                                    Ranked vendor options, scores, strengths, and analysis.
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

export default DownloadSearchWorkflowDialog;
