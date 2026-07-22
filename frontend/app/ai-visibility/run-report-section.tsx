import { getApiBaseUrl } from '@/api/client';
import {
  aiVisibilityApi,
  type AiVisibilityExecution,
  type AiVisibilityProviderStatus,
  type AiVisibilityRun,
} from '../../lib/api/ai-visibility';
import { aiVisibilityStatusLabel, aiVisibilityStatusTone } from './ai-visibility-status';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card } from '../../components/ui/card';
import { Input } from '../../components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';

export function RunReportSection({
  run,
  executions,
  providers,
  completedCount,
  failedCount,
  showSummary,
  repetitions,
  onRepetitionsChange,
  rerunPending,
  onRerun,
  onViewExecution,
}: Readonly<{
  run: AiVisibilityRun;
  executions: AiVisibilityExecution[];
  providers: AiVisibilityProviderStatus[] | undefined;
  completedCount: number;
  failedCount: number;
  showSummary: boolean;
  repetitions: number;
  onRepetitionsChange: (value: number) => void;
  rerunPending: boolean;
  onRerun: () => void;
  onViewExecution: (executionId: number) => void;
}>) {
  return (
    <section className="page-stack">
      <div className="flex items-center gap-3">
        <h2 className="type-subheading text-foreground">Run #{run.id}</h2>
        <label htmlFor="rerun-reps" className="type-body-sm flex items-center gap-2 text-muted">
          Reps
          <Input
            id="rerun-reps"
            type="number"
            min={1}
            value={repetitions}
            onChange={(e) => onRepetitionsChange(Math.max(1, Number(e.target.value) || 1))}
            className="h-8 w-16"
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          onClick={onRerun}
          disabled={
            rerunPending || !providers?.find((item) => item.provider === run.provider)?.configured
          }
        >
          Re-run
        </Button>
      </div>

      <Card className="p-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Status">
            <Badge tone={aiVisibilityStatusTone(run.status)}>
              {aiVisibilityStatusLabel(run.status)}
            </Badge>
          </Stat>
          <Stat label="Progress">
            <span className="type-metric text-foreground">
              {completedCount + failedCount} / {run.requested_count}
            </span>
          </Stat>
          <Stat label="Failed">
            <span className={`type-metric ${failedCount > 0 ? 'text-danger' : 'text-foreground'}`}>
              {failedCount}
            </span>
          </Stat>
          <Stat label="Model">
            <span className="type-body-sm text-secondary">{run.model}</span>
          </Stat>
        </div>

        {showSummary && (
          <div className="mt-4 rounded-lg border border-border bg-background-alt p-4">
            <h4 className="type-label text-foreground">Summary</h4>
            <div className="type-body-sm mt-3 grid grid-cols-1 gap-3 text-secondary sm:grid-cols-3">
              <div>
                Brand mention rate:{' '}
                <strong className="text-foreground">{pct(run.summary.brand_mention_rate)}</strong>
              </div>
              <div>
                Owned citation rate:{' '}
                <strong className="text-foreground">{pct(run.summary.owned_citation_rate)}</strong>
              </div>
              <div>
                Search use rate:{' '}
                <strong className="text-foreground">{pct(run.summary.search_use_rate)}</strong>
              </div>
              <div>
                Tokens used:{' '}
                <strong className="text-foreground">{tokenTotal(run.summary.token_usage)}</strong>
              </div>
              <div>
                Grounded requests:{' '}
                <strong className="text-foreground">
                  {costValue(run.summary.cost, 'grounded_requests').toLocaleString()}
                </strong>
              </div>
            </div>
            <div className="mt-3 flex gap-4">
              <a
                className="link-accent type-body-sm no-underline hover:underline"
                href={`${getApiBaseUrl()}${aiVisibilityApi.getAiVisibilityExportCsvUrl(run.id)}`}
                download
              >
                Download CSV
              </a>
              <a
                className="link-accent type-body-sm no-underline hover:underline"
                href={`${getApiBaseUrl()}${aiVisibilityApi.getAiVisibilityExportMarkdownUrl(run.id)}`}
                download
              >
                Download Markdown
              </a>
            </div>
          </div>
        )}

        {/* Executions Table */}
        <div className="mt-4">
          <h4 className="type-label mb-2 text-foreground">Executions</h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Prompt</TableHead>
                <TableHead className="text-center">Rep</TableHead>
                <TableHead className="text-center">Status</TableHead>
                <TableHead className="text-center">Search</TableHead>
                <TableHead className="text-center">Brand</TableHead>
                <TableHead className="text-center">Owned</TableHead>
                <TableHead className="text-center">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {executions.map((exec) => (
                <TableRow key={exec.id}>
                  <TableCell>{exec.prompt_text_snapshot}</TableCell>
                  <TableCell className="text-center">{exec.repetition}</TableCell>
                  <TableCell className="text-center">
                    <Badge tone={aiVisibilityStatusTone(exec.status)} flat>
                      {aiVisibilityStatusLabel(exec.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-center">
                    <Mark on={exec.search_used} />
                  </TableCell>
                  <TableCell className="text-center">
                    <Mark on={Boolean(exec.score?.brand_mentioned)} />
                  </TableCell>
                  <TableCell className="text-center">
                    <Mark on={Boolean(exec.score?.owned_domain_cited)} />
                  </TableCell>
                  <TableCell className="text-center">
                    {['completed', 'failed'].includes(exec.status) && (
                      <Button variant="ghost" size="sm" onClick={() => onViewExecution(exec.id)}>
                        View
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>
    </section>
  );
}

// --------------------------------------------------------------------------
// Small presentational helpers
// --------------------------------------------------------------------------
function Stat({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div>
      <div className="type-caption text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function Mark({ on }: Readonly<{ on: boolean }>) {
  return on ? <span className="text-success">✓</span> : <span className="text-muted">—</span>;
}

export function pct(value: unknown): string {
  const n = typeof value === 'number' ? value : 0;
  return `${(n * 100).toFixed(0)}%`;
}

// Render total tokens with input/output breakdown, e.g. "12,720 (in 150 / out 7,875)".
export function tokenTotal(value: unknown): string {
  const usage = (value ?? {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === 'number' ? v : 0);
  const total = num(usage.total_tokens);
  const input = num(usage.input_tokens);
  const output = num(usage.output_tokens);
  if (total === 0 && input === 0 && output === 0) return '—';
  const fmt = (n: number) => n.toLocaleString();
  return `${fmt(total)} (in ${fmt(input)} / out ${fmt(output)})`;
}

export function costValue(value: unknown, key: string): number {
  const cost = (value ?? {}) as Record<string, unknown>;
  return typeof cost[key] === 'number' ? cost[key] : 0;
}
