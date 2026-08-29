import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';

import type { RunEvent } from '../../lib/api/types';
import { CRAWL_DEFAULTS } from '../../lib/constants/crawl-defaults';

export function useLiveRunEventAutoScroll({
  live,
  events,
  setLiveJumpAvailable,
  viewportRef,
}: {
  live: boolean;
  events: RunEvent[];
  setLiveJumpAvailable: (available: boolean) => void;
  viewportRef: RefObject<HTMLDivElement | null>;
}) {
  const bottomPinnedRef = useRef(true);

  useEffect(() => {
    const node = viewportRef.current;
    if (!node) return;
    const captureBottomPinned = () => {
      bottomPinnedRef.current =
        node.scrollHeight - node.scrollTop - node.clientHeight < CRAWL_DEFAULTS.SCROLL_THRESHOLD_PX;
    };
    captureBottomPinned();
    node.addEventListener('scroll', captureBottomPinned, { passive: true });
    return () => node.removeEventListener('scroll', captureBottomPinned);
  }, [viewportRef]);

  useEffect(() => {
    if (!live || !viewportRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const node = viewportRef.current;
      if (!node) return;
      if (bottomPinnedRef.current) {
        node.scrollTop = node.scrollHeight;
        bottomPinnedRef.current = true;
        setLiveJumpAvailable(false);
      } else {
        setLiveJumpAvailable(true);
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [events, live, setLiveJumpAvailable, viewportRef]);

  return bottomPinnedRef;
}
