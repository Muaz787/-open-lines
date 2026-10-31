// Pure rules for dashboard state kept in the URL. Separate from the hook below so
// they can be tested, and so an edited or stale URL can never reach a request.

export function parseChoice<T extends string>(raw: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(raw as T) ? (raw as T) : fallback
}

// The query string with one value changed. The default is left out, so the plain
// page URL stays the canonical one for its default view.
export function withChoice(search: string, name: string, value: string, fallback: string): string {
  const params = new URLSearchParams(search)
  if (value === fallback) params.delete(name)
  else params.set(name, value)
  const next = params.toString()
  return next ? `?${next}` : ''
}
