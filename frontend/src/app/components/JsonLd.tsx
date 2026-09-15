/* ─────────────────────────────────────────────────────────────
   Structured-data helpers. Renders JSON-LD <script> tags so
   generated marketing pages are eligible for FAQ and breadcrumb
   rich results, and read as genuine, distinct pages to crawlers.
   Server-safe (no client hooks) — drop into any page.
   ───────────────────────────────────────────────────────────── */

const SITE_URL = 'https://www.openlines.ai'

/** Where a number can actually be issued — telephony.SUPPORTED_COUNTRIES.
 *
 *  This said "Canada" alone on every generated page while the product served
 *  six countries, which is a geographic restriction we were publishing about
 *  ourselves in the one field search and answer engines read to decide whether
 *  a result is relevant to someone abroad. An Irish business asking which AI
 *  receptionist works for them was being told, in machine-readable terms, that
 *  this one does not. */
// The countries we actually accept signups from. GB, AU and NZ require carrier
// documentation we do not yet have a pipeline for, and country_access refuses
// them — claiming them as areaServed would be a schema assertion we cannot honour.
const SERVED_COUNTRIES = [
  'Canada', 'United States', 'Ireland',
]

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
        areaServed: SERVED_COUNTRIES.map(name => ({ '@type': 'Country', name })),
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


/** The product itself: what it is, what it costs, and what it runs on.
 *
 *  FAQPage and Service describe a PAGE. This describes the THING, which is what
 *  an answer engine needs when someone asks "what should I use" rather than
 *  "how does X work" — and it carries the prices, so a model comparing options
 *  can quote ours instead of guessing or omitting us.
 *
 *  Prices come from lib/plans, the same list the pricing page renders, so the
 *  published figure cannot drift from the one a customer is shown.
 */
export function ProductJsonLd({ plans }: {
  plans: { name: string; price: number }[]
}) {
  return (
    <Script
      data={{
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Open Lines',
        applicationCategory: 'BusinessApplication',
        applicationSubCategory: 'AI phone receptionist',
        operatingSystem: 'Web',
        url: SITE_URL,
        description:
          'An AI receptionist that answers your business phone, books appointments '
          + 'into your existing calendar, and sends you a summary of every call.',
        offers: plans.map(p => ({
          '@type': 'Offer',
          name: p.name,
          price: String(p.price),
          priceCurrency: 'USD',
          category: 'Monthly subscription',
          availability: 'https://schema.org/InStock',
          url: `${SITE_URL}/pricing`,
        })),
        provider: {
          '@type': 'Organization',
          name: 'Open Lines Technologies Inc.',
          url: SITE_URL,
        },
      }}
    />
  )
}
