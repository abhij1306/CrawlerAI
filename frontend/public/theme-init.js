(() => {
  let dark = false;

  try {
    const storedTheme = localStorage.getItem('crawlerai-theme');
    if (storedTheme) {
      dark = storedTheme === 'dark';
    } else {
      dark = matchMedia('(prefers-color-scheme:dark)').matches;
    }
  } catch {
    dark = typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme:dark)').matches;
  }

  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
