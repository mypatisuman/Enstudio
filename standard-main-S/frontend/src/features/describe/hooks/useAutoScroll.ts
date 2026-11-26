import { useEffect } from 'react'
import type { RefObject } from 'react'
import type { ChatEntry } from '../types'

// Auto-scroll to bottom after each message.
export function useAutoScroll(bottomRef: RefObject<HTMLDivElement | null>, chat: ChatEntry[], loading: boolean) {
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat, loading, bottomRef])
}
