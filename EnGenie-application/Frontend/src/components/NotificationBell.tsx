import { useState, useEffect, useRef } from 'react';
import { Bell, Check, CheckCheck, AlertTriangle, CheckCircle2, X, Trash2 } from 'lucide-react';
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import {
    getAdminNotifications,
    getUnreadNotificationCount,
    markNotificationRead,
    markAllNotificationsRead,
    deleteAdminNotification,
    deleteAllNotifications,
    AdminNotification,
} from '@/components/AIRecommender/api';
import { playNotificationSound } from '@/utils/sound';

interface NotificationBellProps {
    className?: string;
}

const NotificationBell = ({ className = "" }: NotificationBellProps) => {
    const [isOpen, setIsOpen] = useState(false);
    const [expandedId, setExpandedId] = useState<string | null>(null);
    const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
    const [notifications, setNotifications] = useState<AdminNotification[]>([]);
    const [unreadCount, setUnreadCount] = useState(0);
    const [isLoading, setIsLoading] = useState(false);
    const [filter, setFilter] = useState<'all' | 'unread' | 'read'>('all');
    const panelRef = useRef<HTMLDivElement>(null);
    const bellRef = useRef<HTMLButtonElement>(null);
    const [panelTop, setPanelTop] = useState(0);
    const initialLoadRef = useRef(true);
    const prevCountRef = useRef(0);

    // Track bell's viewport position so the panel (fixed on mobile) opens below it, never off-screen
    useEffect(() => {
        if (!isOpen || !bellRef.current) return;
        const updatePosition = () => setPanelTop(bellRef.current!.getBoundingClientRect().bottom + 8);
        updatePosition();
        window.addEventListener('resize', updatePosition);
        return () => window.removeEventListener('resize', updatePosition);
    }, [isOpen]);

    // Fetch unread count on mount and every 60 seconds
    useEffect(() => {
        fetchUnreadCount();
        const interval = setInterval(fetchUnreadCount, 60000);
        return () => clearInterval(interval);
    }, []);

    // Close panel on clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                panelRef.current &&
                !panelRef.current.contains(event.target as Node) &&
                bellRef.current &&
                !bellRef.current.contains(event.target as Node)
            ) {
                setIsOpen(false);
                setConfirmDeleteId(null);
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isOpen]);

    const fetchUnreadCount = async () => {
        const count = await getUnreadNotificationCount();
        if (!initialLoadRef.current && count > prevCountRef.current) {
            playNotificationSound();
        }
        initialLoadRef.current = false;
        prevCountRef.current = count;
        setUnreadCount(count);
    };

    // Auto-refresh notifications when the panel is open
    useEffect(() => {
        if (!isOpen) return;
        
        const interval = setInterval(() => {
            getAdminNotifications(30, 0, filter).then((result) => {
                setNotifications(result.notifications);
                setUnreadCount(result.unreadCount);
            }).catch(console.error);
        }, 30000);

        return () => clearInterval(interval);
    }, [isOpen, filter]);

    const fetchNotifications = async () => {
        setIsLoading(true);
        const result = await getAdminNotifications(30, 0, filter);
        setNotifications(result.notifications);
        setUnreadCount(result.unreadCount);
        setIsLoading(false);
    };

    // Re-fetch when filter changes
    useEffect(() => {
        if (isOpen) {
            fetchNotifications();
        }
    }, [filter]);

    const handleBellClick = () => {
        if (!isOpen) {
            fetchNotifications();
        }
        setIsOpen(!isOpen);
    };

    const handleMarkRead = async (notificationId: string) => {
        const success = await markNotificationRead(notificationId);
        if (success) {
            setNotifications(prev =>
                prev.map(n => n.id === notificationId ? { ...n, isRead: true } : n)
            );
            setUnreadCount(prev => Math.max(0, prev - 1));
        }
    };

    const handleMarkAllRead = async () => {
        await markAllNotificationsRead();
        setNotifications(prev => prev.map(n => ({ ...n, isRead: true })));
        setUnreadCount(0);
    };

    const handleDelete = async (notificationId: string) => {
        const success = await deleteAdminNotification(notificationId);
        if (success) {
            const wasUnread = notifications.find(n => n.id === notificationId && !n.isRead);
            setNotifications(prev => prev.filter(n => n.id !== notificationId));
            if (wasUnread) {
                setUnreadCount(count => Math.max(0, count - 1));
            }
            if (expandedId === notificationId) {
                setExpandedId(null);
            }
            if (confirmDeleteId === notificationId) {
                setConfirmDeleteId(null);
            }
        }
    };

    const handleDeleteAll = async () => {
        if (notifications.length === 0) return;
        
        const success = await deleteAllNotifications();
        if (success > 0 || notifications.length > 0) {
            setNotifications([]);
            setUnreadCount(0);
            setExpandedId(null);
            setConfirmDeleteId(null);
        }
    };

    const formatTimeAgo = (dateString: string) => {
        try {
            // Append Z if no timezone information is present to ensure correct UTC parsing
            const safeDateString = (dateString && !dateString.endsWith('Z') && !dateString.includes('+')) 
                ? `${dateString}Z` 
                : dateString;
                
            const date = new Date(safeDateString);
            const now = new Date();
            const diffMs = now.getTime() - date.getTime();
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return `${diffMins}m ago`;
            if (diffHours < 24) return `${diffHours}h ago`;
            if (diffDays < 7) return `${diffDays}d ago`;
            return date.toLocaleDateString();
        } catch {
            return '';
        }
    };

    const getPageColor = (page: string) => {
        switch (page) {
            case 'solution': return 'text-purple-500';
            case 'search': return 'text-blue-500';
            case 'chat': return 'text-green-500';
            default: return 'text-slate-500';
        }
    };

    return (
        <div className={`relative ${className}`}>
            {/* Bell Button */}
            <Tooltip>
                <TooltipTrigger asChild>
                    <button
                        type="button"
                        ref={bellRef}
                        onClick={handleBellClick}
                        className="w-10 h-10 rounded-lg glass-card flex items-center justify-center hover:scale-110 transition-transform cursor-pointer relative"
                        aria-label="Notifications"
                    >
                        <Bell className={`h-5 w-5 ${unreadCount > 0 ? 'text-amber-500' : 'text-primary'}`} />

                        {/* Unread Badge */}
                        {unreadCount > 0 && (
                            <span className="absolute -top-1 -right-1 min-w-[18px] h-4.5 flex items-center justify-center rounded-full bg-gradient-to-r from-red-500 to-red-600 text-white text-[10px] font-semibold px-1 shadow-md border border-white/20 dark:border-slate-800/20 animate-in zoom-in duration-200">
                                {unreadCount > 99 ? '99+' : unreadCount}
                            </span>
                        )}
                    </button>
                </TooltipTrigger>
                <TooltipContent><p>Notifications</p></TooltipContent>
            </Tooltip>

            {/* Notification Panel */}
            {isOpen && (
                <div
                    ref={panelRef}
                    className="fixed sm:absolute left-3 right-3 sm:left-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[400px] max-h-[500px] z-50 rounded-xl bg-gradient-to-br from-[#F5FAFC]/95 to-[#EAF6FB]/95 dark:from-slate-900/95 dark:to-slate-800/95 backdrop-blur-xl border border-white/30 dark:border-slate-700/50 shadow-2xl animate-in fade-in slide-in-from-top-2 duration-200 overflow-hidden flex flex-col"
                    style={window.innerWidth < 640 ? { top: panelTop } : undefined}
                >
                    {/* Header */}
                    <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/50 dark:border-slate-700/50">
                        <div className="flex items-center gap-2">
                            <AlertTriangle className="h-4 w-4 text-amber-500" />
                            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                                User Failure Alerts
                            </h3>
                            {unreadCount > 0 && (
                                <span className="px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 text-[11px] font-medium">
                                    {unreadCount} new
                                </span>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            {notifications.length > 0 && (
                                <div className="flex items-center gap-1 mr-1">
                                    <button
                                        type="button"
                                        onClick={handleMarkAllRead}
                                        className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                                        title="Mark all as read"
                                    >
                                        <CheckCheck className="h-3.5 w-3.5" />
                                    </button>
                                    <button
                                        type="button"
                                        onClick={handleDeleteAll}
                                        className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                        title="Delete all notifications"
                                    >
                                        <Trash2 className="h-3.5 w-3.5" />
                                    </button>
                                </div>
                            )}
                            <button
                                type="button"
                                onClick={() => setIsOpen(false)}
                                className="p-1.5 rounded-md hover:bg-slate-200/60 dark:hover:bg-slate-700/60 transition-colors"
                                aria-label="Close"
                            >
                                <X className="h-4 w-4 text-slate-500 dark:text-slate-400" />
                            </button>
                        </div>
                    </div>
                    
                    {/* Filters */}
                    <div className="flex items-center gap-1 px-4 py-2 border-b border-slate-200/40 dark:border-slate-700/40 bg-slate-50/50 dark:bg-slate-900/30">
                        {(['all', 'unread', 'read'] as const).map((f) => (
                            <button
                                key={f}
                                onClick={() => setFilter(f)}
                                className={`px-2.5 py-1 rounded-full text-[10px] font-semibold uppercase tracking-wider transition-all duration-200 ${
                                    filter === f
                                        ? 'bg-blue-600 text-white shadow-sm'
                                        : 'text-slate-500 dark:text-slate-400 hover:bg-slate-200/60 dark:hover:bg-slate-800/60'
                                }`}
                            >
                                {f}
                            </button>
                        ))}
                    </div>

                    {/* Notification List */}
                    <div className="overflow-y-auto flex-1 max-h-[420px] custom-visible-scrollbar-dark">
                        {isLoading ? (
                            <div className="flex items-center justify-center py-8">
                                <div className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                            </div>
                        ) : notifications.length === 0 ? (
                            <div className="flex flex-col items-center justify-center py-10 text-slate-400 dark:text-slate-500">
                                <Bell className="h-8 w-8 mb-2 opacity-50" />
                                <p className="text-sm">No notifications yet</p>
                                <p className="text-xs mt-1 opacity-75">User failures will appear here</p>
                            </div>
                        ) : (
                            notifications.map((notification) => {
                                const isExpanded = expandedId === notification.id;
                                
                                return (
                                <div
                                    key={notification.id}
                                    className={`px-4 py-3 border-b border-slate-100/50 dark:border-slate-700/30 transition-all duration-200 hover:bg-slate-100/60 dark:hover:bg-slate-800/60 cursor-pointer ${
                                        !notification.isRead
                                            ? 'bg-blue-50/40 dark:bg-blue-900/10 border-l-2 border-l-amber-400'
                                            : 'border-l-2 border-l-transparent opacity-75'
                                    } ${isExpanded ? 'bg-slate-50 dark:bg-slate-800/40' : ''}`}
                                    onClick={() => {
                                        if (isExpanded) {
                                            setExpandedId(null);
                                        } else {
                                            setExpandedId(notification.id);
                                            if (!notification.isRead) {
                                                handleMarkRead(notification.id);
                                            }
                                        }
                                    }}
                                >
                                    <div className="flex items-start justify-between gap-2">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className={`text-[10px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded flex-shrink-0 ${getPageColor(notification.page)} bg-current/10`}>
                                                    {notification.page}
                                                </span>
                                                <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">
                                                    Failed: {notification.failedStep}
                                                </span>
                                            </div>
                                            
                                            {!isExpanded && (
                                                <p className="text-[11px] text-slate-500 dark:text-slate-400 italic mt-1 line-clamp-1">
                                                    Tap to view details...
                                                </p>
                                            )}

                                            {isExpanded && (
                                                <div className="mt-3 space-y-2 animate-in slide-in-from-top-1 fade-in zoom-in-95 duration-200">
                                                    {/* User Details Box */}
                                                    <div className="bg-slate-100/80 dark:bg-slate-800/80 p-2.5 rounded-md border border-slate-200 dark:border-slate-700">
                                                        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">User Affected</p>
                                                        <p className="text-xs text-slate-700 dark:text-slate-300">
                                                            <span className="font-medium mr-2">{notification.username}</span>
                                                            <span className="opacity-75">({notification.userEmail || 'No Email'})</span>
                                                        </p>
                                                    </div>
                                                    
                                                    {/* Error Message Box */}
                                                    <div className="bg-red-50 dark:bg-red-900/10 p-2.5 rounded-md border border-red-100 dark:border-red-900/30">
                                                        <p className="text-[10px] font-bold text-red-600 dark:text-red-400 uppercase tracking-wider mb-1">Error Message</p>
                                                        <p className="text-[11px] text-red-700/90 dark:text-red-300/90 whitespace-pre-wrap leading-relaxed">
                                                            {notification.errorMessage}
                                                        </p>
                                                    </div>
                                                    
                                                    {/* Context Box removed per request */}
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex flex-col items-end gap-1 flex-shrink-0 min-w-fit">
                                            <span className="text-[10px] text-slate-400 dark:text-slate-500 whitespace-nowrap">
                                                {formatTimeAgo(notification.createdAt)}
                                            </span>
                                            <div className="flex items-center gap-1 mt-0.5">
                                                {confirmDeleteId === notification.id ? (
                                                    <div className="flex items-center gap-1 animate-in zoom-in-95 duration-200">
                                                        <button
                                                            type="button"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleDelete(notification.id);
                                                            }}
                                                            className="px-2 py-1 bg-red-500 hover:bg-red-600 dark:bg-red-600/90 dark:hover:bg-red-500 text-white text-[10px] font-medium rounded transition-colors flex items-center gap-1"
                                                            title="Confirm Delete"
                                                        >
                                                            <Check className="h-3 w-3" />
                                                            Yes
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setConfirmDeleteId(null);
                                                            }}
                                                            className="px-2 py-1 bg-slate-200 hover:bg-slate-300 dark:bg-slate-700 dark:hover:bg-slate-600 text-slate-700 dark:text-slate-300 text-[10px] font-medium rounded transition-colors flex items-center gap-1"
                                                            title="Cancel Delete"
                                                        >
                                                            <X className="h-3 w-3" />
                                                            No
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <>
                                                        {!notification.isRead && (
                                                            <button
                                                                type="button"
                                                                onClick={(e) => {
                                                                    e.stopPropagation();
                                                                    handleMarkRead(notification.id);
                                                                }}
                                                                className="p-1 rounded hover:bg-slate-200/80 dark:hover:bg-slate-600/50 transition-colors"
                                                                title="Mark as read"
                                                            >
                                                                <Check className="h-3.5 w-3.5 text-blue-500" />
                                                            </button>
                                                        )}
                                                        <button
                                                            type="button"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                setConfirmDeleteId(notification.id);
                                                            }}
                                                            className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 transition-colors group/delete"
                                                            title="Delete notification"
                                                        >
                                                            <Trash2 className="h-3.5 w-3.5 text-slate-400 group-hover/delete:text-red-500 transition-colors" />
                                                        </button>
                                                    </>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )})
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default NotificationBell;
