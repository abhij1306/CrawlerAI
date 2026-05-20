'use client';

import { Bug, Globe2, Info, Shield } from 'lucide-react';
import { useMemo, useState } from 'react';

import type { CrawlSurface, MonitorCreatePayload, MonitorPriority } from '../../lib/api/types';
import { DEFAULT_FIELDS, SURFACE_DISPATCH } from '../crawl/domain-surface-config';
import { SettingSection } from '../crawl/form-fields';
import { Button, Dropdown, Field, Input, Textarea, Toggle, Tooltip } from '../ui/primitives';
import { TabBar, InlineAlert } from '../ui/patterns';

interface MonitorFormProps {
  initial?: Partial<MonitorCreatePayload>;
  onSubmit: (payload: MonitorCreatePayload) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
}

type IntervalUnit = 'hours' | 'days';

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
}: Readonly<MonitorFormProps>) {
  const initialHours = initial?.schedule_interval_hours ?? 24;
  const [name, setName] = useState(initial?.name ?? '');
  const [urlsText, setUrlsText] = useState((initial?.urls ?? []).join('\n'));
  const [surface, setSurface] = useState<CrawlSurface>(
    (initial?.surface as CrawlSurface | undefined) ?? 'ecommerce_detail',
  );
  const [trackedFields, setTrackedFields] = useState<string[]>(
    initial?.tracked_fields?.length ? initial.tracked_fields : ['price'],
  );
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>(
    initialHours >= 24 && initialHours % 24 === 0 ? 'days' : 'hours',
  );
  const [intervalValue, setIntervalValue] = useState(
    String(initialHours >= 24 && initialHours % 24 === 0 ? initialHours / 24 : initialHours),
  );
  const [priority, setPriority] = useState<MonitorPriority>(initial?.priority ?? 'background');
  const [retentionDays, setRetentionDays] = useState(initial?.retention_days ?? 30);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [skipHeadCheck, setSkipHeadCheck] = useState(
    typeof initial?.settings?.skip_head_check === 'boolean'
      ? Boolean(initial.settings.skip_head_check)
      : skipsHeadByDefault((initial?.surface as string | undefined) ?? 'ecommerce_detail'),
  );
  const [proxyEnabled, setProxyEnabled] = useState(Boolean(initial?.settings?.proxy_enabled));
  const [jsRendering, setJsRendering] = useState(
    String(
      (initial?.settings?.fetch_profile as { js_mode?: string } | undefined)?.js_mode ?? '',
    ) === 'enabled',
  );
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const urls = useMemo(
    () =>
      urlsText
        .split(/\r?\n/)
        .map((url) => url.trim())
        .filter(Boolean),
    [urlsText],
  );
  const availableFields = DEFAULT_FIELDS[surface] ?? ['price'];
  const invalidUrls = urls.filter((url) => !/^https?:\/\//i.test(url));
  const intervalHours =
    Math.max(0, Number.parseInt(intervalValue || '0', 10) || 0) *
    (intervalUnit === 'days' ? 24 : 1);

  function handleSurfaceChange(nextSurface: CrawlSurface) {
    const defaultFields = DEFAULT_FIELDS[nextSurface] ?? [];
    setSurface(nextSurface);
    setTrackedFields(defaultFields.includes('price') ? ['price'] : defaultFields.slice(0, 1));
    setSkipHeadCheck(skipsHeadByDefault(nextSurface));
  }

  function toggleField(field: string) {
    setTrackedFields((current) =>
      current.includes(field) ? current.filter((item) => item !== field) : [...current, field],
    );
  }

  async function submit() {
    setError('');
    if (!name.trim()) {
      setError('Name is required.');
      return;
    }
    if (name.trim().length > 100) {
      setError('Name must be 100 characters or less.');
      return;
    }
    if (!urls.length) {
      setError('At least one URL is required.');
      return;
    }
    if (invalidUrls.length) {
      setError('Every URL must start with http:// or https://.');
      return;
    }
    if (urls.length > 500) {
      setError('No more than 500 URLs are allowed.');
      return;
    }
    if (!trackedFields.length) {
      setError('Select at least one tracked field.');
      return;
    }
    if (intervalHours < 1) {
      setError('Schedule interval must be at least 1 hour.');
      return;
    }
    setSubmitting(true);
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
      setError(submitError instanceof Error ? submitError.message : 'Unable to save monitor.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-5">
      {error ? <InlineAlert message={error} /> : null}
      <Field label="Name">
        <Input value={name} maxLength={100} onChange={(event) => setName(event.target.value)} />
      </Field>
      <Field label="URLs" hint={`${urls.length} URL${urls.length === 1 ? '' : 's'}`}>
        <Textarea
          value={urlsText}
          onChange={(event) => setUrlsText(event.target.value)}
          className="min-h-32 font-mono"
          placeholder="https://example.com/product"
        />
      </Field>
      {urls.length > 500 ? (
        <p className="text-warning type-caption">
          More than 500 URLs. Backend will reject this monitor.
        </p>
      ) : null}
      {invalidUrls.length ? (
        <p className="text-danger type-caption">
          {invalidUrls.length} URL(s) need http:// or https://.
        </p>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Surface">
          <Dropdown value={surface} onChange={handleSurfaceChange} options={surfaceOptions} />
        </Field>
        <Field label="Retention" hint={`Keep ${retentionDays} days of history`}>
          <input
            type="range"
            min={1}
            max={90}
            value={retentionDays}
            onChange={(event) => setRetentionDays(Number(event.target.value))}
            className="slider-control w-full"
          />
        </Field>
      </div>
      <div className="space-y-2">
        <div className="field-label">Tracked Fields</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {availableFields.map((field) => (
            <label
              key={field}
              className="border-border bg-panel flex items-center gap-2 rounded-[var(--radius-md)] border px-3 py-2"
            >
              <input
                type="checkbox"
                checked={trackedFields.includes(field)}
                onChange={() => toggleField(field)}
              />
              <span className="type-body-sm">{field}</span>
            </label>
          ))}
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-[1fr_160px]">
        <Field
          label="Schedule Interval"
          hint={intervalHours < 1 ? 'Minimum is 1 hour.' : undefined}
        >
          <Input
            type="number"
            min={1}
            value={intervalValue}
            onChange={(event) => setIntervalValue(event.target.value)}
          />
        </Field>
        <Field label="Unit">
          <Dropdown<IntervalUnit>
            value={intervalUnit}
            onChange={setIntervalUnit}
            options={[
              { value: 'hours', label: 'Hours' },
              { value: 'days', label: 'Days' },
            ]}
          />
        </Field>
      </div>
      <div className="space-y-2">
        <div className="field-label">Priority</div>
        <div className="flex flex-wrap gap-2">
          {priorityOptions.map((option) => (
            <Tooltip key={option.value} content={option.hint}>
              <button
                type="button"
                onClick={() => setPriority(option.value)}
                className={`type-control border-border rounded-[var(--radius-md)] border px-3 py-2 ${
                  priority === option.value ? 'bg-accent-subtle text-accent' : 'text-secondary'
                }`}
              >
                {option.label}
              </button>
            </Tooltip>
          ))}
        </div>
      </div>
      <div className="border-border rounded-[var(--radius-lg)] border">
        <SettingSection
          label="Advanced crawl settings"
          description="Optional crawl runtime controls reused from Crawl Studio."
          icon={<Info />}
          checked={advancedOpen}
          onChange={setAdvancedOpen}
        >
          <SettingSection
            label="Proxy"
            description="Allow proxy settings to be passed with this monitor."
            icon={<Shield />}
            checked={proxyEnabled}
            onChange={setProxyEnabled}
          />
          <SettingSection
            label="JS rendering"
            description="Prefer rendered DOM acquisition for monitor runs."
            icon={<Globe2 />}
            checked={jsRendering}
            onChange={setJsRendering}
          />
          <div className="border-border bg-panel flex items-center justify-between gap-3 rounded-[var(--radius-md)] border px-3 py-2">
            <div>
              <p className="type-body-sm m-0 font-medium">Skip HEAD pre-check</p>
              <p className="text-muted type-caption m-0">
                Ecommerce monitors recrawl on schedule instead of trusting CDN validators.
              </p>
            </div>
            <Toggle
              checked={skipHeadCheck}
              onChange={setSkipHeadCheck}
              ariaLabel="Skip HEAD pre-check"
            />
          </div>
          <div className="text-muted type-caption flex items-center gap-1.5">
            <Bug className="size-3.5" />
            Detailed crawl diagnostics still follow backend run settings.
          </div>
        </SettingSection>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="quiet" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        <Button type="button" onClick={() => void submit()} disabled={submitting}>
          {submitting ? 'Saving...' : submitLabel}
        </Button>
      </div>
    </div>
  );
}
