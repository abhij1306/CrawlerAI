import { describe, expect, it } from 'vite-plus/test';

import { toCsv } from './product-intelligence-export';

describe('toCsv formula-injection escaping', () => {
  it.each([
    '=HYPERLINK("https://evil.example","click")',
    '+1+2',
    '-10-5',
    '@SUM(A1:A9)',
    '\t=1+1',
    '\r=1+1',
  ])('neutralizes the formula prefix in %j', (value) => {
    const csv = toCsv([{ name: value }]);
    expect(csv.split('\n')[1]).toBe(`"'${value.replaceAll('"', '""')}"`);
  });

  it('leaves ordinary scalar values unchanged', () => {
    const csv = toCsv([{ name: 'Nike Sneakers', price: 99.5, in_stock: true, note: null }]);
    expect(csv.split('\n')).toEqual([
      'name,price,in_stock,note',
      '"Nike Sneakers","99.5","true",""',
    ]);
  });

  it('only treats formula characters at the start of a cell as dangerous', () => {
    const csv = toCsv([{ name: 'a=b+c-d@e' }]);
    expect(csv.split('\n')[1]).toBe('"a=b+c-d@e"');
  });

  it('keeps doubling embedded double quotes', () => {
    const csv = toCsv([{ name: 'say "hi"' }]);
    expect(csv.split('\n')[1]).toBe('"say ""hi"""');
  });

  it('prepends the quote prefix before escaping embedded quotes', () => {
    const csv = toCsv([{ name: '="x"' }]);
    expect(csv.split('\n')[1]).toBe(`"'=""x"""`);
  });

  it('serializes object values as JSON', () => {
    const csv = toCsv([{ meta: { a: 1 } }]);
    expect(csv.split('\n')[1]).toBe('"{""a"":1}"');
  });
});
