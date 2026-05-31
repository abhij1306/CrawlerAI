'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { zodResolver } from '@hookform/resolvers/zod';
import { Bell, Check, Clock, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';

import { alertsApi } from '../../lib/api';
import type { AlertTargetRule, CrawlRecord, CrawlRun } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { Badge, Button, Dropdown, Input } from '../ui/primitives';
import { InlineAlert } from '../ui/patterns';
import { humanizeFieldName, isEmptyCandidateValue, uniqueStrings } from './shared';

type AlertBuilderDrawerProps = Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  records: CrawlRecord[];
  run: CrawlRun | undefined;
  onCreated: (alertId: number) => void;
}>;

type AlertRuleDraft = AlertTargetRule & {
  id: string;
};

const alertRuleSchema = z.object({
  id: z.string(),
  path: z.string().min(1),
  label: z.string().nullable().optional(),
  operator: z.string().optional(),
  value: z.unknown().optional(),
  variant_match: z.record(z.string(), z.unknown()).nullable().optional(),
});

const alertBuilderSchema = z.object({
  selectedRecordId: z.string().optional(),
  rules: z.array(alertRuleSchema).min(1, 'Select at least one alert rule.'),
  pollInterval: z.string().regex(/^\d+$/, 'Poll interval must be a number.'),
  webhookUrl: z
    .string()
    .trim()
    .refine((value) => !value || /^https?:\/\//i.test(value), {
      message: 'Webhook URL must start with http:// or https://.',
    }),
});

type AlertBuilderForm = {
  selectedRecordId?: string;
  rules: AlertRuleDraft[];
  pollInterval: string;
  webhookUrl: string;
};

const alertIntervalOptions = [
  { value: '60', label: '1 min' },
  { value: '300', label: '5 min' },
  { value: '900', label: '15 min' },
  { value: '1800', label: '30 min' },
  { value: '3600', label: '1 hour' },
];

const alertOperatorOptions = [
  { value: 'changed', label: 'Changed' },
  { value: 'equals', label: 'Equals' },
  { value: 'not_equals', label: 'Not equals' },
  { value: 'less_than', label: 'Less than' },
  { value: 'greater_than', label: 'Greater than' },
  { value: 'exists', label: 'Exists' },
  { value: 'missing', label: 'Missing' },
];

const ALERT_BUILDER_DEFAULT_VALUES: AlertBuilderForm = {
  selectedRecordId: '',
  rules: [],
  pollInterval: '300',
  webhookUrl: '',
};
const MAX_VARIANTS_DISPLAY = 12;
const MAX_FIELDS_PER_VARIANT = 5;

