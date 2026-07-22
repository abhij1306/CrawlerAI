import { useEffect, useState } from 'react';

import type {
  AiVisibilityProjectCreate,
  CompetitorInput,
  PromptInput,
} from '../../lib/api/ai-visibility';
import { Button } from '../../components/ui/button';
import { AppDialog } from '../../components/ui/dialog';
import { Dropdown } from '../../components/ui/dropdown';
import { Field } from '../../components/ui/field';
import { Input } from '../../components/ui/input';

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

export const presetToForm = (preset: AiVisibilityProjectCreate): ProjectForm => ({
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

export function formToPayload(form: ProjectForm): AiVisibilityProjectCreate {
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
// Dialog
// --------------------------------------------------------------------------
export function ProjectFormDialog({
  open,
  onOpenChange,
  preset,
  pending,
  onSubmit,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preset: AiVisibilityProjectCreate | undefined;
  pending: boolean;
  onSubmit: (payload: AiVisibilityProjectCreate) => void;
}>) {
  const [form, setForm] = useState<ProjectForm>(EMPTY_FORM);

  // Opening the dialog always starts from a blank form (previously the
  // "New Domain" button reset the form before opening).
  useEffect(() => {
    if (open) setForm(EMPTY_FORM);
  }, [open]);

  const canSubmit = Boolean(form.name.trim() && form.brand_name.trim());

  const handleSubmit = () => {
    if (!canSubmit) return;
    onSubmit(formToPayload(form));
  };

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
    <AppDialog
      open={open}
      onOpenChange={onOpenChange}
      title="New Project"
      description="Define the brand, owned domains, competitors, and prompts to benchmark."
      className="w-[760px]"
      footer={
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => preset && setForm(presetToForm(preset))}
            disabled={!preset}
            type="button"
          >
            Prefill sample
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)} type="button">
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={!canSubmit || pending}
          >
            {pending ? 'Creating…' : 'Create Project'}
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
  );
}
