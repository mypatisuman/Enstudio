import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import axios from "axios";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { debounce } from "lodash";
import { useSearchParams, useNavigate } from "react-router-dom";
import {
  AppState,
  ChatMessage,
  ValidationResult,
  AnalysisResult,
  RequirementSchema,
  WorkflowStep,
  SearchAgentResult,
  AdvancedParametersResult,
  AdvancedParametersSelection,
} from "./types";
import LeftSidebar from "./LeftSidebar";
import ChatInterface from "./ChatInterface";
import RightPanel from "./RightPanel";
import {
  callSearchAgent,
  waitForSearchResult,
  initializeNewSearch,
  getSearchContext,
  getAnalysisProductImages,
  classifyRoute,
  confirmRouteResponse,
// REMOVED: searchVendors import and call - vendor search is now fully handled in the backend workflow (Identify Vendors Agent)
} from "./api";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight, Cpu, Wrench } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import MainHeader from "@/components/MainHeader";
import DownloadSearchWorkflowDialog from "@/components/DownloadSearchWorkflowDialog";

type ConversationStep = WorkflowStep;

/** Flatten tiered mappedRequirements into dot-notation keys for sidebar collectedData. */
function flattenMappedRequirements(mappedReqs: Record<string, any> = {}): Record<string, any> {
  const flattenObject = (obj: any, prefix = ""): Record<string, any> =>
    Object.keys(obj || {}).reduce((acc: Record<string, any>, key: string) => {
      const fullKey = prefix ? `${prefix}.${key}` : key;
      if (obj[key] !== null && typeof obj[key] === "object" && !Array.isArray(obj[key])) {
        Object.assign(acc, flattenObject(obj[key], fullKey));
      } else {
        acc[fullKey] = obj[key];
      }
      return acc;
    }, {});

  return flattenObject(mappedReqs);
}

function resolveCollectedDataFromSearchResult(searchResult: SearchAgentResult): Record<string, any> {
  if (searchResult.collectedData && Object.keys(searchResult.collectedData).length > 0) {
    return searchResult.collectedData;
  }
  return flattenMappedRequirements(searchResult.mappedRequirements || {});
}

/** Apply backend SSOT context fields to local sidebar state. */
function syncContextFromSearchResult(
  searchResult: SearchAgentResult,
  prevCollected: Record<string, any>,
): Record<string, any> {
  const backendData = resolveCollectedDataFromSearchResult(searchResult);
  if (searchResult.contextVersion != null && Object.keys(backendData).length > 0) {
    return { ...prevCollected, ...backendData };
  }
  if (Object.keys(backendData).length > 0) {
    return { ...prevCollected, ...backendData };
  }
  return prevCollected;
}

// Vendor search parameters passed from Project page
interface VendorSearchParams {
  category: string;
  productName: string;
  strategy?: string;
  specifiedVendors?: string[];
  specifiedModelFamilies?: string[];
  applicableStandards?: string[];
  standardsSpecs?: Record<string, string>;
}

interface AIRecommenderProps {
  initialInput?: string;
  fillParent?: boolean;
  onStateChange?: (state: {
    messages: ChatMessage[];
    collectedData: { [key: string]: any };
    currentStep: ConversationStep;
    analysisResult: AnalysisResult | null;
    searchInstanceId: string;  // Instance ID for this specific search flow (renamed from searchInstanceId)
    // Extended state for complete restoration
    requirementSchema: RequirementSchema | null;
    validationResult: ValidationResult | null;
    currentProductType: string | null;
    inputValue: string;
    advancedParameters: AdvancedParametersResult | null;
    selectedAdvancedParams: { [key: string]: string };
    fieldDescriptions: Record<string, string>;
    pricingData: Record<string, any>;
    scrollPositions?: { left: number; center: number; right: number };
    dockingState?: { left: boolean; right: boolean };
    standardsEnabled?: boolean;
  }) => void;
  // Props for restoring saved state
  savedMessages?: ChatMessage[];
  savedCollectedData?: { [key: string]: any };
  savedCurrentStep?: ConversationStep;
  savedAnalysisResult?: AnalysisResult | null;
  // Extended saved state
  savedRequirementSchema?: RequirementSchema | null;
  savedValidationResult?: ValidationResult | null;
  savedCurrentProductType?: string | null;
  savedInputValue?: string;
  savedAdvancedParameters?: AdvancedParametersResult | null;
  savedSelectedAdvancedParams?: { [key: string]: string };
  savedFieldDescriptions?: Record<string, string>;
  savedPricingData?: Record<string, any>;
  savedScrollPositions?: { left: number; center: number; right: number };
  savedDockingState?: { left: boolean; right: boolean };
  savedSearchInstanceId?: string; // Instance ID for maintaining backend conversation context (renamed from savedsearchInstanceId)
  savedStandardsEnabled?: boolean; // Restored toggle state (survives tab switches / page refresh)
  // Callback for save functionality (used by standalone pages like /search)
  onSave?: () => void;
  // Vendor search parameters from Project page - triggers background search after validation
  vendorSearchParams?: VendorSearchParams;
}

// Track routing windows by target page for smart window management
// Same target page → reuse window, Different target page → new window
const routingWindows: Record<string, Window | null> = {};

