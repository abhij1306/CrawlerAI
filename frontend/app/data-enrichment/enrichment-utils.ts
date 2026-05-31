const DEFAULT_CURRENCY_FORMATTER = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});
const CURRENCY_FORMATTERS = new Map<string, Intl.NumberFormat>([
  ['USD', DEFAULT_CURRENCY_FORMATTER],
]);

function currencyFormatter(currencyCode: string) {
  const formatter = CURRENCY_FORMATTERS.get(currencyCode);
  if (!formatter) {
    const created = new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currencyCode,
    });
    CURRENCY_FORMATTERS.set(currencyCode, created);
    return created;
  }
  return formatter;
}

export function formatPrice(price: unknown, currency: string): string {
  if (price === null || price === undefined) return '--';
  const stringifyStructuredPrice = (value: object) => {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  };
  const safeCurrency = (value: unknown) => {
    const normalized = String(value || '')
      .trim()
      .toUpperCase();
    return /^[A-Z]{3}$/.test(normalized) ? normalized : 'USD';
  };
  const formatAmount = (amount: number, currencyCode: unknown) => {
    const normalizedCurrency = safeCurrency(currencyCode);
    try {
      return currencyFormatter(normalizedCurrency).format(amount);
    } catch {
      return String(amount);
    }
  };
  if (typeof price === 'object') {
    if (Array.isArray(price)) {
      return stringifyStructuredPrice(price);
    }
    const p = price as Record<string, unknown>;
    const amount = p.amount ?? p.price_min;
    if (typeof amount === 'number') {
      return formatAmount(amount, p.currency || currency);
    }
    return stringifyStructuredPrice(p);
  }
  if (typeof price === 'number') {
    return formatAmount(price, currency);
  }
  return String(price);
}
