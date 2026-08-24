import { surfaceLabel } from '@lib/format/domain';
import { Badge } from '@ui/primitives';
import { DataRegionEmpty, DetailRow, SurfaceSection } from '@ui/patterns';
import type { DomainWorkspace } from './types';
import { formatTimestamp } from './utils';

const MAX_LEARNING_DISPLAY = 8;

type LearningTabProps = { selectedWorkspace: DomainWorkspace };

export function LearningTab({ selectedWorkspace }: LearningTabProps) {
  return (
    <SurfaceSection
      title="Recent Learning"
      description="Latest keep and reject decisions captured for this domain across all surfaces."
      bodyClassName="space-y-2"
    >
      {selectedWorkspace.learning.length ? (
        selectedWorkspace.learning.slice(0, MAX_LEARNING_DISPLAY).map((row) => (
          <DetailRow key={row.id}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={row.action === 'reject' ? 'warning' : 'success'}>{row.action}</Badge>
              <span className="text-base font-normal text-foreground">{row.field_name}</span>
              <Badge tone="neutral">{surfaceLabel(row.surface)}</Badge>
            </div>
            <div className="mt-2 text-base text-secondary">
              Source: {row.source_kind}
              {row.source_value ? ` · Value: ${row.source_value}` : ''}
            </div>
            {row.selector_value ? (
              <code className="mt-2 block text-base break-all text-muted">
                {row.selector_value}
              </code>
            ) : null}
            <div className="mt-2 text-base text-muted">{formatTimestamp(row.created_at)}</div>
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
