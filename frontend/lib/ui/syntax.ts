import { createElement, type ReactNode } from 'react';

// Extra padding (in ch) added so wrapped JSON lines align cleanly past the key.
const WRAP_ALIGN_EXTRA = 4;
const tokenRegex =
  /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?|[\{\}\[\],])/g;

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function displayJsonStringToken(token: string): string {
  const hasColon = token.endsWith(':');
  const rawString = hasColon ? token.slice(0, -1) : token;
  try {
    return `"${JSON.parse(rawString)}"${hasColon ? ':' : ''}`;
  } catch {
    return token;
  }
}

export function syntaxHighlightJson(json: string) {
  if (!json) return '';
  tokenRegex.lastIndex = 0;

  // Walk the input with a tokenizer regex; escape both matched tokens and the
  // gaps between them so any unmatched character is rendered as text, not HTML.
  let highlighted = '';
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = tokenRegex.exec(json)) !== null) {
    if (m.index > lastIndex) {
      highlighted += escapeHtml(json.slice(lastIndex, m.index));
    }
    const match = m[0];
    const token = tokenClassAndText(match);
    highlighted += `<span class="${token.className}">${escapeHtml(token.text)}</span>`;
    lastIndex = m.index + match.length;
  }
  if (lastIndex < json.length) {
    highlighted += escapeHtml(json.slice(lastIndex));
  }

  return highlighted
    .split('\n')
    .map((line) => {
      const spaces = leadingWhitespaceLength(line);
      const indent = spaces + WRAP_ALIGN_EXTRA;
      return `<span style="display: block; padding-left: ${indent}ch; text-indent: -${indent}ch;">${line}</span>`;
    })
    .join('');
}

function leadingWhitespaceLength(value: string) {
  let index = 0;
  while (index < value.length && value[index].trim() === '') index += 1;
  return index;
}

function tokenClassAndText(match: string): { className: string; text: string } {
  if (/^[\{\}\[\],]$/.test(match)) {
    return { className: 'syntax-punct', text: match };
  }
  if (match.startsWith('"')) {
    return {
      className: /:$/.test(match) ? 'syntax-key' : 'syntax-string',
      text: displayJsonStringToken(match),
    };
  }
  if (match === 'true' || match === 'false') {
    return { className: 'syntax-boolean', text: match };
  }
  if (match === 'null') {
    return { className: 'syntax-null', text: match };
  }
  return { className: 'syntax-number', text: match };
}

function syntaxHighlightJsonLineNodes(line: string, lineIndex: number): ReactNode[] {
  const nodes: ReactNode[] = [];
  const lineTokenRegex = new RegExp(tokenRegex.source, 'g');
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let tokenIndex = 0;
  while ((match = lineTokenRegex.exec(line)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(line.slice(lastIndex, match.index));
    }
    const token = tokenClassAndText(match[0]);
    nodes.push(
      createElement(
        'span',
        { key: `${lineIndex}-${tokenIndex}`, className: token.className },
        token.text,
      ),
    );
    tokenIndex += 1;
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < line.length) {
    nodes.push(line.slice(lastIndex));
  }
  return nodes;
}

export function syntaxHighlightJsonNodes(json: string): ReactNode[] {
  if (!json) return [];
  return json.split('\n').map((line, index) => {
    const spaces = leadingWhitespaceLength(line);
    const indent = spaces + WRAP_ALIGN_EXTRA;
    return createElement(
      'span',
      {
        key: `${index}-${line}`,
        style: {
          display: 'block',
          paddingLeft: `${indent}ch`,
          textIndent: `-${indent}ch`,
        },
      },
      syntaxHighlightJsonLineNodes(line, index),
    );
  });
}
