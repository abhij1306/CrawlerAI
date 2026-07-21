import { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/api/query-keys';
import * as api from '@/api/ai-visibility';
import type {
  AiVisibilityProjectCreate,
  AiVisibilityProviderId,
  CompetitorInput,
  PromptInput,
} from '@/api/ai-visibility';
import { getApiBaseUrl } from '@/api/client';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { AppDialog, ConfirmDialog } from '../../components/ui/dialog';
import { Dropdown } from '../../components/ui/dropdown';
import { HistoryDrawer } from '../../components/ui/history-drawer';
import { Field } from '../../components/ui/field';
import { Input, Textarea } from '../../components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { DomainWorkspace } from './domain-workspace';

// --------------------------------------------------------------------------
// Create-project form model
// --------------------------------------------------------------------------
type PromptRow = { text: string; theme: string; intent: string };
type CompetitorRow = { name: string; aliases: string; domains: string };

type ProjectForm = {
  name: string;
  brand_name: string;
  brand_aliases: string;
  owned_domains: string;
  unintended_domains: string;
  country_code: string;
  language_code: string;
  benchmark_mode: 'consumer_like' | 'controlled_localized' | 'forced_grounded';
  default_repetitions: number;
  prompts: PromptRow[];
  competitors: CompetitorRow[];
};

const EMPTY_PROMPT: PromptRow = { text: '', theme: '', intent: '' };
const EMPTY_COMPETITOR: CompetitorRow = { name: '', aliases: '', domains: '' };

const BENCHMARK_MODE_OPTIONS: Array<{ value: ProjectForm['benchmark_mode']; label: string }> = [
  { value: 'controlled_localized', label: 'Controlled localized' },
  { value: 'consumer_like', label: 'Consumer-like' },
  { value: 'forced_grounded', label: 'Forced grounded diagnostic' },
];

const PROMPT_INTENT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'No intent' },
  { value: 'discovery', label: 'Discovery' },
  { value: 'comparison', label: 'Comparison' },
  { value: 'purchase', label: 'Purchase' },
  { value: 'service', label: 'Service' },
  { value: 'local', label: 'Local' },
];

const EMPTY_FORM: ProjectForm = {
  name: '',
  brand_name: '',
  brand_aliases: '',
  owned_domains: '',
  unintended_domains: '',
  country_code: 'AU',
  language_code: 'en-AU',
  benchmark_mode: 'controlled_localized',
  default_repetitions: 3,
  prompts: [{ ...EMPTY_PROMPT }],
  competitors: [],
};

const csvToList = (value: string): string[] =>
  value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);

const presetToForm = (preset: AiVisibilityProjectCreate): ProjectForm => ({
  name: preset.name,
  brand_name: preset.brand_name,
  brand_aliases: (preset.brand_aliases ?? []).join(', '),
  owned_domains: (preset.owned_domains ?? []).join(', '),
  unintended_domains: (preset.unintended_domains ?? []).join(', '),
  country_code: preset.country_code ?? 'AU',
  language_code: preset.language_code ?? 'en-AU',
  benchmark_mode: preset.benchmark_mode ?? 'controlled_localized',
  default_repetitions: preset.default_repetitions ?? 3,
  prompts: (preset.prompts ?? []).map((prompt) => ({
    text: prompt.text,
    theme: prompt.theme ?? '',
    intent: prompt.intent ?? '',
  })),
  competitors: (preset.competitors ?? []).map((competitor) => ({
    name: competitor.name,
    aliases: competitor.aliases.join(', '),
    domains: competitor.domains.join(', '),
  })),
});

function formToPayload(form: ProjectForm): AiVisibilityProjectCreate {
  const prompts: PromptInput[] = form.prompts
    .filter((row) => row.text.trim())
    .map((row) => ({
      text: row.text.trim(),
      theme: row.theme.trim() || undefined,
      intent: row.intent.trim() || undefined,
    }));

  const competitors: CompetitorInput[] = form.competitors
    .filter((row) => row.name.trim())
    .map((row) => ({
      name: row.name.trim(),
      aliases: csvToList(row.aliases),
      domains: csvToList(row.domains),
    }));

  return {
    name: form.name.trim(),
    brand_name: form.brand_name.trim(),
    brand_aliases: csvToList(form.brand_aliases),
    owned_domains: csvToList(form.owned_domains),
    unintended_domains: csvToList(form.unintended_domains),
    competitors,
    country_code: form.country_code.trim() || 'AU',
    language_code: form.language_code.trim() || 'en',
    benchmark_mode: form.benchmark_mode,
    prompts,
    default_repetitions: Math.max(1, form.default_repetitions || 1),
  };
}

