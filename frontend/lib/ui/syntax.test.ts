import { describe, expect, it } from 'vitest';

import { syntaxHighlightJson } from './syntax';

describe('syntaxHighlightJson', () => {
  it('renders escaped quotes inside string values without visible backslashes', () => {
    const html = syntaxHighlightJson('{"description":"meaning \\"Dragon Well\\" tea"}');

    expect(html).toContain('meaning &quot;Dragon Well&quot; tea');
    expect(html).not.toContain('\\&quot;Dragon Well\\&quot;');
  });
});
