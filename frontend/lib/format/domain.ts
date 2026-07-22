// Fallback policy: preserve the original input when parsing fails.
export function getDomain(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export function getNormalizedDomain(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, '').toLowerCase();
  } catch {
    return url;
  }
}

export function isSafeHttpUrl(value: string) {
  try {
    const protocol = new URL(value).protocol;
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

const SPECIAL_USE_HOSTNAMES = new Set(['localhost', 'localhost.localdomain']);

const SPECIAL_USE_SUFFIXES = ['.example', '.invalid', '.local', '.localhost'];

export function isSpecialUseDomain(value: string) {
  const normalized = getNormalizedDomain(value).trim().toLowerCase();
  const host = normalized.startsWith('[')
    ? (() => {
        const closingIndex = normalized.indexOf(']');
        return closingIndex >= 0 ? normalized.slice(0, closingIndex + 1) : normalized;
      })()
    : normalized.replace(/:\d+$/, '');
  if (!host) {
    return true;
  }
  return (
    SPECIAL_USE_HOSTNAMES.has(host) || SPECIAL_USE_SUFFIXES.some((suffix) => host.endsWith(suffix))
  );
}

// Canonical surface label. Unknown surfaces fall back to a humanized form
// (`forum_thread_x` → `forum thread x`) rather than the raw key.
export function surfaceLabel(surface: string) {
  if (surface === 'ecommerce_listing') return 'Commerce Listing';
  if (surface === 'ecommerce_detail') return 'Commerce Detail';
  if (surface === 'job_listing') return 'Job Listing';
  if (surface === 'job_detail') return 'Job Detail';
  return surface.replace(/_/g, ' ');
}
