import type { MetadataRoute } from 'next'

const SITE_URL = 'https://openlines.ai'

// Public, indexable marketing pages only. App/account routes are excluded here
// and disallowed in robots.ts.
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date()
  const pages: { path: string; changeFrequency: MetadataRoute.Sitemap[number]['changeFrequency']; priority: number }[] = [
    { path: '/',             changeFrequency: 'weekly',  priority: 1.0 },
    { path: '/pricing',      changeFrequency: 'monthly', priority: 0.9 },
    { path: '/how-it-works', changeFrequency: 'monthly', priority: 0.8 },
    { path: '/industries',   changeFrequency: 'monthly', priority: 0.8 },
    { path: '/salons',       changeFrequency: 'monthly', priority: 0.8 },
    { path: '/barbers',      changeFrequency: 'monthly', priority: 0.8 },
    { path: '/realtors',     changeFrequency: 'monthly', priority: 0.8 },
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
