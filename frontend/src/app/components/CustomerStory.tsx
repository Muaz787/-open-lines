/* Evidence slot — a real customer story. Renders ONLY when a story is supplied,
   so pages stay honest until real, approved customer content exists. Populate
   the optional `customerStory` field on the page's content object to enable. */
export interface Story {
  quote: string
  name: string
  business: string
  location?: string
  /** Optional real metric, e.g. "Recovered 18 after-hours bookings in month one" */
  result?: string
}

export default function CustomerStory({ story }: { story?: Story }) {
  if (!story) return null
  return (
    <div style={{ background: 'var(--bg-2)', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
      <section className="sec">
        <div className="wrap" style={{ maxWidth: 760 }}>
          <div className="sec-label">Customer story</div>
          <blockquote style={{ margin: 0 }}>
            <p style={{ fontFamily: 'var(--font-syne), sans-serif', fontSize: 'clamp(20px, 3vw, 26px)', fontWeight: 600, lineHeight: 1.4, letterSpacing: '-0.01em', margin: '8px 0 20px' }}>
              “{story.quote}”
            </p>
            <footer style={{ fontSize: 14, color: 'var(--text-2)', fontWeight: 300 }}>
              <span style={{ fontWeight: 600, color: 'var(--text)' }}>{story.name}</span>
              {' · '}{story.business}{story.location ? ` · ${story.location}` : ''}
            </footer>
          </blockquote>
          {story.result && (
            <div style={{ marginTop: 18, display: 'inline-block', background: 'var(--accent-dim)', color: 'var(--accent-text)', fontSize: 14, fontWeight: 600, borderRadius: 999, padding: '8px 16px' }}>
              {story.result}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
