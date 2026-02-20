<!--
 Licensed to the Apache Software Foundation (ASF) under one
 or more contributor license agreements.  See the NOTICE file
 distributed with this work for additional information
 regarding copyright ownership.  The ASF licenses this file
 to you under the Apache License, Version 2.0 (the
 "License"); you may not use this file except in compliance
 with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing,
 software distributed under the License is distributed on an
 "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 KIND, either express or implied.  See the License for the
 specific language governing permissions and limitations
 under the License.
 -->

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Draft: dev list email](#draft-dev-list-email)
  - [Why now](#why-now)
  - [How it relates to the Astronomer Registry](#how-it-relates-to-the-astronomer-registry)
  - [What it does](#what-it-does)
  - [Remaining work](#remaining-work)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Draft: dev list email

Subject: [DISCUSS] Apache Airflow Provider Registry: a searchable catalog of all providers and modules
To: dev@airflow.apache.org

---

Hey all,

tl;dr: I'm proposing an official Provider Registry for the Airflow project,
deployed at airflow.apache.org/registry/. Preview is up at TODO_STAGING_URL
-- take a look and let me know what you think.

PR: TODO_PR_URL

## Why now

With AIP-95 approved, Airflow now has a formal provider lifecycle --
incubation, production, mature, deprecated. That opens the door for
accepting more community-built providers and giving them an official home,
while setting clear expectations about maturity and support. But lifecycle
stages only work if users can actually see them. Right now there's no place
on airflow.apache.org where someone can browse providers, check their
lifecycle stage, or discover what modules they ship.

This registry fills that gap. It gives the PMC a tool to communicate
provider maturity to users, and it gives the community an official way
to surface new providers -- clearly labeled with their lifecycle stage.

## How it relates to the Astronomer Registry

Many of you know the Astronomer Registry (registry.astronomer.io), which
has been the go-to for discovering Airflow providers for years. Big thanks
to Astronomer and Josh Fell for building and maintaining it. This new
registry is designed to be a community-owned successor on
airflow.apache.org, with the eventual goal of redirecting
registry.astronomer.io traffic here once it's stable.

## What it does

The registry currently catalogs 99 providers and 1,648 modules across all
11 module types (operators, hooks, sensors, triggers, transfers, executors,
notifiers, secret backends, logging handlers, DAG bundles, and decorators).

It's built with Eleventy (thanks Ash for the suggestion and prototyping
an approach with it) and auto-generated directly from the
provider.yaml files in the repo -- no separate data pipeline, no manual
curation. When a provider is added or updated, the next CI build picks it
up automatically.

A few things you can do with it:

   - Search across all providers and modules (Cmd+K, powered by Pagefind)
   - Browse by category (Cloud, Databases, AI & ML, etc.)
   - Filter/sort by lifecycle stage, downloads, module count
   - Explore provider detail pages with per-version module listings,
     connection types, parameters, and install commands
   - Access JSON API endpoints (/api/providers.json, /api/modules.json)
     for programmatic access -- useful for AI agents and tooling

The design is deliberately discovery-first: it links out to the API
reference docs and user guides rather than hosting everything itself. This
avoids duplicating content between provider docs and registry entries.

CI/CD is integrated with our existing docs pipeline and syncs to S3
automatically. Nothing in provider code, provider.yaml schemas, core
Airflow, or the docs build is changed by this.

## Remaining work

Still to do after this lands:

   - apache/airflow-site PR for .htaccess rewrite and a "Registry" nav link
   - Redirect registry.astronomer.io traffic once the official one is stable

Future ideas (will create GH issues):

   - Explicit categories in provider.yaml (currently keyword-based matching)
   - LLM-friendly exports (llms.txt, "Copy for AI" buttons, etc.)
   - and many more – but I think the current state is valuable enough already

I'd appreciate feedback and reviews!

Regards,
Kaxil

---

*Draft -- adjust TODO_STAGING_URL and TODO_PR_URL before sending.*
