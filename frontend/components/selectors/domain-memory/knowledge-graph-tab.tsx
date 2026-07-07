import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Clipboard, RefreshCcw, Save, SlidersHorizontal } from 'lucide-react';

import type {
  ExtractionProfile,
  ExtractionProfilePin,
  KnowledgeContract,
  KnowledgeSiteRecord,
} from '../../../lib/api/types';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  SurfaceSection,
} from '../../ui/patterns';
import { Badge, Button, Dropdown, Field, Input, Textarea, Toggle } from '../../ui/primitives';
import type { DomainWorkspace } from './types';
import { useKnowledgeGraph } from './use-knowledge-graph';
import { knowledgeFieldLabel, knowledgeSourceOptions, surfaceLabel } from './utils';

type KnowledgeGraphTabProps = {
  selectedWorkspace: DomainWorkspace;
};

type OriginDescriptor = {
  label: string;
  tone: 'accent' | 'info' | 'neutral';
};

type ProfilePinDraft = {
  canonical_field: string;
  selected_source: string;
  required: boolean;
  value_sense: string;
  aliasesText: string;
};

const EMPTY_CONTRACTS: KnowledgeContract[] = [];
const EMPTY_PROFILES: Record<string, ExtractionProfile> = {};

export function KnowledgeGraphTab({ selectedWorkspace }: KnowledgeGraphTabProps) {
  const { query, selectSource, saveProfile } = useKnowledgeGraph(selectedWorkspace);
  const data = query.data ?? null;
  const site = scopedSite(data?.site, selectedWorkspace);
  const graphVersion = site?.current_version ?? null;
  const [profileDrafts, setProfileDrafts] = useState<Record<string, ProfilePinDraft[]>>({});

  const mutationError = selectSource.error
    ? selectSource.error instanceof Error
      ? selectSource.error.message
      : 'Unable to update extraction preference.'
    : '';
  const loadError = query.error
    ? query.error instanceof Error
      ? query.error.message
      : 'Unable to load extraction preferences.'
    : '';
  const contracts = data?.contracts ?? EMPTY_CONTRACTS;
  const profiles = data?.profiles ?? EMPTY_PROFILES;
  const groupedContracts = useMemo(() => groupContractsByTemplate(contracts), [contracts]);

  useEffect(() => {
    setProfileDrafts((current) => {
      const next = { ...current };
      for (const [surface, templateContracts] of groupedContracts) {
        const profile = profiles[surface] ?? null;
        next[surface] = mergeProfileDraft(templateContracts, profile, current[surface]);
      }
      return next;
    });
  }, [groupedContracts, profiles]);

  function runSelect(contract: KnowledgeContract, selectedSource: string) {
    if (!selectedSource) return;
    selectSource.mutate({ contract, selectedSource, expectedVersion: graphVersion });
  }

  function updateDraft(surface: string, field: string, patch: Partial<ProfilePinDraft>) {
    setProfileDrafts((current) => ({
      ...current,
      [surface]: (current[surface] ?? []).map((pin) =>
        pin.canonical_field === field ? { ...pin, ...patch } : pin,
      ),
    }));
  }

  function runSaveProfile(surface: string) {
    saveProfile.mutate({
      domain: selectedWorkspace.domain,
      surface,
      pins: (profileDrafts[surface] ?? []).map(profilePinPayload),
    });
  }

  return (
    <SurfaceSection
      title="Extraction preferences"
      description="Domain defaults for future crawls, scoped by surface and field—not by individual URL."
      icon={SlidersHorizontal}
      action={
        <Button
          type="button"
          variant="neutral"
          size="sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCcw className="size-3" />
          {query.isFetching ? 'Refreshing...' : 'Refresh'}
        </Button>
      }
      bodyClassName="space-y-5"
    >
      {loadError ? <DataRegionError message={loadError} className="p-0" /> : null}
      {mutationError ? <DataRegionError message={mutationError} className="p-0" /> : null}
      {saveProfile.error ? (
        <DataRegionError
          message={
            saveProfile.error instanceof Error
              ? saveProfile.error.message
              : 'Unable to save extraction profile.'
          }
          className="p-0"
        />
      ) : null}
      {query.isLoading ? (
        <DataRegionLoading count={5} className="p-0" />
      ) : (
        <>
          <PreferenceScope domain={selectedWorkspace.domain} site={site} contracts={contracts} />
          <ContractPanel
            domain={selectedWorkspace.domain}
            groupedContracts={groupedContracts}
            profiles={profiles}
            profileDrafts={profileDrafts}
            pendingContractId={
              selectSource.isPending ? (selectSource.variables?.contract.id ?? '') : ''
            }
            savedContractId={
              selectSource.isSuccess ? (selectSource.variables?.contract.id ?? '') : ''
            }
            pendingProfileSurface={
              saveProfile.isPending ? (saveProfile.variables?.surface ?? '') : ''
            }
            savedProfileSurface={saveProfile.isSuccess ? (saveProfile.data?.surface ?? '') : ''}
            onSelectSource={runSelect}
            onUpdateDraft={updateDraft}
            onSaveProfile={runSaveProfile}
          />
        </>
      )}
    </SurfaceSection>
  );
}

