import { useSearchParams } from 'react-router-dom';

import {
  parseRequestedCategoryMode,
  parseRequestedCrawlTab,
  parseRequestedPdpMode,
} from '../../components/crawl/shared';
import { CrawlConfigScreen } from '../../components/crawl/crawl-config-screen';
import { CrawlRunScreen } from '../../components/crawl/crawl-run-screen';

export default function CrawlPage() {
  const [searchParams] = useSearchParams();
  const runId =
    Number(
      searchParams.get('run_id') || searchParams.get('runId') || searchParams.get('runid') || 0,
    ) || null;

  if (runId !== null) return <CrawlRunScreen key={runId} runId={runId} />;

  return (
    <CrawlConfigScreen
      requestedTab={parseRequestedCrawlTab(searchParams.get('module'))}
      requestedCategoryMode={parseRequestedCategoryMode(searchParams.get('mode'))}
      requestedPdpMode={parseRequestedPdpMode(searchParams.get('mode'))}
      requestedUrl={searchParams.get('url') ?? ''}
    />
  );
}
