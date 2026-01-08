// Install Widget
(function() {
  const installTabs = document.querySelectorAll('#install .tab');
  const installCommand = document.getElementById('install-command');

  const commands = {
    pip: 'pip install apache-airflow-providers-amazon',
    uv: 'uv pip install apache-airflow-providers-amazon',
    requirements: 'apache-airflow-providers-amazon',
  };

  if (installTabs.length > 0) {
    installTabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const tool = tab.dataset.tool || 'pip';

        // Update active tab styles
        installTabs.forEach(t => {
          t.classList.remove('active');
        });
        tab.classList.add('active');

        // Update command
        if (installCommand) {
          installCommand.textContent = commands[tool] || commands.pip;
        }
      });
    });
  }

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