function PreferenceScope({
  domain,
  site,
  contracts,
}: {
  domain: string;
  site: KnowledgeSiteRecord | null;
  contracts: KnowledgeContract[];
}) {
  const surfaces = new Set(contracts.map((contract) => contract.surface)).size;
  return (
    <section className="rounded-lg border border-border bg-background-alt px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold text-foreground">{domain}</span>
        <Badge tone="neutral">
          {surfaces} {surfaces === 1 ? 'surface' : 'surfaces'}
        </Badge>
        {site ? <Badge tone="info">Version {site.current_version}</Badge> : null}
      </div>
      <p className="mt-2 text-xs text-muted">
        Manual choices apply to every current and future URL on this domain and surface.
      </p>
    </section>
  );
}

function ContractPanel({
  groupedContracts,
  domain,
  profiles,
  profileDrafts,
  pendingContractId,
  savedContractId,
  pendingProfileSurface,
  savedProfileSurface,
  onSelectSource,
  onUpdateDraft,
  onSaveProfile,
}: {
  groupedContracts: Array<readonly [string, KnowledgeContract[]]>;
  domain: string;
  profiles: Record<string, ExtractionProfile>;
  profileDrafts: Record<string, ProfilePinDraft[]>;
  pendingContractId: string;
  savedContractId: string;
  pendingProfileSurface: string;
  savedProfileSurface: string;
  onSelectSource: (contract: KnowledgeContract, selectedSource: string) => void;
  onUpdateDraft: (surface: string, field: string, patch: Partial<ProfilePinDraft>) => void;
  onSaveProfile: (surface: string) => void;
}) {
  if (!groupedContracts.length) {
    return (
      <DataRegionEmpty
        title="No extraction preferences yet"
        description="Source choices appear after a crawl observes usable field candidates or an operator activates a grounded correction."
        className="p-0"
      />
    );
  }
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Field defaults</h3>
        <p className="mt-1 text-xs text-muted">
          One reusable source choice per field. AI suggestions remain inactive until promoted.
        </p>
      </div>
      {groupedContracts.map(([surface, templateContracts]) => (
        <section key={surface} className="overflow-hidden rounded-lg border border-border">
          <header className="flex flex-wrap items-center justify-between gap-3 bg-background-alt px-4 py-3">
            <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-foreground">
              {surfaceLabel(surface)}
              {profiles[surface]?.pins.length ? (
                <Badge tone="accent">{profiles[surface].pins.length} pinned</Badge>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {savedProfileSurface === surface ? (
                <span className="flex items-center gap-1 text-xs font-medium text-success">
                  <CheckCircle2 className="size-3.5" /> Profile saved
                </span>
              ) : null}
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={pendingProfileSurface === surface}
                onClick={() => onSaveProfile(surface)}
              >
                <Save className="size-3" />
                {pendingProfileSurface === surface ? 'Saving...' : 'Save Profile'}
              </Button>
            </div>
          </header>
          <div className="divide-y divide-border">
            {templateContracts.map((contract) => (
              <ContractPreferenceRow
                key={contract.id}
                contract={contract}
                draft={
                  profileDrafts[surface]?.find(
                    (pin) => pin.canonical_field === contract.canonical_field,
                  ) ?? profileDraftFromContract(contract, null)
                }
                pending={pendingContractId === contract.id}
                saved={savedContractId === contract.id}
                onSelectSource={onSelectSource}
                onUpdateDraft={(patch) => onUpdateDraft(surface, contract.canonical_field, patch)}
              />
            ))}
          </div>
          <ProfileSnippet
            domain={profiles[surface]?.domain ?? domain}
            surface={surface}
            pins={profileDrafts[surface] ?? []}
          />
        </section>
      ))}
    </section>
  );
}

function ContractPreferenceRow({
  contract,
  draft,
  pending,
  saved,
  onSelectSource,
  onUpdateDraft,
}: {
  contract: KnowledgeContract;
  draft: ProfilePinDraft;
  pending: boolean;
  saved: boolean;
  onSelectSource: (contract: KnowledgeContract, selectedSource: string) => void;
  onUpdateDraft: (patch: Partial<ProfilePinDraft>) => void;
}) {
  const field = knowledgeFieldLabel(contract.canonical_field);
  const sourceOptions = knowledgeSourceOptions(contract);
  const dropdownOptions = sourceOptions.some((option) => option.value === draft.selected_source)
    ? sourceOptions
    : [
        ...sourceOptions,
        {
          value: draft.selected_source,
          label: draft.selected_source,
          kind: 'Pinned source',
          locator: draft.selected_source,
        },
      ].filter((option) => option.value);
  const selected =
    dropdownOptions.find((option) => option.value === draft.selected_source) ??
    sourceOptions.find((option) => option.value === contract.selected_source) ??
    sourceOptions[0];
  const origin = originDescriptor(contract.selection_origin);
  const isProposed = contract.selection_origin === 'llm_proposed';

  return (
    <div className="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.8fr)] lg:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-foreground">{field.label}</span>
          <Badge tone="neutral">{field.group}</Badge>
          <Badge tone={origin.tone}>{origin.label}</Badge>
          {saved ? (
            <span className="flex items-center gap-1 text-xs font-medium text-success">
              <CheckCircle2 className="size-3.5" /> Saved for this surface
            </span>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          <span>{contract.success_count} accepted observations</span>
          <span>{contract.rejection_count} rejected observations</span>
          {isProposed && selected ? (
            <Button
              type="button"
              variant="neutral"
              size="sm"
              disabled={pending}
              onClick={() => onSelectSource(contract, selected.value)}
            >
              Use as domain default
            </Button>
          ) : null}
        </div>
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 text-xs font-medium text-secondary">Preferred source</div>
        {dropdownOptions.length > 1 && selected ? (
          <Dropdown<string>
            value={draft.selected_source || selected.value}
            onChange={(value) => {
              onUpdateDraft({ selected_source: value });
              if (value !== contract.selected_source) onSelectSource(contract, value);
            }}
            options={dropdownOptions.map((source) => ({
              value: source.value,
              label: source.label,
            }))}
            ariaLabel={`Source for ${contract.canonical_field}`}
            disabled={pending}
          />
        ) : selected ? (
          <div className="flex min-h-[var(--control-height)] items-center justify-between gap-3 rounded-md border border-border bg-panel px-3 py-2">
            <span className="min-w-0 truncate text-xs text-foreground">{selected.label}</span>
            <span className="shrink-0 text-xs text-muted">Only observed source</span>
          </div>
        ) : (
          <div className="text-xs text-muted">No usable source observed</div>
        )}
        {selected?.locator ? (
          <div className="mt-1.5 truncate font-mono text-xs text-muted" title={selected.locator}>
            {selected.locator}
          </div>
        ) : null}
        <div className="mt-3 grid gap-3 sm:grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)] sm:items-end">
          <div className="flex items-center gap-2 pb-2">
            <Toggle
              checked={draft.required}
              onChange={(required) => onUpdateDraft({ required })}
              ariaLabel={`Required ${contract.canonical_field}`}
            />
            <span className="text-xs font-medium text-foreground">Required</span>
          </div>
          <Field label="Value sense">
            <Input
              value={draft.value_sense}
              onChange={(event) => onUpdateDraft({ value_sense: event.target.value })}
              placeholder="current_price"
            />
          </Field>
          <Field label="Aliases">
            <Input
              value={draft.aliasesText}
              onChange={(event) => onUpdateDraft({ aliasesText: event.target.value })}
              placeholder="sale price, member price"
            />
          </Field>
        </div>
      </div>
    </div>
  );
}

function ProfileSnippet({
  domain,
  surface,
  pins,
}: {
  domain: string;
  surface: string;
  pins: ProfilePinDraft[];
}) {
  const snippet = JSON.stringify(
    {
      domain,
      surface,
      pins: pins.map(profilePinPayload),
    },
    null,
    2,
  );
  return (
    <section className="border-t border-border bg-background-alt px-4 py-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-xs font-semibold text-foreground">Compiled binding</h4>
        <Button
          type="button"
          variant="neutral"
          size="sm"
          onClick={() => void navigator.clipboard?.writeText(snippet)}
        >
          <Clipboard className="size-3" />
          Copy
        </Button>
      </div>
      <Textarea
        aria-label={`Extraction profile snippet for ${surface}`}
        value={snippet}
        readOnly
        rows={Math.min(12, Math.max(5, pins.length * 5))}
        className="font-mono text-xs"
      />
    </section>
  );
}

// --- helpers ---------------------------------------------------------------

function originDescriptor(origin: string): OriginDescriptor {
  if (origin === 'operator') return { label: 'Manual default', tone: 'accent' };
  if (origin === 'llm_proposed') return { label: 'AI suggested', tone: 'info' };
  return { label: 'Automatic', tone: 'neutral' };
}

function groupContractsByTemplate(contracts: KnowledgeContract[]) {
  const groups = new Map<string, Map<string, KnowledgeContract[]>>();
  for (const contract of contracts) {
    const fields = groups.get(contract.surface) ?? new Map<string, KnowledgeContract[]>();
    const rows = fields.get(contract.canonical_field) ?? [];
    rows.push(contract);
    fields.set(contract.canonical_field, rows);
    groups.set(contract.surface, fields);
  }

  return Array.from(groups.entries()).map(
    ([surface, fields]) =>
      [
        surface,
        Array.from(fields.values())
          .map((rows) => {
            const preferred = rows[0];
            return {
              ...preferred,
              candidates: mergeContractRows(rows, 'candidates'),
              latest_values: mergeContractRows(rows, 'latest_values'),
              success_count: rows.reduce((total, row) => total + row.success_count, 0),
              rejection_count: rows.reduce((total, row) => total + row.rejection_count, 0),
            };
          })
          .sort((left, right) => left.canonical_field.localeCompare(right.canonical_field)),
      ] as const,
  );
}

function mergeProfileDraft(
  contracts: KnowledgeContract[],
  profile: ExtractionProfile | null,
  current: ProfilePinDraft[] | undefined,
) {
  const profilePins = new Map(profile?.pins.map((pin) => [pin.canonical_field, pin]) ?? []);
  const currentPins = new Map(current?.map((pin) => [pin.canonical_field, pin]) ?? []);
  return contracts.map((contract) =>
    profileDraftFromContract(
      contract,
      currentPins.get(contract.canonical_field) ??
        profilePins.get(contract.canonical_field) ??
        null,
    ),
  );
}

function profileDraftFromContract(
  contract: KnowledgeContract,
  pin: ExtractionProfilePin | ProfilePinDraft | null,
): ProfilePinDraft {
  const aliases = 'aliasesText' in (pin ?? {}) ? (pin as ProfilePinDraft).aliasesText : '';
  return {
    canonical_field: contract.canonical_field,
    selected_source: pin?.selected_source || contract.selected_source,
    required: Boolean(pin?.required),
    value_sense: String(pin?.value_sense ?? ''),
    aliasesText:
      aliases || ('aliases' in (pin ?? {}) ? (pin as ExtractionProfilePin).aliases.join(', ') : ''),
  };
}

function profilePinPayload(pin: ProfilePinDraft): ExtractionProfilePin {
  return {
    canonical_field: pin.canonical_field,
    selected_source: pin.selected_source,
    required: pin.required,
    value_sense: pin.value_sense.trim(),
    aliases: pin.aliasesText
      .split(',')
      .map((alias) => alias.trim())
      .filter(Boolean),
  };
}

function mergeContractRows(
  rows: KnowledgeContract[],
  key: 'candidates' | 'latest_values',
): Array<Record<string, unknown>> {
  const merged = new Map<string, Record<string, unknown>>();
  for (const row of rows) {
    for (const item of row[key]) {
      const source = String(item.source ?? '').trim();
      if (!source) continue;
      if (!merged.has(source)) merged.set(source, item);
    }
  }
  return Array.from(merged.values());
}

function scopedSite(
  stateSite: KnowledgeSiteRecord | null | undefined,
  workspace: DomainWorkspace,
): KnowledgeSiteRecord | null {
  const fromState = stateSite?.domain === workspace.domain ? stateSite : null;
  const fromWorkspace =
    workspace.knowledgeSite?.domain === workspace.domain ? workspace.knowledgeSite : null;
  if (!fromState) return fromWorkspace;
  if (!fromWorkspace) return fromState;
  return fromWorkspace.current_version > fromState.current_version ? fromWorkspace : fromState;
}
