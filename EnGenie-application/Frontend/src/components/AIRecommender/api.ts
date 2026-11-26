// api.ts - API functions for AIRecommender
import axios from "axios";
import { playNotificationSound } from "@/utils/sound";
import { streamJobEvents } from "./wsClient";
import {
  ValidationResult,
  AnalysisResult,
  RequirementSchema,
  UserCredentials,
  ChatMessage,
  IntentClassificationResult,
  AgentResponse,
  SearchAgentResult,
  AnalysisImageResult,
  ProjectIntentResult,
} from "./types";

export const BASE_URL: string = import.meta.env.DEV
  ? ""  // Use Vite proxy in development (same-origin, avoids CORS issues in new tabs)
  : (import.meta.env.VITE_BACKEND_URL || "https://api.engenieai.com");

axios.defaults.baseURL = BASE_URL;
axios.defaults.withCredentials = true;

// Add request interceptor to include JWT token in Authorization header
// This bypasses third-party cookie blocking in modern browsers
axios.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

console.log(`[API] Using backend: ${BASE_URL}`);

// ============================================================
// CSRF TOKEN MANAGEMENT (Security Fix #1)
// ============================================================

let csrfToken: string | null = null;

/**
 * Fetch CSRF token from backend.
 * This should be called once on app initialization.
 */
export const fetchCsrfToken = async (): Promise<string> => {
  try {
    const response = await axios.get('/api/csrf-token');
    csrfToken = response.data.csrfToken;
    console.log('[CSRF] Token fetched successfully');
    return csrfToken;
  } catch (error) {
    console.error('[CSRF] Failed to fetch token:', error);
    throw error;
  }
};

/**
 * Get current CSRF token (returns cached token or fetches new one)
 */
export const getCsrfToken = async (): Promise<string> => {
  if (csrfToken) {
    return csrfToken;
  }
  return await fetchCsrfToken();
};

// ============================================================
// AXIOS INTERCEPTOR - Auto-add CSRF token to all requests
// ============================================================

