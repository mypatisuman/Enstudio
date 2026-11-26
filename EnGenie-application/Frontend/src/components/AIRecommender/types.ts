export interface ChatMessage {
  role: any;
  id: string;
  type: "user" | "assistant" | "feedback";
  content: string;
  timestamp: Date;
  metadata?: {
    productType?: string;
    validationResult?: ValidationResult;
    analysisResult?: AnalysisResult;
    examplePrompt?: string;
    vendorAnalysisComplete?: boolean;
    requirementSchema?: RequirementSchema | null;
    routerRedirect?: boolean;
    routerUrl?: string;
    routerTargetPage?: string;
    cacheConfirmation?: boolean;
    matchedProjects?: any[];
    projectId?: string;
  };
}

export interface ValidationResult {
  validationAlert: any;
  isComplete: boolean;
  detectedSchema?: Record<string, any>;
  providedRequirements: Record<string, any>;
  productType: string;
  // Vendor preference fields (extracted from user input)
  specifiedVendors?: string[];
  specifiedModelFamilies?: string[];
  strategy?: string;
  // Requirement schema returned by the validation sub-agent
  // (eliminates the need for a separate GET /schema call)
  requirementSchema?: RequirementSchema;
}
export interface StructuredRequirements {
  [requirement: string]: string | number | boolean | null;
}

export interface ProductMatch {
  productName: string;
  vendor: string;
  matchScore: number;
  requirementsMatch: boolean;
  reasoning: string;
  limitations: string;
  imageUrl?: string; // ✅ Product image URL for vendorMatches
  // New fields for enhanced image support
  topImage?: ProductImage;
  vendorLogo?: VendorLogo;
  allImages?: ProductImage[];
}

export interface VendorAnalysis {
  vendorMatches: ProductMatch[];
}

// ADD imageUrl HERE:
export interface RankedProduct {
  modelFamily: any;
  productType: string;
  rank: number;
  productName: string;
  vendor: string;
  overallScore: number;
  keyStrengths: string;
  concerns: string;
  requirementsMatch: boolean;
  imageUrl?: string; // ✅ Product image URL for rankedProducts
  // New fields for enhanced image support
  topImage?: ProductImage;
  vendorLogo?: VendorLogo;
  allImages?: ProductImage[];
}

export interface ComparisonTableRow {
  vendor: string;
  productName: string;
  modelFamily?: string;
  values: Record<string, string | null>;
}

export interface ComparisonTable {
  specKeys: string[];
  rows: ComparisonTableRow[];
}

export interface AnalysisResult {
  productType: string;
  vendorAnalysis: VendorAnalysis;
  overallRanking: {
    markdownAnalysis: any;
    rankedProducts: RankedProduct[];
  };
  comparisonTable?: ComparisonTable;
  message?: string;
  analysisMetadata?: {
    totalVendorsAnalyzed?: number;
    totalProductsFound?: number;
    standardsApplied?: string[];
    vendorFilterNote?: string;
    [key: string]: any;
  };
}

export interface RequirementSchema {
  [productType: string]: {
    mandatory?: Record<string, string>;
    optional?: Record<string, string>;
  } | Record<string, string>;
  // Three parallel tiers rendered on the left-side spec panel. All three come
  // camelCased from the backend response formatter.
  mandatoryRequirements?: Record<string, any>;
  optionalRequirements?: Record<string, any>;
  advancedRequirements?: Record<string, any>;
}

export interface AppState {
  messages: ChatMessage[];
  currentProductType: string | null;
  validationResult: ValidationResult | null;
  analysisResult: AnalysisResult | null;
  requirementSchema: RequirementSchema | null;
  isLoading: boolean;
  inputValue: string;
  productType?: string;
}

export interface UserCredentials {
  username: string;
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
}

// New types for step-based workflow
// New types for step-based workflow
export interface IntentClassificationResult {
  intent: "productRequirements" | "workflow";  // Simplified intents
  nextStep: "greeting" | "initialInput" | "awaitAdditionalAndLatestSpecs" | "awaitAdvancedSpecs" | "awaitAllSpecs" | "awaitMissingInfo" | "showSummary" | "finalAnalysis" | null;
  resumeWorkflow?: boolean;
}

export interface AgentResponse {
  content: string;
  nextStep?: string | null;
  maintainWorkflow?: boolean;
}

/**
 * Unified response from the single /api/search-agent endpoint.
 * This replaces separate calls to classifyIntent, validateRequirements,
 * generateAgentResponse, and getRequirementSchema.
 */
export interface SearchAgentResult {
  success: boolean;
  intent: string;
  message: string;
  nextStep?: string | null;
  streamId?: string;
  analysisResult?: AnalysisResult;
  comparisonTable?: ComparisonTable;

