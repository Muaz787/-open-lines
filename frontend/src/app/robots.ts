import type { MetadataRoute } from 'next'

const SITE_URL = 'https://openlines.ai'

// Crawlers may index the public marketing pages; keep app/account areas out.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: [
        '/admin',
        '/dashboard',
        '/login',
        '/onboarding',
        '/forgot-password',
        '/reset-password',
        '/payment-success',
        '/payment-cancelled',
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  }
}
