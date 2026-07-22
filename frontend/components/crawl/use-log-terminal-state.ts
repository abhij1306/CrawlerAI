import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';

import type { CrawlLog, CrawlRecord } from '../../lib/api/types';
import { parseApiDate } from '../../lib/crawl/format';
import { cleanRecordForDisplay } from '../../lib/crawl/record-utils';
import {
  buildLogSiteGroups,
  LOG_GROUP_WINDOW_SIZE,
  sanitizeLogMessage,
  siteDomId,
  windowLogGroups,
} from './log-terminal-utils';
import type { LogSiteGroup } from './log-terminal-utils';

const URL_TERMINAL_MESSAGE_PATTERN =
  /\b(processing failed|timed out|stopped after reaching max_records|(?:extracted|yielded)\s+0\s+records?|no (?:public )?records? extracted|rejected detail extraction)\b/i;
const AUTO_EXPAND_GROUP = Symbol('auto-expand-group');

function groupHasTerminalOutcome(group: LogSiteGroup) {
  return (
    !group.url ||
    group.records.length > 0 ||
    group.stageLogs.persistence.length > 0 ||
    group.hasError ||
    group.logs.some((log) => URL_TERMINAL_MESSAGE_PATTERN.test(sanitizeLogMessage(log.message)))
  );
}

function activeSiteGroupKeys(groups: LogSiteGroup[], live: boolean) {
  const activeKeys = new Set<string>();
  if (!live) {
    return activeKeys;
  }

  let latestSerialGroup: LogSiteGroup | null = null;
  for (const group of groups) {
    if (groupHasTerminalOutcome(group)) {
      continue;
    }
    if (group.key.startsWith('site:prefixed:')) {
      activeKeys.add(group.key);
    } else {
      latestSerialGroup = group;
    }
  }
  if (latestSerialGroup) {
    activeKeys.add(latestSerialGroup.key);
  }
  return activeKeys;
}

function serialGroupEndMsByKey(groups: LogSiteGroup[]) {
  const endMsByKey = new Map<string, number>();
  let nextStartMs: number | null = null;
  for (let index = groups.length - 1; index >= 0; index -= 1) {
    const group = groups[index];
    if (!group.url || group.key.startsWith('site:prefixed:')) {
      continue;
    }
    if (nextStartMs !== null) {
      endMsByKey.set(group.key, nextStartMs);
    }
    const createdAt = group.logs[0]?.created_at;
    const startMs = createdAt ? parseApiDate(createdAt).getTime() : Number.NaN;
    if (Number.isFinite(startMs)) {
      nextStartMs = startMs;
    }
  }
  return endMsByKey;
}

