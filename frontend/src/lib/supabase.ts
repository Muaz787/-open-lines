import { createClient } from '@supabase/supabase-js'
import { keepSessionUnlessRejected } from '@/lib/authCheck'

const authSafeFetch: typeof fetch = async (input, init) => {
  const url = input instanceof Request ? input.url : String(input)
  return keepSessionUnlessRejected(url, await fetch(input, init))
}

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  { global: { fetch: authSafeFetch } },
)
