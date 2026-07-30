import { ImageResponse } from 'next/og'
import { ogCard, ogSize } from '@/lib/og-card'

// Dynamic, branded per-page Open Graph card. Pages pass ?eyebrow=&title=&benefit=
// (see ogImageUrl in lib/og-card). The homepage keeps the static branded image;
// sub-pages use this so shares show the page's own title.
export const runtime = 'nodejs'

export function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const eyebrow = (searchParams.get('eyebrow') || 'AI receptionist').slice(0, 60)
  const title = (searchParams.get('title') || 'The line is always open.').slice(0, 120)
  const benefit = (searchParams.get('benefit') || 'Answers calls, captures leads, and books appointments 24/7.').slice(0, 160)

  return new ImageResponse(ogCard({ eyebrow, title, benefit }), {
    ...ogSize,
    headers: { 'Cache-Control': 'public, max-age=31536000, immutable' },
  })
}
