import { describe, expect, it } from 'vitest';

import { getFocusableElements } from './focus-trap';

describe('getFocusableElements', () => {
  it('skips hidden layout nodes but keeps fixed-position elements', () => {
    const container = document.createElement('div');
    const visible = document.createElement('button');
    const hiddenByCss = document.createElement('button');
    const fixed = document.createElement('button');
    const ariaHidden = document.createElement('button');

    hiddenByCss.style.display = 'none';
    fixed.style.position = 'fixed';
    ariaHidden.setAttribute('aria-hidden', 'true');

    Object.defineProperty(visible, 'offsetParent', {
      configurable: true,
      get: () => container,
    });
    Object.defineProperty(hiddenByCss, 'offsetParent', {
      configurable: true,
      get: () => null,
    });
    Object.defineProperty(fixed, 'offsetParent', {
      configurable: true,
      get: () => null,
    });
    Object.defineProperty(ariaHidden, 'offsetParent', {
      configurable: true,
      get: () => container,
    });

    container.append(visible, hiddenByCss, fixed, ariaHidden);

    expect(getFocusableElements(container)).toEqual([visible, fixed]);
  });
});
