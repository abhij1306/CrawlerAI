import { startTransition, useEffect, useReducer, useState } from 'react';
import { CheckCircle2, PlugZap, Plus, Trash2 } from 'lucide-react';

import { Button, Dropdown, Field, Input } from '../../../components/ui/primitives';
import {
  DetailRow,
  InlineAlert,
  MutedPanelMessage,
  PageHeader,
  SectionCard,
} from '../../../components/ui/patterns';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
  TableCell,
} from '../../../components/ui/table';
import { api } from '../../../lib/api';
import type {
  LlmConfigCreatePayload,
  LlmConfigRecord,
  LlmCostLogRecord,
  LlmProviderCatalogItem,
} from '../../../lib/api/types';

const CUSTOM_MODEL_OPTION = '__custom__';
const TASK_TYPES = [
  'general',
  'xpath_discovery',
  'page_classification',
  'schema_inference',
  'data_enrichment_semantic',
];

const INITIAL_LLM_FORM: LlmConfigCreatePayload = {
  provider: 'mistral',
  model: 'mistral-small-latest',
  task_type: 'xpath_discovery',
  api_key: '',
  per_domain_daily_budget_usd: '0',
  global_session_budget_usd: '0',
  is_active: true,
};

type AdminLlmState = {
  providers: LlmProviderCatalogItem[];
  configs: LlmConfigRecord[];
  costLog: LlmCostLogRecord[];
  customModelSelected: boolean;
  error: string;
  message: string;
  saving: boolean;
  testing: boolean;
  form: LlmConfigCreatePayload;
};

type AdminLlmAction =
  | {
      type: 'initialLoaded';
      providers: LlmProviderCatalogItem[];
      configs: LlmConfigRecord[];
      costLog: LlmCostLogRecord[];
    }
  | { type: 'runtimeLoaded'; configs: LlmConfigRecord[]; costLog: LlmCostLogRecord[] }
  | { type: 'patchForm'; patch: Partial<LlmConfigCreatePayload> }
  | { type: 'setCustomModelSelected'; selected: boolean }
  | { type: 'startSave' }
  | { type: 'saveSucceeded' }
  | { type: 'finishSave' }
  | { type: 'startTest' }
  | { type: 'testSucceeded'; message: string }
  | { type: 'finishTest' }
  | { type: 'deleteStarted' }
  | { type: 'deleteSucceeded' }
  | { type: 'failed'; message: string };

const INITIAL_ADMIN_LLM_STATE: AdminLlmState = {
  providers: [],
  configs: [],
  costLog: [],
  customModelSelected: false,
  error: '',
  message: '',
  saving: false,
  testing: false,
  form: INITIAL_LLM_FORM,
};

function alignFormToProviders(
  current: LlmConfigCreatePayload,
  providers: LlmProviderCatalogItem[],
): LlmConfigCreatePayload {
  if (providers.length === 0) {
    return current;
  }
  const fallbackProvider = providers[0];
  const matchingProvider = providers.find((provider) => provider.provider === current.provider);
  if (matchingProvider) {
    if (current.model.trim()) {
      return current;
    }
    return {
      ...current,
      model: matchingProvider.recommended_models[0] ?? current.model,
    };
  }
  return {
    ...current,
    provider: fallbackProvider?.provider ?? current.provider,
    model: fallbackProvider?.recommended_models[0] ?? current.model,
  };
}

function adminLlmReducer(state: AdminLlmState, action: AdminLlmAction): AdminLlmState {
  switch (action.type) {
    case 'initialLoaded':
      return {
        ...state,
        providers: action.providers,
        configs: action.configs,
        costLog: action.costLog,
        customModelSelected: false,
        form: alignFormToProviders(state.form, action.providers),
      };
    case 'runtimeLoaded':
      return { ...state, configs: action.configs, costLog: action.costLog };
    case 'patchForm':
      return { ...state, form: { ...state.form, ...action.patch } };
    case 'setCustomModelSelected':
      return { ...state, customModelSelected: action.selected };
    case 'startSave':
      return { ...state, saving: true, error: '', message: '' };
    case 'saveSucceeded':
      return { ...state, message: 'LLM config saved.', form: { ...state.form, api_key: '' } };
    case 'finishSave':
      return { ...state, saving: false };
    case 'startTest':
      return { ...state, testing: true, error: '', message: '' };
    case 'testSucceeded':
      return { ...state, message: action.message };
    case 'finishTest':
      return { ...state, testing: false };
    case 'deleteStarted':
      return { ...state, error: '', message: '' };
    case 'deleteSucceeded':
      return { ...state, message: 'LLM config removed.' };
    case 'failed':
      return { ...state, error: action.message };
  }
}

