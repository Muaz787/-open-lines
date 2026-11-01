// Minutes reset with a subscription's billing period. An account with no subscription
// has no period, so its counter runs from the start and says so.
export function usagePeriodText(source: string | undefined, anchor: string | null | undefined): string {
  if (source !== 'subscription') return 'Since this account started. This account has no billing period, so this doesn’t reset.'
  if (!anchor) return 'This billing period.'
  const start = new Date(`${anchor}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', year: 'numeric' })
  return `This billing period, since ${start}.`
}
