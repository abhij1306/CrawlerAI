import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  aiVisibilityApi,
  aiVisibilityQueryKeys,
  type AiVisibilityProjectCreate,
  type AiVisibilityProviderId,
  type AiVisibilityRunCreate,
  type PromptInput,
} from '../../lib/api/ai-visibility';

export type RunBenchmarkOptions = {
  projectId: number;
  repetitions: number;
  provider: AiVisibilityProviderId;
  promptIndices?: number[];
  openReport: boolean;
};

export function useAiVisibility() {
  const queryClient = useQueryClient();
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [selectedExecutionId, setSelectedExecutionId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [repetitions, setRepetitions] = useState(3);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyProjectId, setHistoryProjectId] = useState<number | null>(null);
  const [deleteRunId, setDeleteRunId] = useState<number | null>(null);
  const [cancelRunId, setCancelRunId] = useState<number | null>(null);

  // Provider status
  const { data: providers } = useQuery({
    queryKey: aiVisibilityQueryKeys.providers(),
    queryFn: aiVisibilityApi.listAiVisibilityProviders,
  });

  const { data: bestAndLessPreset } = useQuery({
    queryKey: aiVisibilityQueryKeys.bestAndLessPreset(),
    queryFn: aiVisibilityApi.getBestAndLessPreset,
  });

  // Projects list
  const { data: projects = [] } = useQuery({
    queryKey: aiVisibilityQueryKeys.projects(),
    queryFn: () => aiVisibilityApi.listAiVisibilityProjects(),
  });

  const { data: savedRuns = [] } = useQuery({
    queryKey: aiVisibilityQueryKeys.runs(),
    queryFn: () => aiVisibilityApi.listAiVisibilityRuns({ limit: 100 }),
  });

  // Create project mutation
  const createProjectMutation = useMutation({
    mutationFn: aiVisibilityApi.createAiVisibilityProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.projects() });
      setFormOpen(false);
    },
  });

  // Create run mutation
  const createRunMutation = useMutation({
    mutationFn: ({
      openReport: _openReport,
      ...payload
    }: AiVisibilityRunCreate & {
      openReport: boolean;
    }) => aiVisibilityApi.createAiVisibilityRun(payload),
    onSuccess: (run, variables) => {
      queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.runs() });
      if (variables.openReport) setActiveRunId(run.id);
    },
  });

  const updateProjectMutation = useMutation({
    mutationFn: ({ projectId, prompts }: { projectId: number; prompts: PromptInput[] }) =>
      aiVisibilityApi.updateAiVisibilityProject(projectId, { prompts }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.projects() }),
  });

  const deleteRunMutation = useMutation({
    mutationFn: aiVisibilityApi.deleteAiVisibilityRun,
    onSuccess: (_result, runId) => {
      if (activeRunId === runId) setActiveRunId(null);
      setDeleteRunId(null);
      queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.runs() });
    },
  });

  const cancelRunMutation = useMutation({
    mutationFn: aiVisibilityApi.cancelAiVisibilityRun,
    onSuccess: (_result, runId) => {
      setCancelRunId(null);
      queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.runs() });
      queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.run(runId) });
    },
  });

  // Active run detail (with polling)
  const { data: runDetail } = useQuery({
    queryKey: aiVisibilityQueryKeys.run(activeRunId!),
    queryFn: () => aiVisibilityApi.getAiVisibilityRun(activeRunId!),
    enabled: activeRunId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.run.status;
      return status === 'running' || status === 'pending' ? 2000 : false;
    },
  });

  // Selected execution detail
  const { data: executionDetail } = useQuery({
    queryKey: aiVisibilityQueryKeys.execution(selectedExecutionId!),
    queryFn: () => aiVisibilityApi.getAiVisibilityExecution(selectedExecutionId!),
    enabled: selectedExecutionId !== null,
  });

  const run = runDetail?.run;
  const executions = runDetail?.executions ?? [];
  // Run-level counts are only persisted at finalize, so they read 0 mid-run.
  // Derive live progress from the executions array, which updates per poll.
  const liveCompleted = executions.filter((e) => e.status === 'completed').length;
  const liveFailed = executions.filter((e) => e.status === 'failed').length;
  const runInProgress = run?.status === 'running' || run?.status === 'pending';
  const completedCount = runInProgress ? liveCompleted : (run?.completed_count ?? 0);
  const failedCount = runInProgress ? liveFailed : (run?.failed_count ?? 0);
  const showSummary = Boolean(
    run && (run.status === 'completed' || run.status === 'degraded') && run.summary,
  );

  useEffect(() => {
    if (run && ['completed', 'degraded', 'failed'].includes(run.status)) {
      queryClient.invalidateQueries({ queryKey: aiVisibilityQueryKeys.runs() });
    }
  }, [queryClient, run]);

  const handleRunBenchmark = ({
    projectId,
    repetitions: reps,
    provider,
    promptIndices,
    openReport,
  }: RunBenchmarkOptions) => {
    createRunMutation.mutate({
      project_id: projectId,
      repetitions: reps,
      provider,
      prompt_indices: promptIndices,
      openReport,
    });
  };

  const visibleHistory = historyProjectId
    ? savedRuns.filter((savedRun) => savedRun.project_id === historyProjectId)
    : savedRuns;
  const historyItems = visibleHistory.map((savedRun) => ({
    id: savedRun.id,
    status: savedRun.status,
    created_at: savedRun.created_at,
    label: projects.find((project) => project.id === savedRun.project_id)?.name ?? 'Domain',
    meta: `${savedRun.provider} · ${savedRun.requested_count} executions`,
    deletable: !['pending', 'running'].includes(savedRun.status),
    cancellable: ['pending', 'running'].includes(savedRun.status),
  }));

  const openHistory = (projectId: number | null) => {
    setHistoryProjectId(projectId);
    setHistoryOpen(true);
  };

  return {
    // queries
    providers,
    bestAndLessPreset,
    projects,
    savedRuns,
    run,
    executions,
    executionDetail,
    // derived run progress
    runInProgress,
    completedCount,
    failedCount,
    showSummary,
    historyItems,
    historyProjectId,
    // UI state
    activeRunId,
    setActiveRunId,
    selectedExecutionId,
    setSelectedExecutionId,
    formOpen,
    setFormOpen,
    repetitions,
    setRepetitions,
    historyOpen,
    setHistoryOpen,
    openHistory,
    deleteRunId,
    setDeleteRunId,
    cancelRunId,
    setCancelRunId,
    // actions
    handleRunBenchmark,
    createProject: (payload: AiVisibilityProjectCreate) => createProjectMutation.mutate(payload),
    saveProjectPrompts: (projectId: number, prompts: PromptInput[]) =>
      updateProjectMutation.mutate({ projectId, prompts }),
    confirmDeleteRun: () => {
      if (deleteRunId !== null) deleteRunMutation.mutate(deleteRunId);
    },
    confirmCancelRun: () => {
      if (cancelRunId !== null) cancelRunMutation.mutate(cancelRunId);
    },
    // mutation status
    createProjectPending: createProjectMutation.isPending,
    createRunPending: createRunMutation.isPending,
    updateProjectPending: updateProjectMutation.isPending,
    deleteRunPending: deleteRunMutation.isPending,
    cancelRunPending: cancelRunMutation.isPending,
  };
}
