import type { AiVisibilityExecution } from '../../lib/api/ai-visibility';
import { AppDialog } from '../../components/ui/dialog';
import { Textarea } from '../../components/ui/input';

export function ExecutionDetailDialog({
  execution,
  open,
  onOpenChange,
}: Readonly<{
  execution: AiVisibilityExecution | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>) {
  return (
    <AppDialog
      open={open}
      onOpenChange={onOpenChange}
      title={execution ? `Execution #${execution.id}` : 'Execution'}
    >
      {execution && (
        <div className="page-stack p-4">
          <div>
            <span className="field-label">Prompt</span>
            <p className="type-body mt-1 text-secondary">{execution.prompt_text_snapshot}</p>
          </div>

          <div>
            <span className="field-label">Answer</span>
            <div className="type-body-sm mt-1 rounded-lg border border-border bg-background-alt p-3 whitespace-pre-wrap text-secondary">
              {execution.answer_text || '(No answer)'}
            </div>
          </div>

          {execution.error_code ? (
            <div className="rounded-md border border-danger/20 bg-danger/10 p-3 text-sm text-danger">
              <strong>{execution.error_code}</strong>
              {execution.error_message ? ` — ${execution.error_message}` : ''}
            </div>
          ) : null}

          {execution.search_events && execution.search_events.length > 0 && (
            <div>
              <span className="field-label">Search queries</span>
              {execution.search_events.some((event) => event.query?.trim()) ? (
                <ul className="type-body-sm mt-1 list-disc pl-5 text-secondary">
                  {execution.search_events
                    .filter((event) => event.query?.trim())
                    .map((event, idx) => (
                      <li key={idx}>{event.query}</li>
                    ))}
                </ul>
              ) : (
                <p className="type-body-sm mt-1 text-secondary">
                  {execution.search_events.length} web{' '}
                  {execution.search_events.length === 1 ? 'search' : 'searches'} run (this provider
                  does not expose the query text).
                </p>
              )}
            </div>
          )}

          {execution.citations && execution.citations.length > 0 && (
            <div>
              <span className="field-label">Citations</span>
              <ul className="type-body-sm mt-1 list-disc pl-5 text-secondary">
                {execution.citations.map((citation, idx) => (
                  <li key={idx}>
                    {String(citation.domain ?? '')} — {String(citation.title ?? '')}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <span className="field-label">Score</span>
            <Textarea
              readOnly
              value={JSON.stringify(execution.score, null, 2)}
              className="mt-1 h-40 font-mono text-xs"
            />
          </div>
        </div>
      )}
    </AppDialog>
  );
}