// skipcq: JS-0067
export default function AdminLlmPage() {
  const [state, dispatch] = useReducer(adminLlmReducer, INITIAL_ADMIN_LLM_STATE);
  const {
    providers,
    configs,
    costLog,
    customModelSelected,
    error,
    message,
    saving,
    testing,
    form,
  } = state;
  // Client-only "now" so today/yesterday labels don't differ between server and client render.
  const [nowMs, setNowMs] = useState<number | null>(null);
  useEffect(() => {
    const timeoutId = window.setTimeout(() => setNowMs(Date.now()), 0);
    return () => window.clearTimeout(timeoutId);
  }, []);
  async function refreshRuntimeState() {
    try {
      const [nextConfigs, nextCostLog] = await Promise.all([
        api.listLlmConfigs({ include_unsupported: true }),
        api.listLlmCostLog(),
      ]);
      startTransition(() => {
        dispatch({ type: 'runtimeLoaded', configs: nextConfigs, costLog: nextCostLog });
      });
    } catch (nextError) {
      dispatch({
        type: 'failed',
        message: nextError instanceof Error ? nextError.message : 'Unable to load LLM settings.',
      });
    }
  }

  async function handleSave() {
    dispatch({ type: 'startSave' });
    try {
      await api.createLlmConfig(form);
      dispatch({ type: 'saveSucceeded' });
      await refreshRuntimeState();
    } catch (nextError) {
      dispatch({
        type: 'failed',
        message: nextError instanceof Error ? nextError.message : 'Unable to save LLM config.',
      });
    } finally {
      dispatch({ type: 'finishSave' });
    }
  }

  async function handleTest() {
    dispatch({ type: 'startTest' });
    try {
      const response = await api.testLlmConnection({
        provider: form.provider,
        model: form.model,
        api_key: form.api_key,
      });
      dispatch({ type: 'testSucceeded', message: response.message });
    } catch (nextError) {
      dispatch({
        type: 'failed',
        message: nextError instanceof Error ? nextError.message : 'Connection test failed.',
      });
    } finally {
      dispatch({ type: 'finishTest' });
    }
  }

  async function handleDelete(configId: number) {
    dispatch({ type: 'deleteStarted' });
    try {
      await api.deleteLlmConfig(configId);
      dispatch({ type: 'deleteSucceeded' });
      await refreshRuntimeState();
    } catch (nextError) {
      dispatch({
        type: 'failed',
        message: nextError instanceof Error ? nextError.message : 'Unable to delete LLM config.',
      });
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const [nextProviders, nextConfigs, nextCostLog] = await Promise.all([
          api.listLlmProviders(),
          api.listLlmConfigs({ include_unsupported: true }),
          api.listLlmCostLog(),
        ]);
        if (cancelled) return;
        startTransition(() => {
          dispatch({
            type: 'initialLoaded',
            providers: nextProviders,
            configs: nextConfigs,
            costLog: nextCostLog,
          });
        });
      } catch (nextError) {
        if (cancelled) return;
        dispatch({
          type: 'failed',
          message: nextError instanceof Error ? nextError.message : 'Unable to load LLM settings.',
        });
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  const recommendedModels =
    providers.find((provider) => provider.provider === form.provider)?.recommended_models ?? [];
  const modelCatalogLoaded = recommendedModels.length > 0;
  const formModel = form.model.trim();
  const modelInCatalog = recommendedModels.includes(formModel);
  const modelIsCustom =
    customModelSelected || (modelCatalogLoaded && formModel !== '' && !modelInCatalog);
  const modelDropdownValue = modelIsCustom ? CUSTOM_MODEL_OPTION : form.model;
  const modelOptions = [
    ...recommendedModels.map((model) => ({
      value: model,
      label: model,
    })),
    ...(modelCatalogLoaded || formModel === '' || modelInCatalog
      ? []
      : [{ value: formModel, label: formModel }]),
    { value: CUSTOM_MODEL_OPTION, label: 'Custom...' },
  ];
  const modelSuggestionsId = 'llm-model-suggestions';

  return (
    <div className="page-stack">
      <PageHeader
        title="LLM Config"
        description="Restore runtime provider control for selector suggestion, cleanup review, and extraction fallback tasks."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        {/* ── Left column: create form + active configs */}
        <div className="page-stack">
          <CreateConfigCard
            form={form}
            providers={providers}
            modelDropdownValue={modelDropdownValue}
            modelOptions={modelOptions}
            modelIsCustom={modelIsCustom}
            modelSuggestionsId={modelSuggestionsId}
            recommendedModels={recommendedModels}
            testing={testing}
            saving={saving}
            message={message}
            error={error}
            dispatch={dispatch}
            onTest={() => void handleTest()}
            onSave={() => void handleSave()}
          />

          <ActiveConfigsCard configs={configs} onDelete={handleDelete} />
        </div>

        {/* ── Right column: cost log */}
        <CostLogCard costLog={costLog} nowMs={nowMs} />
      </div>
    </div>
  );
}

interface CreateConfigCardProps {
  form: LlmConfigCreatePayload;
  providers: LlmProviderCatalogItem[];
  modelDropdownValue: string;
  modelOptions: { value: string; label: string }[];
  modelIsCustom: boolean;
  modelSuggestionsId: string;
  recommendedModels: string[];
  testing: boolean;
  saving: boolean;
  message: string;
  error: string;
  dispatch: React.Dispatch<AdminLlmAction>;
  onTest: () => void;
  onSave: () => void;
}

function CreateConfigCard({
  form,
  providers,
  modelDropdownValue,
  modelOptions,
  modelIsCustom,
  modelSuggestionsId,
  recommendedModels,
  testing,
  saving,
  message,
  error,
  dispatch,
  onTest,
  onSave,
}: Readonly<CreateConfigCardProps>) {
  return (
    <SectionCard
      title="Create Config"
      description="Activate one provider/model per task. New active configs automatically replace the previous active config for the same task."
      className="space-y-5"
    >
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Provider">
          <Dropdown<string>
            ariaLabel="Provider"
            value={form.provider}
            onChange={(provider) => {
              const nextModel =
                providers.find((row) => row.provider === provider)?.recommended_models?.[0] ?? '';
              dispatch({ type: 'setCustomModelSelected', selected: false });
              dispatch({
                type: 'patchForm',
                patch: {
                  provider,
                  model: nextModel || form.model,
                },
              });
            }}
            options={providers.map((provider) => ({
              value: provider.provider,
              label: provider.label,
            }))}
          />
        </Field>

        <Field label="Task">
          <Dropdown<string>
            ariaLabel="Task"
            value={form.task_type}
            onChange={(task_type) => dispatch({ type: 'patchForm', patch: { task_type } })}
            options={TASK_TYPES.map((taskType) => ({ value: taskType, label: taskType }))}
          />
        </Field>

        <Field label="Model" className="md:col-span-2">
          <div className="grid gap-2">
            <Dropdown<string>
              ariaLabel="Model"
              value={modelDropdownValue}
              onChange={(model) => {
                if (model === CUSTOM_MODEL_OPTION) {
                  dispatch({ type: 'setCustomModelSelected', selected: true });
                  return;
                }
                dispatch({ type: 'setCustomModelSelected', selected: false });
                dispatch({ type: 'patchForm', patch: { model } });
              }}
              options={modelOptions}
            />
            {modelIsCustom ? (
              <>
                <Input
                  value={form.model}
                  list={modelSuggestionsId}
                  onChange={(event) =>
                    dispatch({ type: 'patchForm', patch: { model: event.target.value } })
                  }
                  placeholder="Enter custom model id"
                />
                <datalist id={modelSuggestionsId}>
                  {recommendedModels.map((model) => (
                    <option key={model} value={model} label={model}>
                      {model}
                    </option>
                  ))}
                </datalist>
              </>
            ) : null}
          </div>
        </Field>

        <Field label="API Key" className="md:col-span-2">
          <Input
            type="password"
            value={form.api_key ?? ''}
            onChange={(event) =>
              dispatch({ type: 'patchForm', patch: { api_key: event.target.value } })
            }
            placeholder="Leave blank to rely on environment variables."
          />
        </Field>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="neutral" onClick={onTest} disabled={testing}>
          <PlugZap className="size-3.5" />
          {testing ? 'Testing…' : 'Test Connection'}
        </Button>
        <Button
          type="button"
          variant="action"
          onClick={onSave}
          disabled={saving || !form.model.trim()}
        >
          <Plus className="size-3.5" />
          {saving ? 'Saving…' : 'Save Config'}
        </Button>
      </div>

      <div className="min-h-[52px]">
        {message ? <InlineAlert message={message} tone="neutral" /> : null}
        {error ? <InlineAlert message={error} tone="danger" /> : null}
      </div>
    </SectionCard>
  );
}

interface ActiveConfigsCardProps {
  configs: LlmConfigRecord[];
  onDelete: (id: number) => void;
}

function ActiveConfigsCard({ configs, onDelete }: Readonly<ActiveConfigsCardProps>) {
  return (
    <SectionCard
      title="Active Configs"
      description="The active runtime snapshot available to selector discovery and cleanup tasks."
      className="space-y-4"
    >
      {configs.length ? (
        <div className="space-y-3">
          {configs.map((config) => (
            <DetailRow key={config.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="type-control truncate !font-normal text-foreground">
                      {config.task_type}
                    </span>
                    {config.is_active ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-success-bg px-2 py-0.5 text-xs leading-none font-normal text-success">
                        <CheckCircle2 className="size-3" aria-hidden="true" />
                        active
                      </span>
                    ) : null}
                  </div>
                  <p className="type-caption m-0">
                    {config.provider} · {config.model}
                  </p>
                  <p className="type-caption m-0">
                    {config.api_key_set ? config.api_key_masked : 'env-backed or unset'}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="destructive"
                  size="icon"
                  onClick={() => onDelete(config.id)}
                  aria-label="Delete config"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </DetailRow>
          ))}
        </div>
      ) : (
        <MutedPanelMessage title="No configs saved" description="No LLM configs saved yet." />
      )}
    </SectionCard>
  );
}

interface CostLogCardProps {
  costLog: LlmCostLogRecord[];
  nowMs: number | null;
}

function CostLogCard({ costLog, nowMs }: Readonly<CostLogCardProps>) {
  return (
    <div className="page-stack">
      <SectionCard
        title="Recent Cost Log"
        description="Latest LLM usage events recorded by the backend runtime."
        className="flex-1"
      >
        {costLog.length ? (
          <div className="custom-scrollbar max-h-[700px] overflow-y-auto">
            <Table className="table-auto">
              <TableHeader>
                <TableRow className="border-divider/50">
                  <TableHead className="w-[118px] text-[10px] tracking-[0.08em]">Usage</TableHead>
                  <TableHead className="w-[170px] text-[10px] tracking-[0.08em]">Task</TableHead>
                  <TableHead className="w-[160px] text-[10px] tracking-[0.08em]">Target</TableHead>
                  <TableHead className="text-[10px] tracking-[0.08em]">Provider</TableHead>
                  <TableHead className="w-[110px] text-right text-[10px] tracking-[0.08em]">
                    Time
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(() => {
                  const now = nowMs !== null ? new Date(nowMs) : null;
                  const todayStr = now?.toDateString();
                  const yesterdayStr = now
                    ? new Date(now.getTime() - 86_400_000).toDateString()
                    : undefined;
                  return costLog.slice(0, 40).map((entry) => {
                    const totalTokens = entry.input_tokens + entry.output_tokens;
                    const cost = parseFloat(entry.cost_usd) || 0;
                    return (
                      <TableRow key={entry.id} className="group transition-colors">
                        <TableCell className="py-3">
                          <div className="flex flex-col">
                            <div className="flex items-baseline gap-1.5">
                              <span className="type-caption-mono font-medium text-foreground tabular-nums">
                                {totalTokens.toLocaleString()}
                              </span>
                              <span className="type-caption">tokens</span>
                            </div>
                            <span className="type-label-mono mt-1 font-medium text-accent">
                              ${cost > 0 && cost < 0.0001 ? cost.toFixed(6) : cost.toFixed(4)}
                            </span>
                          </div>
                        </TableCell>

                        <TableCell className="py-3">
                          <span className="type-control block max-w-[150px] !font-normal whitespace-normal text-foreground">
                            {entry.task_type.replace(/_/g, ' ')}
                          </span>
                        </TableCell>

                        <TableCell className="py-3" title={entry.domain || `Run #${entry.run_id}`}>
                          <span className="block truncate text-foreground/80">
                            {entry.domain || (entry.run_id ? `Run #${entry.run_id}` : 'system')}
                          </span>
                        </TableCell>

                        <TableCell className="py-3">
                          <div className="flex flex-col overflow-hidden">
                            <span className="type-control truncate !font-normal text-foreground">
                              {entry.provider}
                            </span>
                            <span className="type-caption truncate" title={entry.model}>
                              {entry.model}
                            </span>
                          </div>
                        </TableCell>

                        <TableCell className="py-3 text-right">
                          <span className="type-caption-mono transition-colors group-hover:text-foreground">
                            {(() => {
                              const d = new Date(entry.created_at);
                              const dStr = d.toDateString();
                              const isToday = dStr === todayStr;
                              const isYesterday = dStr === yesterdayStr;

                              const timeStr = d.toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                hour12: false,
                              });
                              const dateStr = d.toLocaleDateString('en-US', {
                                month: '2-digit',
                                day: '2-digit',
                              });

                              if (isToday) return timeStr;
                              if (isYesterday) return `Yesterday ${timeStr}`;
                              return `${dateStr} ${timeStr}`;
                            })()}
                          </span>
                        </TableCell>
                      </TableRow>
                    );
                  });
                })()}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div className="p-12 text-center">
            <MutedPanelMessage
              title="No cost events"
              description="Detailed LLM usage and token metrics will appear here once active."
            />
          </div>
        )}
      </SectionCard>
    </div>
  );
}
