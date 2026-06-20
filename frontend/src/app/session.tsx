import { createContext, use } from 'react';
import type { ReactNode } from 'react';

import type { User } from '../../lib/api/types';

const SessionContext = createContext<User | null>(null);

export function SessionProvider({ user, children }: Readonly<{ user: User; children: ReactNode }>) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const session = use(SessionContext);
  if (!session) {
    throw new Error('Session context is unavailable.');
  }
  return session;
}
