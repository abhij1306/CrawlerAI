import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import type {
  AiVisibilityExecution,
  AiVisibilityProject,
  AiVisibilityProviderStatus,
  AiVisibilityRun,
} from '../../lib/api/ai-visibility';
import { useAiVisibility } from './use-ai-visibility';

const apiMock = vi.hoisted(() => ({
  listAiVisibilityProviders: vi.fn(),
  getBestAndLessPreset: vi.fn(),
  listAiVisibilityProjects: vi.fn(),
  createAiVisibilityProject: vi.fn(),
  updateAiVisibilityProject: vi.fn(),
  listAiVisibilityRuns: vi.fn(),
  getAiVisibilityRun: vi.fn(),
  deleteAiVisibilityRun: vi.fn(),
  cancelAiVisibilityRun: vi.fn(),
  createAiVisibilityRun: vi.fn(),
  getAiVisibilityExecution: vi.fn(),
  getAiVisibilityExportCsvUrl: vi.fn(),
  getAiVisibilityExportMarkdownUrl: vi.fn(),
}));

vi.mock('../../lib/api/ai-visibility', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/ai-visibility')>();
  return { ...actual, aiVisibilityApi: apiMock };
});

const PROVIDER: AiVisibilityProviderStatus = {
  provider: 'gemini',
  label: 'Gemini',
  surface: 'ai_search',
  configured: true,
  model: 'gemini-2.5-flash',
  supports_search_fanout: true,
  supports_citations: true,
};

const PROJECT: AiVisibilityProject = {
  id: 1,
  name: 'Best&Less',
  brand_name: 'Best&Less',
  brand_aliases: [],
  owned_domains: ['bestandless.com.au'],
  unintended_domains: [],
  competitors: [],
  country_code: 'AU',
  language_code: 'en-AU',
  benchmark_mode: 'controlled_localized',
  prompts: [{ text: 'best kids clothes' }],
  default_repetitions: 3,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
};

function makeRun(overrides: Partial<AiVisibilityRun> = {}): AiVisibilityRun {
  return {
    id: 42,
    project_id: 1,
    status: 'running',
    provider: 'gemini',
    model: 'gemini-2.5-flash',
    repetitions: 3,
    random_seed: 'seed',
    configuration: {},
    summary: {},
    requested_count: 3,
    completed_count: 0,
    failed_count: 0,
    error_message: '',
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
    ...overrides,
  };
}

function makeExecution(overrides: Partial<AiVisibilityExecution> = {}): AiVisibilityExecution {
  return {
    id: 7,
    run_id: 42,
    prompt_index: 0,
    prompt_text_snapshot: 'best kids clothes',
    prompt_theme_snapshot: '',
    prompt_intent_snapshot: '',
    repetition: 1,
    randomized_position: 0,
    status: 'completed',
    answer_text: 'answer',
    search_used: true,
    search_events: [],
    citations: [],
    score: { brand_mentioned: true },
    request_snapshot: {},
    provider_metadata: {},
    error_code: '',
    error_message: '',
    latency_ms: 120,
    ...overrides,
  };
}

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

