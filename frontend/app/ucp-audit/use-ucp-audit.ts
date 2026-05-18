'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { api } from '../../lib/api';
import type { UcpAuditJob, UcpAuditOptions } from '../../lib/api/types';

const defaultOptions: UcpAuditOptions = {
  sample_size: 5,
  include_agent_delta: false,
  llm_enabled: false,
  report_formats: ['json', 'markdown'],
  jobsPollInterval: 5000,
};

export type UcpAuditController = ReturnType<typeof useUcpAudit>;

export function useUcpAudit() {
  const queryClient = useQueryClient();
  const [domain, setDomain] = useState('');
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [options, setOptions] = useState<UcpAuditOptions>(defaultOptions);
  const [error, setError] = useState('');

  const jobsQuery = useQuery({
    queryKey: ['ucp-audit-jobs'],
    queryFn: () => api.listUcpAuditJobs({ limit: 20 }),
    refetchInterval: options.jobsPollInterval === false ? false : options.jobsPollInterval,
  });

  const resolvedJobId = activeJobId ?? jobsQuery.data?.[0]?.id ?? null;
  const detailQuery = useQuery({
    queryKey: ['ucp-audit-job', resolvedJobId],
    queryFn: () => api.getUcpAuditJob(resolvedJobId ?? 0),
    enabled: resolvedJobId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.job?.status ?? '');
      return status === 'queued' || status === 'running' ? 2500 : false;
    },
  });

  const activeJob =
    detailQuery.data?.job ?? jobsQuery.data?.find((job) => job.id === resolvedJobId) ?? null;
  const report = detailQuery.data?.report ?? null;
  const isRunning = activeJob?.status === 'queued' || activeJob?.status === 'running';

  const historyItems = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);

  const createMutation = useMutation({
    mutationFn: () => {
      const { jobsPollInterval, ...jobOptions } = options;
      void jobsPollInterval;
      return api.createUcpAuditJob({
        domain,
        options: jobOptions,
      });
    },
    onSuccess: async (job) => {
      setError('');
      setActiveJobId(job.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ucp-audit-jobs'] }),
        queryClient.invalidateQueries({ queryKey: ['ucp-audit-job', job.id] }),
      ]);
    },
    onError: (mutationError) => {
      setError(mutationError instanceof Error ? mutationError.message : 'Unable to start audit.');
    },
  });

  function startAudit() {
    if (!domain.trim()) {
      setError('Domain is required.');
      return;
    }
    createMutation.mutate();
  }

  function updateDomain(value: string) {
    setDomain(value);
    if (error === 'Domain is required.' && value.trim()) {
      setError('');
    }
  }

  function selectJob(job: UcpAuditJob) {
    setActiveJobId(job.id);
    updateDomain(job.domain);
  }

  return {
    activeJob,
    createPending: createMutation.isPending,
    detail: detailQuery.data,
    detailQuery,
    domain,
    error,
    historyItems,
    isRunning,
    options,
    report,
    resolvedJobId,
    setDomain: updateDomain,
    setError,
    setOptions,
    startAudit,
    selectJob,
  };
}
