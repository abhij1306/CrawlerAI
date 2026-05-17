import { Badge } from '../../ui/primitives';
import { DataRegionEmpty, DetailRow, SurfaceSection } from '../../ui/patterns';
import type { DomainWorkspace } from './types';
import { formatTimestamp, surfaceLabel } from './utils';

type LearningTabProps = { selectedWorkspace: DomainWorkspace };

export function LearningTab({ selectedWorkspace }: LearningTabProps) {
  return (
    <SurfaceSection
      title="Recent Learning"
      description="Latest keep and reject decisions captured for this domain across all surfaces."
      bodyClassName="space-y-2"
    >
      {selectedWorkspace.learning.length ? (
        selectedWorkspace.learning.slice(0, 8).map((row) => (
          <DetailRow key={row.id}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={row.action === 'reject' ? 'warning' : 'success'}>{row.action}</Badge>
              <span className="text-foreground text-sm font-normal">{row.field_name}</span>
              <Badge tone="neutral">{surfaceLabel(row.surface)}</Badge>
            </div>
            <div className="text-secondary mt-2 text-xs">
              Source: {row.source_kind}
              {row.source_value ? ` · Value: ${row.source_value}` : ''}
            </div>
            {row.selector_value ? (
              <code className="text-muted mt-2 block text-xs break-all">{row.selector_value}</code>
            ) : null}
            <div className="text-muted mt-2 text-xs">{formatTimestamp(row.created_at)}</div>
          </DetailRow>
        ))
      ) : (
        <DataRegionEmpty
          title="No recent learning"
          description="Use the Learning tab on a completed run to keep or reject field evidence and populate this history."
        />
      )}
    </SurfaceSection>
  );
}
