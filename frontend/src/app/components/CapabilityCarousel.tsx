'use client'

import { useRef, useState, useEffect, useCallback } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

const CARDS: { title: string; body: string }[] = [
  { title: 'Answer every call, 24/7',        body: 'Never send a customer to voicemail again — day, night, weekends and holidays.' },
  { title: 'Book, reschedule & cancel',      body: 'Straight into your own calendar — Google, Outlook, or Square Appointments.' },
  { title: 'Collect deposits on the call',   body: 'A secure Stripe or Square payment link, texted to the caller instantly.' },
  { title: 'Recognize returning callers',    body: 'Greets them by name and picks up right where they left off.' },
  { title: 'Answer from your knowledge base',body: 'Hours, services, pricing and policies — in your own words.' },
  { title: 'Book with a specific person',    body: '“I’d like to see Sam” just works — matched to your team roster.' },
  { title: 'Confirmations & owner alerts',   body: 'Text confirmations to callers, plus SMS or WhatsApp alerts to you.' },
  { title: 'Capture & qualify every lead',   body: 'Full transcript, AI summary and insights waiting in your dashboard.' },
]

export default function CapabilityCarousel() {
  const trackRef = useRef<HTMLDivElement>(null)
  const reduce   = useReducedMotion()
  const [canPrev, setCanPrev] = useState(false)
  const [canNext, setCanNext] = useState(true)
  const [dots, setDots]       = useState(1)
  const [active, setActive]   = useState(0)

  const update = useCallback(() => {
    const el = trackRef.current
    if (!el) return
    const { scrollLeft, scrollWidth, clientWidth } = el
    setCanPrev(scrollLeft > 8)
    setCanNext(scrollLeft < scrollWidth - clientWidth - 8)
    const pages = Math.max(1, Math.ceil(scrollWidth / clientWidth))
    setDots(pages)
    setActive(Math.round(scrollLeft / clientWidth))
  }, [])

  useEffect(() => {
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [update])

  const scrollBy = (dir: 1 | -1) => {
    const el = trackRef.current
    if (!el) return
    const card = el.querySelector<HTMLElement>('.cap-card')
    const step = card ? card.offsetWidth + 16 : el.clientWidth * 0.8
    el.scrollBy({ left: dir * step, behavior: reduce ? 'auto' : 'smooth' })
  }

  const toPage = (i: number) => {
    const el = trackRef.current
    if (!el) return
    el.scrollTo({ left: i * el.clientWidth, behavior: reduce ? 'auto' : 'smooth' })
  }

  return (
    <section className="cap-section">
      <div className="wrap">
        <motion.div
          className="cap-head"
          initial={reduce ? undefined : { opacity: 0, y: 18 }}
          whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        >
          <div>
            <div className="sec-label" style={{ marginBottom: 16 }}>Capabilities</div>
            <h2 className="cap-title" style={{ fontFamily: 'var(--font-syne), sans-serif' }}>
              What can your OpenLines<br />receptionist do on every call?
            </h2>
          </div>
          <div className="cap-nav">
            <button className="cap-arrow" aria-label="Previous" onClick={() => scrollBy(-1)} disabled={!canPrev}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
            </button>
            <button className="cap-arrow" aria-label="Next" onClick={() => scrollBy(1)} disabled={!canNext}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
        </motion.div>

        <div
          className="cap-track"
          ref={trackRef}
          onScroll={update}
          role="region"
          aria-label="What OpenLines can do"
          tabIndex={0}
        >
          {CARDS.map((c, i) => (
            <motion.div
              className="cap-card"
              key={c.title}
              initial={reduce ? undefined : { opacity: 0, y: 20 }}
              whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-40px' }}
              transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1], delay: Math.min(i, 4) * 0.06 }}
            >
              <div className="cap-num">{String(i + 1).padStart(2, '0')}</div>
              <div className="cap-card-title">{c.title}</div>
              <p className="cap-card-body">{c.body}</p>
            </motion.div>
          ))}
        </div>

        {dots > 1 && (
          <div className="cap-dots" role="tablist" aria-label="Carousel pages">
            {Array.from({ length: dots }).map((_, i) => (
              <button
                key={i}
                className={`cap-dot${i === active ? ' active' : ''}`}
                aria-label={`Go to page ${i + 1}`}
                aria-selected={i === active}
                role="tab"
                onClick={() => toPage(i)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
