import type { Metadata, Viewport } from 'next'
import { Syne, DM_Sans, DM_Mono } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import Script from 'next/script'
import './globals.css'

// Google tags (gtag.js), loaded on every route via the root layout. IDs are public.
const GA_ID = 'G-06VMJV17HC'       // GA4 analytics
const GADS_ID = 'AW-18323006317'   // Google Ads (conversion tracking)

const syne = Syne({
  subsets: ['latin'],
  variable: '--font-syne',
  weight: ['400', '500', '600', '700', '800'],
})

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-dm',
  weight: ['300', '400', '500'],
})

const dmMono = DM_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  weight: ['400', '500'],
})

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

export const metadata: Metadata = {
  metadataBase: new URL('https://openlines.ai'),
  title: 'Open Lines AI — The line is always open.',
  description: 'Open Lines AI answers calls, captures leads, and books appointments 24/7. No staff required. AI voice receptionist for realtors, clinics, and small businesses.',
  keywords: ['Open Lines AI', 'AI receptionist', 'AI phone answering', 'voice AI', 'automated receptionist'],
  alternates: { canonical: '/' },
  openGraph: {
    title: 'Open Lines AI — The line is always open.',
    description: 'AI voice receptionist that answers calls, captures leads, and books appointments 24/7.',
    url: 'https://openlines.ai',
    siteName: 'Open Lines AI',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Open Lines AI — The line is always open.',
    description: 'AI voice receptionist that answers calls, captures leads, and books appointments 24/7.',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${syne.variable} ${dmSans.variable} ${dmMono.variable}`}>
      <body style={{ fontFamily: 'var(--font-dm), sans-serif' }} suppressHydrationWarning>
        {children}
        <Analytics />
        <Script
          src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
          strategy="afterInteractive"
        />
        <Script id="ga4-init" strategy="afterInteractive">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', '${GA_ID}');
            gtag('config', '${GADS_ID}');
          `}
        </Script>
      </body>
    </html>
  )
}
