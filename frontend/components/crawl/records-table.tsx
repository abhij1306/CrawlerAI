'use client';

import { memo, useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';

import type { CrawlRecord } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { formatCellDisplay, humanizeFieldName, stringifyCell } from '../../lib/crawl/format';
import { readRecordValue } from '../../lib/crawl/record-utils';
import { TableBody, TableCell, TableRow } from '../ui/table';
import { RecordThumbnail } from './record-thumbnail';

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

const SELECT_COLUMN_WIDTH = 40;
const IMAGE_COLUMN_WIDTH = 64;
const HEADER_HEIGHT = 38;

function getDataColumnWidth(col: string) {
  const colKey = col.toLowerCase();
  if (URL_KEYS.has(colKey)) return 320;
  if (TITLE_KEYS.has(colKey)) return 360;
  if (PRICE_KEYS.has(colKey)) return 128;
  if (colKey === 'brand') return 180;
  if (colKey === 'size') return 96;
  return 180;
}

function fixedColumnStyle(width: number, left?: number): CSSProperties {
  return {
    ...(left === undefined ? {} : { left }),
    width,
    minWidth: width,
    maxWidth: width,
  };
}

function headerCellStyle(width: number, left?: number): CSSProperties {
  return {
    ...fixedColumnStyle(width, left),
    position: 'sticky',
    top: 0,
    ...(left === undefined ? {} : { left }),
    zIndex: left === undefined ? 60 : 90,
    height: HEADER_HEIGHT,
    background: 'var(--bg-base)',
    color: 'var(--text-muted)',
    fontFamily: 'var(--table-header-font-family)',
    fontSize: 'var(--table-header-font-size)',
    fontWeight: 'var(--table-header-weight)',
    letterSpacing: 'var(--table-header-tracking)',
    textTransform: 'uppercase',
  };
}

function stickyBodyStyle(width: number, left: number): CSSProperties {
  return {
    ...fixedColumnStyle(width, left),
    position: 'sticky',
    zIndex: 20,
  };
}

function RecordCell({ col, record }: Readonly<{ col: string; record: CrawlRecord }>) {
  const colKey = col.toLowerCase();
  const raw = formatCellDisplay(readRecordValue(record, col));
  if (!raw || raw === '--') return <span className="text-muted/40 type-body">--</span>;

  if (TITLE_KEYS.has(colKey)) {
    return <span className="type-body block max-w-[320px] truncate font-medium">{raw}</span>;
  }
  if (PRICE_KEYS.has(colKey)) {
    return <span className="text-foreground type-body font-bold tabular-nums">{raw}</span>;
  }
  if (URL_KEYS.has(colKey)) {
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
  const imageCol = visibleColumns.find((col) => IMAGE_KEYS.has(col.toLowerCase()));
  const dataColumns = visibleColumns.filter((col) => !IMAGE_KEYS.has(col.toLowerCase()));
  const hasImageCol = !!imageCol;
  const totalCols = dataColumns.length + (hasImageCol ? 1 : 0) + 1;
  const pinnedDataLeft = SELECT_COLUMN_WIDTH + (hasImageCol ? IMAGE_COLUMN_WIDTH : 0);
  const totalTableWidth =
    SELECT_COLUMN_WIDTH +
    (hasImageCol ? IMAGE_COLUMN_WIDTH : 0) +
    dataColumns.reduce((sum, col) => sum + getDataColumnWidth(col), 0);

  const rowHeightPx = 44;
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
  const bodyScrollTop = Math.max(0, scrollTop - HEADER_HEIGHT);
  const bodyViewportHeight = Math.max(rowHeightPx, viewportHeight - HEADER_HEIGHT);
  const startIndex = Math.max(0, Math.floor(bodyScrollTop / rowHeightPx) - overscanRows);
  const visibleCount = Math.ceil(bodyViewportHeight / rowHeightPx) + overscanRows * 2;
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

  return (
    <div className="surface-muted max-h-[calc(100vh-272px)] overflow-hidden rounded-md border">
      <div
        ref={setContainerRef}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        className="scrollbar-stable relative max-h-[calc(100vh-276px)] w-full overflow-auto"
      >
        <div
          className="bg-background border-border sticky top-0 z-[100] flex border-b"
          style={{ minWidth: totalTableWidth, height: HEADER_HEIGHT }}
        >
          <div
            className="flex shrink-0 items-center px-5"
            style={headerCellStyle(SELECT_COLUMN_WIDTH, 0)}
          >
            <input
              type="checkbox"
              aria-label="Select all records"
              checked={selectedIds.length === records.length && records.length > 0}
              onChange={(event) => onSelectAll(event.target.checked)}
            />
          </div>
          {hasImageCol ? (
            <div
              className="flex shrink-0 items-center justify-center px-5"
              style={headerCellStyle(IMAGE_COLUMN_WIDTH, SELECT_COLUMN_WIDTH)}
            >
              IMG
            </div>
          ) : null}
          {dataColumns.map((col, idx) => {
            const colKey = col.toLowerCase();
            const isFirstData = idx === 0;
            return (
              <div
                key={col}
                className={cn(
                  'flex shrink-0 items-center px-5 whitespace-nowrap',
                  PRICE_KEYS.has(colKey) && 'justify-end text-right',
                )}
                style={headerCellStyle(
                  getDataColumnWidth(col),
                  isFirstData ? pinnedDataLeft : undefined,
                )}
              >
                {humanizeFieldName(col)}
              </div>
            );
          })}
        </div>
        <table
          className="compact-data-table commerce-table table-fixed caption-bottom"
          style={{ minWidth: totalTableWidth }}
        >
        <colgroup>
          <col style={{ width: SELECT_COLUMN_WIDTH }} />
          {hasImageCol ? <col style={{ width: IMAGE_COLUMN_WIDTH }} /> : null}
          {dataColumns.map((col) => (
            <col key={col} style={{ width: getDataColumnWidth(col) }} />
          ))}
        </colgroup>
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
                <TableCell
                  className="bg-background"
                  style={stickyBodyStyle(SELECT_COLUMN_WIDTH, 0)}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select record ${record.id}`}
                    checked={isSelected}
                    onChange={(event) => onToggleRow(record.id, event.target.checked)}
                  />
                </TableCell>
                {hasImageCol ? (
                  <TableCell
                    className="bg-background text-center"
                    style={stickyBodyStyle(IMAGE_COLUMN_WIDTH, SELECT_COLUMN_WIDTH)}
                  >
                    {imageSrc ? (
                      <RecordThumbnail src={imageSrc} />
                    ) : (
                      <span className="text-muted/40 type-body">--</span>
                    )}
                  </TableCell>
                ) : null}
                {dataColumns.map((col, idx) => {
                  const colKey = col.toLowerCase();
                  const isFirstData = idx === 0;
                  const width = getDataColumnWidth(col);
                  return (
                    <TableCell
                      key={col}
                      style={
                        isFirstData
                          ? stickyBodyStyle(width, pinnedDataLeft)
                          : fixedColumnStyle(width)
                      }
                      className={cn(
                        PRICE_KEYS.has(colKey) && 'text-right',
                        isFirstData && 'bg-background',
                      )}
                    >
                      <RecordCell col={col} record={record} />
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
        </table>
      </div>
    </div>
  );
});
