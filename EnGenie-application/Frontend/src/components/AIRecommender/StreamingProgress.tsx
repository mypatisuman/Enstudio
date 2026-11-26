import React, { useEffect, useState, useRef } from 'react';
import { streamJobEvents } from './wsClient';

interface StreamingProgressProps {
  streamId: string | null;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

interface ProgressStep {
  step: string;
  message: string;
  progress: number;
}

const StreamingProgress: React.FC<StreamingProgressProps> = ({
  streamId,
  onComplete,
  onError
}) => {
  const [currentStep, setCurrentStep] = useState<ProgressStep | null>(null);
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [dotCount, setDotCount] = useState(1);
  const typingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Hold the latest callbacks in refs so the stream effect can depend on
  // streamId ALONE. The parents pass inline onComplete/onError (new identity
  // each render); including them in the effect deps would tear down and reopen
  // the WebSocket on every re-render (reconnection storm).
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  onCompleteRef.current = onComplete;
  onErrorRef.current = onError;

  // Character-by-character typing effect with looping and synchronized dots
  const typeText = (text: string, loop: boolean = true) => {
    setIsTyping(true);
    setDisplayedText('');
    setDotCount(0);

    let currentIndex = 0;
    let sequenceState = 'text'; // 'text' | 'dots' | 'pause'
    let currentDots = 0;
    let pauseCounter = 0;

    if (typingIntervalRef.current) {
      clearInterval(typingIntervalRef.current);
    }

    typingIntervalRef.current = setInterval(() => {
      if (pauseCounter > 0) {
        pauseCounter--;
        if (pauseCounter === 0 && sequenceState === 'pause') {
          if (loop) {
            currentIndex = 0;
            currentDots = 0;
            setDotCount(0);
            setDisplayedText('');
            sequenceState = 'text';
          } else {
            if (typingIntervalRef.current) {
              clearInterval(typingIntervalRef.current);
              typingIntervalRef.current = null;
            }
            setIsTyping(false);
          }
        }
        return;
      }

      if (sequenceState === 'text') {
        if (currentIndex < text.length) {
          currentIndex++;
          setDisplayedText(text.substring(0, currentIndex));
        } else {
          sequenceState = 'dots';
          pauseCounter = 0;
        }
      } else if (sequenceState === 'dots') {
        if (currentDots < 3) {
          currentDots++;
          setDotCount(currentDots);
          pauseCounter = 6; // 300ms between dots
        } else {
          sequenceState = 'pause';
          pauseCounter = 1;
        }
      }
    }, 50);
  };

  useEffect(() => {
    if (!streamId) return;

    if (streamId === 'local') {
      console.log('[STREAMING] Starting local synthetic animation');
      typeText('Analyzing', true);
      return () => {
        if (typingIntervalRef.current) clearInterval(typingIntervalRef.current);
      };
    }

    console.log('[STREAMING] Starting SSE stream for:', streamId);

    typeText('Analyzing', true);

    const controller = new AbortController();

    const processEvent = (eventType: string, data: any) => {
      if (eventType === 'start') {
        console.log('[STREAMING] Workflow started:', data);
        setCurrentStep({ step: 'start', message: data.message || 'Starting analysis...', progress: data.progress || 0 });
        typeText(data.message || 'Starting analysis...', true);
      } else if (eventType === 'step') {
        console.log('[STREAMING] Step update:', data);
        setCurrentStep({ step: data.step || 'processing', message: data.message || 'Processing...', progress: data.progress || 0 });
        typeText(data.message || 'Processing...', true);
      } else if (eventType === 'sub_step') {
        if (data.message) typeText(data.message, true);
      } else if (eventType === 'error') {
        const errorMessage = data.error || 'An error occurred during processing';
        console.error('[STREAMING] Error event from server:', data);
        setCurrentStep({ step: 'error', message: errorMessage, progress: 0 });
        typeText(errorMessage, false);
        controller.abort();
        onErrorRef.current?.(errorMessage);
      }
      // 'result', 'preview', 'close' events are handled by api.ts waitForSSEResult
    };

    // Push-based: events arrive over SSE the instant the server emits them.
    // The typing animation runs in parallel.
    streamJobEvents(streamId, {
      signal: controller.signal,
      onEvent: (type, data) => processEvent(type, data || {}),
    }).catch((err: any) => {
      if (err?.name !== 'AbortError') {
        console.warn('[STREAMING] Stream ended:', err?.message);
      }
    });

    return () => {
      console.log('[STREAMING] Cleaning up SSE stream');
      controller.abort();
      if (typingIntervalRef.current) clearInterval(typingIntervalRef.current);
    };
  }, [streamId]);

  const dots = '.'.repeat(dotCount);

  return (
    <div className="flex justify-start w-full mb-4 mt-2">
      <div className="max-w-[80%] flex items-center space-x-1">
        <div className="flex-shrink-0 flex items-center justify-center bg-transparent">
          <img src="/engenie icon.jpeg" alt="Assistant" className="w-20 h-20 object-contain rounded-full" />
        </div>
        <div className="flex items-center">
          <span className="text-base font-semibold text-[#0a1638] dark:text-blue-100 break-words pt-1">
            {displayedText}
            {isTyping && (
              <span className="inline-block w-8 text-left ml-0.5">{dots}</span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
};

export default StreamingProgress;
