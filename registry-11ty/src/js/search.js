(function() {
  let pagefind = null;
  let currentFilter = 'all';
  let selectedIndex = 0;
  let currentResults = [];

  const modal = document.getElementById('search-modal');
  const input = document.getElementById('search-input');
  const resultsContainer = document.getElementById('search-results');
  const closeButton = document.getElementById('search-close');
  const filterTabs = document.querySelectorAll('#search-modal nav button');

  async function initPagefind() {
    if (pagefind === null) {
      pagefind = await import('/pagefind/pagefind.js');
    }
    return pagefind;
  }

  async function performSearch(query) {
    const pf = await initPagefind();

    if (!query.trim()) {
      return [];
    }

    let search;
    if (currentFilter !== 'all') {
      search = await pf.search(query, { filters: { type: [currentFilter] } });
    } else {
      search = await pf.search(query);
    }

    const results = await Promise.all(search.results.map(r => r.data()));

    return results;
  }

  function renderResults(results) {
    currentResults = results;
    selectedIndex = 0;

    if (results.length === 0) {
      resultsContainer.innerHTML = `
        <div class="search-empty">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p>No results found</p>
        </div>
      `;
      return;
    }

    const html = results.map((result, index) => {
      const type = result.meta.type || 'provider';
      const name = result.meta.className || result.meta.name || result.meta.title || 'Unknown';
      const providerName = result.meta.providerName || '';
      const description = result.meta.description || result.excerpt;
      const moduleType = result.meta.moduleType || '';
      const icon = type === 'provider' ? 'P' : (moduleType ? moduleType[0].toUpperCase() : 'M');

      return `
        <a href="${result.url}" class="result-item${index === selectedIndex ? ' selected' : ''}" data-index="${index}">
          <span class="result-icon ${type}">${icon}</span>
          <div class="result-content">
            <div class="result-title">${name}</div>
            <div class="result-meta">
              ${providerName ? `<span>${providerName}</span>` : ''}
              ${description ? `<span>${description}</span>` : ''}
            </div>
          </div>
          ${index === selectedIndex ? '<svg class="result-arrow" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>' : ''}
        </a>
      `;
    }).join('');

    resultsContainer.innerHTML = html;

    const selected = resultsContainer.querySelector('.result-item.selected');
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }

  async function updateCounts(query) {
    const pf = await initPagefind();

    if (!query.trim()) {
      const providerSearch = await pf.search('', { filters: { type: ['provider'] } });
      const moduleSearch = await pf.search('', { filters: { type: ['module'] } });
      document.getElementById('provider-count').textContent = providerSearch.results.length;
      document.getElementById('module-count').textContent = moduleSearch.results.length;
      return;
    }

    const providerSearch = await pf.search(query, { filters: { type: ['provider'] } });
    const moduleSearch = await pf.search(query, { filters: { type: ['module'] } });

    document.getElementById('provider-count').textContent = providerSearch.results.length;
    document.getElementById('module-count').textContent = moduleSearch.results.length;
  }

  input.addEventListener('input', async (e) => {
    const query = e.target.value;

    if (!query.trim()) {
      resultsContainer.innerHTML = `
        <div class="search-empty">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p>Start typing to search...</p>
        </div>
      `;
      currentResults = [];
      return;
    }

    const pf = await initPagefind();

    let search;
    if (currentFilter !== 'all') {
      search = await pf.debouncedSearch(query, { filters: { type: [currentFilter] } }, 150);
    } else {
      search = await pf.debouncedSearch(query, {}, 150);
    }

    // search will be null if a more recent search was initiated
    if (search !== null) {
      const results = await Promise.all(search.results.map(r => r.data()));
      renderResults(results);
      await updateCounts(query);
    }
  });

  filterTabs.forEach(tab => {
    tab.addEventListener('click', async () => {
      filterTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentFilter = tab.dataset.filter;

      const query = input.value;
      if (query.trim()) {
        const results = await performSearch(query);
        renderResults(results);
      }
    });
  });

  function openModal() {
    modal.classList.add('active');
    input.value = '';
    input.focus();
    currentResults = [];
    selectedIndex = 0;
    resultsContainer.innerHTML = `
      <div class="search-empty">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <p>Start typing to search...</p>
      </div>
    `;

    updateCounts('');
  }

  function closeModal() {
    modal.classList.remove('active');
    input.value = '';
    currentResults = [];
    selectedIndex = 0;
  }

  document.addEventListener('keydown', (e) => {
    if (!modal.classList.contains('active')) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      closeModal();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1);
      renderResults(currentResults);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      renderResults(currentResults);
    } else if (e.key === 'Enter' && currentResults.length > 0) {
      e.preventDefault();
      const selected = currentResults[selectedIndex];
      if (selected) {
        window.location.href = selected.url;
      }
    }
  });

  closeButton.addEventListener('click', closeModal);

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeModal();
    }
  });

  const searchTrigger = document.getElementById('search-trigger');
  const heroSearch = document.getElementById('hero-search');

  if (searchTrigger) {
    searchTrigger.addEventListener('click', openModal);
  }

  if (heroSearch) {
    heroSearch.addEventListener('click', openModal);
  }

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      openModal();
    }
  });
})();
