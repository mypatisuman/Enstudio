import { useEffect, type RefObject } from 'react';
import type { ChatEntry } from '../types';

/**
 * Auto-scrolls the message container to the bottom whenever messages change or loading state toggles.
 */
export function useAutoScroll(
  bottomRef: RefObject<HTMLDivElement | null>,
  chat: ChatEntry[],
  loading: boolean
) {
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chat, loading, bottomRef]);
}
