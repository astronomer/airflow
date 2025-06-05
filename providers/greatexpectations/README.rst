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

Great Expectations Provider
==========================

This provider package contains operators, hooks, and sensors for integrating Great Expectations with Apache Airflow.

Installation
-----------

You can install this package via pip:

.. code-block:: bash

    pip install apache-airflow-providers-greatexpectations

Requirements
-----------

* Apache Airflow >= 2.7.0
* Great Expectations >= 0.18.0

Features
--------

* Run Great Expectations checkpoints as Airflow tasks
* Monitor validation runs with sensors
* Integrate with existing Great Expectations projects

Modules
-------

* :doc:`operators/greatexpectations`
* :doc:`hooks/greatexpectations`
* :doc:`sensors/greatexpectations`

Example
-------

Here's a simple example of how to use the Great Expectations operator in your DAG:

.. code-block:: python

    from airflow import DAG
    from airflow.providers.greatexpectations.operators.greatexpectations import GreatExpectationsOperator
    from datetime import datetime, timedelta

    with DAG(
        "example_greatexpectations",
        schedule=timedelta(days=1),
        start_date=datetime(2024, 1, 1),
    ) as dag:
        run_checkpoint = GreatExpectationsOperator(
            task_id="run_checkpoint",
            checkpoint_name="my_checkpoint",
            context_root_dir="/path/to/great_expectations",
            run_name="daily_validation_{{ ds_nodash }}",
        )

Configuration
------------

The provider requires a Great Expectations project to be set up. You can configure the following:

* ``context_root_dir``: The root directory of your Great Expectations project
* ``checkpoint_name``: The name of the checkpoint to run
* ``run_name``: Optional name for the checkpoint run
* ``fail_task_on_validation_failure``: Whether to fail the task if validation fails (default: True)

For more information, see the `Great Expectations documentation <https://docs.greatexpectations.io/>`_.
