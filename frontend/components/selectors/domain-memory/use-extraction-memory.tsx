import { useQuery } from '@tanstack/react-query';
import { RefreshCcw } from 'lucide-react';

import { queryKeys } from '@/api/query-keys';
import { api } from '../../../lib/api';
import { Button } from '../../ui/primitives';

export function useExtractionMemory(domain: string, fallbackError: string) {
  const query = useQuery({
    queryKey: queryKeys.domainMemory.extraction(domain),
    queryFn: () => api.getExtractionMemory(domain),
  });
  const error = query.error
    ? query.error instanceof Error
      ? query.error.message
      : fallbackError
    : '';
  return { error, query };
}

export function ExtractionMemoryRefreshButton({
  isFetching,
  onRefresh,
}: {
  isFetching: boolean;
  onRefresh: () => void;
}) {
  return (
    <Button type="button" variant="neutral" size="sm" onClick={onRefresh} disabled={isFetching}>
      <RefreshCcw className="size-3" />
      {isFetching ? 'Refreshing...' : 'Refresh'}
    </Button>
  );
}