// --------------------------------------------------------------------------
// Page
// --------------------------------------------------------------------------
export default function AiVisibilityPage() {
  const queryClient = useQueryClient();
  const [activeRunId, setActiveRunId] = useState<number | null>(null);
  const [selectedExecutionId, setSelectedExecutionId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<ProjectForm>(EMPTY_FORM);
  const [repetitions, setRepetitions] = useState(3);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyProjectId, setHistoryProjectId] = useState<number | null>(null);
  const [deleteRunId, setDeleteRunId] = useState<number | null>(null);
  const [cancelRunId, setCancelRunId] = useState<number | null>(null);

  // Provider status
  const { data: providers } = useQuery({
    queryKey: queryKeys.aiVisibility.providers(),
    queryFn: api.getProviders,
  });

  const { data: bestAndLessPreset } = useQuery({
    queryKey: ['ai-visibility', 'presets', 'best-and-less'],
    queryFn: api.getBestAndLessPreset,
  });

  // Projects list
  const { data: projects = [] } = useQuery({
    queryKey: queryKeys.aiVisibility.projects(),
    queryFn: () => api.listProjects(),
  });

  const { data: savedRuns = [] } = useQuery({
    queryKey: queryKeys.aiVisibility.runs(),
    queryFn: () => api.listRuns(undefined, 100),
  });

  // Create project mutation
  const createProjectMutation = useMutation({
    mutationFn: api.createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.projects() });
      setFormOpen(false);
      setForm(EMPTY_FORM);
    },
  });

  // Create run mutation
  const createRunMutation = useMutation({
    mutationFn: ({
      openReport: _openReport,
      ...payload
    }: api.AiVisibilityRunCreate & {
      openReport: boolean;
    }) => api.createRun(payload),
    onSuccess: (run, variables) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.runs() });
      if (variables.openReport) setActiveRunId(run.id);
    },
  });

  const updateProjectMutation = useMutation({
    mutationFn: ({ projectId, prompts }: { projectId: number; prompts: PromptInput[] }) =>
      api.updateProject(projectId, { prompts }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.projects() }),
  });

  const deleteRunMutation = useMutation({
    mutationFn: api.deleteRun,
    onSuccess: (_result, runId) => {
      if (activeRunId === runId) setActiveRunId(null);
      setDeleteRunId(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.runs() });
    },
  });

  const cancelRunMutation = useMutation({
    mutationFn: api.cancelRun,
    onSuccess: (_result, runId) => {
      setCancelRunId(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.runs() });
      queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.run(runId) });
    },
  });

  // Active run detail (with polling)
  const { data: runDetail } = useQuery({
    queryKey: queryKeys.aiVisibility.run(activeRunId!),
    queryFn: () => api.getRun(activeRunId!),
    enabled: activeRunId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.run.status;
      return status === 'running' || status === 'pending' ? 2000 : false;
    },
  });

  // Selected execution detail
  const { data: executionDetail } = useQuery({
    queryKey: queryKeys.aiVisibility.execution(selectedExecutionId!),
    queryFn: () => api.getExecution(selectedExecutionId!),
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
  const showSummary =
    run && (run.status === 'completed' || run.status === 'degraded') && run.summary;

  const canSubmit = form.name.trim() && form.brand_name.trim();

  const handleSubmit = () => {
    if (!canSubmit) return;
    createProjectMutation.mutate(formToPayload(form));
  };

  useEffect(() => {
    if (run && ['completed', 'degraded', 'failed'].includes(run.status)) {
      queryClient.invalidateQueries({ queryKey: queryKeys.aiVisibility.runs() });
    }
  }, [queryClient, run]);

  const handleRunBenchmark = ({
    projectId,
    repetitions: reps,
    provider,
    promptIndices,
    openReport,
  }: {
    projectId: number;
    repetitions: number;
    provider: AiVisibilityProviderId;
    promptIndices?: number[];
    openReport: boolean;
  }) => {
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

  // Form field helpers ------------------------------------------------------
  const setField = <K extends keyof ProjectForm>(key: K, value: ProjectForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const updatePrompt = (index: number, patch: Partial<PromptRow>) =>
    setForm((prev) => ({
      ...prev,
      prompts: prev.prompts.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    }));

  const updateCompetitor = (index: number, patch: Partial<CompetitorRow>) =>
    setForm((prev) => ({
      ...prev,
      competitors: prev.competitors.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    }));

  return (
    <div className="page-stack-lg">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-divider bg-background-alt px-3 py-2">
        <span className="type-caption mr-1 text-muted">Providers</span>
        {(providers ?? []).map((item) => (
          <span
            key={item.provider}
            className="type-body-sm flex items-center gap-1.5 text-secondary"
          >
            <span className={item.configured ? 'text-success' : 'text-danger'}>●</span>
            {item.label}
          </span>
        ))}
      </div>

      <section className="page-stack">
        <div className="flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h2 className="type-subheading text-foreground">Domains & Prompt Panels</h2>
            <p className="type-body-sm text-muted">
              Edit prompts in place. Run one prompt or the full saved panel.
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setHistoryProjectId(null);
              setHistoryOpen(true);
            }}
          >
            <History className="size-3.5" /> Report history ({savedRuns.length})
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setForm(EMPTY_FORM);
              setFormOpen(true);
            }}
          >
            New Domain
          </Button>
        </div>

        {projects.length === 0 ? (
          <Card className="p-4">
            <p className="type-body text-muted">No projects yet. Create one to get started.</p>
          </Card>
        ) : (
          <div className="grid gap-3">
            {projects.map((project) => (
              <DomainWorkspace
                key={project.id}
                project={project}
                providers={providers ?? []}
                historyCount={savedRuns.filter((item) => item.project_id === project.id).length}
                runPending={createRunMutation.isPending}
                savePending={updateProjectMutation.isPending}
                onSavePrompts={(projectId, prompts) =>
                  updateProjectMutation.mutate({ projectId, prompts })
                }
                onRun={handleRunBenchmark}
                onOpenHistory={(projectId) => {
                  setHistoryProjectId(projectId);
                  setHistoryOpen(true);
                }}
              />
            ))}
          </div>
        )}
      </section>

      {/* Active Run */}
      {run && (
        <section className="page-stack">
          <div className="flex items-center gap-3">
            <h2 className="type-subheading text-foreground">Run #{run.id}</h2>
            <label htmlFor="rerun-reps" className="type-body-sm flex items-center gap-2 text-muted">
              Reps
              <Input
                id="rerun-reps"
                type="number"
                min={1}
                value={repetitions}
                onChange={(e) => setRepetitions(Math.max(1, Number(e.target.value) || 1))}
                className="h-8 w-16"
              />
            </label>
            <Button
              variant="secondary"
              size="sm"
              onClick={() =>
                handleRunBenchmark({
                  projectId: run.project_id,
                  repetitions,
                  provider: run.provider,
                  openReport: true,
                })
              }
              disabled={
                createRunMutation.isPending ||
                !providers?.find((item) => item.provider === run.provider)?.configured
              }
            >
              Re-run
            </Button>
          </div>

          <Card className="p-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Status">
                <Badge tone={statusTone(run.status)}>{run.status}</Badge>
              </Stat>
              <Stat label="Progress">
                <span className="type-metric text-foreground">
                  {completedCount + failedCount} / {run.requested_count}
                </span>
              </Stat>
              <Stat label="Failed">
                <span
                  className={`type-metric ${failedCount > 0 ? 'text-danger' : 'text-foreground'}`}
                >
                  {failedCount}
                </span>
              </Stat>
              <Stat label="Model">
                <span className="type-body-sm text-secondary">{run.model}</span>
              </Stat>
            </div>

            {showSummary && (
              <div className="mt-4 rounded-lg border border-border bg-background-alt p-4">
                <h4 className="type-label text-foreground">Summary</h4>
                <div className="type-body-sm mt-3 grid grid-cols-1 gap-3 text-secondary sm:grid-cols-3">
                  <div>
                    Brand mention rate:{' '}
                    <strong className="text-foreground">
                      {pct(run.summary.brand_mention_rate)}
                    </strong>
                  </div>
                  <div>
                    Owned citation rate:{' '}
                    <strong className="text-foreground">
                      {pct(run.summary.owned_citation_rate)}
                    </strong>
                  </div>
                  <div>
                    Search use rate:{' '}
                    <strong className="text-foreground">{pct(run.summary.search_use_rate)}</strong>
                  </div>
                  <div>
                    Tokens used:{' '}
                    <strong className="text-foreground">
                      {tokenTotal(run.summary.token_usage)}
                    </strong>
                  </div>
                  <div>
                    Grounded requests:{' '}
                    <strong className="text-foreground">
                      {costValue(run.summary.cost, 'grounded_requests').toLocaleString()}
                    </strong>
                  </div>
                </div>
                <div className="mt-3 flex gap-4">
                  <a
                    className="link-accent type-body-sm no-underline hover:underline"
                    href={`${getApiBaseUrl()}${api.getExportCsvUrl(run.id)}`}
                    download
                  >
                    Download CSV
                  </a>
                  <a
                    className="link-accent type-body-sm no-underline hover:underline"
                    href={`${getApiBaseUrl()}${api.getExportMarkdownUrl(run.id)}`}
                    download
                  >
                    Download Markdown
                  </a>
                </div>
              </div>
            )}

            {/* Executions Table */}
            <div className="mt-4">
              <h4 className="type-label mb-2 text-foreground">Executions</h4>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Prompt</TableHead>
                    <TableHead className="text-center">Rep</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                    <TableHead className="text-center">Search</TableHead>
                    <TableHead className="text-center">Brand</TableHead>
                    <TableHead className="text-center">Owned</TableHead>
                    <TableHead className="text-center">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {executions.map((exec) => (
                    <TableRow key={exec.id}>
                      <TableCell>{exec.prompt_text_snapshot}</TableCell>
                      <TableCell className="text-center">{exec.repetition}</TableCell>
                      <TableCell className="text-center">
                        <Badge tone={statusTone(exec.status)} flat>
                          {exec.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-center">
                        <Mark on={exec.search_used} />
                      </TableCell>
                      <TableCell className="text-center">
                        <Mark on={Boolean(exec.score?.brand_mentioned)} />
                      </TableCell>
                      <TableCell className="text-center">
                        <Mark on={Boolean(exec.score?.owned_domain_cited)} />
                      </TableCell>
                      <TableCell className="text-center">
                        {['completed', 'failed'].includes(exec.status) && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setSelectedExecutionId(exec.id)}
                          >
                            View
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </section>
      )}

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={activeRunId}
        onSelect={(runId) => setActiveRunId(runId)}
        onDelete={(runId) => setDeleteRunId(runId)}
        onCancel={(runId) => setCancelRunId(runId)}
        title={
          historyProjectId
            ? `${projects.find((project) => project.id === historyProjectId)?.name ?? 'Domain'} reports`
            : 'AI Visibility Reports'
        }
      />

      <ConfirmDialog
        open={deleteRunId !== null}
        onOpenChange={(open) => !open && setDeleteRunId(null)}
        title="Delete saved report?"
        description="This permanently removes the benchmark run and every stored execution."
        confirmLabel="Delete report"
        danger
        pending={deleteRunMutation.isPending}
        onConfirm={() => deleteRunId !== null && deleteRunMutation.mutate(deleteRunId)}
      />

      <ConfirmDialog
        open={cancelRunId !== null}
        onOpenChange={(open) => !open && setCancelRunId(null)}
        title="Stop this run?"
        description="This cancels the run and marks its unfinished executions cancelled. Any live worker stops after its current execution. Use this to clear runs stuck on 'running'."
        confirmLabel="Kill run"
        danger
        pending={cancelRunMutation.isPending}
        onConfirm={() => cancelRunId !== null && cancelRunMutation.mutate(cancelRunId)}
      />

      {/* Create Project dialog */}
      <AppDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        title="New Project"
        description="Define the brand, owned domains, competitors, and prompts to benchmark."
        className="w-[760px]"
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => bestAndLessPreset && setForm(presetToForm(bestAndLessPreset))}
              disabled={!bestAndLessPreset}
              type="button"
            >
              Prefill sample
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setFormOpen(false)} type="button">
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSubmit}
              disabled={!canSubmit || createProjectMutation.isPending}
            >
              {createProjectMutation.isPending ? 'Creating…' : 'Create Project'}
            </Button>
          </>
        }
      >
        <div className="page-stack p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Project name">
              <Input
                value={form.name}
                onChange={(e) => setField('name', e.target.value)}
                placeholder="Best&Less AI Visibility"
              />
            </Field>
            <Field label="Brand name">
              <Input
                value={form.brand_name}
                onChange={(e) => setField('brand_name', e.target.value)}
                placeholder="Best&Less"
              />
            </Field>
            <Field label="Brand aliases" hint="Comma-separated">
              <Input
                value={form.brand_aliases}
                onChange={(e) => setField('brand_aliases', e.target.value)}
                placeholder="Best & Less, Best and Less"
              />
            </Field>
            <Field label="Owned domains" hint="Comma-separated">
              <Input
                value={form.owned_domains}
                onChange={(e) => setField('owned_domains', e.target.value)}
                placeholder="bestandless.com.au"
              />
            </Field>
            <Field label="Unintended domains" hint="Optional, comma-separated">
              <Input
                value={form.unintended_domains}
                onChange={(e) => setField('unintended_domains', e.target.value)}
                placeholder="bestandless.zendesk.com"
              />
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Country">
                <Input
                  value={form.country_code}
                  onChange={(e) => setField('country_code', e.target.value)}
                />
              </Field>
              <Field label="Lang">
                <Input
                  value={form.language_code}
                  onChange={(e) => setField('language_code', e.target.value)}
                />
              </Field>
              <Field label="Reps">
                <Input
                  type="number"
                  min={1}
                  value={form.default_repetitions}
                  onChange={(e) =>
                    setField('default_repetitions', Math.max(1, Number(e.target.value) || 1))
                  }
                />
              </Field>
            </div>
            <Field
              label="Benchmark mode"
              hint="Localized mode supplies disclosed market context. Consumer-like sends exact prompts."
            >
              <Dropdown
                ariaLabel="Benchmark mode"
                value={form.benchmark_mode}
                options={BENCHMARK_MODE_OPTIONS}
                onChange={(value) => setField('benchmark_mode', value)}
              />
            </Field>
          </div>

          {/* Prompts */}
          <div className="page-stack">
            <div className="flex items-center justify-between">
              <span className="field-label">Prompts</span>
              <Button
                variant="ghost"
                size="sm"
                type="button"
                onClick={() => setField('prompts', [...form.prompts, { ...EMPTY_PROMPT }])}
              >
                + Add prompt
              </Button>
            </div>
            <div className="grid gap-2">
              {form.prompts.map((row, index) => (
                <div
                  key={index}
                  className="grid grid-cols-[1fr_auto] items-start gap-2 rounded-lg border border-border bg-background-alt p-2"
                >
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1.5fr_1fr_1fr]">
                    <Input
                      value={row.text}
                      onChange={(e) => updatePrompt(index, { text: e.target.value })}
                      placeholder="prompt text"
                    />
                    <Input
                      value={row.theme}
                      onChange={(e) => updatePrompt(index, { theme: e.target.value })}
                      placeholder="theme"
                    />
                    <Dropdown
                      ariaLabel="Prompt intent"
                      value={row.intent}
                      options={PROMPT_INTENT_OPTIONS}
                      onChange={(value) => updatePrompt(index, { intent: value })}
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    type="button"
                    aria-label="Remove prompt"
                    disabled={form.prompts.length === 1}
                    onClick={() =>
                      setField(
                        'prompts',
                        form.prompts.filter((_, i) => i !== index),
                      )
                    }
                  >
                    ×
                  </Button>
                </div>
              ))}
            </div>
          </div>

          {/* Competitors */}
          <div className="page-stack">
            <div className="flex items-center justify-between">
              <span className="field-label">Competitors</span>
              <Button
                variant="ghost"
                size="sm"
                type="button"
                onClick={() =>
                  setField('competitors', [...form.competitors, { ...EMPTY_COMPETITOR }])
                }
              >
                + Add competitor
              </Button>
            </div>
            {form.competitors.length === 0 ? (
              <p className="type-body-sm text-muted">None. Optional.</p>
            ) : (
              <div className="grid gap-2">
                {form.competitors.map((row, index) => (
                  <div
                    key={index}
                    className="grid grid-cols-[1fr_auto] items-start gap-2 rounded-lg border border-border bg-background-alt p-2"
                  >
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      <Input
                        value={row.name}
                        onChange={(e) => updateCompetitor(index, { name: e.target.value })}
                        placeholder="name"
                      />
                      <Input
                        value={row.aliases}
                        onChange={(e) => updateCompetitor(index, { aliases: e.target.value })}
                        placeholder="aliases (csv)"
                      />
                      <Input
                        value={row.domains}
                        onChange={(e) => updateCompetitor(index, { domains: e.target.value })}
                        placeholder="domains (csv)"
                      />
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      type="button"
                      aria-label="Remove competitor"
                      onClick={() =>
                        setField(
                          'competitors',
                          form.competitors.filter((_, i) => i !== index),
                        )
                      }
                    >
                      ×
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </AppDialog>

      {/* Execution Detail dialog */}
      <AppDialog
        open={selectedExecutionId !== null}
        onOpenChange={(open) => !open && setSelectedExecutionId(null)}
        title={executionDetail ? `Execution #${executionDetail.id}` : 'Execution'}
      >
        {executionDetail && (
          <div className="page-stack p-4">
            <div>
              <span className="field-label">Prompt</span>
              <p className="type-body mt-1 text-secondary">
                {executionDetail.prompt_text_snapshot}
              </p>
            </div>

            <div>
              <span className="field-label">Answer</span>
              <div className="type-body-sm mt-1 rounded-lg border border-border bg-background-alt p-3 whitespace-pre-wrap text-secondary">
                {executionDetail.answer_text || '(No answer)'}
              </div>
            </div>

            {executionDetail.error_code ? (
              <div className="rounded-md border border-danger/20 bg-danger/10 p-3 text-sm text-danger">
                <strong>{executionDetail.error_code}</strong>
                {executionDetail.error_message ? ` — ${executionDetail.error_message}` : ''}
              </div>
            ) : null}

            {executionDetail.search_events && executionDetail.search_events.length > 0 && (
              <div>
                <span className="field-label">Search queries</span>
                {executionDetail.search_events.some((event) => event.query?.trim()) ? (
                  <ul className="type-body-sm mt-1 list-disc pl-5 text-secondary">
                    {executionDetail.search_events
                      .filter((event) => event.query?.trim())
                      .map((event, idx) => (
                        <li key={idx}>{event.query}</li>
                      ))}
                  </ul>
                ) : (
                  <p className="type-body-sm mt-1 text-secondary">
                    {executionDetail.search_events.length} web{' '}
                    {executionDetail.search_events.length === 1 ? 'search' : 'searches'} run (this
                    provider does not expose the query text).
                  </p>
                )}
              </div>
            )}

            {executionDetail.citations && executionDetail.citations.length > 0 && (
              <div>
                <span className="field-label">Citations</span>
                <ul className="type-body-sm mt-1 list-disc pl-5 text-secondary">
                  {executionDetail.citations.map((citation, idx) => (
                    <li key={idx}>
                      {String(citation.domain ?? '')} — {String(citation.title ?? '')}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <span className="field-label">Score</span>
              <Textarea
                readOnly
                value={JSON.stringify(executionDetail.score, null, 2)}
                className="mt-1 h-40 font-mono text-xs"
              />
            </div>
          </div>
        )}
      </AppDialog>
    </div>
  );
}

// --------------------------------------------------------------------------
// Small presentational helpers
// --------------------------------------------------------------------------
function Stat({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div>
      <div className="type-caption text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function Mark({ on }: Readonly<{ on: boolean }>) {
  return on ? <span className="text-success">✓</span> : <span className="text-muted">—</span>;
}

function pct(value: unknown): string {
  const n = typeof value === 'number' ? value : 0;
  return `${(n * 100).toFixed(0)}%`;
}

// Render total tokens with input/output breakdown, e.g. "12,720 (in 150 / out 7,875)".
function tokenTotal(value: unknown): string {
  const usage = (value ?? {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === 'number' ? v : 0);
  const total = num(usage.total_tokens);
  const input = num(usage.input_tokens);
  const output = num(usage.output_tokens);
  if (total === 0 && input === 0 && output === 0) return '—';
  const fmt = (n: number) => n.toLocaleString();
  return `${fmt(total)} (in ${fmt(input)} / out ${fmt(output)})`;
}

function costValue(value: unknown, key: string): number {
  const cost = (value ?? {}) as Record<string, unknown>;
  return typeof cost[key] === 'number' ? cost[key] : 0;
}

function statusTone(
  status: string,
): 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info' {
  switch (status) {
    case 'completed':
      return 'success';
    case 'running':
      return 'accent';
    case 'degraded':
      return 'warning';
    case 'cancelled':
      return 'warning';
    case 'failed':
      return 'danger';
    default:
      return 'neutral';
  }
}
