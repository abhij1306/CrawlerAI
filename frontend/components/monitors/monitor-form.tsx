'use client';

import { Globe2, Info, Shield } from 'lucide-react';
import { useMemo, useReducer } from 'react';

import type { CrawlSurface, MonitorCreatePayload, MonitorPriority } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { DEFAULT_FIELDS, SURFACE_DISPATCH } from '../crawl/domain-surface-config';
import { SettingSection } from '../crawl/form-fields';
import { Button, Dropdown, Field, Input, Textarea, Toggle, Tooltip } from '../ui/primitives';
import { InlineAlert } from '../ui/patterns';
import {
  failFormSubmit,
  settleFormSubmit,
  startFormSubmit,
  toggleSelectedValue,
} from './monitor-form-state';

interface MonitorFormProps {
  initial?: Partial<MonitorCreatePayload>;
  onSubmit: (payload: MonitorCreatePayload) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
  layout?: 'grid' | 'stack';
}

type IntervalUnit = 'hours' | 'days';

type MonitorFormState = {
  name: string;
  urlsText: string;
  surface: CrawlSurface;
  trackedFields: string[];
  intervalUnit: IntervalUnit;
  intervalValue: string;
  priority: MonitorPriority;
  retentionDays: number;
  advancedOpen: boolean;
  skipHeadCheck: boolean;
  proxyEnabled: boolean;
  jsRendering: boolean;
  error: string;
  submitting: boolean;
};

type MonitorFormAction =
  | { type: 'nameChanged'; value: string }
  | { type: 'urlsTextChanged'; value: string }
  | { type: 'surfaceChanged'; value: CrawlSurface }
  | { type: 'fieldToggled'; field: string }
  | { type: 'intervalValueChanged'; value: string }
  | { type: 'intervalUnitChanged'; value: IntervalUnit }
  | { type: 'priorityChanged'; value: MonitorPriority }
  | { type: 'retentionDaysChanged'; value: number }
  | { type: 'advancedOpenChanged'; value: boolean }
  | { type: 'proxyEnabledChanged'; value: boolean }
  | { type: 'jsRenderingChanged'; value: boolean }
  | { type: 'skipHeadCheckChanged'; value: boolean }
  | { type: 'submitStarted' }
  | { type: 'submitFailed'; message: string }
  | { type: 'submitSettled' }
  | { type: 'validationFailed'; message: string };

function monitorFormReducer(state: MonitorFormState, action: MonitorFormAction): MonitorFormState {
  switch (action.type) {
    case 'nameChanged':
      return { ...state, name: action.value };
    case 'urlsTextChanged':
      return { ...state, urlsText: action.value };
    case 'surfaceChanged': {
      const defaultFields = DEFAULT_FIELDS[action.value] ?? [];
      return {
        ...state,
        surface: action.value,
        trackedFields: defaultFields.includes('price') ? ['price'] : defaultFields.slice(0, 1),
        skipHeadCheck: skipsHeadByDefault(action.value),
      };
    }
    case 'fieldToggled':
      return {
        ...state,
        trackedFields: toggleSelectedValue(state.trackedFields, action.field),
      };
    case 'intervalValueChanged':
      return { ...state, intervalValue: action.value };
    case 'intervalUnitChanged':
      return { ...state, intervalUnit: action.value };
    case 'priorityChanged':
      return { ...state, priority: action.value };
    case 'retentionDaysChanged':
      return { ...state, retentionDays: action.value };
    case 'advancedOpenChanged':
      return { ...state, advancedOpen: action.value };
    case 'proxyEnabledChanged':
      return { ...state, proxyEnabled: action.value };
    case 'jsRenderingChanged':
      return { ...state, jsRendering: action.value };
    case 'skipHeadCheckChanged':
      return { ...state, skipHeadCheck: action.value };
    case 'submitStarted':
      return startFormSubmit(state);
    case 'submitFailed':
    case 'validationFailed':
      return failFormSubmit(state, action.message);
    case 'submitSettled':
      return settleFormSubmit(state);
  }
}

const surfaceOptions = Array.from(new Set(Object.values(SURFACE_DISPATCH))).map((surface) => ({
  value: surface,
  label: surface.replace(/_/g, ' '),
}));

const priorityOptions: Array<{ value: MonitorPriority; label: string; hint: string }> = [
  { value: 'background', label: 'Background', hint: 'Runs after higher priority monitors.' },
  { value: 'priority', label: 'Priority', hint: 'Runs before background monitors on each tick.' },
  { value: 'on_demand', label: 'On-Demand', hint: 'Bypasses regular dispatch caps when due.' },
];

function skipsHeadByDefault(surface: string) {
  return surface === 'ecommerce_detail' || surface === 'ecommerce_listing';
}

