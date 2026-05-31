'use client';

import { CheckCircle2, CircleAlert, GripVertical, Info, RotateCcw, Trash2, X } from 'lucide-react';
import React from 'react';
import { useId, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';

import { Button, Input, Tooltip, Toggle as PrimitiveToggle } from '../ui/primitives';
import { cn } from '../../lib/utils';
import { clampNumber, parseLines } from '../../lib/crawl/format';
import {
  cleanRequestedField,
  uniqueRequestedFields,
  validateAdditionalFieldName,
} from '../../lib/crawl/fields';

export type ValidationState = 'idle' | 'valid' | 'invalid';
export type FieldRow = {
  id: string;
  fieldName: string;
  cssSelector: string;
  xpath: string;
  regex: string;
  cssState: ValidationState;
  xpathState: ValidationState;
  regexState: ValidationState;
};
export type FieldRowMessageTone = 'success' | 'warning' | 'danger';
type IconElementProps = {
  className?: string;
};
export function SettingSection({
  label,
  description,
  icon,
  checked,
  onChange,
  children,
  rowClassName,
  bodyClassName,
}: Readonly<{
  label: string;
  description: string;
  icon?: ReactElement<IconElementProps>;
  checked: boolean;
  onChange: (value: boolean) => void;
  children?: ReactNode;
  rowClassName?: string;
  bodyClassName?: string;
}>) {
  const renderedIcon = React.isValidElement<IconElementProps>(icon)
    ? React.cloneElement(icon, {
        className: cn(icon.props.className, 'size-4'),
      })
    : null;

  return (
    // Outer wrapper is flex-col so the children panel is a sibling of the control row,
    // not a child inside the h-9 constraint that would clip it.
    <div className="w-full">
      <div
        className={cn(
          'grid h-9 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3',
          rowClassName,
        )}
      >
        <div className="flex min-w-0 items-center gap-1.5">
          {renderedIcon ? (
            <div
              className={cn(
                'flex size-8 shrink-0 items-center justify-center rounded-md border transition-colors',
                checked
                  ? 'bg-setting-icon-active-bg text-accent shadow-setting-icon-active border-[color:color-mix(in_srgb,var(--accent)_22%,transparent)]'
                  : 'border-border bg-setting-icon-bg text-secondary',
              )}
            >
              {renderedIcon}
            </div>
          ) : null}
          <div className="type-body-sm text-foreground min-w-0 font-semibold">{label}</div>
          <Tooltip content={description}>
            <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
          </Tooltip>
        </div>
        <div className="flex justify-start">
          <PrimitiveToggle checked={checked} onChange={onChange} ariaLabel={label} />
        </div>
      </div>
      {/* Children panel as sibling — can animate height freely */}
      {children ? (
        <div
          className={cn(
            'transition-[max-height] duration-200 ease-out',
            checked ? 'max-h-[500px] overflow-visible' : 'max-h-0 overflow-hidden',
          )}
        >
          <div
            className={cn(
              'border-divider bg-setting-body-bg space-y-3 border-t px-5 py-4',
              bodyClassName,
            )}
          >
            {children}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function SliderRow({
  label,
  description,
  value,
  min,
  max,
  step,
  onChange,
  onReset,
  suffix,
}: Readonly<{
  label: string;
  description?: string;
  value: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: string) => void;
  onReset: () => void;
  suffix?: string;
}>) {
  return (
    <div
      className={cn('grid w-full gap-2.5 md:grid-cols-[160px_minmax(0,1fr)_100px] md:items-center')}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="type-body-sm text-foreground font-semibold">{label}</span>
        {description ? (
          <Tooltip content={description}>
            <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
          </Tooltip>
        ) : null}
        <button
          type="button"
          onClick={onReset}
          aria-label={`Reset ${label}`}
          className="text-muted hover:text-primary transition-colors"
        >
          <RotateCcw className="size-3" aria-hidden="true" />
        </button>
      </div>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={clampNumber(value, min, max, min)}
        onChange={(event) => onChange(event.target.value)}
        className="slider-control w-full"
      />
      <div className="relative">
        <Input
          type="text"
          inputMode="numeric"
          value={value}
          onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ''))}
          onBlur={() => onChange(String(clampNumber(value, min, max, min)))}
          className="pr-8 text-right font-mono tabular-nums"
        />
        {suffix ? (
          <span className="type-caption pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 lowercase">
            {suffix}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function AdditionalFieldInput({
  value,
  fields,
  onChange,
  onCommit,
  onRemove,
}: Readonly<{
  value: string;
  fields: string[];
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
  onRemove: (value: string) => void;
}>) {
  const chips = uniqueRequestedFields([...fields, ...parseLines(value.replace(/,/g, '\n'))]);
  const [validationHint, setValidationHint] = useState<string | null>(null);

  function commitField(candidate: string) {
    const cleaned = cleanRequestedField(candidate);
    if (!cleaned) {
      return;
    }
    const validationError = validateAdditionalFieldName(cleaned);
    if (validationError) {
      setValidationHint(`Skipped "${cleaned}": ${validationError}`);
      return;
    }
    onCommit(cleaned);
  }

  function handleChange(next: string) {
    const parts = next.split(',');
    parts.slice(0, -1).forEach(commitField);
    setValidationHint(null);
    onChange(parts.at(-1) ?? '');
  }

  function commitPendingFields() {
    parseLines(value).forEach(commitField);
    onChange('');
  }

  return (
    <label htmlFor="additional-fields-input" className="grid gap-1.5">
      <span className="type-body-sm text-foreground font-semibold">Additional Fields</span>
      <Input
        id="additional-fields-input"
        value={value}
        onChange={(event) => handleChange(event.target.value)}
        onBlur={commitPendingFields}
        placeholder="price, sku, Features & Benefits, Product Story"
        className="font-mono"
      />
      {validationHint ? <p className="text-danger type-caption">{validationHint}</p> : null}
      {chips.length ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((field) => (
            <button
              key={field}
              type="button"
              onClick={() => onRemove(field)}
              aria-label={`Remove ${field}`}
              className="border-subtle-panel-border bg-subtle-panel text-secondary type-body-sm inline-flex items-center gap-1 rounded-sm border px-2 py-1"
            >
              <X className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{field}</span>
            </button>
          ))}
        </div>
      ) : null}
    </label>
  );
}

export function SitemapConfigFields({
  domain,
  filterKeyword,
  maxUrls,
  onDomainChange,
  onFilterKeywordChange,
  onMaxUrlsChange,
}: Readonly<{
  domain: string;
  filterKeyword: string;
  maxUrls: number;
  onDomainChange: (value: string) => void;
  onFilterKeywordChange: (value: string) => void;
  onMaxUrlsChange: (value: number) => void;
}>) {
  return (
    <div className="grid gap-4">
      <label htmlFor="sitemap-domain" className="grid gap-2">
        <span className="type-control font-medium">Site Domain</span>
        <Input
          id="sitemap-domain"
          value={domain}
          onChange={(event) => onDomainChange(event.target.value)}
          placeholder="example.com or https://example.com/sitemap.xml"
          className="font-mono"
          aria-label="Sitemap domain input"
        />
        <span className="type-caption">App will auto-discover sitemap from this domain.</span>
      </label>

      <label htmlFor="sitemap-filter" className="grid gap-2">
        <span className="type-control flex items-center gap-1.5 font-medium">
          Collection Filter
          <Tooltip content="Only child sitemaps whose filename contains this keyword will be crawled. For Shopify use collections. For WooCommerce or Magento use category.">
            <Info className="text-muted size-3.5 cursor-help" />
          </Tooltip>
        </span>
        <Input
          id="sitemap-filter"
          value={filterKeyword}
          onChange={(event) => onFilterKeywordChange(event.target.value)}
          placeholder="collections"
          className="font-mono"
          aria-label="Sitemap filter keyword input"
        />
      </label>

      <label htmlFor="sitemap-max-urls" className="grid gap-2">
        <span className="type-control flex items-center gap-1.5 font-medium">
          Max Category URLs
          <Tooltip content="Maximum number of category URLs to crawl from the sitemap.">
            <Info className="text-muted size-3.5 cursor-help" />
          </Tooltip>
        </span>
        <Input
          id="sitemap-max-urls"
          type="number"
          min={1}
          max={2000}
          value={maxUrls}
          onChange={(event) => {
            const parsed = parseInt(event.target.value, 10);
            const nextValue = Number.isNaN(parsed) ? maxUrls || 1 : parsed;
            onMaxUrlsChange(Math.min(2000, Math.max(1, nextValue)));
          }}
          aria-label="Sitemap max URLs input"
        />
      </label>
    </div>
  );
}

export function TargetUrlField({
  value,
  placeholder,
  onChange,
}: Readonly<{
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}>) {
  return (
    <label htmlFor="target-url-input" className="grid gap-2">
      <span className="type-control font-medium">Target URL</span>
      <Input
        id="target-url-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="font-mono"
        placeholder={placeholder}
        aria-label="Target URL input"
      />
    </label>
  );
}

export function CsvFileField({
  file,
  onChange,
}: Readonly<{
  file: File | null;
  onChange: (file: File | null) => void;
}>) {
  return (
    <label className="grid gap-2">
      <span className="type-control font-medium">CSV File</span>
      <div className="flex items-center gap-4">
        <input
          id="csv-file-input"
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => onChange(event.target.files?.[0] ?? null)}
          className="sr-only"
          aria-label="CSV file input"
        />
        <label
          htmlFor="csv-file-input"
          className="ui-on-accent-surface bg-accent hover:bg-accent-hover type-control cursor-pointer rounded-md px-3 py-1.5 transition-colors"
        >
          Choose file
        </label>
        <span className="text-muted type-body">{file ? file.name : 'No file chosen'}</span>
      </div>
    </label>
  );
}

export function ManualFieldEditor({
  row,
  onChange,
  onDelete,
  onTest,
  testing = false,
  testDisabled = false,
  message,
  messageTone = 'warning',
  showLabels = true,
}: Readonly<{
  row: FieldRow;
  onChange: (patch: Partial<FieldRow>) => void;
  onDelete: () => void;
  onTest?: () => void;
  testing?: boolean;
  testDisabled?: boolean;
  message?: string;
  messageTone?: FieldRowMessageTone;
  showLabels?: boolean;
}>) {
  const fieldNameId = useId();
  return (
    <div className="border-border card-gradient space-y-1.5 rounded-md border p-2.5">
      <div className="grid gap-2 xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
        <div className="text-muted/50 hidden items-center justify-center xl:flex">
          <GripVertical className="size-3.5" />
        </div>
        <label htmlFor={fieldNameId} className="grid gap-1">
          <span className={cn('field-label', !showLabels && 'sr-only')}>Field</span>
          <Input
            id={fieldNameId}
            aria-label="Field"
            value={row.fieldName}
            onChange={(event) => onChange({ fieldName: event.target.value })}
            placeholder="price"
            className="type-body-sm h-8"
          />
        </label>
        <ValidatedField
          label="CSS"
          value={row.cssSelector}
          state={row.cssState}
          placeholder=".price"
          showLabel={showLabels}
          onChange={(value) => onChange({ cssSelector: value })}
          onBlur={(value) => onChange({ cssState: validateCssSelector(value) })}
        />
        <ValidatedField
          label="XPath"
          value={row.xpath}
          state={row.xpathState}
          placeholder="//span[@class='price']"
          showLabel={showLabels}
          onChange={(value) => onChange({ xpath: value })}
          onBlur={(value) => onChange({ xpathState: validateXPath(value) })}
        />
        <ValidatedField
          label="Regex"
          value={row.regex}
          state={row.regexState}
          placeholder="\\$[\\d,.]+"
          showLabel={showLabels}
          onChange={(value) => onChange({ regex: value })}
          onBlur={(value) => onChange({ regexState: validateRegex(value) })}
        />
        <div className="flex items-end justify-end">
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {onTest ? (
              <Button
                type="button"
                variant="neutral"
                size="sm"
                onClick={onTest}
                disabled={testing || testDisabled}
                className="min-w-[64px]"
              >
                {testing ? '...' : 'Test'}
              </Button>
            ) : null}
            <button
              type="button"
              onClick={onDelete}
              aria-label={`Delete ${row.fieldName || 'manual field'}`}
              className="surface-muted text-danger/70 hover:bg-danger/10 hover:text-danger inline-flex size-8 items-center justify-center rounded-md"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
      {message ? (
        <div
          className={cn(
            'alert-surface type-caption px-2.5 py-1.5',
            messageTone === 'success' && 'alert-success',
            messageTone === 'warning' && 'alert-warning',
            messageTone === 'danger' && 'alert-danger',
          )}
        >
          {message}
        </div>
      ) : null}
    </div>
  );
}

export function FieldEditorHeader() {
  return (
    <div className="hidden items-center gap-2 px-3 py-1.5 xl:grid xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
      <div />
      <div className="flex items-center gap-1.5">
        <span className="field-label">Field</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="field-label">CSS</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="field-label">XPath</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="field-label">Regex</span>
      </div>
      <span className="field-label text-right">Actions</span>
    </div>
  );
}

function ValidatedField({
  label,
  value,
  state,
  placeholder,
  onChange,
  onBlur,
  showLabel = true,
}: Readonly<{
  label: string;
  value: string;
  state: ValidationState;
  placeholder: string;
  onChange: (value: string) => void;
  onBlur: (value: string) => void;
  showLabel?: boolean;
}>) {
  return (
    <label className="grid gap-1">
      <span className={cn('field-label', !showLabel && 'sr-only')}>{label}</span>
      <div className="relative">
        <Input
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={(event) => onBlur(event.target.value)}
          placeholder={placeholder}
          className="type-body-sm h-8 pr-9"
        />
        <div className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center">
          {state === 'valid' ? <CheckCircle2 className="text-success/80 size-3.5" /> : null}
          {state === 'invalid' ? <CircleAlert className="text-danger/80 size-3.5" /> : null}
        </div>
      </div>
    </label>
  );
}

function validateXPath(value: string): ValidationState {
  if (!value.trim()) return 'idle';
  try {
    globalThis.document?.evaluate(value, globalThis.document, null, XPathResult.ANY_TYPE, null);
    return 'valid';
  } catch {
    return 'invalid';
  }
}

function validateCssSelector(value: string): ValidationState {
  if (!value.trim()) return 'idle';
  try {
    globalThis.document?.querySelector(value);
    return 'valid';
  } catch {
    return 'invalid';
  }
}

function validateRegex(value: string): ValidationState {
  if (!value.trim()) return 'idle';
  try {
    new RegExp(value);
    return 'valid';
  } catch {
    return 'invalid';
  }
}