axios.interceptors.request.use(
  async (config) => {
    // Only add CSRF token to state-changing requests (POST, PUT, DELETE, PATCH)
    const methodsRequiringCsrf = ['post', 'put', 'delete', 'patch'];

    if (config.method && methodsRequiringCsrf.includes(config.method.toLowerCase())) {
      try {
        const token = await getCsrfToken();
        config.headers['X-CSRFToken'] = token;
      } catch (error) {
        console.error('[CSRF] Failed to add token to request:', error);
      }
    }

    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// ============================================================
// AXIOS RESPONSE INTERCEPTOR - Refresh token on 403/400 CSRF errors
// ============================================================

axios.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Check if error is CSRF-related (400 with CSRF message)
    const isCsrfError =
      error.response?.status === 400 &&
      error.response?.data?.error?.toLowerCase().includes('csrf');

    // If CSRF error and haven't retried yet, refresh token and retry
    if (isCsrfError && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        console.log('[CSRF] Token invalid, refreshing...');
        await fetchCsrfToken();

        // Retry original request with new token
        const token = await getCsrfToken();
        originalRequest.headers['X-CSRFToken'] = token;
        return axios(originalRequest);
      } catch (refreshError) {
        console.error('[CSRF] Token refresh failed:', refreshError);
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

interface User {
  username: string;
  name: string;
  email: string;
  // Add other user properties if needed
}

// REMOVED: Vendor interface (lines 129-132) - getVendors() removed
// REMOVED: PdfSearchResult interface (lines 141-145) - searchPdfs() removed

interface PendingUser {
  id: number;
  username: string;
  email: string;
}
interface PriceReviewResponse {
  productName: string;
  results: Array<{
    price: string | null;
    reviews: number | null;
    source: string | null;
  }>;
  totalResults?: number;  // Total results available (before 10-result limit)
}

/**
 * Converts snake_case or kebab-case keys to camelCase recursively.
 */
function convertKeysToCamelCase(obj: any): any {
  if (Array.isArray(obj)) {
    return obj.map((v) => convertKeysToCamelCase(v));
  } else if (obj !== null && typeof obj === "object") {
    return Object.keys(obj).reduce((acc: Record<string, any>, key: string) => {
      const camelKey = key.replace(/([-_][a-z])/g, (group) =>
        group.toUpperCase().replace("-", "").replace("_", "")
      );
      acc[camelKey] = convertKeysToCamelCase(obj[key]);
      return acc;
    }, {});
  }
  return obj;
}

/**
 * Normalizes user input by removing backslashes, underscores, and hyphens and converting to lowercase.
 */
function normalizeUserInput(input: string): string {
  return input.replace(/[\\_-]/g, "").toLowerCase();
}

/**
 * Validates if an email address has a real domain (checks MX records on the backend).
 * Returns { valid: boolean, error?: string }
 */
export const validateEmail = async (
  email: string
): Promise<{ valid: boolean; error?: string; message?: string }> => {
  try {
    const response = await axios.post(`/api/validate-email`, { email });
    return response.data;
  } catch (error: any) {
    console.error("Email validation error:", error.response?.data || error.message);
    // If validation endpoint fails, don't block the user
    return { valid: true, message: "Validation unavailable" };
  }
};

/**
 * Sends a 6-digit OTP verification code to the given email address.
 */
export const sendOtp = async (
  email: string
): Promise<{ success: boolean; message?: string; error?: string }> => {
  try {
    const response = await axios.post(`/api/send-otp`, { email });
    return response.data;
  } catch (error: any) {
    console.error("Send OTP error:", error.response?.data || error.message);
    return { success: false, error: error.response?.data?.error || "Failed to send verification code" };
  }
};

/**
 * Verifies the OTP code entered by the user.
 */
export const verifyOtp = async (
  email: string,
  otp: string
): Promise<{ verified: boolean; message?: string; error?: string }> => {
  try {
    const response = await axios.post(`/api/verify-otp`, { email, otp });
    return response.data;
  } catch (error: any) {
    console.error("Verify OTP error:", error.response?.data || error.message);
    return { verified: false, error: error.response?.data?.error || "Verification failed" };
  }
};

/**
 * Signs in or registers a user via Microsoft (Azure AD SSO).
 * Backend verifies the user against Azure AD and either logs in or creates a new account.
 */
export const microsoftSignIn = async (
  accessToken: string,
  email: string,
  name?: string
): Promise<{ success: boolean; message?: string; error?: string; isNewUser?: boolean; user?: any }> => {
  try {
    const response = await axios.post(`/api/microsoft-signin`, {
      accessToken,
      email,
      name
    });
    return response.data;
  } catch (error: any) {
    console.error("Microsoft Sign-In error:", error.response?.data || error.message);
    return {
      success: false,
      error: error.response?.data?.error || "Microsoft Sign-In failed"
    };
  }
};

/**
 * Signs up a new user via Microsoft (Azure AD SSO).
 * Backend verifies the user against Azure AD and creates a new account (status: pending).
 */
export const microsoftSignUp = async (
  accessToken: string,
  email: string,
  name?: string
): Promise<{ success: boolean; message?: string; error?: string; isPending?: boolean; user?: any }> => {
  try {
    const response = await axios.post(`/api/microsoft-signup`, {
      accessToken,
      email,
      name
    });
    return response.data;
  } catch (error: any) {
    console.error("Microsoft Sign-Up error:", error.response?.data || error.message);
    return {
      success: false,
      error: error.response?.data?.error || "Microsoft Sign-Up failed"
    };
  }
};

/**
 * Registers a new user (status is set to 'pending' on backend).
 */
export const signup = async (
  credentials: UserCredentials
): Promise<{ message: string }> => {
  try {
    const response = await axios.post(`/register`, credentials);
    return response.data;
  } catch (error: any) {
    console.error("Signup error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Signup failed");
  }
};

/**
 * Logs a user in; will fail if user status is not 'active'.
 * Returns user info and JWT token for cross-origin authentication.
 */
export const login = async (
  credentials: Omit<UserCredentials, "email">
): Promise<{ message: string; user: User; token?: string }> => {
  try {
    const response = await axios.post(`/login`, credentials);
    return convertKeysToCamelCase(response.data) as { message: string; user: User; token?: string };
  } catch (error: any) {
    console.error("Login error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Login failed");
  }
};

/**
 * Logs out the current user.
 */
export const logout = async (): Promise<{ message: string }> => {
  try {
    const response = await axios.post(`/logout`);
    return response.data;
  } catch (error: any) {
    console.error("Logout error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Logout failed");
  }
};

/**
 * Updates the user's profile (first name, last name, username, company, location).
 */
export const updateProfile = async (
  data: { first_name?: string; last_name?: string; username?: string; company?: string; location?: string }
): Promise<any> => {
  try {
    const response = await axios.post(`/api/update_profile`, data);
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Profile update error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Profile update failed");
  }
};

/**
 * Checks if the user is authenticated, returning user info or null if not authenticated.
 */
export const checkAuth = async (): Promise<{ user: User } | null> => {
  try {
    const response = await axios.get(`/user`);
    return convertKeysToCamelCase(response.data) as { user: User };
  } catch (error: any) {
    if (error.response && error.response.status === 401) {
      console.log("Authentication check failed: User is not logged in.");
      return null;
    }
    console.error("Unexpected error during authentication check:", error);
    return null;
  }
};

// REMOVED: getVendors() function (lines 358-372) - /vendors endpoint removed (not used by frontend)

/**
 * Fetches the submodel to model series mapping.
 * This is used to map analysis results (submodel names) to images (model series names).
 */
export const getSubmodelMapping = async (): Promise<Record<string, string>> => {
  try {
    const response = await axios.get(`/submodel-mapping`);
    return convertKeysToCamelCase(response.data.mapping) as Record<string, string>;
  } catch (error: any) {
    console.error("Failed to fetch submodel mapping:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to fetch submodel mapping");
  }
};





/**
 * Initialize a new search session
 */
export const initializeNewSearch = async (searchInstanceId: string, userSessionId?: string | null): Promise<void> => {
  try {
    const payload: any = {
      search_session_id: searchInstanceId,
      reset: true
    };

    if (userSessionId) {
      payload.user_session_id = userSessionId;
    }

    await axios.post('/new-search', payload);
    console.log(`[NEW_SEARCH] Initialized search session: ${searchInstanceId}`);
  } catch (error: any) {
    console.error("Failed to initialize new search session:", error.response?.data || error.message);
    // Don't throw error - continue with search even if initialization fails
  }
};

/**
 * Calls the unified /api/search-agent endpoint.
 * This is the SINGLE API call the frontend needs for the entire search workflow.
 * It handles intent classification, validation, conversational response generation,
 * and search execution — all in one round-trip.
 */
export const callSearchAgent = async (
  userInput: string,
  currentStep: string,
  searchInstanceId?: string,
  userSessionId?: string | null,
  options?: {
    currentIntent?: string;
    collectedData?: Record<string, any>;
    productType?: string;
    availableParameters?: any[];
    selectedParameters?: Record<string, any>;
    totalSelected?: number;
    missingFields?: string[];
    analysisResult?: any;
    skipStandardRag?: boolean;
    streamId?: string;
  }
): Promise<SearchAgentResult> => {
  try {
    const payload: any = {
      user_input: userInput.trim(),
      current_step: currentStep,
    };

    if (searchInstanceId) payload.session_id = searchInstanceId;
    // user_session_id omitted to prevent tab memory leaking
    if (options?.currentIntent) payload.current_intent = options.currentIntent;
    if (options?.collectedData) payload.collected_data = options.collectedData;
    if (options?.productType) payload.product_type = options.productType;
    if (options?.availableParameters) payload.available_parameters = options.availableParameters;
    if (options?.selectedParameters) payload.selected_parameters = options.selectedParameters;
    if (options?.totalSelected !== undefined) payload.total_selected = options.totalSelected;
    if (options?.missingFields) payload.missing_fields = options.missingFields;
    if (options?.analysisResult) payload.analysis_result = options.analysisResult;
    if (options?.skipStandardRag !== undefined) payload.skip_standard_rag = options.skipStandardRag;
    if (options?.streamId) payload.stream_id = options.streamId;

    const response = await axios.post(`/api/search-agent`, payload);
    const data = response.data || {};
    return {
      ...data,
      streamId: data.streamId || data.stream_id,
      nextStep: data.nextStep ?? data.next_step,
      status: data.status,
    } as SearchAgentResult;
  } catch (error: any) {
    console.error("Search agent error:", error.response?.data || error.message);
    return {
      success: false,
      intent: "error",
      message: error.response?.data?.message || "Search agent call failed. Please try again.",
      nextStep: currentStep,
    };
  }
};








/** Fetch persisted search session context from backend (SSOT for sidebar specs). */
export const getSearchContext = async (
  searchInstanceId: string,
): Promise<SearchAgentResult | null> => {
  try {
    const response = await axios.get("/api/search-context", {
      params: { session_id: searchInstanceId },
    });
    if (!response.data?.success) return null;
    return response.data as SearchAgentResult;
  } catch (error: any) {
    if (error.response?.status === 404) return null;
    console.warn("[SEARCH_CONTEXT] Failed to load persisted context:", error.response?.data || error.message);
    return null;
  }
};

// REMOVED: getRequirementSchema() function (lines 480-499) - /schema endpoint removed (not used by frontend)

// REMOVED: additionalRequirements function (never used)
// REMOVED: structureRequirements() function (lines 506-515) - /structure_requirements endpoint removed (redundant)

// REMOVED: discoverAdvancedParameters function (never called from frontend)
// REMOVED: addAdvancedParameters() function (lines 524-540) - /api/add_advanced_parameters endpoint removed (not used)

/**
 * Fetches a human-readable description for a schema field.
 */
export const getFieldDescription = async (
  field: string,
  productType: string | null
): Promise<{ description: string }> => {
  try {
    const response = await axios.post(`/api/get_field_description`, { field, product_type: productType });
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Field description fetch error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to fetch field description.");
  }
};

/**
 * Fetches human-readable descriptions for many schema fields in a single request.
 * Prefer this over calling getFieldDescription per-field: a full schema render can
 * involve 50-100+ fields, and firing that many individual POSTs serializes behind
 * the browser's per-host connection limit even though most are cache hits.
 */
export const getFieldDescriptionsBatch = async (
  fields: string[],
  productType: string | null
): Promise<Record<string, string>> => {
  try {
    const response = await axios.post(`/api/get_field_descriptions_batch`, {
      fields,
      product_type: productType,
    });
    // NOTE: deliberately does NOT go through convertKeysToCamelCase — the keys
    // of `descriptions` are literal field names (e.g. "p&id number"), not API
    // response keys, and must be returned unmodified so callers can look them
    // up by the same field string they requested.
    return (response.data?.descriptions ?? {}) as Record<string, string>;
  } catch (error: any) {
    console.error("Batched field description fetch error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to fetch field descriptions.");
  }
};

/**
 * Fetches the list of users pending approval (admin only).
 */
export const getPendingUsers = async (): Promise<PendingUser[]> => {
  try {
    const response = await axios.get(`/admin/pending_users`);
    const users = convertKeysToCamelCase(response.data.pendingUsers) as PendingUser[];
    return users;
  } catch (error: any) {
    console.error("Failed to fetch pending users:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to fetch pending users");
  }
};

/**
 * Admin approves or rejects a user.
 * @param userId - ID of the user to approve/reject.
 * @param action - "approve" or "reject".
 */
export const approveOrRejectUser = async (
  userId: number,
  action: "approve" | "reject"
): Promise<{ message: string }> => {
  try {
    const response = await axios.post(`/admin/approve_user`, { user_id: userId, action });
    return response.data;
  } catch (error: any) {
    console.error("Failed to update user status:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to update user status");
  }
};




// REMOVED: classifyIntent() function (lines 593-622) - /api/intent endpoint removed (not used by frontend)








// ====================================================================
// === REMOVED: PDF SEARCH AND VIEW FUNCTIONS ===
// ====================================================================
// REMOVED: searchPdfs() function (lines 640-649) - /api/search_pdfs endpoint removed (not used)
// REMOVED: viewPdf() function (lines 657-660) - /api/view_pdf endpoint removed (not used)

/**
 * Uploads a PDF to the backend for analysis by providing its URL.
 * @param url The URL of the PDF file.
 * @returns A promise that resolves with the analysis result.
 */




/**
 * Fetches price and reviews dynamically from the backend for a given product.
 * @param productName - Name of the product.
 * @returns An object with an array of results, each containing price, reviews, and source.
 */
export const getProductPriceReview = async (
  productName: string,
  vendorName?: string,
  modelFamily?: string,
  subModel?: string,
  productType?: string,
  userLocation?: string
): Promise<PriceReviewResponse> => {
  try {
    if (!productName) {
      throw new Error("productName is required");
    }

    const params: Record<string, string> = { productName };
    if (vendorName) params.vendorName = vendorName;
    if (modelFamily) params.modelFamily = modelFamily;
    if (subModel) params.subModel = subModel;
    if (productType) params.productType = productType;
    if (userLocation) params.userLocation = userLocation;

    const response = await axios.get("/api/get-price-review", { params });

    // The backend now returns a structured object with a 'results' array.
    // The response data matches the PriceReviewResponse interface.
    return convertKeysToCamelCase(response.data) as PriceReviewResponse;

  } catch (error: any) {
    console.error(
      `Failed to fetch price/review for product ${productName}:`,
      error.response?.data || error.message
    );
    // Return a default object with an empty results array on failure.
    return { productName: productName, results: [] };
  }
};

// --- NEW: Function to handle analysis feedback ---

/**
 * Submits user feedback (thumbs up/down and a comment) and gets an LLM-generated response.
 * @param feedbackType - 'positive' for thumbs up, 'negative' for thumbs down. Can be null if only a comment is provided.
 * @param comment - Optional text feedback from the user.
 * @returns A promise that resolves with the LLM's response string.
 */
export const submitFeedback = async (
  feedbackType: "positive" | "negative" | null,
  comment?: string,
  projectId?: string,
  itemMetadata?: {
    itemType?: string;
    itemName?: string;          // Instrument/Accessory/Product name
    vendorName?: string;
    category?: string;
    subcategory?: string;
    model?: string;
    modelFamily?: string;       // Model family (for search products)
    subModel?: string;          // Sub model (for search products)
    userQuery?: string;
    recommendationContext?: any;
    sessionId?: string;
    source?: string;
  }
): Promise<string> => {
  try {
    const body: any = {
      feedbackType,
      comment: comment || "",
      itemMetadata: itemMetadata || {}
    };
    if (projectId) body.projectId = projectId;

    const response = await axios.post("/api/feedback", body);
    // The backend returns a JSON object with a 'response' field.
    return response.data.response;
  } catch (error: any) {
    console.error(
      "Failed to submit feedback:",
      error.response?.data || error.message
    );
    throw new Error(
      error.response?.data?.error || "Submitting feedback failed"
    );
  }
};

// ====================================================================
// === NEW: PRIMARY CONVERSATION API CALL ===
// ====================================================================

/**
 * Sends the user's message to the central agent endpoint and gets a response.
 * This single function replaces the old validate, analyze, and sales-agent calls.
 * @param message The user's current message.
 * @param chatHistory The entire conversation history for context.
 * @returns A promise that resolves with the agent's string response.
 */
export const postConversationTurn = async (
  message: string,
  chatHistory: ChatMessage[]
): Promise<string> => {
  try {
    const response = await axios.post(`/api/conversation-turn`, {
      message,
      // Note: The backend uses the Flask session for secure state,
      // but sending history can be useful for stateless backends or context.
      history: chatHistory,
    });
    // The new backend endpoint returns a JSON object with a 'response' field.
    return response.data.response;
  } catch (error: any) {
    console.error("Conversation turn error:", error.response?.data || error.message);
    return "Sorry, I'm having trouble connecting right now. Please try again in a moment.";
  }
};

// ====================================================================
// === REMOVED: identifyInstruments() and modifyInstruments() ===
// ====================================================================
// These functions have been removed as they are redundant.
// Use callSolutionAgent() instead - it handles all intents internally:
// - Intent classification (requirements/modification/clarification)
// - Instrument identification
// - Instrument modification
// - Standards application
// - Complete response generation
// ====================================================================

// ====================================================================
// === NEW: PROJECT INTENT & RESPONSE APIs (Refactored Architecture) ===
// ====================================================================

/**
 * Calls the solution agent which handles all solution page processing internally.
 *
 * The agent internally:
 * - Classifies intent (requirements/modification/clarification)
 * - Routes to appropriate tools
 * - Identifies/modifies instruments
 * - Applies standards
 * - Returns complete response with instruments and accessories
 *
 * ASYNC ARCHITECTURE:
 * - Backend returns 202 Accepted immediately with stream_id
 * - This function connects to SSE to receive the actual result
 * - Prevents 504 Gateway Timeout for long-running requests
 *
 * @param userInput User's message/input
 * @param currentInstruments Optional - existing instruments list
 * @param currentAccessories Optional - existing accessories list
 * @param awaitingSingleItemConfirmation Optional - true if waiting for user confirmation
 * @returns A promise that resolves with complete solution agent result
 */
export const callSolutionAgent = async (
  userInput: string,
  currentInstruments?: any[],
  currentAccessories?: any[],
  awaitingSingleItemConfirmation?: boolean,
  searchInstanceId?: string,
  userSessionId?: string | null,
  streamId?: string,
  skipStandards?: boolean
): Promise<ProjectIntentResult> => {
  try {
    const payload: any = {
      user_input: userInput,
    };

    if (currentInstruments && currentInstruments.length > 0) {
      payload.current_instruments = currentInstruments;
    }
    if (currentAccessories && currentAccessories.length > 0) {
      payload.current_accessories = currentAccessories;
    }
    if (awaitingSingleItemConfirmation) {
      payload.awaiting_single_item_confirmation = true;
    }
    if (searchInstanceId) {
      payload.search_session_id = searchInstanceId;
    }

    if (userSessionId) {
      payload.user_session_id = userSessionId;
    }

    if (streamId) {
      payload.stream_id = streamId;
    }

    if (skipStandards !== undefined) {
      payload.skip_standards = skipStandards;
    }

    const response = await axios.post(`/api/solution-agent`, payload);

    // Handle async response (202 or proxied 200) - wait for result via SSE
    if ((response.status === 202 || response.status === 200) && response.data.stream_id && response.data.status === 'processing') {
      const resultStreamId = response.data.stream_id;
      console.log(`[SolutionAgent] Async processing started, stream_id: ${resultStreamId}`);

      // Wait for result via status polling with 30-minute timeout
      return await waitForSSEResult(resultStreamId, 1800000); // 30 minute timeout
    }

    // Fallback: If backend returns 200 with direct result
    let responseData = response.data;
    // Unwrap nested result objects to ensure we get the actual intent result
    while (responseData && responseData.result && !responseData.intent && !responseData.success) {
      responseData = responseData.result;
    }
    return convertKeysToCamelCase(responseData) as ProjectIntentResult;
  } catch (error: any) {
    console.error("Solution agent error:", error.response?.data || error.message);
    // Return a default fallback
    return {
      intent: 'error',
      confidence: 'low',
      reasoning: 'Agent processing failed',
      message: 'Failed to process your request. Please try again.',
      instruments: [],
      accessories: []
    };
  }
};

/**
 * Wait for the solution agent result via the SSE push stream.
 *
 * Opens GET /api/events/{streamId} and resolves when a "result" or "error"
 * event is pushed. Never rejects — on error/timeout/close it resolves with an
 * error-shaped ProjectIntentResult so callers can render a message.
 */
async function waitForSSEResult(streamId: string, timeoutMs: number): Promise<ProjectIntentResult> {
  const errorResult = (message: string, reasoning: string): ProjectIntentResult => ({
    success: false,
    intent: 'error',
    confidence: 'low',
    reasoning,
    message,
    instruments: [],
    accessories: [],
  });

  console.log(`[SSE] Streaming result: ${streamId}`);

  return new Promise<ProjectIntentResult>((resolve) => {
    let settled = false;
    const done = (result: ProjectIntentResult) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };

    streamJobEvents(streamId, {
      timeoutMs,
      onEvent: (type, data) => {
        console.log(`[SSE] Event: ${type} (stream: ${streamId})`);
        if (type === 'result' || type === 'task_complete') {
          playNotificationSound();
          if (type === 'result') {
            done(convertKeysToCamelCase(data) as ProjectIntentResult);
          }
        } else if (type === 'error') {
          done(errorResult(
            data?.error || data?.message || 'Failed to process your request. Please try again.',
            data?.message || 'Processing failed'
          ));
        }
      },
    })
      .then(() => done(errorResult(
        'Failed to process your request. Please try again.',
        'Stream closed without result'
      )))
      .catch((err: any) => done(err?.name === 'TimeoutError'
        ? errorResult('The request took too long. Please try again.', 'Request timed out')
        : errorResult('Failed to process your request. Please try again.', err?.message || 'Stream error')
      ));
  });
}

/**
 * Recovery fallback: the WS stream ended without a terminal event (dev-server
 * restart, proxy blip, watchdog close, dropped connection). The backend
 * persists the final result/error in Redis (stream:{id}:result), so poll the
 * status endpoint briefly before declaring the analysis dead — a job that
 * actually finished must not be reported to the user as a failure.
 */
async function pollForFinalResult(
  streamId: string,
  attempts = 6,
  intervalMs = 5000
): Promise<{ type: string; data: any } | null> {
  for (let i = 0; i < attempts; i++) {
    try {
      const resp = await axios.get(`/api/search-status/${streamId}`);
      const events: any[] = resp.data?.events || [];
      const terminal = events.find((e) => e?.type === 'result' || e?.type === 'error');
      if (terminal) {
        console.log(`[SEARCH_SSE] Recovered terminal '${terminal.type}' via status polling (stream: ${streamId})`);
        return terminal;
      }
    } catch {
      // transient fetch errors shouldn't abort recovery — keep polling
    }
    if (i < attempts - 1) await new Promise((r) => setTimeout(r, intervalMs));
  }
  console.warn(`[SEARCH_SSE] No terminal event recovered via polling (stream: ${streamId})`);
  return null;
}

/**
 * Waits for the search analysis result via the SSE push stream.
 * Used after POST /api/search-agent returns 202 (fire-and-forget background analysis).
 * Opens GET /api/events/{streamId} and resolves on the "result" event.
 * On stream close/timeout without a result, falls back to polling
 * /api/search-status/{streamId} for the persisted result before rejecting.
 */
export async function waitForSearchResult(
  streamId: string,
  timeoutMs = 1800000
): Promise<{ analysisResult: any; count: number } | null> {
  console.log(`[SEARCH_SSE] Streaming analysis result: ${streamId}`);

  return new Promise<{ analysisResult: any; count: number }>((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };

    // Settle from a terminal event recovered via polling, or fall back to the
    // given rejection when nothing could be recovered.
    const settleFromRecovered = (
      recovered: { type: string; data: any } | null,
      fallbackError: Error
    ) => {
      if (recovered?.type === 'result') {
        const data = recovered.data ?? {};
        finish(() => resolve({
          analysisResult: data?.analysisResult ?? data,
          count: data?.count ?? 0,
        }));
      } else if (recovered?.type === 'error') {
        const data = recovered.data ?? {};
        finish(() => reject(new Error(data?.error || data?.message || 'Analysis failed on server.')));
      } else {
        finish(() => reject(fallbackError));
      }
    };

    streamJobEvents(streamId, {
      timeoutMs,
      onEvent: (type, data) => {
        console.log(`[SEARCH_SSE] Event: ${type} (stream: ${streamId})`);
        if (type === 'result') {
          finish(() => resolve({
            analysisResult: data?.analysisResult ?? data,
            count: data?.count ?? 0,
          }));
        } else if (type === 'error') {
          finish(() => reject(new Error(data?.error || data?.message || 'Analysis failed on server.')));
        }
      },
    })
      .then(async () => {
        if (settled) return;
        console.warn(`[SEARCH_SSE] Stream closed without result — attempting recovery (stream: ${streamId})`);
        const recovered = await pollForFinalResult(streamId);
        settleFromRecovered(recovered, new Error('Stream closed without returning a result.'));
      })
      .catch(async (err: any) => {
        if (settled) return;
        if (err?.name === 'TimeoutError') {
          // The job may have finished but the terminal event got lost — check
          // the persisted result once before giving up.
          const recovered = await pollForFinalResult(streamId, 1, 0);
          settleFromRecovered(recovered, new Error('Analysis timed out after 30 minutes.'));
        } else {
          const recovered = await pollForFinalResult(streamId, 3, 5000);
          settleFromRecovered(recovered, err instanceof Error ? err : new Error(String(err)));
        }
      });
  });
}

// Backward compatibility alias
export const classifyProjectIntent = callSolutionAgent;

/**
 * Clears conversation memory for a session.
 *
 * Call this when:
 * - User closes a tab/project
 * - User starts a fresh project
 * - User explicitly wants to reset the conversation
 *
 * @param sessionId The session ID to clear memory for
 * @returns A promise that resolves when memory is cleared
 */
export const clearSessionMemory = async (
  sessionId: string
): Promise<{ success: boolean; message: string }> => {
  try {
    const response = await axios.post(`/api/clear-session-memory`, {
      session_id: sessionId,
    });
    return response.data;
  } catch (error: any) {
    console.error("Clear session memory error:", error.response?.data || error.message);
    return {
      success: false,
      message: "Failed to clear session memory",
    };
  }
};




// ====================================================================
// === UNIFIED ROUTE CLASSIFIER API ===
// ====================================================================

/**
 * Input category types returned by the route classifier
 */
export type InputCategory =
  | "empty_gibberish"
  | "greeting"
  | "farewell"
  | "gratitude"
  | "confirmation"
  | "question_help"
  | "chitchat"
  | "out_of_scope"
  | "complaint"
  | "question_general"
  | "route_solution"
  | "route_chat"
  | "route_search"
  | "error"
  | "unknown";

/**
 * Route classification result interface
 * 
 * For NON-ROUTING categories (greeting, chitchat, etc.):
 * - requiresRouting = false
 * - directResponse contains the message to display
 * - User stays on current page
 * 
 * For ROUTING categories (route_solution, route_chat, route_search):
 * - requiresRouting = true (if different from current page)
 * - requiresConfirmation = true (if routing to different page)
 * - confirmationMessage contains the prompt for user
 */
export interface RouteClassificationResult {
  category: InputCategory;                      // The classified input category
  targetPage: "solution" | "chat" | "search";
  currentPage: string;
  requiresRouting: boolean;                     // True if navigation to different page is needed
  requiresConfirmation: boolean;                // Legacy: always false now
  directResponse: string;                       // Response message shown to user (all categories)
  routingUrl: string;                           // URL to navigate to (e.g. "/chat", "/solution")
  originalQuery: string;                        // The original user query
  reasoning: string;
  // Legacy fields (kept for backward compatibility with old confirmation flow)
  confirmationMessage?: string;
  openingMessage?: string;
  declineMessage?: string;
  popupBlockedMessage?: string;
}

/**
 * Classifies user input and determines the best routing page.
 * This should be called on EVERY user message from ANY page.
 * 
 * The classifier handles:
 * - ROUTING: Determines if user should navigate to a different page
 * - NON-ROUTING: Handles greetings, questions, chitchat, out-of-scope inputs directly
 *
 * @param userInput User's message
 * @param currentPage The page the user is currently on ("solution", "chat", "search")
 * @returns A promise that resolves with the routing classification result
 *
 * @example
 * const result = await classifyRoute("Hello!", "solution");
 * if (result.directResponse) {
 *   // Non-routing category - show the direct response
 *   displayMessage(result.directResponse);
 * } else if (result.requiresConfirmation) {
 *   // Show confirmation dialog with result.confirmationMessage
 *   // If user confirms, navigate to result.targetPage
 * } else {
 *   // Continue normal flow on current page
 * }
 */
export const classifyRoute = async (
  userInput: string,
  currentPage: "solution" | "chat" | "search",
  searchInstanceId?: string,
  userSessionId?: string | null
): Promise<RouteClassificationResult> => {
  try {
    const payload: any = {
      user_input: userInput,
      current_page: currentPage
    };
    if (searchInstanceId) payload.search_session_id = searchInstanceId;
    if (userSessionId) payload.user_session_id = userSessionId;

    const response = await axios.post(`/api/route-classifier`, payload);
    return convertKeysToCamelCase(response.data) as RouteClassificationResult;
  } catch (error: any) {
    console.error("Route classification error:", error.response?.data || error.message);
    // Return a default fallback (stay on current page)
    return {
      category: "error",
      targetPage: currentPage,
      currentPage: currentPage,
      requiresConfirmation: false,
      requiresRouting: false,
      directResponse: "I'm having trouble processing your request. Please try again.",
      routingUrl: "",
      originalQuery: userInput,
      reasoning: "Classification failed, staying on current page"
    };
  }
};

/**
 * Route confirmation result interface
 */
export interface RouteConfirmationResult {
  action: "confirm" | "decline" | "unclear";
  message: string;
  proceedWithRouting: boolean;
  targetPage: string;
  originalQuery: string;
  reasoning: string;
}

/**
 * Classifies user's response to a routing confirmation prompt using LLM.
 * This endpoint handles yes/no/unclear responses when user is asked to navigate.
 *
 * @param userInput User's response to the confirmation
 * @param currentPage The page the user is currently on
 * @param targetPage The page the user was asked to navigate to
 * @param originalQuery The original query that triggered the routing
 * @returns A promise that resolves with the confirmation classification result
 */
export const confirmRouteResponse = async (
  userInput: string,
  currentPage: "solution" | "chat" | "search",
  targetPage: string,
  originalQuery: string,
  searchInstanceId?: string,
  userSessionId?: string | null
): Promise<RouteConfirmationResult> => {
  try {
    const payload: any = {
      user_input: userInput,
      current_page: currentPage,
      target_page: targetPage,
      original_query: originalQuery
    };
    if (searchInstanceId) payload.search_session_id = searchInstanceId;
    if (userSessionId) payload.user_session_id = userSessionId;

    const response = await axios.post(`/api/route-confirm`, payload);
    return convertKeysToCamelCase(response.data) as RouteConfirmationResult;
  } catch (error: any) {
    console.error("Route confirmation error:", error.response?.data || error.message);
    // Return unclear as fallback - frontend will treat as new input
    return {
      action: "unclear",
      message: "",
      proceedWithRouting: false,
      targetPage: currentPage,
      originalQuery: originalQuery,
      reasoning: "Confirmation classification failed"
    };
  }
};

/**
 * Gets images for specific analysis products with vendor logo
 * @param vendor Vendor name (e.g. "Emerson")
 * @param productType Product type (e.g. "Flow Transmitter")
 * @param productName Product name (e.g. "Rosemount 3051")
 * @param modelFamilies Array of model families (e.g. ["3051C", "3051S"])
 * @returns A promise that resolves with analysis image result containing top image, vendor logo, and all images
 */
export const getAnalysisProductImages = async (
  vendor: string,
  productType: string,
  productName: string,
  modelFamilies: string[]
): Promise<AnalysisImageResult> => {
  try {
    const response = await axios.post(`/api/get_analysis_product_images`, {
      vendor,
      product_type: productType,
      product_name: productName,
      model_families: modelFamilies
    });
    return convertKeysToCamelCase(response.data) as AnalysisImageResult;
  } catch (error: any) {
    console.error("Analysis image fetch error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to fetch analysis images");
  }
};

// Removed searchVendors API endpoint client call

// ==================== STRATEGY DOCUMENT API FUNCTIONS ====================

/**
 * Strategy document interface
 */
export interface StrategyDocument {
  _id?: string;
  userId?: string;
  vendorId: string;
  vendorName: string;
  category: string;
  subcategory: string;
  strategy: string;
  refinery: string;
  additionalComments: string;
  ownerName: string;
  createdAt?: string;
  updatedAt?: string;
  isActive?: boolean;
}

/**
 * Get all strategy documents for the current user
 * @param category Optional category filter
 * @returns A promise that resolves with the list of strategy documents
 */
export const getStrategyDocuments = async (category?: string): Promise<{
  success: boolean;
  documents: StrategyDocument[];
  totalCount: number;
}> => {
  try {
    const params = category ? { category } : {};
    const response = await axios.get(`/api/strategy-documents`, { params });
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Get strategy documents error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to get strategy documents");
  }
};

/**
 * Upload a single strategy document
 * @param document Strategy document data
 * @returns A promise that resolves with the created document ID
 */
export const uploadStrategyDocument = async (document: Partial<StrategyDocument>): Promise<{
  success: boolean;
  documentId: string;
  message: string;
}> => {
  try {
    const response = await axios.post(`/api/strategy-documents`, {
      vendor_id: document.vendorId,
      vendor_name: document.vendorName,
      category: document.category,
      subcategory: document.subcategory,
      strategy: document.strategy,
      refinery: document.refinery,
      additional_comments: document.additionalComments,
      owner_name: document.ownerName
    });
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Upload strategy document error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to upload strategy document");
  }
};

/**
 * Bulk upload strategy documents from a CSV file
 * @param file CSV file containing strategy documents
 * @returns A promise that resolves with upload results
 */
export const bulkUploadStrategyDocuments = async (file: File): Promise<{
  success: boolean;
  uploadedCount: number;
  documentIds: string[];
  message: string;
}> => {
  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`/api/strategy-documents/bulk`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Bulk upload strategy documents error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to bulk upload strategy documents");
  }
};

