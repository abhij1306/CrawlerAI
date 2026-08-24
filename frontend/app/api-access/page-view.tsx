import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, PlugZap, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { queryKeys } from '@/api/query-keys';
import {
  apiAccessApi,
  type ApiKeyCreated,
  type ApiKeyRecord,
  type PublicApiCapabilities,
} from '@lib/api/api-access';
import { formatAdminUserDate } from '@lib/format/date';
import { Button, Field, Input } from '@ui/primitives';
import { ConfirmDialog } from '@ui/dialog';
import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  SectionCard,
} from '@ui/patterns';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@ui/table';
import { ApiAccessConnect } from './api-access-connect';
import { ApiAccessSetup } from './api-access-setup';

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default function ApiAccessPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [capabilities, setCapabilities] = useState<PublicApiCapabilities | null>(null);
  const [probeError, setProbeError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<ApiKeyRecord | null>(null);
  const keysQuery = useQuery({
    queryKey: queryKeys.apiAccess.keys(),
    queryFn: apiAccessApi.listKeys,
  });
  const createMutation = useMutation({
    mutationFn: apiAccessApi.createKey,
    onSuccess: async (key) => {
      setCreated(key);
      setName('');
      setCapabilities(null);
      setProbeError('');
      await queryClient.invalidateQueries({ queryKey: queryKeys.apiAccess.all });
      try {
        setCapabilities(await apiAccessApi.getCapabilities(key.api_key));
      } catch (error) {
        setProbeError(errorMessage(error, 'Unable to verify the public API.'));
      }
    },
  });
  const deleteMutation = useMutation({
    mutationFn: apiAccessApi.deleteKey,
    onSuccess: async (_result, deletedKeyId) => {
      setDeleteTarget(null);
      // The one-time secret panel must not outlive the key it belongs to.
      if (created?.id === deletedKeyId) {
        setCreated(null);
        setCapabilities(null);
        setProbeError('');
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.apiAccess.all });
    },
  });

  function createKey(event: React.FormEvent) {
    event.preventDefault();
    const cleanedName = name.trim();
    if (cleanedName) createMutation.mutate(cleanedName);
  }

  const keys = keysQuery.data ?? [];

  return (
    <div className="page-stack">
      <PageHeader title="API & MCP" description="Create credentials for REST and MCP clients." />

      <SectionCard
        title="Create API key"
        description="Keys inherit your account access and authenticate both the public API and MCP server."
      >
        <form className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={createKey}>
          <Field label="Key name" required className="flex-1">
            {(fieldProps) => (
              <Input
                {...fieldProps}
                value={name}
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                placeholder="Local MCP"
                autoComplete="off"
              />
            )}
          </Field>
          <Button
            type="submit"
            variant="action"
            disabled={!name.trim() || createMutation.isPending}
          >
            <KeyRound className="size-4" />
            {createMutation.isPending ? 'Creating...' : 'Create key'}
          </Button>
        </form>
        {createMutation.error ? (
          <InlineAlert message={errorMessage(createMutation.error, 'Unable to create API key.')} />
        ) : null}
        {created ? (
          <ApiAccessSetup
            created={created}
            capabilities={capabilities}
            probeError={probeError}
            onDismiss={() => setCreated(null)}
          />
        ) : null}
      </SectionCard>

      <SectionCard
        title="API keys"
        description="Delete credentials you no longer use. Deletion can take up to one minute to propagate across running API processes."
      >
        {keysQuery.error ? (
          <InlineAlert message={errorMessage(keysQuery.error, 'Unable to load API keys.')} />
        ) : null}
        {keysQuery.isLoading ? <DataRegionLoading count={3} /> : null}
        {!keysQuery.isLoading && !keys.length ? (
          <DataRegionEmpty
            title="No API keys"
            description="Create a key to connect a REST or MCP client."
            className="px-0"
          />
        ) : null}
        {keys.length ? (
          <div className="surface-muted rounded-md border">
            {/* No status column: deleting removes the row, so every key listed
                here is by definition active. */}
            <Table className="compact-data-table min-w-[720px] table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Prefix</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Last used</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.map((key) => (
                  <TableRow key={key.id}>
                    <TableCell className="font-medium text-foreground">{key.name}</TableCell>
                    <TableCell className="font-mono text-base">{key.key_prefix}…</TableCell>
                    <TableCell className="text-base">
                      {formatAdminUserDate(key.created_at)}
                    </TableCell>
                    <TableCell className="text-base">
                      {key.last_used_at ? formatAdminUserDate(key.last_used_at) : 'Never'}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        onClick={() => setDeleteTarget(key)}
                      >
                        <Trash2 className="size-3.5" />
                        Delete
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </SectionCard>

      <ApiAccessConnect />

      <SectionCard
        title="Public REST API"
        description="Use the same key as a Bearer token against /api/v1. Single-product extraction is HTTP-only and bounded by the public API timeout."
      >
        <div className="flex items-start gap-3 rounded-md border border-border bg-panel px-4 py-3">
          <PlugZap className="mt-0.5 size-4 shrink-0 text-muted" />
          <p className="type-body m-0">
            Batch extraction remains deferred. Use Crawl Studio for browser-required pages and
            queued workloads.
          </p>
        </div>
        <div className="mt-3 flex items-start gap-3 rounded-md border border-border bg-panel px-4 py-3">
          <PlugZap className="mt-0.5 size-4 shrink-0 text-muted" />
          <p className="type-body m-0">
            MCP is local-only in this release: use stdio by default, or bind SSE to a literal
            loopback address. Public hosted MCP is blocked until every caller has independent
            inbound authentication.
          </p>
        </div>
      </SectionCard>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete API key?"
        description={
          <>
            <strong>{deleteTarget?.name}</strong> will be deleted permanently and will stop
            authenticating API and MCP requests. This cannot be undone.
          </>
        }
        confirmLabel="Delete key"
        danger
        pending={deleteMutation.isPending}
        error={
          deleteMutation.error
            ? errorMessage(deleteMutation.error, 'Unable to delete API key.')
            : undefined
        }
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
      />
    </div>
  );
}