const AIRecommender = ({
  initialInput,
  fillParent,
  onStateChange,
  savedMessages,
  savedCollectedData,
  savedCurrentStep,
  savedAnalysisResult,
  savedRequirementSchema,
  savedValidationResult,
  savedCurrentProductType,
  savedInputValue,
  savedAdvancedParameters,
  savedSelectedAdvancedParams,
  savedFieldDescriptions,
  savedPricingData,
  savedScrollPositions,
  savedDockingState,
  savedSearchInstanceId,
  savedStandardsEnabled,
  onSave,
  vendorSearchParams,
}: AIRecommenderProps) => {
  const { toast } = useToast();
  const { user, logout, userSessionId } = useAuth();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();



  // State for pricing data from RightPanel
  const [pricingData, setPricingData] = useState<Record<string, any>>(savedPricingData || {});

  // Handle pricing data updates from RightPanel
  // Must be memoized with useCallback to prevent infinite render loop:
  // RightPanel's useEffect depends on this ref — a new function every render
  // would re-trigger the effect → setPricingData → re-render → new ref → loop.
  const handlePricingDataUpdate = useCallback((priceReviewMap: Record<string, any>) => {
    setPricingData(priceReviewMap);
  }, []);

  // Generate unique search instance ID for this component instance, or restore saved one
  // This is the INSTANCE ID (Level 2) - different for each search tab/flow
  // The USER SESSION ID (Level 1) comes from AuthContext and is same across all screens
  const [searchInstanceId, setSearchInstanceId] = useState(() => {
    if (savedSearchInstanceId) {
      console.log(`[SEARCH_INSTANCE] Restoring saved instance ID: ${savedSearchInstanceId}`);
      return savedSearchInstanceId;
    }
    const id = `search_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    console.log(`[SEARCH_INSTANCE] Created new search instance ID: ${id}`);
    return id;
  });

  useEffect(() => {
    if (savedSearchInstanceId && searchInstanceId !== savedSearchInstanceId) {
      console.log(`[SEARCH_INSTANCE] Adopting restored instance ID: ${savedSearchInstanceId}`);
      setSearchInstanceId(savedSearchInstanceId);
    }
  }, [savedSearchInstanceId, searchInstanceId]);

  // Add session tracking for debugging
  useEffect(() => {
    console.log(`[TAB_SESSION] Tab initialized with session ID: ${searchInstanceId}`);
    return () => {
      console.log(`[TAB_SESSION] Tab with session ID ${searchInstanceId} is unmounting`);
    };
  }, [searchInstanceId]);

  const [collectedData, setCollectedData] = useState<{ [key: string]: any }>(savedCollectedData || {});
  const [advancedParameters, setAdvancedParameters] = useState<AdvancedParametersResult | null>(savedAdvancedParameters || null);
  const [selectedAdvancedParams, setSelectedAdvancedParams] = useState<{ [key: string]: string }>(savedSelectedAdvancedParams || {});
  const [fieldDescriptions, setFieldDescriptions] = useState<Record<string, string>>(savedFieldDescriptions || {});
  const [state, setState] = useState<AppState>({
    messages: savedMessages || [],
    currentProductType: savedCurrentProductType || null,
    validationResult: savedValidationResult || null,
    analysisResult: savedAnalysisResult || null,
    requirementSchema: savedRequirementSchema || null,
    isLoading: false,
    // Only restore inputValue if there are no saved messages (user was typing but hadn't sent)
    inputValue: (savedMessages && savedMessages.length > 0) ? "" : (savedInputValue || ""),
    productType: savedCurrentProductType || "",
  });
  const [currentStep, setCurrentStep] = useState<ConversationStep>(savedCurrentStep || "initialInput");
  const [hasAutoSubmitted, setHasAutoSubmitted] = useState(!!(savedMessages && savedMessages.length > 0));

  // Streaming state
  const [streamId, setStreamId] = useState<string | null>(null);

  // Route confirmation states
  const [awaitingRouteConfirmation, setAwaitingRouteConfirmation] = useState(false);
  const [pendingRouteTarget, setPendingRouteTarget] = useState<string>("");
  const [pendingRouteQuery, setPendingRouteQuery] = useState<string>("");
  const [pendingRouteMessages, setPendingRouteMessages] = useState<{
    openingMessage: string;
    declineMessage: string;
    popupBlockedMessage: string;
  }>({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });

  // Repeated Request cache confirmation dialog states
  const [cacheConfirmationOpen, setCacheConfirmationOpen] = useState(false);
  const [cacheConfirmationData, setCacheConfirmationData] = useState<any>(null);
  const [selectedCacheProjectId, setSelectedCacheProjectId] = useState<string>('');
  const [previewProjectData, setPreviewProjectData] = useState<any>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);

  // Track which page opened this one (to avoid opening duplicate windows when routing back)
  const [sourcePage] = useState<string | null>(() => {
    return sessionStorage.getItem('lastSourcePage') || null;
  });

  // Layout states
  const [isStreaming, setIsStreaming] = useState(false);

  // Standards toggle initial state:
  //   1. Restore saved value first (tab switch / page refresh / loaded project)
  //   2. Default: ON (true)
  const [standardsEnabled, setStandardsEnabled] = useState<boolean>(() => {
    if (savedStandardsEnabled !== undefined) return savedStandardsEnabled;
    return true;
  });

  const [isDocked, setIsDocked] = useState(() => {
    // If we have no data, force docked (collapsed) state initially, ignoring saved preference
    const hasData = (savedCollectedData && Object.keys(savedCollectedData).length > 0) || savedValidationResult || savedRequirementSchema;
    if (!hasData) return true;
    return savedDockingState?.left ?? true;
  });
  const [isRightDocked, setIsRightDocked] = useState(() => {
    const hasRightData = !!savedAnalysisResult;
    if (!hasRightData) return true;
    return savedDockingState?.right ?? true;
  });
  const DEFAULT_DOCKED_WIDTH = 0;
  const DEFAULT_EXPANDED_WIDTH = 21;
  const DEFAULT_RIGHT_DOCKED_WIDTH = 0;
  const DEFAULT_RIGHT_EXPANDED_WIDTH = 46;
  const [widths, setWidths] = useState(() => {
    // Initialize widths based on saved docking state
    const leftWidth = (savedDockingState?.left ?? true) ? DEFAULT_DOCKED_WIDTH : DEFAULT_EXPANDED_WIDTH;
    const rightWidth = (savedDockingState?.right ?? true) ? DEFAULT_RIGHT_DOCKED_WIDTH : DEFAULT_RIGHT_EXPANDED_WIDTH;
    return {
      left: leftWidth,
      center: 100 - leftWidth - rightWidth,
      right: rightWidth
    };
  });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const [draggingHandle, setDraggingHandle] = useState<"left" | "right" | null>(null);

  const scrollPositionsRef = useRef({
    left: savedScrollPositions?.left || 0,
    center: savedScrollPositions?.center || 0,
    right: savedScrollPositions?.right || 0
  });
  const centerScrollRef = useRef<HTMLDivElement>(null);
  const handleSendMessageRef = useRef<((query: string) => void) | null>(null);
  const skipNextUserMessageRef = useRef(false);

  // Debounced scroll handler to update state without performance hit
  // Synchronous scroll handler to update ref immediately, with debounced state save
  const emitParentState = useCallback((currentPositions: { left: number; center: number; right: number }) => {
    if (onStateChange) {
      onStateChange({
        messages: state.messages,
        collectedData,
        currentStep,
        analysisResult: state.analysisResult,
        searchInstanceId,
        requirementSchema: state.requirementSchema,
        validationResult: state.validationResult,
        currentProductType: state.currentProductType,
        inputValue: state.inputValue,
        advancedParameters,
        selectedAdvancedParams,
        fieldDescriptions,
        pricingData,
        scrollPositions: currentPositions,
        dockingState: { left: isDocked, right: isRightDocked },
        standardsEnabled,
      });
    }
  }, [onStateChange, state.messages, state.analysisResult, state.requirementSchema, state.validationResult, state.currentProductType, state.inputValue, collectedData, currentStep, searchInstanceId, advancedParameters, selectedAdvancedParams, fieldDescriptions, pricingData, isDocked, isRightDocked, standardsEnabled]);

  const notifyParentState = useMemo(() => {
    return debounce((currentPositions: { left: number; center: number; right: number }) => {
      emitParentState(currentPositions);
    }, 500);
  }, [emitParentState]);

  useEffect(() => {
    return () => {
      notifyParentState.cancel();
    };
  }, [notifyParentState]);

  useEffect(() => {
    emitParentState(scrollPositionsRef.current);
  }, [emitParentState]);

  const handleScrollUpdate = useCallback((position: { section: 'left' | 'center' | 'right', value: number }) => {
    // Update ref synchronously
    scrollPositionsRef.current = {
      ...scrollPositionsRef.current,
      [position.section]: position.value
    };

    // Trigger debounced save
    notifyParentState(scrollPositionsRef.current);
  }, [notifyParentState]);

  // State for search workflow download dialog
  const [isDownloadDialogOpen, setIsDownloadDialogOpen] = useState<boolean>(false);

  const exportWorkflowParams = useMemo(() => {
    const pType = state.currentProductType || savedCurrentProductType || 'Industrial Equipment';
    return {
      productType: pType,
      projectName: pType,
      sessionId: searchInstanceId || userSessionId,
      userQuery: state.messages.find(m => m.type === 'user')?.content || initialInput || '',
      collectedData: collectedData,
      validationResult: state.validationResult,
      analysisResult: state.analysisResult,
      chatMessages: state.messages,
      standardsEnabled: standardsEnabled,
      currentStep: currentStep,
      searchInstanceId: searchInstanceId,
    };
  }, [state.currentProductType, savedCurrentProductType, searchInstanceId, userSessionId, state.messages, initialInput, collectedData, state.validationResult, state.analysisResult, standardsEnabled, currentStep]);

  // Restore center scroll on mount/updates
  // Restore center scroll when messages load
  const hasRestoredCenterScroll = useRef(false);
  useEffect(() => {
    if (!hasRestoredCenterScroll.current && savedScrollPositions?.center && savedScrollPositions.center > 0 && state.messages.length > 0 && centerScrollRef.current) {
      requestAnimationFrame(() => {
        if (centerScrollRef.current) {
          centerScrollRef.current.scrollTop = savedScrollPositions.center;
          hasRestoredCenterScroll.current = true;
        }
      });
    }
  }, [state.messages, savedScrollPositions?.center]);



  // Auto-undock right panel when analysis result arrives (only once per session)
  const hasRightPanelAutoUndocked = useRef(false);
  // Track the previous analysis result to detect when NEW data arrives
  const prevAnalysisResultRef = useRef<AnalysisResult | null>(null);

  useEffect(() => {
    // Skip if this is a restored session with saved analysis result
    if (savedAnalysisResult) {
      hasRightPanelAutoUndocked.current = true;
      return;
    }

    const hasNewData = state.analysisResult?.vendorAnalysis?.vendorMatches?.length > 0;
    const hadDataBefore = prevAnalysisResultRef.current?.vendorAnalysis?.vendorMatches?.length > 0;

    // Only auto-undock when:
    // 1. We have new analysis data
    // 2. We didn't have data before (this is fresh data arriving)
    // 3. We haven't already auto-undocked
    if (hasNewData && !hadDataBefore && !hasRightPanelAutoUndocked.current) {
      hasRightPanelAutoUndocked.current = true;
      setIsRightDocked(false);
    }

    // Update the previous result ref
    prevAnalysisResultRef.current = state.analysisResult;
  }, [state.analysisResult, savedAnalysisResult]);

  // Sync local state with props on initial mount only - do NOT re-run on collectedData/schema changes
  // because that would override the auto-undock triggered by incoming API responses.
  const hasSyncedDockingState = useRef(false);
  useEffect(() => {
    if (hasSyncedDockingState.current) return; // only once on mount
    hasSyncedDockingState.current = true;

    if (savedDockingState) {
      if (savedDockingState.left !== undefined) {
        // Only allow opening (false) if we have saved data
        const hasData = (savedCollectedData && Object.keys(savedCollectedData).length > 0) || savedValidationResult || savedRequirementSchema;
        if (!hasData) {
          setIsDocked(true);
        } else {
          setIsDocked(savedDockingState.left);
        }
      }

      if (savedDockingState.right !== undefined) {
        const hasRightData = !!savedAnalysisResult;
        if (!hasRightData) {
          setIsRightDocked(true);
        } else {
          setIsRightDocked(savedDockingState.right);
        }
      }
    }
  }, []); // intentionally empty - run once on mount only

  // Restore saved state when props become available (for page refresh persistence)
  const hasRestoredState = useRef(false);
  useEffect(() => {
    // Only restore once when saved data becomes available
    if (hasRestoredState.current) return;

    // Check if we have saved messages (indicates saved state is available)
    if (savedMessages && savedMessages.length > 0) {
      console.log('[AIRecommender] Restoring saved state from IndexedDB/localStorage');

      // Restore messages
      setState((prev) => ({
        ...prev,
        messages: savedMessages,
        currentProductType: savedCurrentProductType || prev.currentProductType,
        validationResult: savedValidationResult || prev.validationResult,
        analysisResult: savedAnalysisResult || prev.analysisResult,
        requirementSchema: savedRequirementSchema || prev.requirementSchema,
        // Clear inputValue when restoring messages - those messages are already in the chat
        inputValue: "",
        productType: savedCurrentProductType || prev.productType,
      }));

      // Restore other state
      if (savedCollectedData && Object.keys(savedCollectedData).length > 0) {
        setCollectedData(savedCollectedData);
      }
      if (savedCurrentStep) {
        setCurrentStep(savedCurrentStep);
      }
      if (savedAdvancedParameters) {
        setAdvancedParameters(savedAdvancedParameters);
      }
      if (savedSelectedAdvancedParams && Object.keys(savedSelectedAdvancedParams).length > 0) {
        setSelectedAdvancedParams(savedSelectedAdvancedParams);
      }
      if (savedFieldDescriptions && Object.keys(savedFieldDescriptions).length > 0) {
        setFieldDescriptions(savedFieldDescriptions);
      }
      if (savedPricingData && Object.keys(savedPricingData).length > 0) {
        setPricingData(savedPricingData);
      }

      // Mark as restored and prevent auto-submission
      hasRestoredState.current = true;
      setHasAutoSubmitted(true);

      // Restore scroll positions
      if (savedScrollPositions) {
        scrollPositionsRef.current = savedScrollPositions;
      }

      console.log('[AIRecommender] State restored:', {
        messages: savedMessages.length,
        currentStep: savedCurrentStep,
        hasCollectedData: !!savedCollectedData,
        hasAnalysisResult: !!savedAnalysisResult,
      });
    }
  }, [savedMessages, savedCollectedData, savedCurrentStep, savedAnalysisResult, savedRequirementSchema, savedValidationResult, savedCurrentProductType, savedInputValue, savedAdvancedParameters, savedSelectedAdvancedParams, savedFieldDescriptions, savedPricingData, savedScrollPositions]);


  // Update sidebar width when docking state changes
  useEffect(() => {
    const newLeftWidth = isDocked ? DEFAULT_DOCKED_WIDTH : DEFAULT_EXPANDED_WIDTH;
    const newRightWidth = isRightDocked ? DEFAULT_RIGHT_DOCKED_WIDTH : DEFAULT_RIGHT_EXPANDED_WIDTH;
    setWidths({
      left: newLeftWidth,
      center: 100 - newLeftWidth - newRightWidth,
      right: newRightWidth
    });
  }, [isDocked, isRightDocked, DEFAULT_DOCKED_WIDTH, DEFAULT_EXPANDED_WIDTH, DEFAULT_RIGHT_DOCKED_WIDTH, DEFAULT_RIGHT_EXPANDED_WIDTH]);

  // Track if instance ID was restored from saved state
  const isRestoredInstanceRef = useRef(savedSearchInstanceId !== undefined && savedSearchInstanceId !== null);

  // Update the ref when savedSearchInstanceId becomes available
  useEffect(() => {
    if (savedSearchInstanceId && searchInstanceId === savedSearchInstanceId) {
      isRestoredInstanceRef.current = true;
      console.log(`[SEARCH_SESSION] Detected restored instance ID: ${savedSearchInstanceId}`);
    }
  }, [savedSearchInstanceId, searchInstanceId]);

  // Initialize new search session when component mounts (only if not restoring saved state)
  useEffect(() => {
    if (hasInitialized.current) return;

    // Skip initialization if instance ID was restored from saved state
    if (isRestoredInstanceRef.current) {
      console.log(`[SEARCH_SESSION] Skipping initialization - restoring saved state with instance ID: ${searchInstanceId}`);
      hasInitialized.current = true;
      return;
    }

    // Also skip if we have saved messages (backup check for async loaded state)
    if (savedMessages && savedMessages.length > 0) {
      console.log(`[SEARCH_SESSION] Skipping initialization - restoring saved state with ${savedMessages.length} messages`);
      hasInitialized.current = true;
      isRestoredInstanceRef.current = true; // Mark as restored
      return;
    }

    // Wait a bit to see if saved state is loading (give IndexedDB time to load)
    // This prevents initializing a new session when saved state is about to load
    const timeoutId = setTimeout(() => {
      // Double-check if saved state loaded during the delay
      if (hasInitialized.current) return;
      if (isRestoredInstanceRef.current) {
        console.log(`[SEARCH_SESSION] Instance ID was restored during delay, skipping initialization`);
        hasInitialized.current = true;
        return;
      }
      if (savedMessages && savedMessages.length > 0) {
        console.log(`[SEARCH_SESSION] Saved state loaded during delay, skipping initialization`);
        hasInitialized.current = true;
        isRestoredInstanceRef.current = true;
        return;
      }

      hasInitialized.current = true;

      const initializeSearch = async () => {
        try {
          await initializeNewSearch(searchInstanceId, userSessionId);
          console.log(`[SEARCH_SESSION] Initialized independent search session: ${searchInstanceId}`);
        } catch (error) {
          console.warn(`[SEARCH_SESSION] Failed to initialize search session: ${searchInstanceId}`, error);
          // Continue anyway - the backend will handle missing session ID gracefully
        }
      };

      initializeSearch();
    }, 300); // Delay to allow saved state to load from IndexedDB

    return () => clearTimeout(timeoutId);
  }, [searchInstanceId, savedMessages, userSessionId]);

  // Hydrate sidebar from backend SSOT when reopening a tab (survives server restart).
  useEffect(() => {
    if (!searchInstanceId) return;
    let cancelled = false;
    (async () => {
      const ctx = await getSearchContext(searchInstanceId);
      if (cancelled || !ctx?.contextSynced) return;
      const backendData = resolveCollectedDataFromSearchResult(ctx);
      if (Object.keys(backendData).length === 0) return;
      setCollectedData((prev) => ({ ...prev, ...backendData }));
      if (ctx.requirementSchema || ctx.productType) {
        setState((prev) => ({
          ...prev,
          requirementSchema: (ctx.requirementSchema as RequirementSchema) || prev.requirementSchema,
          productType: ctx.productType || prev.productType,
          currentProductType: ctx.productType || prev.currentProductType,
        }));
      }
      if (ctx.nextStep) {
        setCurrentStep(ctx.nextStep as ConversationStep);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchInstanceId]);

  // Handle URL parameter for pre-filled input (from Project page single item workflow)
  useEffect(() => {
    const urlInput = searchParams.get('input');
    const dataKey = searchParams.get('dataKey');
    const queryKey = searchParams.get('queryKey');

    console.log(`[URL_INPUT_DEBUG] key: "${dataKey || queryKey}", input: "${urlInput}", hasAutoSubmitted: ${hasAutoSubmitted}`);

    if ((urlInput || dataKey || queryKey) && !hasAutoSubmitted) {
      let finalInput = '';

      if (queryKey) {
        // Retrieve from sessionStorage (or localStorage fallback) wrapper
        const storedInput = sessionStorage.getItem(queryKey) || localStorage.getItem(queryKey);
        if (storedInput) {
          finalInput = storedInput;
          console.log(`[URL_INPUT_DEBUG] Retrieved input from storage (queryKey):`, finalInput);
          sessionStorage.removeItem(queryKey);
          localStorage.removeItem(queryKey);
        }
      } else if (dataKey) {
        // Retrieve from localStorage using the key (legacy)
        const storedInput = localStorage.getItem(dataKey);
        if (storedInput) {
          finalInput = storedInput;
          console.log(`[URL_INPUT_DEBUG] Retrieved input from storage (dataKey):`, finalInput);
          // Clean up storage
          localStorage.removeItem(dataKey);
        }
      } else if (urlInput) {
        // Fallback to direct URL input (legacy)
        finalInput = urlInput;
      }

      if (finalInput) {
        console.log(`[URL_INPUT_DEBUG] Setting state with input:`, finalInput);

        // Set the input value in state
        setState(prev => {
          return { ...prev, inputValue: finalInput };
        });

        // Mark as auto-filled to prevent re-processing
        setHasAutoSubmitted(true);
      }
    }
  }, [searchParams, hasAutoSubmitted, toast]);

  // Set window name for BroadcastChannel targeting
  useEffect(() => {
    window.name = 'eng_search';
  }, []);

  // Track if component has been initialized to prevent continuous re-loading
  const hasInitialized = useRef(false);

  // Initialize with saved state if provided (only once)
  useEffect(() => {
    if (hasInitialized.current) {
      console.log(`[${searchInstanceId}] Already initialized, skipping`);
      return;
    }


    if (savedMessages || savedCollectedData || savedCurrentStep || savedAnalysisResult || savedRequirementSchema || savedValidationResult) {
      console.log(`[${searchInstanceId}] Restoring saved state...`);

      // Restore saved state
      if (savedMessages && savedMessages.length > 0) {
        console.log(`[${searchInstanceId}] Restoring ${savedMessages.length} messages`);
        setState(prev => ({
          ...prev,
          messages: savedMessages
        }));
      }

      if (savedCollectedData) {
        console.log(`[${searchInstanceId}] Restoring collected data with ${Object.keys(savedCollectedData).length} keys`);
        setCollectedData(savedCollectedData);
      }

      if (savedCurrentStep) {
        console.log(`[${searchInstanceId}] Restoring current step: ${savedCurrentStep}`);
        setCurrentStep(savedCurrentStep);
      }

      if (savedAnalysisResult) {
        console.log(`[${searchInstanceId}] Restoring analysis result`);
        setState(prev => ({
          ...prev,
          analysisResult: savedAnalysisResult
        }));
      }

      // Restore extended state
      if (savedRequirementSchema) {
        console.log(`[${searchInstanceId}] Restoring requirement schema`);
        setState(prev => ({
          ...prev,
          requirementSchema: savedRequirementSchema
        }));
      }

      if (savedValidationResult) {
        console.log(`[${searchInstanceId}] Restoring validation result`);
        setState(prev => ({
          ...prev,
          validationResult: savedValidationResult,
          currentProductType: savedCurrentProductType,
          productType: savedCurrentProductType || prev.productType
        }));
      }

      // Determine input value: prefer saved draft if provided, otherwise fall back to initial input.
      // This ensures when users were mid-chat and saved a draft input, it is restored on load.
      const hasMessages = savedMessages && savedMessages.length > 0;
      // If conversation already has messages (i.e., the search was run), leave input empty.
      // Otherwise show saved draft or initial input so user can submit it.
      const inputValueToSet = hasMessages ? '' : (savedInputValue ?? initialInput ?? '');

      console.log(`[${searchInstanceId}] Setting input value on restore: hasMessages=${hasMessages}, value="${inputValueToSet}"`);
      setState(prev => ({ ...prev, inputValue: inputValueToSet }));
      // Mark auto-fill as handled so other effects don't overwrite this restored input
      setHasAutoSubmitted(true);

      if (savedAdvancedParameters) {
        console.log(`[${searchInstanceId}] Restoring advanced parameters`);
        setAdvancedParameters(savedAdvancedParameters);
      }

      if (savedSelectedAdvancedParams) {
        console.log(`[${searchInstanceId}] Restoring selected advanced params`);
        setSelectedAdvancedParams(savedSelectedAdvancedParams);
      }

      if (savedFieldDescriptions && Object.keys(savedFieldDescriptions).length > 0) {
        console.log(`[${searchInstanceId}] Restoring field descriptions:`, Object.keys(savedFieldDescriptions).length, 'fields');
        setFieldDescriptions(savedFieldDescriptions);
      }

      if (savedPricingData && Object.keys(savedPricingData).length > 0) {
        console.log(`[${searchInstanceId}] Restoring pricing data:`, Object.keys(savedPricingData).length, 'products');
        setPricingData(savedPricingData);
      }

      // After restoration, trigger state notification to parent
      if (onStateChange) {
        console.log(`[${searchInstanceId}] Notifying parent of restored state`);
        const hasMessages = savedMessages && savedMessages.length > 0;
        const inputValueToNotify = hasMessages ? '' : (savedInputValue ?? initialInput ?? '');
        onStateChange({
          messages: savedMessages || [],
          collectedData: savedCollectedData || {},
          currentStep: savedCurrentStep || "greeting",
          analysisResult: savedAnalysisResult || null,
          searchInstanceId,
          requirementSchema: savedRequirementSchema || null,
          validationResult: savedValidationResult || null,
          currentProductType: savedCurrentProductType || null,
          inputValue: inputValueToNotify,
          advancedParameters: savedAdvancedParameters || null,
          selectedAdvancedParams: savedSelectedAdvancedParams || {},
          fieldDescriptions: savedFieldDescriptions || {},
          pricingData: savedPricingData || {},
          scrollPositions: scrollPositionsRef.current,
          standardsEnabled: savedStandardsEnabled,
        });
      }
    } else {
      console.log(`[${searchInstanceId}] No saved state found, using defaults`);
    }

    // Mark as initialized to prevent re-initialization
    hasInitialized.current = true;
    console.log(`[${searchInstanceId}] Initialization complete`);
  }, [savedMessages, savedCollectedData, savedCurrentStep, savedAnalysisResult, savedRequirementSchema, savedValidationResult, savedCurrentProductType, savedInputValue, savedAdvancedParameters, savedSelectedAdvancedParams, savedFieldDescriptions, savedPricingData, searchInstanceId, initialInput]);

  // Notify parent component of state changes for project saving
  useEffect(() => {
    if (onStateChange) {
      onStateChange({
        messages: state.messages,
        collectedData,
        currentStep,
        analysisResult: state.analysisResult,
        searchInstanceId,
        requirementSchema: state.requirementSchema,
        validationResult: state.validationResult,
        currentProductType: state.currentProductType,
        inputValue: state.inputValue,
        advancedParameters,
        selectedAdvancedParams,
        fieldDescriptions,
        pricingData,
        scrollPositions: scrollPositionsRef.current,
        dockingState: { left: isDocked, right: isRightDocked }
      });
    }
  }, [state.messages, collectedData, currentStep, state.analysisResult, searchInstanceId, state.requirementSchema, state.validationResult, state.currentProductType, state.inputValue, advancedParameters, selectedAdvancedParams, fieldDescriptions, pricingData, isDocked, isRightDocked]);

  // --- Resize functionality ---
  const handleMouseDown = useCallback((e: React.MouseEvent, handle: "left" | "right") => {
    e.preventDefault();
    setDraggingHandle(handle);

    const startX = e.clientX;
    const startWidths = { ...widths };
    const containerWidth = containerRef.current?.offsetWidth || 1200;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!containerRef.current) return;

      const deltaX = moveEvent.clientX - startX;
      const deltaPercent = (deltaX / containerWidth) * 100;

      let newWidths;
      if (handle === "left") {
        // Dragging left handle (between sidebar and chat)
        const newLeft = Math.max(0, Math.min(30, startWidths.left + deltaPercent));
        const adjustment = newLeft - startWidths.left;
        newWidths = {
          left: newLeft,
          center: Math.max(10, startWidths.center - adjustment),
          right: startWidths.right
        };

        // Auto-dock if width is small
        if (newLeft < 5 && !isDocked) setIsDocked(true);
        if (newLeft >= 5 && isDocked) setIsDocked(false);

      } else {
        // Dragging right handle (between chat and right panel)
        const newCenter = Math.max(10, Math.min(60, startWidths.center + deltaPercent));
        const adjustment = newCenter - startWidths.center;

        // Calculate the new right width based on the center adjustment
        // Since right increases as center decreases (dragging left), or decreases as center increases (dragging right)
        // startWidths.right - adjustment is correct because:
        // if dragging RIGHT (positive delta), center increases, right decreases.
        // if dragging LEFT (negative delta), center decreases, right increases.
        const potentialRight = startWidths.right - adjustment;
        const newRight = Math.max(0, Math.min(65, potentialRight));

        newWidths = {
          left: startWidths.left,
          center: newCenter,
          right: newRight
        };

        // Auto-dock if width is small
        if (newRight < 5 && !isRightDocked) setIsRightDocked(true);
        if (newRight >= 5 && isRightDocked) setIsRightDocked(false);
      }

      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }

      animationFrameRef.current = requestAnimationFrame(() => {
        setWidths(newWidths);
      });
    };

    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      setDraggingHandle(null);

      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [widths]);

  // Cleanup animation frame on unmount
  useEffect(() => {
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

  // Handle field descriptions updates from LeftSidebar
  const handleFieldDescriptionsChange = useCallback((descriptions: Record<string, string>) => {
    console.log(`[${searchInstanceId}] Field descriptions updated:`, Object.keys(descriptions).length, 'fields');
    setFieldDescriptions(descriptions);
  }, [searchInstanceId]);

  // --- Helper functions ---
  const addMessage = useCallback(
    (message: Omit<ChatMessage, "id" | "timestamp">) => {
      const newMessage: ChatMessage = {
        ...message,
        id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
        timestamp: new Date(),
        role: message.role,
        type: message.type,
      };
      setState((prev) => ({ ...prev, messages: [...prev.messages, newMessage] }));
      return newMessage;
    },
    []
  );

  const updateMessage = useCallback((id: string, newContent: string) => {
    setState((prev) => ({
      ...prev,
      messages: prev.messages.map((msg) =>
        msg.id === id ? { ...msg, content: newContent } : msg
      ),
    }));
  }, []);

  const streamAssistantMessage = useCallback(
    async (fullText: string, metadata?: any) => {
      // For single-response steps we no longer stream character-by-character.
      // Add the assistant message once with the complete content.
      setIsStreaming(true);
      const msg = addMessage({ type: "assistant", content: fullText, role: undefined, metadata });
      // Slight delay to allow UI to reflect loading state briefly
      await new Promise((res) => setTimeout(res, 50));
      setIsStreaming(false);
      return msg.id;
    },
    [addMessage]
  );

  const composeUserDataString = (data: any): string => {
    const parts: string[] = [];
    if (data.productType) parts.push(`Product Type: ${data.productType}`);
    for (const key in data) {
      if (key === "productType") continue;
      const value = data[key];
      if (value != null && value !== "") {
        parts.push(
          typeof value === "object"
            ? Object.entries(value)
              .map(([k, v]) => (Array.isArray(v) ? `${k}: ${v.join(", ")}` : `${k}: ${v}`))
              .join(". ")
            : `${key}: ${value}`
        );
      }
    }
    return parts.join(". ");
  };



  // --- Core analysis and summary flow ---
  const completeVendorAnalysis = useCallback(async (
    streamId: string,
    initialAnalysis?: AnalysisResult,
  ) => {
    let analysis: AnalysisResult;
    if (initialAnalysis) {
      analysis = initialAnalysis;
    } else {
      const polled = await waitForSearchResult(streamId);
      if (!polled?.analysisResult) {
        throw new Error("Analysis failed or no result returned.");
      }
      analysis = polled.analysisResult as AnalysisResult;
    }

    const APPROXIMATE_THRESHOLD = 30;
    const exactMatches = analysis.overallRanking.rankedProducts.filter(
      (p) => p.requirementsMatch === true
    );
    const approximateMatches = analysis.overallRanking.rankedProducts.filter(
      (p) => p.requirementsMatch === false && (p.overallScore ?? 0) >= APPROXIMATE_THRESHOLD
    );
    const productsToFetchImagesFor = exactMatches.length > 0 ? exactMatches : approximateMatches;

    if (productsToFetchImagesFor.length > 0) {
      try {
        const imageFetchPromises = productsToFetchImagesFor.map(async (product) => {
          if (!product.vendor || !product.productName) return product;
          try {
            const modelFamilies = product.modelFamily ? [product.modelFamily] : [];
            const imageResult = await getAnalysisProductImages(
              product.vendor,
              state.productType || "",
              product.productName,
              modelFamilies
            );
            return {
              ...product,
              topImage: imageResult.topImage,
              vendorLogo: imageResult.vendorLogo,
              allImages: imageResult.allImages || [],
            };
          } catch (error) {
            console.error(`Failed to fetch images for ${product.vendor} - ${product.productName}:`, error);
            return product;
          }
        });

        const productsWithImages = await Promise.all(imageFetchPromises);
        analysis.overallRanking.rankedProducts = analysis.overallRanking.rankedProducts.map(product => {
          const updatedProduct = productsWithImages.find(
            p => p.vendor === product.vendor && p.productName === product.productName
          );
          return updatedProduct || product;
        });

        if (analysis.vendorAnalysis?.vendorMatches) {
          for (const match of analysis.vendorAnalysis.vendorMatches) {
            const correspondingProduct = productsWithImages.find(
              p => p.vendor === match.vendor && p.productName === match.productName
            );
            if (correspondingProduct) {
              match.topImage = correspondingProduct.topImage;
              match.vendorLogo = correspondingProduct.vendorLogo;
              match.allImages = correspondingProduct.allImages;
            }
          }
        }
      } catch (error) {
        console.error("Error fetching product images:", error);
      }
    }

    let completionMessage = analysis.message || "Analysis complete. I have ranked the products based on your requirements.";
    const analysisWarnings = (analysis as any)?.warnings;
    if (Array.isArray(analysisWarnings) && analysisWarnings.length > 0) {
      completionMessage += "\n\n" + analysisWarnings.map((w: string) => `⚠️ ${w}`).join("\n");
    }
    const vendorFilterNote = analysis.analysisMetadata?.vendorFilterNote;
    if (vendorFilterNote) {
      completionMessage += "\n\n" + `⚠️ ${vendorFilterNote}`;
    }
    await streamAssistantMessage(completionMessage);

    setState((prev) => ({ ...prev, analysisResult: analysis, isLoading: false }));
    setCurrentStep("finalAnalysis");
    toast({
      title: "Analysis Complete",
      description: completionMessage,
      variant: "default",
    });
  }, [state.productType, streamAssistantMessage, toast]);

  const performAnalysis = useCallback(async () => {
    setState((prev) => ({ ...prev, isLoading: true }));
    const newStreamId = `stream-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    setStreamId(newStreamId);

    try {
      const searchResult = await callSearchAgent(
        "proceed",
        "awaitAllSpecs",
        searchInstanceId,
        userSessionId,
        {
          productType: state.productType || undefined,
          collectedData: collectedData,
          skipStandardRag: !standardsEnabled,
          streamId: newStreamId
        }
      );

      if (searchResult.streamId) {
        setStreamId(searchResult.streamId);
      }

      if (searchResult.analysisResult) {
        await completeVendorAnalysis(searchResult.streamId || newStreamId, searchResult.analysisResult as AnalysisResult);
      } else {
        await completeVendorAnalysis(searchResult.streamId || newStreamId);
      }
    } catch (error) {
      console.error("Analysis error:", error);
      await streamAssistantMessage("I'm sorry, an error occurred during analysis. Please try again.");
      toast({
        title: "Analysis Error",
        description: "An error occurred during analysis. Please try again.",
        variant: "destructive",
      });
      setState((prev) => ({ ...prev, isLoading: false }));
      setCurrentStep("analysisError");
    }
  }, [collectedData, state.productType, toast, streamAssistantMessage, searchInstanceId, userSessionId, vendorSearchParams, standardsEnabled, completeVendorAnalysis]);

  const handleShowSummaryAndProceed = useCallback(async (options?: { skipIntro?: boolean; introAlreadyStreamed?: boolean; skipAnalysis?: boolean }) => {
    setState((prev) => ({ ...prev, isLoading: true }));
    try {
      const requirementsOnly = (({ productType, ...rest }) => rest)(collectedData);
      const requirementsString = composeUserDataString(requirementsOnly);

      // Use search agent to format requirements (it handles structure internally via validation subagent)
      const agentResponse = await callSearchAgent(
        requirementsString,
        "showSummary",
        searchInstanceId,
        userSessionId,
        {
          currentIntent: "productRequirements",
          collectedData: collectedData,
          productType: state.productType || undefined,
          skipStandardRag: !standardsEnabled
        }
      );

      // Check if agent indicates routing is needed
      if (agentResponse.intent === 'router_needed' || agentResponse.nextStep === 'route') {
        console.log('[ROUTER] Input not search-related - routing to:', agentResponse.message);

        addMessage({
          type: "assistant",
          content: agentResponse.message || "This doesn't seem to be a product search request.",
          role: undefined
        });

        setState((prev) => ({ ...prev, isLoading: false }));
        return;
      }

      // Get formatted requirements summary from search agent response
      const summaryContent = agentResponse.formattedRequirementsSummary || agentResponse.message || "Requirements collected.";

      if (!options?.skipIntro && !options?.introAlreadyStreamed) {
        await streamAssistantMessage("Here's a summary of your requirements. Running analysis now...");
      }

      addMessage({ type: "assistant", content: `\n\n${summaryContent}\n\n`, role: undefined });

      // ✅ Always call analysis immediately after structure response
      await performAnalysis();

      setState((prev) => ({ ...prev, isLoading: false }));
    } catch (error) {
      console.error("Summary error:", error);
      await streamAssistantMessage("I had trouble generating the summary. Please try again.");
      setState((prev) => ({ ...prev, isLoading: false }));
      setCurrentStep("showSummary");
    }
  }, [collectedData, performAnalysis, streamAssistantMessage, addMessage, searchInstanceId, userSessionId, state.productType, vendorSearchParams, standardsEnabled]);

  const handleCacheOpen = async (projectId: string) => {
    setCacheConfirmationOpen(false);
    // Clear the pending recall so the next message is not misread as a reply to the offer.
    try {
      await axios.post('/api/projects/recall/dismiss', { session_id: userSessionId });
    } catch (err: any) {
      console.error("Failed to dismiss recall:", err);
    }
    navigate(`/search?projectId=${projectId}`);
  };

  const handleCachePreview = async (projectId: string) => {
    if (!projectId) return;
    setIsPreviewLoading(true);
    setPreviewProjectData(null);
    try {
      const response = await axios.get(`/api/projects/${projectId}`);
      if (response.status === 200) {
        setPreviewProjectData(response.data.project || response.data);
      } else {
        toast({
          title: "Preview Failed",
          description: "Failed to fetch project specifications.",
          variant: "destructive",
        });
      }
    } catch (err: any) {
      console.error("Preview project specs error:", err);
      toast({
        title: "Preview Failed",
        description: err.message || "Failed to load project details.",
        variant: "destructive",
      });
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const handleCacheIgnore = async () => {
    setCacheConfirmationOpen(false);
    try {
      const response = await axios.post('/api/projects/recall/ignore', {
        session_id: userSessionId,
      });
      const data = response.data || {};
      const originalQuery = (data.originalQuery || data.original_query || '').trim();

      if (data.message) {
        await streamAssistantMessage(data.message, { recallAction: data.action });
      }

      if (originalQuery && handleSendMessageRef.current) {
        skipNextUserMessageRef.current = true;
        await handleSendMessageRef.current(originalQuery);
      }
    } catch (err: any) {
      console.error("Failed to decline recall:", err);
      await streamAssistantMessage("Okay — I'll start fresh for you.");
    }
  };

  // --- New workflow-aware message handler ---
  const handleSendMessage = useCallback(
    async (userInput: string) => {
      const trimmedInput = userInput.trim();
      if (!trimmedInput) return;

      const skipUserMessage = skipNextUserMessageRef.current;
      skipNextUserMessageRef.current = false;

      if (!skipUserMessage) {
        addMessage({ type: "user", content: trimmedInput, role: undefined });
      }
      setState((prev) => ({ ...prev, inputValue: "", isLoading: true }));

      try {
        // =====================================================
        // STEP 0: Check if user is responding to route confirmation
        // =====================================================
        if (awaitingRouteConfirmation) {
          console.log('[ROUTE] User responding to route confirmation, calling LLM...');

          // Use LLM to classify yes/no/unclear
          const confirmResult = await confirmRouteResponse(
            trimmedInput,
            "search",
            pendingRouteTarget,
            pendingRouteQuery,
            searchInstanceId,
            userSessionId
          );

          console.log('[ROUTE] Confirmation result:', confirmResult);

          if (confirmResult.action === 'confirm' && confirmResult.proceedWithRouting) {
            console.log(`[ROUTE] User confirmed - opening ${pendingRouteTarget}`);

            // Check if we're routing back to the source page FIRST (avoid duplicate windows)
            const normalizedTarget = pendingRouteTarget === 'solution' ? 'solution' : pendingRouteTarget;
            if (sourcePage && (sourcePage === normalizedTarget || sourcePage === 'solution' && normalizedTarget === 'solution')) {
              // User is trying to go back to the page they came from
              addMessage({
                type: "assistant",
                content: pendingRouteMessages.openingMessage || confirmResult.message,
                role: undefined
              });

              // Copy query to clipboard for convenience
              navigator.clipboard.writeText(pendingRouteQuery).catch(() => { });

              toast({
                title: "Switch Tabs",
                description: "Please switch to your Solution tab to continue.",
              });

              // Focus Solution window with smooth transition
              setTimeout(() => {
                const solutionWindow = window.open('', 'eng_solution');
                try {
                  solutionWindow?.focus();
                } catch { /* ignore focus errors */ }
              }, 100);

              // Clear route confirmation state
              setAwaitingRouteConfirmation(false);
              setPendingRouteTarget("");
              setPendingRouteQuery("");
              setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
              setState((prev) => ({ ...prev, isLoading: false }));
              return;
            }

            // If Solution page is already open, send the query there instead of opening a duplicate tab
            if (pendingRouteTarget === 'solution') {
              const preFocusWindow = window.open('', 'eng_solution');
              try {
                preFocusWindow?.focus();
              } catch { /* ignore focus errors */ }

              const requestId = `solution_${Date.now()}_${Math.random().toString(36).slice(2)}`;
              const channel = new BroadcastChannel('eng-route-handoff');
              const ackPromise = new Promise<boolean>((resolve) => {
                const timeout = window.setTimeout(() => {
                  channel.removeEventListener('message', onMessage);
                  resolve(false);
                }, 150);

                const onMessage = (event: MessageEvent) => {
                  const data: any = event.data;
                  if (data && data.type === 'solution_ack' && data.requestId === requestId) {
                    window.clearTimeout(timeout);
                    channel.removeEventListener('message', onMessage);
                    resolve(true);
                  }
                };

                channel.addEventListener('message', onMessage);
              });

              channel.postMessage({
                type: 'solution_run_query',
                requestId,
                query: pendingRouteQuery
              });

              const acked = await ackPromise;
              channel.close();

              if (acked) {
                // Focus Solution window with smooth transition
                setTimeout(() => {
                  const solutionWindow = window.open('', 'eng_solution');
                  try {
                    solutionWindow?.focus();
                  } catch { /* ignore focus errors */ }
                }, 100);

                addMessage({
                  type: "assistant",
                  content: pendingRouteMessages.openingMessage || confirmResult.message,
                  role: undefined
                });

                setAwaitingRouteConfirmation(false);
                setPendingRouteTarget("");
                setPendingRouteQuery("");
                setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
                setState((prev) => ({ ...prev, isLoading: false }));
                return;
              }
            }

            // If Chat page is already open, send the query there instead of opening a duplicate tab
            if (pendingRouteTarget === 'chat') {
              const preFocusWindow = window.open('', 'eng_chat');
              try {
                preFocusWindow?.focus();
              } catch { /* ignore focus errors */ }

              const requestId = `chat_${Date.now()}_${Math.random().toString(36).slice(2)}`;
              const channel = new BroadcastChannel('eng-route-handoff');
              const ackPromise = new Promise<boolean>((resolve) => {
                const timeout = window.setTimeout(() => {
                  channel.removeEventListener('message', onMessage);
                  resolve(false);
                }, 150);

                const onMessage = (event: MessageEvent) => {
                  const data: any = event.data;
                  if (data && data.type === 'chat_ack' && data.requestId === requestId) {
                    window.clearTimeout(timeout);
                    channel.removeEventListener('message', onMessage);
                    resolve(true);
                  }
                };

                channel.addEventListener('message', onMessage);
              });

              channel.postMessage({
                type: 'chat_run_query',
                requestId,
                query: pendingRouteQuery
              });

              const acked = await ackPromise;
              channel.close();

              if (acked) {
                // Focus Chat window with smooth transition
                setTimeout(() => {
                  const chatWindow = window.open('', 'eng_chat');
                  try {
                    chatWindow?.focus();
                  } catch { /* ignore focus errors */ }
                }, 100);

                addMessage({
                  type: "assistant",
                  content: pendingRouteMessages.openingMessage || confirmResult.message,
                  role: undefined
                });

                setAwaitingRouteConfirmation(false);
                setPendingRouteTarget("");
                setPendingRouteQuery("");
                setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
                setState((prev) => ({ ...prev, isLoading: false }));
                return;
              }
            }

            // NOT going back to source - show opening message and open new window
            addMessage({
              type: "assistant",
              content: pendingRouteMessages.openingMessage || confirmResult.message,
              role: undefined
            });

            // Store query for target page in localStorage (shared across tabs)
            const queryKey = `route_query_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem(queryKey, pendingRouteQuery);

            // Build URL based on target page
            let targetUrl = '';
            if (pendingRouteTarget === 'solution') {
              targetUrl = `/solution?queryKey=${queryKey}&fresh=true`;
            } else if (pendingRouteTarget === 'chat') {
              targetUrl = `/chat?queryKey=${queryKey}&fresh=true`;
            }

            // Smart window management: Check if window for this target page exists
            let newWindow: Window | null = null;
            if (routingWindows[pendingRouteTarget] && !routingWindows[pendingRouteTarget]?.closed) {
              // Reuse existing window for same target page
              newWindow = routingWindows[pendingRouteTarget];
              newWindow!.focus();
              newWindow!.location.href = targetUrl;
              console.log(`[ROUTING] Reusing existing window for target: ${pendingRouteTarget}`);
            } else {
              // Open new window for different target page
              const windowName = pendingRouteTarget === 'solution' ? 'eng_solution'
                : (pendingRouteTarget === 'chat') ? 'eng_chat'
                  : '_blank';
              newWindow = window.open(targetUrl, windowName);
              routingWindows[pendingRouteTarget] = newWindow;
              console.log(`[ROUTING] Opened new window for target: ${pendingRouteTarget}`);
            }
            const isPopupBlocked = !newWindow || newWindow.closed || typeof newWindow.closed === 'undefined';
            if (isPopupBlocked) {
              addMessage({
                type: "assistant",
                content: `${pendingRouteMessages.popupBlockedMessage || ""}\n\n[Open page](${targetUrl})`.trim(),
                role: undefined
              });
              toast({
                title: "Popup Blocked",
                description: "Please allow popups or click the link.",
                variant: "destructive",
              });
            } else {
              // Focus new window with smooth transition
              setTimeout(() => {
                try {
                  newWindow?.focus();
                } catch { /* ignore focus errors */ }
              }, 100);
              toast({
                title: "Opening New Tab",
                description: "A new tab has been opened",
              });
            }

            // Clear route confirmation state
            setAwaitingRouteConfirmation(false);
            setPendingRouteTarget("");
            setPendingRouteQuery("");
            setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
            setState((prev) => ({ ...prev, isLoading: false }));
            return;
          }

          if (confirmResult.action === 'decline') {
            console.log('[ROUTE] User declined - staying on Search');

            // Use LLM-generated decline message
            addMessage({
              type: "assistant",
              content: pendingRouteMessages.declineMessage || confirmResult.message,
              role: undefined
            });

            // Clear route confirmation state
            setAwaitingRouteConfirmation(false);
            setPendingRouteTarget("");
            setPendingRouteQuery("");
            setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
            setState((prev) => ({ ...prev, isLoading: false }));
            return;
          }

          // Unclear response - clear state and treat as new input
          console.log('[ROUTE] Unclear response - treating as new input');
          setAwaitingRouteConfirmation(false);
          setPendingRouteTarget("");
          setPendingRouteQuery("");
          setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
        }

        // =====================================================
        // STEP 1: Single call to /api/search-agent
        // The backend handles: intent classification → validation → 
        // LLM response generation → step management
        // =====================================================
        // Generate stream ID immediately so UI can connect to SSE
        const newStreamId = `stream-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
        setStreamId(newStreamId);

        const searchResult: SearchAgentResult = await callSearchAgent(
          trimmedInput,
          currentStep,
          searchInstanceId,
          userSessionId,
          {
            currentIntent: undefined,
            collectedData,
            productType: state.productType || undefined,
            availableParameters: advancedParameters?.uniqueParameters,
            selectedParameters: selectedAdvancedParams,
            totalSelected: Object.keys(selectedAdvancedParams || {}).length,
            missingFields: state.validationResult?.validationAlert?.missingFields || [],
            analysisResult: state.analysisResult || undefined,
            skipStandardRag: !standardsEnabled,
            streamId: newStreamId,
          }
        );

        console.log('[SEARCH_AGENT] Response:', searchResult);

        if (searchResult.status === 'processing') {
          setCurrentStep('finalAnalysis');
          try {
            await completeVendorAnalysis(searchResult.streamId || newStreamId);
          } catch (error) {
            console.error('Analysis error:', error);
            await streamAssistantMessage("I'm sorry, an error occurred during analysis. Please try again.");
            toast({
              title: 'Analysis Error',
              description: 'An error occurred during analysis. Please try again.',
              variant: 'destructive',
            });
            setState((prev) => ({ ...prev, isLoading: false }));
            setCurrentStep('analysisError');
          }
          return;
        }

        // streamId is already set up in frontend state via setStreamId(newStreamId) so we don't strictly need to reset it,
        // but if the backend returned a new one we align to it
        if (searchResult.streamId && searchResult.streamId !== newStreamId) {
          setStreamId(searchResult.streamId);
        }

        // ─── Handle cache confirmation (Repeated Request) ─────────
        if (searchResult.intent === "cacheConfirmation" || (searchResult.requiresConfirmation && !searchResult.routerNeeded)) {
          console.log('[SEARCH] Cache confirmation required, opening dialog:', searchResult);
          
          const firstProjId = searchResult.matchedProjects?.[0]?.projectId || searchResult.matchedProjects?.[0]?.project_id || '';
          
          if (searchResult.message) {
            await streamAssistantMessage(searchResult.message, {
              cacheConfirmation: true,
              matchedProjects: searchResult.matchedProjects,
              projectId: firstProjId
            });
          }
          
          setCacheConfirmationData(searchResult);
          setSelectedCacheProjectId(firstProjId);
          setCacheConfirmationOpen(true);
          setState((prev) => ({ ...prev, isLoading: false }));
          
          // Automatically fetch preview details for the first matched project
          if (firstProjId) {
            handleCachePreview(firstProjId);
          }
          return;
        }

        // ─── Handle error ─────────────────────────────────────────
        if (!searchResult.success && searchResult.intent === "error") {
          await streamAssistantMessage(searchResult.message || "Something went wrong. Please try again.");
          toast({
            title: "Error",
            description: searchResult.message || "Something went wrong. Please try again.",
            variant: "destructive",
          });
          setState((prev) => ({ ...prev, isLoading: false }));
          return;
        }

        // ─── Handle router redirect ──────────────────────────────
        if (searchResult.routerNeeded) {
          // If routing to a different page with confirmation
          if (searchResult.requiresConfirmation && searchResult.routerTargetPage !== 'search') {
            console.log(`[SEARCH] Routing to ${searchResult.routerTargetPage} requires confirmation`);

            // Show confirmation message
            addMessage({
              type: "assistant",
              content: searchResult.confirmationMessage || searchResult.message,
              role: undefined
            });

            // Set confirmation state
            setAwaitingRouteConfirmation(true);
            setPendingRouteTarget(searchResult.routerTargetPage);
            setPendingRouteQuery(trimmedInput);
            setPendingRouteMessages({
              openingMessage: searchResult.openingMessage || "",
              declineMessage: searchResult.declineMessage || "",
              popupBlockedMessage: searchResult.popupBlockedMessage || ""
            });
            setState((prev) => ({ ...prev, isLoading: false }));
            return;
          }

          // Direct routing response with navigation button
          const routerTargetPage = searchResult.routerTargetPage || '';
          const routerRequiresRouting = searchResult.routerRequiresRouting || false;

          // Build URL client-side with input stored in localStorage (shared across tabs)
          // so the target tab can read it when opened via window.open()
          let routerUrl = searchResult.routerUrl || (routerTargetPage ? `/${routerTargetPage}` : '');
          if (routerTargetPage && routerTargetPage !== 'search' && trimmedInput) {
            const queryKey = `route_query_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            localStorage.setItem(queryKey, trimmedInput);
            routerUrl = `/${routerTargetPage}?queryKey=${queryKey}&fresh=true`;
          }

          // Show message with routing metadata for button rendering
          addMessage({
            type: "assistant",
            content: searchResult.routerMessage || searchResult.message,
            role: undefined,
            metadata: {
              routerRedirect: routerRequiresRouting && routerTargetPage !== 'search',
              routerUrl: routerUrl,
              routerTargetPage: routerTargetPage
            }
          });

          setState((prev) => ({ ...prev, isLoading: false }));
          return;
        }

        // ─── Handle reset ────────────────────────────────────────
        if (searchResult.resetComplete) {
          await streamAssistantMessage(searchResult.message);
          setCurrentStep("greeting");
          setCollectedData({});
          setSelectedAdvancedParams({});
          setAdvancedParameters(null);
          setState((prev) => ({
            ...prev,
            isLoading: false,
            productType: undefined,
            currentProductType: null,
            validationResult: null,
            requirementSchema: null,
            analysisResult: null,
          }));
          return;
        }

        // ─── Handle modification ─────────────────────────────────────
        if (searchResult.intent === "modification") {
          // Update UI data if the backend returned updated schema/requirements
          if (searchResult.mappedRequirements || searchResult.productType || searchResult.collectedData) {
            const schema = searchResult.requirementSchema || state.requirementSchema || { mandatoryRequirements: {}, optionalRequirements: {}, advancedRequirements: {} };
            const mergedData = resolveCollectedDataFromSearchResult(searchResult);

            // Merge into existing collectedData (backend SSOT via contextVersion)
            setCollectedData((prev) => syncContextFromSearchResult(searchResult, prev));

            // Update validation/schema state so sidebar re-renders with new values
            if (searchResult.productType || schema) {
              setState((prev) => ({
                ...prev,
                requirementSchema: schema as any,
                productType: searchResult.productType || prev.productType,
                currentProductType: searchResult.productType || prev.currentProductType,
                validationResult: {
                  ...(prev.validationResult as any),
                  validationAlert: searchResult.validationAlert || (
                    (searchResult.nextStep === "awaitMissingInfo" || searchResult.nextStep === "awaitAllSpecs")
                      ? { missingFields: searchResult.missingFields || [], message: "" }
                      : null
                  ),
                  isComplete: searchResult.nextStep !== "awaitMissingInfo" && searchResult.nextStep !== "awaitAllSpecs",
                  detectedSchema: schema as any,
                  providedRequirements: mergedData,
                  productType: searchResult.productType || prev.validationResult?.productType || "",
                  specifiedVendors: searchResult.specifiedVendors || prev.validationResult?.specifiedVendors,
                  specifiedModelFamilies: searchResult.specifiedModelFamilies || prev.validationResult?.specifiedModelFamilies,
                  requirementSchema: schema,
                },
              }));
            }
          }

          await streamAssistantMessage(searchResult.message);

          // Always undock sidebar so user can see the updated fields
          setIsDocked(false);

          // Update the workflow step
          if (searchResult.nextStep) {
            setCurrentStep(searchResult.nextStep as ConversationStep);
          }

          setState((prev) => ({ ...prev, isLoading: false }));
          return;
        }

        // ─── Update validation state if present ──────────────────
        if (searchResult.productType) {
          const schema = searchResult.requirementSchema || { mandatoryRequirements: {}, optionalRequirements: {}, advancedRequirements: {} };
          const mergedData = resolveCollectedDataFromSearchResult(searchResult);

          console.log('[SEARCH] Received mappedRequirements:', searchResult.mappedRequirements);
          console.log('[SEARCH] Received schema:', schema);
          console.log('[SEARCH] Standard specs:', searchResult.standardSpecs);
          console.log('[SEARCH] Standard specs source:', searchResult.standardSpecsSource);

          console.log('[SEARCH] Flattened data:', mergedData);
          console.log('[SEARCH] Flattened data keys:', Object.keys(mergedData));
          console.log('[SEARCH] Sample flattened values:', {
            measurementPrinciple: mergedData['mandatoryRequirements.Performance.measurementPrinciple'],
            materials: mergedData['mandatoryRequirements.Mechanical.materials'],
            outputSignal: mergedData['mandatoryRequirements.Electrical.outputSignal'],
            ingressProtection: mergedData['mandatoryRequirements.Environmental.ingressProtection']
          });

          setCollectedData((prev) => {
            const updated = syncContextFromSearchResult(searchResult, prev);
            console.log('[SEARCH] Updated collectedData (sample):', {
              measurementPrinciple: updated['mandatoryRequirements.Performance.measurementPrinciple'],
              materials: updated['mandatoryRequirements.Mechanical.materials'],
              totalKeys: Object.keys(updated).length,
              contextVersion: searchResult.contextVersion,
            });
            return updated;
          });
          setState((prev) => ({
            ...prev,
            requirementSchema: schema,
            productType: searchResult.productType,
            currentProductType: searchResult.productType || null,
            validationResult: {
              validationAlert: searchResult.validationAlert || null,
              isComplete: !searchResult.validationAlert,
              detectedSchema: searchResult.requirementSchema as any,
              providedRequirements: mergedData,
              productType: searchResult.productType!,
              specifiedVendors: searchResult.specifiedVendors,
              specifiedModelFamilies: searchResult.specifiedModelFamilies,
              strategy: searchResult.strategy,
              requirementSchema: schema,
            },
          }));
        }

        // ─── Stream the assistant message ────────────────────────
        if (searchResult.message) {
          await streamAssistantMessage(searchResult.message);
        }

        // ─── Undock sidebar after first substantive response ─────
        // Open sidebar whenever we have a meaningful step with schema data
        const sidebarSteps = ["awaitMissingInfo", "awaitAdditionalAndLatestSpecs", "awaitAdvancedSpecs", "awaitAllSpecs", "showSummary"];
        if (searchResult.nextStep && sidebarSteps.includes(searchResult.nextStep)) {
          setIsDocked(false);
        } else if (searchResult.nextStep && searchResult.nextStep !== "greeting" && searchResult.nextStep !== "initialInput") {
          setIsDocked(false);
        }

        // ─── Handle special step transitions ─────────────────────
        const nextStep = searchResult.nextStep || currentStep;

        // showSummary → trigger summary and analysis flow
        if (nextStep === "showSummary" && currentStep !== "showSummary") {
          setCurrentStep("showSummary");
          await handleShowSummaryAndProceed({ introAlreadyStreamed: true, skipAnalysis: true });
          setState((prev) => ({ ...prev, isLoading: false }));
          return;
        }

        // If already in showSummary and user confirms → run analysis
        if (nextStep === "showSummary" && currentStep === "showSummary") {
          const normalizedInput = trimmedInput.toLowerCase().replace(/\s/g, "");
          if (["yes", "proceed", "continue", "run", "analyze", "ok"].some(cmd => normalizedInput.includes(cmd))) {
            await performAnalysis();
            setState((prev) => ({ ...prev, isLoading: false }));
            return;
          }
        }

        // finalAnalysis / analysisError → handle rerun requests only (proceed starts via 202 + SSE above)
        if (nextStep === "finalAnalysis" || nextStep === "analysisError") {
          const normalizedInput = trimmedInput.toLowerCase().replace(/\s/g, "");
          if (["rerun", "run", "runagain"].some(cmd => normalizedInput.includes(cmd))) {
            await performAnalysis();
            setState((prev) => ({ ...prev, isLoading: false }));
            return;
          }
        }

        // ─── Set the next step ───────────────────────────────────
        setCurrentStep(nextStep as ConversationStep);

        setState((prev) => ({ ...prev, isLoading: false }));

      } catch (error) {
        console.error("Message handling error:", error);
        await streamAssistantMessage("I'm sorry, there was an error processing your message. Please try again.");
        toast({
          title: "Error",
          description: "There was an error processing your message. Please try again.",
          variant: "destructive",
        });
        setState((prev) => ({ ...prev, isLoading: false }));
      }
    },
    [currentStep, collectedData, state.productType, state.validationResult, state.requirementSchema, addMessage, performAnalysis, completeVendorAnalysis, handleShowSummaryAndProceed, streamAssistantMessage, isDocked, setIsDocked, searchInstanceId, userSessionId, advancedParameters, selectedAdvancedParams, vendorSearchParams, standardsEnabled, state.analysisResult, toast]
  );

  // Update ref when handleSendMessage changes
  useEffect(() => {
    handleSendMessageRef.current = handleSendMessage;
  }, [handleSendMessage]);

  // BroadcastChannel listener for receiving queries from other pages
  useEffect(() => {
    const channel = new BroadcastChannel('eng-route-handoff');

    const onMessage = (event: MessageEvent) => {
      const data: any = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type !== 'search_run_query') return;

      channel.postMessage({
        type: 'search_ack',
        requestId: data.requestId
      });

      // Focus this window to bring it to front
      window.focus();

      const incomingQuery = String(data.query || '').trim();
      if (!incomingQuery) return;

      // Set input value directly, user hits send manually
      setTimeout(() => {
        setState((prev) => ({ ...prev, inputValue: incomingQuery }));
      }, 0);
    };

    channel.addEventListener('message', onMessage);
    return () => {
      channel.removeEventListener('message', onMessage);
      channel.close();
    };
  }, []);

  const setInputValue = useCallback((value: string) => {
    setState((prev) => ({ ...prev, inputValue: value }));
  }, []);

  const handleRetry = useCallback(() => performAnalysis(), [performAnalysis]);

  // Handle URL parameters for auto-filling input (but not auto-submitting)
  useEffect(() => {
    // Check for sessionStorage key first (for large inputs from Requirements page)
    const inputKey = searchParams.get('inputKey');
    const queryKey = searchParams.get('queryKey');
    let inputParam = searchParams.get('input');

    if (queryKey) {
      // Check for queryKey (from Project routing)
      const storedInput = sessionStorage.getItem(queryKey) || localStorage.getItem(queryKey);
      if (storedInput) {
        inputParam = storedInput;
        sessionStorage.removeItem(queryKey);
        localStorage.removeItem(queryKey);
      }
    } else if (inputKey) {
      // Retrieve from sessionStorage and clean up (legacy)
      const storedInput = sessionStorage.getItem(inputKey);
      if (storedInput) {
        inputParam = storedInput;
        sessionStorage.removeItem(inputKey);
      }
    }

    // Prefer prop-based initial input when provided (for embedded tabs)
    if (!inputParam && initialInput) {
      inputParam = initialInput;
    }

    if (inputParam && !hasAutoSubmitted) {
      // If a saved conversation already has messages, do not auto-fill the input
      const hasSavedMessages = savedMessages && savedMessages.length > 0;
      if (hasSavedMessages) {
        // Avoid overwriting the restored empty input for previously-run conversations
        console.log(`[${searchInstanceId}] Skipping auto-fill from initialInput because saved messages exist`);
      } else {
        // Only set the input value, don't auto-submit - let user decide when to submit
        setState((prev) => ({ ...prev, inputValue: inputParam }));
        setHasAutoSubmitted(true); // Mark as processed to avoid re-setting
      }
    }
  }, [searchParams, hasAutoSubmitted, initialInput, savedMessages, searchInstanceId]);

  return (

    <div
      className={`flex flex-col ${fillParent ? 'h-full' : 'h-screen w-full animate-in fade-in duration-300 overflow-hidden custom-visible-scrollbar-dark'} text-foreground app-glass-gradient !min-h-0 ${fillParent ? '' : 'pt-24'}`}
      ref={containerRef}
    >
      {/* Decorative background images */}
      {!fillParent && (
        <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
            <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
        </div>
      )}
      {/* MAIN HEADER - Only show when not embedded in another page */}
      {!fillParent && (
        <MainHeader onSave={onSave} onDownloadWorkflow={() => setIsDownloadDialogOpen(true)} />
      )}

      {/* Left corner dock button - only show if there is collected data or validation result */}
      {(Object.keys(collectedData).length > 0 || state.validationResult) && (
        <Button
          variant="ghost"
          size="icon"
          className="fixed top-32 left-0 z-20 btn-glass-secondary border-0 shadow-lg rounded-l-none"
          onClick={() => setIsDocked(!isDocked)}
          aria-label={isDocked ? "Expand left panel" : "Collapse left panel"}
        >
          {isDocked ? <ChevronRight /> : <ChevronLeft />}
        </Button>
      )}

      {/* Right corner dock button - only show if there is an analysis result */}
      {!!state.analysisResult && (
        <Button
          variant="ghost"
          size="icon"
          className="fixed top-32 right-0 z-50 btn-glass-secondary border-0 shadow-lg rounded-r-none"
          onClick={() => setIsRightDocked(!isRightDocked)}
          aria-label={isRightDocked ? "Expand right panel" : "Collapse right panel"}
        >
          {isRightDocked ? <ChevronLeft /> : <ChevronRight />}
        </Button>
      )}

      <div className="flex flex-1 overflow-hidden">
        <div
          className="h-full flex flex-col relative transition-all duration-500 ease-in-out"
          style={{
            width: `${widths.left}%`,
            minWidth: widths.left === 0 ? "0%" : "7%",
            willChange: "width, opacity",
            overflow: "hidden",
            opacity: isDocked ? 0 : 1
          }}
        >
          <LeftSidebar
            validationResult={state.validationResult}
            requirementSchema={state.requirementSchema}
            currentProductType={state.currentProductType}
            collectedData={collectedData}
            isDocked={isDocked}
            setIsDocked={setIsDocked}
            fieldDescriptions={fieldDescriptions}
            onFieldDescriptionsChange={handleFieldDescriptionsChange}
            onScroll={(val) => handleScrollUpdate({ section: 'left', value: val })}
            initialScrollTop={scrollPositionsRef.current.left}
          />
        </div>

        {widths.left > 0 && (
          <div
            className={`w-1.5 cursor-col-resize transition-colors duration-500 ease-in-out ${draggingHandle === "left"
              ? "bg-[#5FB3E6]"
              : "bg-border hover:bg-[#5FB3E6]"
              }`}
            style={{ height: "100%", zIndex: 20 }}
            onMouseDown={(e) => handleMouseDown(e, "left")}
          />
        )}

        <div
          ref={centerScrollRef}
          onScroll={(e) => handleScrollUpdate({ section: 'center', value: e.currentTarget.scrollTop })}
          className="h-full transition-all duration-500 ease-in-out overflow-auto flex flex-col glass-sidebar relative"
          style={{ width: `${100 - (widths.left > 0 ? widths.left : 0) - (widths.right > 0 ? widths.right : 0)}%`, minWidth: "5%", willChange: "width" }}
        >
          <ChatInterface
            messages={state.messages}
            onSendMessage={handleSendMessage}
            isLoading={state.isLoading}
            isStreaming={isStreaming}
            streamId={streamId}
            inputValue={state.inputValue}
            setInputValue={setInputValue}
            currentStep={currentStep}
            isValidationComplete={!!state.validationResult}
            productType={state.currentProductType}
            collectedData={collectedData}
            vendorAnalysisComplete={!!state.analysisResult}
            onRetry={handleRetry}
            searchInstanceId={searchInstanceId}
            onCacheOpen={handleCacheOpen}
            onCachePreview={(projId) => {
              setSelectedCacheProjectId(projId);
              setCacheConfirmationOpen(true);
              handleCachePreview(projId);
            }}
            onCacheIgnore={handleCacheIgnore}
            headerRightContent={
              <div
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#212121] border border-white/10 shadow-lg"
              >
                <label
                  htmlFor="standards-toggle-search"
                  className="text-[12px] text-zinc-300 cursor-pointer font-semibold tracking-wide select-none whitespace-nowrap"
                >
                  Apply standards
                </label>
                <Switch
                  id="standards-toggle-search"
                  checked={standardsEnabled}
                  onCheckedChange={setStandardsEnabled}
                  className="data-[state=checked]:bg-sky-500 scale-[0.8] origin-right"
                />
              </div>
            }
          />
        </div>

        {widths.right > 0 && (
          <div
            className={`w-1.5 cursor-col-resize transition-colors duration-500 ease-in-out ${draggingHandle === "right"
              ? "bg-[#5FB3E6]"
              : "bg-border hover:bg-[#5FB3E6]"
              }`}
            style={{ height: "100%", zIndex: 20 }}
            onMouseDown={(e) => handleMouseDown(e, "right")}
          />
        )}

        <div
          className="h-full transition-all duration-500 ease-in-out"
          style={{
            width: `${widths.right}%`,
            minWidth: widths.right === 0 ? "0%" : "7%",
            willChange: "width, opacity",
            overflow: "hidden",
            opacity: isRightDocked ? 0 : 1
          }}
        >
          <RightPanel
            analysisResult={state.analysisResult}
            productType={state.productType || state.currentProductType || ""}
            validationResult={undefined}
            requirementSchema={undefined}
            isDocked={isRightDocked}
            setIsDocked={setIsRightDocked}
            onPricingDataUpdate={handlePricingDataUpdate}
            userLocation={user?.location}
            onScroll={(val) => handleScrollUpdate({ section: 'right', value: val })}
            initialScrollTop={scrollPositionsRef.current.right}
            onDownloadWorkflow={() => setIsDownloadDialogOpen(true)}
          />
        </div>
      </div>

      {/* Repeated Request Dialog */}
      <Dialog open={cacheConfirmationOpen} onOpenChange={setCacheConfirmationOpen}>
        <DialogContent className="max-w-3xl bg-white border-slate-200 text-slate-900 shadow-2xl overflow-hidden rounded-xl">
          <DialogHeader className="border-b border-slate-100 pb-4">
            <DialogTitle className="text-xl font-bold flex items-center gap-2 text-sky-600">
              <span className="flex h-3 w-3 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-sky-500"></span>
              </span>
              Repeated Request Detected
            </DialogTitle>
            <DialogDescription className="text-slate-500 text-sm">
              {cacheConfirmationData?.message || "I see that you saved a similar project recently. How would you like to proceed?"}
            </DialogDescription>
          </DialogHeader>

          <div className="py-6 grid grid-cols-1 md:grid-cols-2 gap-6 min-h-[300px] max-h-[500px] overflow-y-auto pr-2 custom-visible-scrollbar-dark">
            {/* Matches List */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Matching Projects</h3>
              <div className="space-y-2">
                {cacheConfirmationData?.matchedProjects?.map((proj: any) => {
                  const projId = proj.projectId || proj.project_id;
                  const isSelected = selectedCacheProjectId === projId;
                  return (
                    <div
                      key={projId}
                      onClick={() => {
                        setSelectedCacheProjectId(projId);
                        handleCachePreview(projId);
                      }}
                      className={`p-3 rounded-lg border cursor-pointer transition-all duration-200 ${
                        isSelected
                          ? "bg-sky-50 border-sky-500 shadow-md shadow-sky-500/10"
                          : "bg-slate-50/50 border-slate-200 hover:bg-slate-100/50 hover:border-slate-300"
                      }`}
                    >
                      <div className="flex justify-between items-start">
                        <div className="font-semibold text-slate-800 truncate max-w-[180px]">
                          {proj.projectName || proj.project_name || "Untitled Project"}
                        </div>
                        {proj.similarity !== undefined && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-sky-100 text-sky-700 border border-sky-200">
                            {Math.round(proj.similarity * 100)}% Match
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500 mt-1 flex flex-col gap-0.5">
                        <span>Category: {proj.productType || proj.product_type || "N/A"}</span>
                        <span>Saved: {proj.updatedAt || proj.updated_at ? new Date(proj.updatedAt || proj.updated_at).toLocaleString() : "Unknown"}</span>
                      </div>
                    </div>
                  );
                })}
                {(!cacheConfirmationData?.matchedProjects || cacheConfirmationData.matchedProjects.length === 0) && (
                  <div className="text-slate-400 text-xs py-4 text-center">No projects found.</div>
                )}
              </div>
            </div>

            {/* Preview Section */}
            <div className="bg-slate-50/50 rounded-xl border border-slate-200 p-4 flex flex-col h-full min-h-[250px]">
              <h3 className="text-sm font-semibold text-slate-500 mb-3 uppercase tracking-wider">Project Preview</h3>
              {isPreviewLoading ? (
                <div className="flex-1 flex flex-col items-center justify-center text-slate-500 gap-2">
                  <span className="h-6 w-6 animate-spin rounded-full border-2 border-sky-500 border-t-transparent" />
                  <span className="text-xs">Fetching specifications...</span>
                </div>
              ) : previewProjectData ? (
                <div className="flex-1 overflow-y-auto text-xs space-y-3 custom-visible-scrollbar-dark pr-1">
                  <div>
                    <span className="text-slate-500 block font-medium">Project Name:</span>
                    <span className="text-slate-800 text-sm font-semibold">{previewProjectData.projectName || previewProjectData.project_name || "Untitled"}</span>
                  </div>
                  
                  {previewProjectData.productType || previewProjectData.product_type ? (
                    <div>
                      <span className="text-slate-500 block font-medium">Product Type:</span>
                      <span className="text-slate-800 font-semibold">{previewProjectData.productType || previewProjectData.product_type}</span>
                    </div>
                  ) : null}

                  {/* If Solution project (instruments/accessories) */}
                  {((previewProjectData.identified_instruments || previewProjectData.instruments || []).length > 0 ||
                    (previewProjectData.identified_accessories || previewProjectData.accessories || []).length > 0) ? (
                    <div className="space-y-3 pt-3 border-t border-slate-200">
                      {(previewProjectData.identified_instruments || previewProjectData.instruments || []).length > 0 && (
                        <div className="space-y-1.5">
                          <span className="text-slate-500 font-semibold text-[11px] uppercase tracking-wider block">Instruments ({(previewProjectData.identified_instruments || previewProjectData.instruments).length}):</span>
                          <div className="flex flex-wrap gap-1.5">
                            {(previewProjectData.identified_instruments || previewProjectData.instruments).map((inst: any, idx: number) => (
                              <div 
                                key={idx} 
                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-100/70 shadow-sm transition-all hover:bg-sky-100 hover:scale-[1.02]"
                              >
                                <Cpu className="h-3 w-3 text-sky-500 flex-shrink-0" />
                                <span className="max-w-[150px] truncate" title={inst.productName || inst.product_name || inst.category}>
                                  {inst.productName || inst.product_name || inst.category}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {(previewProjectData.identified_accessories || previewProjectData.accessories || []).length > 0 && (
                        <div className="space-y-1.5 pt-1">
                          <span className="text-slate-500 font-semibold text-[11px] uppercase tracking-wider block">Accessories ({(previewProjectData.identified_accessories || previewProjectData.accessories).length}):</span>
                          <div className="flex flex-wrap gap-1.5">
                            {(previewProjectData.identified_accessories || previewProjectData.accessories).map((acc: any, idx: number) => (
                              <div 
                                key={idx} 
                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-100/70 shadow-sm transition-all hover:bg-emerald-100 hover:scale-[1.02]"
                              >
                                <Wrench className="h-3 w-3 text-emerald-500 flex-shrink-0" />
                                <span className="max-w-[150px] truncate" title={acc.accessoryName || acc.accessory_name || acc.category}>
                                  {acc.accessoryName || acc.accessory_name || acc.category}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : null}

                  {/* If Search project (search tabs) */}
                  {((previewProjectData.search_tabs || previewProjectData.searchTabs || []).length > 0) ? (
                    <div className="space-y-1 pt-2 border-t border-slate-200">
                      <span className="text-slate-500 font-medium block">Search Tabs ({(previewProjectData.search_tabs || previewProjectData.searchTabs).length}):</span>
                      <ul className="list-disc list-inside text-sky-600 pl-1 space-y-1">
                        {(previewProjectData.search_tabs || previewProjectData.searchTabs).map((tab: any, idx: number) => (
                          <li key={idx} className="truncate">
                            {tab.title || `Tab ${idx + 1}`} ({tab.input || "No query"})
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  {previewProjectData.initial_requirements || previewProjectData.initialRequirements ? (
                    <div className="pt-2 border-t border-slate-200">
                      <span className="text-slate-500 block font-medium">Initial Requirements:</span>
                      <p className="text-slate-700 italic text-[11px] line-clamp-3 bg-slate-100 p-2 rounded mt-1 border border-slate-200">
                        "{previewProjectData.initial_requirements || previewProjectData.initialRequirements}"
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
                  <span className="text-xs text-center px-4">Select a project and click Preview to view its configuration.</span>
                  {selectedCacheProjectId && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-2 bg-sky-50 text-sky-600 hover:bg-sky-100 border-sky-200 text-xs"
                      onClick={() => handleCachePreview(selectedCacheProjectId)}
                    >
                      Preview Details
                    </Button>
                  )}
                </div>
              )}
            </div>
          </div>

          <DialogFooter className="border-t border-slate-200 pt-4 flex gap-2 sm:justify-end">
            <Button
              variant="ghost"
              onClick={handleCacheIgnore}
              className="text-slate-500 hover:text-slate-700 hover:bg-slate-100"
            >
              Ignore & Run Fresh
            </Button>
            {selectedCacheProjectId && (
              <Button
                variant="outline"
                onClick={() => handleCachePreview(selectedCacheProjectId)}
                className="bg-white hover:bg-slate-100 text-slate-700 border-slate-200"
              >
                Preview
              </Button>
            )}
            <Button
              onClick={() => handleCacheOpen(selectedCacheProjectId)}
              disabled={!selectedCacheProjectId}
              className="bg-sky-600 hover:bg-sky-500 text-white font-semibold shadow-sm"
            >
              Open Project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Download Search Workflow Data Dialog */}
      <DownloadSearchWorkflowDialog
        open={isDownloadDialogOpen}
        onOpenChange={setIsDownloadDialogOpen}
        exportParams={exportWorkflowParams}
      />
    </div>
  );
};

export default AIRecommender;
