import type { Metadata } from 'next'
import { Syne, DM_Sans } from 'next/font/google'
import Cursor from './components/Cursor'
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

export const metadata: Metadata = {
  title: 'Open Lines — The line is always open.',
  description: 'AI-powered phone handling for Realtors, Clinics, and Public Offices.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${syne.variable} ${dmSans.variable}`}>
      <body style={{ fontFamily: 'var(--font-dm), sans-serif' }} suppressHydrationWarning>
        <Cursor />
        {children}
      </body>
    </html>
  )
}
