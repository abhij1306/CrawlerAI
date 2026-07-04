import { ApiError, isAbortError } from './errors';

function normalizeBaseUrl(value: string) {
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

function runtimeEnv(name: 'NODE_ENV' | 'VITE_API_BASE_URL') {
  if (name === 'NODE_ENV') return import.meta.env.MODE?.trim();
  return import.meta.env[name]?.trim();
}

function parseConfiguredApiBaseUrl(configured: string) {
  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    throw new Error(
      'VITE_API_BASE_URL must be a valid absolute URL (for example, http://127.0.0.1:8000).',
    );
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('VITE_API_BASE_URL must use http:// or https://.');
  }
  return normalizeBaseUrl(parsed.toString());
}

let resolvedBaseUrl: string | null = null;

export function getApiBaseUrl() {
  if (resolvedBaseUrl) return resolvedBaseUrl;
  const configured = runtimeEnv('VITE_API_BASE_URL');
  if (configured) {
    resolvedBaseUrl = parseConfiguredApiBaseUrl(configured);
    return resolvedBaseUrl;
  }
  if (runtimeEnv('NODE_ENV') === 'production') {
    throw new Error('VITE_API_BASE_URL must be set in production.');
  }
  if (typeof window !== 'undefined') {
    const { protocol, hostname } = window.location;
    resolvedBaseUrl = `${protocol}//${hostname}:8000`;
    return resolvedBaseUrl;
  }
  resolvedBaseUrl = 'http://127.0.0.1:8000';
  return resolvedBaseUrl;
}

export function getApiWebSocketBaseUrl() {
  return getApiBaseUrl().replace(/^http/, 'ws');
}

export type ApiRequestOptions = {
  signal?: AbortSignal;
  headers?: HeadersInit;
  requestId?: string;
  idempotencyKey?: string;
  retryNetworkFailures?: boolean;
};

type ResponseKind = 'json' | 'text' | 'blob';
type RequestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

type InternalRequestOptions = ApiRequestOptions & {
  method: RequestMethod;
  body?: BodyInit;
};

function createRequestId() {
  return (
    globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function buildHeaders(options: InternalRequestOptions, requestId: string) {
  const headers = new Headers(options.headers);
  if (options.method !== 'GET' || options.requestId) {
    headers.set('X-Request-ID', requestId);
  }
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return headers;
}

async function fetchResponse(path: string, options: InternalRequestOptions, requestId: string) {
  return fetch(`${getApiBaseUrl()}${path}`, {
    method: options.method,
    body: options.body,
    signal: options.signal,
    cache: 'no-store',
    credentials: 'include',
    headers: buildHeaders(options, requestId),
  });
}

function canRetryNetworkFailure(options: InternalRequestOptions) {
  return (
    Boolean(options.retryNetworkFailures) &&
    (options.method === 'GET' || Boolean(options.idempotencyKey))
  );
}

async function requestResponse(path: string, options: InternalRequestOptions) {
  const requestId = options.requestId ?? createRequestId();
  const maxAttempts = canRetryNetworkFailure(options) ? 2 : 1;
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetchResponse(path, options, requestId);
      if (response.ok) return { response, requestId };
      const body = await readErrorBody(response);
      throw new ApiError(
        body || response.statusText || 'Request failed',
        response.status,
        body,
        response.headers.get('x-request-id') ?? requestId,
      );
    } catch (error) {
      lastError = error;
      if (
        error instanceof ApiError ||
        isAbortError(error) ||
        attempt >= maxAttempts ||
        !canRetryNetworkFailure(options)
      ) {
        throw error;
      }
      await delay(150 * attempt, options.signal);
    }
  }

  throw lastError instanceof Error ? lastError : new Error('Failed to reach API.');
}

async function parseResponse<T>(response: Response, kind: ResponseKind): Promise<T> {
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T;
  }
  if (kind === 'text') return response.text() as Promise<T>;
  if (kind === 'blob') return response.blob() as Promise<T>;
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    const text = await response.text();
    if (!text.trim()) return undefined as T;
    throw new ApiError('Expected JSON response from API.', response.status, text);
  }
  return response.json() as Promise<T>;
}

async function request<T>(
  method: RequestMethod,
  path: string,
  kind: ResponseKind,
  body: unknown,
  options: ApiRequestOptions = {},
) {
  const encodedBody =
    body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body);
  const { response } = await requestResponse(path, { ...options, method, body: encodedBody });
  return parseResponse<T>(response, kind);
}

export const apiClient = {
  get: <T>(path: string, options?: ApiRequestOptions) =>
    request<T>('GET', path, 'json', undefined, options),
  getText: (path: string, options?: ApiRequestOptions) =>
    request<string>('GET', path, 'text', undefined, options),
  getBlob: (path: string, options?: ApiRequestOptions) =>
    request<Blob>('GET', path, 'blob', undefined, options),
  post: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>('POST', path, 'json', body, options),
  postForm: <T>(path: string, body: FormData, options?: ApiRequestOptions) =>
    request<T>('POST', path, 'json', body, options),
  put: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>('PUT', path, 'json', body, options),
  patch: <T>(path: string, body: unknown, options?: ApiRequestOptions) =>
    request<T>('PATCH', path, 'json', body, options),
  delete: <T>(path: string, options?: ApiRequestOptions) =>
    request<T>('DELETE', path, 'json', undefined, options),
};

async function readErrorBody(response: Response) {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    try {
      const payload = await response.json();
      if (payload && typeof payload === 'object') {
        const detail = (payload as Record<string, unknown>).detail;
        if (typeof detail === 'string') return detail;
      }
      return JSON.stringify(payload);
    } catch {
      return response.statusText;
    }
  }
  try {
    return (await response.text()).trim();
  } catch {
    return response.statusText;
  }
}

function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      },
      { once: true },
    );
  });
}

export { ApiError, httpErrorStatus } from './errors';
