import type { MetadataRoute } from 'next'
import { INTEGRATION_SLUGS } from './integrations/integrations-data'
import { ARTICLE_SLUGS } from './learn/learn-data'

const SITE_URL = 'https://www.openlines.ai'

type Freq = MetadataRoute.Sitemap[number]['changeFrequency']

// Public, indexable marketing pages only. App/account routes are excluded here
// and disallowed in robots.ts.
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date()
  const pages: { path: string; changeFrequency: Freq; priority: number }[] = [
    { path: '/',             changeFrequency: 'weekly',  priority: 1.0 },
    { path: '/pricing',      changeFrequency: 'monthly', priority: 0.9 },
    { path: '/how-it-works', changeFrequency: 'monthly', priority: 0.8 },
    { path: '/industries',   changeFrequency: 'monthly', priority: 0.8 },
    // Vertical landing pages
    { path: '/salons',       changeFrequency: 'monthly', priority: 0.8 },
    { path: '/barbers',      changeFrequency: 'monthly', priority: 0.8 },
    { path: '/realtors',     changeFrequency: 'monthly', priority: 0.8 },
    { path: '/legal',        changeFrequency: 'monthly', priority: 0.8 },
    { path: '/home-services', changeFrequency: 'monthly', priority: 0.8 },
    { path: '/contractors',  changeFrequency: 'monthly', priority: 0.8 },
    { path: '/restaurants',  changeFrequency: 'monthly', priority: 0.8 },
    { path: '/automotive',   changeFrequency: 'monthly', priority: 0.8 },
    { path: '/insurance',    changeFrequency: 'monthly', priority: 0.8 },
    { path: '/courier',      changeFrequency: 'monthly', priority: 0.8 },
    // Integrations
    { path: '/integrations', changeFrequency: 'monthly', priority: 0.7 },
    ...INTEGRATION_SLUGS.map((slug): { path: string; changeFrequency: Freq; priority: number } => (
      { path: `/integrations/${slug}`, changeFrequency: 'monthly', priority: 0.7 }
    )),
    // Learn / guides
    { path: '/learn',        changeFrequency: 'weekly',  priority: 0.7 },
    ...ARTICLE_SLUGS.map((slug): { path: string; changeFrequency: Freq; priority: number } => (
      { path: `/learn/${slug}`, changeFrequency: 'monthly', priority: 0.6 }
    )),
    { path: '/platform',     changeFrequency: 'monthly', priority: 0.8 },
    { path: '/docs',         changeFrequency: 'monthly', priority: 0.6 },
    { path: '/support',      changeFrequency: 'monthly', priority: 0.5 },
    { path: '/privacy',      changeFrequency: 'yearly',  priority: 0.3 },
    { path: '/terms',        changeFrequency: 'yearly',  priority: 0.3 },
    { path: '/subprocessors', changeFrequency: 'monthly', priority: 0.3 },
    { path: '/acceptable-use', changeFrequency: 'yearly',  priority: 0.3 },
    { path: '/dpa',          changeFrequency: 'yearly',  priority: 0.3 },
  ]

  return pages.map(({ path, changeFrequency, priority }) => ({
    url: `${SITE_URL}${path}`,
    lastModified,
    changeFrequency,
    priority,
  }))
}
