import { useRef, useState, useEffect, KeyboardEvent, FormEvent, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Loader2, Database, Sparkles, AlertCircle, X } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import BouncingDots from '@/components/AIRecommender/BouncingDots';
import { classifyRoute, confirmRouteResponse, BASE_URL } from "@/components/AIRecommender/api";
import MainHeader from "@/components/MainHeader";
import { useAuth } from "@/contexts/AuthContext";
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

// Types for RAG response
interface RAGResponse {
    success: boolean;
    answer: string;
    source: "database" | "llm" | "pending_confirmation" | "user_declined" | "unknown";
    foundInDatabase: boolean;
    awaitingConfirmation?: boolean;
    sourcesUsed?: string[];
    metadata?: any;
    resultsCount?: number;
    note?: string;
    error?: string;
    isChatRelated?: boolean;
    routerResult?: {
        requiresRouting: boolean;
        targetPage: string;
        category: string;
        directResponse?: string;
        routingUrl?: string;
    };
}

interface ChatMessage {
    id: string;
    type: "user" | "assistant";
    content: string;
    source?: string;
    sourcesUsed?: string[];
    metadata?: any;
    awaitingConfirmation?: boolean;
    timestamp: Date;
}

// UI Labels from backend
interface UILabels {
    loadingText: string;
    confirmationHint: string;
    inputPlaceholder: string;
    sourceDatabase: string;
    sourceLlm: string;
    sourcePending: string;
    errorMessage: string;
}

// MessageRow component with animations (same as Project.tsx - Solution page)
interface MessageRowProps {
    message: ChatMessage;
    isHistory: boolean;
    uiLabels: UILabels;
    onFeedbackClick?: (key: string, itemType: string, itemName: string, feedbackType: 'positive' | 'negative', itemData: any) => void;
}

const MessageRow = ({ message, isHistory, uiLabels, onFeedbackClick }: MessageRowProps) => {
    const isRecent = useMemo(() => {
        if (!message.timestamp) return false;
        try {
            const tsDate = message.timestamp instanceof Date ? message.timestamp : new Date(message.timestamp);
            const diff = Date.now() - tsDate.getTime();
            return diff >= 0 && diff < 5000;
        } catch {
            return false;
        }
    }, [message.timestamp]);

    const effectiveIsHistory = isHistory || !isRecent;
    const [isVisible, setIsVisible] = useState(effectiveIsHistory);

    useEffect(() => {
        if (!effectiveIsHistory) {
            const delay = message.type === 'user' ? 200 : 0;
            const timer = setTimeout(() => {
                setIsVisible(true);
            }, delay);
            return () => clearTimeout(timer);
        } else {
            setIsVisible(true);
        }
    }, [effectiveIsHistory, message.type]);

    const formatTimestamp = (ts: Date) => {
        try {
            return ts.toLocaleTimeString();
        } catch {
            return '';
        }
    };

    const getSourceIcon = (source?: string) => {
        switch (source) {
            case "database":
                return <Database className="w-4 h-4 text-green-500" />;
            case "llm":
                return <Sparkles className="w-4 h-4 text-purple-500" />;
            case "pending_confirmation":
                return <AlertCircle className="w-4 h-4 text-yellow-500" />;
            default:
                return null;
        }
    };

    const getSourceLabel = (source?: string) => {
        switch (source) {
            case "database":
                return uiLabels.sourceDatabase;
            case "llm":
                return uiLabels.sourceLlm;
            case "pending_confirmation":
                return uiLabels.sourcePending;
            default:
                return "";
        }
    };

    return (
        <div className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] flex items-start space-x-2 ${message.type === 'user' ? 'flex-row-reverse space-x-reverse' : ''}`}>
                {/* Avatar */}
                <div className={`flex-shrink-0 w-16 h-16 rounded-full flex items-center justify-center ${message.type === 'user' ? 'bg-transparent text-white -mt-3' : 'bg-transparent'}`}>
                    {message.type === 'user' ? (
                        <img src="/icon-user-3d.png" alt="User" className="w-16 h-16 object-contain" />
                    ) : (
                        <img src="/engenie icon.jpeg" alt="Assistant" className="w-20 h-20 object-contain rounded-full" />
                    )}
                </div>

                {/* Message Bubble */}
                <div className="flex-1">
                    <div
                        className={`break-words ${message.type === 'user' ? 'glass-bubble-user' : 'glass-bubble-assistant'}`}
                        style={{
                            opacity: isVisible ? 1 : 0,
                            transform: isVisible ? 'translateY(0) scale(1)' : 'translateY(12px) scale(0.96)',
                            transformOrigin: message.type === 'user' ? 'bottom right' : 'bottom left',
                            transition: 'opacity 0.4s ease-out, transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)'
                        }}
                    >
                        {/* Message content with Markdown */}
                        <div>
                            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{message.content}</ReactMarkdown>
                        </div>

                        {/* Confirmation hint - from backend */}
                        {message.awaitingConfirmation && (
                            <div className="mt-2 pt-2 border-t border-yellow-200/50 text-xs text-yellow-700">
                                💡 {uiLabels.confirmationHint}
                            </div>
                        )}

                        {/* Router redirect button */}
                        {message.metadata?.routerRedirect && message.metadata?.routerUrl && (
                            <div className="mt-3">
                                <a
                                    href={message.metadata.routerUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center justify-center rounded-md text-xs font-semibold px-3 py-1.5 bg-sky-500 hover:bg-sky-400 text-black transition-colors shadow-xs"
                                >
                                    Open {message.metadata.routerTargetPage ? message.metadata.routerTargetPage.charAt(0).toUpperCase() + message.metadata.routerTargetPage.slice(1) : 'Target'} Page ↗
                                </a>
                            </div>
                        )}
                    </div>

                    {/* Timestamp */}
                    <p
                        className={`text-xs text-muted-foreground mt-1 px-1 ${message.type === 'user' ? 'text-right' : ''}`}
                        style={{
                            opacity: isVisible ? 1 : 0,
                            transition: 'opacity 0.8s ease 0.3s'
                        }}
                    >
                        {formatTimestamp(message.timestamp)}
                    </p>

                    {/* Feedback Icons (only for assistant messages, exclude welcome messages) */}
                    {message.type === 'assistant' && onFeedbackClick && !message.id.startsWith('greeting_') && (
                        <div className="flex justify-end gap-1 -mt-4">
                            <button
                                onClick={() => onFeedbackClick(`chat_${message.id}`, 'chat_response', message.content.substring(0, 50), 'positive', message)}
                                className="transition-transform duration-300 hover:scale-125"
                                title="Good response"
                            >
                                <img
                                    src="/icon-thumbs-3d.png"
                                    alt="Thumbs Up"
                                    className="h-8 w-8 object-contain"
                                />
                            </button>
                            <button
                                onClick={() => onFeedbackClick(`chat_${message.id}`, 'chat_response', message.content.substring(0, 50), 'negative', message)}
                                className="transition-transform duration-300 hover:scale-125"
                                title="Bad response"
                            >
                                <img
                                    src="/icon-thumbsdown-3d.png"
                                    alt="Thumbs Down"
                                    className="h-8 w-8 object-contain"
                                />
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

// Default UI labels (fallback)
const DEFAULT_UI_LABELS: UILabels = {
    loadingText: "Searching database...",
    confirmationHint: "Type 'Yes' for AI answer, or 'No' to skip",
    inputPlaceholder: "Ask about products, vendors, or specifications...",
    sourceDatabase: "From Database",
    sourceLlm: "From AI Knowledge",
    sourcePending: "Awaiting Your Response",
    errorMessage: "Sorry, something went wrong. Please try again."
};

// Escape string for use in RegExp
const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Compute next available duplicate name
const computeNextDuplicateName = (base: string, projects: any[]) => {
    if (!base) return `${base} (1)`;
    const baseTrim = base.trim();

    const baseNameMatch = baseTrim.match(/^(.*?)(?:\s*\(\d+\))?$/);
    const actualBaseName = baseNameMatch ? baseNameMatch[1].trim() : baseTrim;

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

    if (foundBase) return `${actualBaseName} (1)`;

    return `${actualBaseName} (1)`;
};

// IndexedDB configuration for persisting Chat state
const CHAT_DB_NAME = 'chat_db';
const CHAT_STORE_NAME = 'chat_state';

const getChatTabId = () => {
    let tabId = sessionStorage.getItem('chat_app_tab_id');
    if (!tabId) {
        tabId = `tab_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        sessionStorage.setItem('chat_app_tab_id', tabId);
    }
    return tabId;
};

