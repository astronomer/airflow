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

import { useState, useEffect, useCallback, useRef } from 'react';
import type { SearchResult } from '../types';
import { MODULE_TYPE_ICONS } from '../types';
import type { ModuleType } from '../types';

interface CommandPaletteProps {
  searchData: SearchResult[];
}

type FilterType = 'all' | 'provider' | 'module';

const typeColors: Record<string, string> = {
  operator: 'bg-green-500/20 text-green-400 border-green-500/30',
  hook: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  sensor: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  trigger: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  transfer: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  provider: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
};

// Improved search scoring function
function scoreResult(item: SearchResult, queryTerms: string[]): number {
  const name = item.name.toLowerCase();
  const className = ((item as any).className || '').toLowerCase();
  const description = (item.description || '').toLowerCase();
  const providerName = (item.providerName || '').toLowerCase();
  const importPath = ((item as any).importPath || '').toLowerCase();

  let score = 0;

  for (const term of queryTerms) {
    const termLower = term.toLowerCase();

    // Exact class name match - highest priority
    if (className === termLower) {
      score += 2000;
    }
    // Class name starts with term - very high priority
    else if (className.startsWith(termLower)) {
      score += 1000;
    }
    // Class name contains term
    else if (className.includes(termLower)) {
      score += 500;
    }
    // Exact name match
    else if (name === termLower) {
      score += 400;
    }
    // Name starts with term
    else if (name.startsWith(termLower)) {
      score += 300;
    }
    // Name contains term
    else if (name.includes(termLower)) {
      score += 200;
    }
    // Check import path
    else if (importPath.includes(termLower)) {
      score += 150;
    }
    // Provider name contains term
    else if (providerName.includes(termLower)) {
      score += 100;
    }
    // Description contains term
    else if (description.includes(termLower)) {
      score += 50;
    }
  }

  // Bonus for shorter names (more specific matches)
  if (score > 0) {
    score += Math.max(0, 50 - className.length);
  }

  return score;
}

