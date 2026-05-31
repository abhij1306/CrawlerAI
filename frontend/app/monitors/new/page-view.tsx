'use client';

import { useRouter } from 'next/navigation';

import { monitorsApi } from '../../../lib/api';
import type { MonitorCreatePayload } from '../../../lib/api/types';
import { MonitorForm } from '../../../components/monitors/monitor-form';
import { PageHeader, SurfacePanel } from '../../../components/ui/patterns';

export default function NewMonitorPage() {
  const router = useRouter();

  /**
   * Errors from create/navigation are delegated to MonitorForm, which renders
   * submit failures inline.
   */
  async function submit(payload: MonitorCreatePayload) {
    const monitor = await monitorsApi.create(payload);
    router.push(`/monitors/${monitor.id}`);
  }

  return (
    <div className="page-stack">
      <PageHeader title="New Monitor" description="Create a recurring extraction monitor." />
      <SurfacePanel className="p-5">
        <MonitorForm
          layout="grid"
          submitLabel="Create Monitor"
          onSubmit={submit}
          onCancel={() => router.push('/monitors')}
        />
      </SurfacePanel>
    </div>
  );
}
