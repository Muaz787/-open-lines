import { defineConfig } from '@playwright/test'

// Local only. The server is pointed at hosts that do not exist and each test
// fulfils them itself, so a run cannot reach the real API, Stripe or Supabase.
const PORT = 3100

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 120_000,
  use: { baseURL: `http://localhost:${PORT}` },
  webServer: {
    command: `npx next dev -p ${PORT}`,
    url: `http://localhost:${PORT}/onboarding`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      NEXT_PUBLIC_API_URL: 'http://api.test',
      NEXT_PUBLIC_SUPABASE_URL: 'http://supabase.test',
      NEXT_PUBLIC_SUPABASE_ANON_KEY: 'stub',
      NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY: 'pk_test_stub',
      NEXT_PUBLIC_POSTHOG_KEY: '',
    },
  },
})
