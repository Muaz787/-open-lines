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
const SERVED_COUNTRIES = [
  'Canada', 'United States', 'Ireland', 'United Kingdom', 'Australia', 'New Zealand',
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
        provider: { '@id': ORG_ID },
        areaServed: SERVED_COUNTRIES.map(name => ({ '@type': 'Country', name })),
      }}
    />
  )
}

/* ─────────────────────────────────────────────────────────────
   Brand entity. Three months of Search Console showed the site
   failing to own its own name: "openlines" sat at position 23 and
   "openline ai" at 65.8. Nothing on the site told a crawler that
   OpenLines, Open Lines and OpenLines.ai are one entity, because
   Organization existed only nested inside Service as a provider,
   never as a subject with an @id of its own.

   These two render site-wide from the root layout. The @id lets
   every other block point at the same entity instead of restating
   an anonymous one.
   ───────────────────────────────────────────────────────────── */

export const ORG_ID = `${SITE_URL}/#organization`

//: Profiles that prove the entity is the same one elsewhere. EMPTY ON PURPOSE:
//: sameAs must list URLs that genuinely resolve to this company, and inventing
//: them is worse than omitting the field. Add the real LinkedIn / X / Crunchbase
//: URLs here and they take effect everywhere at once.
const SAME_AS: string[] = []

export function OrganizationJsonLd() {
  return (
    <Script
      data={{
        '@context': 'https://schema.org',
        '@type': 'Organization',
        '@id': ORG_ID,
        name: 'Open Lines Technologies Inc.',
        // Every spelling a person actually searches for.
        alternateName: ['Open Lines', 'OpenLines', 'OpenLines.ai', 'Open Lines AI'],
        url: SITE_URL,
        logo: {
          '@type': 'ImageObject',
          url: `${SITE_URL}/logo.png`,
        },
        description:
          'Open Lines is an AI receptionist that answers business calls, checks live '
          + 'availability and books appointments into the calendar a business already uses.',
        areaServed: SERVED_COUNTRIES.map(name => ({ '@type': 'Country', name })),
        ...(SAME_AS.length ? { sameAs: SAME_AS } : {}),
      }}
    />
  )
}

export function WebSiteJsonLd() {
  return (
    <Script
      data={{
        '@context': 'https://schema.org',
        '@type': 'WebSite',
        '@id': `${SITE_URL}/#website`,
        name: 'Open Lines',
        alternateName: ['OpenLines', 'OpenLines.ai'],
        url: SITE_URL,
        publisher: { '@id': ORG_ID },
        inLanguage: 'en',
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
        provider: { '@id': ORG_ID },
      }}
    />
  )
}
