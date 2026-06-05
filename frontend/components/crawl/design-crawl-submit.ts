'use client';

import { api } from '../../lib/api';
import type { CrawlConfig, DomainRunProfile } from '../../lib/api/types';
import { cloneRunProfile } from './crawl-config-logic';

export function createDesignCrawlRun({
  targetUrl,
  config,
  runProfile,
}: Readonly<{
  targetUrl: string;
  config: CrawlConfig;
  runProfile: DomainRunProfile;
}>) {
  const url = targetUrl.trim();
  if (!url) {
    throw new Error('Enter a target URL for design crawl.');
  }
  const parsedUrl = new URL(url);
  if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
    throw new Error('Design crawl needs an http or https URL.');
  }
  const designProfile = cloneRunProfile(runProfile);
  return api.createCrawl({
    run_type: 'crawl',
    url,
    surface: 'design_system',
    settings: {
      llm_enabled: true,
      max_records: 1,
      respect_robots_txt: config.respect_robots_txt,
      proxy_enabled: config.proxy_enabled,
      proxy_list: config.proxy_lines,
      proxy_profile: {
        enabled: config.proxy_enabled,
        proxy_list: config.proxy_lines,
      },
      crawl_module: 'pdp',
      crawl_mode: 'single',
      fetch_profile: {
        ...designProfile.fetch_profile,
        fetch_mode: 'browser_only',
        extraction_source: 'rendered_dom_visual',
        traversal_mode: null,
      },
      locality_profile: { ...designProfile.locality_profile },
      diagnostics_profile: { ...designProfile.diagnostics_profile },
      acquisition_contract: { ...designProfile.acquisition_contract },
    },
    additional_fields: [],
  });
}
