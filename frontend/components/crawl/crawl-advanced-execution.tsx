import { Info } from 'lucide-react';

import type { DomainRunProfile } from '../../lib/api/types';
import { Dropdown, Tooltip } from '../ui/primitives';
import { SettingSection } from './form-fields';
import {
  BROWSER_ENGINE_OPTIONS,
  EXTRACTION_SOURCE_OPTIONS,
  FETCH_MODE_OPTIONS,
  JS_MODE_OPTIONS,
  TRAVERSAL_MODE_OPTIONS,
  type BrowserEngine,
  type ExtractionSource,
  type FetchMode,
  type JsMode,
  type TraversalDropdownValue,
} from './crawl-config-logic';
import {
  ADVANCED_COLUMN_CLASS,
  ADVANCED_CONTROL_ROW_CLASS,
  ADVANCED_SECTION_TITLE_CLASS,
  ADVANCED_SUBSECTION_CLASS,
} from './crawl-config-state';
import { cn } from '../../lib/utils';

type ProfileUpdater = (current: DomainRunProfile) => DomainRunProfile;

type CrawlAdvancedExecutionProps = {
  runProfile: DomainRunProfile;
  respectRobotsTxt: boolean;
  onProfileChange: (updater: ProfileUpdater) => void;
  onRespectRobotsTxtChange: (value: boolean) => void;
};

export function CrawlAdvancedExecution({
  runProfile,
  respectRobotsTxt,
  onProfileChange,
  onRespectRobotsTxtChange,
}: Readonly<CrawlAdvancedExecutionProps>) {
  return (
    <section className={cn(ADVANCED_COLUMN_CLASS, 'xl:pr-6')}>
      <div className={ADVANCED_SECTION_TITLE_CLASS}>
        <h3>Execution</h3>
        <Tooltip content="Control how the crawler fetches, renders, and traverses the target.">
          <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
        </Tooltip>
      </div>
      <div className={ADVANCED_SUBSECTION_CLASS}>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Fetch Mode</div>
          <Dropdown<FetchMode>
            ariaLabel="Fetch mode"
            value={runProfile.fetch_profile.fetch_mode}
            onChange={(next) => {
              if (!FETCH_MODE_OPTIONS.has(next)) return;
              onProfileChange((current) => ({
                ...current,
                fetch_profile: { ...current.fetch_profile, fetch_mode: next },
                acquisition_contract:
                  next === 'browser_only'
                    ? {
                        ...current.acquisition_contract,
                        prefer_browser: true,
                        handoff_eligible: false,
                        handoff_cookie_engine: 'auto',
                      }
                    : {
                        ...current.acquisition_contract,
                        prefer_browser: false,
                        handoff_eligible: false,
                        handoff_cookie_engine: 'auto',
                      },
              }));
            }}
            options={[
              { value: 'auto', label: 'Auto' },
              { value: 'http_only', label: 'HTTP Only' },
              { value: 'browser_only', label: 'Browser Only' },
              { value: 'http_then_browser', label: 'HTTP Then Browser' },
            ]}
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Browser Engine</div>
          <Dropdown<BrowserEngine>
            ariaLabel="Browser engine"
            value={runProfile.acquisition_contract.preferred_browser_engine}
            onChange={(next) => {
              if (!BROWSER_ENGINE_OPTIONS.has(next)) return;
              onProfileChange((current) => ({
                ...current,
                acquisition_contract: {
                  ...current.acquisition_contract,
                  preferred_browser_engine: next,
                  prefer_browser: next !== 'auto',
                  handoff_eligible: false,
                  handoff_cookie_engine: next === 'auto' ? 'auto' : next,
                },
              }));
            }}
            options={[
              { value: 'auto', label: 'Auto' },
              { value: 'patchright', label: 'Patchright' },
              { value: 'real_chrome', label: 'Real Chrome' },
            ]}
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Extraction</div>
          <Dropdown<ExtractionSource>
            ariaLabel="Extraction source"
            value={runProfile.fetch_profile.extraction_source}
            onChange={(next) => {
              if (!EXTRACTION_SOURCE_OPTIONS.has(next)) return;
              onProfileChange((current) => ({
                ...current,
                fetch_profile: { ...current.fetch_profile, extraction_source: next },
              }));
            }}
            options={[
              { value: 'raw_html', label: 'Raw HTML' },
              { value: 'rendered_dom', label: 'Rendered DOM' },
              { value: 'rendered_dom_visual', label: 'Rendered + Visual' },
              { value: 'network_payload_first', label: 'Network Payload First' },
            ]}
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">JS Mode</div>
          <Dropdown<JsMode>
            ariaLabel="JavaScript mode"
            value={runProfile.fetch_profile.js_mode}
            onChange={(next) => {
              if (!JS_MODE_OPTIONS.has(next)) return;
              onProfileChange((current) => ({
                ...current,
                fetch_profile: { ...current.fetch_profile, js_mode: next },
              }));
            }}
            options={[
              { value: 'auto', label: 'Auto' },
              { value: 'enabled', label: 'Enabled' },
              { value: 'disabled', label: 'Disabled' },
            ]}
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Traversal</div>
          <Dropdown<TraversalDropdownValue>
            ariaLabel="Traversal mode"
            value={runProfile.fetch_profile.traversal_mode ?? 'off'}
            onChange={(next) => {
              if (next === 'off') {
                onProfileChange((current) => ({
                  ...current,
                  fetch_profile: { ...current.fetch_profile, traversal_mode: null },
                }));
                return;
              }
              if (!TRAVERSAL_MODE_OPTIONS.has(next)) return;
              onProfileChange((current) => ({
                ...current,
                fetch_profile: { ...current.fetch_profile, traversal_mode: next },
              }));
            }}
            options={[
              { value: 'off', label: 'Off' },
              { value: 'paginate', label: 'Paginate' },
              { value: 'scroll', label: 'Scroll' },
              { value: 'load_more', label: 'Load More' },
              { value: 'view_all', label: 'View All' },
            ]}
          />
        </div>
      </div>
      <div className={ADVANCED_SUBSECTION_CLASS}>
        <SettingSection
          label="Include iframes"
          description="Allow iframe content to participate in extraction and selector recovery."
          checked={runProfile.fetch_profile.include_iframes}
          onChange={(next) =>
            onProfileChange((current) => ({
              ...current,
              fetch_profile: { ...current.fetch_profile, include_iframes: next },
            }))
          }
        />
        <SettingSection
          label="Respect robots.txt"
          description="Skip disallowed paths and honor crawl-delay."
          checked={respectRobotsTxt}
          onChange={onRespectRobotsTxtChange}
        />
      </div>
    </section>
  );
}
