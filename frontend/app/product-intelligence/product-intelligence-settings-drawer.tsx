'use client';

import { X } from 'lucide-react';
import { useEffect } from 'react';

import { Button, Dropdown, Field, Input, Textarea } from '../../components/ui/primitives';
import type { ProductIntelligenceOptions } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { SEARCH_PROVIDER_OPTIONS } from './product-intelligence-components';

export function SettingsDrawer({
  open,
  onClose,
  options,
  onOptionsChange,
  allowedDomainsText,
  onAllowedDomainsTextChange,
  excludedDomainsText,
  onExcludedDomainsTextChange,
  maxSourceProductsLimit,
  maxCandidatesPerProductLimit,
  defaultOptions,
}: Readonly<{
  open: boolean;
  onClose: () => void;
  options: ProductIntelligenceOptions;
  onOptionsChange: (patch: Partial<ProductIntelligenceOptions>) => void;
  allowedDomainsText: string;
  onAllowedDomainsTextChange: (value: string) => void;
  excludedDomainsText: string;
  onExcludedDomainsTextChange: (value: string) => void;
  maxSourceProductsLimit: number;
  maxCandidatesPerProductLimit: number;
  defaultOptions: ProductIntelligenceOptions;
}>) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div className="border-divider bg-background-elevated animate-in slide-in-from-right-4 fixed top-0 right-0 z-50 h-full w-[380px] max-w-full overflow-y-auto border-l p-5 shadow-xl duration-200">
        <div className="flex items-center justify-between">
          <h2 className="text-foreground type-heading text-sm font-medium">Configuration</h2>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
            aria-label="Close settings"
          >
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="mt-4 space-y-4">
          <ProviderField options={options} onOptionsChange={onOptionsChange} />
          <Field label="Max Sources">
            <Input
              type="number"
              min={1}
              max={maxSourceProductsLimit}
              value={options.max_source_products}
              onChange={(event) =>
                onOptionsChange({
                  max_source_products: clampInt(
                    event.target.value,
                    1,
                    maxSourceProductsLimit,
                    defaultOptions.max_source_products,
                  ),
                })
              }
            />
          </Field>
          <Field label="Max URLs">
            <Input
              type="number"
              min={1}
              max={maxCandidatesPerProductLimit}
              value={options.max_candidates_per_product}
              onChange={(event) =>
                onOptionsChange({
                  max_candidates_per_product: clampInt(
                    event.target.value,
                    1,
                    maxCandidatesPerProductLimit,
                    defaultOptions.max_candidates_per_product,
                  ),
                })
              }
            />
          </Field>
          <Field label="Private Label">
            <Dropdown
              value={options.private_label_mode}
              onChange={(value) =>
                onOptionsChange({
                  private_label_mode: value as ProductIntelligenceOptions['private_label_mode'],
                })
              }
              options={[
                { value: 'flag', label: 'Flag' },
                { value: 'exclude', label: 'Exclude' },
                { value: 'include', label: 'Include' },
              ]}
            />
          </Field>
          <Field label="LLM Cleanup">
            <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 shadow-sm">
              <span className="text-muted text-xs font-normal">Enable Enrichment</span>
              <input
                type="checkbox"
                checked={options.llm_enrichment_enabled}
                onChange={(event) =>
                  onOptionsChange({ llm_enrichment_enabled: event.target.checked })
                }
                className="border-divider text-accent focus:ring-accent h-3.5 w-3.5 rounded"
              />
            </div>
          </Field>
          <Field label="Allowed Domains">
            <Textarea
              value={allowedDomainsText}
              onChange={(event) => onAllowedDomainsTextChange(event.target.value)}
              className="min-h-[76px] text-xs"
              placeholder="ralphlauren.com"
            />
          </Field>
          <Field label="Excluded Domains">
            <Textarea
              value={excludedDomainsText}
              onChange={(event) => onExcludedDomainsTextChange(event.target.value)}
              className="min-h-[76px] text-xs"
              placeholder="amazon.com"
            />
          </Field>
        </div>
      </div>
    </>
  );
}

function ProviderField({
  options,
  onOptionsChange,
}: {
  options: ProductIntelligenceOptions;
  onOptionsChange: (patch: Partial<ProductIntelligenceOptions>) => void;
}) {
  return (
    <Field label="Provider">
      <div className="flex gap-1.5">
        {SEARCH_PROVIDER_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onOptionsChange({ search_provider: option.value })}
            aria-pressed={options.search_provider === option.value}
            className={cn(
              'flex-1 rounded-[var(--radius-md)] border px-3 py-1.5 text-center text-sm font-medium transition-[background-color,border-color]',
              options.search_provider === option.value
                ? 'border-accent bg-accent-subtle text-accent'
                : 'border-border-strong bg-background-elevated text-foreground hover:bg-background-alt',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </Field>
  );
}

function clampInt(value: unknown, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}
