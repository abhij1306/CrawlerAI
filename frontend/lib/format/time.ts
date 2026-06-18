export function formatSeconds(seconds: number | null | undefined): string {
  const value = Math.abs(seconds ?? 0);
  if (value >= 3600) return `${Math.round(value / 3600)}h`;
  if (value >= 60) return `${Math.round(value / 60)}m`;
  return `${value}s`;
}