/**
 * Delete all strategy documents for the current user
 * @returns A promise that resolves with delete results
 */
export const deleteAllStrategyDocuments = async (): Promise<{
  success: boolean;
  deletedCount: number;
  message: string;
}> => {
  try {
    const response = await axios.delete(`/api/strategy-documents`);
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Delete strategy documents error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to delete strategy documents");
  }
};

/**
 * Import strategy documents from the default CSV file on the server
 * @returns A promise that resolves with import results
 */
export const importDefaultStrategyDocuments = async (): Promise<{
  success: boolean;
  uploadedCount: number;
  message: string;
}> => {
  try {
    const response = await axios.post(`/api/strategy-documents/import-default`);
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Import default strategy documents error:", error.response?.data || error.message);
    throw new Error(error.response?.data?.error || "Failed to import default strategy documents");
  }
};

/**
 * Strategy file extraction result interface
 */
export interface StrategyFileUploadResult {
  success: boolean;
  message: string;
  documentId?: string;
  filename?: string;
  fileType?: string;
  entryCount?: number;
  extractedData?: Array<{
    vendorName: string;
    category: string;
    subcategory: string;
    stratergy: string;
  }>;
  error?: string;
  extractedTextPreview?: string;
}

/**
 * Upload a strategy file (PDF, DOCX, TXT, Images) and extract structured strategy data using Gemini 2.5 Flash
 *
 * This function accepts any supported file format and sends it to the backend where:
 * 1. Text is extracted from the file (PDF, DOCX, images via OCR, etc.)
 * 2. Gemini 2.5 Flash LLM analyzes the text to extract structured strategy data
 * 3. The extracted data is stored in MongoDB
 *
 * @param file The file to upload (PDF, DOCX, TXT, JPG, PNG, etc.)
 * @returns A promise that resolves with the extraction results including extracted strategy data
 */