export function MonitorForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
  layout = 'stack',
}: Readonly<MonitorFormProps>) {
  const initialHours = initial?.schedule_interval_hours ?? 24;
  const [state, dispatch] = useReducer(monitorFormReducer, {
    name: initial?.name ?? '',
    urlsText: (initial?.urls ?? []).join('\n'),
    surface: (initial?.surface as CrawlSurface | undefined) ?? 'ecommerce_detail',
    trackedFields: initial?.tracked_fields?.length ? initial.tracked_fields : ['price'],
    intervalUnit: initialHours >= 24 && initialHours % 24 === 0 ? 'days' : 'hours',
    intervalValue: String(
      initialHours >= 24 && initialHours % 24 === 0 ? initialHours / 24 : initialHours,
    ),
    priority: initial?.priority ?? 'background',
    retentionDays: initial?.retention_days ?? 30,
    advancedOpen: false,
    skipHeadCheck:
      typeof initial?.settings?.skip_head_check === 'boolean'
        ? Boolean(initial.settings.skip_head_check)
        : skipsHeadByDefault((initial?.surface as string | undefined) ?? 'ecommerce_detail'),
    proxyEnabled: Boolean(initial?.settings?.proxy_enabled),
    jsRendering:
      String(
        (initial?.settings?.fetch_profile as { js_mode?: string } | undefined)?.js_mode ?? '',
      ) === 'enabled',
    error: '',
    submitting: false,
  });
  const {
    name,
    urlsText,
    surface,
    trackedFields,
    intervalUnit,
    intervalValue,
    priority,
    retentionDays,
    advancedOpen,
    skipHeadCheck,
    proxyEnabled,
    jsRendering,
    error,
    submitting,
  } = state;

  const urls = useMemo(
    () =>
      urlsText.split(/\r?\n/).flatMap((url) => {
        const trimmed = url.trim();
        return trimmed ? [trimmed] : [];
      }),
    [urlsText],
  );
  const availableFields = DEFAULT_FIELDS[surface] ?? ['price'];
  const invalidUrls = urls.filter((url) => !/^https?:\/\//i.test(url));
  const intervalHours =
    Math.max(0, Number.parseInt(intervalValue || '0', 10) || 0) *
    (intervalUnit === 'days' ? 24 : 1);

  function handleSurfaceChange(nextSurface: CrawlSurface) {
    dispatch({ type: 'surfaceChanged', value: nextSurface });
  }

  function toggleField(field: string) {
    dispatch({ type: 'fieldToggled', field });
  }

  async function submit() {
    if (!name.trim()) {
      dispatch({ type: 'validationFailed', message: 'Name is required.' });
      return;
    }
    if (name.trim().length > 100) {
      dispatch({ type: 'validationFailed', message: 'Name must be 100 characters or less.' });
      return;
    }
    if (!urls.length) {
      dispatch({ type: 'validationFailed', message: 'At least one URL is required.' });
      return;
    }
    if (invalidUrls.length) {
      dispatch({
        type: 'validationFailed',
        message: 'Every URL must start with http:// or https://.',
      });
      return;
    }
    if (urls.length > 500) {
      dispatch({ type: 'validationFailed', message: 'No more than 500 URLs are allowed.' });
      return;
    }
    if (!trackedFields.length) {
      dispatch({ type: 'validationFailed', message: 'Select at least one tracked field.' });
      return;
    }
    if (intervalHours < 1) {
      dispatch({ type: 'validationFailed', message: 'Schedule interval must be at least 1 hour.' });
      return;
    }
    dispatch({ type: 'submitStarted' });
    try {
      await onSubmit({
        name: name.trim(),
        urls,
        surface,
        tracked_fields: trackedFields,
        schedule_interval_hours: intervalHours,
        priority,
        retention_days: retentionDays,
        requested_fields: Array.from(new Set([...availableFields, ...trackedFields])),
        settings: {
          skip_head_check: skipHeadCheck,
          proxy_enabled: proxyEnabled,
          fetch_profile: {
            js_mode: jsRendering ? 'enabled' : 'disabled',
            extraction_source: jsRendering ? 'rendered_dom' : 'raw_html',
          },
        },
      });
    } catch (submitError) {
      dispatch({
        type: 'submitFailed',
        message: submitError instanceof Error ? submitError.message : 'Unable to save monitor.',
      });
    } finally {
      dispatch({ type: 'submitSettled' });
    }
  }

  return (
    <div className="space-y-4">
      {error ? <InlineAlert message={error} /> : null}

      <div className={cn(layout === 'grid' ? 'grid gap-6 lg:grid-cols-2' : 'space-y-4')}>
        <div className="space-y-4">
          <Field label="Name">
            <Input
              value={name}
              maxLength={100}
              onChange={(event) => dispatch({ type: 'nameChanged', value: event.target.value })}
            />
          </Field>

          <Field label="URLs" hint={`${urls.length} URL${urls.length === 1 ? '' : 's'}`}>
            <Textarea
              value={urlsText}
              onChange={(event) => dispatch({ type: 'urlsTextChanged', value: event.target.value })}
              className="h-28 font-mono"
              placeholder="https://example.com/product"
            />
          </Field>
          {urls.length > 500 ? (
            <p className="text-warning type-caption m-0">
              More than 500 URLs. Backend will reject this monitor.
            </p>
          ) : null}
          {invalidUrls.length ? (
            <p className="text-danger type-caption m-0">
              {invalidUrls.length} URL(s) need http:// or https://.
            </p>
          ) : null}

          <div className="grid grid-cols-2 gap-4">
            <Field label="Surface">
              <Dropdown value={surface} onChange={handleSurfaceChange} options={surfaceOptions} />
            </Field>

            <Field label="Retention" hint={`Keep ${retentionDays} days`}>
              <div className="flex h-[var(--control-height)] items-center">
                <input
                  type="range"
                  aria-label="Retention days"
                  min={1}
                  max={90}
                  value={retentionDays}
                  onChange={(event) =>
                    dispatch({ type: 'retentionDaysChanged', value: Number(event.target.value) })
                  }
                  className="slider-control w-full"
                />
              </div>
            </Field>
          </div>

          <div className="space-y-1.5">
            <div className="field-label">Tracked Fields</div>
            <div className="flex flex-wrap gap-1.5">
              {availableFields.map((field) => {
                const isSelected = trackedFields.includes(field);
                return (
                  <button
                    key={field}
                    type="button"
                    onClick={() => toggleField(field)}
                    className={cn(
                      'type-control cursor-pointer rounded-sm border px-2.5 py-1 text-xs font-semibold transition-colors',
                      isSelected
                        ? 'border-accent bg-accent-subtle text-accent'
                        : 'border-border bg-panel text-secondary hover:bg-background-alt',
                    )}
                  >
                    {field}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-4">
          <div className="space-y-4">
            <div className="grid grid-cols-[1fr_120px] gap-4">
              <Field
                label="Schedule Interval"
                hint={intervalHours < 1 ? 'Minimum is 1 hour.' : undefined}
              >
                <Input
                  type="number"
                  min={1}
                  value={intervalValue}
                  onChange={(event) =>
                    dispatch({ type: 'intervalValueChanged', value: event.target.value })
                  }
                />
              </Field>
              <Field label="Unit">
                <Dropdown<IntervalUnit>
                  value={intervalUnit}
                  onChange={(value) => dispatch({ type: 'intervalUnitChanged', value })}
                  options={[
                    { value: 'hours', label: 'Hours' },
                    { value: 'days', label: 'Days' },
                  ]}
                />
              </Field>
            </div>

            <div className="space-y-1.5">
              <div className="field-label">Priority</div>
              <div className="border-border bg-background-alt flex w-max gap-1 rounded-md border p-0.5">
                {priorityOptions.map((option) => (
                  <Tooltip key={option.value} content={option.hint}>
                    <button
                      type="button"
                      onClick={() => dispatch({ type: 'priorityChanged', value: option.value })}
                      className={cn(
                        'type-control cursor-pointer rounded-sm px-3 py-1 text-xs font-semibold transition-colors',
                        priority === option.value
                          ? 'border-border bg-panel text-foreground border shadow-xs'
                          : 'text-secondary hover:text-foreground border border-transparent',
                      )}
                    >
                      {option.label}
                    </button>
                  </Tooltip>
                ))}
              </div>
            </div>

            <div className="border-border rounded-lg border">
              <SettingSection
                label="Advanced crawl settings"
                description="Optional crawl runtime controls reused from Crawl Studio."
                icon={<Info />}
                checked={advancedOpen}
                onChange={(value) => dispatch({ type: 'advancedOpenChanged', value })}
                rowClassName="h-auto min-h-12 px-3 py-2"
                bodyClassName="space-y-3.5 p-3"
              >
                <div className="space-y-3.5">
                  <SettingSection
                    label="Proxy"
                    description="Allow proxy settings to be passed with this monitor."
                    icon={<Shield />}
                    checked={proxyEnabled}
                    onChange={(value) => dispatch({ type: 'proxyEnabledChanged', value })}
                  />
                  <SettingSection
                    label="JS rendering"
                    description="Prefer rendered DOM acquisition for monitor runs."
                    icon={<Globe2 />}
                    checked={jsRendering}
                    onChange={(value) => dispatch({ type: 'jsRenderingChanged', value })}
                  />
                  <div className="border-border bg-panel flex items-center justify-between gap-3 rounded-md border px-3 py-2">
                    <div>
                      <p className="type-body-sm m-0 font-medium">Skip HEAD pre-check</p>
                      <p className="type-caption m-0">
                        Ecommerce monitors recrawl on schedule instead of trusting CDN validators.
                      </p>
                    </div>
                    <Toggle
                      checked={skipHeadCheck}
                      onChange={(value) => dispatch({ type: 'skipHeadCheckChanged', value })}
                      ariaLabel="Skip HEAD pre-check"
                    />
                  </div>
                </div>
              </SettingSection>
            </div>
          </div>

          <div
            className={cn(
              'border-border flex justify-end gap-2 border-t pt-4',
              layout === 'grid' ? 'mt-auto' : 'mt-6',
            )}
          >
            <Button type="button" variant="quiet" onClick={onCancel} disabled={submitting}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void submit()} disabled={submitting}>
              {submitting ? 'Saving...' : submitLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
