import AIRecommender from "@/components/AIRecommender";
import { useState, useCallback, useRef, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useToast } from "@/hooks/use-toast";
import { BASE_URL } from "@/components/AIRecommender/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { X } from 'lucide-react';
import { Switch } from '@/components/ui/switch';

const DOCKING_STATE_KEY = "ai_recommender_docking_state";
const AUTH_TOKEN_KEY = 'auth_token';

const authFetch = (url: string, init?: RequestInit): Promise<Response> => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return fetch(url, {
    ...init,
    headers: {
      ...init?.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
};

// Helper to extract first N words from input
const extractFirstWords = (input: string, count: number = 2): string => {
  if (!input || typeof input !== 'string') return 'Search';

  // Clean and split the input
  const words = input.trim().split(/\s+/).filter(word => word.length > 0);

  if (words.length === 0) return 'Search';

  // Take first N words and capitalize first letter of each
  const firstWords = words.slice(0, count).map(word =>
    word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
  ).join(' ');

  return firstWords || 'Search';
};

// Escape string for use in RegExp
const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Compute next available duplicate name
const computeNextDuplicateName = (base: string, projects: any[]) => {
  if (!base) return `${base} (1)`;
  const baseTrim = base.trim();

  // Extract the actual base name without any numbering
  const baseNameMatch = baseTrim.match(/^(.*?)(?:\s*\(\d+\))?$/);
  const actualBaseName = baseNameMatch ? baseNameMatch[1].trim() : baseTrim;

  // Create regex to match all variations of the base name with numbers
  const regex = new RegExp(`^${escapeRegExp(actualBaseName)}(?:\\s*\\((\\d+)\\))?$`, 'i');
  let maxNum = 0;
  let foundBase = false;

  for (const p of projects) {
    const pName = (p.projectName || p.project_name || '').trim();
    if (!pName) continue;
    const m = pName.match(regex);
    if (m) {
      if (!m[1]) {
        foundBase = true;
      } else {
        const n = parseInt(m[1], 10);
        if (!isNaN(n) && n > maxNum) maxNum = n;
      }
    }
  }

  if (maxNum > 0) {
    return `${actualBaseName} (${maxNum + 1})`;
  }

  return `${actualBaseName} (1)`;
};

// IndexedDB configuration for persisting Search state
const search_DB_NAME = 'search_db';
const search_STORE_NAME = 'search_state';
const getSearchTabId = () => {
  let tabId = sessionStorage.getItem('search_app_tab_id');
  if (!tabId) {
    tabId = `tab_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    sessionStorage.setItem('search_app_tab_id', tabId);
  }
  return tabId;
};

const getSearchStateKey = () => `current_session_${getSearchTabId()}`;
const getSearchBackupKey = () => `search_state_backup_${getSearchTabId()}`;

// Helper function to open IndexedDB
const opensearchDB = (): Promise<IDBDatabase> => {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(search_DB_NAME, 1);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(search_STORE_NAME)) {
        db.createObjectStore(search_STORE_NAME, { keyPath: 'id' });
      }
    };
  });
};

// Helper function to save state to IndexedDB
const saveStateTosearchDB = async (state: any): Promise<void> => {
  try {
    const db = await opensearchDB();
    const transaction = db.transaction(search_STORE_NAME, 'readwrite');
    const store = transaction.objectStore(search_STORE_NAME);

    await new Promise<void>((resolve, reject) => {
      const request = store.put({ id: getSearchStateKey(), ...state });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });

    db.close();
  } catch (e) {
    console.warn('[search] Failed to save to IndexedDB:', e);
  }
};

// Helper function to load state from IndexedDB
const loadStateFromsearchDB = async (): Promise<any | null> => {
  try {
    const db = await opensearchDB();
    const transaction = db.transaction(search_STORE_NAME, 'readonly');
    const store = transaction.objectStore(search_STORE_NAME);

    const result = await new Promise<any>((resolve, reject) => {
      const request = store.get(getSearchStateKey());
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });

    db.close();

    if (result) {
      // Restore Date objects for chat messages if needed
      if (result.messages) {
        result.messages = result.messages.map((msg: any) => ({
          ...msg,
          timestamp: msg.timestamp ? new Date(msg.timestamp) : undefined
        }));
      }
      return result;
    }
    return null;
  } catch (e) {
    console.warn('[search] Failed to load from IndexedDB:', e);
    return null;
  }
};

// Helper function to clear IndexedDB state
const clearsearchDBState = async (): Promise<void> => {
  try {
    const db = await opensearchDB();
    const transaction = db.transaction(search_STORE_NAME, 'readwrite');
    const store = transaction.objectStore(search_STORE_NAME);

    await new Promise<void>((resolve, reject) => {
      const request = store.delete(getSearchStateKey());
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });

    db.close();
    // Also clear localStorage backup
    localStorage.removeItem(getSearchBackupKey());
    console.log('[search] IndexedDB state cleared');
  } catch (e) {
    console.warn('[search] Failed to clear IndexedDB:', e);
  }
};

// Greeting messages for Search page (shown when opened from video navigation)
const SEARCH_GREETINGS = [
  "Welcome to Search & Recommender. I am your AI assistant. Please describe the product you are looking for, and I will identify suitable vendors and model options.",

  "Hello. I am your AI assistant. Share the product category, specifications, or preferred vendor, and I will find relevant matches for you.",

  "You are now in the Search workspace. I am your AI assistant. Provide your technical requirements, and I will retrieve appropriate products based on your criteria.",

  "I am your AI assistant. Tell me the type of instrument, required specifications, or application details, and I will search for the best available options.",

  "Welcome. I am your AI assistant. Enter the product details or performance parameters you need, and I will return structured search results."
];

const Index = () => {
  const { toast } = useToast();
  const [searchParams] = useSearchParams();

  // Clean up any stale asset context keys left in localStorage by Assets page
  (() => {
    const assetCtxKey = new URLSearchParams(window.location.search).get('assetCtx');
    if (assetCtxKey) localStorage.removeItem(assetCtxKey);
  })();

  // Track the latest AIRecommender state for saving
  const currentStateRef = useRef<any>(null);
  const isInitializingRef = useRef(false);

  // AUTO-SAVE support: prevent saving during initial state restore
  const isSearchRestoringRef = useRef(true);
  const searchAutoSaveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Server auto-save uses its own, longer debounce than the local IndexedDB
  // save (see Project.tsx for the same split): a streaming response can call
  // handleStateChange every few seconds, and a single 1500ms timer re-armed
  // that often still fires a full server save (Azure Blob PUT + old-blob
  // DELETE) on nearly every update instead of coalescing them.
  const serverAutoSaveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const SERVER_AUTOSAVE_DEBOUNCE_MS = 8000;

  // Duplicate name dialog states
  const [duplicateNameDialogOpen, setDuplicateNameDialogOpen] = useState(false);
  const [duplicateProjectName, setDuplicateProjectName] = useState<string | null>(null);
  const [autoRenameSuggestion, setAutoRenameSuggestion] = useState<string | null>(null);
  const [duplicateDialogNameInput, setDuplicateDialogNameInput] = useState<string>('');
  const [duplicateDialogError, setDuplicateDialogError] = useState<string | null>(null);

  // Pre-conversation project initialization states
  const [showGoogleSavePopup, setShowGoogleSavePopup] = useState<boolean>(() => {
    const skipped = sessionStorage.getItem('skip_project_init_search') === 'true';
    const hasChoice = sessionStorage.getItem('search_server_autosave_enabled') !== null;
    const urlParams = new URLSearchParams(window.location.search);
    const projectId = urlParams.get('projectId');
    return !projectId && !skipped && !hasChoice;
  });
  const [initProjectName, setInitProjectName] = useState('');
  const [initProjectError, setInitProjectError] = useState<string | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);

  // Server Auto-Save states
  const [isServerAutoSaveEnabled, setIsServerAutoSaveEnabled] = useState<boolean>(() => {
    return sessionStorage.getItem('search_server_autosave_enabled') === 'true'; // default to false
  });
  const [projectName, setProjectName] = useState<string>(() => {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('projectId')) return 'Project'; // will load from server
      const backup = localStorage.getItem(getSearchBackupKey());
      if (backup) {
        return JSON.parse(backup).projectName || 'Project';
      }
    } catch (e) {}
    return 'Project';
  });

  // State for loaded project data
  const [loadedProjectData, setLoadedProjectData] = useState<any>(() => {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('projectId')) return null;
      if (sessionStorage.getItem('clear_search_state') === 'true') return null;
      // Check if this is a newly opened tab
      if (!sessionStorage.getItem('search_tab_initialized_flag')) return null;

      const backup = localStorage.getItem(getSearchBackupKey());
      if (!backup) return null;

      const restoredState = JSON.parse(backup);
      if (restoredState?.messages) {
        restoredState.messages = restoredState.messages.map((msg: any) => ({
          ...msg,
          timestamp: msg.timestamp ? new Date(msg.timestamp) : undefined
        }));
      }

      return {
        messages: restoredState.messages || [],
        currentStep: restoredState.currentStep || 'initialInput',
        searchInstanceId: restoredState.searchInstanceId || restoredState.searchSessionId,
        requirementSchema: restoredState.requirementSchema || null,
        validationResult: restoredState.validationResult || null,
        currentProductType: restoredState.currentProductType || null,
        inputValue: restoredState.inputValue || '',
        advancedParameters: restoredState.advancedParameters || null,
        selectedAdvancedParams: restoredState.selectedAdvancedParams || {},
        fieldDescriptions: restoredState.fieldDescriptions || {},
        collectedData: restoredState.collectedData || {},
        analysisResult: restoredState.analysisResult || null,
        pricingData: restoredState.pricingData || {},
        scrollPositions: restoredState.scrollPositions || { left: 0, center: 0, right: 0 },
        dockingState: restoredState.dockingState || { left: true, right: true },
      };
    } catch (e) {
      return null;
    }
  });

  // Load saved docking state from localStorage
  const [savedDockingState] = useState<{ left: boolean; right: boolean } | undefined>(() => {
    try {
      const saved = localStorage.getItem(DOCKING_STATE_KEY);
      if (saved) {
        return JSON.parse(saved);
      }
    } catch (e) {
      console.warn("Failed to load saved docking state:", e);
    }
    return undefined;
  });

  // SESSION MEMORY: Cleared on actual tab close (NOT on refresh or navigation)
  // HOW IT WORKS (deferred cleanup pattern):
  // - beforeunload: Mark session as "pending cleanup" in localStorage
  // - sessionStorage survives refresh but is LOST on tab close
  // - On page load: If sessionStorage still has the session → it was a refresh → cancel cleanup
  // - On page load: Process any pending cleanups from OTHER closed tabs

  // Keep a ref to searchInstanceId so beforeunload always has the latest value
  // Initialize from localStorage backup immediately (synchronous) so it's available at mount
  const _initialSearchInstanceId = (() => {
    try {
      const backup = localStorage.getItem(getSearchBackupKey());
      if (backup) {
        const parsed = JSON.parse(backup);
        return parsed.searchInstanceId || parsed.searchSessionId || null;
      }
    } catch (e) { /* ignore */ }
    return null;
  })();
  const searchInstanceIdRef = useRef<string | null>(_initialSearchInstanceId);
  // Keep ref updated as child component reports state changes
  const handleSearchInstanceIdUpdate = (id: string) => {
    if (id && id !== searchInstanceIdRef.current) {
      searchInstanceIdRef.current = id;
      sessionStorage.setItem('search_session_alive', id);
    }
  };

  // DEFERRED SESSION CLEANUP: On mount, process any pending cleanups from closed tabs
  useEffect(() => {
    // Mark this tab's session as "alive" in sessionStorage (survives refresh, lost on tab close)
    // searchInstanceIdRef is pre-populated from localStorage backup so this works correctly on refresh
    const currentId = searchInstanceIdRef.current;
    if (currentId) {
      sessionStorage.setItem('search_session_alive', currentId);
      console.log('[SEARCH] Marked session alive in sessionStorage:', currentId);
    }

    // Helper to process pending cleanups for a given localStorage key
    const processPendingCleanups = (storageKey: string, aliveKey: string, clearEndpoints: string[]) => {
      try {
        const pendingRaw = localStorage.getItem(storageKey);
        if (!pendingRaw) return;

        const pendingCleanups: { sessionId: string; timestamp: number }[] = JSON.parse(pendingRaw);
        const aliveSessionId = sessionStorage.getItem(aliveKey);
        const remainingCleanups: typeof pendingCleanups = [];
        const now = Date.now();
        const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours - expire stale entries

        for (const cleanup of pendingCleanups) {
          // Expire stale entries (older than 24h)
          if (now - cleanup.timestamp > MAX_AGE_MS) {
            console.log('[SEARCH] Expiring stale cleanup:', cleanup.sessionId);
            continue;
          }

          if (cleanup.sessionId === aliveSessionId) {
            // This session is still alive (page was refreshed, not closed) → cancel cleanup
            console.log('[SEARCH] Refresh detected - cancelling cleanup for:', cleanup.sessionId);
            continue;
          }

          // This session's tab was closed → perform cleanup
          console.log('[SEARCH] Cleaning up closed tab session:', cleanup.sessionId);
          try {
            for (const endpoint of clearEndpoints) {
              const payload = JSON.stringify({ session_id: cleanup.sessionId });
              const fullUrl = endpoint.startsWith('http') ? endpoint : `${BASE_URL}${endpoint}`;
              navigator.sendBeacon(
                fullUrl,
                new Blob([payload], { type: 'text/plain' })
              );
            }
          } catch (e) {
            // If cleanup fails, keep it for retry on next page load
            console.warn('[SEARCH] Failed to clean up session, will retry:', cleanup.sessionId, e);
            remainingCleanups.push(cleanup);
          }
        }

        // Update localStorage: keep only failed cleanups for retry
        if (remainingCleanups.length > 0) {
          localStorage.setItem(storageKey, JSON.stringify(remainingCleanups));
        } else {
          localStorage.removeItem(storageKey);
        }
      } catch (e) {
        console.warn('[SEARCH] Error processing pending cleanups for', storageKey, e);
      }
    };

    // Process pending cleanups for Search sessions
    processPendingCleanups(
      'pending_search_session_cleanups',
      'search_session_alive',
      ['/api/clear-session-memory']
    );

    // Also process pending cleanups for Project sessions (cross-page cleanup)
    processPendingCleanups(
      'pending_session_cleanups',
      'project_session_alive',
      ['/api/clear-session-memory']
    );

    // Also process pending cleanups for Chat sessions (cross-page cleanup)
    processPendingCleanups(
      'pending_chat_session_cleanups',
      'chat_session_alive',
      ['/api/clear-session-memory', '/api/chat/clear-session']
    );
  }, []);

  // (sessionStorage sync is handled by handleSearchInstanceIdUpdate called from onStateChange)

  // SAVE ON PAGE CLOSE/REFRESH: Save state and mark session for deferred cleanup
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (!currentStateRef.current) return;

      const stateToSave = {
        ...currentStateRef.current,
        savedAt: new Date().toISOString()
      };

      // Use synchronous localStorage as fallback for immediate save
      try {
        localStorage.setItem(getSearchBackupKey(), JSON.stringify(stateToSave));
        console.log('[SEARCH] Saved state to localStorage backup on page close');
      } catch (e) {
        console.warn('[SEARCH] Failed to save backup state:', e);
      }

      // Also try to save to IndexedDB (might not complete)
      saveStateTosearchDB(stateToSave);

      // Mark session as "pending cleanup" in localStorage
      // On next page load, if sessionStorage still has this session → refresh → cancel cleanup
      // If sessionStorage lost it → tab was closed → cleanup will execute
      const currentInstanceId = searchInstanceIdRef.current;
      if (currentInstanceId) {
        try {
          const pendingRaw = localStorage.getItem('pending_search_session_cleanups');
          const pending: { sessionId: string; timestamp: number }[] = pendingRaw ? JSON.parse(pendingRaw) : [];
          // Avoid duplicate entries
          if (!pending.some(p => p.sessionId === currentInstanceId)) {
            pending.push({ sessionId: currentInstanceId, timestamp: Date.now() });
          }
          localStorage.setItem('pending_search_session_cleanups', JSON.stringify(pending));
          console.log('[SEARCH] Marked session for pending cleanup:', currentInstanceId);
        } catch (e) {
          console.warn('[SEARCH] Failed to mark pending cleanup:', e);
        }
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, []);

  // Save state on component unmount (e.g. React Router navigation)
  useEffect(() => {
    return () => {
      if (!currentStateRef.current) return;

      const stateToSave = {
        ...currentStateRef.current,
        savedAt: new Date().toISOString()
      };

      // Synchronous localStorage backup
      try {
        localStorage.setItem(getSearchBackupKey(), JSON.stringify(stateToSave));
        console.log('[SEARCH] Saved state to localStorage backup on unmount');
      } catch (e) {
        console.warn('[SEARCH] Failed to save backup state on unmount:', e);
      }

      // Async IndexedDB save
      saveStateTosearchDB(stateToSave).catch(e => console.warn('[SEARCH] Failed to save to IndexedDB on unmount:', e));
    };
  }, []);

  // LOAD FROM INDEXEDDB: Restore state on mount (unless projectId is present)
  useEffect(() => {
    // If loading a specific project, don't restore session state
    if (searchParams.get('projectId')) return;

    const loadState = async () => {
      // Check if we need to clear state (triggered by New button or fresh navigation)
      const urlParams = new URLSearchParams(window.location.search);
      const isFresh = urlParams.get('fresh') === 'true';

      // Check if this is a brand new tab (manual URL open)
      if (!sessionStorage.getItem('search_tab_initialized_flag') && !isFresh) {
        sessionStorage.setItem('search_tab_initialized_flag', 'true');
        console.log('[SEARCH] New tab detected - not restoring state');

        // Show greeting for manual URL opens (not for routing buttons)
        if (!searchParams.get('initialQuery') && !searchParams.get('input') && !searchParams.get('dataKey') && !searchParams.get('queryKey') && !searchParams.get('projectId')) {
          const greetingText = SEARCH_GREETINGS[Math.floor(Math.random() * SEARCH_GREETINGS.length)];
          setLoadedProjectData({
            messages: [{
              id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
              type: 'assistant',
              role: 'assistant',
              content: greetingText,
              timestamp: new Date()
            }],
            currentStep: 'initialInput',
          });
          console.log('[SEARCH] Added greeting message for new tab (manual URL open)');
        }
        isSearchRestoringRef.current = false;
        return; // Don't restore anything
      }

      if (sessionStorage.getItem('clear_search_state') === 'true' || isFresh) {
        console.log('[search] Clearing state as requested by', isFresh ? 'fresh navigation' : 'New button');
        sessionStorage.removeItem('clear_search_state');
        sessionStorage.removeItem('skip_project_init');
        await clearsearchDBState();
        // Remove fresh param from URL to prevent re-clearing on refresh
        if (isFresh) {
          sessionStorage.setItem('search_tab_initialized_flag', 'true');
          urlParams.delete('fresh');
          const newUrl = urlParams.toString()
            ? `${window.location.pathname}?${urlParams.toString()}`
            : window.location.pathname;
          window.history.replaceState({}, '', newUrl);

          // Show a random greeting message for fresh navigation (not for routing buttons)
          if (!searchParams.get('initialQuery') && !searchParams.get('input') && !searchParams.get('dataKey') && !searchParams.get('queryKey')) {
            const greetingText = SEARCH_GREETINGS[Math.floor(Math.random() * SEARCH_GREETINGS.length)];
            setLoadedProjectData({
              messages: [{
                id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                type: 'assistant',
                role: 'assistant',
                content: greetingText,
                timestamp: new Date()
              }],
              currentStep: 'initialInput',
            });
            console.log('[SEARCH] Added greeting message for fresh navigation');
          }
        }
        isSearchRestoringRef.current = false;
        return; // Don't restore anything
      }

      try {
        // First check localStorage backup (faster/synchronous)
        let restoredState: any = null;
        try {
          const backup = localStorage.getItem(getSearchBackupKey());
          if (backup) {
            restoredState = JSON.parse(backup);
            console.log('[search] Loaded state from localStorage backup');
          }
        } catch (e) {
          console.warn('[search] Failed to load backup:', e);
        }

        // If no backup, try IndexedDB
        if (!restoredState) {
          restoredState = await loadStateFromsearchDB();
          if (restoredState) {
            console.log('[search] Loaded state from IndexedDB');
          }
        }

        if (restoredState) {
          // Restore messages with proper Date objects
          if (restoredState.messages) {
            restoredState.messages = restoredState.messages.map((msg: any) => ({
              ...msg,
              timestamp: msg.timestamp ? new Date(msg.timestamp) : undefined
            }));
          }

          // Ensure all required fields are present for AIRecommender restoration
          const completeState = {
            messages: restoredState.messages || [],
            currentStep: restoredState.currentStep || 'greeting',
            searchInstanceId: restoredState.searchInstanceId || restoredState.searchSessionId,
            requirementSchema: restoredState.requirementSchema || null,
            validationResult: restoredState.validationResult || null,
            currentProductType: restoredState.currentProductType || null,
            inputValue: restoredState.inputValue || '',
            advancedParameters: restoredState.advancedParameters || null,
            selectedAdvancedParams: restoredState.selectedAdvancedParams || {},
            fieldDescriptions: restoredState.fieldDescriptions || {},
            collectedData: restoredState.collectedData || {},
            analysisResult: restoredState.analysisResult || null,
            pricingData: restoredState.pricingData || {},
            scrollPositions: restoredState.scrollPositions || { left: 0, center: 0, right: 0 },
            dockingState: restoredState.dockingState || { left: true, right: true },
          };

          // Set loaded project data to restore the state in AIRecommender
          setLoadedProjectData(completeState);
          console.log('[SEARCH] Restored complete state from IndexedDB:', {
            messages: completeState.messages.length,
            currentStep: completeState.currentStep,
            hasCollectedData: !!completeState.collectedData && Object.keys(completeState.collectedData).length > 0,
            hasAnalysisResult: !!completeState.analysisResult,
          });
        } else {
          // No saved state found - show greeting message
          // This handles the case when returning from catalog with no prior messages
          if (!searchParams.get('initialQuery') && !searchParams.get('input') && !searchParams.get('dataKey') && !searchParams.get('queryKey')) {
            const greetingText = SEARCH_GREETINGS[Math.floor(Math.random() * SEARCH_GREETINGS.length)];
            setLoadedProjectData({
              messages: [{
                id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                type: 'assistant',
                role: 'assistant',
                content: greetingText,
                timestamp: new Date()
              }],
              currentStep: 'initialInput',
            });
            console.log('[SEARCH] Added greeting message - no saved state found');
          }
        }
        isSearchRestoringRef.current = false;
      } catch (e) {
        console.warn('[search] Error restoring state:', e);
        // On error, also show greeting
        if (!searchParams.get('initialQuery') && !searchParams.get('input') && !searchParams.get('dataKey') && !searchParams.get('queryKey')) {
          const greetingText = SEARCH_GREETINGS[Math.floor(Math.random() * SEARCH_GREETINGS.length)];
          setLoadedProjectData({
            messages: [{
              id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
              type: 'assistant',
              role: 'assistant',
              content: greetingText,
              timestamp: new Date()
            }],
            currentStep: 'initialInput',
          });
          console.log('[SEARCH] Added greeting message after error');
        }
        isSearchRestoringRef.current = false;
      }
    };

    loadState();
  }, [searchParams]);



  // Load project if projectId is in the URL
  useEffect(() => {
    const projectId = searchParams.get('projectId');
    if (!projectId) return;

    const loadProject = async () => {
      try {
        console.log('[search] Loading project:', projectId);
        const response = await authFetch(`${BASE_URL}/api/projects/${projectId}`, {
          credentials: 'include'
        });

        if (!response.ok) {
          throw new Error('Failed to load project');
        }

        const data = await response.json();
        const project = data.project || data;

        // Load conversation history from the project
        const convHistories = project.conversationHistories || project.conversation_histories || {};
        let searchHistory = convHistories['search'];
        let resolvedTabId = 'search';

        // Fallback 1: If search is missing, try to find the history of the active tab
        const activeTab = project.activeTab || project.active_tab;
        if (!searchHistory && activeTab && activeTab !== 'project' && activeTab !== 'Project') {
          searchHistory = convHistories[activeTab];
          if (searchHistory) {
            resolvedTabId = activeTab;
            console.log(`[search] Found history for active tab: ${activeTab}`);
          }
        }

        // Fallback 2: Try to find the history of the first search tab
        const searchTabs = project.searchTabs || project.search_tabs || [];
        if (!searchHistory && searchTabs.length > 0) {
          const firstTabId = searchTabs[0].id || searchTabs[0].tabId;
          if (firstTabId) {
            searchHistory = convHistories[firstTabId];
            if (searchHistory) {
              resolvedTabId = firstTabId;
              console.log(`[search] Found history for first search tab: ${firstTabId}`);
            }
          }
        }

        // Fallback 3: Fall back to project's main conversation (from Solution page)
        if (!searchHistory) {
          const mainMessages = project.projectChatMessages || project.project_chat_messages || [];
          if (mainMessages.length > 0) {
            searchHistory = {
              messages: mainMessages,
              currentStep: project.currentStep || project.current_step || 'greeting',
              currentProductType: project.productType || project.product_type || '',
              fieldDescriptions: project.fieldDescriptions || project.field_descriptions || {}
            };
            resolvedTabId = 'project';
            console.log('[search] Fallback: Using main solution chat messages.');
          }
        }

        // Fallback 4: If we still don't have any searchHistory, create a default greeting so we don't leave the screen empty/blank
        if (!searchHistory) {
          searchHistory = {
            messages: [{
              id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
              type: 'assistant',
              role: 'assistant',
              content: 'Welcome to search workflow.',
              timestamp: new Date()
            }],
            currentStep: 'initialInput',
            currentProductType: project.productType || project.product_type || '',
          };
          resolvedTabId = 'search';
          console.log('[search] No history found at all, using default placeholder greeting.');
        }

        const name = project.projectName || project.project_name || 'Project';
        setProjectName(name);

        // Restore instance ID from top level or nested location
        const restoredInstanceId = project.projectInstanceId || project.project_instance_id ||
          searchHistory.searchInstanceId || searchHistory.searchSessionId;

        // Pass the loaded data to be used by AIRecommender
        setLoadedProjectData({
          messages: searchHistory.messages || [],
          currentStep: searchHistory.currentStep || project.currentStep || project.current_step || 'greeting',
          searchInstanceId: restoredInstanceId,
          requirementSchema: searchHistory.requirementSchema,
          validationResult: searchHistory.validationResult,
          currentProductType: searchHistory.currentProductType || project.productType || project.product_type,
          advancedParameters: searchHistory.advancedParameters,
          selectedAdvancedParams: searchHistory.selectedAdvancedParams,
          fieldDescriptions: searchHistory.fieldDescriptions || project.fieldDescriptions || project.field_descriptions,
          collectedData: (project.collectedData || project.collected_data || {})[resolvedTabId] || {},
          analysisResult: (project.analysisResults || project.analysis_results || {})[resolvedTabId] || null,
        });

        if (restoredInstanceId) {
          console.log('[SEARCH] Restoring searchInstanceId:', restoredInstanceId);
        }

        console.log('[search] Loaded project data');

        toast({
          title: "Project Loaded",
          description: `Loaded "${project.projectName || project.project_name}"`,
        });
      } catch (error: any) {
        console.error('[search] Error loading project:', error);
        toast({
          title: "Load Failed",
          description: error.message || "Failed to load project",
          variant: "destructive",
        });
      }
    };

    loadProject();
  }, [searchParams, toast]);

  const autoInitializeProject = useCallback(async (firstMsg: string) => {
    try {
      console.log('[SEARCH] Auto-initializing project in background...');
      const nameResponse = await authFetch(`${BASE_URL}/api/projects/generate-name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requirements: firstMsg }),
        credentials: 'include'
      });
      if (!nameResponse.ok) throw new Error('Failed to generate project name');
      const nameData = await nameResponse.json();
      const generatedName = nameData.project_name || 'Search Project';

      const newInstanceId = currentStateRef.current?.searchInstanceId || `search_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const projectData = {
        project_name: generatedName,
        project_description: `Search project - Created on ${new Date().toLocaleDateString()}`,
        initial_requirements: firstMsg,
        source_page: 'search',
        is_initialization: true,
        project_instance_id: newInstanceId,
        conversation_histories: {
          'search': {
            messages: currentStateRef.current?.messages || [],
            currentStep: currentStateRef.current?.currentStep || 'initialInput',
            searchInstanceId: newInstanceId,
          }
        },
        product_type: 'unknown',
        current_step: 'initialInput',
        workflow_position: {
          current_tab: 'search',
          has_results: false,
          last_interaction: new Date().toISOString(),
          project_phase: 'requirements_gathering'
        },
        user_interactions: {
          conversations_count: 0,
          has_analysis: false,
          last_save: new Date().toISOString()
        }
      };

      const response = await authFetch(`${BASE_URL}/api/projects/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(projectData),
        credentials: 'include'
      });

      if (!response.ok) throw new Error('Failed to save project');
      const result = await response.json();
      const newProjectId = result.project?.project_id || result.project?.id;

      if (newProjectId) {
        setProjectName(generatedName);
        setIsServerAutoSaveEnabled(true);
        sessionStorage.setItem('search_server_autosave_enabled', 'true');
        
        const newParams = new URLSearchParams(window.location.search);
        newParams.set('projectId', newProjectId);
        window.history.replaceState(null, '', `${window.location.pathname}?${newParams.toString()}`);
        
        toast({
          title: "Project Auto-Initialized",
          description: `"${generatedName}" has been created in the background.`,
        });
      }
    } catch (err) {
      console.error('[SEARCH] Background project initialization failed:', err);
      isInitializingRef.current = false;
    }
  }, [toast]);

  const resetDuplicateDialog = () => {
    setDuplicateNameDialogOpen(false);
    setDuplicateProjectName(null);
    setAutoRenameSuggestion(null);
    setDuplicateDialogError(null);
    setDuplicateDialogNameInput('');
  };

  // Save project functionality
  const handleSaveProject = useCallback(async (
    overrideName?: string,
    options?: { skipDuplicateDialog?: boolean; isAutoSave?: boolean }
  ) => {
    const state = currentStateRef.current;

    if (!state) {
      toast({
        title: "Nothing to Save",
        description: "Start a conversation first before saving.",
        variant: "destructive",
      });
      return;
    }

    try {
      // Extract first 2 words from the first user message for project name
      let projectNameBase = 'Search';
      if (state.messages && state.messages.length > 0) {
        const firstUserMessage = state.messages.find((m: any) => m.type === 'user');
        if (firstUserMessage && firstUserMessage.content) {
          projectNameBase = extractFirstWords(firstUserMessage.content, 2);
        }
      }

      // Use override name if provided, otherwise add "(Search)" suffix
      // Use override name if provided, then current state/stored name, otherwise compute from first user message
      let effectiveProjectName = (overrideName || projectName || '').trim();
      if (!effectiveProjectName || effectiveProjectName === 'Project') {
        let projectNameBase = 'Search';
        if (state.messages && state.messages.length > 0) {
          const firstUserMessage = state.messages.find((m: any) => m.type === 'user');
          if (firstUserMessage && firstUserMessage.content) {
            projectNameBase = extractFirstWords(firstUserMessage.content, 2);
          }
        }
        effectiveProjectName = `${projectNameBase} (Search)`;
      }

      // Check for duplicate project name
      if (!options?.skipDuplicateDialog) {
        try {
          const listResponse = await authFetch(`${BASE_URL}/api/projects`, {
            credentials: 'include'
          });

          if (listResponse.ok) {
            const data = await listResponse.json();
            const projects: any[] = data.projects || [];

            const nameLower = effectiveProjectName.toLowerCase();
            const hasDuplicate = projects.some((p: any) => {
              const pName = (p.projectName || p.project_name || '').trim();
              if (!pName) return false;
              return pName.toLowerCase() === nameLower;
            });

            if (hasDuplicate) {
              const suggested = computeNextDuplicateName(effectiveProjectName, projects);
              setDuplicateProjectName(effectiveProjectName);
              setAutoRenameSuggestion(suggested);
              setDuplicateDialogNameInput(effectiveProjectName);
              setDuplicateNameDialogOpen(true);
              return;
            }
          }
        } catch (e) {
          // If duplicate check fails, continue with normal save flow.
        }
      }

      // Get the first user message as initial requirements
      const firstUserMsg = state.messages?.find((m: any) => m.type === 'user');
      const initialRequirements = firstUserMsg?.content || 'Search query';

      const projectData = {
        project_name: effectiveProjectName,
        project_description: `Search project - Created on ${new Date().toLocaleDateString()}`,
        initial_requirements: initialRequirements,
        source_page: 'search',
        project_instance_id: state.searchInstanceId || '', // Save the search instance ID at top level
        conversation_histories: {
          'search': {
            messages: state.messages || [],
            currentStep: state.currentStep || 'greeting',
            searchInstanceId: state.searchInstanceId,
            requirementSchema: state.requirementSchema || null,
            validationResult: state.validationResult || null,
            currentProductType: state.currentProductType || null,
            inputValue: state.inputValue || '',
            advancedParameters: state.advancedParameters || null,
            selectedAdvancedParams: state.selectedAdvancedParams || {},
            fieldDescriptions: state.fieldDescriptions || {}
          }
        },
        collected_data: state.collectedData ? { 'search': state.collectedData } : {},
        analysis_results: state.analysisResult ? { 'search': state.analysisResult } : {},
        field_descriptions: state.fieldDescriptions || {},
        pricing: state.pricingData ? { 'search': state.pricingData } : {},
        product_type: state.currentProductType || '',
        current_step: state.currentStep || 'greeting',
        workflow_position: {
          current_tab: 'search',
          has_results: !!state.analysisResult,
          last_interaction: new Date().toISOString(),
          project_phase: state.analysisResult ? 'results_review' : 'requirements_gathering'
        },
        user_interactions: {
          conversations_count: 1,
          has_analysis: !!state.analysisResult,
          last_save: new Date().toISOString()
        }
      };

      console.log('[search_SAVE] Saving project:', effectiveProjectName);

      const response = await authFetch(`${BASE_URL}/api/projects/save`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(projectData),
      });

      if (!response.ok) {
        let errorData: any = null;
        try {
          errorData = await response.json();
        } catch (e) {
          // ignore JSON parse errors
        }

        const errorMessage = errorData?.error || 'Failed to save project';
        const errorCode = errorData?.code || errorData?.errorCode;

        const looksLikeDuplicateNameError =
          response.status === 409 ||
          errorCode === 'DUPLICATE_PROJECT_NAME' ||
          /already exists|already present|duplicate project name/i.test(errorMessage);

        if (!options?.skipDuplicateDialog && looksLikeDuplicateNameError) {
          const nameInErrorMatch = errorMessage.match(/"([^"]+)"/);
          const nameFromError = nameInErrorMatch ? nameInErrorMatch[1] : effectiveProjectName;

          let suggested = `${nameFromError} (1)`;
          try {
            const listResp = await authFetch(`${BASE_URL}/api/projects`, { credentials: 'include' });
            if (listResp.ok) {
              const listData = await listResp.json();
              suggested = computeNextDuplicateName(nameFromError, listData.projects || []);
            }
          } catch (e) {
            // fallback remains
          }

          setDuplicateProjectName(nameFromError);
          setAutoRenameSuggestion(suggested);
          setDuplicateDialogNameInput(nameFromError);
          setDuplicateDialogError(null);
          setDuplicateNameDialogOpen(true);
          return;
        }

        throw new Error(errorMessage);
      }

      const result = await response.json();
      console.log('[search_SAVE] Project saved successfully:', result);

      if (!options?.isAutoSave) {
        toast({
          title: "Project Saved",
          description: `"${effectiveProjectName}" has been saved successfully.`,
        });
      }

    } catch (error: any) {
      console.error('[search_SAVE] Error saving project:', error);
      if (!options?.isAutoSave) {
        toast({
          title: "Save Failed",
          description: error.message || "Failed to save project",
          variant: "destructive",
        });
      }
    }
  }, [toast, projectName]);

  // Handle state changes from AIRecommender to persist docking state and track current state
  const handleStateChange = useCallback((state: any) => {
    // Store the latest state for save functionality
    currentStateRef.current = state;

    // Keep searchInstanceId ref and sessionStorage in sync
    if (state.searchInstanceId) {
      handleSearchInstanceIdUpdate(state.searchInstanceId);
    }

    // Auto-initialize project in background on first message if autosave is enabled
    const urlParams = new URLSearchParams(window.location.search);
    const projectIdParam = urlParams.get('projectId');
    const firstUserMsg = state.messages?.find((m: any) => m.type === 'user')?.content;
    if (!projectIdParam && firstUserMsg && !isInitializingRef.current && isServerAutoSaveEnabled) {
      isInitializingRef.current = true;
      autoInitializeProject(firstUserMsg);
    }

    if (state.dockingState) {
      try {
        localStorage.setItem(DOCKING_STATE_KEY, JSON.stringify(state.dockingState));
      } catch (e) {
        console.warn("Failed to save docking state:", e);
      }
    }

    // AUTO-SAVE: Debounced save to IndexedDB on every state change.
    // Ensures state is persisted during React Router navigation (no beforeunload fired).
    if (!isSearchRestoringRef.current) {
      if (searchAutoSaveTimeoutRef.current) {
        clearTimeout(searchAutoSaveTimeoutRef.current);
      }
      searchAutoSaveTimeoutRef.current = setTimeout(async () => {
        if (currentStateRef.current) {
          const stateToSave = {
            ...currentStateRef.current,
            projectName,
            savedAt: new Date().toISOString()
          };
          await saveStateTosearchDB(stateToSave);
          console.log('[SEARCH] State auto-saved to IndexedDB');
        }
      }, 1500);

      // Server auto-save: separate, longer debounce so a fast-moving stream
      // coalesces into one save shortly after it settles.
      const projectId = new URLSearchParams(window.location.search).get('projectId');
      if (isServerAutoSaveEnabled && projectId) {
        if (serverAutoSaveTimeoutRef.current) {
          clearTimeout(serverAutoSaveTimeoutRef.current);
        }
        serverAutoSaveTimeoutRef.current = setTimeout(async () => {
          try {
            await handleSaveProject(projectName, { skipDuplicateDialog: true, isAutoSave: true });
            console.log('[SEARCH] State auto-saved to Server');
          } catch (e) {
            console.warn('[SEARCH] Server auto-save failed:', e);
          }
        }, SERVER_AUTOSAVE_DEBOUNCE_MS);
      }
    }
  }, [isServerAutoSaveEnabled, projectName, handleSaveProject, autoInitializeProject]);



  const handleSkipInitialization = () => {
    sessionStorage.setItem('skip_project_init', 'true');
    setIsServerAutoSaveEnabled(false);
    sessionStorage.setItem('search_server_autosave_enabled', 'false');
    setShowInitProjectDialog(false);
  };

  const handleInitializeProject = async () => {
    const trimmedName = initProjectName.trim();
    if (!trimmedName) {
      setInitProjectError('Project name is required');
      return;
    }

    setIsInitializing(true);
    setInitProjectError(null);

    try {
      const newInstanceId = `search_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

      const projectData = {
        project_name: trimmedName,
        project_description: `Search project - Created on ${new Date().toLocaleDateString()}`,
        initial_requirements: 'Search initialized',
        source_page: 'search',
        is_initialization: true,
        project_instance_id: newInstanceId,
        conversation_histories: {
          'search': {
            messages: [],
            currentStep: 'initialInput',
            searchInstanceId: newInstanceId,
          }
        },
        product_type: 'unknown',
        current_step: 'initialInput',
        workflow_position: {
          current_tab: 'search',
          has_results: false,
          last_interaction: new Date().toISOString(),
          project_phase: 'requirements_gathering'
        },
        user_interactions: {
          conversations_count: 0,
          has_analysis: false,
          last_save: new Date().toISOString()
        }
      };

      const response = await authFetch(`${BASE_URL}/api/projects/save`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(projectData),
      });

      if (!response.ok) {
        let errorData: any = null;
        try {
          errorData = await response.json();
        } catch (e) {}
        throw new Error(errorData?.error || 'Failed to initialize project');
      }

      const result = await response.json();
      const newProjectId = result.project?.project_id || result.project?.id;

      if (!newProjectId) {
        throw new Error('Project ID was not returned');
      }

      toast({
        title: "Project Initialized",
        description: `"${trimmedName}" has been created and will be auto-saved.`,
      });

      setProjectName(trimmedName);
      setIsServerAutoSaveEnabled(true);
      sessionStorage.setItem('search_server_autosave_enabled', 'true');
      setShowInitProjectDialog(false);

      // Force state update to load the initialized project context
      setLoadedProjectData({
        messages: [],
        currentStep: 'initialInput',
        searchInstanceId: newInstanceId,
        requirementSchema: null,
        validationResult: null,
        currentProductType: null,
        inputValue: '',
        advancedParameters: null,
        selectedAdvancedParams: {},
        fieldDescriptions: {},
        collectedData: {},
        analysisResult: null,
        pricingData: {},
        scrollPositions: { left: 0, center: 0, right: 0 },
        dockingState: { left: true, right: true },
      });

      // Update URL parameters
      const urlParams = new URLSearchParams(window.location.search);
      urlParams.set('projectId', newProjectId);
      urlParams.delete('fresh');
      const newUrl = `${window.location.pathname}?${urlParams.toString()}`;
      window.history.replaceState({}, '', newUrl);

    } catch (err: any) {
      console.error('Failed to initialize project:', err);
      setInitProjectError(err.message || 'Failed to initialize project');
    } finally {
      setIsInitializing(false);
    }
  };



  const handleDuplicateNameChangeConfirm = () => {
    const trimmed = (duplicateDialogNameInput || '').trim();
    if (!trimmed) {
      setDuplicateDialogError('Project name is required');
      return;
    }

    resetDuplicateDialog();
    handleSaveProject(trimmed, { skipDuplicateDialog: false });
  };

  const handleDuplicateNameAutoRename = async () => {
    const baseName = (duplicateProjectName || '').trim() || 'Search';
    let suggested = autoRenameSuggestion || `${baseName} (1)`;
    try {
      const listResp = await authFetch(`${BASE_URL}/api/projects`, { credentials: 'include' });
      if (listResp.ok) {
        const listData = await listResp.json();
        suggested = computeNextDuplicateName(baseName, listData.projects || []);
      }
    } catch (e) {
      // ignore and use fallback
    }

    resetDuplicateDialog();
    handleSaveProject(suggested, { skipDuplicateDialog: true });
  };

  return (
    <>
      <AIRecommender
        savedDockingState={loadedProjectData?.dockingState || savedDockingState}
        onStateChange={handleStateChange}
        onSave={() => handleSaveProject()}
        // Pass loaded project data if available
        savedMessages={loadedProjectData?.messages}
        savedCollectedData={loadedProjectData?.collectedData}
        savedCurrentStep={loadedProjectData?.currentStep}
        savedAnalysisResult={loadedProjectData?.analysisResult}
        savedRequirementSchema={loadedProjectData?.requirementSchema}
        savedValidationResult={loadedProjectData?.validationResult}
        savedCurrentProductType={loadedProjectData?.currentProductType}
        savedAdvancedParameters={loadedProjectData?.advancedParameters}
        savedSelectedAdvancedParams={loadedProjectData?.selectedAdvancedParams}
        savedFieldDescriptions={loadedProjectData?.fieldDescriptions}
        savedScrollPositions={loadedProjectData?.scrollPositions}
        savedPricingData={loadedProjectData?.pricingData}
        savedSearchInstanceId={loadedProjectData?.searchInstanceId || loadedProjectData?.searchSessionId}
        savedInputValue={loadedProjectData?.inputValue}
        savedStandardsEnabled={loadedProjectData?.standardsEnabled}
      />

      {/* Duplicate project name dialog */}
      <AlertDialog
        open={duplicateNameDialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            resetDuplicateDialog();
          } else {
            setDuplicateNameDialogOpen(open);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Project name already exists</AlertDialogTitle>
            <AlertDialogDescription>
              {duplicateProjectName
                ? `"${duplicateProjectName}" is already present. Do you want to change the project name, or save it as "${(autoRenameSuggestion || `${duplicateProjectName} (1)`)}"?`
                : 'A project with this name is already present. Do you want to change the project name, or save it with a default suffix (1)?'}
            </AlertDialogDescription>
            <div className="mt-4 space-y-2">
              <label htmlFor="duplicate-project-name-input" className="text-sm font-medium">
                New project name
              </label>
              <input
                id="duplicate-project-name-input"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                value={duplicateDialogNameInput}
                onChange={(e) => {
                  setDuplicateDialogNameInput(e.target.value);
                  if (duplicateDialogError) {
                    setDuplicateDialogError(null);
                  }
                }}
                autoFocus
              />
              {duplicateDialogError && (
                <p className="text-xs text-destructive">{duplicateDialogError}</p>
              )}
            </div>
          </AlertDialogHeader>
          <button
            type="button"
            onClick={resetDuplicateDialog}
            className="absolute right-3 top-3 rounded-full p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
            aria-label="Close duplicate name dialog"
          >
            <X className="h-4 w-4" />
          </button>
          <AlertDialogFooter>
            <AlertDialogAction onClick={handleDuplicateNameAutoRename}>
              Use suggested name
            </AlertDialogAction>
            <AlertDialogAction onClick={handleDuplicateNameChangeConfirm}>
              Save new name
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Floating Google-style non-blocking Cloud Auto-Save popup */}
      {showGoogleSavePopup && (
        <div className="fixed top-16 right-4 z-50 w-[360px] bg-[#171717] rounded-2xl border border-white/10 shadow-2xl overflow-hidden animate-in fade-in slide-in-from-top-5 duration-300 text-zinc-100 text-left">
          {/* Header Graphic */}
          <div className="relative h-28 bg-[#212121] border-b border-white/10 flex items-center justify-center">
            <div className="absolute right-3 top-3">
              <button
                onClick={() => {
                  setShowGoogleSavePopup(false);
                  sessionStorage.setItem('skip_project_init_search', 'true');
                }}
                className="text-zinc-400 hover:text-white transition-colors p-1 hover:bg-white/10 rounded-full"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <svg className="w-20 h-20" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M30 65 A 15 15 0 0 1 35 36 A 25 25 0 0 1 80 45 A 18 18 0 0 1 70 79 Z" fill="#2a2a2a" />
              <rect x="35" y="30" width="30" height="40" rx="3" fill="#171717" stroke="#0ea5e9" strokeWidth="3" />
              <line x1="42" y1="42" x2="58" y2="42" stroke="#0ea5e9" strokeWidth="2.5" strokeLinecap="round" />
              <line x1="42" y1="52" x2="54" y2="52" stroke="#0ea5e9" strokeWidth="2.5" strokeLinecap="round" />
              <circle cx="68" cy="62" r="12" fill="#10b981" />
              <path d="M63 62 L67 66 L74 58" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </div>

          {/* Content */}
          <div className="p-5">
            <h3 className="text-[16px] font-semibold text-white leading-tight">
              Enable cloud auto-save?
            </h3>
            <p className="text-[13px] text-zinc-400 mt-2 leading-relaxed">
              Continuous cloud auto-saving keeps your search query and product recommendations safe in the secure server database.
            </p>

            {/* Actions */}
            <div className="flex items-center justify-between mt-6 pt-2">
              <div className="text-zinc-500 hover:text-zinc-300 cursor-pointer">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setShowGoogleSavePopup(false);
                    sessionStorage.setItem('skip_project_init_search', 'true');
                  }}
                  className="px-4 py-2 text-[13px] font-semibold text-zinc-300 bg-white/10 hover:bg-white/15 rounded-full transition-colors"
                >
                  Close
                </button>
                <button
                  onClick={() => {
                    setShowGoogleSavePopup(false);
                    setIsServerAutoSaveEnabled(true);
                    localStorage.setItem('search_server_autosave_enabled', 'true');
                    toast({
                      title: "Auto-Save Enabled",
                    });

                    // If a message was already sent but not initialized, trigger it now!
                    const urlParams = new URLSearchParams(window.location.search);
                    const projectIdParam = urlParams.get('projectId');
                    const firstUserMsg = currentStateRef.current?.messages?.find((m: any) => m.type === 'user')?.content;
                    if (!projectIdParam && firstUserMsg && !isInitializingRef.current) {
                      isInitializingRef.current = true;
                      autoInitializeProject(firstUserMsg);
                    }
                  }}
                  className="px-4 py-2 text-[13px] font-semibold text-white bg-sky-500 hover:bg-sky-400 rounded-full transition-colors shadow-lg shadow-sky-500/25"
                >
                  Enable
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default Index;