  // Validation fields (present when validation ran)
  productType?: string;
  requirementSchema?: RequirementSchema;
  mappedRequirements?: Record<string, any>;
  collectedData?: Record<string, any>;
  contextVersion?: number;
  contextUpdatedAt?: string;
  contextSummary?: string;
  contextSynced?: boolean;
  changeLog?: Array<Record<string, unknown>>;
  missingFields?: string[]; // legacy alias for missingMandatoryFields
  missingMandatoryFields?: string[];
  missingOptionalFields?: string[];
  missingAdvancedFields?: string[];
  missingFieldsFriendly?: string[];
  missingAdvancedFieldsFriendly?: string[];
  validationAlert?: any;
  specifiedVendors?: string[];
  specifiedModelFamilies?: string[];
  strategy?: string;
  schemaSource?: string;
  formattedRequirementsSummary?: string;

  // Search fields (present when full search executed)
  searchExecuted?: boolean;
  searchResults?: RankedProduct[];
  vendorMatches?: ProductMatch[];
  totalFound?: number;

  // Modification fields
  modifiedParams?: Record<string, any>;
  changesMade?: string[];

  // Flags
  resetComplete?: boolean;
  needsConfirmation?: boolean;
  requiresConfirmation?: boolean;  // alias used in router handling
  needsClarification?: boolean;
  routerNeeded?: boolean;
  status?: string;

  // Router fields (present when routerNeeded is true)
  routerTargetPage?: string;
  routerUrl?: string;
  routerRequiresRouting?: boolean;
  routerMessage?: string;
  confirmationMessage?: string;
  openingMessage?: string;
  declineMessage?: string;
  popupBlockedMessage?: string;

  // Standards fields
  standardSpecs?: Record<string, any>;
  standardSpecsSource?: string;
}

export type WorkflowStep =
  | "greeting"
  | "initialInput"
  | "awaitMissingInfo"
  | "awaitAdditionalAndLatestSpecs"
  | "awaitAdvancedSpecs"
  | "awaitAllSpecs"
  | "confirmAfterMissingInfo"
  | "showSummary"
  | "finalAnalysis"
  | "analysisError"
  | "default";

// Advanced Parameters types
export interface AdvancedParameter {
  name: string;
  value?: string;
  selected?: boolean;
}

export interface VendorParametersResult {
  vendor: string;
  parameters: string[];
  sourceUrl: string;
}

export interface AdvancedParametersResult {
  productType: string;
  vendorParameters: VendorParametersResult[];
  uniqueParameters: string[];
  totalVendorsSearched: number;
  totalUniqueParameters: number;
  fallback?: boolean;
}

export interface AdvancedParametersSelection {
  selectedParameters: Record<string, string>;
  explanation: string;
  friendlyResponse: string;
  totalSelected: number;
}

// Instrument Identification types
export interface IdentifiedInstrument {
  category: string;
  quantity?: number;
  productName: string;
  specifications: Record<string, string>;
  sampleInput: string;
  strategy?: string;
  specifiedVendors?: string[];
  specifiedModelFamilies?: string[];
  // Standards RAG fields (per-instrument)
  userSpecifiedStandards?: string[];  // Standards explicitly mentioned by user for THIS instrument
  skipStandards?: boolean;  // True if user said no standards for THIS instrument
  standardsSpecs?: Record<string, string>;  // Specifications extracted from standards document
  applicableStandards?: string[];  // List of applicable standard names
  standardsSummary?: string;  // Summary of standards requirements
  standardsSource?: 'user_specified' | 'document' | 'skipped_by_user' | 'none' | 'error';  // Where standards came from
}

export interface IdentifiedAccessory {
  category: string;
  quantity?: number;
  accessoryName: string;
  specifications: Record<string, string>;
  sampleInput: string;
  strategy?: string;
  specifiedVendors?: string[];
  specifiedModelFamilies?: string[];
  parentInstrumentCategory?: string;
  // Standards RAG fields (per-accessory)
  userSpecifiedStandards?: string[];  // Standards explicitly mentioned by user for THIS accessory
  skipStandards?: boolean;  // True if user said no standards for THIS accessory
  standardsSpecs?: Record<string, string>;  // Specifications extracted from standards document
  applicableStandards?: string[];  // List of applicable standard names
  standardsSummary?: string;  // Summary of standards requirements
  standardsSource?: 'user_specified' | 'document' | 'skipped_by_user' | 'none' | 'error';  // Where standards came from
}

export interface InstrumentIdentificationResult {
  // Response type indicator
  response_type?: 'greeting' | 'question' | 'requirements' | 'error';
  responseType?: 'greeting' | 'question' | 'requirements' | 'error';

  // For greeting and question responses
  message?: string;
  isIndustrial?: boolean;

  // For requirements response
  projectName?: string;
  instruments: IdentifiedInstrument[];
  accessories?: IdentifiedAccessory[];
  summary: string;

