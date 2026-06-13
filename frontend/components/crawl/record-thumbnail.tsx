'use client';

import Image from '@/routing/image';
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

export function RecordThumbnail({ src }: Readonly<{ src: string }>) {
  const host = thumbnailHost(src);
  const initiallyBroken =
    BROKEN_THUMBNAIL_URLS.has(src) || (host !== '' && BROKEN_THUMBNAIL_HOSTS.has(host));
  const [broken, setBroken] = useState(initiallyBroken);
  if (broken) {
    return <span className="text-muted text-xs">--</span>;
  }
  return (
    <div className="relative w-[46px] h-[46px] overflow-hidden rounded-sm border border-border bg-gradient-to-br from-background-elevated/60 to-background-alt flex items-center justify-center shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)] transition-all duration-180 hover:-translate-y-px group-hover:border-accent/38">
      <Image
        src={src}
        alt=""
        fill
        sizes="64px"
        unoptimized
        referrerPolicy="no-referrer"
        className="w-full h-full object-contain"
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
