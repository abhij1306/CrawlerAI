'use client';

import { ClipboardCheck, Globe } from 'lucide-react';
import type { Route } from 'next';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { api } from '../../lib/api';
import type { PageAuditContext } from '../../lib/api/types';
import { PageHeader, TabBar } from '../ui/patterns';
import { Badge, Button, Card, Dropdown } from '../ui/primitives';
import { TargetUrlField } from './shared';

export function CrawlWorkspaceTabs({
  value,
  onChange,
}: Readonly<{
  value: 'crawl' | 'audit';
  onChange: (value: string) => void;
}>) {
  return (
    <TabBar
      value={value}
      onChange={onChange}
      options={[
        { value: 'crawl', label: 'Crawl', icon: <Globe className="size-3.5" /> },
        { value: 'audit', label: 'Audit', icon: <ClipboardCheck className="size-3.5" /> },
      ]}
    />
  );
}

export function CrawlWorkspaceHeader({
  value,
  onChange,
}: Readonly<{
  value: 'crawl' | 'audit';
  onChange: (value: string) => void;
}>) {
  return (
    <>
      <PageHeader
        title="Crawl Studio"
        description="Configure crawls or run a technical page audit."
      />
      <CrawlWorkspaceTabs value={value} onChange={onChange} />
    </>
  );
}

export function CrawlAuditMode({
  targetUrl,
  onTargetUrlChange,
  onWorkspaceChange,
}: Readonly<{
  targetUrl: string;
  onTargetUrlChange: (value: string) => void;
  onWorkspaceChange: (value: string) => void;
}>) {
  const router = useRouter();
  const [context, setContext] = useState<PageAuditContext>('auto');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function startAudit() {
    setSubmitting(true);
    setError('');
    try {
      const job = await api.createPageAuditJob({ url: targetUrl.trim(), context });
      router.replace(`/crawl?audit_job_id=${job.id}` as Route);
    } catch (auditError) {
      setError(auditError instanceof Error ? auditError.message : 'Unable to start page audit.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-stack gap-4">
      <CrawlWorkspaceHeader value="audit" onChange={onWorkspaceChange} />
      <form
        className="grid gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          void startAudit();
        }}
      >
        <Card className="section-card overflow-hidden p-0">
          <header className="border-border flex h-10 items-center justify-between border-b bg-[color-mix(in_srgb,var(--bg-alt)_40%,var(--bg-panel))] px-6">
            <span className="type-heading-3">Page Audit</span>
            <Badge tone="accent" className="h-5 px-1.5 text-xs font-medium">
              Technical
            </Badge>
          </header>
          <div className="grid gap-5 px-6 pt-5 pb-6 lg:grid-cols-[minmax(0,1fr)_220px_auto] lg:items-end">
            <TargetUrlField
              value={targetUrl}
              onChange={onTargetUrlChange}
              placeholder="https://example.com/page"
            />
            <label className="grid gap-2">
              <span className="type-control font-medium">Audit Context</span>
              <Dropdown<PageAuditContext>
                ariaLabel="Audit Context"
                value={context}
                onChange={setContext}
                options={[
                  { value: 'auto', label: 'Auto Detect' },
                  { value: 'generic', label: 'Generic Page' },
                  { value: 'ecommerce', label: 'Ecommerce Page' },
                ]}
              />
            </label>
            <Button
              variant="action"
              type="submit"
              disabled={!targetUrl.trim() || submitting}
              className="min-w-[132px]"
            >
              <ClipboardCheck className="size-4" />
              {submitting ? 'Starting...' : 'Start Audit'}
            </Button>
          </div>
        </Card>
        {error ? <div className="text-danger type-body">{error}</div> : null}
      </form>
    </div>
  );
}
