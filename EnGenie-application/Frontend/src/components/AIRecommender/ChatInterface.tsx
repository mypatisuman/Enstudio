import { useRef, useEffect, useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Bot, User, CheckCircle, Loader2 } from "lucide-react";
import { ChatMessage } from "./types";
import { useToast } from "@/hooks/use-toast";
import ReactMarkdown from "react-markdown";
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import StreamingProgress from './StreamingProgress';

interface ChatInterfaceProps {
  messages: ChatMessage[];
  onSendMessage: (message: string) => void;
  isLoading: boolean;
  isStreaming: boolean;
  streamId?: string | null;
  inputValue: string;
  setInputValue: (value: string) => void;
  currentStep:
  | "greeting"
  | "initialInput"
  | "awaitMissingInfo"
  | "awaitAdditionalAndLatestSpecs"
  | "awaitAdvancedSpecs"
  | "awaitAllSpecs"
  | "confirmAfterMissingInfo"
  | "showSummary"
  | "finalConfirmation"
  | "finalAnalysis"
  | "analysisError"
  | "default";
  isValidationComplete: boolean;
  productType: string | null;
  collectedData: { [key: string]: string };
  vendorAnalysisComplete: boolean;
  onRetry: () => void;
  searchInstanceId?: string; // Optional instance ID for debugging
  bottomContent?: React.ReactNode;
  headerRightContent?: React.ReactNode;
  onCacheOpen?: (projectId: string) => void;
  onCachePreview?: (projectId: string) => void;
  onCacheIgnore?: () => void;
}

interface MessageRowProps {
  message: ChatMessage;
  isHistory: boolean;
  renderVendorAnalysisStatus: (message: ChatMessage) => React.ReactNode;
  formatTimestamp: (ts: Date | string | number | null | undefined) => string;
  onCacheOpen?: (projectId: string) => void;
  onCachePreview?: (projectId: string) => void;
  onCacheIgnore?: () => void;
}

const MessageRow = ({ message, isHistory, renderVendorAnalysisStatus, formatTimestamp, onCacheOpen, onCachePreview, onCacheIgnore }: MessageRowProps) => {
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
      const delay = message.type === "user" ? 200 : 0;
      const timer = setTimeout(() => {
        setIsVisible(true);
      }, delay);
      return () => clearTimeout(timer);
    } else {
      setIsVisible(true);
    }
  }, [effectiveIsHistory, message.type]);

  return (
    <div
      className={`flex ${message.type === "user" ? "justify-end" : "justify-start"
        }`}
    >
      <div
        className={`max-w-[80%] flex items-start space-x-2 ${message.type === "user" ? "flex-row-reverse space-x-reverse" : ""
          }`}
      >
        <div
          className={`flex-shrink-0 w-16 h-16 rounded-full flex items-center justify-center ${message.type === "user"
            ? "bg-transparent text-white -mt-3"
            : "bg-transparent"
            }`}
        >
          {message.type === "user" ? (
            <img
              src="/icon-user-3d.png"
              alt="User"
              className="w-16 h-16 object-contain"
            />
          ) : (
            <img src="/engenie icon.jpeg" alt="Assistant" className="w-20 h-20 object-contain rounded-full" />
          )}
        </div>
        <div className="flex-1">
          <div
            className={`break-words ${message.type === "user"
              ? "glass-bubble-user"
              : "glass-bubble-assistant"
              }`}
            style={{
              opacity: isVisible ? 1 : 0,
              transform: isVisible ? "scale(1)" : "scale(0.8)",
              transformOrigin: message.type === "user" ? "top right" : "top left",
              transition: "opacity 0.8s ease-out, transform 0.8s cubic-bezier(0.175, 0.885, 0.32, 1.275)"
            }}
          >
            <div>
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{message.content}</ReactMarkdown>
            </div>

            {/* Cache confirmation actions */}
            {message.metadata?.cacheConfirmation && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  onClick={() => onCacheOpen?.(message.metadata?.projectId || '')}
                  disabled={!message.metadata?.projectId}
                  className="bg-sky-600 hover:bg-sky-500 text-white font-semibold shadow-sm"
                  size="sm"
                >
                  Open
                </Button>
                <Button
                  onClick={() => onCachePreview?.(message.metadata?.projectId || '')}
                  disabled={!message.metadata?.projectId}
                  className="bg-white/10 hover:bg-white/20 text-sky-300 border border-white/15 font-semibold shadow-sm"
                  size="sm"
                >
                  Preview
                </Button>
                <Button
                  onClick={() => onCacheIgnore?.()}
                  variant="ghost"
                  className="text-zinc-400 hover:text-zinc-200 hover:bg-white/5"
                  size="sm"
                >
                  Ignore
                </Button>
              </div>
            )}

            {/* Router redirect button */}
            {message.metadata?.routerRedirect && message.metadata?.routerUrl && (
              <div className="mt-3">
                <a
                  href={message.metadata?.routerUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center rounded-md text-xs font-semibold px-3 py-1.5 bg-sky-500 hover:bg-sky-400 text-black transition-colors shadow-xs"
                >
                  Open {message.metadata.routerTargetPage ? message.metadata.routerTargetPage.charAt(0).toUpperCase() + message.metadata.routerTargetPage.slice(1) : 'Target'} Page ↗
                </a>
              </div>
            )}

            {renderVendorAnalysisStatus(message)}
          </div>
          <p
            className={`text-xs text-muted-foreground mt-1 px-1 ${message.type === "user" ? "text-right" : ""
              }`}
            style={{
              opacity: isVisible ? 1 : 0,
              transition: "opacity 0.8s ease 0.3s"
            }}
          >
            {formatTimestamp(message.timestamp)}
          </p>
        </div>
      </div>
    </div>
  );
};

