(() => {
  let dark = false;

  try {
    const storedTheme = localStorage.getItem('crawlerai-theme');
    dark =
      storedTheme === 'dark' ||
      (!storedTheme && matchMedia('(prefers-color-scheme:dark)').matches);
  } catch (error) {
    try {
      dark = matchMedia('(prefers-color-scheme:dark)').matches;
    } catch (_) {
      dark = false;
    }
  }

  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