export function AlertBuilderDrawer({
  open,
  onOpenChange,
  records,
  run,
  onCreated,
}: AlertBuilderDrawerProps) {
  const [submitError, setSubmitError] = useState('');
  const {
    control,
    formState: { errors, isSubmitting },
    handleSubmit,
    reset,
    setValue,
  } = useForm<AlertBuilderForm>({
    resolver: zodResolver(alertBuilderSchema),
    defaultValues: ALERT_BUILDER_DEFAULT_VALUES,
  });

  const selectedRecordId = useWatch({ control, name: 'selectedRecordId' });
  const rules = useWatch({ control, name: 'rules' }) ?? [];
  const pollInterval = useWatch({ control, name: 'pollInterval' });
  const webhookUrl = useWatch({ control, name: 'webhookUrl' });

  const selectedRecord = useMemo(() => {
    return records.find((record) => String(record.id) === selectedRecordId) ?? records[0];
  }, [records, selectedRecordId]);
  const selectedData = useMemo(() => recordData(selectedRecord), [selectedRecord]);
  const variants = useMemo(() => productVariants(selectedData), [selectedData]);
  const rootFields = useMemo(() => alertRootFields(selectedData), [selectedData]);
  const variantFields = useMemo(() => alertVariantFields(variants), [variants]);
  const recordOptions = useMemo(
    () =>
      records.map((record) => ({
        value: String(record.id),
        label: alertRecordLabel(record),
      })),
    [records],
  );
  const validationError =
    errors.rules?.message ?? errors.webhookUrl?.message ?? errors.pollInterval?.message;
  const visibleVariants = variants.slice(0, MAX_VARIANTS_DISPLAY);
  const hiddenVariantCount = variants.length - visibleVariants.length;
  const visibleVariantFields = variantFields.slice(0, MAX_FIELDS_PER_VARIANT);
  const hiddenVariantFieldCount = variantFields.length - visibleVariantFields.length;

  useEffect(() => {
    if (!open) {
      return;
    }
    reset(ALERT_BUILDER_DEFAULT_VALUES);
  }, [open, reset]);

  function toggleRule(nextRule: AlertRuleDraft) {
    const existing = rules.find(
      (rule) => alertRuleSignature(rule) === alertRuleSignature(nextRule),
    );
    setValue(
      'rules',
      existing ? rules.filter((rule) => rule.id !== existing.id) : [...rules, nextRule],
      { shouldValidate: true },
    );
  }

  function updateRule(id: string, patch: Partial<AlertRuleDraft>) {
    setValue(
      'rules',
      rules.map((rule) => (rule.id === id ? { ...rule, ...patch } : rule)),
      { shouldValidate: true },
    );
  }

  async function createAlert(values: AlertBuilderForm) {
    setSubmitError('');
    if (!selectedRecord) {
      setSubmitError('No product record selected.');
      return;
    }
    const url = alertRecordUrl(selectedRecord, run);
    if (!url) {
      setSubmitError('Selected record has no URL.');
      return;
    }
    try {
      const targetRules = values.rules.map(({ id: _id, ...rule }) => ({
        ...rule,
        value: needsAlertRuleValue(rule.operator) ? rule.value : undefined,
      }));
      const alert = await alertsApi.create({
        url,
        target_fields: alertTargetFields(targetRules),
        target_rules: targetRules,
        condition: null,
        webhook_url: values.webhookUrl.trim() || null,
        poll_interval_seconds: Number.parseInt(values.pollInterval, 10),
      });
      onOpenChange(false);
      onCreated(alert.id);
    } catch (createError) {
      setSubmitError(
        createError instanceof Error ? createError.message : 'Unable to create alert.',
      );
    }
  }

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => !isSubmitting && onOpenChange(nextOpen)}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[100] animate-[fade-in_200ms_ease-out] bg-[color-mix(in_srgb,var(--bg-base)_34%,black)]" />
        <DialogPrimitive.Content className="border-border bg-background shadow-elevated fixed top-0 right-0 z-[101] flex h-dvh w-[min(720px,100vw)] animate-[slide-in-right_250ms_cubic-bezier(0.16,1,0.3,1)] flex-col border-l">
          <div className="border-border flex-none border-b px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <DialogPrimitive.Title className="type-heading-1 m-0 flex items-center gap-2.5">
                  <span className="bg-accent/10 text-accent inline-flex size-8 items-center justify-center rounded-md">
                    <Bell className="size-4" />
                  </span>
                  Alert Builder
                </DialogPrimitive.Title>
                <DialogPrimitive.Description className="text-muted type-body-sm mt-2 flex items-center gap-1.5 truncate">
                  {alertRecordUrl(selectedRecord, run) || 'No product URL'}
                </DialogPrimitive.Description>
              </div>
              <DialogPrimitive.Close asChild>
                <Button
                  type="button"
                  variant="quiet"
                  size="icon"
                  aria-label="Close"
                  disabled={isSubmitting}
                >
                  <X className="size-4" />
                </Button>
              </DialogPrimitive.Close>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-5">
            {submitError || validationError ? (
              <div className="mb-4">
                <InlineAlert tone="danger" message={submitError || validationError || ''} />
              </div>
            ) : null}

            <div className="space-y-6">
              {recordOptions.length > 1 ? (
                <section>
                  <DrawerStepHeader step={1} title="Select Record" />
                  <div className="mt-3">
                    <Dropdown
                      value={selectedRecord ? String(selectedRecord.id) : ''}
                      onChange={(value) => setValue('selectedRecordId', value)}
                      options={recordOptions}
                      ariaLabel="Record"
                      portal={false}
                    />
                  </div>
                </section>
              ) : null}

              <section>
                <DrawerStepHeader
                  step={recordOptions.length > 1 ? 2 : 1}
                  title="Product Fields"
                  subtitle="Select fields to monitor for changes"
                />
                <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                  {rootFields.map((field) => {
                    const rule = buildAlertRule({
                      path: field,
                      label: `Product ${humanizeFieldName(field).toLowerCase()}`,
                    });
                    const isActive = rules.some(
                      (item) => alertRuleSignature(item) === alertRuleSignature(rule),
                    );
                    return (
                      <AlertFieldCard
                        key={field}
                        active={isActive}
                        label={humanizeFieldName(field)}
                        value={formatAlertValue(selectedData[field])}
                        onClick={() => toggleRule(rule)}
                      />
                    );
                  })}
                </div>
              </section>

              {variants.length ? (
                <section>
                  <DrawerStepHeader
                    step={recordOptions.length > 1 ? 3 : 2}
                    title="Variants"
                    subtitle={`${variants.length} variant${variants.length !== 1 ? 's' : ''} detected`}
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    {variantFields.map((field) => {
                      const rule = buildAlertRule({
                        path: `variants[*].${field}`,
                        label: `Any variant ${humanizeFieldName(field).toLowerCase()}`,
                      });
                      return (
                        <Button
                          key={field}
                          type="button"
                          variant={
                            rules.some(
                              (item) => alertRuleSignature(item) === alertRuleSignature(rule),
                            )
                              ? 'action'
                              : 'neutral'
                          }
                          size="sm"
                          onClick={() => toggleRule(rule)}
                        >
                          <Bell className="size-3.5" />
                          Any {humanizeFieldName(field)}
                        </Button>
                      );
                    })}
                  </div>
                  <div className="mt-3 space-y-2">
                    {visibleVariants.map((variant, index) => {
                      const hasActiveRule = variantFields.some((field) => {
                        const rule = buildAlertRule({
                          path: `variants[*].${field}`,
                          label: '',
                          variant_match: variantMatch(variant),
                        });
                        return rules.some(
                          (item) => alertRuleSignature(item) === alertRuleSignature(rule),
                        );
                      });
                      return (
                        <div
                          key={variantIdentity(variant, index)}
                          className={cn(
                            'border-border bg-panel rounded-md border p-3 transition-colors',
                            hasActiveRule && 'border-l-accent border-l-2',
                          )}
                        >
                          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
                            <span className="text-foreground type-body-sm font-semibold">
                              {variantTitle(variant, index)}
                            </span>
                            <Badge tone="neutral">
                              {formatAlertValue(
                                variant.availability ?? variant.price ?? variant.sku,
                              )}
                            </Badge>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {visibleVariantFields.map((field) => {
                              const rule = buildAlertRule({
                                path: `variants[*].${field}`,
                                label: `${variantTitle(variant, index)} ${humanizeFieldName(field).toLowerCase()}`,
                                variant_match: variantMatch(variant),
                              });
                              return (
                                <Button
                                  key={field}
                                  type="button"
                                  size="sm"
                                  variant={
                                    rules.some(
                                      (item) =>
                                        alertRuleSignature(item) === alertRuleSignature(rule),
                                    )
                                      ? 'action'
                                      : 'quiet'
                                  }
                                  onClick={() => toggleRule(rule)}
                                >
                                  {humanizeFieldName(field)}
                                </Button>
                              );
                            })}
                            {hiddenVariantFieldCount > 0 ? (
                              <span className="text-muted type-body-sm inline-flex h-8 items-center px-1.5">
                                and {hiddenVariantFieldCount} more…
                              </span>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                    {hiddenVariantCount > 0 ? (
                      <div className="text-muted type-body-sm px-1.5 py-1">
                        and {hiddenVariantCount} more…
                      </div>
                    ) : null}
                  </div>
                </section>
              ) : null}

              <hr className="border-border" />

              <section>
                <DrawerStepHeader
                  step={
                    recordOptions.length > 1 ? (variants.length ? 4 : 3) : variants.length ? 3 : 2
                  }
                  title="Active Rules"
                  subtitle={
                    rules.length
                      ? `${rules.length} rule${rules.length !== 1 ? 's' : ''} configured`
                      : undefined
                  }
                />
                {rules.length ? (
                  <div className="mt-3 space-y-2">
                    {rules.map((rule) => (
                      <div
                        key={rule.id}
                        className="border-border bg-panel grid gap-3 rounded-md border p-3.5 md:grid-cols-[1fr_150px_140px_auto]"
                      >
                        <div className="min-w-0">
                          <div className="text-foreground type-body-sm truncate font-semibold">
                            {rule.label || rule.path}
                          </div>
                          <div className="text-muted type-body-sm mt-0.5 truncate">{rule.path}</div>
                        </div>
                        <Dropdown
                          value={rule.operator || 'changed'}
                          onChange={(operator) => updateRule(rule.id, { operator })}
                          options={alertOperatorOptions}
                          ariaLabel="Operator"
                          size="sm"
                          portal={false}
                        />
                        {needsAlertRuleValue(rule.operator) ? (
                          <Input
                            value={String(rule.value ?? '')}
                            onChange={(event) => updateRule(rule.id, { value: event.target.value })}
                            placeholder="Value"
                          />
                        ) : (
                          <div />
                        )}
                        <Button
                          type="button"
                          variant="quiet"
                          size="icon"
                          aria-label="Remove rule"
                          onClick={() =>
                            setValue(
                              'rules',
                              rules.filter((item) => item.id !== rule.id),
                              { shouldValidate: true },
                            )
                          }
                        >
                          <X className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3">
                    <InlineAlert
                      tone="warning"
                      message="Click product fields or variant attributes above to add alert rules."
                    />
                  </div>
                )}
              </section>

              <section className="bg-background-alt rounded-lg p-4">
                <h3 className="type-body-sm text-foreground mb-3 flex items-center gap-2 font-semibold">
                  <Clock className="text-muted size-4" />
                  Alert Settings
                </h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="grid gap-1.5">
                    <span className="field-label">Poll Interval</span>
                    <Dropdown
                      value={pollInterval}
                      onChange={(value) =>
                        setValue('pollInterval', value, { shouldValidate: true })
                      }
                      options={alertIntervalOptions}
                      ariaLabel="Poll Interval"
                      portal={false}
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <span className="field-label">Webhook URL</span>
                    <Input
                      value={webhookUrl}
                      onChange={(event) =>
                        setValue('webhookUrl', event.target.value, { shouldValidate: true })
                      }
                      placeholder="https://agent.example/webhook"
                    />
                  </div>
                </div>
              </section>
            </div>
          </div>

          <div className="border-border bg-background flex-none border-t px-6 py-4">
            <div className="flex items-center justify-between">
              <span className="type-body-sm text-muted">
                {rules.length
                  ? `${rules.length} rule${rules.length !== 1 ? 's' : ''} selected`
                  : 'No rules selected'}
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="quiet"
                  onClick={() => onOpenChange(false)}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  onClick={() => void handleSubmit(createAlert)()}
                  disabled={isSubmitting || !rules.length}
                >
                  {isSubmitting ? 'Creating...' : 'Create Alert'}
                </Button>
              </div>
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function DrawerStepHeader({
  step,
  title,
  subtitle,
}: Readonly<{ step: number; title: string; subtitle?: string }>) {
  return (
    <div className="flex items-center gap-3">
      <span className="bg-accent text-accent-fg inline-flex size-6 items-center justify-center rounded-full text-xs font-bold">
        {step}
      </span>
      <div className="min-w-0">
        <h3 className="type-heading-3 m-0">{title}</h3>
        {subtitle ? <p className="text-muted type-body-sm m-0">{subtitle}</p> : null}
      </div>
    </div>
  );
}

function AlertFieldCard({
  active,
  label,
  value,
  onClick,
}: Readonly<{ active: boolean; label: string; value: string; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'group border-border bg-panel rounded-md border p-3.5 text-left transition-all',
        'hover:shadow-card hover:border-accent/50',
        active && 'border-accent bg-accent-subtle shadow-card',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-foreground type-body-sm block font-semibold">{label}</span>
        {active ? (
          <span className="bg-accent text-accent-fg inline-flex size-5 shrink-0 items-center justify-center rounded-full">
            <Check className="size-3" />
          </span>
        ) : (
          <span className="border-border group-hover:border-accent/40 inline-flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors" />
        )}
      </div>
      <span className="text-secondary type-body-sm mt-1.5 block truncate">{value}</span>
    </button>
  );
}

function buildAlertRule(rule: Omit<AlertRuleDraft, 'id' | 'operator'> & { operator?: string }) {
  return {
    ...rule,
    id: `${rule.path}:${JSON.stringify(rule.variant_match ?? {})}`,
    operator: rule.operator ?? 'changed',
  };
}

function alertRuleSignature(rule: AlertTargetRule) {
  return `${rule.path}:${JSON.stringify(rule.variant_match ?? {})}`;
}

function needsAlertRuleValue(operator: string | undefined) {
  return ['equals', 'not_equals', 'less_than', 'greater_than'].includes(operator ?? '');
}

function alertTargetFields(rules: AlertTargetRule[]) {
  return uniqueStrings(
    rules.map((rule) =>
      rule.path.startsWith('variants[*].') ? 'variants' : rule.path.split('.')[0],
    ),
  );
}

function recordData(record: CrawlRecord | undefined) {
  return record?.data && typeof record.data === 'object'
    ? (record.data as Record<string, unknown>)
    : {};
}

function productVariants(data: Record<string, unknown>) {
  return Array.isArray(data.variants)
    ? data.variants.flatMap((item) =>
        isRecordObject(item) ? [item as Record<string, unknown>] : [],
      )
    : [];
}

function alertRootFields(data: Record<string, unknown>) {
  const preferred = ['price', 'availability', 'sku', 'title', 'brand', 'currency', 'image_url'];
  return preferred.filter(
    (field) => data[field] !== undefined && !isEmptyCandidateValue(data[field]),
  );
}

function alertVariantFields(variants: Array<Record<string, unknown>>) {
  const preferred = ['availability', 'price', 'sku', 'size', 'color', 'currency'];
  const present = new Set<string>();
  variants.forEach((variant) => {
    preferred.forEach((field) => {
      if (variant[field] !== undefined && !isEmptyCandidateValue(variant[field])) {
        present.add(field);
      }
    });
  });
  return preferred.filter((field) => present.has(field));
}

function variantMatch(variant: Record<string, unknown>) {
  if (variant.sku) return { sku: variant.sku };
  const match: Record<string, unknown> = {};
  if (variant.size) match.size = variant.size;
  if (variant.color) match.color = variant.color;
  if (Object.keys(match).length) return match;
  if (variant.url) return { url: variant.url };
  return null;
}

function variantIdentity(variant: Record<string, unknown>, index: number) {
  return String(
    variant.sku || variant.url || `${variant.size || ''}:${variant.color || ''}:${index}`,
  );
}

function variantTitle(variant: Record<string, unknown>, index: number) {
  const parts = [variant.size, variant.color, variant.sku].filter(Boolean).map(String);
  return parts.length ? parts.join(' · ') : `Variant ${index + 1}`;
}

function alertRecordLabel(record: CrawlRecord) {
  const data = recordData(record);
  return String(data.title || data.sku || data.url || record.source_url || `Record ${record.id}`);
}

function alertRecordUrl(record: CrawlRecord | undefined, run: CrawlRun | undefined) {
  if (!record) return '';
  const data = recordData(record);
  return String(data.url || record.source_url || run?.url || '');
}

function formatAlertValue(value: unknown) {
  if (value === null || value === undefined || value === '') return 'empty';
  if (Array.isArray(value)) return `${value.length} items`;
  if (isRecordObject(value)) return JSON.stringify(value);
  return String(value);
}

function isRecordObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
