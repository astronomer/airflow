// Theme Toggle
(function() {
  const themeToggle = document.getElementById('theme-toggle');
  const html = document.documentElement;
  const sunIcon = document.getElementById('theme-icon-sun');
  const moonIcon = document.getElementById('theme-icon-moon');

  // Get current theme from color-scheme property
  function getCurrentTheme() {
    return html.style.colorScheme || 'dark';
  }

  // Update icon visibility based on current theme
  function updateIcons() {
    const isLight = getCurrentTheme() === 'light';
    if (sunIcon) sunIcon.style.display = isLight ? 'block' : 'none';
    if (moonIcon) moonIcon.style.display = isLight ? 'none' : 'block';
  }

  // Initialize icons on load
  updateIcons();

  // Toggle theme
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const currentTheme = getCurrentTheme();
      const newTheme = currentTheme === 'light' ? 'dark' : 'light';

      html.style.colorScheme = newTheme;
      localStorage.setItem('theme', newTheme);
      updateIcons();
    });
  }
})();
