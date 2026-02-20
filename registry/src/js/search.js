/*!
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

(function() {
  let pagefind = null;
  let currentFilter = 'all';
  let selectedIndex = 0;
  let currentResults = [];
  let searchId = 0;

  const typeLabels = {
    operator: 'Operator',
    hook: 'Hook',
    sensor: 'Sensor',
    trigger: 'Trigger',
    transfer: 'Transfer',
    bundle: 'Bundle',
    notifier: 'Notifier',
    secret: 'Secrets Backend',
    logging: 'Log Handler',
    executor: 'Executor',
    decorator: 'Decorator',
  };

  const modal = document.getElementById('search-modal');
  const input = document.getElementById('search-input');
  const resultsContainer = document.getElementById('search-results');
  const closeButton = document.getElementById('search-close');
  const filterTabs = document.querySelectorAll('#search-modal nav button');

  async function initPagefind() {
    if (pagefind === null) {
      const base = window.__REGISTRY_BASE__ || '/';
      pagefind = await import(base + 'pagefind/pagefind.js');
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

  function renderResults(results, resetSelection) {
    currentResults = results;
    if (resetSelection) {
      selectedIndex = 0;
    }

    if (results.length === 0) {
      resultsContainer.innerHTML = `
        <div class="search-empty">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p>No results found</p>
        </div>
      `;
      updateCountsFromResults([]);
      return;
    }

    const html = results.map((result, index) => {
      const type = result.meta.type || 'provider';
      const name = result.meta.className || result.meta.name || result.meta.title || 'Unknown';
      const providerName = result.meta.providerName || '';
      const description = result.meta.description || result.excerpt;
      const moduleType = result.meta.moduleType || '';
      const icon = type === 'provider' ? 'P' : (moduleType ? moduleType[0].toUpperCase() : 'M');
      const resultType = type === 'provider' ? 'provider' : moduleType;

      return `
        <a href="${result.url}" class="${resultType}${index === selectedIndex ? ' selected' : ''}" data-index="${index}">
          <span>${icon}</span>
          <div>
            <div>
              ${name}
              ${moduleType ? `<span class="badge ${moduleType}">${typeLabels[moduleType] || moduleType}</span>` : ''}
            </div>
            <div>
              ${providerName ? `<span><svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg> ${providerName}</span>` : ''}
              ${description ? `<span>${description}</span>` : ''}
            </div>
          </div>
          ${index === selectedIndex ? '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>' : ''}
        </a>
      `;
    }).join('');

    resultsContainer.innerHTML = html;
    updateCountsFromResults(results);

    const selected = resultsContainer.querySelector('a.selected');
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' });
    }
  }

  function updateCountsFromResults(results) {
    let providerCount = 0;
    let moduleCount = 0;

    results.forEach(result => {
      const type = result.meta.type || 'provider';
      if (type === 'provider') {
        providerCount++;
      } else {
        moduleCount++;
      }
    });

    document.getElementById('provider-count').textContent = providerCount;
    document.getElementById('module-count').textContent = moduleCount;
  }

  async function initializeCounts() {
    const pf = await initPagefind();
    const providerSearch = await pf.search('', { filters: { type: ['provider'] } });
    const moduleSearch = await pf.search('', { filters: { type: ['module'] } });
    document.getElementById('provider-count').textContent = providerSearch.results.length;
    document.getElementById('module-count').textContent = moduleSearch.results.length;
  }

  input.addEventListener('input', async (e) => {
    const query = e.target.value;
    const thisSearchId = ++searchId;

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

    if (search !== null && thisSearchId === searchId) {
      const results = await Promise.all(search.results.map(r => r.data()));

      if (thisSearchId === searchId) {
        renderResults(results, true);
      }
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
        renderResults(results, true);
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

    initializeCounts();
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
        closeModal();
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