export const uploadStrategyFile = async (file: File): Promise<StrategyFileUploadResult> => {
  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`/api/upload-strategy-file`, formData);
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Strategy file upload error:", error.response?.data || error.message);

    // Return a structured error response
    return {
      success: false,
      message: error.response?.data?.error || "Failed to upload and process strategy file",
      error: error.response?.data?.error || error.message,
      extractedTextPreview: error.response?.data?.extracted_text_preview
    };
  }
};

// ====================================================================
// === PRODUCT INFO RAG API FUNCTIONS ===
// ====================================================================

/**
 * Chat RAG response interface
 */
export interface ChatRAGResponse {
  success: boolean;
  answer: string;
  source: "database" | "llm" | "pending_confirmation" | "user_declined" | "unknown";
  foundInDatabase: boolean;
  awaitingConfirmation: boolean;
  sourcesUsed: string[];
  resultsCount?: number;
  note?: string;
  error?: string;
}

/**
 * Query chat information using RAG (Retrieval-Augmented Generation)
 *
 * This function:
 * 1. Searches MongoDB for relevant product data
 * 2. If found, generates answer from database context
 * 3. If NOT found, asks user for confirmation to use LLM knowledge
 * 4. On confirmation, generates answer from LLM
 *
 * @param query User's question about products
 * @param sessionId Optional session identifier for tracking conversation state
 * @returns Promise resolving with RAG response including answer and source
 *
 * @example
 * // First query - data found in database
 * const response = await queryChat("What vendors have pressure transmitters?");
 * // response.source === "database"
 *
 * // Query - data not found
 * const response = await queryChat("What is HART protocol?");
 * // response.source === "pending_confirmation"
 * // response.awaitingConfirmation === true
 *
 * // User confirms with "yes"
 * const response = await queryChat("yes");
 * // response.source === "llm"
 */
