'use client'

import { useState } from 'react'
import { trackEvent } from '@/lib/analytics'

/* "Don't take our word for it — ask an AI." A row of buttons that open
   ChatGPT / Claude / Perplexity pre-loaded with a research prompt about
   Open Lines, plus a copy-prompt fallback for any other assistant. */

const PROMPT =
  "I'm checking out Open Lines (openlines.ai), an AI phone receptionist for small businesses. " +
  "Based on their website, help me understand what it does, how it would handle my calls, and how " +
  "easy it is to get started. Ask me about my business if that helps you give a straight answer."

const Q = encodeURIComponent(PROMPT)

const TOOLS: { id: string; name: string; href: string; dot: string }[] = [
  { id: 'chatgpt',    name: 'ChatGPT',    href: `https://chatgpt.com/?q=${Q}`,               dot: '#10A37F' },
  { id: 'claude',     name: 'Claude',     href: `https://claude.ai/new?q=${Q}`,              dot: '#D97757' },
  { id: 'perplexity', name: 'Perplexity', href: `https://www.perplexity.ai/search?q=${Q}`,   dot: '#20808D' },
]

export default function AskAiSection() {
  const [copied, setCopied] = useState(false)

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(PROMPT)
    } catch {
      // Fallback for older/blocked clipboard: a hidden textarea + execCommand.
      const ta = document.createElement('textarea')
      ta.value = PROMPT
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch { /* no-op */ }
      document.body.removeChild(ta)
    }
    trackEvent('ask_ai_prompt_copied', { location: 'landing' })
    setCopied(true)
    setTimeout(() => setCopied(false), 2200)
  }

  return (
    <section className="sec" style={{ textAlign: 'center' }}>
      <div className="wrap">
        <div className="sec-label">See for yourself</div>
        <h2 style={{ fontFamily: 'var(--font-syne), sans-serif', maxWidth: 620, margin: '0 auto 12px' }}>
          Don&rsquo;t take our word for it — ask an AI.
        </h2>
        <p className="sec-sub" style={{ maxWidth: 520, margin: '0 auto 30px' }}>
          Have ChatGPT, Claude, or Perplexity look at openlines.ai and tell you, in plain terms, what it
          does, how it would handle your calls, and how to get started.
        </p>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
          {TOOLS.map(t => (
            <a
              key={t.id}
              href={t.href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackEvent('ask_ai_clicked', { tool: t.id, location: 'landing' })}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 10,
                background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 999,
                padding: '12px 20px', fontSize: 15, fontWeight: 500, color: 'var(--text)',
                textDecoration: 'none',
              }}
            >
              <span aria-hidden style={{ width: 9, height: 9, borderRadius: '50%', background: t.dot, flexShrink: 0 }} />
              Ask {t.name}
              <span aria-hidden style={{ color: 'var(--text-3)' }}>↗</span>
            </a>
          ))}

          <button
            type="button"
            onClick={copyPrompt}
            aria-live="polite"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              background: 'transparent', border: '1px solid var(--border-2)', borderRadius: 999,
              padding: '12px 20px', fontSize: 15, fontWeight: 500,
              color: copied ? 'var(--accent-text)' : 'var(--text-2)', cursor: 'pointer',
            }}
          >
            {copied ? '✓ Copied' : 'Copy the prompt'}
          </button>
        </div>

        <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 16 }}>
          Works with any assistant — copy the prompt into Gemini, Grok, or Copilot too.
        </p>
      </div>
    </section>
  )
}
