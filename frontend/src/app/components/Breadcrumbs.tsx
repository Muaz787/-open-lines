import Link from 'next/link'

/* Visible breadcrumb trail. Pair with <BreadcrumbJsonLd> for the structured
   data. The last item is the current page (not a link). */
export default function Breadcrumbs({ trail }: { trail: { name: string; path: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" style={{ marginBottom: 18 }}>
      <ol style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, listStyle: 'none', padding: 0, margin: 0, fontSize: 13, color: 'var(--text-3)' }}>
        {trail.map((t, i) => {
          const last = i === trail.length - 1
          return (
            <li key={t.path} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {last ? (
                <span aria-current="page" style={{ color: 'var(--text-2)', fontWeight: 500 }}>{t.name}</span>
              ) : (
                <>
                  <Link href={t.path} style={{ color: 'var(--text-3)' }}>{t.name}</Link>
                  <span aria-hidden style={{ opacity: 0.6 }}>/</span>
                </>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
