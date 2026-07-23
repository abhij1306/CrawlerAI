import { getApiBaseUrl } from '@/api/client';

type TelemetryPayload = Record<string, unknown>;

const isBrowser = typeof window !== 'undefined';
const TELEMETRY_PATH = '/api/telemetry/events';

function safeString(value: unknown) {
  if (typeof value === 'string') {
    return value;
  }
  if (value == null) {
    return '';
  }
  return String(value);
}

function normalizeErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return safeString(error) || 'Unknown error';
}

export function trackEvent(name: string, payload: TelemetryPayload = {}) {
  if (!isBrowser) {
    return;
  }

  const event = {
    name,
    payload,
    ts: new Date().toISOString(),
    path: window.location.pathname,
  };

  if (import.meta.env.MODE !== 'production') {
    // Keep local and test runs noise-free but observable.
    console.debug('[telemetry:event]', event);
    return;
  }

  try {
    // Resolve against the API base: a relative URL posts to the SPA origin and
    // silently 404s in split-origin deploys. Resolution stays inside the try so
    // a missing VITE_API_BASE_URL can never break a user action.
    const endpoint = `${getApiBaseUrl()}${TELEMETRY_PATH}`;
    const body = JSON.stringify(event);
    if (typeof navigator !== 'undefined' && 'sendBeacon' in navigator) {
      const payloadBlob = new Blob([body], { type: 'application/json' });
      navigator.sendBeacon(endpoint, payloadBlob);
      return;
    }
    void fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    });
  } catch {
    // Telemetry must never block user actions.
  }
}

export function telemetryErrorPayload(error: unknown, extra: TelemetryPayload = {}) {
  return {
    ...extra,
    error_message: normalizeErrorMessage(error),
  };
}
