import { Globe, Info, SlidersHorizontal, Sparkles } from 'lucide-react';

import type { CrawlDomain, CrawlSurface } from '../../lib/api/types';
import { Badge, Card, Dropdown, Textarea, Toggle, Tooltip } from '../ui/primitives';
import { TabBar } from '../ui/patterns';
import type { StudioMode } from './crawl-config-logic';
import { surfaceLabel } from './crawl-config-logic';
import {
  RUN_SETUP_CONTROL_CLASS,
  RUN_SETUP_LABEL_CLASS,
  RUN_SETUP_ROW_CLASS,
} from './crawl-config-state';
import { DOMAIN_OPTIONS } from './domain-surface-config';

type CrawlQuickSettingsCardProps = {
  crawlDomain: CrawlDomain;
  studioMode: StudioMode;
  smartExtraction: boolean;
  proxyEnabled: boolean;
  proxyInput: string;
  singleUrlMode: boolean;
  savedProfileLoaded: boolean;
  savedProfileDomain: string;
  surface: CrawlSurface;
  onDomainChange: (domain: CrawlDomain) => void;
  onStudioModeChange: (mode: StudioMode) => void;
  onSmartExtractionChange: (enabled: boolean) => void;
  onProxyEnabledChange: (enabled: boolean) => void;
  onProxyInputChange: (value: string) => void;
};

export function CrawlQuickSettingsCard({
  crawlDomain,
  studioMode,
  smartExtraction,
  proxyEnabled,
  proxyInput,
  singleUrlMode,
  savedProfileLoaded,
  savedProfileDomain,
  surface,
  onDomainChange,
  onStudioModeChange,
  onSmartExtractionChange,
  onProxyEnabledChange,
  onProxyInputChange,
}: Readonly<CrawlQuickSettingsCardProps>) {
  return (
    <div className="h-full xl:self-stretch">
      <div className="h-full xl:sticky xl:top-[68px]">
        <Card className="section-card h-full overflow-hidden p-0">
          <header className="flex h-10 items-center justify-between border-b border-border bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
            <span className="type-heading-3">Crawl Settings</span>
            <Badge tone="accent" className="h-5 px-1.5 text-xs font-medium">
              {studioMode === 'advanced' ? 'Advanced' : 'Quick'}
            </Badge>
          </header>
          <div className="page-stack px-6 pt-4 pb-6">
            <div className={RUN_SETUP_ROW_CLASS}>
              <div className={RUN_SETUP_LABEL_CLASS}>
                <Globe className="size-4 shrink-0 text-accent" />
                <div className="type-body-sm font-semibold text-foreground">Domain</div>
              </div>
              <Dropdown<CrawlDomain>
                ariaLabel="Domain"
                value={crawlDomain}
                className={RUN_SETUP_CONTROL_CLASS}
                onChange={(value) => {
                  if (DOMAIN_OPTIONS.some((option) => option.value === value)) {
                    onDomainChange(value);
                  }
                }}
                options={DOMAIN_OPTIONS}
              />
            </div>
            <div className={RUN_SETUP_ROW_CLASS}>
              <div className={RUN_SETUP_LABEL_CLASS}>
                <SlidersHorizontal className="size-4 shrink-0 text-accent" />
                <div className="flex items-center gap-1.5">
                  <div className="type-body-sm font-semibold text-foreground">Mode</div>
                  <Tooltip content="Advanced Mode exposes the full fetch, locality, diagnostics, and selector controls.">
                    <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
                  </Tooltip>
                </div>
              </div>
              <TabBar
                value={studioMode}
                compact
                className={RUN_SETUP_CONTROL_CLASS}
                onChange={(value) => {
                  if (value === 'quick' || value === 'advanced') onStudioModeChange(value);
                }}
                options={[
                  { value: 'quick', label: 'Quick' },
                  { value: 'advanced', label: 'Advanced' },
                ]}
              />
            </div>

            <div className="flex h-[var(--control-height)] items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 shrink-0 text-accent" />
                <span className="type-body-sm font-semibold text-foreground">LLM Processing</span>
                <Tooltip content="Per-run enrichment only. This does not overwrite saved domain defaults.">
                  <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
                </Tooltip>
              </div>
              <Toggle
                checked={smartExtraction}
                onChange={onSmartExtractionChange}
                ariaLabel="LLM Processing"
              />
            </div>

            <div className="border-t border-border pt-4">
              <div className="flex h-[var(--control-height)] items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Globe className="size-4 shrink-0 text-accent" />
                  <span className="type-body-sm font-semibold text-foreground">Proxy List</span>
                  <Tooltip content={'Example:\nhttp://host:port\nhttp://user:pass@host:port'}>
                    <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
                  </Tooltip>
                </div>
                <Toggle
                  checked={proxyEnabled}
                  onChange={onProxyEnabledChange}
                  ariaLabel="Proxy List enabled"
                />
              </div>
            </div>

            {proxyEnabled ? (
              <div className="ml-8 flex flex-col gap-4">
                <div className="type-body-sm font-semibold text-foreground">Proxy URLs</div>
                <Textarea
                  value={proxyInput}
                  onChange={(event) => onProxyInputChange(event.target.value)}
                  placeholder={'http://host:port\nhttp://user:pass@host:port'}
                  className="min-h-[104px] font-mono leading-relaxed"
                  aria-label="Proxy pool input"
                />
              </div>
            ) : null}

            {singleUrlMode && savedProfileLoaded ? (
              <div className="type-body leading-relaxed text-secondary">
                Saved domain profile active:{' '}
                <span className="type-label-mono text-foreground">{savedProfileDomain}</span> ·{' '}
                {surfaceLabel(surface)}
              </div>
            ) : null}
          </div>
        </Card>
      </div>
    </div>
  );
}
