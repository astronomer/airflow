# SparkStandaloneExecutor — POC

Demonstrates the `SparkStandaloneExecutor`: an Airflow executor that submits
every task to a Spark Standalone cluster via the REST Submission API.

## The problem it solves

Today, running a task on Spark requires an explicit operator in every DAG:

```python
# Must change every DAG that needs Spark
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

transform = SparkSubmitOperator(task_id="transform", application="job.py", ...)
```

`SparkStandaloneExecutor` follows the same pattern as `KubernetesExecutor`:
**change the executor config once, no DAG changes needed.** Every task runs on
the Spark cluster. Tasks that call `SparkSession.builder.getOrCreate()` get a
live session for free — they are running inside a Spark driver process.

## Architecture

```
Scheduler
  └─► SparkStandaloneExecutor
        └─► POST /v1/submissions/create   (Spark REST API on port 6066)
              └─► Spark worker runs airflow_task_runner.py as driver
                    └─► SparkSession available natively
        └─► GET /v1/submissions/status/{id}  (polls until FINISHED/FAILED)
```

## Prerequisites

- Docker + Docker Compose
- Airflow with the `apache-airflow-providers-apache-spark` provider installed

## Quick start

### 1. Start the Spark cluster

```bash
cd dev/spark-standalone
docker compose up -d
```

Verify the cluster is up:
- Spark Master UI: http://localhost:8080
- REST API: `curl http://localhost:6066/v1/submissions/status/test` should return JSON

### 2. Configure Airflow

Add to `airflow.cfg`:

```ini
[core]
executor = airflow.providers.apache.spark.executors.spark_standalone_executor.SparkStandaloneExecutor

[spark_standalone_executor]
master_url            = spark://localhost:7077
rest_url              = http://localhost:6066/v1/submissions
task_runner_script    = file:///opt/airflow/scripts/airflow_task_runner.py
spark_version         = 3.5.0
driver_memory         = 512m
executor_memory       = 1g
executor_cores        = 1
startup_timeout       = 30
submission_timeout    = 30
```

### 3. Trigger the demo DAG

```bash
airflow dags trigger demo_spark_standalone_executor
```

Or through the Airflow UI.

## Per-task Spark resource overrides

Tasks can request additional resources via `executor_config`:

```python
@task(executor_config={"spark_properties": {"spark.executor.memory": "4g", "spark.executor.cores": "4"}})
def heavy_job():
    ...
```

## Limitations (POC scope)

| Limitation | Status |
|---|---|
| Full Airflow task SDK integration | TODO — stub in `airflow_task_runner.py`. Blocked on [AIP-72 token propagation](https://github.com/apache/airflow/issues/45107) |
| YARN / Kubernetes cluster managers | Not supported — use Livy or `SparkKubernetesExecutor` |
| Task log streaming from Spark UI | Not implemented |
| Callbacks (`on_failure_callback` etc.) | Not implemented |

## Running the tests

```bash
uv run --project providers/apache/spark pytest \
  providers/apache/spark/tests/unit/apache/spark/executors/test_spark_standalone_executor.py -xvs
```
