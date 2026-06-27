import type { DomainRecipe } from '../../lib/api/types';
import { DataRegionEmpty, DetailRow, InlineAlert, SectionHeader } from '../ui/patterns';
import { Badge, Button, Card } from '../ui/primitives';
import type { RecipeActionPendingKey } from './use-run-recipe-actions';
import { selectorWinnerLabel } from './shared';

type RunLearningPanelProps = {
  loading: boolean;
  recipe: DomainRecipe | undefined;
  pendingKey: RecipeActionPendingKey | null;
  error: string;
  onFieldAction: (
    fieldName: string,
    action: 'keep' | 'reject',
    selectorKind?: string | null,
    selectorValue?: string | null,
    sourceRecordIds?: number[],
  ) => void;
};

export function RunLearningPanel({
  loading,
  recipe,
  pendingKey,
  error,
  onFieldAction,
}: Readonly<RunLearningPanelProps>) {
  if (loading) {
    return (
      <Card className="section-card">
        <SectionHeader
          title="Run Learning"
          description="Loading keep and reject recommendations for this run."
        />
      </Card>
    );
  }

  if (!recipe) {
    return (
      <DataRegionEmpty
        title="No learning data available"
        description="This run did not produce reusable field-learning evidence."
        className="px-0"
      />
    );
  }

  return (
    <div className="space-y-4">
      {error ? <InlineAlert tone="danger" message={error} /> : null}
      <Card className="section-card space-y-4">
        <SectionHeader
          title="Run Learning"
          description={`Review extraction evidence for ${recipe.domain} on ${recipe.surface}. Keep what should compound, reject what should not.`}
        />
        <div className="grid gap-3 md:grid-cols-2">
          <div className="surface-muted type-body rounded-md px-6 py-3 leading-relaxed text-secondary">
            <div className="field-label mb-1">Requested Coverage</div>
            Requested: {recipe.requested_field_coverage.requested.join(', ') || 'None'}
            <br />
            Found: {recipe.requested_field_coverage.found.join(', ') || 'None'}
            <br />
            Missing: {recipe.requested_field_coverage.missing.join(', ') || 'None'}
          </div>
          <div className="surface-muted type-body rounded-md px-6 py-3 leading-relaxed text-secondary">
            <div className="field-label mb-1">Acquisition Evidence</div>
            Method: {recipe.acquisition_evidence.actual_fetch_method || '—'}
            <br />
            Browser Used: {recipe.acquisition_evidence.browser_used ? 'Yes' : 'No'}
            <br />
            Browser Reason: {recipe.acquisition_evidence.browser_reason || '—'}
            <br />
            Cookie Memory:{' '}
            {recipe.acquisition_evidence.cookie_memory_available
              ? 'Saved'
              : recipe.acquisition_evidence.browser_used
                ? 'No reusable state observed'
                : 'Not applicable'}
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <div className="field-label mb-0">Field Learning</div>
            <p className="type-body mt-1 text-secondary">
              Keep accepted field evidence or reject bad field evidence for future runs on this
              domain and surface.
            </p>
          </div>
          {recipe.field_learning.length ? (
            <div className="space-y-2">
              {recipe.field_learning.map((item) => {
                const keepPending = pendingKey === `field:${item.field_name}:keep`;
                const rejectPending = pendingKey === `field:${item.field_name}:reject`;
                return (
                  <DetailRow
                    key={`${item.field_name}:${item.selector_kind ?? 'source'}:${item.selector_value ?? item.source_labels.join(',')}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="type-control text-foreground">{item.field_name}</span>
                          {item.selector_kind ? (
                            <Badge tone="info">{item.selector_kind}</Badge>
                          ) : (
                            <Badge tone="neutral">non-selector</Badge>
                          )}
                          {item.feedback ? (
                            <Badge tone={item.feedback.action === 'reject' ? 'warning' : 'success'}>
                              {item.feedback.action}
                            </Badge>
                          ) : null}
                        </div>
                        <div className="type-caption mt-1">
                          {selectorWinnerLabel(item.selector_kind)} · Sources:{' '}
                          {item.source_labels.join(', ') || '—'}
                        </div>
                        {item.selector_value ? (
                          <code className="type-caption-mono mt-2 block truncate text-secondary">
                            {item.selector_value}
                          </code>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="neutral"
                          type="button"
                          size="sm"
                          disabled={pendingKey !== null}
                          onClick={() =>
                            onFieldAction(
                              item.field_name,
                              'keep',
                              item.selector_kind,
                              item.selector_value,
                              item.source_record_ids,
                            )
                          }
                        >
                          {keepPending ? 'Keeping…' : 'Keep'}
                        </Button>
                        <Button
                          variant="quiet"
                          type="button"
                          size="sm"
                          disabled={pendingKey !== null}
                          onClick={() =>
                            onFieldAction(
                              item.field_name,
                              'reject',
                              item.selector_kind,
                              item.selector_value,
                              item.source_record_ids,
                            )
                          }
                        >
                          {rejectPending ? 'Rejecting…' : 'Reject'}
                        </Button>
                      </div>
                    </div>
                  </DetailRow>
                );
              })}
            </div>
          ) : (
            <div className="surface-muted rounded-lg border border-dashed px-6 py-3">
              <p className="type-body m-0 text-secondary">
                No field learning signals were captured for this run.
              </p>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
