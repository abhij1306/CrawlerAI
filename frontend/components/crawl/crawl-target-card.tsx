import { StudioChip } from './shared';
import type { CategoryMode, CrawlTab, PdpMode } from './shared';
import { SECTION_CARD_HEADER_CLASS, SECTION_CARD_TITLE_CLASS } from './crawl-config-state';
import { parseLines } from '../../lib/crawl/format';
import {
  AdditionalFieldInput,
  CsvFileField,
  SitemapConfigFields,
  TargetUrlField,
} from './form-fields';
import { CrawlActionButtons } from './crawl-action-buttons';
import { TabBar } from '../ui/patterns';
import { Card, Textarea } from '../ui/primitives';

type CrawlTargetCardProps = {
  crawlTab: CrawlTab;
  categoryMode: CategoryMode;
  pdpMode: PdpMode;
  activeMode: CategoryMode | PdpMode;
  activeTabLabel: string;
  domainTabs: Array<{ value: CrawlTab; label: string }>;
  showSurfaceTabs: boolean;
  canSubmit: boolean;
  isSubmitting: boolean;
  targetUrl: string;
  bulkUrls: string;
  csvFile: File | null;
  sitemapDomain: string;
  sitemapFilterKeyword: string;
  sitemapMaxUrls: number;
  savedProfileMessage: string;
  additionalDraft: string;
  additionalFields: string[];
  onTabChange: (tab: CrawlTab) => void;
  onCategoryModeChange: (mode: CategoryMode) => void;
  onPdpModeChange: (mode: PdpMode) => void;
  onTargetUrlChange: (value: string) => void;
  onBulkUrlsChange: (value: string) => void;
  onCsvFileChange: (file: File | null) => void;
  onSitemapDomainChange: (value: string) => void;
  onSitemapFilterKeywordChange: (value: string) => void;
  onSitemapMaxUrlsChange: (value: number) => void;
  onAdditionalDraftChange: (value: string) => void;
  onAdditionalFieldCommit: (value: string) => void;
  onAdditionalFieldRemove: (value: string) => void;
};

type TargetInputProps = Pick<
  CrawlTargetCardProps,
  | 'crawlTab'
  | 'pdpMode'
  | 'activeMode'
  | 'targetUrl'
  | 'bulkUrls'
  | 'csvFile'
  | 'sitemapDomain'
  | 'sitemapFilterKeyword'
  | 'sitemapMaxUrls'
  | 'onTargetUrlChange'
  | 'onBulkUrlsChange'
  | 'onCsvFileChange'
  | 'onSitemapDomainChange'
  | 'onSitemapFilterKeywordChange'
  | 'onSitemapMaxUrlsChange'
> & { bulkMode: boolean };

function TargetInput(props: Readonly<TargetInputProps>) {
  if (props.bulkMode) {
    return (
      <label className="grid gap-2">
        <span className="type-control font-medium">URLs (one per line)</span>
        <div className="relative">
          <Textarea
            value={props.bulkUrls}
            onChange={(event) => props.onBulkUrlsChange(event.target.value)}
            placeholder={'https://example.com/page-1\nhttps://example.com/page-2'}
            className="min-h-[420px] font-mono"
            aria-label="Bulk URLs input"
          />
          {props.bulkUrls.trim() ? (
            <div className="type-caption absolute right-2 bottom-2 rounded-sm bg-background/80 px-2 py-1 text-foreground backdrop-blur-sm">
              {parseLines(props.bulkUrls).length} URLs
            </div>
          ) : null}
        </div>
      </label>
    );
  }
  if (props.crawlTab === 'pdp' && props.pdpMode === 'csv') {
    return <CsvFileField file={props.csvFile} onChange={props.onCsvFileChange} />;
  }
  if (props.crawlTab === 'category' && props.activeMode === 'sitemap') {
    return (
      <SitemapConfigFields
        domain={props.sitemapDomain}
        filterKeyword={props.sitemapFilterKeyword}
        maxUrls={props.sitemapMaxUrls}
        onDomainChange={props.onSitemapDomainChange}
        onFilterKeywordChange={props.onSitemapFilterKeywordChange}
        onMaxUrlsChange={props.onSitemapMaxUrlsChange}
      />
    );
  }
  return (
    <TargetUrlField
      value={props.targetUrl}
      onChange={props.onTargetUrlChange}
      placeholder={
        props.crawlTab === 'category' ? 'https://example.com/list' : 'https://example.com/page'
      }
    />
  );
}

