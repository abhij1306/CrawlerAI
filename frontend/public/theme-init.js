// Theme bootstrap — must stay an external classic script: production builds ship
// a CSP meta with script-src 'self' (see csp-meta plugin in vite.config.ts), and
// it has to run synchronously before first paint to avoid a theme flash.
(() => {
  let dark = false;
  try {
    const storedTheme = localStorage.getItem('crawlerai-theme');
    if (storedTheme) {
      dark = storedTheme === 'dark';
    } else {
      dark = window.matchMedia('(prefers-color-scheme:dark)').matches;
    }
  } catch {
    dark =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-color-scheme:dark)').matches;
  }
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
