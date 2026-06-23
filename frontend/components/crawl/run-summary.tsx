import { useMemo } from 'react';

import type { CrawlRecord, CrawlRun, ResultSummaryQualityLevel } from '../../lib/api/types';
import { Badge } from '../ui/primitives';
import { RunSummaryChips, TabBar } from '../ui/patterns';
import {
  formatDuration,
  formatDurationMs,
  humanizeQuality,
  humanizeVerdict,
  type OutputTabKey,
} from './shared';

function llmTouchedFieldNames(record: CrawlRecord): string[] {
  const raw =
    record.raw_data && typeof record.raw_data === 'object'
      ? (record.raw_data as Record<string, unknown>)
      : {};
  const touched = new Set<string>();
  const source = typeof raw._source === 'string' ? raw._source : '';
  if (source.startsWith('llm_')) {
    touched.add('_record');
  }
  const fieldSources =
    raw._field_sources && typeof raw._field_sources === 'object'
      ? (raw._field_sources as Record<string, unknown>)
      : {};
  for (const [fieldName, value] of Object.entries(fieldSources)) {
    if (
      Array.isArray(value) &&
      value.some((item) => typeof item === 'string' && item.startsWith('llm_'))
    ) {
      touched.add(fieldName);
    }
  }
  return Array.from(touched);
}

function backendQualityLevel(run: CrawlRun | undefined): ResultSummaryQualityLevel {
  const level = String(run?.result_summary?.quality_summary?.level ?? '')
    .trim()
    .toLowerCase();
  return level === 'high' || level === 'medium' || level === 'low' || level === 'unknown'
    ? level
    : 'unknown';
}

type UseRunSummaryOptions = {
  run: CrawlRun | undefined;
  terminal: boolean;
  verdict: string;
  effectiveStartMs: number;
  localNow: number;
  recordsTotal: number;
  tableTotal: number;
  visibleFieldCount: number;
  batchSourceRecords: CrawlRecord[];
  summaryRecordsFromRun: number;
};

export function useRunSummary({
  run,
  terminal,
  verdict,
  effectiveStartMs,
  localNow,
  recordsTotal,
  tableTotal,
  visibleFieldCount,
  batchSourceRecords,
  summaryRecordsFromRun,
}: Readonly<UseRunSummaryOptions>) {
  const llmSummary = useMemo(() => {
    const touchedFields = new Set<string>();
    let touchedRecords = 0;
    for (const record of batchSourceRecords) {
      const fields = llmTouchedFieldNames(record);
      if (!fields.length) continue;
      touchedRecords += 1;
      fields.forEach((fieldName) => touchedFields.add(fieldName));
    }
    return {
      requested: Boolean(run?.settings?.llm_enabled),
      touchedRecords,
      touchedFields: touchedFields.size,
    };
  }, [batchSourceRecords, run?.settings?.llm_enabled]);

  const summaryPagesFromRun =
    Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0;
  const summaryCurrentUrlIndex = Number(run?.result_summary?.current_url_index ?? 0) || 0;
  const summary = {
    records: Math.max(summaryRecordsFromRun, recordsTotal, tableTotal),
    pages: Math.max(
      summaryPagesFromRun,
      summaryCurrentUrlIndex,
      Number(run?.result_summary?.progress ?? 0) > 0 ? 1 : 0,
    ),
    fields: visibleFieldCount,
    duration:
      (terminal ? formatDurationMs(run?.result_summary?.duration_ms) : null) ??
      formatDuration(
        new Date(effectiveStartMs).toISOString(),
        terminal ? run?.completed_at : new Date(localNow).toISOString(),
      ),
  };

  return {
    llmSummary,
    summary,
    qualityLevel: backendQualityLevel(run),
    runErrorMessage: typeof run?.result_summary?.error === 'string' ? run.result_summary.error : '',
    emptyRecordsState:
      verdict === 'blocked'
        ? {
            title: 'Access blocked',
            description:
              'The target site blocked acquisition for this run. Check Logs or browser diagnostics for challenge details.',
          }
        : {
            title: 'No records captured yet',
            description: 'Records will appear here once extraction returns rows.',
          },
  };
}

export function RunOutputTabs({
  value,
  recordCount,
  showLearning,
  onChange,
}: Readonly<{
  value: OutputTabKey;
  recordCount: number;
  showLearning: boolean;
  onChange: (value: OutputTabKey) => void;
}>) {
  return (
    <TabBar
      value={value}
      variant="underline"
      onChange={(next) => onChange(next as OutputTabKey)}
      options={[
        { value: 'table', label: `Table (${recordCount})` },
        { value: 'json', label: 'JSON' },
        { value: 'logs', label: 'Logs' },
        ...(showLearning ? [{ value: 'learning', label: 'Learning' }] : []),
      ]}
    />
  );
}

export function RunOutputSummary({
  llmRequested,
  llmTouchedRecords,
  llmTouchedFields,
  duration,
  verdict,
  quality,
}: Readonly<{
  llmRequested: boolean;
  llmTouchedRecords: number;
  llmTouchedFields: number;
  duration: string;
  verdict: string;
  quality: ResultSummaryQualityLevel;
}>) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2.5">
      {llmRequested ? (
        <Badge
          tone={llmTouchedRecords > 0 ? 'accent' : 'neutral'}
          title={
            llmTouchedRecords > 0
              ? `LLM used ${llmTouchedRecords} record(s) / ${llmTouchedFields} field(s)`
              : 'LLM enabled, no visible repair'
          }
        >
          {llmTouchedRecords > 0
            ? `LLM used ${llmTouchedRecords} rec / ${llmTouchedFields} fld`
            : 'LLM on, no visible repair'}
        </Badge>
      ) : (
        <Badge tone="neutral">LLM off</Badge>
      )}
      <RunSummaryChips
        duration={duration}
        verdict={humanizeVerdict(verdict).toLowerCase()}
        quality={humanizeQuality(quality).toLowerCase()}
      />
    </div>
  );
}
