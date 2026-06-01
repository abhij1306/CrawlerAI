import type { AdvancedCrawlMode, DomainRunProfile } from '../../../lib/api/types';
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../../lib/constants/crawl-defaults';
import { Dropdown, Field, Input } from '../../ui/primitives';
import type { SurfaceWorkspace } from './types';
import type { UpdateProfileDraft } from './profile-types';
import { parseOptionalClampedNumber } from './utils';

type RunProfileFieldsProps = {
  domain: string;
  profile: DomainRunProfile;
  surface: SurfaceWorkspace;
  updateProfileDraft: UpdateProfileDraft;
};

type BrowserEngine = 'auto' | 'patchright' | 'real_chrome';
type BrowserEngineFieldKey = 'preferred_browser_engine' | 'handoff_cookie_engine';

const browserEngineOptions: Array<{ value: BrowserEngine; label: string }> = [
  { value: 'auto', label: 'Auto' },
  { value: 'patchright', label: 'Patchright' },
  { value: 'real_chrome', label: 'Real Chrome' },
];

export function RunProfileFields({
  domain,
  profile,
  surface,
  updateProfileDraft,
}: RunProfileFieldsProps) {
  function updateBrowserEngine(key: BrowserEngineFieldKey, value: string) {
    updateProfileDraft(domain, surface, (current) => ({
      ...current,
      acquisition_contract: {
        ...current.acquisition_contract,
        [key]: value as BrowserEngine,
      },
    }));
  }

  return (
    <div className="grid content-start gap-3 md:col-span-2 md:grid-cols-2">
      <Field label="Fetch Mode">
        <Dropdown
          value={profile.fetch_profile.fetch_mode}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              fetch_profile: { ...current.fetch_profile, fetch_mode: value },
            }))
          }
          options={[
            { value: 'auto', label: 'Auto' },
            { value: 'http_only', label: 'HTTP Only' },
            { value: 'browser_only', label: 'Browser Only' },
            { value: 'http_then_browser', label: 'HTTP Then Browser' },
          ]}
        />
      </Field>
      <Field label="Extraction Source">
        <Dropdown
          value={profile.fetch_profile.extraction_source}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              fetch_profile: { ...current.fetch_profile, extraction_source: value },
            }))
          }
          options={[
            { value: 'raw_html', label: 'Raw HTML' },
            { value: 'rendered_dom', label: 'Rendered DOM' },
            { value: 'rendered_dom_visual', label: 'Rendered DOM + Visual' },
            { value: 'network_payload_first', label: 'Network Payload First' },
          ]}
        />
      </Field>
      <Field label="JS Mode">
        <Dropdown
          value={profile.fetch_profile.js_mode}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              fetch_profile: { ...current.fetch_profile, js_mode: value },
            }))
          }
          options={[
            { value: 'auto', label: 'Auto' },
            { value: 'enabled', label: 'Enabled' },
            { value: 'disabled', label: 'Disabled' },
          ]}
        />
      </Field>
      <Field label="Traversal Mode">
        <Dropdown
          value={profile.fetch_profile.traversal_mode ?? ''}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              fetch_profile: {
                ...current.fetch_profile,
                traversal_mode: value ? (value as AdvancedCrawlMode) : null,
              },
            }))
          }
          options={[
            { value: '', label: 'Off' },
            { value: 'scroll', label: 'Scroll' },
            { value: 'load_more', label: 'Load More' },
            { value: 'view_all', label: 'View All' },
            { value: 'paginate', label: 'Paginate' },
          ]}
        />
      </Field>
      <Field label="Host Memory TTL (s)">
        <Input
          type="number"
          min={CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS}
          max={CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS}
          placeholder={String(CRAWL_DEFAULTS.HOST_MEMORY_TTL_SECONDS)}
          value={profile.fetch_profile.host_memory_ttl_seconds ?? ''}
          onChange={(event) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              fetch_profile: {
                ...current.fetch_profile,
                host_memory_ttl_seconds: parseOptionalClampedNumber(
                  event.target.value,
                  CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS,
                  CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS,
                ),
              },
            }))
          }
        />
      </Field>
      <Field label="Geo Country">
        <Input
          value={profile.locality_profile.geo_country}
          onChange={(event) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              locality_profile: {
                ...current.locality_profile,
                geo_country: event.target.value || 'auto',
              },
            }))
          }
        />
      </Field>
      <Field label="Language Hint">
        <Input
          value={profile.locality_profile.language_hint ?? ''}
          onChange={(event) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              locality_profile: {
                ...current.locality_profile,
                language_hint: event.target.value || null,
              },
            }))
          }
        />
      </Field>
      <Field label="Currency Hint">
        <Input
          value={profile.locality_profile.currency_hint ?? ''}
          onChange={(event) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              locality_profile: {
                ...current.locality_profile,
                currency_hint: event.target.value || null,
              },
            }))
          }
        />
      </Field>
      <Field label="Network Capture">
        <Dropdown
          value={profile.diagnostics_profile.capture_network}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              diagnostics_profile: { ...current.diagnostics_profile, capture_network: value },
            }))
          }
          options={[
            { value: 'off', label: 'Off' },
            { value: 'matched_only', label: 'Matched Only' },
            { value: 'all_small_json', label: 'All Small JSON' },
          ]}
        />
      </Field>
      <Field label="Preferred Browser Engine">
        <BrowserEngineDropdown
          value={profile.acquisition_contract.preferred_browser_engine}
          onChange={(value) => updateBrowserEngine('preferred_browser_engine', value)}
        />
      </Field>
      <Field label="Handoff Cookie Engine">
        <BrowserEngineDropdown
          value={profile.acquisition_contract.handoff_cookie_engine}
          onChange={(value) => updateBrowserEngine('handoff_cookie_engine', value)}
        />
      </Field>
    </div>
  );
}

function BrowserEngineDropdown({
  value,
  onChange,
}: Readonly<{
  value: BrowserEngine;
  onChange: (value: string) => void;
}>) {
  return <Dropdown value={value} onChange={onChange} options={browserEngineOptions} />;
}
