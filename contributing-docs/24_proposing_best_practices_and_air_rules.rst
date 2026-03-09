.. Licensed to the Apache Software Foundation (ASF) under one
   or more contributor license agreements.  See the NOTICE file
   distributed with this work for additional information
   regarding copyright ownership.  The ASF licenses this file
   to you under the Apache License, Version 2.0 (the
   "License"); you may not use this file except in compliance
   with the License.  You may obtain a copy of the License at

..   http://www.apache.org/licenses/LICENSE-2.0

.. Unless required by applicable law or agreed to in writing,
   software distributed under the License is distributed on an
   "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
   KIND, either express or implied.  See the License for the
   specific language governing permissions and limitations
   under the License.

Proposing Airflow Best Practices and Ruff AIR Rules
===================================================

This document explains how to propose a new Airflow best practice and, when appropriate, a matching Ruff
``AIR`` rule.

Not every best practice needs a linter rule, but for practices that can be checked automatically, ``AIR`` rules
help contributors and users detect issues early and keep code consistent.

Recommended process
-------------------

1. Start a devlist discussion and reach agreement through Lazy Consensus or a formal vote for the
   best-practice, migration, deprecation, or behavior you want to codify.
2. Once the decision is approved, open a PR and update Airflow documentation with the agreed guidance.
   Rule implementation work can proceed in parallel.
3. After the Ruff PR is merged, finalize documentation so it reflects the new ``AIR`` rule and includes
   usage or migration guidance where needed.

See also
--------

* `How to communicate <02_how_to_communicate.rst>`__
* `ASF Voting Process <https://www.apache.org/foundation/voting.html>`__
* `Pull Requests <05_pull_requests.rst>`__