export default function CommandPalette({ searchData }: CommandPaletteProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [filter, setFilter] = useState<FilterType>('all');
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Count results by type
  const counts = {
    providers: searchData.filter(item => item.type === 'provider').length,
    modules: searchData.filter(item => item.type === 'module').length,
  };

  // Filter and score results based on query
  const filteredResults = (() => {
    let results = searchData;

    // Apply type filter
    if (filter === 'provider') {
      results = results.filter(item => item.type === 'provider');
    } else if (filter === 'module') {
      results = results.filter(item => item.type === 'module');
    }

    if (!query.trim()) {
      // Show recent/popular when no query
      return results.slice(0, 15);
    }

    const queryTerms = query.trim().toLowerCase().split(/\s+/);

    // Score and filter results
    const scored = results
      .map(item => ({
        item,
        score: scoreResult(item, queryTerms),
      }))
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 25);

    return scored.map(({ item }) => item);
  })();

  // Count filtered results by type for filter badges
  const filteredCounts = (() => {
    if (!query.trim()) {
      return counts;
    }

    const queryTerms = query.trim().toLowerCase().split(/\s+/);
    const scored = searchData
      .map(item => ({ item, score: scoreResult(item, queryTerms) }))
      .filter(({ score }) => score > 0);

    return {
      providers: scored.filter(({ item }) => item.type === 'provider').length,
      modules: scored.filter(({ item }) => item.type === 'module').length,
    };
  })();

  // Open/close handlers
  const open = useCallback(() => {
    setIsOpen(true);
    setQuery('');
    setSelectedIndex(0);
    setFilter('all');
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    setQuery('');
    setSelectedIndex(0);
    setFilter('all');
  }, []);

  // Navigate to selected result
  const navigateTo = useCallback((result: SearchResult) => {
    // Use base path for navigation (set by Astro/Vite at build time)
    const basePath = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');
    if (result.type === 'provider') {
      window.location.href = `${basePath}/providers/${result.id}`;
    } else {
      // For modules, link to provider page with module highlighted
      const providerId = (result as any).providerId || result.providerName?.toLowerCase().replace(/\s+/g, '-');
      const className = (result as any).className || result.name;
      if (providerId) {
        // Navigate to provider page with module hash for highlighting
        window.location.href = `${basePath}/providers/${providerId}?highlight=${encodeURIComponent(className)}#${encodeURIComponent(className)}`;
      } else {
        window.open(result.url, '_blank');
      }
    }
    close();
  }, [close]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      switch (e.key) {
        case 'Escape':
          e.preventDefault();
          close();
          break;
        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex((prev) => Math.min(prev + 1, filteredResults.length - 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex((prev) => Math.max(prev - 1, 0));
          break;
        case 'Enter':
          e.preventDefault();
          if (filteredResults[selectedIndex]) {
            navigateTo(filteredResults[selectedIndex]);
          }
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, selectedIndex, filteredResults, close, navigateTo]);

  // Listen for custom open event
  useEffect(() => {
    const handleOpen = () => open();
    document.addEventListener('open-command-palette', handleOpen);
    return () => document.removeEventListener('open-command-palette', handleOpen);
  }, [open]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const selected = listRef.current.children[selectedIndex] as HTMLElement;
      if (selected) {
        selected.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex]);

  // Reset selection when query or filter changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query, filter]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-navy-900/80 backdrop-blur-sm"
        onClick={close}
      />

      {/* Palette */}
      <div className="relative w-full max-w-2xl bg-navy-800 border border-navy-600 rounded-xl shadow-2xl overflow-hidden animate-fade-in">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-4 border-b border-navy-700">
          <svg className="w-5 h-5 text-gray-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for operators, hooks, sensors, providers..."
            className="flex-1 bg-transparent text-gray-100 placeholder-gray-500 outline-none text-lg"
          />
          <button
            onClick={close}
            className="p-1 rounded-full hover:bg-navy-700 transition-colors"
          >
            <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-navy-700">
          <button
            onClick={() => setFilter('all')}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all ${
              filter === 'all'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-gray-400 hover:text-gray-300 hover:bg-navy-700'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setFilter('provider')}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all flex items-center gap-1.5 ${
              filter === 'provider'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-gray-400 hover:text-gray-300 hover:bg-navy-700'
            }`}
          >
            Providers
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${
              filter === 'provider' ? 'bg-cyan-500/30' : 'bg-navy-600'
            }`}>
              {filteredCounts.providers}
            </span>
          </button>
          <button
            onClick={() => setFilter('module')}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all flex items-center gap-1.5 ${
              filter === 'module'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-gray-400 hover:text-gray-300 hover:bg-navy-700'
            }`}
          >
            Modules
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${
              filter === 'module' ? 'bg-cyan-500/30' : 'bg-navy-600'
            }`}>
              {filteredCounts.modules}
            </span>
          </button>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-96 overflow-y-auto py-2">
          {filteredResults.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-500">
              <svg className="w-12 h-12 mx-auto mb-3 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <p className="text-lg">No results found for "{query}"</p>
              <p className="text-sm mt-1">Try searching for operator names, providers, or descriptions</p>
            </div>
          ) : (
            filteredResults.map((result, index) => {
              const isSelected = index === selectedIndex;
              const typeIcon = result.type === 'module' && result.moduleType
                ? MODULE_TYPE_ICONS[result.moduleType as ModuleType]
                : 'P';
              const typeClass = result.type === 'module' && result.moduleType
                ? typeColors[result.moduleType]
                : typeColors.provider;

              // Use className if available, otherwise generate from name
              const fullDisplayName = (result as any).className
                || (result.type === 'module' && result.moduleType
                  ? `${result.name.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join('')}${result.moduleType.charAt(0).toUpperCase()}${result.moduleType.slice(1)}`
                  : result.name.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(''));

              return (
                <button
                  key={`${result.type}-${result.id}-${index}`}
                  className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                    isSelected ? 'bg-cyan-500/10' : 'hover:bg-navy-700'
                  }`}
                  onClick={() => navigateTo(result)}
                  onMouseEnter={() => setSelectedIndex(index)}
                >
                  {/* Type icon */}
                  <span className={`w-8 h-8 flex items-center justify-center rounded text-sm font-bold border flex-shrink-0 ${typeClass}`}>
                    {typeIcon}
                  </span>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-100">{fullDisplayName}</span>
                      {result.type === 'module' && result.moduleType && (
                        <span className={`text-xs px-1.5 py-0.5 rounded border ${typeClass}`}>
                          {result.moduleType}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-sm text-gray-500 truncate">
                      {result.providerName && (
                        <span className="flex items-center gap-1">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                          </svg>
                          {result.providerName}
                        </span>
                      )}
                      {result.description && (
                        <span className="truncate">• {result.description}</span>
                      )}
                    </div>
                  </div>

                  {/* Arrow when selected */}
                  {isSelected && (
                    <svg className="w-4 h-4 text-cyan-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-3 border-t border-navy-700 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-navy-700 border border-navy-600 rounded">↑</kbd>
            <kbd className="px-1.5 py-0.5 bg-navy-700 border border-navy-600 rounded">↓</kbd>
            to navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-navy-700 border border-navy-600 rounded">↵</kbd>
            to select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1.5 py-0.5 bg-navy-700 border border-navy-600 rounded">esc</kbd>
            to close
          </span>
        </div>
      </div>
    </div>
  );
}
