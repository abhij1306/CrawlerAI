export function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) {
    return [];
  }
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter(
    (element) =>
      !element.hidden &&
      element.getAttribute('aria-hidden') !== 'true' &&
      (element.offsetParent !== null || getComputedStyle(element).position === 'fixed'),
  );
}

export function trapFocus(event: KeyboardEvent, container: HTMLElement | null) {
  if (event.key !== 'Tab') {
    return;
  }
  const focusable = getFocusableElements(container);
  if (!focusable.length) {
    event.preventDefault();
    container?.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  if (event.shiftKey) {
    if (activeElement === first || !container?.contains(activeElement)) {
      event.preventDefault();
      last.focus();
    }
    return;
  }
  if (activeElement === last || !container?.contains(activeElement)) {
    event.preventDefault();
    first.focus();
  }
}