describe('useAiVisibility', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listAiVisibilityProviders.mockResolvedValue([PROVIDER]);
    apiMock.getBestAndLessPreset.mockResolvedValue({ name: 'preset', brand_name: 'brand' });
    apiMock.listAiVisibilityProjects.mockResolvedValue([PROJECT]);
    apiMock.listAiVisibilityRuns.mockResolvedValue([makeRun()]);
    apiMock.getAiVisibilityRun.mockResolvedValue({ run: makeRun(), executions: [] });
    apiMock.getAiVisibilityExecution.mockResolvedValue(makeExecution());
  });

  it('loads providers, preset, projects, and runs through the query-key factory', async () => {
    const { queryClient, wrapper } = createHarness();
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    await waitFor(() => expect(result.current.savedRuns).toHaveLength(1));

    expect(result.current.providers).toEqual([PROVIDER]);
    expect(apiMock.listAiVisibilityProjects).toHaveBeenCalledWith();
    expect(apiMock.listAiVisibilityRuns).toHaveBeenCalledWith({ limit: 100 });

    const cachedKeys = queryClient
      .getQueryCache()
      .findAll()
      .map((query) => query.queryKey);
    expect(cachedKeys).toContainEqual(['ai-visibility', 'providers']);
    expect(cachedKeys).toContainEqual(['ai-visibility', 'presets', 'best-and-less']);
    expect(cachedKeys).toContainEqual(['ai-visibility', 'projects']);
    expect(cachedKeys).toContainEqual(['ai-visibility', 'runs', 'all']);
  });

  it('builds history items with per-project filtering and labels', async () => {
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.savedRuns).toHaveLength(1));

    expect(result.current.historyItems).toEqual([
      expect.objectContaining({
        id: 42,
        label: 'Best&Less',
        meta: 'gemini · 3 executions',
        deletable: false,
        cancellable: true,
      }),
    ]);

    act(() => result.current.openHistory(99));
    expect(result.current.historyItems).toEqual([]);
    expect(result.current.historyOpen).toBe(true);
  });

  it('starts a benchmark without leaking openReport to the API and opens the report', async () => {
    const { wrapper } = createHarness();
    apiMock.createAiVisibilityRun.mockResolvedValue(makeRun({ id: 77 }));
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));

    act(() =>
      result.current.handleRunBenchmark({
        projectId: 1,
        repetitions: 2,
        provider: 'gemini',
        promptIndices: [0, 2],
        openReport: true,
      }),
    );

    await waitFor(() => expect(result.current.activeRunId).toBe(77));
    expect(apiMock.createAiVisibilityRun).toHaveBeenCalledWith({
      project_id: 1,
      repetitions: 2,
      provider: 'gemini',
      prompt_indices: [0, 2],
    });
  });

  it('does not open the report when openReport is false', async () => {
    const { wrapper } = createHarness();
    apiMock.createAiVisibilityRun.mockResolvedValue(makeRun({ id: 78 }));
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));

    act(() =>
      result.current.handleRunBenchmark({
        projectId: 1,
        repetitions: 1,
        provider: 'gemini',
        openReport: false,
      }),
    );

    await waitFor(() => expect(apiMock.createAiVisibilityRun).toHaveBeenCalled());
    expect(result.current.activeRunId).toBeNull();
  });

  it('derives live progress from executions while a run is in progress', async () => {
    const { wrapper } = createHarness();
    apiMock.getAiVisibilityRun.mockResolvedValue({
      run: makeRun({ status: 'running', completed_count: 0, failed_count: 0 }),
      executions: [makeExecution({ id: 1 }), makeExecution({ id: 2, status: 'failed' })],
    });
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    act(() => result.current.setActiveRunId(42));

    await waitFor(() => expect(result.current.run?.id).toBe(42));
    expect(result.current.completedCount).toBe(1);
    expect(result.current.failedCount).toBe(1);
    expect(result.current.runInProgress).toBe(true);
    expect(result.current.showSummary).toBe(false);
  });

  it('uses persisted counts once a run finishes and exposes the summary', async () => {
    const { wrapper } = createHarness();
    apiMock.getAiVisibilityRun.mockResolvedValue({
      run: makeRun({
        status: 'completed',
        completed_count: 9,
        failed_count: 1,
        summary: { brand_mention_rate: 0.5 },
      }),
      executions: [makeExecution({ id: 1 })],
    });
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    act(() => result.current.setActiveRunId(42));

    await waitFor(() => expect(result.current.run?.status).toBe('completed'));
    expect(result.current.completedCount).toBe(9);
    expect(result.current.failedCount).toBe(1);
    expect(result.current.runInProgress).toBe(false);
    expect(result.current.showSummary).toBe(true);
  });

  it('clears the active run when that run is deleted', async () => {
    const { wrapper } = createHarness();
    apiMock.deleteAiVisibilityRun.mockResolvedValue(undefined);
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    act(() => result.current.setActiveRunId(42));
    await waitFor(() => expect(result.current.run?.id).toBe(42));

    act(() => result.current.setDeleteRunId(42));
    act(() => result.current.confirmDeleteRun());

    await waitFor(() => expect(result.current.activeRunId).toBeNull());
    expect(apiMock.deleteAiVisibilityRun).toHaveBeenCalledWith(42, expect.anything());
    expect(result.current.deleteRunId).toBeNull();
  });

  it('creates a project and closes the form dialog', async () => {
    const { wrapper } = createHarness();
    apiMock.createAiVisibilityProject.mockResolvedValue(PROJECT);
    const { result } = renderHook(() => useAiVisibility(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    act(() => result.current.setFormOpen(true));
    act(() => result.current.createProject({ name: 'New', brand_name: 'Brand' }));

    await waitFor(() => expect(result.current.formOpen).toBe(false));
    expect(apiMock.createAiVisibilityProject).toHaveBeenCalledWith(
      {
        name: 'New',
        brand_name: 'Brand',
      },
      expect.anything(),
    );
  });
});
