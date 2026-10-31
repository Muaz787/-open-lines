// Wording for a list with nothing to show. A filter that matches nothing is a
// different situation from an account with no calls yet, and must say so.

export type CallPeriod = '7' | '30' | '0'
export type CallQuality = 'all' | 'hot' | 'warm' | 'cold'

export interface EmptyCopy {
  title: string
  sub: string
  canClear: boolean
}

const PERIOD_TEXT: Record<CallPeriod, string> = {
  '7': 'in the last 7 days',
  '30': 'in the last 30 days',
  '0': 'yet',
}

export function emptyCallsCopy(quality: CallQuality, period: CallPeriod, callsInPeriod: number): EmptyCopy {
  if (quality !== 'all' && callsInPeriod > 0) {
    return {
      title: `No ${quality} calls ${period === '0' ? 'found' : PERIOD_TEXT[period]}.`,
      sub: 'Try another quality filter or date range.',
      canClear: true,
    }
  }
  if (period !== '0') {
    return {
      title: `No calls ${PERIOD_TEXT[period]}.`,
      sub: 'Try a longer date range.',
      canClear: true,
    }
  }
  if (quality !== 'all') {
    return { title: `No ${quality} calls found.`, sub: 'Try another quality filter.', canClear: true }
  }
  return {
    title: 'No calls yet.',
    sub: 'Calls will appear here after your first inbound call.',
    canClear: false,
  }
}
