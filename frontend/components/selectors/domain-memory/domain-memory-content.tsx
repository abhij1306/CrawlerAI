import { RefreshCcw, Trash2 } from 'lucide-react';

import { ConfirmDialog } from '../../ui/dialog';
import { EmptyPanel, InlineAlert, MutedPanelMessage, PageHeader, TabBar } from '../../ui/patterns';
import { Button, Dropdown, Input } from '../../ui/primitives';
import type { DomainMemoryWorkspaceController } from './use-domain-memory-workspace';
import { CookiesTab } from './cookies-tab';
import { DomainSidebar } from './domain-sidebar';
import { ExtractionMemoryTab } from './extraction-memory-tab';
import { LearningTab } from './learning-tab';
import { ProfilesTab } from './profiles-tab';
import { SelectorsTab } from './selectors-tab';
import { getProfileCount, surfaceLabel } from './utils';

type DomainMemoryContentProps = { controller: DomainMemoryWorkspaceController };

export function DomainMemoryContent({ controller }: DomainMemoryContentProps) {
  const selectedWorkspace = controller.selectedWorkspace;
  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Domain Memory"
        description="Inspect run profiles, cookies, grounded learning, and extraction contracts by domain."
        actions={domainMemoryActions(controller)}
      />
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative min-w-0 flex-1">
          <Input
            value={controller.searchQuery}
            onChange={(event) => controller.setSearchQuery(event.target.value)}
            placeholder="Search domain, fetch mode, feedback, or completed run"
          />
        </div>
        <Dropdown<string>
          value={controller.surfaceFilter}
          onChange={controller.setSurfaceFilter}
          options={[
            { value: 'all', label: 'All surfaces' },
            ...controller.availableSurfaces.map((surface) => ({
              value: surface,
              label: surfaceLabel(surface),
            })),
          ]}
          ariaLabel="Filter by surface"
        />
      </div>
      {controller.error ? <InlineAlert message={controller.error} /> : null}
      {!controller.hasLoadedOnce ? (
        <MutedPanelMessage
          title="Loading domain memory"
          description="Fetching run profiles, cookies, grounded learning, and extraction contracts."
        />
      ) : !controller.groupedWorkspaces.length ? (
        <EmptyPanel
          title="No domain memory found"
          description="Complete a crawl or activate a grounded correction to populate this workspace."
        />
      ) : selectedWorkspace ? (
        <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
          <DomainSidebar
            groupedWorkspaces={controller.groupedWorkspaces}
            resolvedSelectedDomain={controller.resolvedSelectedDomain}
            setSelectedDomain={controller.setSelectedDomain}
          />
          <div className="space-y-4">
            <DomainDetail controller={controller} />
          </div>
        </div>
      ) : null}
      <ConfirmDialog
        open={controller.resetDialogOpen}
        onOpenChange={(open) => {
          if (!controller.resetPending) {
            controller.setResetDialogOpen(open);
            if (!open) controller.setResetError('');
          }
        }}
        title="Reset domain memory"
        description="Delete extraction recipes, run profiles, field feedback, saved cookies, host protection memory, and runtime cookie files for a fresh start."
        confirmLabel="Reset Domain Memory"
        pending={controller.resetPending}
        danger
        error={controller.resetError}
        onConfirm={() => void controller.resetDomainMemoryWorkspace()}
      />
    </div>
  );
}

function domainMemoryActions(controller: DomainMemoryWorkspaceController) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="destructive"
        size="sm"
        onClick={() => {
          controller.setResetError('');
          controller.setResetDialogOpen(true);
        }}
        disabled={controller.resetPending}
      >
        <Trash2 className="size-3" />
        {controller.resetPending ? 'Resetting...' : 'Reset Domain Memory'}
      </Button>
      <Button
        type="button"
        variant="neutral"
        size="sm"
        onClick={() => void controller.loadWorkspace()}
        disabled={controller.loading || controller.resetPending}
      >
        <RefreshCcw className="size-3" />
        {controller.loading ? 'Refreshing...' : 'Refresh'}
      </Button>
    </div>
  );
}

function DomainDetail({ controller }: DomainMemoryContentProps) {
  const selectedWorkspace = controller.selectedWorkspace;
  if (!selectedWorkspace) return null;
  return (
    <>
      <h2 className="type-heading-3 truncate">{selectedWorkspace.domain}</h2>
      <TabBar
        value={controller.activeTab}
        onChange={controller.setActiveTab}
        options={tabOptions(selectedWorkspace)}
      />
      {controller.activeTab === 'profiles' ? (
        <ProfilesTab {...controller} selectedWorkspace={selectedWorkspace} />
      ) : null}
      {controller.activeTab === 'cookies' ? (
        <CookiesTab selectedWorkspace={selectedWorkspace} />
      ) : null}
      {controller.activeTab === 'learning' ? (
        <LearningTab selectedWorkspace={selectedWorkspace} />
      ) : null}
      {controller.activeTab === 'selectors' ? (
        <SelectorsTab domain={selectedWorkspace.domain} />
      ) : null}
      {controller.activeTab === 'knowledge' ? (
        <ExtractionMemoryTab selectedWorkspace={selectedWorkspace} />
      ) : null}
    </>
  );
}

function tabOptions(
  selectedWorkspace: NonNullable<DomainMemoryWorkspaceController['selectedWorkspace']>,
) {
  return [
    {
      value: 'profiles',
      label: `Profiles (${getProfileCount(selectedWorkspace.surfaces)})`,
    },
    {
      value: 'cookies',
      label: `Cookies${selectedWorkspace.cookieMemory ? ` (${selectedWorkspace.cookieMemory.cookie_count})` : ''}`,
    },
    { value: 'learning', label: `Learning (${selectedWorkspace.learning.length})` },
    { value: 'selectors', label: 'Selectors' },
    { value: 'knowledge', label: 'Extraction' },
  ];
}
