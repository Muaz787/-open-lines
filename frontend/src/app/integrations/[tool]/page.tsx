import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import IntegrationLanding from '../../components/IntegrationLanding'
import { INTEGRATION_SLUGS, getIntegration } from '../integrations-data'
import { ogImageUrl } from '@/lib/og-card'

// Only the integrations we actually support get pages; anything else 404s.
export const dynamicParams = false

export function generateStaticParams() {
  return INTEGRATION_SLUGS.map(tool => ({ tool }))
}

export async function generateMetadata({ params }: { params: Promise<{ tool: string }> }): Promise<Metadata> {
  const { tool } = await params
  const c = getIntegration(tool)
  if (!c) return {}
  return {
    title: c.metaTitle,
    description: c.metaDescription,
    alternates: { canonical: `/integrations/${c.slug}` },
    openGraph: {
      title: `${c.name} integration`,
      description: c.metaDescription,
      url: `https://www.openlines.ai/integrations/${c.slug}`,
      images: [ogImageUrl({ eyebrow: c.eyebrow, title: c.h1, benefit: `${c.name} + Open Lines` })],
    },
  }
}

export default async function IntegrationPage({ params }: { params: Promise<{ tool: string }> }) {
  const { tool } = await params
  const c = getIntegration(tool)
  if (!c) notFound()
  return <IntegrationLanding content={c} />
}
