import { AppDrawer } from '../../components/ui/dialog';
import { Dropdown, Field, Input, Textarea } from '../../components/ui/primitives';
import type { ProductIntelligenceOptions } from '../../lib/api/product-intelligence';
import { cn } from '../../lib/utils';
import { clampInt, SEARCH_PROVIDER_OPTIONS } from './product-intelligence-utils';

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
  return (
    <AppDrawer
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
      title="Configuration"
    >
      <div className="space-y-4 p-5">
        <ProviderField options={options} onOptionsChange={onOptionsChange} />
        <Field label="Max Sources">
          <Input
            type="number"
            min={1}
            max={maxSourceProductsLimit}
            value={options.max_source_products}
            onChange={(event) =>
              onOptionsChange({
                max_source_products: Number(event.target.value),
              })
            }
            onBlur={(event) =>
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
                max_candidates_per_product: Number(event.target.value),
              })
            }
            onBlur={(event) =>
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
            ariaLabel="Private Label"
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
          <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-md px-3 shadow-sm">
            <span className="text-sm font-normal text-muted">Enable Enrichment</span>
            <input
              type="checkbox"
              aria-label="Enable LLM enrichment"
              checked={options.llm_enrichment_enabled}
              onChange={(event) =>
                onOptionsChange({ llm_enrichment_enabled: event.target.checked })
              }
              className="size-3.5 rounded border-divider text-accent focus:ring-accent"
            />
          </div>
        </Field>
        <Field label="Allowed Domains">
          <Textarea
            value={allowedDomainsText}
            onChange={(event) => onAllowedDomainsTextChange(event.target.value)}
            className="min-h-[76px] text-sm"
            placeholder="ralphlauren.com"
          />
        </Field>
        <Field label="Excluded Domains">
          <Textarea
            value={excludedDomainsText}
            onChange={(event) => onExcludedDomainsTextChange(event.target.value)}
            className="min-h-[76px] text-sm"
            placeholder="amazon.com"
          />
        </Field>
      </div>
    </AppDrawer>
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
              'flex-1 rounded-md border px-3 py-1.5 text-center text-sm font-medium transition-[background-color,border-color]',
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
