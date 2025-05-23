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

Rust SDK Plan
=============

This document proposes a plan for creating a Rust implementation of the
Airflow Task SDK.  It follows the general approach of the Go SDK that was
introduced in PR `#50964 <https://github.com/apache/airflow/pull/50964>`_.

Overview
--------

The Rust SDK aims to:

* Let developers author Airflow tasks in Rust.
* Reuse the Task Execution API and concepts shared by the Python and Go SDKs.
* Integrate with Celery-based executors via
  `rusty-celery <https://github.com/rusty-celery/rusty-celery>`_.

Architecture
------------

1. **Message types** – Provide Rust ``struct`` definitions mirroring the
   protocol used by other SDKs.  Serialization should use ``serde`` for
   compatibility with JSON payloads.
2. **Worker runner** – Offer a binary that subscribes to Airflow's task queue
   (using ``rusty-celery``) and executes Rust functions.
3. **Context helpers** – Implement utilities similar to ``TaskContext`` from the
   Go SDK, allowing tasks to access params, XComs and logging facilities.
4. **Testing utilities** – Supply mocks and helper functions to facilitate unit
   testing of Rust tasks without requiring a running Airflow instance.

Milestones
----------

#. Bootstrap an ``airflow-task-sdk-rust`` crate with CI and formatting tools.
#. Implement the core message types and a minimal worker capable of running a
   single task.
#. Provide example DAGs and documentation showing how the Rust worker can run
   alongside Airflow.
#. Document packaging and release steps for publishing the crate to crates.io.
#. Expand functionality to reach parity with the Go SDK.

Documentation
-------------

Detailed user guides will be placed under ``task-sdk/docs`` once the SDK
stabilises. They should cover installation, configuration and common patterns for
writing tasks in Rust.  The documentation build process (``breeze build-docs``)
will include the Rust SDK docs so they are published together with the rest of
Airflow's documentation.