export function CrawlTargetCard({
  crawlTab,
  categoryMode,
  pdpMode,
  activeMode,
  activeTabLabel,
  domainTabs,
  showSurfaceTabs,
  canSubmit,
  isSubmitting,
  targetUrl,
  bulkUrls,
  csvFile,
  sitemapDomain,
  sitemapFilterKeyword,
  sitemapMaxUrls,
  savedProfileMessage,
  additionalDraft,
  additionalFields,
  onTabChange,
  onCategoryModeChange,
  onPdpModeChange,
  onTargetUrlChange,
  onBulkUrlsChange,
  onCsvFileChange,
  onSitemapDomainChange,
  onSitemapFilterKeywordChange,
  onSitemapMaxUrlsChange,
  onAdditionalDraftChange,
  onAdditionalFieldCommit,
  onAdditionalFieldRemove,
}: Readonly<CrawlTargetCardProps>) {
  const bulkMode =
    (crawlTab === 'category' && categoryMode === 'bulk') ||
    (crawlTab === 'pdp' && pdpMode === 'batch');

  return (
    <Card className="section-card overflow-hidden p-0">
      <header className={SECTION_CARD_HEADER_CLASS}>
        <span className={SECTION_CARD_TITLE_CLASS}>Target URL</span>
        <StudioChip>{activeTabLabel}</StudioChip>
      </header>
      <div className="space-y-5 px-6 pt-4 pb-6">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
          <div className="ml-[-4px] flex flex-wrap items-center gap-2.5">
            {showSurfaceTabs ? (
              <TabBar value={crawlTab} onChange={onTabChange} options={domainTabs} />
            ) : null}
            <div className="ml-[-4px] flex flex-wrap items-center gap-2.5">
              {crawlTab === 'category' ? (
                <TabBar
                  value={categoryMode}
                  compact
                  onChange={onCategoryModeChange}
                  options={[
                    { value: 'single', label: 'Single' },
                    { value: 'sitemap', label: 'Sitemap' },
                    { value: 'bulk', label: 'Bulk' },
                  ]}
                />
              ) : (
                <TabBar
                  value={pdpMode}
                  compact
                  onChange={onPdpModeChange}
                  options={[
                    { value: 'single', label: 'Single' },
                    { value: 'batch', label: 'Batch' },
                    { value: 'csv', label: 'CSV Upload' },
                  ]}
                />
              )}
            </div>
          </div>
          <CrawlActionButtons canSubmit={canSubmit} isSubmitting={isSubmitting} />
        </div>

        <TargetInput
          crawlTab={crawlTab}
          pdpMode={pdpMode}
          activeMode={activeMode}
          targetUrl={targetUrl}
          bulkUrls={bulkUrls}
          csvFile={csvFile}
          sitemapDomain={sitemapDomain}
          sitemapFilterKeyword={sitemapFilterKeyword}
          sitemapMaxUrls={sitemapMaxUrls}
          onTargetUrlChange={onTargetUrlChange}
          onBulkUrlsChange={onBulkUrlsChange}
          onCsvFileChange={onCsvFileChange}
          onSitemapDomainChange={onSitemapDomainChange}
          onSitemapFilterKeywordChange={onSitemapFilterKeywordChange}
          onSitemapMaxUrlsChange={onSitemapMaxUrlsChange}
          bulkMode={bulkMode}
        />

        {savedProfileMessage ? (
          <div className="type-body rounded-md border border-subtle-panel-border bg-subtle-panel px-3 py-2 leading-relaxed text-secondary">
            {savedProfileMessage}
          </div>
        ) : null}

        <AdditionalFieldInput
          value={additionalDraft}
          fields={additionalFields}
          onChange={onAdditionalDraftChange}
          onCommit={onAdditionalFieldCommit}
          onRemove={onAdditionalFieldRemove}
        />
      </div>
    </Card>
  );
}
