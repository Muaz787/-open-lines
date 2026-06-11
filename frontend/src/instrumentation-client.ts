// Next.js client instrumentation — runs once in the browser before hydration.
// https://nextjs.org/docs/app/api-reference/file-conventions/instrumentation-client
import posthog from 'posthog-js'
import { persistFirstTouch } from '@/lib/analytics'

const key = process.env.NEXT_PUBLIC_POSTHOG_KEY

if (key) {
  posthog.init(key, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
    // '2025-05-24' defaults include capture_pageview: 'history_change' —
    // SPA navigations produce exactly one $pageview each, no duplicates.
    defaults: '2025-05-24',
    // PRIVACY: the dashboard renders caller phone numbers, lead names and
    // full call transcripts. Autocapture sends clicked-element text, so it
    // stays OFF — all product events are explicit via lib/analytics.ts.
    autocapture: false,
    // PRIVACY: session recordings would capture transcripts, calendar
    // details and uploaded knowledge-base content. Never enable without
    // strict masking.
    disable_session_recording: true,
    // Don't create person profiles for anonymous landing-page visitors.
    person_profiles: 'identified_only',
    loaded: (ph) => {
      if (process.env.NODE_ENV === 'development') ph.debug()
    },
  })

  // Store first-touch UTM/referrer for later attribution on signup events.
  persistFirstTouch()
}
