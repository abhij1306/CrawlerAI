import type { AdvancedCrawlMode, DomainRunProfile } from '../../../lib/api/types';
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../../lib/constants/crawl-defaults';
import { Dropdown, Input } from '../../ui/primitives';
import type { SurfaceWorkspace } from './types';
import type { UpdateProfileDraft } from './profile-types';
import { parseOptionalClampedNumber } from './utils';

type RunProfileFieldsProps = {
  domain: string;
  profile: DomainRunProfile;
  surface: SurfaceWorkspace;
  updateProfileDraft: UpdateProfileDraft;
};

export function RunProfileFields({
  domain,
  profile,
  surface,
  updateProfileDraft,
}: RunProfileFieldsProps) {
  return (
    <div className="grid content-start gap-3 md:col-span-2 md:grid-cols-2">
      <label className="grid gap-1.5">
        <span className="field-label">Fetch Mode</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Extraction Source</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">JS Mode</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Traversal Mode</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Host Memory TTL (s)</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Geo Country</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Language Hint</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Currency Hint</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Network Capture</span>
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
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Preferred Browser Engine</span>
        <Dropdown
          value={profile.acquisition_contract.preferred_browser_engine}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              acquisition_contract: {
                ...current.acquisition_contract,
                preferred_browser_engine: value as 'auto' | 'patchright' | 'real_chrome',
              },
            }))
          }
          options={[
            { value: 'auto', label: 'Auto' },
            { value: 'patchright', label: 'Patchright' },
            { value: 'real_chrome', label: 'Real Chrome' },
          ]}
        />
      </label>
      <label className="grid gap-1.5">
        <span className="field-label">Handoff Cookie Engine</span>
        <Dropdown
          value={profile.acquisition_contract.handoff_cookie_engine}
          onChange={(value) =>
            updateProfileDraft(domain, surface, (current) => ({
              ...current,
              acquisition_contract: {
                ...current.acquisition_contract,
                handoff_cookie_engine: value as 'auto' | 'patchright' | 'real_chrome',
              },
            }))
          }
          options={[
            { value: 'auto', label: 'Auto' },
            { value: 'patchright', label: 'Patchright' },
            { value: 'real_chrome', label: 'Real Chrome' },
          ]}
        />
      </label>
    </div>
  );
}
