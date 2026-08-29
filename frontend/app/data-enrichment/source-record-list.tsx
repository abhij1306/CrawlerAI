import { Badge } from '../../components/ui/primitives';
import { SafeExternalLink } from '../../components/ui/safe-external-link';
import type { DataEnrichmentSourceRecordInput } from '../../lib/api/data-enrichment';

function recordTitle(record: DataEnrichmentSourceRecordInput) {
  const title = record.data?.title;
  return typeof title === 'string' && title.trim()
    ? title
    : record.source_url?.replace(/^https?:\/\/(www\.)?/, '') || `Record #${record.id}`;
}

export function SourceRecordList({
  records,
}: Readonly<{ records: DataEnrichmentSourceRecordInput[] }>) {
  return (
    <div className="overflow-auto">
      {records.map((record, index) => {
        const badgeValue = record.id ?? record.source_url;
        return (
          <div
            key={record.id ?? record.source_url ?? index}
            className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-accent/[0.04]"
          >
            <span className="w-6 shrink-0 font-mono text-base text-muted">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="type-body-sm truncate font-medium">{recordTitle(record)}</div>
              <div className="type-caption flex items-center gap-2">
                {record.source_url ? (
                  <SafeExternalLink
                    href={record.source_url}
                    className="truncate text-accent opacity-80 hover:underline"
                    title={record.source_url}
                  >
                    {record.source_url}
                  </SafeExternalLink>
                ) : null}
              </div>
            </div>
            {badgeValue ? (
              <Badge tone="neutral" className="h-5 shrink-0 px-1.5 font-mono text-base opacity-60">
                #{badgeValue}
              </Badge>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
