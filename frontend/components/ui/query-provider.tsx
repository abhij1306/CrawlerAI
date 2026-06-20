import { QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';

import { createAppQueryClient } from '@/api/query-client';

export function QueryProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [client] = useState(createAppQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
