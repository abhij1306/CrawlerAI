import { useCallback, useMemo } from 'react';
import type { Dispatch, SetStateAction } from 'react';

import type { CrawlRecord } from '../../lib/api/types';
import type { OutputTabKey } from './shared';

type UseRunRecordSelectionOptions = {
  outputTab: OutputTabKey;
  records: CrawlRecord[];
  tableRecords: CrawlRecord[];
  selectedIds: number[];
  setSelectedIds: Dispatch<SetStateAction<number[]>>;
};

export function useRunRecordSelection({
  outputTab,
  records,
  tableRecords,
  selectedIds,
  setSelectedIds,
}: Readonly<UseRunRecordSelectionOptions>) {
  const visibleColumns = useMemo(() => {
    const columns = new Set<string>();
    for (const record of [...tableRecords, ...records]) {
      for (const source of [record.data, record.raw_data]) {
        Object.keys(source ?? {}).forEach((key) => {
          const normalized = key.toLowerCase();
          if (
            !key.startsWith('_') &&
            normalized !== 'canonical_url' &&
            normalized !== 'source_run_id' &&
            normalized !== 'run_id' &&
            normalized !== 'product'
          ) {
            columns.add(key);
          }
        });
      }
    }
    const urlKeys = new Set(['url', 'source_url', 'product_url']);
    return Array.from(columns).sort((a, b) => {
      const aIsUrl = urlKeys.has(a.toLowerCase());
      const bIsUrl = urlKeys.has(b.toLowerCase());
      if (aIsUrl && !bIsUrl) return -1;
      if (!aIsUrl && bIsUrl) return 1;
      return 0;
    });
  }, [records, tableRecords]);

  const visibleRecords = outputTab === 'table' ? tableRecords : records;
  const visibleRecordIds = useMemo(
    () => new Set(visibleRecords.map((record) => record.id)),
    [visibleRecords],
  );
  const visibleSelectedIds = useMemo(
    () => selectedIds.filter((id) => visibleRecordIds.has(id)),
    [selectedIds, visibleRecordIds],
  );
  const selectedRecords = useMemo(
    () => visibleRecords.filter((record) => visibleSelectedIds.includes(record.id)),
    [visibleRecords, visibleSelectedIds],
  );
  const batchSourceRecords = tableRecords.length ? tableRecords : records;
  const selectAllVisibleTableRecords = useCallback(
    (checked: boolean) => {
      setSelectedIds(checked ? tableRecords.map((record) => record.id) : []);
    },
    [setSelectedIds, tableRecords],
  );
  const toggleSelectedRecord = useCallback(
    (id: number, checked: boolean) => {
      setSelectedIds((current) =>
        checked ? Array.from(new Set([...current, id])) : current.filter((value) => value !== id),
      );
    },
    [setSelectedIds],
  );

  return {
    visibleColumns,
    filteredTableRecords: tableRecords,
    visibleSelectedIds,
    selectedRecords,
    batchSourceRecords,
    selectAllVisibleTableRecords,
    toggleSelectedRecord,
  };
}