export const queryChat = async (
  query: string,
  sessionId?: string
): Promise<ChatRAGResponse> => {
  try {
    const payload: any = { query };
    if (sessionId) {
      payload.session_id = sessionId;
    }

    const response = await axios.post(`/api/chat/query`, payload);
    return convertKeysToCamelCase(response.data) as ChatRAGResponse;
  } catch (error: any) {
    console.error("Chat RAG query error:", error.response?.data || error.message);
    return {
      success: false,
      answer: error.response?.data?.answer || "Sorry, I encountered an error. Please try again.",
      source: "unknown",
      foundInDatabase: false,
      awaitingConfirmation: false,
      sourcesUsed: [],
      error: error.message
    };
  }
};

/**
 * Clear the pending confirmation state for a chat session
 * Call this when user navigates away or wants to start fresh
 *
 * @param sessionId Optional session identifier
 */
export const clearChatSession = async (sessionId?: string): Promise<void> => {
  try {
    const payload: any = {};
    if (sessionId) {
      payload.session_id = sessionId;
    }
    await axios.post(`/api/chat/clear-session`, payload);
  } catch (error: any) {
    console.error("Clear chat session error:", error.response?.data || error.message);
  }
};

// ==================== STANDARDS DOCUMENT API FUNCTIONS ====================

