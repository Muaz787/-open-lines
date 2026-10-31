'use client'

import { createContext, useContext, type ReactNode } from 'react'
import { presentAccount, type Account, type ProviderState } from './accountState'

interface AccountState {
  account: Account | null | undefined
  status: 'loading' | 'ready' | 'error'
  provider?: ProviderState
}

const AccountContext = createContext<AccountState>({ account: null, status: 'loading' })

// Loaded once by the dashboard layout, so every page reads the same answer,
// including what Stripe said, and no page can disagree with another.
export function AccountProvider({ value, children }: { value: AccountState; children: ReactNode }) {
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>
}

export function useAccountState() {
  return useContext(AccountContext)
}

export function useAccountView() {
  const { account, status, provider } = useContext(AccountContext)
  return presentAccount(account, status, provider)
}
