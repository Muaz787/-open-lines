import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { parseChoice, withChoice } from './queryState'

// A filter or tab held in the URL, so reload, deep links and Back/Forward keep it.
export function useQueryParam<T extends string>(name: string, allowed: readonly T[], fallback: T) {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const value = parseChoice(params.get(name), allowed, fallback)
  const setValue = (next: T) => {
    router.push(`${pathname}${withChoice(window.location.search, name, next, fallback)}`, { scroll: false })
  }
  return [value, setValue] as const
}
