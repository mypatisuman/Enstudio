import { useState, useRef, useCallback, useEffect } from 'react'

// Minimal ambient types for the Web Speech API's SpeechRecognition — not
// guaranteed present in TS's DOM lib across versions, so declared locally
// rather than assumed. Only the members this hook actually uses.
interface SpeechRecognitionAlt { transcript: string }
interface SpeechRecognitionResultLike { isFinal: boolean; length: number; [index: number]: SpeechRecognitionAlt }
interface SpeechRecognitionResultListLike { length: number; [index: number]: SpeechRecognitionResultLike }
interface SpeechRecognitionEventLike extends Event { results: SpeechRecognitionResultListLike }
interface SpeechRecognitionLike extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  start(): void
  stop(): void
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike

const SILENCE_TIMEOUT_MS = 5000

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
}

/**
 * Browser dictation for the Describe composer. Feature-detected — WebView2
 * (this app's desktop runtime) has historically not implemented
 * SpeechRecognition, unlike Chrome, so `supported` reflects the ACTUAL
 * runtime rather than assuming Chromium parity. When unsupported, callers
 * should simply not render a mic button rather than show one that fails.
 */
export function useVoiceInput(onTranscript: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const [supported] = useState(
    () => typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition),
  )
  const recRef = useRef<SpeechRecognitionLike | null>(null)
  const baseTextRef = useRef('')
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
  }, [])

  const stop = useCallback(() => {
    clearSilenceTimer()
    recRef.current?.stop()
  }, [clearSilenceTimer])

  // Auto-stop after 5s with no new speech — restarted on every result event,
  // so the mic only closes once the user actually goes quiet, not on a fixed
  // total duration.
  const armSilenceTimer = useCallback(() => {
    clearSilenceTimer()
    silenceTimerRef.current = setTimeout(() => { recRef.current?.stop() }, SILENCE_TIMEOUT_MS)
  }, [clearSilenceTimer])

  const start = useCallback((currentText: string) => {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition
    if (!Ctor) return
    const rec = new Ctor()
    rec.lang = 'en-US'
    rec.continuous = true
    rec.interimResults = true
    baseTextRef.current = currentText.trim() ? currentText.trimEnd() + ' ' : ''

    rec.onresult = ev => {
      let transcript = ''
      for (let i = 0; i < ev.results.length; i++) transcript += ev.results[i][0].transcript
      onTranscript(baseTextRef.current + transcript)
      armSilenceTimer()
    }
    rec.onerror = () => { clearSilenceTimer(); setListening(false) }
    rec.onend = () => { clearSilenceTimer(); setListening(false) }

    recRef.current = rec
    rec.start()
    armSilenceTimer()
    setListening(true)
  }, [onTranscript, armSilenceTimer, clearSilenceTimer])

  // Stop any live mic on unmount so it doesn't keep listening after the
  // composer disappears (e.g. project switch).
  useEffect(() => () => { clearSilenceTimer(); recRef.current?.stop() }, [clearSilenceTimer])

  return { supported, listening, start, stop }
}
