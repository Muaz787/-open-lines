/* Shared renderer for per-page Open Graph cards (next/og / Satori).
   Keeps the brand look — navy background, Open Lines mark — while carrying
   each page's own eyebrow + title + benefit line. Used by the per-segment
   opengraph-image.tsx routes for verticals, integrations, and guides. */
import type { ReactElement } from 'react'

export const ogSize = { width: 1200, height: 630 }
export const ogContentType = 'image/png'

const SITE_URL = 'https://www.openlines.ai'

/** Absolute URL for a page-specific, branded OG card served by /og. */
export function ogImageUrl({ eyebrow, title, benefit }: { eyebrow: string; title: string; benefit: string }): string {
  const q = new URLSearchParams({ eyebrow, title, benefit })
  return `${SITE_URL}/og?${q.toString()}`
}

const NAVY = '#001F3F'
const NAVY2 = '#00305f'
const LIGHT = '#DDE8F2'
const ACCENT = '#5AA7FF'

// The Open Lines mark, drawn to match icon.svg (Satori supports basic SVG shapes).
function Mark({ size = 96 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <path d="M 15.9,3.2 A 11,11 0 0,1 15.9,24.8" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M 12.1,24.8 A 11,11 0 0,1 12.1,3.2" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
      <line x1="10.5" y1="12.5" x2="10.5" y2="16.5" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
      <line x1="14" y1="9.5" x2="14" y2="18.5" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
      <line x1="17.5" y1="11.5" x2="17.5" y2="17" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  )
}

export function ogCard({ eyebrow, title, benefit }: { eyebrow: string; title: string; benefit: string }): ReactElement {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '72px 80px',
        background: `linear-gradient(135deg, ${NAVY} 0%, ${NAVY2} 100%)`,
        color: '#fff',
        fontFamily: 'sans-serif',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
        <Mark size={64} />
        <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: '-0.01em' }}>openlines.ai</div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: ACCENT, marginBottom: 22 }}>
          {eyebrow}
        </div>
        <div style={{ fontSize: 62, fontWeight: 800, lineHeight: 1.07, letterSpacing: '-0.02em', maxWidth: 1040 }}>
          {title}
        </div>
      </div>

      <div style={{ fontSize: 30, fontWeight: 400, color: LIGHT, maxWidth: 1000 }}>{benefit}</div>
    </div>
  )
}
