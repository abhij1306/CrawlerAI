import { useState } from 'react';
const BROKEN_THUMBNAIL_STORAGE_KEY = 'crawlerai-broken-thumb-urls-v1';
const BROKEN_THUMBNAIL_HOSTS_KEY = 'crawlerai-broken-thumb-hosts-v1';
const BROKEN_THUMBNAIL_URLS = new Set<string>();
const BROKEN_THUMBNAIL_HOSTS = new Set<string>();

function loadBrokenThumbnailCache() {
  if (typeof window === 'undefined') return;
  try {
    const urls = window.sessionStorage.getItem(BROKEN_THUMBNAIL_STORAGE_KEY);
    if (urls) (JSON.parse(urls) as string[]).forEach((u) => BROKEN_THUMBNAIL_URLS.add(u));
    const hosts = window.sessionStorage.getItem(BROKEN_THUMBNAIL_HOSTS_KEY);
    if (hosts) (JSON.parse(hosts) as string[]).forEach((h) => BROKEN_THUMBNAIL_HOSTS.add(h));
  } catch {
    /* ignore */
  }
}
loadBrokenThumbnailCache();

function persistBrokenThumbnailCache() {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.setItem(
      BROKEN_THUMBNAIL_STORAGE_KEY,
      JSON.stringify(Array.from(BROKEN_THUMBNAIL_URLS).slice(-500)),
    );
    window.sessionStorage.setItem(
      BROKEN_THUMBNAIL_HOSTS_KEY,
      JSON.stringify(Array.from(BROKEN_THUMBNAIL_HOSTS)),
    );
  } catch {
    /* ignore */
  }
}

function thumbnailHost(src: string): string {
  try {
    return new URL(src).host;
  } catch {
    return '';
  }
}

const IMAGE_EXTENSION_PATTERN = /\.(?:avif|bmp|gif|jpe?g|png|svg|webp)(?:$|[?#])/i;
const IMAGE_FORMAT_PATTERN =
  /(?:^|[?&])(?:format|fm|auto)=([^&#]*\b(?:avif|gif|jpe?g|png|webp)\b[^&#]*)/i;
const IMAGE_HOST_PATTERN =
  /(?:^|[.-])(?:assets?|cdn|images?|img|media|photos?|pictures?|static)(?:[.-]|$)/i;
const IMAGE_PATH_PATTERN = /\/(?:assets?|cdn|images?|img|media|photos?|pictures?|static)\//i;

export function isLikelyThumbnailUrl(src: string) {
  try {
    const parsed = new URL(src);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false;
    const href = parsed.href;
    return (
      IMAGE_EXTENSION_PATTERN.test(href) ||
      IMAGE_FORMAT_PATTERN.test(parsed.search) ||
      IMAGE_HOST_PATTERN.test(parsed.hostname) ||
      IMAGE_PATH_PATTERN.test(parsed.pathname)
    );
  } catch {
    return false;
  }
}

export function RecordThumbnail({ src }: Readonly<{ src: string }>) {
  const host = thumbnailHost(src);
  const initiallyBroken =
    BROKEN_THUMBNAIL_URLS.has(src) || (host !== '' && BROKEN_THUMBNAIL_HOSTS.has(host));
  const [broken, setBroken] = useState(initiallyBroken);
  if (broken) {
    return <span className="text-base text-muted">--</span>;
  }
  return (
    <div className="relative mx-auto flex size-8 items-center justify-center overflow-hidden rounded-sm border border-border bg-gradient-to-br from-background-elevated/60 to-background-alt shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] transition-colors duration-180 group-hover:border-accent/38">
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className="absolute inset-0 h-full w-full object-contain"
        onError={() => {
          BROKEN_THUMBNAIL_URLS.add(src);
          if (host) BROKEN_THUMBNAIL_HOSTS.add(host);
          persistBrokenThumbnailCache();
          setBroken(true);
        }}
      />
    </div>
  );
}
