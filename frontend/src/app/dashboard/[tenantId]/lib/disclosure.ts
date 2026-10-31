import type { KeyboardEvent } from 'react'

// Props that make a clickable row work as a disclosure from the keyboard and to a
// screen reader. Keys only act on the row itself, so buttons inside it keep theirs.
export function disclosureProps(open: boolean, toggle: () => void, panelId: string) {
  return {
    role: 'button',
    tabIndex: 0,
    'aria-expanded': open,
    'aria-controls': panelId,
    onClick: toggle,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault()
        toggle()
      }
    },
  }
}
