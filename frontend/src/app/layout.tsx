import type { Metadata, Viewport } from 'next'
import { Syne, DM_Sans, DM_Mono } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import './globals.css'

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
  title: 'Open Lines AI — The line is always open.',
  description: 'Open Lines AI answers calls, captures leads, and books appointments 24/7. No staff required. AI voice receptionist for realtors, clinics, and small businesses.',
  keywords: ['Open Lines AI', 'AI receptionist', 'AI phone answering', 'voice AI', 'automated receptionist'],
  openGraph: {
    title: 'Open Lines AI — The line is always open.',
    description: 'AI voice receptionist that answers calls, captures leads, and books appointments 24/7.',
    url: 'https://openlines.ai',
    siteName: 'Open Lines AI',
    type: 'website',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${syne.variable} ${dmSans.variable} ${dmMono.variable}`}>
      <body style={{ fontFamily: 'var(--font-dm), sans-serif' }} suppressHydrationWarning>
        {children}
        <Analytics />
      </body>
    </html>
  )
}
