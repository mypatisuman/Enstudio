/**
 * Solution Workflow Export Utilities
 * 
 * Formats and packages the complete Input and Output data of the Solution Workflow
 * for export/download as JSON or CSV.
 */

export interface SolutionWorkflowExportData {
    workflow: string;
    version: string;
    exportedAt: string;
    projectName: string;
    projectId?: string | null;
    sessionId?: string | null;
    summary: {
        totalInstruments: number;
        totalAccessories: number;
        standardsApplied: boolean;
        intent?: string;
    };
    inputData: {
        userRequirements: string;
        standardsEnabled: boolean;
        currentInstruments?: any[];
        currentAccessories?: any[];
        conversationHistory?: {
            role: string;
            content: string;
            timestamp?: string;
        }[];
        workflowConfiguration?: {
            page: string;
            skipStandards: boolean;
            sessionId?: string | null;
            userSessionId?: string | null;
            streamId?: string | null;
        };
    };
    outputData: {
        intent?: string;
        assistantMessage?: string;
        summary?: string;
        engineeringCompleteness?: any;
        consolidatedRequirements?: string | null;
        standardsApplied?: boolean;
        instruments: any[];
        accessories: any[];
        designedSolution?: {
            projectObjective?: string;
            designOverview?: string;
            componentRoles?: any[];
            optimizations?: string[];
            designConsiderations?: string[];
            assumptions?: string[];
            pidGraph?: any;
        } | null;
        changesMade?: any[];
        agentPath?: string[];
    };
}

export interface BuildExportParams {
    projectName?: string;
    projectId?: string | null;
    sessionId?: string | null;
    userRequirements?: string;
    standardsEnabled?: boolean;
    chatMessages?: any[];
    instruments?: any[];
    accessories?: any[];
    designedSolution?: any;
    intentResult?: any;
    streamId?: string | null;
}

/**
 * Builds a comprehensive, structured data object containing all input and output data of the solution workflow.
 */
export function buildSolutionWorkflowExport(params: BuildExportParams): SolutionWorkflowExportData {
    const {
        projectName = 'Project',
        projectId = null,
        sessionId = null,
        userRequirements = '',
        standardsEnabled = true,
        chatMessages = [],
        instruments = [],
        accessories = [],
        designedSolution = null,
        intentResult = null,
        streamId = null,
    } = params;

    // Extract formatted conversation history
    const conversationHistory = chatMessages.map((msg) => ({
        role: msg.type === 'user' ? 'user' : 'assistant',
        content: msg.content || '',
        timestamp: msg.timestamp ? new Date(msg.timestamp).toISOString() : undefined,
    }));

    // Extract output intent & assistant message
    const intent = intentResult?.intent || (instruments.length > 0 ? 'requirements' : 'unknown');
    const assistantMessage = intentResult?.message || chatMessages.filter(m => m.type === 'assistant').pop()?.content || '';
    const summary = intentResult?.summary || '';
    const consolidatedRequirements = intentResult?.consolidatedRequirements || null;
    const engineeringCompleteness = intentResult?.engineeringCompleteness || null;
    const changesMade = intentResult?.changesMade || undefined;
    const agentPath = intentResult?.agentPath || intentResult?.agent_path || [];

    return {
        workflow: 'solution_workflow',
        version: '1.0',
        exportedAt: new Date().toISOString(),
        projectName: projectName.trim() || 'Engineering Solution',
        projectId: projectId || null,
        sessionId: sessionId || null,
        summary: {
            totalInstruments: instruments.length,
            totalAccessories: accessories.length,
            standardsApplied: standardsEnabled,
            intent: intent,
        },
        inputData: {
            userRequirements: userRequirements || '',
            standardsEnabled: Boolean(standardsEnabled),
            conversationHistory: conversationHistory.length > 0 ? conversationHistory : undefined,
            workflowConfiguration: {
                page: 'solution',
                skipStandards: !standardsEnabled,
                sessionId: sessionId || null,
                streamId: streamId || null,
            },
        },
        outputData: {
            intent: intent,
            assistantMessage: assistantMessage,
            summary: summary,
            engineeringCompleteness: engineeringCompleteness,
            consolidatedRequirements: consolidatedRequirements,
            standardsApplied: Boolean(standardsEnabled),
            instruments: instruments,
            accessories: accessories,
            designedSolution: designedSolution || intentResult?.designedSolution || null,
            changesMade: changesMade,
            agentPath: agentPath.length > 0 ? agentPath : undefined,
        },
    };
}

/**
 * Triggers a browser download of a JSON object.
 */
