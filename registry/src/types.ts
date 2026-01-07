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

/**
 * Provider tier classification
 */
export type ProviderTier = 'official' | 'community';

/**
 * Module type classification
 */
export type ModuleType = 'operator' | 'hook' | 'sensor' | 'trigger' | 'transfer' | 'notifier' | 'secret' | 'logging' | 'executor' | 'decorator';

/**
 * Type icon mapping
 */
export const MODULE_TYPE_ICONS: Record<ModuleType, string> = {
  operator: 'O',
  hook: 'H',
  sensor: 'S',
  trigger: 'T',
  transfer: 'X',
  notifier: 'N',
  secret: 'K',  // Key
  logging: 'L',
  executor: 'E',
  decorator: '@',
};

/**
 * Provider metadata
 */
export interface Provider {
  id: string;
  name: string;
  packageName: string;
  description: string;
  tier: ProviderTier;
  logo?: string;

  // Version info
  version: string;
  versions: string[];

  // Compatibility badges
  airflowVersions: string[];

  // Quality metrics
  qualityScore: number;
  pypiDownloads: {
    weekly: number;
    monthly: number;
    total: number;
  };

  // Module counts by type
  moduleCounts: Record<ModuleType, number>;

  // Categories (e.g., S3, Lambda, EC2 for amazon)
  categories: Category[];

  // Connection types
  connectionTypes: { conn_type: string; hook_class: string; docs_url: string }[];

  // Python requirements
  requiresPython: string;  // e.g., ">=3.10"

  // Relationships
  dependencies: string[];  // Package dependencies from pyproject.toml
  optionalExtras: Record<string, string[]>;  // Optional extras: {extra_name: [deps]}
  dependents: string[];
  relatedProviders: string[];

  // Links
  docsUrl: string;
  sourceUrl: string;
  pypiUrl: string;

  // Metadata
  lastUpdated: string;
}

/**
 * Category within a provider
 */
export interface Category {
  id: string;
  name: string;
  moduleCount: number;
}

/**
 * Module (operator, hook, sensor, etc.)
 */
export interface Module {
  id: string;
  name: string;
  type: ModuleType;
  importPath: string;
  shortDescription: string;
  docsUrl: string;
  sourceUrl: string;
  category: string;
  providerId: string;
  providerName: string;
}

/**
 * Search result item
 */
export interface SearchResult {
  type: 'provider' | 'module';
  id: string;
  name: string;
  description: string;
  url: string;
  moduleType?: ModuleType;
  providerName?: string;
}

/**
 * Helper to format download counts
 */
export function formatDownloads(count: number): string {
  if (count >= 1_000_000_000) {
    return `${(count / 1_000_000_000).toFixed(1)}B`;
  }
  if (count >= 1_000_000) {
    return `${(count / 1_000_000).toFixed(1)}M`;
  }
  if (count >= 1_000) {
    return `${(count / 1_000).toFixed(1)}K`;
  }
  return count.toString();
}

/**
 * Get CSS class for module type badge
 */
export function getModuleTypeBadgeClass(type: ModuleType): string {
  return `badge-${type}`;
}

/**
 * Get CSS class for tier badge
 */
export function getTierBadgeClass(tier: ProviderTier): string {
  return `badge-${tier}`;
}
