import { PlugZap, Plus } from 'lucide-react';

import { Button, Dropdown, Field, Input } from '@ui/primitives';
import { InlineAlert, SectionCard } from '@ui/patterns';
import type { LlmConfigCreatePayload, LlmProviderCatalogItem } from '@lib/api/types';

const CUSTOM_MODEL_OPTION = '__custom__';
const TASK_TYPES = [
  'general',
  'data_enrichment_semantic',
  'grounded_extraction_repair',
  'product_intelligence_enrichment',
  'product_intelligence_brand_inference',
];

interface LlmConfigFormCardProps {
  form: LlmConfigCreatePayload;
  providers: LlmProviderCatalogItem[];
  customModelSelected: boolean;
  testing: boolean;
  saving: boolean;
  message: string;
  error: string;
  onPatchForm: (patch: Partial<LlmConfigCreatePayload>) => void;
  onCustomModelSelected: (selected: boolean) => void;
  onTest: () => void;
  onSave: () => void;
}

export function LlmConfigFormCard({
  form,
  providers,
  customModelSelected,
  testing,
  saving,
  message,
  error,
  onPatchForm,
  onCustomModelSelected,
  onTest,
  onSave,
}: Readonly<LlmConfigFormCardProps>) {
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
              onCustomModelSelected(false);
              onPatchForm({
                provider,
                model: nextModel || form.model,
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
            onChange={(task_type) => onPatchForm({ task_type })}
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
                  onCustomModelSelected(true);
                  return;
                }
                onCustomModelSelected(false);
                onPatchForm({ model });
              }}
              options={modelOptions}
            />
            {modelIsCustom ? (
              <>
                <Input
                  value={form.model}
                  list={modelSuggestionsId}
                  onChange={(event) => onPatchForm({ model: event.target.value })}
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
            onChange={(event) => onPatchForm({ api_key: event.target.value })}
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
