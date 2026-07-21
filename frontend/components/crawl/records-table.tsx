import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';

import type { CrawlRecord } from '../../lib/api/types';
import { cn } from '../../lib/utils';
import { formatCellDisplay, humanizeFieldName, stringifyCell } from '../../lib/crawl/format';
import { readRecordValue } from '../../lib/crawl/record-utils';
import { isLikelyThumbnailUrl, RecordThumbnail } from './record-thumbnail';
import { isSafeHttpUrl } from '../../lib/format/domain';

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

const SELECT_COLUMN_WIDTH = 48;
const IMAGE_COLUMN_WIDTH = 80;
// Virtualization constants — must match --table-header-height / --table-row-height
// in globals.css (CSS vars can't feed the windowing math; keep in sync manually).
export const HEADER_HEIGHT = 30;
export const ROW_HEIGHT = 38;

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
    ...(left === undefined ? {} : { left: `${left}px` }),
    width: `${width}px`,
    minWidth: `${width}px`,
    maxWidth: `${width}px`,
  };
}

function headerCellStyle(width: number, left?: number, isLast?: boolean): CSSProperties {
  return {
    ...fixedColumnStyle(width, left),
    position: 'sticky',
    top: 0,
    zIndex: left === undefined ? 60 : 90,
    height: HEADER_HEIGHT,
    background: 'var(--bg-base)',
    color: 'var(--text-muted)',
    fontFamily: 'var(--table-header-font-family)',
    fontSize: 'var(--table-header-font-size)',
    fontWeight: 'var(--table-header-weight)',
    letterSpacing: 'var(--table-header-tracking)',
    textTransform: 'uppercase',
    // React omits `undefined` style values, so this drops the fixed maxWidth.
    ...(isLast ? { maxWidth: undefined, flexGrow: 1, flexShrink: 1 } : {}),
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
  if (!raw || raw === '--')
    return (
      <span className="text-muted/40" style={{ fontSize: 'var(--table-font-size)' }}>
        --
      </span>
    );

  if (TITLE_KEYS.has(colKey)) {
    return (
      <span
        className="block max-w-[320px] truncate text-secondary"
        style={{ fontSize: 'var(--table-font-size)' }}
      >
        {raw}
      </span>
    );
  }
  if (PRICE_KEYS.has(colKey)) {
    return (
      <span
        className="font-mono font-semibold text-foreground tabular-nums"
        style={{ fontSize: 'var(--table-font-size)' }}
      >
        {raw}
      </span>
    );
  }
  if (URL_KEYS.has(colKey)) {
    if (isSafeHttpUrl(raw)) {
      return (
        <a
          href={raw}
          target="_blank"
          rel="noreferrer"
          className="link-accent block max-w-[200px] truncate transition-colors"
          style={{ fontSize: 'var(--table-font-size)' }}
          title={raw}
        >
          {raw}
        </a>
      );
    }
  }
  return (
    <span
      className="block max-w-[260px] truncate text-secondary"
      style={{ fontSize: 'var(--table-font-size)' }}
    >
      {raw}
    </span>
  );
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
  const pinnedDataLeft = SELECT_COLUMN_WIDTH + (hasImageCol ? IMAGE_COLUMN_WIDTH : 0);
  const gridTemplateColumns = [
    `${SELECT_COLUMN_WIDTH}px`,
    ...(hasImageCol ? [`${IMAGE_COLUMN_WIDTH}px`] : []),
    ...dataColumns.map((col, index) =>
      index === dataColumns.length - 1
        ? `minmax(${getDataColumnWidth(col)}px, 1fr)`
        : `${getDataColumnWidth(col)}px`,
    ),
  ].join(' ');
  const totalTableWidth =
    SELECT_COLUMN_WIDTH +
    (hasImageCol ? IMAGE_COLUMN_WIDTH : 0) +
    dataColumns.reduce((sum, col) => sum + getDataColumnWidth(col), 0);

  const rowHeightPx = ROW_HEIGHT;
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
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

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
    <div className="relative isolate z-0 max-h-[calc(100vh-272px)] overflow-hidden">
      <div
        ref={setContainerRef}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        className="scrollbar-stable relative max-h-[calc(100vh-276px)] w-full overflow-auto"
        role="table"
        aria-rowcount={records.length + 1}
        aria-colcount={1 + (hasImageCol ? 1 : 0) + dataColumns.length}
      >
        <div
          role="row"
          aria-rowindex={1}
          className="sticky top-0 z-[100] grid border-b border-border"
          style={{
            minWidth: totalTableWidth,
            height: HEADER_HEIGHT,
            gridTemplateColumns,
            background: 'var(--bg-base)',
          }}
        >
          <div
            role="columnheader"
            aria-colindex={1}
            className="flex shrink-0 items-center justify-center px-3"
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
              role="columnheader"
              aria-colindex={2}
              className="flex shrink-0 items-center justify-center px-2"
              style={headerCellStyle(IMAGE_COLUMN_WIDTH, SELECT_COLUMN_WIDTH)}
            >
              IMG
            </div>
          ) : null}
          {dataColumns.map((col, idx) => {
            const isFirstData = idx === 0;
            const isLastData = idx === dataColumns.length - 1;
            return (
              <div
                key={col}
                role="columnheader"
                aria-colindex={1 + (hasImageCol ? 1 : 0) + idx + 1}
                className="flex shrink-0 items-center px-5 whitespace-nowrap"
                style={headerCellStyle(
                  getDataColumnWidth(col),
                  isFirstData ? pinnedDataLeft : undefined,
                  isLastData,
                )}
              >
                {humanizeFieldName(col)}
              </div>
            );
          })}
        </div>
        <div
          className="bg-panel"
          style={{ minWidth: totalTableWidth, fontSize: 'var(--table-font-size)' }}
          role="rowgroup"
        >
          {topSpacerPx > 0 ? (
            <div aria-hidden className="pointer-events-none" style={{ height: topSpacerPx }} />
          ) : null}
          {windowedRecords.map((record, windowIndex) => {
            const isSelected = selectedSet.has(record.id);
            const imageSrc = imageCol ? stringifyCell(readRecordValue(record, imageCol)) : '';

            return (
              <div
                key={record.id}
                role="row"
                aria-rowindex={startIndex + windowIndex + 2}
                className={cn(
                  'group grid h-[var(--table-row-height)] border-b border-divider bg-panel transition-colors hover:bg-background',
                  isSelected && 'bg-accent/[0.04]',
                )}
                style={{ gridTemplateColumns }}
              >
                <div
                  role="cell"
                  aria-colindex={1}
                  className="flex items-center justify-center bg-panel px-0 text-center"
                  style={stickyBodyStyle(SELECT_COLUMN_WIDTH, 0)}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select record ${record.id}`}
                    checked={isSelected}
                    onChange={(event) => onToggleRow(record.id, event.target.checked)}
                  />
                </div>
                {hasImageCol ? (
                  <div
                    role="cell"
                    aria-colindex={2}
                    className="flex items-center justify-center bg-panel px-2 text-center"
                    style={stickyBodyStyle(IMAGE_COLUMN_WIDTH, SELECT_COLUMN_WIDTH)}
                  >
                    {imageSrc && isLikelyThumbnailUrl(imageSrc) ? (
                      <RecordThumbnail src={imageSrc} />
                    ) : (
                      <span className="type-body text-muted/40">--</span>
                    )}
                  </div>
                ) : null}
                {dataColumns.map((col, idx) => {
                  const colKey = col.toLowerCase();
                  const isFirstData = idx === 0;
                  const isLastData = idx === dataColumns.length - 1;
                  const width = getDataColumnWidth(col);
                  return (
                    <div
                      key={col}
                      role="cell"
                      aria-colindex={1 + (hasImageCol ? 1 : 0) + idx + 1}
                      style={
                        isFirstData
                          ? stickyBodyStyle(width, pinnedDataLeft)
                          : isLastData
                            ? { minWidth: width }
                            : fixedColumnStyle(width)
                      }
                      className={cn(
                        'flex items-center px-5 tabular-nums',
                        PRICE_KEYS.has(colKey) && 'text-right',
                        isFirstData && 'bg-panel',
                      )}
                    >
                      <RecordCell col={col} record={record} />
                    </div>
                  );
                })}
              </div>
            );
          })}
          {bottomSpacerPx > 0 ? (
            <div aria-hidden className="pointer-events-none" style={{ height: bottomSpacerPx }} />
          ) : null}
        </div>
      </div>
    </div>
  );
});