  // Standards RAG indicator
  standardsApplied?: boolean;

  // For error responses
  error?: string;
}

// Optimized engineering solution produced by the standalone parallel
// solution-build agent (returned alongside the BOM on the requirements path).
// Keys are camelCased by the backend response formatter.
export interface DesignedSolutionComponentRole {
  name: string;
  category: string;
  purpose: string;
}

export interface PIDNode {
  id: string;
  label: string;
  kind: string;
  description?: string;
  area?: string;
  subsystemId?: string;
  subsystem_id?: string;
  isTieIn?: boolean;
  is_tie_in?: boolean;
  tieInLabel?: string;
  tie_in_label?: string;
  specifications?: Record<string, any>;
  x?: number;
  y?: number;
}

export interface PIDEdge {
  from: string;
  to: string;
  kind: string;
  label?: string;
  fluid?: string;
  lineSize?: string;
}

export interface PIDLayoutCell {
  row: number;
  col: number;
  nodeId: string;
  tag: string;
}

export interface PIDSubsystemArea {
  id: string;
  name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  nodeIds: string[];
  node_ids?: string[];
}

export interface PIDLayout {
  rows: number;
  cols: number;
  cells: PIDLayoutCell[];
  subsystemAreas?: PIDSubsystemArea[];
  subsystem_areas?: PIDSubsystemArea[];
}

export interface PIDGraph {
  projectType?: 'greenfield' | 'brownfield';
  project_type?: 'greenfield' | 'brownfield';
  nodes: PIDNode[];
  edges: PIDEdge[];
  layout: PIDLayout;
  subsystemAreas?: PIDSubsystemArea[];
  subsystem_areas?: PIDSubsystemArea[];
  summary: string;
  svgPreview?: string;
  svg_preview?: string;
}

export interface DesignedSolution {
  projectObjective: string;
  designOverview: string;
  componentRoles: DesignedSolutionComponentRole[];
  optimizations: string[];
  designConsiderations: string[];
  assumptions: string[];
  pidGraph?: PIDGraph;
  pid_graph?: PIDGraph;
}

// New interfaces for refactored API structure
export interface ProjectIntentResult {
  success?: boolean;
  intent: 'requirements' | 'modification' | 'confirm_search' | 'add_more' | 'clarification' | 'reset' | 'reset_confirmed' | 'reset_cancelled' | 'router_needed' | 'error';
  confidence: 'high' | 'medium' | 'low';
  reasoning: string;
  // DEPRECATED: shouldCall is no longer used - solution agent handles everything internally
  shouldCall?: string;

  // Response data (returned by solution agent)
  responseType?: string;
  projectName?: string;
  message?: string;
  instruments?: IdentifiedInstrument[];
  accessories?: IdentifiedAccessory[];
  changesMade?: string[];
  summary?: string;

  // Optimized engineering solution from the parallel solution-build agent
  // (present on the requirements path; may be absent if design generation failed)
  designedSolution?: DesignedSolution;
  pidGraph?: PIDGraph;

  // Router redirect fields (for router_needed intent)
  routerCategory?: string;
  routerTargetPage?: string;
  routerRequiresRouting?: boolean;
  routerUrl?: string;
  routerMessage?: string;

  // Clarification fields
  clarificationNeeded?: boolean;
  clarificationQuestions?: string[];
  clarificationContext?: any;

  // Single item confirmation flow
  openDashboard?: boolean;
  sampleInput?: string;
  stillAwaitingConfirmation?: boolean;
  awaitingMoreRequirements?: boolean;
  awaitingConfirmation?: boolean;

  // Product info confirmation flow
  awaitingChatConfirmation?: boolean;
  originalQuery?: string;
  isSingleItemFlow?: boolean;
}

export interface ProjectResponseResult {
  responseType: 'greeting' | 'question' | 'unrelated';
  message: string;
  isIndustrial?: boolean;
  instructions?: IdentifiedInstrument[];
  accessories?: IdentifiedAccessory[];
  stillAwaitingConfirmation?: boolean;
}

// New interfaces for image API integration
export interface ProductImage {
  url: string;
  title: string;
  source: "google_cse" | "serpapi" | "serper";
  thumbnail: string;
  domain: string;
  searchType?: string;
  searchPriority?: number;
  relevanceScore?: number;
}

export interface VendorLogo {
  url: string;
  thumbnail: string;
  source: string;
  title?: string;
  domain?: string;
}

export interface AnalysisImageResult {
  vendor: string;
  productType: string;
  productName: string;
  modelFamilies: string[];
  topImage: ProductImage | null;
  vendorLogo: VendorLogo | null;
  allImages: ProductImage[];
  totalFound: number;
  uniqueCount: number;
  bestCount: number;
  searchSummary: {
    searchesPerformed: number;
    searchTypes: string[];
    sourcesUsed: string[];
  };
}