export function downloadJson(data: any, filename: string): void {
    const jsonString = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonString], { type: 'application/json;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename.endsWith('.json') ? filename : `${filename}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/**
 * Generates and downloads a CSV spreadsheet of instruments and accessories BOM.
 */
export function downloadBOMCsv(instruments: any[] = [], accessories: any[] = [], projectName: string = 'solution'): void {
    const sanitizeCsvField = (val: any): string => {
        if (val === null || val === undefined) return '';
        let str = typeof val === 'object' ? JSON.stringify(val) : String(val);
        // Escape quotes
        str = str.replace(/"/g, '""');
        if (str.includes(',') || str.includes('\n') || str.includes('"')) {
            return `"${str}"`;
        }
        return str;
    };

    const headers = [
        'Item Type',
        'Category',
        'Product / Accessory Name',
        'Quantity',
        'Key Specifications',
        'Applicable Standards',
        'Specified Vendors',
        'Specified Model Families',
        'Procurement Strategy',
        'Parent Instrument Category',
        'Standards Summary'
    ];

    const rows: string[] = [headers.join(',')];

    // Format Instruments
    instruments.forEach((inst) => {
        const specSummary = inst.specifications
            ? Object.entries(inst.specifications)
                .map(([k, v]) => `${k}: ${v}`)
                .join('; ')
            : '';
        const standards = Array.isArray(inst.applicableStandards) ? inst.applicableStandards.join('; ') : '';
        const vendors = Array.isArray(inst.specifiedVendors) ? inst.specifiedVendors.join('; ') : '';
        const models = Array.isArray(inst.specifiedModelFamilies) ? inst.specifiedModelFamilies.join('; ') : '';

        const row = [
            'Instrument',
            sanitizeCsvField(inst.category || ''),
            sanitizeCsvField(inst.productName || inst.name || ''),
            sanitizeCsvField(inst.quantity || 1),
            sanitizeCsvField(specSummary),
            sanitizeCsvField(standards),
            sanitizeCsvField(vendors),
            sanitizeCsvField(models),
            sanitizeCsvField(inst.strategy || ''),
            '', // Parent category (N/A for instruments)
            sanitizeCsvField(inst.standardsSummary || '')
        ];
        rows.push(row.join(','));
    });

    // Format Accessories
    accessories.forEach((acc) => {
        const specSummary = acc.specifications
            ? Object.entries(acc.specifications)
                .map(([k, v]) => `${k}: ${v}`)
                .join('; ')
            : '';
        const standards = Array.isArray(acc.applicableStandards) ? acc.applicableStandards.join('; ') : '';
        const vendors = Array.isArray(acc.specifiedVendors) ? acc.specifiedVendors.join('; ') : '';

        const row = [
            'Accessory',
            sanitizeCsvField(acc.category || ''),
            sanitizeCsvField(acc.accessoryName || acc.name || ''),
            sanitizeCsvField(acc.quantity || 1),
            sanitizeCsvField(specSummary),
            sanitizeCsvField(standards),
            sanitizeCsvField(vendors),
            '', // Model families
            sanitizeCsvField(acc.strategy || ''),
            sanitizeCsvField(acc.parentInstrumentCategory || ''),
            sanitizeCsvField(acc.standardsSummary || '')
        ];
        rows.push(row.join(','));
    });

    const csvContent = rows.join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeName = projectName.toLowerCase().replace(/[^a-z0-9_-]/g, '_').replace(/_+/g, '_').slice(0, 40) || 'solution';
    link.href = url;
    link.download = `${safeName}_bom_${Date.now()}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/**
 * Copies text/JSON to clipboard.
 */
export async function copyJsonToClipboard(data: any): Promise<boolean> {
    try {
        const jsonString = JSON.stringify(data, null, 2);
        await navigator.clipboard.writeText(jsonString);
        return true;
    } catch (err) {
        console.error('Failed to copy to clipboard:', err);
        return false;
    }
}

export interface PDFExportOptions {
    maxItems?: number; // 0 for all, or 3, 5, etc.
}

/**
 * Generates and downloads a clean, professional multi-page PDF report
 * containing the complete User Input and Solution Workflow Output.
 */
export async function generateSolutionWorkflowPDF(
    exportData: SolutionWorkflowExportData,
    options?: PDFExportOptions
): Promise<void> {
    const { default: jsPDF } = await import('jspdf');

    const maxItems = options?.maxItems ?? 0;

    const doc = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4',
    });

    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margin = 16;
    const contentWidth = pageWidth - margin * 2;
    let yPos = margin;

    // Helper to sanitize markdown and control characters
    const cleanStr = (input: any): string => {
        if (input === null || input === undefined) return '';
        let s = String(input);
        s = s.replace(/<[^>]*>/g, '');
        s = s.replace(/\*\*/g, '');
        s = s.replace(/\*/g, '');
        s = s.replace(/_/g, '');
        s = s.replace(/`/g, '');
        s = s.replace(/#/g, '');
        s = s.replace(/~~/g, '');
        s = s.replace(/\r/g, '');
        return s.trim();
    };

    // Helper to check page bounds and auto-advance
    const ensureSpace = (requiredHeight: number) => {
        if (yPos + requiredHeight > pageHeight - margin - 12) {
            doc.addPage();
            yPos = margin + 8;
        }
    };

    // Helper to print text
    const addText = (
        text: string,
        fontSize: number = 10,
        isBold: boolean = false,
        indent: number = 0,
        color: [number, number, number] = [30, 41, 59] // slate-800
    ) => {
        const clean = cleanStr(text);
        if (!clean) return;

        doc.setFontSize(fontSize);
        doc.setFont('helvetica', isBold ? 'bold' : 'normal');
        doc.setTextColor(color[0], color[1], color[2]);

        const maxWidth = contentWidth - indent;
        const split = doc.splitTextToSize(clean, maxWidth);
        const textHeight = split.length * (fontSize * 0.38) + 1.5;

        ensureSpace(textHeight);
        doc.text(split, margin + indent, yPos);
        yPos += textHeight;
    };

    // Helper for Section Headers
    const addSectionHeader = (title: string, subtitle?: string) => {
        ensureSpace(18);
        yPos += 4;

        // Section Accent Line
        doc.setFillColor(15, 108, 189); // Primary Blue #0F6CBD
        doc.roundedRect(margin, yPos, 3, 7, 0.5, 0.5, 'F');

        doc.setFontSize(13);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(15, 23, 42); // slate-900
        doc.text(title, margin + 6, yPos + 5.5);

        yPos += 9;

        if (subtitle) {
            doc.setFontSize(8.5);
            doc.setFont('helvetica', 'normal');
            doc.setTextColor(100, 116, 139); // slate-500
            doc.text(subtitle, margin + 6, yPos);
            yPos += 4.5;
        }

        // Dividing line
        doc.setDrawColor(226, 232, 240); // slate-200
        doc.setLineWidth(0.3);
        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 4;
    };

    // Helper for Card Containers
    const drawCard = (height: number, fillColor: [number, number, number] = [248, 250, 252], borderColor: [number, number, number] = [226, 232, 240]) => {
        doc.setFillColor(fillColor[0], fillColor[1], fillColor[2]);
        doc.setDrawColor(borderColor[0], borderColor[1], borderColor[2]);
        doc.setLineWidth(0.3);
        doc.roundedRect(margin, yPos, contentWidth, height, 2, 2, 'FD');
    };

    // ──────────────────────────────────────────────────────────────────────────
    // 1. TOP COVER / HEADER BANNER
    // ──────────────────────────────────────────────────────────────────────────
    // Top Color Accent Bar
    doc.setFillColor(15, 108, 189);
    doc.rect(0, 0, pageWidth, 5, 'F');

    yPos = 14;

    // Organization & Platform Header
    doc.setFontSize(9);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(15, 108, 189);
    doc.text('ENGINEERING SOLUTION WORKFLOW', margin, yPos);

    yPos += 7;

    // Document Title
    const projTitle = exportData.projectName || 'Engineering Solution Architecture';
    doc.setFontSize(18);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(15, 23, 42);
    const titleLines = doc.splitTextToSize(projTitle, contentWidth);
    doc.text(titleLines, margin, yPos);
    yPos += titleLines.length * 7 + 2;

    // Subtitle
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(100, 116, 139);
    doc.text('Comprehensive Input Requirements & Output Bill of Materials Report', margin, yPos);
    yPos += 6;

    // Metadata Summary Box
    const metadataHeight = 16;
    drawCard(metadataHeight, [241, 245, 249], [203, 213, 225]);

    const formattedDate = new Date(exportData.exportedAt || Date.now()).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
    });

    doc.setFontSize(8.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(51, 65, 85);
    doc.text(`Generated:`, margin + 4, yPos + 6);
    doc.setFont('helvetica', 'normal');
    doc.text(formattedDate, margin + 22, yPos + 6);

    doc.setFont('helvetica', 'bold');
    doc.text(`Scope:`, margin + 68, yPos + 6);
    doc.setFont('helvetica', 'normal');
    doc.text(`${exportData.summary.totalInstruments} Instruments · ${exportData.summary.totalAccessories} Accessories`, margin + 80, yPos + 6);

    doc.setFont('helvetica', 'bold');
    doc.text(`Standards:`, margin + 4, yPos + 12);
    doc.setFont('helvetica', 'normal');
    doc.text(exportData.summary.standardsApplied ? 'Applied (Industry Rules)' : 'Skipped', margin + 22, yPos + 12);

    doc.setFont('helvetica', 'bold');
    doc.text(`Workflow:`, margin + 68, yPos + 12);
    doc.setFont('helvetica', 'normal');
    doc.text(exportData.workflow || 'solution_workflow', margin + 84, yPos + 12);

    yPos += metadataHeight + 8;

    // ──────────────────────────────────────────────────────────────────────────
    // 2. SECTION: USER INPUT DATA
    // ──────────────────────────────────────────────────────────────────────────
    addSectionHeader('1. USER INPUT DATA & REQUIREMENTS', 'Initial engineering requirements, constraints, and configuration parameters.');

    // User Requirements Card
    const reqText = exportData.inputData?.userRequirements || 'No requirements text supplied.';
    doc.setFontSize(9.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(15, 23, 42);
    doc.text('Submitted Technical Requirements:', margin, yPos);
    yPos += 4;

    doc.setFontSize(9);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(51, 65, 85);
    const splitReq = doc.splitTextToSize(cleanStr(reqText), contentWidth - 8);
    const reqCardHeight = splitReq.length * 4.2 + 8;

    ensureSpace(reqCardHeight);
    drawCard(reqCardHeight, [248, 250, 252], [226, 232, 240]);
    doc.text(splitReq, margin + 4, yPos + 5.5);
    yPos += reqCardHeight + 5;

    // ──────────────────────────────────────────────────────────────────────────
    // 2. SECTION: SOLUTION ARCHITECTURE & DESIGN OVERVIEW (OUTPUT)
    // ──────────────────────────────────────────────────────────────────────────
    const designedSol = exportData.outputData?.designedSolution;
    const assistantMsg = exportData.outputData?.assistantMessage || exportData.outputData?.summary || '';

    addSectionHeader('2. SOLUTION ARCHITECTURE & ENGINEERING NARRATIVE', 'Synthesized system design, functional roles, and process optimizations.');

    // Assistant Executive Message
    if (assistantMsg) {
        doc.setFontSize(9.5);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(15, 23, 42);
        doc.text('AI Engineering Assessment & Synthesis:', margin, yPos);
        yPos += 4;

        const cleanMsg = cleanStr(assistantMsg);
        const splitMsg = doc.splitTextToSize(cleanMsg, contentWidth - 8);
        const msgHeight = splitMsg.length * 4.2 + 8;

        ensureSpace(msgHeight);
        drawCard(msgHeight, [240, 249, 255], [186, 230, 253]); // Sky blue accent
        doc.setFontSize(9);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(12, 74, 110); // Sky-900
        doc.text(splitMsg, margin + 4, yPos + 5.5);
        yPos += msgHeight + 5;
    }

    // Project Objective & Design Overview
    if (designedSol?.projectObjective) {
        addText('Project Objective:', 9.5, true, 0, [15, 23, 42]);
        addText(designedSol.projectObjective, 9, false, 4, [51, 65, 85]);
        yPos += 2;
    }

    if (designedSol?.designOverview) {
        addText('Design Overview:', 9.5, true, 0, [15, 23, 42]);
        addText(designedSol.designOverview, 9, false, 4, [51, 65, 85]);
        yPos += 2;
    }

    // Component Roles
    if (designedSol?.componentRoles && designedSol.componentRoles.length > 0) {
        ensureSpace(12);
        addText('System Component Functional Roles:', 9.5, true, 0, [15, 23, 42]);
        designedSol.componentRoles.forEach((role: any) => {
            const roleTitle = `• ${role.name || role.category || 'Component'}${role.category && role.name !== role.category ? ` (${role.category})` : ''}:`;
            addText(roleTitle, 8.5, true, 4, [15, 108, 189]);
            addText(role.purpose || role.description || '', 8.5, false, 8, [71, 85, 105]);
        });
        yPos += 2;
    }

    // Optimizations
    if (designedSol?.optimizations && designedSol.optimizations.length > 0) {
        ensureSpace(12);
        addText('Process & Safety Optimizations:', 9.5, true, 0, [15, 23, 42]);
        designedSol.optimizations.forEach((opt: string) => {
            addText(`• ${opt}`, 8.5, false, 4, [51, 65, 85]);
        });
        yPos += 2;
    }

    // Design Considerations & Assumptions
    if (designedSol?.designConsiderations && designedSol.designConsiderations.length > 0) {
        ensureSpace(12);
        addText('Design Considerations:', 9.5, true, 0, [15, 23, 42]);
        designedSol.designConsiderations.forEach((dc: string) => {
            addText(`• ${dc}`, 8.5, false, 4, [51, 65, 85]);
        });
        yPos += 2;
    }

    if (designedSol?.assumptions && designedSol.assumptions.length > 0) {
        ensureSpace(12);
        addText('Engineering Assumptions:', 9.5, true, 0, [15, 23, 42]);
        designedSol.assumptions.forEach((assump: string) => {
            addText(`• ${assump}`, 8.5, false, 4, [51, 65, 85]);
        });
        yPos += 2;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // 4. SECTION: IDENTIFIED INSTRUMENTS (OUTPUT BOM)
    // ──────────────────────────────────────────────────────────────────────────
    const allInstruments = exportData.outputData?.instruments || [];
    const instruments = (maxItems > 0 && maxItems < allInstruments.length)
        ? allInstruments.slice(0, maxItems)
        : allInstruments;
    const instCountLabel = allInstruments.length > instruments.length
        ? `TOP ${instruments.length} OF ${allInstruments.length} ITEMS`
        : `${instruments.length} ITEMS`;
    addSectionHeader(`3. IDENTIFIED INSTRUMENTS (${instCountLabel})`, 'Detailed instrument specifications, quantities, standards compliance, and vendors.');

    if (instruments.length === 0) {
        addText('No instruments identified for this workflow run.', 9, false, 4, [100, 116, 139]);
    } else {
        instruments.forEach((inst, index) => {
            ensureSpace(28);

            const cat = inst.category || 'Instrument';
            const name = inst.productName || inst.name || cat;
            const qty = inst.quantity ? ` (Quantity: ${inst.quantity})` : '';

            // Item Title
            addText(`${index + 1}. ${name}${qty}`, 10.5, true, 0, [15, 108, 189]);
            addText(`Category: ${cat}`, 8.5, false, 4, [100, 116, 139]);

            // Specifications
            if (inst.specifications && Object.keys(inst.specifications).length > 0) {
                addText('Specifications:', 8.5, true, 4, [51, 65, 85]);
                Object.entries(inst.specifications).forEach(([k, v]) => {
                    addText(`• ${k}: ${String(v)}`, 8, false, 8, [71, 85, 105]);
                });
            }

            // Applicable Standards
            if (inst.applicableStandards && inst.applicableStandards.length > 0) {
                const stdsStr = Array.isArray(inst.applicableStandards) ? inst.applicableStandards.join(', ') : String(inst.applicableStandards);
                addText(`Applicable Standards: ${stdsStr}`, 8.5, true, 4, [16, 116, 139]);
            }
            if (inst.standardsSummary) {
                addText(`Standards Summary: ${inst.standardsSummary}`, 8, false, 6, [71, 85, 105]);
            }

            // Sourcing & Vendors
            if (inst.specifiedVendors && inst.specifiedVendors.length > 0) {
                const vStr = Array.isArray(inst.specifiedVendors) ? inst.specifiedVendors.join(', ') : String(inst.specifiedVendors);
                addText(`Specified Vendors: ${vStr}`, 8.5, false, 4, [51, 65, 85]);
            }
            if (inst.specifiedModelFamilies && inst.specifiedModelFamilies.length > 0) {
                const mStr = Array.isArray(inst.specifiedModelFamilies) ? inst.specifiedModelFamilies.join(', ') : String(inst.specifiedModelFamilies);
                addText(`Model Families: ${mStr}`, 8.5, false, 4, [51, 65, 85]);
            }
            if (inst.strategy) {
                addText(`Procurement Strategy: ${inst.strategy}`, 8, false, 4, [100, 116, 139]);
            }

            yPos += 3;
        });
    }

    // ──────────────────────────────────────────────────────────────────────────
    // 5. SECTION: IDENTIFIED ACCESSORIES (OUTPUT BOM)
    // ──────────────────────────────────────────────────────────────────────────
    const accessories = exportData.outputData?.accessories || [];
    addSectionHeader(`4. IDENTIFIED ACCESSORIES (${accessories.length} ITEMS)`, 'Complementary manifolds, mounting brackets, thermowells, and cabling.');

    if (accessories.length === 0) {
        addText('No accessories identified for this workflow run.', 9, false, 4, [100, 116, 139]);
    } else {
        accessories.forEach((acc, index) => {
            ensureSpace(22);

            const cat = acc.category || 'Accessory';
            const name = acc.accessoryName || acc.name || cat;
            const qty = acc.quantity ? ` (Quantity: ${acc.quantity})` : '';

            addText(`${index + 1}. ${name}${qty}`, 10, true, 0, [5, 150, 105]); // Emerald green
            if (acc.parentInstrumentCategory) {
                addText(`Parent Instrument: ${acc.parentInstrumentCategory}`, 8.5, false, 4, [100, 116, 139]);
            }

            // Specifications
            if (acc.specifications && Object.keys(acc.specifications).length > 0) {
                addText('Specifications:', 8.5, true, 4, [51, 65, 85]);
                Object.entries(acc.specifications).forEach(([k, v]) => {
                    addText(`• ${k}: ${String(v)}`, 8, false, 8, [71, 85, 105]);
                });
            }

            // Standards & Vendors
            if (acc.applicableStandards && acc.applicableStandards.length > 0) {
                const stdsStr = Array.isArray(acc.applicableStandards) ? acc.applicableStandards.join(', ') : String(acc.applicableStandards);
                addText(`Applicable Standards: ${stdsStr}`, 8.5, true, 4, [16, 116, 139]);
            }
            if (acc.specifiedVendors && acc.specifiedVendors.length > 0) {
                const vStr = Array.isArray(acc.specifiedVendors) ? acc.specifiedVendors.join(', ') : String(acc.specifiedVendors);
                addText(`Vendors: ${vStr}`, 8.5, false, 4, [51, 65, 85]);
            }

            yPos += 2.5;
        });
    }

    // ──────────────────────────────────────────────────────────────────────────
    // 6. SECTION: P&ID PROCESS SCHEMATIC (OUTPUT)
    // ──────────────────────────────────────────────────────────────────────────
    const pidGraph = designedSol?.pidGraph || designedSol?.pid_graph;
    if (pidGraph) {
        addSectionHeader('5. P&ID PROCESS SCHEMATIC & TOPOLOGY', 'Instrumentation tag nodes, piping lines, and process subsystem areas.');

        const pType = (pidGraph.projectType || pidGraph.project_type || 'greenfield').toUpperCase();
        const nodeCount = pidGraph.nodes?.length || 0;
        const edgeCount = pidGraph.edges?.length || 0;

        addText(`Process Topology Classification: ${pType} (${nodeCount} Elements, ${edgeCount} Process Lines)`, 9.5, true, 0, [15, 23, 42]);

        if (pidGraph.summary) {
            addText(`Schematic Summary: ${pidGraph.summary}`, 8.5, false, 4, [71, 85, 105]);
        }

        const subAreas = pidGraph.subsystemAreas || pidGraph.subsystem_areas || [];
        if (subAreas.length > 0) {
            ensureSpace(12);
            addText('Process Subsystem Areas:', 9, true, 4, [51, 65, 85]);
            subAreas.forEach((area: any) => {
                addText(`• ${area.name || area.id}`, 8.5, false, 8, [15, 108, 189]);
            });
        }

        if (pidGraph.nodes && pidGraph.nodes.length > 0) {
            ensureSpace(15);
            addText('Tagged Elements:', 9, true, 4, [51, 65, 85]);
            const tags = pidGraph.nodes.map((n: any) => `${n.label || n.id} (${n.kind || 'instrument'})`).join('; ');
            addText(tags, 8, false, 8, [71, 85, 105]);
        }
        yPos += 3;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // 7. FOOTER & PAGE NUMBERING ON ALL PAGES
    // ──────────────────────────────────────────────────────────────────────────
    const totalPages = doc.internal.pages.length - 1;
    for (let i = 1; i <= totalPages; i++) {
        doc.setPage(i);

        // Header (pages after page 1)
        if (i > 1) {
            doc.setFontSize(7.5);
            doc.setFont('helvetica', 'normal');
            doc.setTextColor(148, 163, 184); // slate-400
            doc.text(`Solution Workflow Report • ${cleanStr(projTitle)}`, margin, 10);
            doc.setDrawColor(226, 232, 240);
            doc.setLineWidth(0.2);
            doc.line(margin, 12, pageWidth - margin, 12);
        }

        // Footer
        doc.setDrawColor(226, 232, 240);
        doc.setLineWidth(0.2);
        doc.line(margin, pageHeight - 12, pageWidth - margin, pageHeight - 12);

        doc.setFontSize(7.5);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(148, 163, 184);
        doc.text('Generated by Engineering Platform • Confidential & Proprietary', margin, pageHeight - 7);
        doc.text(`Page ${i} of ${totalPages}`, pageWidth - margin - 18, pageHeight - 7);
    }

    // Trigger Browser Download
    const safeProjectName = (exportData.projectName || 'solution')
        .toLowerCase()
        .replace(/[^a-z0-9_-]/g, '_')
        .replace(/_+/g, '_')
        .slice(0, 35);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

    doc.save(`solution_workflow_${safeProjectName}_${timestamp}.pdf`);
}

// ============================================================================
// SEARCH WORKFLOW EXPORT UTILITIES
// ============================================================================

export interface SearchWorkflowExportData {
    workflow: string;
    version: string;
    exportedAt: string;
    productType: string;
    projectName?: string;
    sessionId?: string | null;
    summary: {
        totalRankedProducts: number;
        totalVendorsAnalyzed: number;
        standardsApplied: boolean;
        currentStep?: string;
    };
    inputData: {
        productType: string;
        userQuery: string;
        collectedSpecifications: Record<string, any>;
        vendorPreferences?: {
            specifiedVendors?: string[];
            specifiedModelFamilies?: string[];
            strategy?: string;
        };
        standardsEnabled: boolean;
        conversationHistory: {
            role: string;
            content: string;
            timestamp?: string;
        }[];
        workflowConfiguration?: {
            searchInstanceId?: string | null;
            standardsEnabled: boolean;
        };
    };
    outputData: {
        validationResult?: {
            isComplete: boolean;
            productType?: string;
            detectedSchema?: Record<string, any>;
            providedRequirements?: Record<string, any>;
        } | null;
        analysisResult?: {
            markdownAnalysis?: string;
            rankedProducts: Array<{
                rank: number;
                vendor: string;
                productName: string;
                overallScore?: number;
                matchScore?: number;
                keyStrengths?: string;
                concerns?: string;
                reasoning?: string;
                limitations?: string;
                requirementsMatch?: boolean;
                modelFamily?: string;
            }>;
            vendorMatches?: Array<any>;
            analysisMetadata?: Record<string, any>;
        } | null;
        assistantMessage?: string;
    };
}

export interface BuildSearchExportParams {
    productType?: string;
    projectName?: string;
    sessionId?: string | null;
    userQuery?: string;
    collectedData?: Record<string, any>;
    validationResult?: any;
    analysisResult?: any;
    chatMessages?: any[];
    standardsEnabled?: boolean;
    currentStep?: string;
    searchInstanceId?: string | null;
}

/**
 * Builds structured search workflow export data.
 */
export function buildSearchWorkflowExport(params: BuildSearchExportParams): SearchWorkflowExportData {
    const {
        productType = 'Industrial Instrument',
        projectName = productType || 'Search Project',
        sessionId = null,
        userQuery = '',
        collectedData = {},
        validationResult = null,
        analysisResult = null,
        chatMessages = [],
        standardsEnabled = true,
        currentStep = 'finalAnalysis',
        searchInstanceId = null,
    } = params;

    // Find the first user message if userQuery is not explicitly given
    let derivedUserQuery = userQuery;
    if (!derivedUserQuery && chatMessages.length > 0) {
        const firstUser = chatMessages.find(m => m.type === 'user');
        if (firstUser) derivedUserQuery = firstUser.content || '';
    }

    const conversationHistory = chatMessages.map((msg) => ({
        role: msg.type === 'user' ? 'user' : 'assistant',
        content: msg.content || '',
        timestamp: msg.timestamp ? new Date(msg.timestamp).toISOString() : undefined,
    }));

    const rankedProducts = analysisResult?.overallRanking?.rankedProducts || [];
    const totalVendors = analysisResult?.analysisMetadata?.totalVendorsAnalyzed ||
        new Set(rankedProducts.map((p: any) => p.vendor).filter(Boolean)).size ||
        (analysisResult?.vendorAnalysis?.vendorMatches ? new Set(analysisResult.vendorAnalysis.vendorMatches.map((m: any) => m.vendor)).size : 0);

    const assistantMessage = analysisResult?.message ||
        chatMessages.filter(m => m.type === 'assistant').slice(-1)[0]?.content ||
        '';

    const cleanRankedProducts = rankedProducts.map((p: any, idx: number) => ({
        rank: p.rank || idx + 1,
        vendor: p.vendor || 'Unknown Vendor',
        productName: p.productName || p.name || 'Product',
        overallScore: p.overallScore ?? p.matchScore,
        matchScore: p.matchScore,
        keyStrengths: p.keyStrengths || '',
        concerns: p.concerns || '',
        reasoning: p.reasoning || '',
        limitations: p.limitations || '',
        requirementsMatch: p.requirementsMatch ?? true,
        modelFamily: p.modelFamily || '',
    }));

    const hasStandards = Boolean(
        standardsEnabled ||
        (validationResult as any)?.applicableStandards?.length ||
        (validationResult as any)?.applicable_standards?.length ||
        (analysisResult as any)?.applicable_standards?.length ||
        (analysisResult as any)?.applicableStandards?.length ||
        (collectedData && Object.values(collectedData).some((v: any) => typeof v === 'string' && v.includes('(STANDARD)')))
    );

    return {
        workflow: 'search_workflow',
        version: '1.0',
        exportedAt: new Date().toISOString(),
        productType: productType,
        projectName: projectName,
        sessionId: sessionId || searchInstanceId,
        summary: {
            totalRankedProducts: cleanRankedProducts.length,
            totalVendorsAnalyzed: totalVendors,
            standardsApplied: hasStandards,
            currentStep: currentStep,
        },
        inputData: {
            productType: productType,
            userQuery: derivedUserQuery,
            collectedSpecifications: collectedData || {},
            vendorPreferences: {
                specifiedVendors: validationResult?.specifiedVendors || [],
                specifiedModelFamilies: validationResult?.specifiedModelFamilies || [],
                strategy: validationResult?.strategy || '',
            },
            standardsEnabled: hasStandards,
            conversationHistory: conversationHistory,
            workflowConfiguration: {
                searchInstanceId: searchInstanceId,
                standardsEnabled: hasStandards,
            },
        },
        outputData: {
            validationResult: validationResult ? {
                isComplete: validationResult.isComplete ?? true,
                productType: validationResult.productType || productType,
                detectedSchema: validationResult.detectedSchema,
                providedRequirements: validationResult.providedRequirements || {},
            } : null,
            analysisResult: {
                markdownAnalysis: analysisResult?.overallRanking?.markdownAnalysis || '',
                rankedProducts: cleanRankedProducts,
                vendorMatches: analysisResult?.vendorAnalysis?.vendorMatches || [],
                analysisMetadata: analysisResult?.analysisMetadata || {},
            },
            assistantMessage: assistantMessage,
        },
    };
}

/**
 * Downloads Search ranked products as a CSV spreadsheet.
 */
export function downloadSearchBOMCsv(rankedProducts: any[], productType: string = 'search'): void {
    const escapeCell = (val: any): string => {
        if (val === null || val === undefined) return '""';
        const str = String(val).replace(/"/g, '""');
        return `"${str}"`;
    };

    const headers = [
        'Rank',
        'Vendor',
        'Product / Model Name',
        'Score',
        'Requirements Match',
        'Key Strengths',
        'Concerns & Limitations',
        'Engineering Evaluation',
    ];

    const rows: string[] = [headers.map(escapeCell).join(',')];

    rankedProducts.forEach((p, idx) => {
        rows.push([
            escapeCell(p.rank || idx + 1),
            escapeCell(p.vendor || ''),
            escapeCell(p.productName || p.name || ''),
            escapeCell(p.overallScore !== undefined ? `${p.overallScore}%` : (p.matchScore !== undefined ? `${p.matchScore}%` : '')),
            escapeCell(p.requirementsMatch ? 'Yes' : 'Partial / No'),
            escapeCell(p.keyStrengths || ''),
            escapeCell(p.concerns || p.limitations || ''),
            escapeCell(p.reasoning || ''),
        ].join(','));
    });

    const csvContent = rows.join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const safeName = productType.toLowerCase().replace(/[^a-z0-9_-]/g, '_').replace(/_+/g, '_').slice(0, 40) || 'search';
    link.href = url;
    link.download = `${safeName}_ranked_products_${Date.now()}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

/**
 * Extracts clean, concise bullet highlights from raw product fields.
 */
function extractProductHighlights(product: any): string[] {
    const raw = product.keyStrengths || product.key_strengths || product.strengths || product.highlights || product.pros || '';

    const cleanItem = (str: any): string => {
        if (!str) return '';
        let s = String(str);
        s = s.replace(/<[^>]*>/g, '');
        s = s.replace(/[*_`#~]/g, '');
        s = s.replace(/^[•\-\*\d\.\:\s]+/, '').trim();
        s = s.replace(/^(Key Strengths|Strengths|Highlights|Key Features|Pros|Advantages)\s*:\s*/i, '').trim();
        return s.trim();
    };

    if (Array.isArray(raw)) {
        const items = raw
            .map(item => cleanItem(typeof item === 'object' ? Object.values(item).join(' - ') : item))
            .filter(Boolean);
        if (items.length > 0) return items.slice(0, 3);
    }

    if (typeof raw === 'string' && raw.trim()) {
        const lines = raw
            .split(/[\n\r]+/)
            .map(cleanItem)
            .filter(line => line.length > 3 && !line.toLowerCase().startsWith('key strength') && !line.toLowerCase().startsWith('strengths'));
        if (lines.length > 0) {
            return lines.slice(0, 3);
        }

        // Split single paragraph by sentences
        const sentences = raw
            .split(/(?<=[.!?])\s+/)
            .map(cleanItem)
            .filter(s => s.length > 5);
        if (sentences.length > 0) {
            return sentences.slice(0, 3);
        }
    }

    // Fallback to first concise clause from reasoning
    if (product.reasoning) {
        const firstClause = cleanItem(String(product.reasoning).split(/[.\n]/)[0]);
        if (firstClause && firstClause.length > 5) {
            return [firstClause.slice(0, 120)];
        }
    }

    return ['Meets process and technical specifications for this equipment category.'];
}

/**
 * Generates and downloads a clean, professional multi-page PDF report
 * for the Search / Vendor Selection workflow containing ONLY:
 * 1. User Input & Process Specifications
 * 2. Ranked Vendor Recommendations (Score + Small Highlight Points)
 */
export async function generateSearchWorkflowPDF(
    exportData: SearchWorkflowExportData,
    options?: PDFExportOptions
): Promise<void> {
    const { default: jsPDF } = await import('jspdf');

    const maxItems = options?.maxItems ?? 5;

    const doc = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4',
    });

    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margin = 14;
    const contentWidth = pageWidth - margin * 2;
    let yPos = margin;

    const cleanStr = (input: any): string => {
        if (input === null || input === undefined) return '';
        let s = String(input);
        s = s.replace(/<[^>]*>/g, '');
        s = s.replace(/[*_`#~]/g, '');
        s = s.replace(/\r/g, '');
        return s.trim();
    };

    const ensureSpace = (requiredHeight: number) => {
        if (yPos + requiredHeight > pageHeight - margin - 10) {
            doc.addPage();
            yPos = margin + 6;
        }
    };

    const addText = (
        text: string,
        fontSize: number = 8.5,
        isBold: boolean = false,
        indent: number = 0,
        color: [number, number, number] = [30, 41, 59]
    ) => {
        const clean = cleanStr(text);
        if (!clean) return;

        doc.setFontSize(fontSize);
        doc.setFont('helvetica', isBold ? 'bold' : 'normal');
        doc.setTextColor(color[0], color[1], color[2]);

        const maxWidth = contentWidth - indent;
        const split = doc.splitTextToSize(clean, maxWidth);
        const textHeight = split.length * (fontSize * 0.36) + 1.2;

        ensureSpace(textHeight);
        doc.text(split, margin + indent, yPos);
        yPos += textHeight;
    };

    const addSectionHeader = (title: string) => {
        ensureSpace(14);
        yPos += 3;

        doc.setFillColor(15, 108, 189); // Primary Blue #0F6CBD
        doc.roundedRect(margin, yPos, 3, 6, 0.5, 0.5, 'F');

        doc.setFontSize(11);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(15, 23, 42);
        doc.text(title, margin + 5, yPos + 4.8);

        yPos += 7;
        doc.setDrawColor(226, 232, 240);
        doc.setLineWidth(0.3);
        doc.line(margin, yPos, pageWidth - margin, yPos);
        yPos += 3.5;
    };

    const drawCard = (height: number, fillColor: [number, number, number] = [248, 250, 252], borderColor: [number, number, number] = [226, 232, 240]) => {
        doc.setFillColor(fillColor[0], fillColor[1], fillColor[2]);
        doc.setDrawColor(borderColor[0], borderColor[1], borderColor[2]);
        doc.setLineWidth(0.3);
        doc.roundedRect(margin, yPos, contentWidth, height, 1.5, 1.5, 'FD');
    };

    // ──────────────────────────────────────────────────────────────────────────
    // 1. TOP HEADER & METADATA
    // ──────────────────────────────────────────────────────────────────────────
    doc.setFillColor(15, 108, 189);
    doc.rect(0, 0, pageWidth, 4, 'F');

    yPos = 12;

    doc.setFontSize(8);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(15, 108, 189);
    doc.text('PRODUCT SPECIFICATIONS & VENDOR RECOMMENDATION REPORT', margin, yPos);

    yPos += 6;

    const prodTitle = exportData.productType || exportData.projectName || 'Industrial Equipment Search';
    doc.setFontSize(16);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(15, 23, 42);
    const titleLines = doc.splitTextToSize(prodTitle, contentWidth);
    doc.text(titleLines, margin, yPos);
    yPos += titleLines.length * 6.5 + 2;

    // Metadata Bar
    const formattedDate = new Date(exportData.exportedAt || Date.now()).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short',
    });

    const metaHeight = 11;
    drawCard(metaHeight, [241, 245, 249], [203, 213, 225]);
    doc.setFontSize(8);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(51, 65, 85);
    doc.text(`Generated:`, margin + 3, yPos + 5);
    doc.setFont('helvetica', 'normal');
    doc.text(formattedDate, margin + 20, yPos + 5);

    const allRankedProducts = exportData.outputData?.analysisResult?.rankedProducts || [];
    const rankedProducts = (maxItems > 0 && maxItems < allRankedProducts.length)
        ? allRankedProducts.slice(0, maxItems)
        : allRankedProducts;

    doc.setFont('helvetica', 'bold');
    doc.text(`Ranked Options:`, margin + 65, yPos + 5);
    doc.setFont('helvetica', 'normal');
    const totalCount = exportData.summary.totalRankedProducts || allRankedProducts.length;
    const rankedBadge = (maxItems > 0 && totalCount > rankedProducts.length)
        ? `Top ${rankedProducts.length} of ${totalCount} Models`
        : `${totalCount} Recommended Models`;
    doc.text(rankedBadge, margin + 92, yPos + 5);

    doc.setFont('helvetica', 'bold');
    doc.text(`Standards:`, margin + 140, yPos + 5);
    doc.setFont('helvetica', 'normal');
    doc.text(exportData.summary.standardsApplied ? 'Applied' : 'Not Specified', margin + 158, yPos + 5);

    yPos += metaHeight + 6;

    // ──────────────────────────────────────────────────────────────────────────
    // 2. SECTION 1: USER INPUT & TECHNICAL SPECIFICATIONS
    // ──────────────────────────────────────────────────────────────────────────
    addSectionHeader('1. USER INPUT & TECHNICAL SPECIFICATIONS');

    const userQuery = exportData.inputData?.userQuery || 'No search query text provided.';
    const splitQuery = doc.splitTextToSize(cleanStr(userQuery), contentWidth - 6);
    const queryCardHeight = splitQuery.length * 3.8 + 6;

    ensureSpace(queryCardHeight + 6);
    doc.setFontSize(8.5);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(15, 108, 189);
    doc.text('Submitted Requirements Query:', margin, yPos);
    yPos += 3.5;

    drawCard(queryCardHeight, [248, 250, 252], [226, 232, 240]);
    doc.setFontSize(8.5);
    doc.setFont('helvetica', 'normal');
    doc.setTextColor(51, 65, 85);
    doc.text(splitQuery, margin + 3, yPos + 4.5);
    yPos += queryCardHeight + 4;

    // Captured Technical Specifications (Clean Key-Value parameters)
    const collectedSpecs = exportData.inputData?.collectedSpecifications || {};
    const specEntries = Object.entries(collectedSpecs).filter(([_, v]) => v !== undefined && v !== null && v !== '');

    if (specEntries.length > 0) {
        ensureSpace(14);
        doc.setFontSize(8.5);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(15, 23, 42);
        doc.text('Captured Technical Parameters:', margin, yPos);
        yPos += 3.5;

        // Render clean bulleted spec rows
        specEntries.forEach(([key, val]) => {
            const formattedKey = key.replace(/([A-Z])/g, ' $1').replace(/[._]/g, ' ').trim();
            const valStr = typeof val === 'object' ? JSON.stringify(val) : String(val);
            addText(`• ${formattedKey}: ${cleanStr(valStr)}`, 8, false, 3, [51, 65, 85]);
        });
        yPos += 3;
    }

    // Vendor Preferences (if specified)
    const vendorPrefs = exportData.inputData?.vendorPreferences;
    if (vendorPrefs && ((vendorPrefs.specifiedVendors && vendorPrefs.specifiedVendors.length > 0) || vendorPrefs.strategy)) {
        ensureSpace(10);
        if (vendorPrefs.specifiedVendors && vendorPrefs.specifiedVendors.length > 0) {
            addText(`• Preferred Vendors: ${vendorPrefs.specifiedVendors.join(', ')}`, 8, false, 3, [71, 85, 105]);
        }
        if (vendorPrefs.strategy) {
            addText(`• Sourcing Strategy: ${vendorPrefs.strategy}`, 8, false, 3, [71, 85, 105]);
        }
        yPos += 2;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // 3. SECTION 2: RANKED VENDOR RECOMMENDATIONS (OUTPUT)
    // ──────────────────────────────────────────────────────────────────────────
    const sectionRankCount = (maxItems > 0 && allRankedProducts.length > rankedProducts.length)
        ? `TOP ${rankedProducts.length} OF ${allRankedProducts.length} OPTIONS`
        : `${rankedProducts.length} OPTIONS`;
    addSectionHeader(`2. RECOMMENDED PRODUCTS & RANKINGS (${sectionRankCount})`);

    if (rankedProducts.length === 0) {
        addText('No ranked vendor recommendations available for this query.', 8.5, false, 3, [100, 116, 139]);
    } else {
        const textWidth = contentWidth - 10;

        rankedProducts.forEach((product, index) => {
            const rankNum = product.rank || index + 1;
            const vendorName = cleanStr(product.vendor || 'Vendor');
            const prodName = cleanStr(product.productName || product.name || 'Product');
            const scoreVal = product.overallScore ?? product.matchScore;
            const scoreStr = scoreVal !== undefined && scoreVal !== null ? `${scoreVal}%` : '';

            // 1. Prepare Title Lines
            doc.setFontSize(9.5);
            doc.setFont('helvetica', 'bold');
            const titleFull = `Rank #${rankNum} · ${vendorName} — ${prodName}`;
            const titleAvailableWidth = scoreStr ? textWidth - 28 : textWidth;
            const splitTitle = doc.splitTextToSize(titleFull, titleAvailableWidth);
            const titleLineHeight = 4.0;
            const titleHeight = splitTitle.length * titleLineHeight;

            // 2. Prepare Match Status (clean standard ASCII text without unsupported glyphs)
            const matchStatus = product.requirementsMatch ? 'Meets Process Requirements' : 'Partial Specification Match';
            const matchColor: [number, number, number] = product.requirementsMatch ? [16, 185, 129] : [217, 119, 6];
            const statusHeight = 3.6;

            // 3. Prepare Highlights Lines with Exact Measurement
            const rawHighlights = extractProductHighlights(product);
            doc.setFontSize(8);
            doc.setFont('helvetica', 'normal');

            const preparedHighlights = rawHighlights.map((hl) => {
                const cleaned = cleanStr(hl);
                const split = doc.splitTextToSize(`• ${cleaned}`, textWidth);
                const height = split.length * 3.8;
                return { split, height };
            });

            const highlightsTotalHeight = preparedHighlights.reduce((acc, curr) => acc + curr.height + 1.2, 0);

            // 4. Calculate Exact Dynamic Card Height
            const topPadding = 4.0;
            const bottomPadding = 4.0;
            const spacingBetween = 2.5;
            const blockHeight = topPadding + titleHeight + spacingBetween + statusHeight + (preparedHighlights.length > 0 ? spacingBetween + highlightsTotalHeight : 0) + bottomPadding;

            // Ensure space on page (prevent split across pages)
            ensureSpace(blockHeight + 4);

            // Draw Card Box & Left Accent Bar
            drawCard(blockHeight, [255, 255, 255], [226, 232, 240]);
            doc.setFillColor(15, 108, 189);
            doc.roundedRect(margin, yPos, 2.5, blockHeight, 0.5, 0.5, 'F');

            // 5. Draw Title & Score Badge
            let currentCursorY = yPos + topPadding + 3.2;

            doc.setFontSize(9.5);
            doc.setFont('helvetica', 'bold');
            doc.setTextColor(15, 23, 42);
            doc.text(splitTitle, margin + 5, currentCursorY);

            if (scoreStr) {
                doc.setFontSize(8.5);
                doc.setFont('helvetica', 'bold');
                doc.setTextColor(15, 108, 189);
                doc.text(`Score: ${scoreStr}`, pageWidth - margin - 5, currentCursorY, { align: 'right' });
            }

            currentCursorY += (splitTitle.length - 1) * titleLineHeight + spacingBetween + 3.5;

            // Draw Match Status
            doc.setFontSize(7.5);
            doc.setFont('helvetica', 'bold');
            doc.setTextColor(matchColor[0], matchColor[1], matchColor[2]);
            doc.text(matchStatus, margin + 5, currentCursorY);

            currentCursorY += spacingBetween + 3.2;

            // Draw Highlights
            doc.setFontSize(8);
            doc.setFont('helvetica', 'normal');
            doc.setTextColor(51, 65, 85);
            preparedHighlights.forEach(({ split, height }) => {
                doc.text(split, margin + 5, currentCursorY);
                currentCursorY += height + 1.2;
            });

            // Advance yPos by exact card height plus spacing
            yPos += blockHeight + 3.5;
        });
    }

    // ──────────────────────────────────────────────────────────────────────────
    // 4. FOOTER & PAGE NUMBERING ON ALL PAGES
    // ──────────────────────────────────────────────────────────────────────────
    const totalPages = doc.internal.pages.length - 1;
    for (let i = 1; i <= totalPages; i++) {
        doc.setPage(i);

        if (i > 1) {
            doc.setFontSize(7.5);
            doc.setFont('helvetica', 'normal');
            doc.setTextColor(148, 163, 184);
            doc.text(`Product Search Report • ${cleanStr(prodTitle)}`, margin, 8);
            doc.setDrawColor(226, 232, 240);
            doc.setLineWidth(0.2);
            doc.line(margin, 10, pageWidth - margin, 10);
        }

        doc.setDrawColor(226, 232, 240);
        doc.setLineWidth(0.2);
        doc.line(margin, pageHeight - 10, pageWidth - margin, pageHeight - 10);

        doc.setFontSize(7.5);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(148, 163, 184);
        doc.text('Generated by Engineering Platform • Technical Recommendation Report', margin, pageHeight - 6);
        doc.text(`Page ${i} of ${totalPages}`, pageWidth - margin - 16, pageHeight - 6);
    }

    const safeName = (exportData.productType || exportData.projectName || 'search')
        .toLowerCase()
        .replace(/[^a-z0-9_-]/g, '_')
        .replace(/_+/g, '_')
        .slice(0, 35);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

    doc.save(`search_workflow_${safeName}_${timestamp}.pdf`);
}


