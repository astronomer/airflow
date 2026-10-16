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

<!-- START Apache Airflow, please keep comment here to allow auto update of PyPI readme.md -->
# Apache Airflow

| Category   | Badges                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
|------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| License    | [![License](https://img.shields.io/:license-Apache%202-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0.txt)                                                                                                                                                                                                                                                                                                                                                                                                                   |
| PyPI       | [![PyPI version](https://badge.fury.io/py/apache-airflow.svg)](https://badge.fury.io/py/apache-airflow) [![PyPI - Python Version](https://img.shields.io/pypi/pyversions/apache-airflow.svg)](https://pypi.org/project/apache-airflow/) [![PyPI - Downloads](https://img.shields.io/pypi/dm/apache-airflow)](https://pypi.org/project/apache-airflow/)                                                                                                                                                                               |
| Containers | [![Docker Pulls](https://img.shields.io/docker/pulls/apache/airflow.svg)](https://hub.docker.com/r/apache/airflow) [![Docker Stars](https://img.shields.io/docker/stars/apache/airflow.svg)](https://hub.docker.com/r/apache/airflow) [![Artifact HUB](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/apache-airflow)](https://artifacthub.io/packages/search?repo=apache-airflow)                                                                                                                      |
| Community  | [![Contributors](https://img.shields.io/github/contributors/apache/airflow)](https://github.com/apache/airflow/graphs/contributors) [![Slack Status](https://img.shields.io/badge/slack-join_chat-white.svg?logo=slack&style=social)](https://s.apache.org/airflow-slack) ![Commit Activity](https://img.shields.io/github/commit-activity/m/apache/airflow) [![LFX Health Score](https://insights.linuxfoundation.org/api/badge/health-score?project=apache-airflow)](https://insights.linuxfoundation.org/project/apache-airflow)  |
| Dev tools  | [![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)                                                                                                                                                                                                                                                                                                                                                                            |

| Version | Build Status                                                                                                                                                    |
|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Main    | [![Tests AMD main](https://github.com/apache/airflow/actions/workflows/ci-amd.yml/badge.svg)](https://github.com/apache/airflow/actions/workflows/ci-amd.yml) [![Tests ARM main](https://github.com/apache/airflow/actions/workflows/ci-arm.yml/badge.svg)](https://github.com/apache/airflow/actions/workflows/ci-arm.yml) |
| 3.x     | [![Tests AMD 3.2](https://github.com/apache/airflow/actions/workflows/ci-amd.yml/badge.svg?branch=v3-2-test)](https://github.com/apache/airflow/actions/workflows/ci-amd.yml) [![Tests ARM 3.2](https://github.com/apache/airflow/actions/workflows/ci-arm.yml/badge.svg?branch=v3-2-test)](https://github.com/apache/airflow/actions/workflows/ci-arm.yml) |



<picture width="500">
  <img
    src="https://github.com/apache/airflow/blob/19ebcac2395ef9a6b6ded3a2faa29dc960c1e635/docs/apache-airflow/img/logos/wordmark_1.png?raw=true"
    alt="Apache Airflow logo"
  />
</picture>

[Apache Airflow](https://airflow.apache.org/docs/apache-airflow/stable/) (or simply Airflow) is a platform to programmatically author, schedule, and monitor workflows.

When workflows are defined as code, they become more maintainable, versionable, testable, and collaborative.

Use Airflow to author workflows (Dags) that orchestrate tasks. The Airflow scheduler executes your tasks on an array of workers while following the specified dependencies. Rich command line utilities make performing complex surgeries on Dags a snap. The rich user interface makes it easy to visualize pipelines running in production, monitor progress, and troubleshoot issues when needed.

<!-- END Apache Airflow, please keep comment here to allow auto update of PyPI readme.md -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of contents**

- [Project Focus](#project-focus)
- [Principles](#principles)
- [Requirements](#requirements)
- [Getting started](#getting-started)
- [Installing from PyPI](#installing-from-pypi)
- [Installation](#installation)
- [Official source code](#official-source-code)
- [Convenience packages](#convenience-packages)
- [User Interface](#user-interface)
- [Semantic versioning](#semantic-versioning)
- [Version Life Cycle](#version-life-cycle)
- [Support for Python and Kubernetes versions](#support-for-python-and-kubernetes-versions)
- [Base OS support for reference Airflow images](#base-os-support-for-reference-airflow-images)
- [Approach to dependencies of Airflow](#approach-to-dependencies-of-airflow)
- [Contributing](#contributing)
- [Community standards](#community-standards)
- [Agent-assisted contribution (apache-magpie)](#agent-assisted-contribution-apache-magpie)
- [Voting Policy](#voting-policy)
- [Who uses Apache Airflow?](#who-uses-apache-airflow)
- [Who maintains Apache Airflow?](#who-maintains-apache-airflow)
- [What goes into the next release?](#what-goes-into-the-next-release)
- [Can I use the Apache Airflow logo in my presentation?](#can-i-use-the-apache-airflow-logo-in-my-presentation)
- [Links](#links)
- [Sponsors](#sponsors)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Project Focus

Airflow works best with workflows that are mostly static and slowly changing. When the Dag structure is similar from one run to the next, it clarifies the unit of work and continuity. Other similar projects include [Luigi](https://github.com/spotify/luigi), [Oozie](https://oozie.apache.org/) and [Azkaban](https://azkaban.github.io/).

Beyond traditional data pipelines, Airflow is widely used to orchestrate machine learning workflows — training, retraining, evaluation, and deployment — and increasingly to orchestrate agentic and LLM-based workloads, coordinating the steps of an AI pipeline (data prep, tool calls, model invocation, evaluation) rather than acting as the agent itself. This isn't a new direction: teams have run ML and AI workloads on Airflow for years, and the ecosystem of providers supporting these use cases (see the [AI & ML section of the Airflow registry](https://airflow.apache.org/registry/providers/?category=ai-ml)) continues to grow.

Airflow is commonly used to process data, but has the opinion that tasks should ideally be idempotent (i.e., results of the task will be the same, and will not create duplicated data in a destination system), and should not pass large quantities of data from one task to the next (though tasks can pass metadata using Airflow's [XCom feature](https://airflow.apache.org/docs/apache-airflow/stable/concepts/xcoms.html)). For high-volume, data-intensive tasks, a best practice is to delegate to external services specializing in that type of work.

Airflow is not a streaming solution, but it is often used to process real-time data, pulling data off streams in batches.

## Principles

- **Dynamic**: Pipelines are defined in code, enabling dynamic dag generation and parameterization.
- **Extensible**: The Airflow framework includes a wide range of built-in operators and can be extended to fit your needs.
- **Flexible**: Airflow leverages the [**Jinja**](https://jinja.palletsprojects.com) templating engine, allowing rich customizations.

<!-- START Requirements, please keep comment here to allow auto update of PyPI readme.md -->
## Requirements

Apache Airflow is tested with:

|            | Main version (dev)                       | Stable version (3.3.2)             | Deprecate version (2.11.2)   |
|------------|------------------------------------------|------------------------------------|------------------------------|
| Python     | 3.11, 3.12, 3.13, 3.14                   | 3.10, 3.11, 3.12, 3.13, 3.14       | 3.10, 3.11, 3.12             |
| Platform   | AMD64/ARM64                              | AMD64/ARM64                        | AMD64/ARM64(\*)              |
| Kubernetes | 1.31, 1.32, 1.33, 1.34, 1.35, 1.36, 1.37 | 1.30, 1.31, 1.32, 1.33, 1.34, 1.35 | 1.26, 1.27, 1.28, 1.29, 1.30 |
| PostgreSQL | 14, 15, 16, 17, 18                       | 14, 15, 16, 17, 18                 | 12, 13, 14, 15, 16           |
| MySQL      | 8.0, 8.4, Innovation                     | 8.0, 8.4, Innovation               | 8.0, Innovation              |
| SQLite     | 3.15.0+                                  | 3.15.0+                            | 3.15.0+                      |

\* Experimental

**Note**: MariaDB is not tested/recommended.

**Note**: SQLite is used in Airflow tests. Do not use it in production. We recommend
using the latest stable version of SQLite for local development.

**Note**: Airflow currently can be run on POSIX-compliant Operating Systems. For development, it is regularly
tested on fairly modern Linux Distros and recent versions of macOS.
On Windows you can run it via WSL2 (Windows Subsystem for Linux 2) or via Linux Containers.
The work to add Windows support is tracked via [#10388](https://github.com/apache/airflow/issues/10388), but
it is not a high priority. You should only use Linux-based distros as "Production" execution environment
as this is the only environment that is supported. The only distro that is used in our CI tests and that
is used in the [Community managed DockerHub image](https://hub.docker.com/p/apache/airflow) is
`Debian Bookworm`.

<!-- END Requirements, please keep comment here to allow auto update of PyPI readme.md -->
<!-- START Getting started, please keep comment here to allow auto update of PyPI readme.md -->
## Getting started

Visit the official Airflow website documentation (latest **stable** release) for help with
[installing Airflow](https://airflow.apache.org/docs/apache-airflow/stable/installation/),
[getting started](https://airflow.apache.org/docs/apache-airflow/stable/start.html), or walking
through a more complete [tutorial](https://airflow.apache.org/docs/apache-airflow/stable/tutorial/).

> Note: If you're looking for documentation for the main branch (latest development branch): you can find it on [s.apache.org/airflow-docs](https://s.apache.org/airflow-docs/).

For more information on Airflow Improvement Proposals (AIPs), visit
the [Airflow Wiki](https://cwiki.apache.org/confluence/display/AIRFLOW/Airflow+Improvement+Proposals).

Documentation for dependent projects like provider distributions, Docker image, Helm Chart, you'll find it in [the documentation index](https://airflow.apache.org/docs/).

<!-- END Getting started, please keep comment here to allow auto update of PyPI readme.md -->
<!-- START Installing from PyPI, please keep comment here to allow auto update of PyPI readme.md -->

## Installing from PyPI

We publish Apache Airflow as `apache-airflow` package in PyPI. Installing it however might be sometimes tricky
because Airflow is a bit of both a library and application. Libraries usually keep their dependencies open, and
applications usually pin them, but we should do neither and both simultaneously. We decided to keep
our dependencies as open as possible (in `pyproject.toml`) so users can install different versions of libraries
if needed. This means that `pip install apache-airflow` will not work from time to time or will
produce unusable Airflow installation.

To have repeatable installation, however, we keep a set of "known-to-be-working" constraint
files in the orphan `constraints-main` and `constraints-2-0` branches. We keep those "known-to-be-working"
constraints files separately per major/minor Python version.
You can use them as constraint files when installing Airflow from PyPI. Note that you have to specify
correct Airflow tag/version/branch and Python versions in the URL.

1. Installing just Airflow:

> Note: Only `pip` and `uv` installation is currently officially supported.

While it is possible to install Airflow with tools like [Poetry](https://python-poetry.org) or
[pip-tools](https://pypi.org/project/pip-tools), they do not share the same workflow as
`pip` - especially when it comes to constraint vs. requirements management.
Installing via `Poetry` or `pip-tools` is not currently supported.

If you wish to install Airflow using those tools, you should use the constraint files and convert
them to the appropriate format and workflow that your tool requires.


```bash
pip install 'apache-airflow==3.3.2' \
 --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.10.txt"
```

2. Installing with extras (i.e., postgres, google)

```bash
pip install 'apache-airflow[postgres,google]==3.3.2' \
 --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.10.txt"
```

For information on installing provider distributions, check
[providers](https://airflow.apache.org/docs/apache-airflow-providers/index.html).

<!-- END Installing from PyPI, please keep comment here to allow auto update of PyPI readme.md -->

## Installation

For comprehensive instructions on setting up your local development environment and installing Apache Airflow, please refer to the [INSTALLING.md](INSTALLING.md) file.

<!-- START Official source code, please keep comment here to allow auto update of PyPI readme.md -->
## Official source code

Apache Airflow is an [Apache Software Foundation](https://www.apache.org) (ASF) project,
and our official source code releases:

- Follow the [ASF Release Policy](https://www.apache.org/legal/release-policy.html)
- Can be downloaded from [the ASF Distribution Directory](https://downloads.apache.org/airflow)
- Are cryptographically signed by the release manager
- Are officially voted on by the PMC members during the
  [Release Approval Process](https://www.apache.org/legal/release-policy.html#release-approval)

Following the ASF rules, the source packages released must be sufficient for a user to build and test the
release provided they have access to the appropriate platform and tools.

<!-- END Official source code, please keep comment here to allow auto update of PyPI readme.md -->
## Convenience packages

There are other ways of installing and using Airflow. Those are "convenience" methods - they are
not "official releases" as stated by the `ASF Release Policy`, but they can be used by the users
who do not want to build the software themselves.

Those are - in the order of most common ways people install Airflow:

- [PyPI releases](https://pypi.org/project/apache-airflow/) to install Airflow using standard `pip` tool
- [Docker Images](https://hub.docker.com/r/apache/airflow) to install airflow via
  `docker` tool, use them in Kubernetes, Helm Charts, `docker-compose`, `docker swarm`, etc. You can
  read more about using, customizing, and extending the images in the
  [Latest docs](https://airflow.apache.org/docs/docker-stack/index.html), and
  learn details on the internals in the [images](https://airflow.apache.org/docs/docker-stack/index.html) document.
- [Tags in GitHub](https://github.com/apache/airflow/tags) to retrieve the git project sources that
  were used to generate official source packages via git

All those artifacts are not official releases, but they are prepared using officially released sources.
Some of those artifacts are "development" or "pre-release" ones, and they are clearly marked as such
following the ASF Policy.

## User Interface

- **Dags**: Overview of all Dags in your environment.

  ![Dags](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/dags.png)

- **Assets**: Overview of Assets with dependencies.

  ![Asset Dependencies](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/assets_graph.png)

- **Grid**: Grid representation of a Dag that spans across time.

  ![Grid](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/grid.png)

- **Graph**: Visualization of a Dag's dependencies and their current status for a specific run.

  ![Graph](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/graph.png)

- **Home**: Summary statistics of your Airflow environment.

  ![Home](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/home.png)

- **Backfill**: Backfilling a Dag for a specific date range.

  ![Backfill](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/backfill.png)

- **Code**: Quick way to view source code of a Dag.

  ![Code](https://raw.githubusercontent.com/apache/airflow/main/airflow-core/docs/img/ui-dark/code.png)

## Semantic versioning

Airflow, providers, the Helm Chart and the API clients each follow strict [SemVer](https://semver.org/)
independently: provider, chart and client versions are not tied to the Airflow version. See the
[release process](https://airflow.apache.org/docs/apache-airflow/stable/release-process.html) for details.

## Version Life Cycle

Apache Airflow version life cycle:

<!-- This table is automatically updated by prek scripts/ci/prek/supported_versions.py -->
<!-- Beginning of auto-generated table -->

| Version   | Current Patch/Minor   | State       | First Release   | Limited Maintenance   | EOL/Terminated   |
|-----------|-----------------------|-------------|-----------------|-----------------------|------------------|
| 3         | 3.3.2                 | Maintenance | Apr 22, 2025    | TBD                   | TBD              |
| 2         | 2.11.2                | EOL         | Dec 17, 2020    | Oct 22, 2025          | Apr 22, 2026     |
| 1.10      | 1.10.15               | EOL         | Aug 27, 2018    | Dec 17, 2020          | June 17, 2021    |
| 1.9       | 1.9.0                 | EOL         | Jan 03, 2018    | Aug 27, 2018          | Aug 27, 2018     |
| 1.8       | 1.8.2                 | EOL         | Mar 19, 2017    | Jan 03, 2018          | Jan 03, 2018     |
| 1.7       | 1.7.1.2               | EOL         | Mar 28, 2016    | Mar 19, 2017          | Mar 19, 2017     |

<!-- End of auto-generated table -->

Limited support versions get only security and critical bug fixes; EOL versions get no fixes.
We recommend running the latest minor release, and upgrading to the latest major release before EOL.

## Support for Python and Kubernetes versions

We drop Python and Kubernetes versions when they reach EOL (released in the next MINOR Airflow version),
and add new versions once they work in our CI. This policy is best-effort. See the
[Python](https://devguide.python.org/#status-of-python-branches) and
[Kubernetes](https://kubernetes.io/docs/setup/release/version-skew-policy/) release schedules.

## Base OS support for reference Airflow images

Reference container images are published with each release and are based on the current stable Debian,
switching to the newer Debian release about 6 months before the previous one leaves regular support. See the
[Docker stack docs](https://airflow.apache.org/docs/docker-stack/index.html) for building custom images.

## Approach to dependencies of Airflow

Airflow is installed reproducibly with `constraints`, but dependencies are not upper-bound by default.
Core dependencies (in `pyproject.toml`) that are known to break across versions - such as SQLAlchemy,
Alembic, Flask, werkzeug, celery and kubernetes - are upper-bound, with a comment explaining why.
Provider dependencies (in each `provider.yaml`) are not upper-bound unless the provider's maintainers
justify it. See [PROVIDERS.rst](https://github.com/apache/airflow/blob/main/PROVIDERS.rst).

<!-- START Contributing, please keep comment here to allow auto update of PyPI readme.md -->

## Contributing

Want to help build Apache Airflow? Check out our [contributors' guide](https://github.com/apache/airflow/blob/main/contributing-docs/README.rst) for a comprehensive overview of how to contribute, including setup instructions, coding standards, and pull request guidelines.

If you can't wait to contribute, and want to get started asap, check out the [contribution quickstart](https://github.com/apache/airflow/blob/main/contributing-docs/03a_contributors_quick_start_beginners.rst) here!

Official Docker (container) images for Apache Airflow are described in [images](https://github.com/apache/airflow/blob/main/dev/breeze/doc/ci/02_images.md).

<!-- END Contributing, please keep comment here to allow auto update of PyPI readme.md -->

## Community standards

Everyone interacting with the Apache Airflow project — on GitHub, the
mailing lists, Slack, the CWiki, or anywhere else — is expected to
follow the [Code of Conduct](CODE_OF_CONDUCT.md).

When repeated Code of Conduct breaches, spamming, abuse of project
resources, or other sustained disruptive behaviour cannot be resolved
through normal review and mentoring, the project applies the
[Community escalation process](COMMUNITY_ESCALATION.md). It describes
the steps maintainers and the PMC may take — from direct feedback,
through closing PRs, up to PMC-level or ASF-Infrastructure-level
blocks and reporting accounts to GitHub — and how affected
contributors can appeal a decision by emailing the PMC at
`private@airflow.apache.org`.

## Agent-assisted contribution (apache-magpie)

Maintainer PR-management skills come from the [`apache/magpie`](https://github.com/apache/magpie)
plugin, installed per-user in your agent harness (nothing to set up in the repo). In Claude Code:

```text
/plugin marketplace add apache/magpie
/plugin install magpie-pr-management@apache-magpie
```

The recommended set is in `.apache-magpie.lock`; Airflow-specific overrides live in
[`.apache-magpie-overrides/`](.apache-magpie-overrides/). Other harnesses are covered in the
[marketplace guide](https://github.com/apache/magpie/blob/main/docs/setup/marketplaces.md).

<!-- START Who uses Apache Airflow, please keep comment here to allow auto update of PyPI readme.md -->

## Voting Policy

* Commits need a +1 vote from a committer who is not the author
* When we do AIP voting, both PMC member's and committer's `+1s` are considered a binding vote.

## Who uses Apache Airflow?

We know about around 500 organizations that are using Apache Airflow (but there are likely many more)
[in the wild](https://github.com/apache/airflow/blob/main/INTHEWILD.md).

If you use Airflow - feel free to make a PR to add your organisation to the list.

<!-- END Who uses Apache Airflow, please keep comment here to allow auto update of PyPI readme.md -->
<!-- START Who maintains Apache Airflow, please keep comment here to allow auto update of PyPI readme.md -->

## Who maintains Apache Airflow?

Airflow is the work of the [community](https://github.com/apache/airflow/graphs/contributors),
but the [core committers/maintainers](https://people.apache.org/committers-by-project.html#airflow)
are responsible for reviewing and merging PRs as well as steering conversations around new feature requests.
If you would like to become a maintainer, please review the Apache Airflow
[committer requirements](https://github.com/apache/airflow/blob/main/COMMITTERS.rst#guidelines-to-become-an-airflow-committer).

<!-- END Who maintains Apache Airflow, please keep comment here to allow auto update of PyPI readme.md -->

## What goes into the next release?

PRs merged to `main` go into the next `MINOR` release. Bug-fix and doc-only PRs may also be cherry-picked
into the current `vX-Y-stable` branch for the next `PATCH` release when marked with that milestone - the
release manager makes the final call. Milestones on issues express intent, not a promise. See
[What goes into the next release](dev/WHAT_GOES_INTO_THE_NEXT_RELEASE.md) for details and an FAQ.

## Can I use the Apache Airflow logo in my presentation?

Yes! Be sure to abide by the Apache Foundation [trademark policies](https://www.apache.org/foundation/marks/#books) and the Apache Airflow [Brandbook](https://cwiki.apache.org/confluence/display/AIRFLOW/Brandbook). The most up-to-date logos are found in [this repo](https://github.com/apache/airflow/tree/main/airflow-core/docs/img/logos/) and on the Apache Software Foundation [website](https://www.apache.org/logos/about.html).

## Links

- [Documentation](https://airflow.apache.org/docs/apache-airflow/stable/)
- [Chat](https://s.apache.org/airflow-slack)
- [Community Information](https://airflow.apache.org/community/)

## Sponsors

The CI infrastructure for Apache Airflow has been sponsored by:

<!-- Ordered by most recently "funded" -->

<a href="https://astronomer.io"><img src="https://assets2.astronomer.io/logos/logoForLIGHTbackground.png" alt="astronomer.io" width="250px"></a>
<a href="https://aws.amazon.com/opensource/"><img src="https://github.com/apache/airflow/blob/main/providers/amazon/docs/integration-logos/AWS-Cloud-alt_light-bg@4x.png?raw=true" alt="AWS OpenSource" width="130px"></a>
