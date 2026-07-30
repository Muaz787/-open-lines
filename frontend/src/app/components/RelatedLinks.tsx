import Link from 'next/link'

/* Contextual internal-linking module. Use descriptive anchors (label), not
   "learn more". Renders nothing if given no links. */
export default function RelatedLinks({
  heading,
  links,
}: { heading: string; links: { href: string; label: string; sub?: string }[] }) {
  if (!links?.length) return null
  return (
    <section className="sec" style={{ paddingTop: 56, paddingBottom: 56 }}>
      <div className="wrap">
        <div className="sec-label">{heading}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 14, marginTop: 8 }}>
          {links.map(l => (
            <Link
              key={l.href + l.label}
              href={l.href}
              style={{ display: 'block', background: 'var(--bg-2)', border: '1px solid var(--border-2)', borderRadius: 14, padding: '16px 18px', color: 'inherit' }}
            >
              <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{l.label}</div>
              {l.sub && <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 4, fontWeight: 300, lineHeight: 1.5 }}>{l.sub}</div>}
            </Link>
          ))}
        </div>
      </div>
    </section>
  )
}
