'use client'

import { useEffect, useRef, useState } from 'react'

interface MicButtonProps {
  /** Called with each final transcribed chunk of text. */
  onResult: (text: string) => void
  /** Pixel size of the button (square). Default 32. */
  size?: number
}

/**
 * Browser-native voice-to-text button using the Web Speech API.
 * Renders nothing in browsers without SpeechRecognition (e.g. Firefox) —
 * those users fall back to their OS/keyboard dictation.
 */
export default function MicButton({ onResult, size = 32 }: MicButtonProps) {
  const [supported, setSupported] = useState(false)
  const [listening, setListening] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null)
  const cbRef = useRef(onResult)
  cbRef.current = onResult

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = typeof window !== 'undefined'
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
      : null
    if (!SR) return
    setSupported(true)

    const rec = new SR()
    rec.continuous = true
    rec.interimResults = false
    rec.lang = 'en-US'
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      let text = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) text += e.results[i][0].transcript
      }
      if (text.trim()) cbRef.current(text.trim())
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recRef.current = rec

    return () => { try { rec.stop() } catch {} }
  }, [])

  if (!supported) return null

  const toggle = () => {
    const rec = recRef.current
    if (!rec) return
    if (listening) {
      try { rec.stop() } catch {}
      setListening(false)
    } else {
      try { rec.start(); setListening(true) } catch {}
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      title={listening ? 'Stop dictation' : 'Dictate with your voice'}
      aria-label={listening ? 'Stop dictation' : 'Dictate with your voice'}
      style={{
        height: size, flexShrink: 0, minWidth: size,
        width: listening ? 'auto' : size,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 4,
        borderRadius: 8, cursor: 'pointer',
        border: '1px solid', borderColor: listening ? '#ef4444' : '#e8e6e0',
        background: listening ? '#fef2f2' : '#fff',
        color: listening ? '#ef4444' : '#888',
        transition: 'all 0.15s', whiteSpace: 'nowrap', padding: listening ? '0 10px' : 0,
      }}
    >
      <svg width={size * 0.5} height={size * 0.5} viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="9" y="2" width="6" height="11" rx="3" />
        <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
        <line x1="12" y1="18" x2="12" y2="22" />
      </svg>
      {listening && <span style={{ fontSize: 11, fontWeight: 600 }}>Listening…</span>}
    </button>
  )
}
