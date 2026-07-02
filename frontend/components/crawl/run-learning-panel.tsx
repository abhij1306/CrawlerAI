import type { DomainRecipe, DomainRecipeFieldLearningItem } from '../../lib/api/types';
import { DataRegionEmpty, DetailRow, InlineAlert, SectionHeader } from '../ui/patterns';
import { Badge, Button, Card } from '../ui/primitives';
import type { RecipeActionPendingKey } from './use-run-recipe-actions';
import { selectorWinnerLabel } from './shared';

type RunLearningPanelProps = {
  loading: boolean;
  recipe: DomainRecipe | undefined;
  pendingKey: RecipeActionPendingKey | null;
  error: string;
  onActivateCorrection: (item: DomainRecipeFieldLearningItem) => void;
};

export function RunLearningPanel({
  loading,
  recipe,
  pendingKey,
  error,
  onActivateCorrection,
}: Readonly<RunLearningPanelProps>) {
  if (loading) {
    return (
      <Card className="section-card">
        <SectionHeader
          title="Run Learning"
          description="Loading grounded extraction evidence for this run."
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
          description={`Review grounded extraction evidence for ${recipe.domain} on ${recipe.surface}. Activation is allowed only after representative replay passes.`}
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
            <div className="field-label mb-0">Grounded Field Corrections</div>
            <p className="type-body mt-1 text-secondary">
              Activate only evidence backed by persisted HTML and representative results from the
              same template cohort.
            </p>
          </div>
          {recipe.field_learning.length ? (
            <div className="space-y-2">
              {recipe.field_learning.map((item) => {
                const pending = pendingKey === `field:${item.field_name}:activate`;
                const canActivate =
                  item.selector_kind === 'css_selector' &&
                  Boolean(item.selector_value?.trim()) &&
                  item.representative_url_result_ids.length > 0;
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
                          <Badge tone={canActivate ? 'success' : 'warning'}>
                            {canActivate
                              ? `${item.representative_url_result_ids.length} replay result${item.representative_url_result_ids.length === 1 ? '' : 's'}`
                              : 'not activatable'}
                          </Badge>
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
                      <Button
                        variant="neutral"
                        type="button"
                        size="sm"
                        disabled={pendingKey !== null || !canActivate}
                        onClick={() => onActivateCorrection(item)}
                      >
                        {pending ? 'Replaying…' : 'Activate correction'}
                      </Button>
                    </div>
                  </DetailRow>
                );
              })}
            </div>
          ) : (
            <div className="surface-muted rounded-lg border border-dashed px-6 py-3">
              <p className="type-body m-0 text-secondary">
                No grounded field-learning signals were captured for this run.
              </p>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
