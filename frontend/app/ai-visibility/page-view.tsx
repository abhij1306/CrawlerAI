import { History } from 'lucide-react';

import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { ConfirmDialog } from '../../components/ui/dialog';
import { HistoryDrawer } from '../../components/ui/history-drawer';
import { DomainWorkspace } from './domain-workspace';
import { ExecutionDetailDialog } from './execution-detail-dialog';
import { ProjectFormDialog } from './project-form-dialog';
import { RunReportSection } from './run-report-section';
import { useAiVisibility } from './use-ai-visibility';

export default function AiVisibilityPage() {
  const page = useAiVisibility();

  return (
    <div className="page-stack-lg">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-divider bg-background-alt px-3 py-2">
        <span className="type-caption mr-1 text-muted">Providers</span>
        {(page.providers ?? []).map((item) => (
          <span
            key={item.provider}
            className="type-body-sm flex items-center gap-1.5 text-secondary"
          >
            <span className={item.configured ? 'text-success' : 'text-danger'}>●</span>
            {item.label}
          </span>
        ))}
      </div>

      <section className="page-stack">
        <div className="flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h2 className="type-subheading text-foreground">Domains & Prompt Panels</h2>
            <p className="type-body-sm text-muted">
              Edit prompts in place. Run one prompt or the full saved panel.
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => page.openHistory(null)}>
            <History className="size-3.5" /> Report history ({page.savedRuns.length})
          </Button>
          <Button variant="primary" size="sm" onClick={() => page.setFormOpen(true)}>
            New Domain
          </Button>
        </div>

        {page.projects.length === 0 ? (
          <Card className="p-4">
            <p className="type-body text-muted">No projects yet. Create one to get started.</p>
          </Card>
        ) : (
          <div className="grid gap-3">
            {page.projects.map((project) => (
              <DomainWorkspace
                key={project.id}
                project={project}
                providers={page.providers ?? []}
                historyCount={
                  page.savedRuns.filter((item) => item.project_id === project.id).length
                }
                runPending={page.createRunPending}
                savePending={page.updateProjectPending}
                onSavePrompts={page.saveProjectPrompts}
                onRun={page.handleRunBenchmark}
                onOpenHistory={page.openHistory}
              />
            ))}
          </div>
        )}
      </section>

      {/* Active Run */}
      {page.run && (
        <RunReportSection
          run={page.run}
          executions={page.executions}
          providers={page.providers}
          completedCount={page.completedCount}
          failedCount={page.failedCount}
          showSummary={page.showSummary}
          repetitions={page.repetitions}
          onRepetitionsChange={page.setRepetitions}
          rerunPending={page.createRunPending}
          onRerun={() =>
            page.handleRunBenchmark({
              projectId: page.run!.project_id,
              repetitions: page.repetitions,
              provider: page.run!.provider,
              openReport: true,
            })
          }
          onViewExecution={page.setSelectedExecutionId}
        />
      )}

      <HistoryDrawer
        open={page.historyOpen}
        onClose={() => page.setHistoryOpen(false)}
        items={page.historyItems}
        activeId={page.activeRunId}
        onSelect={(runId) => page.setActiveRunId(runId)}
        onDelete={(runId) => page.setDeleteRunId(runId)}
        onCancel={(runId) => page.setCancelRunId(runId)}
        title={
          page.historyProjectId
            ? `${page.projects.find((project) => project.id === page.historyProjectId)?.name ?? 'Domain'} reports`
            : 'AI Visibility Reports'
        }
      />

      <ConfirmDialog
        open={page.deleteRunId !== null}
        onOpenChange={(open) => !open && page.setDeleteRunId(null)}
        title="Delete saved report?"
        description="This permanently removes the benchmark run and every stored execution."
        confirmLabel="Delete report"
        danger
        pending={page.deleteRunPending}
        onConfirm={page.confirmDeleteRun}
      />

      <ConfirmDialog
        open={page.cancelRunId !== null}
        onOpenChange={(open) => !open && page.setCancelRunId(null)}
        title="Stop this run?"
        description="This cancels the run and marks its unfinished executions cancelled. Any live worker stops after its current execution. Use this to clear runs stuck on 'running'."
        confirmLabel="Kill run"
        danger
        pending={page.cancelRunPending}
        onConfirm={page.confirmCancelRun}
      />

      <ProjectFormDialog
        open={page.formOpen}
        onOpenChange={page.setFormOpen}
        preset={page.bestAndLessPreset}
        pending={page.createProjectPending}
        onSubmit={page.createProject}
      />

      <ExecutionDetailDialog
        execution={page.executionDetail}
        open={page.selectedExecutionId !== null}
        onOpenChange={(open) => !open && page.setSelectedExecutionId(null)}
      />
    </div>
  );
}
