import { startTransition } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../../lib/api';
import type { CrawlConfig, DomainRunProfile } from '../../lib/api/types';
import { telemetryErrorPayload, trackEvent } from '../../lib/telemetry/events';
import { buildDispatch, inferRunTypeHint, type StudioMode } from './crawl-config-logic';
import type { FieldRow, PendingDispatch } from './shared';
import { deriveSurface } from './shared';
import { crawlConfigSchema, transformFormToSubmission } from './use-crawl-config';

type UseCrawlSubmissionOptions = {
  config: CrawlConfig;
  fieldRows: FieldRow[];
  runProfile: DomainRunProfile;
  studioMode: StudioMode;
  maxRecords: string;
  setConfigError: (message: string) => void;
};

export function useCrawlSubmission({
  config,
  fieldRows,
  runProfile,
  studioMode,
  maxRecords,
  setConfigError,
}: Readonly<UseCrawlSubmissionOptions>) {
  const navigate = useNavigate();

  async function startCrawl() {
    setConfigError('');
    const surface = deriveSurface(config.domain, config.module);
    try {
      const parsedConfig = crawlConfigSchema.safeParse(
        transformFormToSubmission({
          mode: config.mode,
          targetUrl: config.target_url,
          bulkUrls: config.bulk_urls,
          maxRecords,
        }),
      );
      if (!parsedConfig.success) {
        throw new Error(parsedConfig.error.issues[0]?.message ?? 'Unable to launch crawl.');
      }

      const dispatch = buildDispatch(config, fieldRows, { runProfile, studioMode });
      if (studioMode === 'advanced') {
        trackEvent('advanced_mode_selected_vs_effective', {
          module: config.module,
          selected_advanced_mode: runProfile.fetch_profile.traversal_mode,
          effective_advanced_mode: dispatch.settings.advanced_mode ?? null,
        });
      }

      const response =
        dispatch.runType === 'csv'
          ? await createCsvRun(dispatch)
          : await api.createCrawl({
              run_type: dispatch.runType,
              url: dispatch.url,
              urls: dispatch.urls,
              surface: dispatch.surface,
              settings: dispatch.settings,
              additional_fields: dispatch.additionalFields,
            });

      startTransition(() => {
        navigate(`/crawl?run_id=${response.run_id}`, { replace: true });
      });
    } catch (error) {
      trackEvent(
        'crawl_submit_error_rate',
        telemetryErrorPayload(error, {
          module: config.module,
          mode: config.mode,
          surface,
          studio_mode: studioMode,
          smart_extraction: config.smart_extraction,
          run_type_hint: inferRunTypeHint(config),
        }),
      );
      setConfigError(error instanceof Error ? error.message : 'Unable to launch crawl.');
    }
  }

  return { startCrawl };
}

async function createCsvRun(dispatch: PendingDispatch) {
  if (!dispatch.csvFile) {
    throw new Error('CSV file is missing.');
  }
  return api.createCsvCrawl({
    file: dispatch.csvFile,
    surface: dispatch.surface,
    additionalFields: dispatch.additionalFields,
    settings: dispatch.settings,
  });
}
