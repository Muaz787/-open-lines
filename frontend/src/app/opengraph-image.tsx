import { ImageResponse } from 'next/og'

// Site-wide Open Graph / social share image. Inherited by every route unless a
// segment defines its own. Rendered with next/og at build time (static).
export const alt = 'Open Lines AI — AI voice receptionist that answers calls 24/7'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '96px',
          background: 'linear-gradient(135deg, #001F3F 0%, #00305f 100%)',
          color: '#ffffff',
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 40 }}>
          <div style={{ width: 22, height: 22, borderRadius: 999, background: '#34C759' }} />
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: '0.14em', color: '#9AAABB' }}>
            OPEN LINES AI
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            fontSize: 84,
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: '-0.02em',
          }}
        >
          <span>The line is</span>
          <span style={{ color: '#34C759' }}>always open.</span>
        </div>
        <div style={{ marginTop: 40, fontSize: 34, fontWeight: 400, color: '#DDE8F2', maxWidth: 900 }}>
          AI voice receptionist that answers calls, captures leads, and books
          appointments 24/7.
        </div>
      </div>
    ),
    { ...size },
  )
}
