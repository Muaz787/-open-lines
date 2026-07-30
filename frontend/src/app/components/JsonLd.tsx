/* ─────────────────────────────────────────────────────────────
   Structured-data helpers. Renders JSON-LD <script> tags so
   generated marketing pages are eligible for FAQ and breadcrumb
   rich results, and read as genuine, distinct pages to crawlers.
   Server-safe (no client hooks) — drop into any page.
   ───────────────────────────────────────────────────────────── */

const SITE_URL = 'https://www.openlines.ai'

function Script({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      // Content is our own static data, not user input.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  )
}

export function FaqJsonLd({ faqs }: { faqs: { q: string; a: string }[] }) {
  if (!faqs?.length) return null
  return (
    <Script
      data={{
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: faqs.map(f => ({
          '@type': 'Question',
          name: f.q,
          acceptedAnswer: { '@type': 'Answer', text: f.a },
        })),
      }}
    />
  )
}

export function ServiceJsonLd({
  name,
  description,
  path,
  serviceType,
}: { name: string; description: string; path: string; serviceType?: string }) {
  return (
    <Script
      data={{
        '@context': 'https://schema.org',
        '@type': 'Service',
        name,
        description,
        serviceType: serviceType || 'AI phone receptionist',
        url: `${SITE_URL}${path}`,
        provider: {
          '@type': 'Organization',
          name: 'Open Lines Technologies Inc.',
          url: SITE_URL,
        },
        areaServed: { '@type': 'Country', name: 'Canada' },
      }}
    />
  )
}

export function BreadcrumbJsonLd({ trail }: { trail: { name: string; path: string }[] }) {
  if (!trail?.length) return null
  return (
    <Script
      data={{
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        itemListElement: trail.map((t, i) => ({
          '@type': 'ListItem',
          position: i + 1,
          name: t.name,
          item: `${SITE_URL}${t.path}`,
        })),
      }}
    />
  )
}
