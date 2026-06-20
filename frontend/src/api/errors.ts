export class ApiError extends Error {
  readonly status: number;
  readonly body: string;
  readonly requestId?: string;

  constructor(message: string, status: number, body: string, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.requestId = requestId;
  }

  get isUnauthorized() {
    return this.status === 401;
  }

  get isRetryable() {
    return this.status === 408 || this.status === 429 || this.status >= 500;
  }
}

export function httpErrorStatus(error: unknown): number | undefined {
  if (error instanceof ApiError) return error.status;
  if (typeof error === 'object' && error !== null && 'status' in error) {
    const status = (error as { status: unknown }).status;
    return typeof status === 'number' && Number.isFinite(status) ? status : undefined;
  }
  return undefined;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === 'AbortError'
    : error instanceof Error && error.name === 'AbortError';
}
