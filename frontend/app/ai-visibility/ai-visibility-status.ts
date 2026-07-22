import { dashboardStatusLabel, statusTone } from '../../lib/ui/status';

type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info';

// Tone and labels always come from the canonical status module
// ('cancelled' -> warning is covered by its generic aliases).
export function aiVisibilityStatusTone(status: string): BadgeTone {
  return statusTone(status);
}

export function aiVisibilityStatusLabel(status: string): string {
  return dashboardStatusLabel(status);
}