const getChatStateKey = () => `current_session_${getChatTabId()}`;
const getChatBackupKey = () => `chat_state_backup_${getChatTabId()}`;

// Helper function to open IndexedDB
const openChatDB = (): Promise<IDBDatabase> => {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(CHAT_DB_NAME, 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (event) => {
            const db = (event.target as IDBOpenDBRequest).result;
            if (!db.objectStoreNames.contains(CHAT_STORE_NAME)) {
                db.createObjectStore(CHAT_STORE_NAME, { keyPath: 'id' });
            }
        };
    });
};

// Helper function to save state to IndexedDB
const saveStateToChatDB = async (state: any): Promise<void> => {
    try {
        const db = await openChatDB();
        const transaction = db.transaction(CHAT_STORE_NAME, 'readwrite');
        const store = transaction.objectStore(CHAT_STORE_NAME);

        await new Promise<void>((resolve, reject) => {
            const request = store.put({ id: getChatStateKey(), ...state });
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });

        db.close();
    } catch (e) {
        console.warn('[CHAT] Failed to save to IndexedDB:', e);
    }
};

// Helper function to load state from IndexedDB
const loadStateFromChatDB = async (): Promise<any | null> => {
    try {
        const db = await openChatDB();
        const transaction = db.transaction(CHAT_STORE_NAME, 'readonly');
        const store = transaction.objectStore(CHAT_STORE_NAME);

        const result = await new Promise<any>((resolve, reject) => {
            const request = store.get(getChatStateKey());
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
        console.warn('[CHAT] Failed to load from IndexedDB:', e);
        return null;
    }
};

// Helper function to clear IndexedDB state
const clearChatDBState = async (): Promise<void> => {
    try {
        const db = await openChatDB();
        const transaction = db.transaction(CHAT_STORE_NAME, 'readwrite');
        const store = transaction.objectStore(CHAT_STORE_NAME);

        await new Promise<void>((resolve, reject) => {
            const request = store.delete(getChatStateKey());
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });

        db.close();
        // Also clear localStorage backup
        localStorage.removeItem(getChatBackupKey());
        console.log('[CHAT] IndexedDB state cleared');
    } catch (e) {
        console.warn('[CHAT] Failed to clear IndexedDB:', e);
    }
};

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

// Track routing windows by target page for smart window management
// Same target page → reuse window, Different target page → new window
const routingWindows: Record<string, Window | null> = {};

// Greeting messages for Chat page (shown when opened from video navigation)
const CHAT_GREETINGS = [
    "Welcome to Product Chat. I am your AI assistant. You may ask me any questions related to products, vendors, technical specifications, or standards.",

    "Hello. I am your AI assistant. Feel free to inquire about product details, vendor comparisons, specifications, or application guidance.",

    "You are now in the Chat workspace. I am your AI assistant. Ask me about instrumentation products, technical data, or industry standards, and I will assist you.",

    "I am your AI assistant. Share your question regarding products, performance parameters, certifications, or vendor information, and I will provide a structured response.",

    "Welcome. I am your AI assistant. Type your technical or product-related query, and I will provide accurate and relevant information."
];

const Chat = () => {
    const { toast } = useToast();
    const { userSessionId } = useAuth(); // Get user session ID
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const [inputValue, setInputValue] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [showThinking, setShowThinking] = useState(false);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [chatInstanceId, setChatInstanceId] = useState(() => `chat_${Date.now()}`);
    const [hasAutoSubmitted, setHasAutoSubmitted] = useState(false);
    const [isHistory, setIsHistory] = useState(false);
    const [uiLabels] = useState<UILabels>(DEFAULT_UI_LABELS); // Using static labels for instant loading
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const chatContainerRef = useRef<HTMLDivElement>(null);

    // State ref for immediate access during save  
    const stateRef = useRef({
        messages: [] as ChatMessage[],
        chatInstanceId: ''
    });

    // Keep stateRef in sync
    useEffect(() => {
        stateRef.current = { messages, chatInstanceId };
    }, [messages, chatInstanceId]);

    // Track which page opened this one (to avoid opening duplicate windows when routing back)
    const [sourcePage] = useState<string | null>(() => {
        return sessionStorage.getItem('lastSourcePage') || null;
    });

    // Route confirmation states
    const [awaitingRouteConfirmation, setAwaitingRouteConfirmation] = useState(false);
    const [pendingRouteTarget, setPendingRouteTarget] = useState<string>("");
    const [pendingRouteQuery, setPendingRouteQuery] = useState<string>("");
    const [pendingRouteMessages, setPendingRouteMessages] = useState<{
        openingMessage: string;
        declineMessage: string;
        popupBlockedMessage: string;
    }>({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });

    // Duplicate name dialog states
    const [duplicateNameDialogOpen, setDuplicateNameDialogOpen] = useState(false);
    const [duplicateProjectName, setDuplicateProjectName] = useState<string | null>(null);
    const [autoRenameSuggestion, setAutoRenameSuggestion] = useState<string | null>(null);
    const [duplicateDialogNameInput, setDuplicateDialogNameInput] = useState<string>('');
    const [duplicateDialogError, setDuplicateDialogError] = useState<string | null>(null);

    const handleSaveProjectRef = useRef<any>(null);

    // Feedback modal states
    type FeedbackType = 'positive' | 'negative' | null;
    const [feedbackModalOpen, setFeedbackModalOpen] = useState(false);
    const [feedbackModalItem, setFeedbackModalItem] = useState<{ key: string; type: string; name: string; data?: any } | null>(null);
    const [feedbackState, setFeedbackState] = useState<Record<string, { type: FeedbackType; comment: string; loading: boolean; submitted: boolean; response?: string }>>({});

    // Auto-scroll to bottom when new messages arrive - scroll within container only
    useEffect(() => {
        if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
    }, [messages, showThinking]);

    // Convert snake_case to camelCase
    const toCamelCase = (obj: any): any => {
        if (Array.isArray(obj)) {
            return obj.map(v => toCamelCase(v));
        } else if (obj !== null && typeof obj === 'object') {
            return Object.keys(obj).reduce((acc: Record<string, any>, key: string) => {
                const camelKey = key.replace(/([-_][a-z])/g, (group) =>
                    group.toUpperCase().replace("-", "").replace("_", "")
                );
                acc[camelKey] = toCamelCase(obj[key]);
                return acc;
            }, {});
        }
        return obj;
    };

    // Keep a ref to chatInstanceId so beforeunload always has the latest value
    const chatInstanceIdRef = useRef(chatInstanceId);
    useEffect(() => {
        chatInstanceIdRef.current = chatInstanceId;
    }, [chatInstanceId]);

    // DEFERRED SESSION CLEANUP: On mount, process any pending cleanups from closed tabs
    useEffect(() => {
        // Mark this tab's session as "alive" in sessionStorage (survives refresh, lost on tab close)
        const currentId = chatInstanceIdRef.current;
        if (currentId) {
            sessionStorage.setItem('chat_session_alive', currentId);
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
                        console.log('[CHAT] Expiring stale cleanup:', cleanup.sessionId);
                        continue;
                    }

                    if (cleanup.sessionId === aliveSessionId) {
                        // This session is still alive (page was refreshed, not closed) → cancel cleanup
                        console.log('[CHAT] Refresh detected - cancelling cleanup for:', cleanup.sessionId);
                        continue;
                    }

                    // This session's tab was closed → perform cleanup
                    console.log('[CHAT] Cleaning up closed tab session:', cleanup.sessionId);
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
                        console.warn('[CHAT] Failed to clean up session, will retry:', cleanup.sessionId, e);
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
                console.warn('[CHAT] Error processing pending cleanups for', storageKey, e);
            }
        };

        // Process pending cleanups for Chat sessions
        processPendingCleanups(
            'pending_chat_session_cleanups',
            'chat_session_alive',
            ['/api/clear-session-memory', '/api/chat/clear-session']
        );

        // Also process pending cleanups for Project sessions (cross-page cleanup)
        // This handles the case where user closes Project tab and only opens Chat tab next
        processPendingCleanups(
            'pending_session_cleanups',
            'project_session_alive',
            ['/api/clear-session-memory']
        );

        // Also process pending cleanups for Search sessions (cross-page cleanup)
        // This handles the case where user closes Search tab and only opens Chat tab next
        processPendingCleanups(
            'pending_search_session_cleanups',
            'search_session_alive',
            ['/api/clear-session-memory']
        );
    }, []);

    // Keep sessionStorage in sync when chatInstanceId changes
    useEffect(() => {
        if (chatInstanceId) {
            sessionStorage.setItem('chat_session_alive', chatInstanceId);
        }
    }, [chatInstanceId]);

    // SAVE ON PAGE CLOSE/REFRESH: Save state and mark session for deferred cleanup
    useEffect(() => {
        const handleBeforeUnload = () => {
            const stateToSave = {
                messages: stateRef.current.messages,
                chatInstanceId: stateRef.current.chatInstanceId,
                savedAt: new Date().toISOString()
            };

            // Use synchronous localStorage as fallback for immediate save
            try {
                localStorage.setItem(getChatBackupKey(), JSON.stringify(stateToSave));
                console.log('[CHAT] Saved state to localStorage backup on page close');
            } catch (e) {
                console.warn('[CHAT] Failed to save backup state:', e);
            }

            // Also try to save to IndexedDB (might not complete)
            saveStateToChatDB(stateToSave);

            // Mark session as "pending cleanup" in localStorage
            // On next page load, if sessionStorage still has this session → refresh → cancel cleanup
            // If sessionStorage lost it → tab was closed → cleanup will execute
            const currentInstanceId = chatInstanceIdRef.current;
            if (currentInstanceId) {
                try {
                    const pendingRaw = localStorage.getItem('pending_chat_session_cleanups');
                    const pending: { sessionId: string; timestamp: number }[] = pendingRaw ? JSON.parse(pendingRaw) : [];
                    // Avoid duplicate entries
                    if (!pending.some(p => p.sessionId === currentInstanceId)) {
                        pending.push({ sessionId: currentInstanceId, timestamp: Date.now() });
                    }
                    localStorage.setItem('pending_chat_session_cleanups', JSON.stringify(pending));
                    console.log('[CHAT] Marked session for pending cleanup:', currentInstanceId);
                } catch (e) {
                    console.warn('[CHAT] Failed to mark pending cleanup:', e);
                }
            }
        };

        window.addEventListener('beforeunload', handleBeforeUnload);

        return () => {
            window.removeEventListener('beforeunload', handleBeforeUnload);
        };
    }, []);

    // AUTO-SAVE: Persist state to IndexedDB whenever messages change (debounced).
    // This ensures state is saved during React Router navigation (which does NOT trigger beforeunload).
    const chatSaveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const isRestoringStateRef = useRef(true); // Prevent saving during initial restore

    useEffect(() => {
        // Don't save while restoring initial state
        if (isRestoringStateRef.current) return;

        // Nothing meaningful to save
        if (!messages.length) return;

        if (chatSaveTimeoutRef.current) {
            clearTimeout(chatSaveTimeoutRef.current);
        }

        chatSaveTimeoutRef.current = setTimeout(async () => {
            const stateToSave = {
                messages: stateRef.current.messages,
                chatInstanceId: stateRef.current.chatInstanceId,
                savedAt: new Date().toISOString()
            };
            await saveStateToChatDB(stateToSave);
            console.log('[CHAT] State auto-saved to IndexedDB');

            // Server background auto-save if projectId is set
            const projectId = new URLSearchParams(window.location.search).get('projectId');
            if (projectId && handleSaveProjectRef.current) {
                try {
                    await handleSaveProjectRef.current(undefined, { skipDuplicateDialog: true, isAutoSave: true });
                    console.log('[CHAT] State auto-saved to Server');
                } catch (e) {
                    console.warn('[CHAT] Server auto-save failed:', e);
                }
            }
        }, 1500);

        return () => {
            if (chatSaveTimeoutRef.current) {
                clearTimeout(chatSaveTimeoutRef.current);
            }
        };
    }, [messages, chatInstanceId]);

    // SAVE ON UNMOUNT: Catch any unsaved state when navigating away via React Router
    useEffect(() => {
        return () => {
            if (!isRestoringStateRef.current && stateRef.current.messages.length > 0) {
                const stateToSave = {
                    messages: stateRef.current.messages,
                    chatInstanceId: stateRef.current.chatInstanceId,
                    savedAt: new Date().toISOString()
                };
                saveStateToChatDB(stateToSave);
                console.log('[CHAT] State saved to IndexedDB on unmount');
            }
        };
    }, []);

    // LOAD FROM INDEXEDDB: Restore state on mount (unless projectId is present)
    useEffect(() => {
        // If loading a specific project, don't restore session state
        if (searchParams.get('projectId')) return;

        const loadState = async () => {
            // Check if this is a newly opened tab
            if (!sessionStorage.getItem('chat_tab_initialized_flag')) {
                const urlParams = new URLSearchParams(window.location.search);
                if (urlParams.get('fresh') !== 'true') {
                    // Ensure it starts fresh instead of saving
                    sessionStorage.setItem('chat_tab_initialized_flag', 'true');

                    // Show greeting for manual URL opens (not for routing buttons)
                    if (!searchParams.get('initialQuery') && !searchParams.get('queryKey')) {
                        const greetingText = CHAT_GREETINGS[Math.floor(Math.random() * CHAT_GREETINGS.length)];
                        setMessages([{
                            id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                            type: 'assistant',
                            content: greetingText,
                            timestamp: new Date()
                        }]);
                        console.log('[CHAT] Added greeting message for new tab (manual URL open)');
                    }

                    isRestoringStateRef.current = false;
                    return;
                }
            }

            // Check if we need to clear state (triggered by New button or fresh navigation)
            const urlParams = new URLSearchParams(window.location.search);
            const isFresh = urlParams.get('fresh') === 'true';
            const isNewTab = !sessionStorage.getItem('chat_tab_initialized_flag');

            if (sessionStorage.getItem('clear_chat_state') === 'true' || isFresh || isNewTab) {
                console.log('[CHAT] Not restoring state:', isFresh ? 'fresh navigation' : (isNewTab ? 'new tab' : 'clear requested'));

                if (sessionStorage.getItem('clear_chat_state') === 'true') {
                    sessionStorage.removeItem('clear_chat_state');
                    await clearChatDBState();
                }

                if (isNewTab) {
                    sessionStorage.setItem('chat_tab_initialized_flag', 'true');
                }

                // Remove fresh param from URL to prevent re-clearing on refresh
                if (isFresh) {
                    urlParams.delete('fresh');
                    const newUrl = urlParams.toString()
                        ? `${window.location.pathname}?${urlParams.toString()}`
                        : window.location.pathname;
                    window.history.replaceState({}, '', newUrl);
                }

                // Show a random greeting message for fresh navigation (not for routing buttons)
                if (isFresh && !searchParams.get('initialQuery') && !searchParams.get('queryKey')) {
                    const greetingText = CHAT_GREETINGS[Math.floor(Math.random() * CHAT_GREETINGS.length)];
                    setMessages([{
                        id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                        type: 'assistant',
                        content: greetingText,
                        timestamp: new Date()
                    }]);
                    console.log('[CHAT] Added greeting message for fresh navigation');
                }

                isRestoringStateRef.current = false;
                return; // Don't restore anything
            }

            try {
                // First check localStorage backup (faster/synchronous)
                let restoredState: any = null;
                try {
                    const backup = localStorage.getItem(getChatBackupKey());
                    if (backup) {
                        restoredState = JSON.parse(backup);
                        console.log('[CHAT] Loaded state from localStorage backup');
                    }
                } catch (e) {
                    console.warn('[CHAT] Failed to load backup:', e);
                }

                // If no backup, try IndexedDB
                if (!restoredState) {
                    restoredState = await loadStateFromChatDB();
                    if (restoredState) {
                        console.log('[CHAT] Loaded state from IndexedDB');
                    }
                }

                if (restoredState && restoredState.messages && restoredState.messages.length > 0) {
                    // Restore messages with proper Date objects
                    const restoredMessages = restoredState.messages.map((msg: any) => ({
                        ...msg,
                        timestamp: msg.timestamp ? new Date(msg.timestamp) : undefined
                    }));

                    setMessages(restoredMessages);

                    // Restore the saved chatInstanceId to maintain backend conversation context
                    if (restoredState.chatInstanceId) {
                        console.log('[CHAT] Restoring chatInstanceId:', restoredState.chatInstanceId);
                        setChatInstanceId(restoredState.chatInstanceId);
                    }

                    setHasAutoSubmitted(true); // Don't re-submit initial query
                    setIsHistory(true); // Disable animations

                    // Scroll to bottom
                    setTimeout(() => {
                        if (chatContainerRef.current) {
                            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
                        }
                    }, 100);
                } else {
                    // No saved state found - show greeting message
                    // This handles the case when returning from catalog with no prior messages
                    if (!searchParams.get('initialQuery') && !searchParams.get('queryKey')) {
                        const greetingText = CHAT_GREETINGS[Math.floor(Math.random() * CHAT_GREETINGS.length)];
                        setMessages([{
                            id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                            type: 'assistant',
                            content: greetingText,
                            timestamp: new Date()
                        }]);
                        console.log('[CHAT] Added greeting message - no saved state found');
                    }
                }
                isRestoringStateRef.current = false;
            } catch (e) {
                console.warn('[CHAT] Error restoring state:', e);
                // On error, also show greeting
                if (!searchParams.get('initialQuery') && !searchParams.get('queryKey')) {
                    const greetingText = CHAT_GREETINGS[Math.floor(Math.random() * CHAT_GREETINGS.length)];
                    setMessages([{
                        id: `greeting_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
                        type: 'assistant',
                        content: greetingText,
                        timestamp: new Date()
                    }]);
                    console.log('[CHAT] Added greeting message after error');
                }
                isRestoringStateRef.current = false;
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
                console.log('[CHAT] Loading project:', projectId);
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
                const chatHistory = convHistories['chat'];

                if (chatHistory && chatHistory.messages) {
                    // Set messages from saved history
                    setMessages(chatHistory.messages);
                    setIsHistory(true); // Mark as history so animations don't play

                    // Restore chatInstanceId from top level or nested location
                    const restoredInstanceId = project.projectInstanceId || project.project_instance_id ||
                        chatHistory.chatInstanceId;
                    if (restoredInstanceId) {
                        console.log('[CHAT] Restoring chatInstanceId:', restoredInstanceId);
                        setChatInstanceId(restoredInstanceId);
                    }

                    console.log('[CHAT] Loaded', chatHistory.messages.length, 'messages from project');

                    toast({
                        title: "Project Loaded",
                        description: `Loaded "${project.projectName || project.project_name}"`,
                    });
                }
            } catch (error: any) {
                console.error('[CHAT] Error loading project:', error);
                toast({
                    title: "Load Failed",
                    description: error.message || "Failed to load project",
                    variant: "destructive",
                });
            }
        };

        loadProject();
    }, [searchParams, toast]);

    // Set window name for BroadcastChannel targeting
    useEffect(() => {
        window.name = 'eng_chat';
    }, []);

    // BroadcastChannel listener for receiving queries from other pages
    useEffect(() => {
        const channel = new BroadcastChannel('eng-route-handoff');

        const onMessage = (event: MessageEvent) => {
            const data: any = event.data;
            if (!data || typeof data !== 'object') return;
            if (data.type !== 'chat_run_query') return;

            channel.postMessage({
                type: 'chat_ack',
                requestId: data.requestId
            });

            // Focus this window to bring it to front
            window.focus();

            const incomingQuery = String(data.query || '').trim();
            if (!incomingQuery) return;

            // Set input value directly, user hits send manually
            setTimeout(() => {
                setInputValue(incomingQuery);
            }, 0);
        };

        channel.addEventListener('message', onMessage);
        return () => {
            channel.removeEventListener('message', onMessage);
            channel.close();
        };
    }, []);

    // Handle query from URL parameter (when redirected from Solution page)
    useEffect(() => {
        if (hasAutoSubmitted) return;

        // Check for queryKey (sessionStorage/localStorage method)
        const queryKey = searchParams.get('queryKey');
        if (queryKey) {
            const storedQuery = sessionStorage.getItem(queryKey) || localStorage.getItem(queryKey);
            if (storedQuery) {
                console.log('[Chat] Auto-filling query from URL (key):', storedQuery);
                sessionStorage.removeItem(queryKey);
                localStorage.removeItem(queryKey); // cleanup in both
                setHasAutoSubmitted(true);
                setInputValue(storedQuery);
                return;
            }
        }

        // Check for direct initialQuery parameter
        const initialQuery = searchParams.get('initialQuery');
        if (initialQuery) {
            console.log('[Chat] Auto-filling query from URL (param):', initialQuery);
            setHasAutoSubmitted(true);
            setInputValue(initialQuery);
        }
    }, [searchParams, hasAutoSubmitted]);

    const queryChat = async (query: string): Promise<RAGResponse> => {
        try {
            const token = localStorage.getItem(AUTH_TOKEN_KEY);
            const response = await axios.post("/api/chat-agent", {
                query,
                session_id: chatInstanceId,
                user_session_id: userSessionId // Pass user session ID
            }, {
                withCredentials: true,
                headers: token ? { Authorization: `Bearer ${token}` } : {}
            });
            return toCamelCase(response.data) as RAGResponse;
        } catch (error: any) {
            console.error("RAG query error:", error);
            return {
                success: false,
                answer: error.response?.data?.answer || uiLabels.errorMessage,
                source: "unknown",
                foundInDatabase: false,
                awaitingConfirmation: false,
                sourcesUsed: [],
                error: error.message
            };
        }
    };

    // Separate function to submit query (used by both handleSend and auto-submit)
    const submitQuery = async (query: string) => {
        // Add user message
        const userMessage: ChatMessage = {
            id: `user_${Date.now()}`,
            type: "user",
            content: query,
            timestamp: new Date()
        };
        setMessages(prev => [...prev, userMessage]);
        setInputValue("");
        setIsLoading(true);
        setShowThinking(true);



        try {
            // =====================================================
            // STEP 1: Check if user is responding to route confirmation
            // =====================================================
            if (awaitingRouteConfirmation) {
                console.log('[ROUTE] User responding to route confirmation, calling LLM...');

                // Use LLM to classify yes/no/unclear
                const confirmResult = await confirmRouteResponse(
                    query,
                    "chat",
                    pendingRouteTarget,
                    pendingRouteQuery,
                    chatInstanceId,
                    userSessionId
                );

                console.log('[ROUTE] Confirmation result:', confirmResult);

                if (confirmResult.action === 'confirm' && confirmResult.proceedWithRouting) {
                    console.log(`[ROUTE] User confirmed - opening ${pendingRouteTarget}`);

                    setShowThinking(false);

                    // Check if we're routing back to the source page (Solution)
                    // In this case, send the query via BroadcastChannel to be processed
                    const normalizedTarget = pendingRouteTarget === 'solution' ? 'solution' : pendingRouteTarget;
                    if (sourcePage && (sourcePage === normalizedTarget || sourcePage === 'solution' && normalizedTarget === 'solution')) {
                        // Routing back to Solution page - send query via BroadcastChannel
                        console.log('[ROUTE] Routing back to source page (Solution) with query');

                        const requestId = `solution_back_${Date.now()}_${Math.random().toString(36).slice(2)}`;
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

                        // Send the query to Solution page
                        channel.postMessage({
                            type: 'solution_run_query',
                            requestId,
                            query: pendingRouteQuery
                        });

                        const acked = await ackPromise;
                        channel.close();

                        if (acked) {
                            // Solution page received the query - show message and focus
                            const switchMessage: ChatMessage = {
                                id: `assistant_switch_${Date.now()}`,
                                type: "assistant",
                                content: pendingRouteMessages.openingMessage || confirmResult.message,
                                timestamp: new Date()
                            };
                            setMessages(prev => [...prev, switchMessage]);

                            // Focus the Solution window with smooth transition
                            setTimeout(() => {
                                const solutionWindow = window.open('', 'eng_solution');
                                try {
                                    solutionWindow?.focus();
                                } catch { /* ignore focus errors */ }
                            }, 100);

                            toast({
                                title: "Query Sent",
                                description: "Your query has been sent to the Solution page.",
                            });

                            // Clear route confirmation state
                            setAwaitingRouteConfirmation(false);
                            setPendingRouteTarget("");
                            setPendingRouteQuery("");
                            setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
                            setIsLoading(false);
                            return;
                        }

                        // If BroadcastChannel failed, fall through to the regular approach below
                        console.log('[ROUTE] BroadcastChannel failed, falling through to regular approach');
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
                            // Focus the Solution window with smooth transition
                            setTimeout(() => {
                                const solutionWindow = window.open('', 'eng_solution');
                                try {
                                    solutionWindow?.focus();
                                } catch { /* ignore focus errors */ }
                            }, 100);

                            const confirmMessage: ChatMessage = {
                                id: `assistant_${Date.now()}`,
                                type: "assistant",
                                content: pendingRouteMessages.openingMessage || confirmResult.message,
                                timestamp: new Date()
                            };
                            setMessages(prev => [...prev, confirmMessage]);

                            setAwaitingRouteConfirmation(false);
                            setPendingRouteTarget("");
                            setPendingRouteQuery("");
                            setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
                            setIsLoading(false);
                            return;
                        }
                    }

                    // If search page is already open, send the query there instead of opening a duplicate tab
                    if (pendingRouteTarget === 'search') {
                        const preFocusWindow = window.open('', 'eng_search');
                        try {
                            preFocusWindow?.focus();
                        } catch { /* ignore focus errors */ }

                        const requestId = `search_${Date.now()}_${Math.random().toString(36).slice(2)}`;
                        const channel = new BroadcastChannel('eng-route-handoff');

                        const ackPromise = new Promise<boolean>((resolve) => {
                            const timeout = window.setTimeout(() => {
                                channel.removeEventListener('message', onMessage);
                                resolve(false);
                            }, 150);

                            const onMessage = (event: MessageEvent) => {
                                const data: any = event.data;
                                if (data && data.type === 'search_ack' && data.requestId === requestId) {
                                    window.clearTimeout(timeout);
                                    channel.removeEventListener('message', onMessage);
                                    resolve(true);
                                }
                            };

                            channel.addEventListener('message', onMessage);
                        });

                        channel.postMessage({
                            type: 'search_run_query',
                            requestId,
                            query: pendingRouteQuery
                        });

                        const acked = await ackPromise;
                        channel.close();

                        if (acked) {
                            // Focus the search window with smooth transition
                            setTimeout(() => {
                                const searchWindow = window.open('', 'eng_search');
                                try {
                                    searchWindow?.focus();
                                } catch { /* ignore focus errors */ }
                            }, 100);

                            const confirmMessage: ChatMessage = {
                                id: `assistant_${Date.now()}`,
                                type: "assistant",
                                content: pendingRouteMessages.openingMessage || confirmResult.message,
                                timestamp: new Date()
                            };
                            setMessages(prev => [...prev, confirmMessage]);

                            setAwaitingRouteConfirmation(false);
                            setPendingRouteTarget("");
                            setPendingRouteQuery("");
                            setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
                            setIsLoading(false);
                            return;
                        }
                    }

                    // NOT going back to source - show opening message and open new window
                    const confirmMessage: ChatMessage = {
                        id: `assistant_${Date.now()}`,
                        type: "assistant",
                        content: pendingRouteMessages.openingMessage || confirmResult.message,
                        timestamp: new Date()
                    };
                    setMessages(prev => [...prev, confirmMessage]);

                    // Store query for target page in localStorage (shared across tabs)
                    const queryKey = `route_query_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                    localStorage.setItem(queryKey, pendingRouteQuery);

                    // Build URL based on target page
                    let targetUrl = '';
                    if (pendingRouteTarget === 'solution') {
                        targetUrl = `/solution?queryKey=${queryKey}&fresh=true`;
                    } else if (pendingRouteTarget === 'search') {
                        targetUrl = `/search?queryKey=${queryKey}&fresh=true`;
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
                            : pendingRouteTarget === 'search' ? 'eng_search'
                                : '_blank';
                        newWindow = window.open(targetUrl, windowName);
                        routingWindows[pendingRouteTarget] = newWindow;
                        console.log(`[ROUTING] Opened new window for target: ${pendingRouteTarget}`);
                    }
                    const isPopupBlocked = !newWindow || newWindow.closed || typeof newWindow.closed === 'undefined';
                    if (isPopupBlocked) {
                        const linkMessage: ChatMessage = {
                            id: `assistant_link_${Date.now()}`,
                            type: "assistant",
                            content: `${pendingRouteMessages.popupBlockedMessage || ""}\n\n[Open page](${targetUrl})`.trim(),
                            timestamp: new Date()
                        };
                        setMessages(prev => [...prev, linkMessage]);
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
                    setIsLoading(false);
                    return;
                }

                if (confirmResult.action === 'decline') {
                    console.log('[ROUTE] User declined - staying on Product Info');

                    setShowThinking(false);

                    // Use LLM-generated decline message
                    const declineMessageContent: ChatMessage = {
                        id: `assistant_${Date.now()}`,
                        type: "assistant",
                        content: confirmResult.message,
                        timestamp: new Date()
                    };
                    setMessages(prev => [...prev, declineMessageContent]);

                    // Clear route confirmation state
                    setAwaitingRouteConfirmation(false);
                    setPendingRouteTarget("");
                    setPendingRouteQuery("");
                    setPendingRouteMessages({ openingMessage: "", declineMessage: "", popupBlockedMessage: "" });
                    setIsLoading(false);
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
            // STEP 2: Directly call Product Info query (chat agent wrapper)
            // =====================================================
            const response = await queryChat(query);

            // Hide thinking indicator
            setShowThinking(false);

            // Check if routing is required
            if (response.routerResult?.requiresRouting && response.routerResult?.targetPage) {
                const targetPage = response.routerResult.targetPage;
                let routingUrl = response.routerResult.routingUrl || `/${targetPage}`;

                // Construct queryKey routing URL if we have a query
                if (query) {
                    const queryKey = `route_query_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                    localStorage.setItem(queryKey, query);
                    routingUrl = `/${targetPage}?queryKey=${queryKey}&fresh=true`;
                }

                // Add assistant message with routing button metadata
                const routingMessage: ChatMessage = {
                    id: `assistant_${Date.now()}`,
                    type: "assistant",
                    content: response.answer,
                    source: response.source,
                    timestamp: new Date(),
                    metadata: {
                        routerRedirect: true,
                        routerUrl: routingUrl,
                        routerTargetPage: targetPage
                    }
                };
                setMessages(prev => [...prev, routingMessage]);

                toast({
                    title: "Navigation Available",
                    description: `This query is best handled on the ${targetPage.charAt(0).toUpperCase() + targetPage.slice(1)} page`,
                });
            } else {
                // Normal response handling (valid chat query or invalid without routing)
                // Add assistant message
                const assistantMessage: ChatMessage = {
                    id: `assistant_${Date.now()}`,
                    type: "assistant",
                    content: response.answer,
                    source: response.source,
                    sourcesUsed: response.sourcesUsed,
                    awaitingConfirmation: response.awaitingConfirmation,
                    timestamp: new Date()
                };
                setMessages(prev => [...prev, assistantMessage]);

                // Show toast for source - only if response is successful
                if (response.success) {
                    if (response.source === "database") {
                        toast({
                            title: uiLabels.sourceDatabase,
                            description: `${response.sourcesUsed?.join(", ") || "database"}`,
                        });
                    } else if (response.source === "llm") {
                        toast({
                            title: uiLabels.sourceLlm,
                            description: "AI knowledge",
                        });
                    }
                } else if (response.error || !response.success) {
                    // Show error toast if response failed
                    toast({
                        title: "Error",
                        description: response.error || uiLabels.errorMessage,
                        variant: "destructive",
                    });
                }
            }
        } catch (error) {
            console.error("Error querying product info:", error);
            setShowThinking(false);
            toast({
                title: "Error",
                description: uiLabels.errorMessage,
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Enforce textarea height when inputValue changes programmatically
    useEffect(() => {
        if (textareaRef.current) {
            const textarea = textareaRef.current;
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`;
        }
    }, [inputValue]);

    // Feedback helper functions
    const openFeedbackModal = (
        key: string,
        itemType: string,
        itemName: string,
        initialFeedbackType?: FeedbackType,
        itemData?: any
    ) => {
        setFeedbackModalItem({ key, type: itemType, name: itemName, data: itemData });
        setFeedbackModalOpen(true);
        if (!feedbackState[key]) {
            setFeedbackState(prev => ({
                ...prev,
                [key]: { type: initialFeedbackType || null, comment: '', loading: false, submitted: false }
            }));
        } else if (initialFeedbackType) {
            setFeedbackState(prev => ({
                ...prev,
                [key]: { ...prev[key], type: initialFeedbackType }
            }));
        }
    };

    const closeFeedbackModal = () => {
        setFeedbackModalOpen(false);
        setTimeout(() => setFeedbackModalItem(null), 200);
    };

    const submitFeedbackForItem = async () => {
        if (!feedbackModalItem) return;

        const { key, type: itemType, name: itemName, data: itemData } = feedbackModalItem;
        const fb = feedbackState[key];
        if (!fb || (!fb.type && !fb.comment.trim())) {
            toast({ title: "No feedback provided", description: "Please select thumbs up/down or add a comment", variant: "destructive" });
            return;
        }

        setFeedbackState(prev => ({ ...prev, [key]: { ...prev[key], loading: true } }));

        try {
            const itemMetadata = {
                itemType: 'chat_response',
                itemName: 'Chat Response',
                chatMessageId: itemData?.id || '',
                chatContent: itemData?.content || itemName,
                userQuery: messages[messages.findIndex(m => m.id === itemData?.id) - 1]?.content || '',
                sessionId: chatInstanceId || '',
                source: 'chat'
            };

            const { submitFeedback } = await import('@/components/AIRecommender/api');
            const response = await submitFeedback(
                fb.type,
                fb.comment.trim(),
                undefined,
                itemMetadata
            );

            setFeedbackState(prev => ({
                ...prev,
                [key]: { ...prev[key], loading: false, submitted: true, response }
            }));
            toast({ title: "Feedback submitted!", description: "Thank you for your feedback." });

            setTimeout(() => {
                closeFeedbackModal();
            }, 1500);
        } catch (error: any) {
            setFeedbackState(prev => ({ ...prev, [key]: { ...prev[key], loading: false } }));
            toast({ title: "Error", description: error.message || "Failed to submit feedback", variant: "destructive" });
        }
    };

    const handleFeedbackKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submitFeedbackForItem();
        }
    };

    const setFeedbackType = (key: string, type: FeedbackType) => {
        setFeedbackState(prev => ({
            ...prev,
            [key]: { ...prev[key], type, comment: prev[key]?.comment || '', loading: false, submitted: false }
        }));
    };

    const setFeedbackComment = (key: string, comment: string) => {
        setFeedbackState(prev => ({
            ...prev,
            [key]: { ...prev[key], comment, loading: false, submitted: false }
        }));
    };

    const handleSend = async () => {
        const trimmedInput = inputValue.trim();
        if (!trimmedInput) {
            return;
        }

        // Reset textarea height to initial height before sending
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }

        await submitQuery(trimmedInput);
    };

    const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        handleSend();
    };

    const handleKeyPress = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    // Helper to extract first N words from input
    const extractFirstWords = (input: string, count: number = 2): string => {
        if (!input || typeof input !== 'string') return 'Product Info';

        // Clean and split the input
        const words = input.trim().split(/\s+/).filter(word => word.length > 0);

        if (words.length === 0) return 'Product Info';

        // Take first N words and capitalize first letter of each
        const firstWords = words.slice(0, count).map(word =>
            word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
        ).join(' ');

        return firstWords || 'Product Info';
    };



    // Reset duplicate dialog state
    const resetDuplicateDialog = () => {
        setDuplicateNameDialogOpen(false);
        setDuplicateProjectName(null);
        setAutoRenameSuggestion(null);
        setDuplicateDialogError(null);
        setDuplicateDialogNameInput('');
    };

    // Save project functionality with duplicate name handling
    const handleSaveProject = async (
        overrideName?: string,
        options?: { skipDuplicateDialog?: boolean; isAutoSave?: boolean }
    ) => {
        if (messages.length === 0) {
            if (!options?.isAutoSave) {
                toast({
                    title: "Nothing to Save",
                    description: "Start a conversation first before saving.",
                    variant: "destructive",
                });
            }
            return;
        }

        try {
            // Extract first 2 words from the first user message for project name
            let projectNameBase = 'Product Info';
            const firstUserMessage = messages.find(m => m.type === 'user');
            if (firstUserMessage && firstUserMessage.content) {
                projectNameBase = extractFirstWords(firstUserMessage.content, 2);
            }

            // Use override name if provided, otherwise add "(Product Info)" suffix
            const effectiveProjectName = overrideName
                ? overrideName.trim()
                : `${projectNameBase} (Product Info)`;

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
            const firstUserMsg = messages.find(m => m.type === 'user');
            const initialRequirements = firstUserMsg?.content || 'Chat inquiry';

            const projectData = {
                project_name: effectiveProjectName,
                project_description: `Chat conversation - Created on ${new Date().toLocaleDateString()}`,
                initial_requirements: initialRequirements,
                source_page: 'chat',
                project_instance_id: chatInstanceId, // Save the chat instance ID at top level
                conversation_histories: {
                    'chat': {
                        messages: messages,
                        chatInstanceId: chatInstanceId,
                    }
                },
                product_type: 'chat',
                current_step: 'conversation',
                workflow_position: {
                    current_tab: 'chat',
                    has_results: messages.length > 0,
                    last_interaction: new Date().toISOString(),
                    project_phase: 'product_inquiry'
                },
                user_interactions: {
                    conversations_count: 1,
                    messages_count: messages.length,
                    last_save: new Date().toISOString()
                }
            };

            console.log('[CHAT_SAVE] Saving project:', effectiveProjectName);

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
            console.log('[CHAT_SAVE] Project saved successfully:', result);

            if (!options?.isAutoSave) {
                toast({
                    title: "Project Saved",
                    description: `"${effectiveProjectName}" has been saved successfully.`,
                });
            }

        } catch (error: any) {
            console.error('[CHAT_SAVE] Error saving project:', error);
            if (!options?.isAutoSave) {
                toast({
                    title: "Save Failed",
                    description: error.message || "Failed to save project",
                    variant: "destructive",
                });
            }
        }
    };

    handleSaveProjectRef.current = handleSaveProject;

    // Handle duplicate name dialog actions
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
        const baseName = (duplicateProjectName || '').trim() || 'Chat';
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
        <div className="h-screen w-full app-glass-gradient flex flex-col overflow-hidden relative custom-visible-scrollbar-dark">
            {/* Decorative background images */}
            <div className="absolute inset-0 pointer-events-none overflow-hidden z-0 flex items-center justify-center">
                <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-8 md:translate-y-12" />
            </div>

            {/* MAIN HEADER - Fixed at top with animated video logo and profile */}
            <MainHeader onSave={() => handleSaveProject()} />

            {/* SECOND HEADER - Below main header, not scrollable */}
            <div className="flex-none pt-24 pb-0">
                <div className="py-0 border-b border-white/10 bg-transparent flex justify-center items-center">
                    <div className="flex items-center gap-0 animate-item stagger-1">
                        <div className="flex items-center justify-center">
                            <img src="/engenie logo.jpeg" alt="Logo" className="w-24 h-24 object-contain" />
                        </div>
                        <h1 className="text-3xl font-bold text-white inline-flex items-center gap-2 whitespace-nowrap -ml-6">
                            Product Chat
                        </h1>
                    </div>
                </div>
            </div>

            {/* Chat Messages Area - Scrolls behind the input */}
            <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-4 space-y-4 custom-no-scrollbar pb-24">
                {messages.map((message) => (
                    <MessageRow
                        key={message.id}
                        message={message}
                        isHistory={isHistory}
                        uiLabels={uiLabels}
                        onFeedbackClick={openFeedbackModal}
                    />
                ))}

                {/* Bouncing Dots Loading Indicator */}
                {showThinking && (
                    <div className="flex justify-start">
                        <div className="max-w-[80%] flex items-start space-x-2">
                            <div className="flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center bg-transparent">
                                <img src="/engenie icon.jpeg" alt="Assistant" className="w-20 h-20 object-contain rounded-full" />
                            </div>
                            <div className="p-3 rounded-lg">
                                <BouncingDots />
                                <span className="sr-only">{uiLabels.loadingText}</span>
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input Form - Fixed at viewport bottom, messages scroll behind it */}
            <div className="fixed bottom-0 left-0 right-0 p-4 bg-transparent z-30 pointer-events-none">
                <div className="max-w-4xl mx-auto px-2 md:px-8 pointer-events-auto">
                    {/* Privacy badge */}

                    <form onSubmit={handleSubmit}>
                        <div className="relative group">
                            <div
                                className="chat-input-wrapper relative w-full rounded-2xl flex items-end transition-all duration-300 bg-[#212121] border border-white/10 hover:border-white/20 focus-within:border-white/30 shadow-2xl p-2"
                                style={{
                                    WebkitBackdropFilter: 'blur(12px)',
                                    backdropFilter: 'blur(12px)',
                                    color: '#f4f4f5'
                                }}
                            >
                                <textarea
                                    ref={textareaRef}
                                    value={inputValue}
                                    onChange={(e) => setInputValue(e.target.value)}
                                    onKeyDown={handleKeyPress}
                                    onInput={(e) => {
                                        const target = e.target as HTMLTextAreaElement;
                                        target.style.height = 'auto';
                                        target.style.height = `${Math.min(target.scrollHeight, 150)}px`;
                                    }}
                                    className="flex-1 min-w-0 bg-transparent border-0 focus:ring-0 focus:outline-none px-4 py-2.5 text-sm resize-none min-h-[40px] max-h-[150px] leading-relaxed custom-visible-scrollbar-dark text-white placeholder:text-zinc-500"
                                    style={{
                                        fontSize: '15px',
                                        fontFamily: 'inherit',
                                        boxShadow: 'none',
                                        overflowY: 'auto'
                                    }}
                                    placeholder="Ask about products, vendors, or specifications..."
                                    disabled={isLoading}
                                />

                                {/* Action Button - flex sibling so scrollbar appears to its left */}
                                <div className="flex-shrink-0 pb-1 pr-1 flex items-center gap-1">
                                    <Button
                                        type="submit"
                                        disabled={!inputValue.trim() || isLoading}
                                        className={`w-9 h-9 p-0 rounded-xl flex items-center justify-center transition-all duration-200 ${!inputValue.trim() || isLoading
                                                ? 'bg-zinc-800 text-zinc-500 opacity-50 cursor-not-allowed'
                                                : 'bg-sky-500 hover:bg-sky-400 text-white shadow-lg shadow-sky-500/25 active:scale-95'
                                            }`}
                                        variant="ghost"
                                        size="icon"
                                        title="Submit"
                                    >
                                        {isLoading ? (
                                            <Loader2 className="h-4 w-4 animate-spin text-white" />
                                        ) : (
                                            <Send className="h-4 w-4" />
                                        )}
                                    </Button>
                                </div>
                            </div>
                        </div>
                    </form>
                </div>
            </div>

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
                            <label htmlFor="duplicate-project-name-input-pi" className="text-sm font-medium">
                                New project name
                            </label>
                            <input
                                id="duplicate-project-name-input-pi"
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

            {/* Feedback Modal */}
            {feedbackModalOpen && (() => {
                const feedbackKey = feedbackModalItem?.key || '';
                const fb = feedbackState[feedbackKey] || { type: null, comment: '', loading: false, submitted: false };

                return (
                    <div className="fixed inset-0 z-50 flex items-center justify-center p-6 animate-in fade-in duration-200">
                        <div
                            className="max-w-sm w-full relative animate-in zoom-in-95 duration-300 acrylic-glass-pill p-6"
                            style={{ backdropFilter: 'blur(80px)', backgroundColor: 'rgba(255, 255, 255, 0.65)' }}
                        >
                            <button
                                onClick={closeFeedbackModal}
                                className="absolute top-5 right-8 text-muted-foreground hover:text-foreground hover:scale-125 transition-all duration-200"
                            >
                                <span className="text-lg">✕</span>
                            </button>

                            <div className="text-center mb-4">
                                <div className="flex items-center justify-center gap-2 mb-1">
                                    <span className="text-3xl opacity-80">💬</span>
                                    <h2 className="text-xl font-bold">Feedback</h2>
                                </div>
                                <p className="text-muted-foreground text-xs">
                                    Help us improve by sharing your thoughts on<br />
                                    <span className="font-semibold">this response</span>
                                </p>
                            </div>

                            {fb.submitted ? (
                                <div className="text-center py-6">
                                    <div className="text-4xl mb-3">✓</div>
                                    <p className="font-semibold text-lg mb-2">Thank you!</p>
                                    <p className="text-sm text-muted-foreground mb-4">{fb.response || 'Your feedback has been submitted.'}</p>
                                </div>
                            ) : (
                                <>
                                    <div className="flex justify-center gap-6 mb-6">
                                        <button onClick={() => setFeedbackType(feedbackKey, 'positive')} className="flex flex-col items-center gap-2">
                                            <img
                                                src="/icon-thumbs-3d.png"
                                                alt="Thumbs Up"
                                                className={`h-16 w-16 transition-all duration-200 ${fb.type === 'positive' ? 'brightness-100 saturate-150 drop-shadow-lg scale-110' : 'brightness-75 opacity-60'}`}
                                            />
                                        </button>
                                        <button onClick={() => setFeedbackType(feedbackKey, 'negative')} className="flex flex-col items-center gap-2">
                                            <img
                                                src="/icon-thumbsdown-3d.png"
                                                alt="Thumbs Down"
                                                className={`h-16 w-16 transition-all duration-200 ${fb.type === 'negative' ? 'brightness-100 saturate-150 drop-shadow-lg scale-110' : 'brightness-75 opacity-60'}`}
                                            />
                                        </button>
                                    </div>

                                    <Textarea
                                        placeholder="Additional comments (optional)"
                                        value={fb.comment}
                                        onChange={(e) => setFeedbackComment(feedbackKey, e.target.value)}
                                        onKeyDown={handleFeedbackKeyDown}
                                        className="mb-4 bg-white/50 border-gray-200 min-h-[80px]"
                                    />

                                    <div className="flex gap-2">
                                        <Button
                                            type="button"
                                            variant="outline"
                                            onClick={closeFeedbackModal}
                                            className="flex-1"
                                        >
                                            Cancel
                                        </Button>
                                        <Button
                                            type="button"
                                            onClick={submitFeedbackForItem}
                                            disabled={fb.loading || (!fb.type && !fb.comment.trim())}
                                            className={`flex-1 rounded-xl py-2.5 font-semibold transition-opacity duration-300 hover:brightness-100 hover:saturate-100 ${fb.loading || (!fb.type && !fb.comment.trim())
                                                ? 'btn-glass-primary opacity-50 cursor-not-allowed'
                                                : 'btn-glass-primary'
                                                }`}
                                        >
                                            {fb.loading ? (
                                                <>
                                                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                                                    Submitting...
                                                </>
                                            ) : (
                                                "Submit Feedback"
                                            )}
                                        </Button>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                );
            })()}


        </div>
    );
};

export default Chat;
