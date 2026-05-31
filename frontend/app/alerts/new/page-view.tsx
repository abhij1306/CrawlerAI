'use client';

import { useRouter } from 'next/navigation';

import { alertsApi } from '../../../lib/api';
import type { AlertCreatePayload, AlertUpdatePayload } from '../../../lib/api/types';
import { AlertForm } from '../../../components/monitors/alert-form';
import { PageHeader, SurfacePanel } from '../../../components/ui/patterns';

export default function NewAlertPage() {
  const router = useRouter();

  async function submit(payload: AlertCreatePayload | AlertUpdatePayload) {
    const alert = await alertsApi.create(payload as AlertCreatePayload);
    router.push(`/alerts/${alert.id}`);
  }

  return (
    <div className="page-stack">
      <PageHeader title="New Product Alert" description="Create a price or availability alert." />
      <SurfacePanel className="p-5">
        <AlertForm
          submitLabel="Create Alert"
          onSubmit={submit}
          onCancel={() => router.push('/alerts')}
        />
      </SurfacePanel>
    </div>
  );
}
