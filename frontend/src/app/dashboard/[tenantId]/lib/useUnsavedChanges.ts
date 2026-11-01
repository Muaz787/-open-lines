import { useEffect } from 'react'

// Asks before a reload or closed tab discards unsaved edits. The App Router gives no
// way to intercept an in-app link, so the page also says the edits are unsaved.
export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
}
