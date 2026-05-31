'use client';

import dynamic from 'next/dynamic';

const CartesianGrid = dynamic(() => import('recharts').then((mod) => mod.CartesianGrid), {
  ssr: false,
});
const Line = dynamic(() => import('recharts').then((mod) => mod.Line), { ssr: false });
const LineChart = dynamic(() => import('recharts').then((mod) => mod.LineChart), { ssr: false });
const ResponsiveContainer = dynamic(
  () => import('recharts').then((mod) => mod.ResponsiveContainer),
  { ssr: false },
);
const Tooltip = dynamic(() => import('recharts').then((mod) => mod.Tooltip), { ssr: false });
const XAxis = dynamic(() => import('recharts').then((mod) => mod.XAxis), { ssr: false });
const YAxis = dynamic(() => import('recharts').then((mod) => mod.YAxis), { ssr: false });

export type MonitorHistoryPoint = {
  time: string;
  records: number;
  changes: number;
};

export default function MonitorHistoryLineChart({
  rows,
}: Readonly<{ rows: MonitorHistoryPoint[] }>) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={rows} margin={{ top: 12, right: 20, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="time" tick={{ fill: 'var(--muted)', fontSize: 11 }} />
        <YAxis tick={{ fill: 'var(--muted)', fontSize: 11 }} allowDecimals={false} />
        <Tooltip
          contentStyle={{
            background: 'var(--bg-panel)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
          }}
        />
        <Line
          type="monotone"
          dataKey="records"
          stroke="var(--accent)"
          strokeWidth={2}
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="changes"
          stroke="var(--warning)"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
