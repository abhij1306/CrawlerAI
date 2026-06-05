import { api } from '../../lib/api';
import type { FieldRow, FieldRowMessageTone } from './shared';

export async function testCrawlFieldRow({
  row,
  targetUrl,
  setActiveId,
  setMessage,
}: Readonly<{
  row: FieldRow;
  targetUrl: string;
  setActiveId: (value: string | null) => void;
  setMessage: (rowId: string, tone: FieldRowMessageTone, message: string) => void;
}>) {
  const target = targetUrl.trim();
  if (!target) {
    setMessage(row.id, 'warning', 'Enter a target URL before testing selectors.');
    return;
  }
  if (!row.cssSelector.trim() && !row.xpath.trim() && !row.regex.trim()) {
    setMessage(row.id, 'warning', 'Add a CSS selector, XPath, or regex before testing.');
    return;
  }
  setActiveId(row.id);
  try {
    const response = await api.testSelector({
      url: target,
      css_selector: row.cssSelector.trim() || undefined,
      xpath: row.xpath.trim() || undefined,
      regex: row.regex.trim() || undefined,
    });
    const suffix = response.matched_value ? `: ${response.matched_value}` : '.';
    setMessage(
      row.id,
      response.count > 0 ? 'success' : 'warning',
      response.count > 0
        ? `Matched ${response.count} result${response.count === 1 ? '' : 's'}${suffix}`
        : 'No matches.',
    );
  } catch (error) {
    setMessage(row.id, 'danger', error instanceof Error ? error.message : 'Selector test failed.');
  } finally {
    setActiveId(null);
  }
}