/**
 * Standards document/file interface (stored in GridFS)
 */
export interface StandardsDocument {
  fileId: string;
  filename: string;
  contentType: string;
  uploadedAt?: string;
  size?: number;
}

// REMOVED: getStandardsDocuments() function (lines 1486-1499) - /api/standards-documents GET endpoint removed (not used)

/**
 * Standards file upload result interface
 */
export interface StandardsFileUploadResult {
  success: boolean;
  message: string;
  fileId?: string;
  filename?: string;
  size?: number;
  error?: string;
}

/**
 * Upload a standards file to GridFS (no extraction, file stored as-is)
 *
 * @param file The file to upload (PDF, DOCX, TXT, etc.)
 * @returns A promise that resolves with the upload result
 */
export const uploadStandardsFile = async (file: File): Promise<StandardsFileUploadResult> => {
  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`/api/upload-standards-file`, formData);
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Standards file upload error:", error.response?.data || error.message);

    return {
      success: false,
      message: error.response?.data?.error || "Failed to upload standards file",
      error: error.response?.data?.error || error.message
    };
  }
};

export interface AssetsFileUploadResult {
  success: boolean;
  message: string;
  filename?: string;
  blob_url?: string;
  document_id?: string;
  entry_count?: number;
  extracted_data?: any[];
  error?: string;
}

