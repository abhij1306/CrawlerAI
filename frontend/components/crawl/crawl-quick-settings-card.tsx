import { Globe, Info, SlidersHorizontal, Sparkles } from 'lucide-react';

import type { CrawlDomain, CrawlSurface } from '../../lib/api/types';
import { surfaceLabel } from '../../lib/format/domain';
import { Card, Dropdown, Textarea, Toggle, Tooltip } from '../ui/primitives';
import { TabBar } from '../ui/patterns';
import type { StudioMode } from './crawl-config-logic';
import {
  RUN_SETUP_CONTROL_CLASS,
  RUN_SETUP_LABEL_CLASS,
  RUN_SETUP_ROW_CLASS,
  RUN_SETUP_TOGGLE_ROW_CLASS,
  SECTION_CARD_HEADER_CLASS,
  SECTION_CARD_TITLE_CLASS,
} from './crawl-config-state';
import { StudioChip } from './shared';
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
          <header className={SECTION_CARD_HEADER_CLASS}>
            <span className={SECTION_CARD_TITLE_CLASS}>Crawl Settings</span>
            <StudioChip>{studioMode === 'advanced' ? 'Advanced' : 'Quick'}</StudioChip>
          </header>
          <div className="flex flex-col px-6 pt-4 pb-6">
            <div className={RUN_SETUP_ROW_CLASS}>
              <div className={RUN_SETUP_LABEL_CLASS}>
                <Globe className="size-4 shrink-0 text-muted" />
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
                <SlidersHorizontal className="size-4 shrink-0 text-muted" />
                <div className="flex items-center gap-1.5">
                  <div className="type-body-sm font-semibold text-foreground">Mode</div>
                  <Tooltip content="Advanced Mode exposes the full fetch, locality, diagnostics, and selector controls.">
                    <button
                      type="button"
                      aria-label="More information"
                      className="focus-ring inline-flex rounded-sm"
                    >
                      <Info
                        aria-hidden="true"
                        className="size-3.5 cursor-help text-subtle transition-colors hover:text-secondary"
                      />
                    </button>
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

            <div className={RUN_SETUP_TOGGLE_ROW_CLASS}>
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 shrink-0 text-muted" />
                <span className="type-body-sm font-semibold text-foreground">LLM Processing</span>
                <Tooltip content="Per-run enrichment only. This does not overwrite saved domain defaults.">
                  <button
                    type="button"
                    aria-label="More information"
                    className="focus-ring inline-flex rounded-sm"
                  >
                    <Info
                      aria-hidden="true"
                      className="size-3.5 cursor-help text-subtle transition-colors hover:text-secondary"
                    />
                  </button>
                </Tooltip>
              </div>
              <Toggle
                checked={smartExtraction}
                onChange={onSmartExtractionChange}
                ariaLabel="LLM Processing"
              />
            </div>

            <div className={RUN_SETUP_TOGGLE_ROW_CLASS}>
              <div className="flex items-center gap-2">
                <Globe className="size-4 shrink-0 text-muted" />
                <span className="type-body-sm font-semibold text-foreground">Proxy List</span>
                <Tooltip content={'Example:\nhttp://host:port\nhttp://user:pass@host:port'}>
                  <button
                    type="button"
                    aria-label="More information"
                    className="focus-ring inline-flex rounded-sm"
                  >
                    <Info
                      aria-hidden="true"
                      className="size-3.5 cursor-help text-subtle transition-colors hover:text-secondary"
                    />
                  </button>
                </Tooltip>
              </div>
              <Toggle
                checked={proxyEnabled}
                onChange={onProxyEnabledChange}
                ariaLabel="Proxy List enabled"
              />
            </div>

            {proxyEnabled ? (
              <div className="mt-3 ml-8 flex flex-col gap-4">
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
              <div className="type-body mt-4 leading-relaxed text-secondary">
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
