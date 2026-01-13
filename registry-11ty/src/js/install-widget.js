// Search functionality
(function() {
  // Hero search button
  const heroSearch = document.getElementById('hero-search');
  if (heroSearch) {
    heroSearch.addEventListener('click', () => {
      // TODO: Implement command palette
      console.log('Search not yet implemented');
    });
  }

  // Header search button
  const searchTrigger = document.getElementById('search-trigger');
  if (searchTrigger) {
    searchTrigger.addEventListener('click', () => {
      // TODO: Implement command palette
      console.log('Search not yet implemented');
    });
  }

  // Keyboard shortcut (Cmd+K or Ctrl+K)
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      // TODO: Implement command palette
      console.log('Search not yet implemented');
    }
  });
})();

// Install tool preference persistence
(function() {
  const widget = document.querySelector('#install .widget');
  if (!widget) return;

  const radios = widget.querySelectorAll('input[type="radio"][name="install-tool"]');

  // Restore saved preference
  const savedTool = localStorage.getItem('installTool');
  if (savedTool) {
    const savedRadio = widget.querySelector(`input[value="${savedTool}"]`);
    if (savedRadio) {
      savedRadio.checked = true;
    }
  }

  // Save preference on change
  radios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (radio.checked) {
        localStorage.setItem('installTool', radio.value);
      }
    });
  });
})();