/**
 * Upload an assets file (PDF, DOCX, TXT, CSV, Images) and extract structured asset/equipment data
 *
 * @param file The file to upload (PDF, DOCX, TXT, CSV, JPG, PNG, etc.)
 * @returns A promise that resolves with the upload result
 */
export const uploadAssetsFile = async (file: File): Promise<AssetsFileUploadResult> => {
  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await axios.post(`/api/upload-assets-file`, formData);
    return convertKeysToCamelCase(response.data);
  } catch (error: any) {
    console.error("Assets file upload error:", error.response?.data || error.message);

    return {
      success: false,
      message: error.response?.data?.error || "Failed to upload assets file",
      error: error.response?.data?.error || error.message
    };
  }
};

// ====================================================================
// === ADMIN NOTIFICATION APIs ===
// ====================================================================

export interface AdminNotification {
  id: string;
  userId: number;
  username: string;
  userEmail: string;
  failedStep: string;
  errorMessage: string;
  page: string;
  isRead: boolean;
  createdAt: string;
  additionalContext: Record<string, any>;
}

export interface NotificationsResponse {
  notifications: AdminNotification[];
  totalCount: number;
  unreadCount: number;
}

/**
 * Fetches admin notifications.
 * @param limit - Max notifications to return (default 50)
 * @param skip - Pagination offset (default 0)
 * @param unreadOnly - If true, only return unread notifications
 */
export const getAdminNotifications = async (
  limit: number = 50,
  skip: number = 0,
  filter: string = "all"
): Promise<NotificationsResponse> => {
  try {
    const response = await axios.get(`/api/notifications`, {
      params: { limit, skip, filter }
    });
    return convertKeysToCamelCase(response.data) as NotificationsResponse;
  } catch (error: any) {
    console.error("Fetch notifications error:", error.response?.data || error.message);
    return { notifications: [], totalCount: 0, unreadCount: 0 };
  }
};

/**
 * Gets the unread notification count (for the badge).
 */
export const getUnreadNotificationCount = async (): Promise<number> => {
  try {
    const response = await axios.get(`/api/notifications/unread-count`);
    return response.data.unread_count || 0;
  } catch (error: any) {
    console.error("Unread count error:", error.response?.data || error.message);
    return 0;
  }
};

/**
 * Marks a single notification as read.
 * @param notificationId - The notification ID to mark as read
 */
export const markNotificationRead = async (notificationId: string): Promise<boolean> => {
  try {
    await axios.post(`/api/notifications/${notificationId}/read`);
    return true;
  } catch (error: any) {
    console.error("Mark notification read error:", error.response?.data || error.message);
    return false;
  }
};

/**
 * Marks all notifications as read.
 */
export const markAllNotificationsRead = async (): Promise<number> => {
  try {
    const response = await axios.post(`/api/notifications/mark-all-read`);
    return response.data.marked_count || 0;
  } catch (error: any) {
    console.error("Mark all read error:", error.response?.data || error.message);
    return 0;
  }
};

/**
 * Deletes an admin notification.
 * @param notificationId - ID of the notification to delete
 */
export const deleteAdminNotification = async (notificationId: string): Promise<boolean> => {
  try {
    await axios.delete(`/api/notifications/${notificationId}`);
    return true;
  } catch (error: any) {
    console.error(`Delete notification error (${notificationId}):`, error.response?.data || error.message);
    return false;
  }
};

/**
 * Deletes all admin notifications.
 */
export const deleteAllNotifications = async (): Promise<number> => {
  try {
    const response = await axios.delete(`/api/notifications`);
    return response.data.deleted_count || 0;
  } catch (error: any) {
    console.error("Delete all notifications error:", error.response?.data || error.message);
    return 0;
  }
};

/**
 * Extracts asset configuration from natural language text.
 */
export const extractFromText = async (message: string, context: any): Promise<any> => {
  try {
    const response = await axios.post('/api/asset-configurations/extract-from-text', {
      message,
      context
    });
    return response.data;
  } catch (error: any) {
    console.error("Extract from text error:", error.response?.data || error.message);
    return { 
      success: false, 
      status: error.response?.status,
      error: error.response?.data?.error || "Failed to extract information" 
    };
  }
};

/**
 * Fetches engineering standards for a specific asset type.
 */
export const getAssetStandards = async (assetType: string): Promise<any> => {
  try {
    const response = await axios.get('/api/asset-configurations/standards', {
      params: { asset_type: assetType }
    });
    return response.data;
  } catch (error: any) {
    console.error("Get standards error:", error.response?.data || error.message);
    return { found: false, error: error.response?.data?.error };
  }
};

