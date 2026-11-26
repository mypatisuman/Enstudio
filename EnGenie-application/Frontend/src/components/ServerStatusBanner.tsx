import { useState, useEffect, useCallback, useRef } from 'react';
import { X, AlertTriangle } from 'lucide-react';
import { BASE_URL } from '@/components/AIRecommender/api';

const FAILURE_THRESHOLD = 3; // Show banner only after this many consecutive failures

interface ServerStatusBannerProps {
    /** Custom message to display. If not provided, uses default server error message */
    message?: string;
    /** How often to check server health in milliseconds. Default: 30000 (30 seconds) */
    checkInterval?: number;
    /** Callback when server status changes */
    onStatusChange?: (isDown: boolean) => void;
    /** Callback when the banner is dismissed by the user */
    onDismiss?: () => void;
}

const ServerStatusBanner = ({
    message = "Server is currently experiencing issues. Some features may be unavailable.",
    checkInterval = 30000,
    onStatusChange,
    onDismiss
}: ServerStatusBannerProps) => {
    const FAILURE_THRESHOLD = 3; // Must fail 3 times consecutively before showing
    const [isServerDown, setIsServerDown] = useState(false);
    const [isDismissed, setIsDismissed] = useState(false);
    // useRef so the counter never causes re-renders and is never stale inside callbacks
    const consecutiveFailures = useRef(0);
    const isMounted = useRef(true);
    // Store the current AbortController so we can cancel in-flight requests on unmount
    const abortControllerRef = useRef<AbortController | null>(null);

    const checkServerHealth = useCallback(async () => {
        let failed = false;
        let backendOfficiallyDown = false;

        const controller = new AbortController();
        abortControllerRef.current = controller;
        // Abort if server hasn't responded within 10 seconds (fast path should be instant)
        const timeoutId = setTimeout(() => controller.abort(), 10000);

        try {
            const response = await fetch(`${BASE_URL}/api/health`, {
                method: 'GET',
                signal: controller.signal,
                credentials: 'include'
            });

            clearTimeout(timeoutId);

            try {
                const data = await response.json();
                if (data && data.system_officially_down !== undefined) {
                    // Backend already applies its own 3-consecutive-failures rule
                    failed = data.system_officially_down;
                    if (data.system_officially_down) {
                        backendOfficiallyDown = true;
                    }
                } else {
                    // Fallback: treat unhealthy status as a failure (counted below)
                    failed = data.status === 'unhealthy';
                }
            } catch {
                failed = !response.ok;
            }
        } catch {
            clearTimeout(timeoutId);
            // Network error / timeout counts as a failure
            failed = true;
        }

        // Don't update state if the component has been unmounted
        if (!isMounted.current) return;

        if (failed) {
            consecutiveFailures.current += 1;
            if (backendOfficiallyDown || consecutiveFailures.current >= FAILURE_THRESHOLD) {
                setIsServerDown(prev => {
                    if (!prev) onStatusChange?.(true);
                    return true;
                });
            }
            // Below threshold — don't show banner yet, keep counting
        } else {
            consecutiveFailures.current = 0;
            setIsServerDown(prev => {
                if (prev) {
                    // Recovered — re-show banner next time it goes down
                    setIsDismissed(false);
                    onStatusChange?.(false);
                }
                return false;
            });
        }
    }, [onStatusChange]);

    useEffect(() => {
        isMounted.current = true;
        // Delay the first check slightly so a slow cold-start doesn't show the banner
        // on page load before the server has had any chance to respond
        const initialDelay = setTimeout(() => checkServerHealth(), 5000);
        const intervalId = setInterval(checkServerHealth, checkInterval);
        return () => {
            isMounted.current = false;
            abortControllerRef.current?.abort();
            clearTimeout(initialDelay);
            clearInterval(intervalId);
        };
    }, [checkServerHealth, checkInterval]);

    // Sync banner visibility into a CSS variable so MainHeader and content can offset
    useEffect(() => {
        const visible = isServerDown && !isDismissed;
        document.documentElement.style.setProperty(
            '--banner-height',
            visible ? '40px' : '0px'
        );
        return () => {
            document.documentElement.style.setProperty('--banner-height', '0px');
        };
    }, [isServerDown, isDismissed]);

    if (!isServerDown || isDismissed) {
        return null;
    }

    return (
        <div
            className="relative w-full bg-red-600 text-white px-4 py-2 flex items-center justify-center z-[70]"
            style={{ height: '40px' }}
            role="alert"
            aria-live="polite"
        >
            <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                <span className="text-sm font-medium">{message}</span>
            </div>
            <button
                onClick={() => { setIsDismissed(true); onDismiss?.(); }}
                className="absolute right-4 p-1 hover:bg-red-700 rounded transition-colors flex-shrink-0"
                aria-label="Dismiss server status banner"
            >
                <X className="h-4 w-4" />
            </button>
        </div>
    );
};

export default ServerStatusBanner;
