import { Info } from 'lucide-react';

import type { DomainRunProfile } from '../../lib/api/types';
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from '../../lib/constants/crawl-defaults';
import { cn } from '../../lib/utils';
import { Input, Tooltip } from '../ui/primitives';
import { clampNumber, parseOptionalClampedNumber } from '../../lib/crawl/format';
import { SliderRow } from './form-fields';
import {
  ADVANCED_COLUMN_CLASS,
  ADVANCED_CONTROL_ROW_CLASS,
  ADVANCED_SECTION_TITLE_CLASS,
  ADVANCED_SUBSECTION_CLASS,
} from './crawl-config-state';

type ProfileUpdater = (current: DomainRunProfile) => DomainRunProfile;

type CrawlAdvancedLimitsProps = {
  runProfile: DomainRunProfile;
  maxRecords: string;
  onProfileChange: (updater: ProfileUpdater) => void;
  onMaxRecordsChange: (value: string) => void;
};

export function CrawlAdvancedLimits({
  runProfile,
  maxRecords,
  onProfileChange,
  onMaxRecordsChange,
}: Readonly<CrawlAdvancedLimitsProps>) {
  return (
    <section className={cn(ADVANCED_COLUMN_CLASS, 'xl:px-6')}>
      <div className={ADVANCED_SECTION_TITLE_CLASS}>
        <h3>Limits &amp; Locales</h3>
        <Tooltip content="Set repeat-run bounds and regional hints before dispatch.">
          <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
        </Tooltip>
      </div>
      <div className={ADVANCED_SUBSECTION_CLASS}>
        <SliderRow
          label="Request Delay"
          description="Wait time between requests to the same target."
          value={String(runProfile.fetch_profile.request_delay_ms)}
          min={CRAWL_LIMITS.MIN_REQUEST_DELAY_MS}
          max={CRAWL_LIMITS.MAX_REQUEST_DELAY_MS}
          step={100}
          onChange={(next) =>
            onProfileChange((current) => ({
              ...current,
              fetch_profile: {
                ...current.fetch_profile,
                request_delay_ms: clampNumber(
                  next,
                  CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
                  CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
                  CRAWL_DEFAULTS.REQUEST_DELAY_MS,
                ),
              },
            }))
          }
          onReset={() =>
            onProfileChange((current) => ({
              ...current,
              fetch_profile: {
                ...current.fetch_profile,
                request_delay_ms: CRAWL_DEFAULTS.REQUEST_DELAY_MS,
              },
            }))
          }
        />
        <SliderRow
          label="Max Records"
          description="Target record count. The crawler stops after a page reaches this target; it does not trim extra rows from that page."
          value={maxRecords}
          min={CRAWL_LIMITS.MIN_RECORDS}
          max={CRAWL_LIMITS.MAX_RECORDS}
          step={10}
          onChange={onMaxRecordsChange}
          onReset={() => onMaxRecordsChange(String(CRAWL_DEFAULTS.MAX_RECORDS))}
        />
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="flex items-center gap-2">
            <div className="type-body-sm font-semibold text-foreground">Host Memory TTL</div>
            <Tooltip
              content={`Blank uses default ${CRAWL_DEFAULTS.HOST_MEMORY_TTL_SECONDS}s. Lower TTL forgets host block and pacing memory sooner.`}
            >
              <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
            </Tooltip>
          </div>
          <Input
            type="number"
            min={CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS}
            max={CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS}
            placeholder={String(CRAWL_DEFAULTS.HOST_MEMORY_TTL_SECONDS)}
            value={runProfile.fetch_profile.host_memory_ttl_seconds ?? ''}
            onChange={(event) =>
              onProfileChange((current) => ({
                ...current,
                fetch_profile: {
                  ...current.fetch_profile,
                  host_memory_ttl_seconds: parseOptionalClampedNumber(
                    event.target.value,
                    CRAWL_LIMITS.MIN_HOST_MEMORY_TTL_SECONDS,
                    CRAWL_LIMITS.MAX_HOST_MEMORY_TTL_SECONDS,
                    'clamp-to-min',
                  ),
                },
              }))
            }
            aria-label="Host memory TTL seconds"
          />
        </div>
      </div>
      <div className={ADVANCED_SUBSECTION_CLASS}>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Geo Country</div>
          <Input
            value={runProfile.locality_profile.geo_country}
            onChange={(event) =>
              onProfileChange((current) => ({
                ...current,
                locality_profile: {
                  ...current.locality_profile,
                  geo_country: event.target.value.trim() || 'auto',
                },
              }))
            }
            aria-label="Geo country"
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Language Hint</div>
          <Input
            value={runProfile.locality_profile.language_hint ?? ''}
            onChange={(event) =>
              onProfileChange((current) => ({
                ...current,
                locality_profile: {
                  ...current.locality_profile,
                  language_hint: event.target.value.trim() || null,
                },
              }))
            }
            aria-label="Language hint"
          />
        </div>
        <div className={ADVANCED_CONTROL_ROW_CLASS}>
          <div className="type-body-sm font-semibold text-foreground">Currency Hint</div>
          <Input
            value={runProfile.locality_profile.currency_hint ?? ''}
            onChange={(event) =>
              onProfileChange((current) => ({
                ...current,
                locality_profile: {
                  ...current.locality_profile,
                  currency_hint: event.target.value.trim() || null,
                },
              }))
            }
            aria-label="Currency hint"
          />
        </div>
      </div>
    </section>
  );
}
