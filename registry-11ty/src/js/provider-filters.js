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

// Provider Filtering and Sorting - Progressive Enhancement
(function() {
  // Elements
  const searchInput = document.getElementById('provider-search');
  const tierButtons = document.querySelectorAll('.tier-btn');
  const sortSelect = document.getElementById('provider-sort');
  const providerGrid = document.getElementById('provider-grid');
  const emptyState = document.getElementById('empty-state');
  const providerItems = document.querySelectorAll('.provider-item');

  // Exit if elements don't exist (not on providers page)
  if (!searchInput || !providerGrid || !emptyState) return;

  // State
  let currentTier = 'all';
  let currentSearch = '';

  // Filter and count visible providers
  function filterProviders() {
    let visibleCount = 0;

    providerItems.forEach(item => {
      const tier = item.dataset.tier;
      const name = item.dataset.name || '';

      const matchesTier = currentTier === 'all' || tier === currentTier;
      const matchesSearch = name.includes(currentSearch.toLowerCase());

      if (matchesTier && matchesSearch) {
        item.style.display = 'block';
        visibleCount++;
      } else {
        item.style.display = 'none';
      }
    });

    // Toggle empty state
    if (visibleCount === 0) {
      emptyState.style.display = 'block';
      providerGrid.style.display = 'none';
    } else {
      emptyState.style.display = 'none';
      providerGrid.style.display = 'grid';
    }
  }

  // Search handler
  searchInput.addEventListener('input', (e) => {
    currentSearch = e.target.value.trim();
    filterProviders();
  });

  // Tier filter handler
  tierButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      // Update active state
      tierButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Update filter
      currentTier = btn.dataset.tier;
      filterProviders();
    });
  });

  // Sort handler
  if (sortSelect) {
    sortSelect.addEventListener('change', () => {
      const sortBy = sortSelect.value;
      const items = Array.from(providerItems);

      items.sort((a, b) => {
        switch (sortBy) {
          case 'downloads':
            return Number(b.dataset.downloads || 0) - Number(a.dataset.downloads || 0);
          case 'name':
            return (a.dataset.name || '').localeCompare(b.dataset.name || '');
          case 'updated':
            return (b.dataset.updated || '').localeCompare(a.dataset.updated || '');
          case 'score':
            return Number(b.dataset.score || 0) - Number(a.dataset.score || 0);
          default:
            return 0;
        }
      });

      // Re-append in sorted order
      items.forEach(item => providerGrid.appendChild(item));
    });
  }
})();
