import { RefreshCcw, Trash2 } from 'lucide-react';

import { ConfirmDialog } from '../../ui/dialog';
import { EmptyPanel, InlineAlert, MutedPanelMessage, PageHeader, TabBar } from '../../ui/patterns';
import { Button, Dropdown, Input } from '../../ui/primitives';
import type { DomainMemoryWorkspaceController } from './use-domain-memory-workspace';
import { CookiesTab } from './cookies-tab';
import { DomainSidebar } from './domain-sidebar';
import { LearningTab } from './learning-tab';
import { ProfilesTab } from './profiles-tab';
import { SelectorsTab } from './selectors-tab';
import { getProfileCount, getTotalSelectorCount, surfaceLabel } from './utils';

type DomainMemoryContentProps = { controller: DomainMemoryWorkspaceController };

export function DomainMemoryContent({ controller }: DomainMemoryContentProps) {
  const selectedWorkspace = controller.selectedWorkspace;
  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Domain Memory"
        description="Manage learned selectors, run profiles, cookies, and recent learning by domain."
        actions={domainMemoryActions(controller)}
      />
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative min-w-0 flex-1">
          <Input
            value={controller.searchQuery}
            onChange={(event) => controller.setSearchQuery(event.target.value)}
            placeholder="Search domain, field, selector text, fetch mode, or feedback"
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
          description="Fetching saved selectors, run profiles, cookies, and recent learning."
        />
      ) : !controller.groupedWorkspaces.length ? (
        <EmptyPanel
          title="No domain memory found"
          description="Run a crawl, save selectors, or keep learning signals to populate this workspace."
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
        description="Delete saved selectors, run profiles, field feedback, saved cookies, host protection memory, and runtime cookie files for a fresh start."
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
        variant="secondary"
        className="h-[var(--control-height)]"
        onClick={() => {
          controller.setResetError('');
          controller.setResetDialogOpen(true);
        }}
        disabled={controller.resetPending}
      >
        <Trash2 className="size-3.5" />
        {controller.resetPending ? 'Resetting...' : 'Reset Domain Memory'}
      </Button>
      <Button
        type="button"
        variant="secondary"
        className="h-[var(--control-height)]"
        onClick={() => void controller.loadWorkspace()}
        disabled={controller.loading || controller.resetPending}
      >
        <RefreshCcw className="size-3.5" />
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
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-foreground type-heading text-lg font-semibold">
          {selectedWorkspace.domain}
        </h2>
        {selectedWorkspace.surfaces.some((surface) => surface.selectorCount) ? (
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={() => void controller.deleteDomainSelectors(selectedWorkspace.domain)}
          >
            <Trash2 className="size-3.5" />
            Clear Selectors
          </Button>
        ) : null}
      </div>
      <TabBar
        value={controller.activeTab}
        onChange={controller.setActiveTab}
        options={tabOptions(selectedWorkspace)}
      />
      {controller.activeTab === 'selectors' ? (
        <SelectorsTab {...controller} selectedWorkspace={selectedWorkspace} />
      ) : null}
      {controller.activeTab === 'profiles' ? (
        <ProfilesTab {...controller} selectedWorkspace={selectedWorkspace} />
      ) : null}
      {controller.activeTab === 'cookies' ? (
        <CookiesTab selectedWorkspace={selectedWorkspace} />
      ) : null}
      {controller.activeTab === 'learning' ? (
        <LearningTab selectedWorkspace={selectedWorkspace} />
      ) : null}
    </>
  );
}

function tabOptions(
  selectedWorkspace: NonNullable<DomainMemoryWorkspaceController['selectedWorkspace']>,
) {
  return [
    {
      value: 'selectors',
      label: `Selectors (${getTotalSelectorCount(selectedWorkspace.surfaces)})`,
    },
    {
      value: 'profiles',
      label: `Profiles (${getProfileCount(selectedWorkspace.surfaces)})`,
    },
    {
      value: 'cookies',
      label: `Cookies${selectedWorkspace.cookieMemory ? ` (${selectedWorkspace.cookieMemory.cookie_count})` : ''}`,
    },
    { value: 'learning', label: `Learning (${selectedWorkspace.learning.length})` },
  ];
}
