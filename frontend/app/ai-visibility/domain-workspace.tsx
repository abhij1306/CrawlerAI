import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, History, Play, Plus, Save, X } from 'lucide-react';

import type {
  AiVisibilityProject,
  AiVisibilityProviderId,
  AiVisibilityProviderStatus,
  PromptInput,
} from '../../lib/api/ai-visibility';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { Dropdown } from '../../components/ui/dropdown';
import { Input } from '../../components/ui/input';

type ProviderId = AiVisibilityProviderId;

const PROMPT_INTENT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'No intent' },
  { value: 'discovery', label: 'Discovery' },
  { value: 'comparison', label: 'Comparison' },
  { value: 'purchase', label: 'Purchase' },
  { value: 'service', label: 'Service' },
  { value: 'local', label: 'Local' },
];

export function DomainWorkspace({
  project,
  providers,
  historyCount,
  runPending,
  savePending,
  onSavePrompts,
  onRun,
  onOpenHistory,
}: Readonly<{
  project: AiVisibilityProject;
  providers: AiVisibilityProviderStatus[];
  historyCount: number;
  runPending: boolean;
  savePending: boolean;
  onSavePrompts: (projectId: number, prompts: PromptInput[]) => void;
  onRun: (options: {
    projectId: number;
    repetitions: number;
    provider: ProviderId;
    promptIndices?: number[];
    openReport: boolean;
  }) => void;
  onOpenHistory: (projectId: number) => void;
}>) {
  const [open, setOpen] = useState(false);
  const [prompts, setPrompts] = useState<PromptInput[]>(project.prompts);
  const [provider, setProvider] = useState<ProviderId>('gemini');
  const [repetitions, setRepetitions] = useState(project.default_repetitions);
  const [openReport, setOpenReport] = useState(true);

  useEffect(() => setPrompts(project.prompts), [project.prompts, project.updated_at]);
  useEffect(() => setRepetitions(project.default_repetitions), [project.default_repetitions]);

  const providerStatus = providers.find((item) => item.provider === provider);
  const domain = project.owned_domains[0] || project.name;
  const dirty = JSON.stringify(prompts) !== JSON.stringify(project.prompts);
  const runnable = Boolean(providerStatus?.configured) && !runPending && !dirty;

  const updatePrompt = (index: number, patch: Partial<PromptInput>) =>
    setPrompts((current) =>
      current.map((prompt, promptIndex) =>
        promptIndex === index ? { ...prompt, ...patch } : prompt,
      ),
    );

  const run = (promptIndices?: number[]) =>
    onRun({
      projectId: project.id,
      repetitions,
      provider,
      promptIndices,
      openReport,
    });

  return (
    <Card className="overflow-hidden p-0">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-background-alt"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        <div className="min-w-0 flex-1">
          <div className="type-subheading truncate text-foreground">{domain}</div>
          <div className="type-body-sm text-muted">
            {project.brand_name} · {prompts.length} prompts · {historyCount} saved reports
          </div>
        </div>
        {dirty ? <Badge tone="warning">Unsaved prompt edits</Badge> : null}
      </button>

      {open ? (
        <div className="border-t border-divider p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-1 text-xs text-muted">
              Provider
              <Dropdown
                ariaLabel="Provider"
                className="min-w-64"
                size="sm"
                value={provider}
                options={providers.map((item) => ({
                  value: item.provider as ProviderId,
                  label: `${item.label}${item.configured ? '' : ' — not configured'}`,
                }))}
                onChange={(value) => setProvider(value)}
              />
            </div>
            <label
              htmlFor={`ai-visibility-repetitions-${project.id}`}
              className="grid gap-1 text-xs text-muted"
            >
              Repetitions
              <Input
                id={`ai-visibility-repetitions-${project.id}`}
                className="h-9 w-24"
                type="number"
                min={1}
                value={repetitions}
                onChange={(event) => setRepetitions(Math.max(1, Number(event.target.value) || 1))}
              />
            </label>
            <label className="type-body-sm flex h-9 items-center gap-2 text-secondary">
              <input
                type="checkbox"
                checked={openReport}
                onChange={(event) => setOpenReport(event.target.checked)}
              />
              Open report after launch
            </label>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button variant="quiet" size="sm" onClick={() => onOpenHistory(project.id)}>
                <History className="size-3.5" /> History ({historyCount})
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!dirty || savePending || prompts.every((prompt) => !prompt.text.trim())}
                onClick={() =>
                  onSavePrompts(
                    project.id,
                    prompts.filter((prompt) => prompt.text.trim()),
                  )
                }
              >
                <Save className="size-3.5" /> {savePending ? 'Saving…' : 'Save prompts'}
              </Button>
              <Button variant="action" size="sm" disabled={!runnable} onClick={() => run()}>
                <Play className="size-3.5" /> Run all
              </Button>
            </div>
          </div>

          <div className="mt-4 grid gap-2">
            {prompts.map((prompt, index) => (
              <div
                key={`${project.id}-${index}`}
                className="grid gap-2 rounded-md border border-border bg-background-alt p-2 lg:grid-cols-[minmax(280px,1fr)_180px_150px_auto]"
              >
                <Input
                  value={prompt.text}
                  onChange={(event) => updatePrompt(index, { text: event.target.value })}
                  placeholder="Buyer-intent prompt"
                />
                <Input
                  value={prompt.theme ?? ''}
                  onChange={(event) => updatePrompt(index, { theme: event.target.value })}
                  placeholder="Theme"
                />
                <Dropdown
                  ariaLabel="Prompt intent"
                  value={prompt.intent ?? ''}
                  options={PROMPT_INTENT_OPTIONS}
                  onChange={(value) => updatePrompt(index, { intent: value })}
                />
                <div className="flex justify-end gap-1">
                  <Button
                    variant="quiet"
                    size="sm"
                    disabled={!runnable || !prompt.text.trim()}
                    onClick={() => run([index])}
                  >
                    <Play className="size-3.5" /> Run
                  </Button>
                  <Button
                    variant="quiet"
                    size="icon"
                    aria-label={`Remove prompt ${index + 1}`}
                    disabled={prompts.length === 1}
                    onClick={() =>
                      setPrompts((current) => current.filter((_, itemIndex) => itemIndex !== index))
                    }
                  >
                    <X className="size-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
          <Button
            className="mt-2"
            variant="quiet"
            size="sm"
            onClick={() =>
              setPrompts((current) => [...current, { text: '', theme: '', intent: '' }])
            }
          >
            <Plus className="size-3.5" /> Add prompt
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
