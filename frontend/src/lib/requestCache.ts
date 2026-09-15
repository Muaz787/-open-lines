/**
 * Two small caches behind authedFetch. No imports, so the logic can be reasoned
 * about (and exercised) on its own.
 *
 * 1. In-flight sharing: identical GETs issued at the same moment share one
 *    network request. The dashboard layout and the page under it ask for the
 *    same tenant, leads and appointments on mount; each now costs one request.
 *
 * 2. Last good response: the JSON body of the most recent successful GET per
 *    URL. A page reads it with peekJson() to paint a tab it has already shown
 *    instantly on a revisit, then replaces it with the fresh response its normal
 *    fetch brings back. Any mutation clears it, and so does logout, so it never
 *    outlives the data or the person it belongs to.
 */

const MAX_ENTRIES = 50

const inflight = new Map<string, Promise<Response>>()
const lastGood = new Map<string, unknown>()
// Bumped on every clear, so a GET that was already in flight when a mutation
// happened cannot write its (possibly pre-mutation) body back afterwards.
let generation = 0

function remember(key: string, data: unknown) {
  lastGood.delete(key)
  lastGood.set(key, data)
  if (lastGood.size > MAX_ENTRIES) {
    const oldest = lastGood.keys().next().value
    if (oldest !== undefined) lastGood.delete(oldest)
  }
}

/** Run `send` once for concurrent callers of the same key; each gets its own body. */
export function shareInflight(key: string, send: () => Promise<Response>): Promise<Response> {
  let pending = inflight.get(key)
  if (!pending) {
    const startedAt = generation
    const request = send().then(res => {
      if (res.ok) {
        res.clone().json().then(
          data => { if (startedAt === generation) remember(key, data) },
          () => {},  // not JSON: nothing to remember
        )
      }
      return res
    })
    const done = () => { if (inflight.get(key) === request) inflight.delete(key) }
    request.then(done, done)
    inflight.set(key, request)
    pending = request
  }
  return pending.then(res => res.clone())
}

/** The last successful JSON body for this URL, or undefined if none is cached. */
export function peekJson<T = unknown>(key: string): T | undefined {
  return lastGood.get(key) as T | undefined
}

export function clearResponseCache() {
  generation++
  lastGood.clear()
}
