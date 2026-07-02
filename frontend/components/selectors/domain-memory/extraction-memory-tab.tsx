import { Database } from 'lucide-react';

import type { ExtractionMemoryRecipe, ExtractionMemoryTemplate } from '../../../lib/api/types';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  SurfaceSection,
} from '../../ui/patterns';
import { Badge } from '../../ui/primitives';
import { KnowledgeGraphTab } from './knowledge-graph-tab';
import type { DomainWorkspace } from './types';
import { ExtractionMemoryRefreshButton, useExtractionMemory } from './use-extraction-memory';
import { formatTimestamp, surfaceLabel } from './utils';

export function ExtractionMemoryTab({ selectedWorkspace }: { selectedWorkspace: DomainWorkspace }) {
  const { error, query } = useExtractionMemory(
    selectedWorkspace.domain,
    'Unable to load extraction runtime memory.',
  );
  const data = query.data;

  return (
    <div className="space-y-4">
      <SurfaceSection
        title="Extraction runtime"
        description="Templates, compiled recipes, releases, and observed use for this domain."
        icon={Database}
        action={
          <ExtractionMemoryRefreshButton
            isFetching={query.isFetching}
            onRefresh={() => void query.refetch()}
          />
        }
        bodyClassName="space-y-4"
      >
        {error ? <DataRegionError message={error} className="p-0" /> : null}
        {query.isLoading ? (
          <DataRegionLoading count={4} className="p-0" />
        ) : !data?.templates.length ? (
          <DataRegionEmpty
            title="No extraction runtime memory"
            description="Templates appear after extraction persists a manifest or an activated correction."
            className="p-0"
          />
        ) : (
          <>
            <RuntimeSummary summary={data.summary} />
            <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
              {data.templates.map((template) => (
                <TemplateRow key={template.id} template={template} />
              ))}
            </div>
          </>
        )}
      </SurfaceSection>
      <KnowledgeGraphTab selectedWorkspace={selectedWorkspace} />
    </div>
  );
}

function RuntimeSummary({
  summary,
}: {
  summary: {
    template_count: number;
    recipe_count: number;
    selector_count: number;
    observation_count: number;
    release_count: number;
  };
}) {
  const items = [
    ['Templates', summary.template_count],
    ['Recipes', summary.recipe_count],
    ['Selectors', summary.selector_count],
    ['Observations', summary.observation_count],
    ['Releases', summary.release_count],
  ] as const;
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-3 border-b border-divider pb-4">
      {items.map(([label, value]) => (
        <div key={label} className="min-w-20">
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="mt-1 font-mono text-lg font-semibold text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function TemplateRow({ template }: { template: ExtractionMemoryTemplate }) {
  return (
    <section className="px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-foreground">
              {surfaceLabel(template.surface)}
            </span>
            <Badge tone={template.status === 'active' ? 'success' : 'warning'}>
              {template.status}
            </Badge>
            {template.tech_signals.map((signal) => (
              <Badge key={signal} tone="info">
                {signal}
              </Badge>
            ))}
          </div>
          <div className="mt-2 font-mono text-xs break-all text-muted">
            {template.route_pattern || template.fingerprint}
          </div>
        </div>
        <div className="text-right text-xs text-muted">
          <div>{template.observation_count} observations</div>
          <div>{template.manifest_count} manifests</div>
          <div>Last used {formatTimestamp(template.last_observed_at)}</div>
        </div>
      </div>
      {!template.recipes.length ? (
        <p className="mt-3 text-xs text-muted">Template observed. No recipe compiled.</p>
      ) : (
        <div className="mt-4 divide-y divide-border rounded-md bg-background-alt px-3">
          {template.recipes.map((recipe) => (
            <RecipeRow key={recipe.id} recipe={recipe} />
          ))}
        </div>
      )}
    </section>
  );
}

function RecipeRow({ recipe }: { recipe: ExtractionMemoryRecipe }) {
  const itemCount = recipe.kind === 'selectors' ? recipe.rule_count : recipe.contract_count;
  const itemLabel = recipe.kind === 'selectors' ? 'rules' : 'contracts';
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div>
        <div className="text-xs font-semibold text-foreground">
          {recipe.kind === 'selectors' ? 'Selector recipe' : 'Extraction contract'}
        </div>
        <div className="mt-1 text-xs text-muted">
          {recipe.layer} layer · version {recipe.version} · {itemCount} {itemLabel}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={recipe.compiled ? 'success' : 'warning'}>
          {recipe.compiled ? `Compiled ${recipe.compiled.compiler_version}` : 'Not compiled'}
        </Badge>
        <span className="text-xs text-muted">Updated {formatTimestamp(recipe.updated_at)}</span>
      </div>
    </div>
  );
}
