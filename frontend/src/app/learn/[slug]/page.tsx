import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import LearnArticle from '../../components/LearnArticle'
import { ARTICLE_SLUGS, getArticle } from '../learn-data'

export const dynamicParams = false

export function generateStaticParams() {
  return ARTICLE_SLUGS.map(slug => ({ slug }))
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params
  const c = getArticle(slug)
  if (!c) return {}
  return {
    title: c.metaTitle,
    description: c.metaDescription,
    alternates: { canonical: `/learn/${c.slug}` },
    openGraph: { title: c.metaTitle, description: c.metaDescription, url: `https://www.openlines.ai/learn/${c.slug}`, type: 'article', images: ['/opengraph-image.jpg'] },
  }
}

export default async function LearnPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const c = getArticle(slug)
  if (!c) notFound()
  return <LearnArticle content={c} />
}
