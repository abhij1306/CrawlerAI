import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vite-plus/test';

import type {
  AiVisibilityExecution,
  AiVisibilityProject,
  AiVisibilityProviderStatus,
  AiVisibilityRun,
} from '../../lib/api/ai-visibility';
import AiVisibilityPage from './page-view';

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
  getAiVisibilityExportCsvUrl: vi.fn(
    (runId: number) => `/api/ai-visibility/runs/${runId}/export.csv`,
  ),
  getAiVisibilityExportMarkdownUrl: vi.fn(
    (runId: number) => `/api/ai-visibility/runs/${runId}/export.md`,
  ),
}));

vi.mock('../../lib/api/ai-visibility', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/ai-visibility')>();
  return { ...actual, aiVisibilityApi: apiMock };
});

const PROVIDERS: AiVisibilityProviderStatus[] = [
  {
    provider: 'gemini',
    label: 'Gemini',
    surface: 'ai_search',
    configured: true,
    model: 'gemini-2.5-flash',
    supports_search_fanout: true,
    supports_citations: true,
  },
  {
    provider: 'anthropic',
    label: 'Anthropic',
    surface: 'ai_search',
    configured: false,
    model: 'claude-sonnet',
    supports_search_fanout: true,
    supports_citations: true,
  },
];

const PROJECT: AiVisibilityProject = {
  id: 1,
  name: 'Best&Less AI Visibility',
  brand_name: 'Best&Less',
  brand_aliases: ['Best & Less'],
  owned_domains: ['bestandless.com.au'],
  unintended_domains: [],
  competitors: [],
  country_code: 'AU',
  language_code: 'en-AU',
  benchmark_mode: 'controlled_localized',
  prompts: [{ text: 'best kids clothes', theme: 'kids', intent: 'purchase' }],
  default_repetitions: 3,
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
};

const COMPLETED_RUN: AiVisibilityRun = {
  id: 42,
  project_id: 1,
  status: 'completed',
  provider: 'gemini',
  model: 'gemini-2.5-flash',
  repetitions: 3,
  random_seed: 'seed',
  configuration: {},
  summary: {
    brand_mention_rate: 0.5,
    owned_citation_rate: 0.25,
    search_use_rate: 1,
    token_usage: { total_tokens: 12720, input_tokens: 150, output_tokens: 7875 },
    cost: { grounded_requests: 3 },
  },
  requested_count: 3,
  completed_count: 3,
  failed_count: 0,
  error_message: '',
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:05:00Z',
  completed_at: '2026-07-01T00:05:00Z',
};

const EXECUTION: AiVisibilityExecution = {
  id: 7,
  run_id: 42,
  prompt_index: 0,
  prompt_text_snapshot: 'best kids clothes',
  prompt_theme_snapshot: 'kids',
  prompt_intent_snapshot: 'purchase',
  repetition: 1,
  randomized_position: 0,
  status: 'completed',
  answer_text: 'Best&Less is a great option.',
  search_used: true,
  search_events: [{ sequence: 1, query: 'best kids clothes australia' }],
  citations: [{ domain: 'bestandless.com.au', title: 'Best&Less Kids' }],
  score: { brand_mentioned: true, owned_domain_cited: true },
  request_snapshot: {},
  provider_metadata: {},
  error_code: '',
  error_message: '',
  latency_ms: 120,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AiVisibilityPage />
    </QueryClientProvider>,
  );
}

describe('AiVisibilityPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.listAiVisibilityProviders.mockResolvedValue(PROVIDERS);
    apiMock.getBestAndLessPreset.mockResolvedValue({
      name: 'Sample Project',
      brand_name: 'Sample Brand',
    });
    apiMock.listAiVisibilityProjects.mockResolvedValue([PROJECT]);
    apiMock.listAiVisibilityRuns.mockResolvedValue([COMPLETED_RUN]);
    apiMock.getAiVisibilityRun.mockResolvedValue({
      run: COMPLETED_RUN,
      executions: [EXECUTION],
    });
    apiMock.getAiVisibilityExecution.mockResolvedValue(EXECUTION);
  });

  it('renders provider status and project workspaces', async () => {
    renderPage();

    expect(await screen.findByText('Gemini')).toBeInTheDocument();
    expect(screen.getByText('Anthropic')).toBeInTheDocument();
    expect(await screen.findByText('bestandless.com.au')).toBeInTheDocument();
    expect(screen.getByText(/1 prompts · 1 saved reports/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Report history \(1\)/ })).toBeInTheDocument();
  });

  it('shows an empty state when there are no projects', async () => {
    apiMock.listAiVisibilityProjects.mockResolvedValue([]);
    apiMock.listAiVisibilityRuns.mockResolvedValue([]);
    renderPage();

    expect(
      await screen.findByText('No projects yet. Create one to get started.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Report history \(0\)/ })).toBeInTheDocument();
  });

  it('creates a project from the New Domain dialog', async () => {
    apiMock.createAiVisibilityProject.mockResolvedValue(PROJECT);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'New Domain' }));
    fireEvent.change(screen.getByLabelText('Project name'), {
      target: { value: 'New Domain Project' },
    });
    fireEvent.change(screen.getByLabelText('Brand name'), { target: { value: 'New Brand' } });
    fireEvent.change(screen.getByPlaceholderText('prompt text'), {
      target: { value: 'best school uniforms' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));

    await waitFor(() =>
      expect(apiMock.createAiVisibilityProject).toHaveBeenCalledWith(
        {
          name: 'New Domain Project',
          brand_name: 'New Brand',
          brand_aliases: [],
          owned_domains: [],
          unintended_domains: [],
          competitors: [],
          country_code: 'AU',
          language_code: 'en-AU',
          benchmark_mode: 'controlled_localized',
          prompts: [{ text: 'best school uniforms', theme: undefined, intent: undefined }],
          default_repetitions: 3,
        },
        expect.anything(),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Create Project' })).not.toBeInTheDocument(),
    );
  });

  it('opens a saved report from history and renders the run report', async () => {
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Report history \(1\)/ }));
    fireEvent.click(await screen.findByText('#42'));

    expect(await screen.findByRole('heading', { name: 'Run #42' })).toBeInTheDocument();
    expect(screen.getAllByText('Completed').length).toBeGreaterThan(0);
    expect(screen.getByText('3 / 3')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText('25%')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByText('12,720 (in 150 / out 7,875)')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Download CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('/api/ai-visibility/runs/42/export.csv'),
    );
    expect(screen.getByText('best kids clothes')).toBeInTheDocument();
  });

  it('opens the execution detail dialog from the report table', async () => {
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Report history \(1\)/ }));
    fireEvent.click(await screen.findByText('#42'));
    fireEvent.click(await screen.findByRole('button', { name: 'View' }));

    expect(await screen.findByText('Execution #7')).toBeInTheDocument();
    expect(screen.getByText('Best&Less is a great option.')).toBeInTheDocument();
    expect(screen.getByText('best kids clothes australia')).toBeInTheDocument();
    expect(screen.getAllByText(/^bestandless\.com\.au$/).length).toBeGreaterThan(0);
  });
});
