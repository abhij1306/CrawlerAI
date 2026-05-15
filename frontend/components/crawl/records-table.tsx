'use client';

import { memo, useCallback, useEffect, useState } from 'react';

import type { CrawlRecord } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { formatCellDisplay, humanizeFieldName, stringifyCell } from '../../lib/crawl/format';
import { readRecordValue } from '../../lib/crawl/record-utils';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { RecordThumbnail } from './record-thumbnail';
export const RecordsTable = memo(function RecordsTable({
  records,
  visibleColumns,
  selectedIds,
  onSelectAll,
  onToggleRow,
}: Readonly<{
  records: CrawlRecord[];
  visibleColumns: string[];
  selectedIds: number[];
  onSelectAll: (checked: boolean) => void;
  onToggleRow: (id: number, checked: boolean) => void;
}>) {
  const IMAGE_KEYS = new Set(['image_url', 'image', 'thumbnail', 'img']);
  const TITLE_KEYS = new Set(['title', 'name', 'product_name', 'product title']);
  const PRICE_KEYS = new Set([
    'price',
    'sale_price',
    'offer_price',
    'current_price',
    'final_price',
    'our_price',
    'deal_price',
  ]);
  const URL_KEYS = new Set(['url', 'source_url', 'product_url', 'canonical_url']);

  const imageCol = visibleColumns.find((col) => IMAGE_KEYS.has(col));
  const dataColumns = visibleColumns.filter((col) => !IMAGE_KEYS.has(col));
  const hasImageCol = !!imageCol;
  const totalCols = dataColumns.length + (hasImageCol ? 1 : 0) + 1;

  const rowHeightPx = 48;
  const overscanRows = 8;
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(560);
  const [containerNode, setContainerNode] = useState<HTMLDivElement | null>(null);
  const setContainerRef = useCallback((node: HTMLDivElement | null) => {
    setContainerNode(node);
    if (node) {
      setViewportHeight(node.clientHeight || 560);
    }
  }, []);
  const totalCount = records.length;
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeightPx) - overscanRows);
  const visibleCount = Math.ceil(viewportHeight / rowHeightPx) + overscanRows * 2;
  const endIndex = Math.min(totalCount, startIndex + visibleCount);
  const windowedRecords = records.slice(startIndex, endIndex);
  const topSpacerPx = startIndex * rowHeightPx;
  const bottomSpacerPx = Math.max(0, (totalCount - endIndex) * rowHeightPx);

  useEffect(() => {
    if (!containerNode || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      setViewportHeight(entry.contentRect.height || 560);
    });
    observer.observe(containerNode);
    return () => observer.disconnect();
  }, [containerNode]);

  function renderCell(col: string, record: CrawlRecord) {
    const raw = formatCellDisplay(readRecordValue(record, col));
    if (!raw || raw === '--') return <span className="text-muted/40 type-body">--</span>;

    if (TITLE_KEYS.has(col)) {
      return <span className="type-body block max-w-[320px] truncate font-medium">{raw}</span>;
    }
    if (PRICE_KEYS.has(col)) {
      return <span className="text-foreground type-body font-bold tabular-nums">{raw}</span>;
    }
    if (URL_KEYS.has(col)) {
      const isSafe = raw.startsWith('http://') || raw.startsWith('https://');
      if (isSafe) {
        return (
          <a
            href={raw}
            target="_blank"
            rel="noreferrer"
            className="link-accent block max-w-[200px] truncate text-sm transition-colors"
            title={raw}
          >
            {raw}
          </a>
        );
      }
    }
    return <span className="text-secondary block max-w-[260px] truncate text-sm">{raw}</span>;
  }

  return (
    <div className="surface-muted max-h-[calc(100vh-272px)] overflow-hidden rounded-[var(--radius-md)] border">
      <Table
        className="compact-data-table min-w-max"
        wrapperClassName="max-h-[calc(100vh-276px)] scrollbar-stable"
        wrapperRef={setContainerRef}
        onWrapperScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      >
        <TableHeader className="bg-background sticky top-0 z-40">
          <TableRow>
            <TableHead className="bg-background sticky left-0 z-50 w-10">
              <input
                type="checkbox"
                checked={selectedIds.length === records.length && records.length > 0}
                onChange={(event) => onSelectAll(event.target.checked)}
              />
            </TableHead>
            {hasImageCol ? (
              <TableHead className="bg-background sticky left-10 z-50 w-16 text-center">
                IMG
              </TableHead>
            ) : null}
            {dataColumns.map((col, idx) => {
              const isFirstData = idx === 0;
              const isUrl = URL_KEYS.has(col.toLowerCase());
              const leftOffset = isFirstData ? (hasImageCol ? 104 : 40) : undefined;
              return (
                <TableHead
                  key={col}
                  style={
                    leftOffset !== undefined
                      ? { left: leftOffset, width: isUrl ? 280 : 180 }
                      : undefined
                  }
                  className={cn(
                    'bg-background whitespace-nowrap',
                    PRICE_KEYS.has(col) && 'text-right',
                    isFirstData && 'sticky z-50',
                    isUrl && 'min-w-[280px]',
                  )}
                >
                  {humanizeFieldName(col)}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {topSpacerPx > 0 ? (
            <TableRow aria-hidden className="pointer-events-none hover:bg-transparent">
              <TableCell colSpan={totalCols} style={{ height: topSpacerPx, padding: 0 }} />
            </TableRow>
          ) : null}
          {windowedRecords.map((record) => {
            const isSelected = selectedIds.includes(record.id);
            const imageSrc = imageCol ? stringifyCell(readRecordValue(record, imageCol)) : '';

            return (
              <TableRow key={record.id} className={cn(isSelected && 'bg-accent/[0.04]')}>
                <TableCell className="bg-background sticky left-0 z-30">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(event) => onToggleRow(record.id, event.target.checked)}
                  />
                </TableCell>
                {hasImageCol ? (
                  <TableCell className="bg-background sticky left-10 z-30 text-center">
                    {imageSrc ? (
                      <RecordThumbnail src={imageSrc} />
                    ) : (
                      <span className="text-muted/40 type-body">--</span>
                    )}
                  </TableCell>
                ) : null}
                {dataColumns.map((col, idx) => {
                  const isFirstData = idx === 0;
                  const isUrl = URL_KEYS.has(col.toLowerCase());
                  const leftOffset = isFirstData ? (hasImageCol ? 104 : 40) : undefined;
                  return (
                    <TableCell
                      key={col}
                      style={
                        leftOffset !== undefined
                          ? { left: leftOffset, width: isUrl ? 280 : 180 }
                          : undefined
                      }
                      className={cn(
                        PRICE_KEYS.has(col) && 'text-right',
                        isFirstData && 'bg-background sticky z-30',
                        isUrl && 'min-w-[280px]',
                      )}
                    >
                      {renderCell(col, record)}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
          {bottomSpacerPx > 0 ? (
            <TableRow aria-hidden className="pointer-events-none hover:bg-transparent">
              <TableCell colSpan={totalCols} style={{ height: bottomSpacerPx, padding: 0 }} />
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
    </div>
  );
});
