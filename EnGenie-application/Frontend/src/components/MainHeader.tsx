import { useState, useRef, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useNavigate, useLocation, NavLink } from 'react-router-dom';
import { Lightbulb, Search, MessageSquare, Settings2, Workflow, ExternalLink } from 'lucide-react';
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";

interface MainHeaderProps {
    /** Optional: Additional content to render between the logo and profile section */
    children?: React.ReactNode;
    /** Optional: Show project action buttons (Save, New, Open) - preserved for interface compatibility */
    showProjectActions?: boolean;
    /** Optional: Project action button handlers - preserved for interface compatibility */
    onSave?: () => void;
    onNew?: () => void;
    onDownloadWorkflow?: () => void;
    onProjectSelect?: (project: any) => void;
    onProjectDelete?: (projectId: string) => void;
    /** Optional: Custom class name for the header */
    className?: string;
    /** Optional: Custom content to render on the right side */
    rightContent?: React.ReactNode;
}

// Navigation routes configuration
const NAV_ROUTES = [
    { path: '/chat', label: 'Describe Copilot', icon: MessageSquare },
    { path: '/solution', label: 'Solution', icon: Lightbulb },
    { path: '/pid-studio', label: 'P&ID Studio', icon: Workflow },
    { path: '/search', label: 'Search', icon: Search },
    { path: '/configure', label: 'Configure', icon: Settings2 },
];

const MainHeader = ({
    children,
    className = "",
    rightContent
}: MainHeaderProps) => {
    const navigate = useNavigate();
    const location = useLocation();
    const [isNavPopupOpen, setIsNavPopupOpen] = useState(false);

    const navPopupRef = useRef<HTMLDivElement>(null);
    const videoContainerRef = useRef<HTMLDivElement>(null);

    // Close popup when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                navPopupRef.current &&
                !navPopupRef.current.contains(event.target as Node) &&
                videoContainerRef.current &&
                !videoContainerRef.current.contains(event.target as Node)
            ) {
                setIsNavPopupOpen(false);
            }
        };

        if (isNavPopupOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isNavPopupOpen]);

    // Get current route category to filter navigation options
    const getCurrentRouteCategory = () => {
        const path = location.pathname;
        if (path.startsWith('/describe') || path.startsWith('/chat')) return '/chat';
        if (path.startsWith('/pid-studio')) return '/pid-studio';
        if (path.startsWith('/solution')) return '/solution';
        if (path.startsWith('/search')) return '/search';
        if (path.startsWith('/configure')) return '/configure';
        return '/chat';
    };

    // Get available navigation routes (exclude current page)
    const getAvailableRoutes = () => {
        const currentCategory = getCurrentRouteCategory();
        return NAV_ROUTES.filter(route => route.path !== currentCategory);
    };

    // Handle navigation button click - opens in new window with fresh state
    const handleNavigation = (path: string) => {
        // Add fresh=true to signal the target page to start with clean state
        const separator = path.includes('?') ? '&' : '?';
        const fullUrl = `${window.location.origin}${path}${separator}fresh=true`;
        // Use unique window name so a new window is always created
        const windowName = `engenie_${path.replace(/\//g, '_')}_${Date.now()}`;
        window.open(fullUrl, windowName, 'noopener');
        setIsNavPopupOpen(false);
    };

    return (
        <>
            <header
                className={`glass-header px-6 py-4 fixed w-full z-50 ${className}`}
                style={{ top: 'var(--banner-height, 0px)', transition: 'top 0.2s ease' }}
            >
                <div className="flex items-center justify-between">
                    {/* Left side - Logo and optional children (tabs, etc.) */}
                    <div className="flex items-center gap-4">
                        <div className="relative">
                            {/* Clickable Video Container */}
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <div
                                        ref={videoContainerRef}
                                        onClick={() => setIsNavPopupOpen(!isNavPopupOpen)}
                                        className="w-16 h-16 rounded-full overflow-hidden shadow-lg border-2 border-white/20 bg-[#171717] cursor-pointer transition-transform hover:scale-105 hover:border-sky-400/70"
                                    >
                                        <img
                                            src="/engenie logo.jpeg"
                                            alt="Logo"
                                            className="w-full h-full object-cover pointer-events-none"
                                        />
                                    </div>
                                </TooltipTrigger>
                                <TooltipContent><p>Navigate</p></TooltipContent>
                            </Tooltip>

                            {/* Navigation Popup */}
                            <AnimatePresence>
                                {isNavPopupOpen && (
                                    <motion.div
                                        ref={navPopupRef}
                                        initial={{ opacity: 0, y: -10, scale: 0.94 }}
                                        animate={{ opacity: 1, y: 0, scale: 1 }}
                                        exit={{ opacity: 0, y: -8, scale: 0.95 }}
                                        transition={{ type: 'spring', stiffness: 420, damping: 28 }}
                                        className="absolute top-full left-0 mt-2 z-50 flex flex-col gap-1.5 p-2 rounded-xl bg-[#171717]/95 backdrop-blur-xl border border-white/10 shadow-2xl min-w-[210px]"
                                    >
                                        {getAvailableRoutes().map((route, i) => {
                                            const IconComponent = route.icon;
                                            return (
                                                <motion.div
                                                    key={route.path}
                                                    initial={{ opacity: 0, x: -8 }}
                                                    animate={{ opacity: 1, x: 0 }}
                                                    transition={{ delay: i * 0.06, type: 'spring', stiffness: 400, damping: 28 }}
                                                    className="flex items-center gap-1 group"
                                                >
                                                    <NavLink
                                                        to={route.path}
                                                        onClick={() => setIsNavPopupOpen(false)}
                                                        className="flex-1 flex items-center gap-2.5 px-3 py-2 rounded-lg bg-[#212121] hover:bg-[#2a2a2a] text-zinc-200 hover:text-white hover:border-sky-500/40 border border-white/10 shadow-xs text-xs font-medium transition-all"
                                                    >
                                                        <IconComponent className="h-4 w-4 text-sky-400 flex-shrink-0" />
                                                        <span className="truncate">{route.label}</span>
                                                    </NavLink>
                                                    <a
                                                        href={route.path}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setIsNavPopupOpen(false);
                                                        }}
                                                        title={`Open ${route.label} in new tab`}
                                                        className="p-2 rounded-lg bg-[#212121] hover:bg-[#2a2a2a] text-zinc-400 hover:text-white border border-white/10 opacity-70 hover:opacity-100 transition-all flex items-center justify-center flex-shrink-0"
                                                    >
                                                        <ExternalLink className="h-3.5 w-3.5" />
                                                    </a>
                                                </motion.div>
                                            );
                                        })}
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </div>

                        {/* Optional children slot - can be used for tabs, navigation, etc. */}
                        {children}
                    </div>

                    {/* Right side - Action Buttons and Profile */}
                    <div className="flex items-center gap-2">
                        {rightContent}
                    </div>
                </div>
            </header>
        </>
    );
};

export default MainHeader;
