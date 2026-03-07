import React, { createContext, useContext, useState, useCallback, type ReactNode } from 'react';

interface AccountContextState {
  selectedAccountId: number | null;
  setSelectedAccountId: (id: number | null) => void;
  isAggregated: boolean;
}

const AccountContext = createContext<AccountContextState | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [selectedAccountId, setSelectedAccountIdState] = useState<number | null>(null);

  const setSelectedAccountId = useCallback((id: number | null) => {
    setSelectedAccountIdState(id);
  }, []);

  const value: AccountContextState = {
    selectedAccountId,
    setSelectedAccountId,
    isAggregated: selectedAccountId === null,
  };

  return React.createElement(AccountContext.Provider, { value }, children);
}

export function useAccount(): AccountContextState {
  const ctx = useContext(AccountContext);
  if (!ctx) throw new Error('useAccount must be used within AccountProvider');
  return ctx;
}