export function useLogTerminalState({
  logs,
  records,
  live,
  nowMs,
}: Readonly<{
  logs: CrawlLog[];
  records: CrawlRecord[];
  live: boolean;
  nowMs?: number;
}>) {
  const peekPanelRef = useRef<HTMLDivElement | null>(null);
  // Static mount-time fallback only; the workspace passes its shared live clock via nowMs.
  const [fallbackNowMs] = useState(() => Date.now());
  const effectiveNowMs = nowMs ?? fallbackNowMs;
  const [peekedGroupKey, setPeekedGroupKey] = useState<string | null>(null);
  const [peekedRecordIndex, setPeekedRecordIndex] = useState(0);
  const [expandedGroupPreference, setExpandedGroupPreference] = useState<
    string | null | typeof AUTO_EXPAND_GROUP
  >(AUTO_EXPAND_GROUP);
  const [triageCursor, setTriageCursor] = useState(0);

  const groups = useMemo(() => buildLogSiteGroups(logs, records), [logs, records]);
  const deferredGroups = useDeferredValue(groups);
  const [visibleGroupCount, setVisibleGroupCount] = useState(LOG_GROUP_WINDOW_SIZE);
  const { visible: visibleGroups, hiddenCount: hiddenGroupCount } = useMemo(
    () => windowLogGroups(deferredGroups, visibleGroupCount),
    [deferredGroups, visibleGroupCount],
  );
  const showEarlierGroups = () => {
    setVisibleGroupCount((current) => current + LOG_GROUP_WINDOW_SIZE);
  };
  // Absolute index of each group in the full list — stable identity for parity
  // and window math, unlike the window-relative render index.
  const groupIndexByKey = useMemo(() => {
    const values = new Map<string, number>();
    groups.forEach((group, index) => {
      values.set(group.key, index);
    });
    return values;
  }, [groups]);
  const siteOrdinalByKey = useMemo(() => {
    let ordinal = 0;
    const values = new Map<string, number>();
    for (const group of groups) {
      if (!group.url) {
        continue;
      }
      ordinal += 1;
      values.set(group.key, ordinal);
    }
    return values;
  }, [groups]);
  const issueGroups = useMemo(
    () => groups.filter((group) => group.hasError || group.hasWarning),
    [groups],
  );
  const activeGroupKeys = useMemo(() => activeSiteGroupKeys(groups, live), [groups, live]);
  const activeGroupKey = useMemo(
    () => [...groups].reverse().find((group) => activeGroupKeys.has(group.key))?.key ?? null,
    [activeGroupKeys, groups],
  );
  const inferredSerialEndMsByKey = useMemo(() => serialGroupEndMsByKey(groups), [groups]);
  const activePeekedGroupKey = useMemo(
    () => (groups.some((group) => group.key === peekedGroupKey) ? peekedGroupKey : null),
    [groups, peekedGroupKey],
  );
  const peekedGroup = useMemo(
    () => groups.find((group) => group.key === activePeekedGroupKey) ?? null,
    [activePeekedGroupKey, groups],
  );
  const expandedGroupKey = useMemo(() => {
    if (
      typeof expandedGroupPreference === 'string' &&
      groups.some((group) => group.key === expandedGroupPreference)
    ) {
      return expandedGroupPreference;
    }
    if (expandedGroupPreference === null) {
      return null;
    }
    if (activeGroupKey) {
      return activeGroupKey;
    }
    return issueGroups[0]?.key ?? null;
  }, [activeGroupKey, expandedGroupPreference, groups, issueGroups]);
  const safePeekedRecordIndex = peekedGroup
    ? Math.min(peekedRecordIndex, Math.max(peekedGroup.records.length - 1, 0))
    : 0;
  const peekedRecordJson =
    peekedGroup && peekedGroup.records[safePeekedRecordIndex]
      ? JSON.stringify(cleanRecordForDisplay(peekedGroup.records[safePeekedRecordIndex]), null, 2)
      : '';
  const safeTriageCursor = issueGroups.length ? Math.min(triageCursor, issueGroups.length - 1) : 0;

  useEffect(() => {
    if (!activePeekedGroupKey) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      const panel = peekPanelRef.current;
      if (panel && !panel.contains(event.target as Node)) {
        setPeekedGroupKey(null);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [activePeekedGroupKey]);

  const timelineTicks = useMemo(() => {
    if (!groups.length) {
      return [];
    }
    const start = parseApiDate(groups[0].logs[0]?.created_at ?? new Date().toISOString()).getTime();
    const lastGroup = groups.at(-1);
    const end = parseApiDate(
      lastGroup?.logs.at(-1)?.created_at ??
        groups[0].logs[0]?.created_at ??
        new Date().toISOString(),
    ).getTime();
    const range = Math.max(1, end - start);
    return groups.map((group) => {
      const createdAt = group.logs[0]?.created_at ?? new Date().toISOString();
      const percent = ((parseApiDate(createdAt).getTime() - start) / range) * 100;
      let tone = 'bg-white/15';
      if (group.hasError) {
        tone = 'bg-danger';
      } else if (group.hasWarning) {
        tone = 'bg-warning';
      } else if (group.recordCount > 0) {
        tone = 'bg-emerald-400';
      }
      return { key: group.key, percent, tone };
    });
  }, [groups]);

  const jumpToGroup = (groupKey: string) => {
    const scrollToGroup = () => {
      const element = document.getElementById(siteDomId(groupKey));
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        element.classList.add('log-entry-highlight');
        setTimeout(() => element.classList.remove('log-entry-highlight'), 2000);
      }
    };
    const groupIndex = groupIndexByKey.get(groupKey);
    const isWindowedOut =
      groupIndex !== undefined && groupIndex < groups.length - visibleGroupCount;
    if (isWindowedOut) {
      // Reveal the window containing the target, then scroll after it renders.
      setVisibleGroupCount(groups.length - groupIndex);
      window.requestAnimationFrame(scrollToGroup);
    } else {
      scrollToGroup();
    }
    setExpandedGroupPreference(groupKey);
  };

  const toggleGroup = (groupKey: string) => {
    if (groupKey !== activeGroupKey) {
      setExpandedGroupPreference((current) => (current === groupKey ? null : groupKey));
    }
  };

  const navigateTriage = (direction: 'next' | 'prev') => {
    if (!issueGroups.length) {
      return;
    }
    const delta = direction === 'next' ? 1 : -1;
    const nextIndex = (safeTriageCursor + delta + issueGroups.length) % issueGroups.length;
    setTriageCursor(nextIndex);
    jumpToGroup(issueGroups[nextIndex].key);
  };

  return {
    activeGroupKey,
    activeGroupKeys,
    activePeekedGroupKey,
    expandedGroupKey,
    groupIndexByKey,
    groups,
    hiddenGroupCount,
    inferredSerialEndMsByKey,
    issueGroups,
    jumpToGroup,
    navigateTriage,
    nowMs: effectiveNowMs,
    peekedGroup,
    peekedRecordJson,
    peekPanelRef,
    safePeekedRecordIndex,
    setPeekedGroupKey,
    setPeekedRecordIndex,
    showEarlierGroups,
    siteOrdinalByKey,
    timelineTicks,
    toggleGroup,
    visibleGroups,
  };
}