/**
 * Fetches a generic image for an asset type.
 */
export const getGenericImage = async (assetType: string): Promise<any> => {
  try {
    const response = await axios.get(`/api/generic_image/${encodeURIComponent(assetType)}`);
    return response.data;
  } catch (error: any) {
    console.error("Get generic image error:", error.response?.data || error.message);
    return { image: null };
  }
};

/**
 * Saves or updates an asset configuration.
 */
export const saveAssetConfiguration = async (configId: string | null, data: any): Promise<any> => {
  try {
    if (configId) {
      const response = await axios.put(`/api/asset-configurations/${configId}`, data);
      return response.data;
    } else {
      const response = await axios.post('/api/asset-configurations', data);
      return response.data;
    }
  } catch (error: any) {
    console.error("Save asset configuration error:", error.response?.data || error.message);
    return { success: false, error: error.response?.data?.error || "Save failed" };
  }
};

/**
 * Generates YAML for an asset configuration.
 */
export const generateAssetYaml = async (configId: string): Promise<any> => {
  try {
    const response = await axios.post(`/api/asset-configurations/${configId}/generate-yaml`);
    return response.data;
  } catch (error: any) {
    console.error("Generate YAML error:", error.response?.data || error.message);
    return { 
      success: false, 
      status: error.response?.status,
      error: error.response?.data?.error || "Generation failed" 
    };
  }
};

// ── Honeywell Experion PKS (C300 CEE) API ────────────────────────────────────

/**
 * Infers Honeywell Experion C300 Control Modules and CEE Function Blocks from P&ID graph.
 */
export const inferExperionStrategy = async (pidGraph: any, controllerName = "CEE01_C300"): Promise<any> => {
  try {
    const response = await axios.post("/api/experion/infer", {
      pid_graph: pidGraph,
      controller_name: controllerName,
    });
    return response.data;
  } catch (error: any) {
    console.error("Experion infer error:", error.response?.data || error.message);
    return { success: false, error: error.response?.data?.error || "Inference failed" };
  }
};

/**
 * Downloads Honeywell Control Builder XML file for C300 controllers.
 */
export const exportControlBuilderXml = async (strategy: any): Promise<void> => {
  try {
    const response = await axios.post(
      "/api/experion/export-xml",
      { strategy },
      { responseType: "blob" }
    );
    const blob = new Blob([response.data], { type: "application/xml" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `experion_c300_${strategy?.target_controller || "CEE01"}_strategy.xml`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  } catch (error: any) {
    console.error("Export XML error:", error.response?.data || error.message);
    throw error;
  }
};

/**
 * Downloads Honeywell Quick Builder / Point Builder CSV tag database file.
 */
export const exportPointBuilderCsv = async (strategy: any): Promise<void> => {
  try {
    const response = await axios.post(
      "/api/experion/export-csv",
      { strategy },
      { responseType: "blob" }
    );
    const blob = new Blob([response.data], { type: "text/csv" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "experion_c300_point_builder_tags.csv";
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  } catch (error: any) {
    console.error("Export CSV error:", error.response?.data || error.message);
    throw error;
  }
};

/**
 * Connects or initializes OPC UA bridge to Honeywell Experion OPC Server.
 */
export const connectExperionOpc = async (config: {
  endpoint_url: string;
  security_policy?: string;
  simulation_mode?: boolean;
}): Promise<any> => {
  try {
    const response = await axios.post("/api/experion/opc/connect", config);
    return response.data;
  } catch (error: any) {
    console.error("OPC Connect error:", error.response?.data || error.message);
    return { success: false, error: error.response?.data?.error || "Connection failed" };
  }
};

/**
 * Reads live runtime PV, SP, OP, and Mode values for all active Experion loops.
 */
export const getExperionOpcTags = async (): Promise<any> => {
  try {
    const response = await axios.get("/api/experion/opc/tags");
    return response.data;
  } catch (error: any) {
    console.error("OPC Read Tags error:", error.response?.data || error.message);
    return { success: false, tags: [], error: error.response?.data?.error || "Read failed" };
  }
};

/**
 * Writes a Setpoint, Output, or Controller Mode to an Experion CEE block.
 */
export const writeExperionOpcTag = async (
  cmName: string,
  blockTag: string,
  parameter: string,
  value: any
): Promise<any> => {
  try {
    const response = await axios.post("/api/experion/opc/write", {
      cm_name: cmName,
      block_tag: blockTag,
      parameter,
      value,
    });
    return response.data;
  } catch (error: any) {
    console.error("OPC Write Tag error:", error.response?.data || error.message);
    return { success: false, error: error.response?.data?.error || "Write failed" };
  }
};



// ── Persisted P&ID: engineer decisions ───────────────────────────────────────
//
// A P&ID produced by the solution agent is stored per solution session and
// carries a `revision`. A modification may leave it waiting on the engineer
// (`pendingAction`): queued deletions to confirm, or which subsystem new
// equipment belongs in. Decisions name the revision they were made against;
// a stale revision comes back as `conflict` with the current drawing.

export interface PidDecisionResult {
  success: boolean;
  pidGraph?: any;
  history?: any[];
  error?: string;
  question?: string;
  conflict?: boolean;
}

const pidDecisionError = (error: any, fallback: string): PidDecisionResult => {
  const data = error.response?.data || {};
  return {
    success: false,
    error: data.error || fallback,
    question: data.question,
    conflict: error.response?.status === 409,
    pidGraph: data.pid_graph ? convertKeysToCamelCase(data.pid_graph) : undefined,
  };
};

/** The session's current stored P&ID and its revision history. */
export const getActivePid = async (sessionId: string): Promise<PidDecisionResult> => {
  try {
    const response = await axios.get("/api/pid/active", { params: { session_id: sessionId } });
    const data = convertKeysToCamelCase(response.data);
    return { success: true, pidGraph: data.pidGraph, history: data.history };
  } catch (error: any) {
    return pidDecisionError(error, "Could not load the P&ID");
  }
};

/** Apply (confirmed=true) or cancel the deletions the retrofit agent queued. */
export const confirmPidAction = async (
  sessionId: string,
  revision: number,
  confirmed: boolean
): Promise<PidDecisionResult> => {
  try {
    const response = await axios.post("/api/pid/confirm", {
      session_id: sessionId,
      revision,
      confirmed,
    });
    return { success: true, pidGraph: convertKeysToCamelCase(response.data.pid_graph) };
  } catch (error: any) {
    return pidDecisionError(error, "Could not apply the decision");
  }
};

/** Answer "which subsystem?" (a number, a name, or "none"); runs the waiting modification. */
export const clarifyPidAction = async (
  sessionId: string,
  revision: number,
  answer: string
): Promise<PidDecisionResult> => {
  try {
    const response = await axios.post("/api/pid/clarify", {
      session_id: sessionId,
      revision,
      answer,
    });
    return { success: true, pidGraph: convertKeysToCamelCase(response.data.pid_graph) };
  } catch (error: any) {
    return pidDecisionError(error, "Could not apply the answer");
  }
};