const ChatInterface = ({
  messages,
  onSendMessage,
  isLoading,
  isStreaming,
  streamId,
  inputValue,
  setInputValue,
  currentStep,
  isValidationComplete,
  productType,
  collectedData,
  vendorAnalysisComplete,
  onRetry,
  searchInstanceId,
  bottomContent,
  headerRightContent,
  onCacheOpen,
  onCachePreview,
  onCacheIgnore,
}: ChatInterfaceProps) => {
  const { toast } = useToast();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isHistoryRef = useRef(true);

  // Set isHistory to false after initial mount so new messages animate
  useEffect(() => {
    // Small timeout to ensure first render completes before we switch mode
    const timer = setTimeout(() => {
      isHistoryRef.current = false;
    }, 1000);
    return () => clearTimeout(timer);
  }, []);

  const [activeDescription, setActiveDescription] = useState<string | null>(null);
  const [showThinking, setShowThinking] = useState(false);

  useEffect(() => {
    if (isLoading) {
      const timer = setTimeout(() => {
        setShowThinking(true);
      }, 600);
      return () => clearTimeout(timer);
    } else {
      setShowThinking(false);
    }
  }, [isLoading]);

  useEffect(() => {
    // Scroll within container only, not the entire page
    if (chatContainerRef.current && (isLoading || showThinking || messages.length > 0)) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages, isLoading, showThinking]);

  // Enforce textarea height when inputValue changes programmatically (e.g., from URL params)
  useEffect(() => {
    if (textareaRef.current) {
      const textarea = textareaRef.current;
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`;
    }
  }, [inputValue]);

  const prettifyRequirement = (req: string) =>
    req
      .replace(/_/g, " ")
      .replace(/-/g, " ")
      .replace(/\b\w/g, (l) => l.toUpperCase());

  const formatTimestamp = (ts: Date | string | number | null | undefined): string => {
    if (!ts) return "";
    // If already a Date
    if (ts instanceof Date) {
      try {
        return ts.toLocaleTimeString();
      } catch (e) {
        return ts.toString();
      }
    }

    // If numeric (epoch ms)
    if (typeof ts === "number") {
      const d = new Date(ts);
      return isNaN(d.getTime()) ? String(ts) : d.toLocaleTimeString();
    }

    // If ISO/string, try to parse
    if (typeof ts === "string") {
      const parsed = Date.parse(ts);
      if (!isNaN(parsed)) {
        return new Date(parsed).toLocaleTimeString();
      }

      // If string isn't parseable, return as-is (fallback)
      return ts;
    }

    // Unknown type: fallback to string
    try {
      return String(ts);
    } catch (e) {
      return "";
    }
  };

  const handleSend = () => {
    const trimmedInput = inputValue.trim();
    if (!trimmedInput) {
      toast({
        title: "Input required",
        description: "Please enter your data before sending.",
        variant: "destructive",
      });
      return;
    }
    if (isLoading) return;

    // Reset textarea height to initial height before sending
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    onSendMessage(trimmedInput);
    setInputValue("");
    setActiveDescription(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };



  const handleSampleClick = (sampleText: string) => {
    setInputValue(sampleText);
    textareaRef.current?.focus();
    setActiveDescription(null);
  };

  const handleInteractiveButtonClick = (label: string) => {
    setActiveDescription((current) => (current === label ? null : label));
  };

  const renderVendorAnalysisStatus = (message: ChatMessage) => {
    if (message.metadata?.vendorAnalysisComplete) {
      return (
        <div className="mt-3 p-4 rounded-lg bg-ai-primary/5 border border-ai-primary/20 space-y-2 shadow-inner">
          <h4 className="font-semibold text-ai-primary mb-1 flex items-center">
            <CheckCircle className="h-4 w-4 mr-2" /> Vendor Analysis Complete
          </h4>
          <p className="text-sm text-muted-foreground">
            Detailed results are displayed in the right panel.
          </p>
        </div>
      );
    }
    return null;
  };

  const getPlaceholderText = () => {
    if (isLoading) {
      return "Thinking...";
    }
    switch (currentStep) {
      case "initialInput":
        return "";
      case "awaitMissingInfo":
        return "";
      case "awaitAdditionalAndLatestSpecs":
        return "";
      case "awaitAdvancedSpecs":
        return "";
      case "awaitAllSpecs":
        return "Edit specs in chat (e.g. set accuracy to 3mm) or type proceed to search...";
      case "showSummary":
      case "analysisError":
        return "";
      case "finalAnalysis":
        return "";
      default:
        return "Send a message...";
    }
  };

  const sampleInputs = [
    {
      label: "Pressure Transmitter",
      text: "I am looking for a very specific pressure transmitter. The required performance includes a tight pressure range of -10 to 10 inH2O and a high standard accuracy of 0.035% of span. For system integration, the device must provide a 4-20mA with HART output signal. In terms of materials, the process-wetted parts must be compatible with Hastelloy C-276, and it should feature a 1/4-18 NPT process connection.",
    },
    {
      label: "Temperature Transmitter",
      text: "We are looking for a high-performance temperature transmitter suitable for a critical process monitoring application. The unit must be compatible with a Pt100 RTD sensor and provide a high degree of accuracy, specifically ±0.10 °C. For integration with our current system, it needs to have a 4-20 mA output signal with HART protocol. The physical installation requires a rugged stainless steel housing and the ability to be pipe-mounted. Most importantly, the transmitter must meet our stringent safety standards, which requires both a SIL 3 certification and an ATEX rating for use in potentially hazardous areas.",
    },
    {
      label: "Humidity Transmitter",
      text: "I am looking for a humidity transmitter with a 0-10V output. The measurement range should be 0-100% RH and it needs to be wall-mountable.",
    },
  ];

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent relative">
      {/* Decorative background images */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-[0] flex items-center justify-center">
          <img src="/engenie logo.jpeg" alt="" className="w-80 h-80 md:w-[32rem] md:h-[32rem] object-contain opacity-[0.04] select-none translate-y-2 md:translate-y-4" />
      </div>

      {/* SECOND HEADER - Content header */}
      <div className="flex-none py-0 border-b border-white/10 bg-transparent z-20 relative flex items-center justify-center p-2 min-h-[64px]">
        <div className="flex items-center gap-0">
          <div className="flex items-center justify-center">
            <img src="/engenie logo.jpeg" alt="Logo" className="w-14 h-14 md:w-24 md:h-24 object-contain" />
          </div>
          <h1 className="text-xl md:text-3xl font-bold text-white inline-flex items-center gap-2 whitespace-nowrap -ml-4 md:-ml-6">
            Search & Recommender
          </h1>
        </div>

        {/* Render headerRightContent (e.g., standard toggle) */}
        {headerRightContent && (
          <div className="absolute right-2 md:right-4 flex items-center [&_label]:hidden [&_label]:md:inline">
            {headerRightContent}
          </div>
        )}
      </div>
      {/* Chat Messages Area - Scrolls behind the input */}
      <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-4 space-y-4 custom-no-scrollbar pb-24">
        {messages.length === 0 ? (
          <div className="text-center p-6">
            {/* Empty state */}
          </div>
        ) : (
          messages.map((message) => (
            <MessageRow
              key={message.id}
              message={message}
              isHistory={isHistoryRef.current}
              renderVendorAnalysisStatus={renderVendorAnalysisStatus}
              formatTimestamp={formatTimestamp}
              onCacheOpen={onCacheOpen}
              onCachePreview={onCachePreview}
              onCacheIgnore={onCacheIgnore}
            />
          ))
        )}

        {showThinking && !isStreaming && streamId && (
          <StreamingProgress
            streamId={streamId}
            onComplete={() => {
              console.log('[STREAMING] Complete callback triggered');
            }}
            onError={(error) => {
              console.error('[STREAMING] Error callback triggered:', error);
            }}
          />
        )}

        <div ref={messagesEndRef} />
      </div>

      {activeDescription && (
        <div
          className="p-4 bg-secondary/30 rounded border border-border text-sm text-muted-foreground max-w-2xl mx-auto mb-4 cursor-pointer hover:bg-secondary/50 transition"
          onClick={() =>
            handleSampleClick(
              sampleInputs.find(({ label }) => label === activeDescription)
                ?.text || ""
            )
          }
        >
          <p>
            {sampleInputs.find(({ label }) => label === activeDescription)?.text}
          </p>
        </div>
      )}


      <div className="fixed bottom-0 left-0 right-0 p-4 bg-transparent z-30 pointer-events-none">
        <div className="max-w-4xl mx-auto px-2 md:px-8 pointer-events-auto">
          <form onSubmit={(e) => { e.preventDefault(); handleSend(); }}>
            <div className="relative group">
              <div className="chat-input-wrapper relative w-full rounded-2xl flex items-end transition-all duration-300 bg-[#212121] border border-white/10 hover:border-white/20 focus-within:border-white/30 shadow-2xl p-2"
                style={{
                  WebkitBackdropFilter: 'blur(12px)',
                  backdropFilter: 'blur(12px)',
                  color: '#f4f4f5'
                }}>
                <textarea
                  ref={textareaRef}
                  placeholder="Type your message here..."
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
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
          {bottomContent && (
            <div className="pointer-events-auto">
              {bottomContent}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ChatInterface;
