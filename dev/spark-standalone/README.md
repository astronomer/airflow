# SparkStandaloneExecutor

> **TL;DR** — `KubernetesExecutor` lets you run any Airflow task on Kubernetes without touching your DAGs. This is the same thing for Spark Standalone clusters.

---

## Who This Is For

**Spark shops** — organisations whose data platform runs on a Spark Standalone cluster (on-premises hardware, bare-metal cloud, or a managed Spark service without Kubernetes). This includes:

- Firms running multi-petabyte Spark deployments on-prem, where Kubernetes is not available or not approved.
- Teams that evaluated `KubernetesExecutor` but cannot adopt it because their compute is Spark, not Kubernetes.
- Data engineering teams that want to use Airflow for orchestration but cannot accept the per-task boilerplate that `SparkSubmitOperator` requires.

---

## The Gap

Spark is one of the most widely deployed distributed compute engines in the world, and Airflow is one of the most widely deployed orchestrators. Yet there is no first-class way to run Airflow tasks *on* a Spark cluster.

The only option today is `SparkSubmitOperator`: a task-level operator that submits a standalone Python application file to Spark. It works, but it forces every team to make a choice at DAG-authoring time — "does this task run on Spark or not?" — and to maintain a separate application file for every Spark task. If you want a `SparkSession` inside a task, you cannot write a regular `@task` function; you must restructure the entire task as a Spark application.

Compare this to Kubernetes. Before `KubernetesExecutor` existed, the only option was `KubernetesPodOperator` — one operator per task, with image names and resource requests baked into DAG code. Then `KubernetesExecutor` arrived and made the entire question disappear at the DAG level: configure the executor once, and every task runs in a pod. DAG authors write normal Python.

**Spark has never had its `KubernetesExecutor` moment (yet). This POC is that moment.**

---

## The Problem in Code

Running Airflow tasks on Spark today requires every DAG author to explicitly wrap their logic in a Spark operator:

```python
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

transform = SparkSubmitOperator(
    task_id="transform",
    application="/opt/jobs/transform.py",   # ← separate file which is deployed to the spark cluster
    conn_id="spark_default",
    executor_memory="4g",
    num_executors=10,
    ...
)
```

Every task that needs Spark requires:
1. A separate `.py` application file maintained alongside the DAG
2. An explicit `SparkSubmitOperator` (or `SparkKubernetesOperator`) in the DAG
3. A Spark connection configured by the platform team
4. Knowledge of Spark submit parameters baked into the DAG

This means moving a pipeline to Spark is a DAG rewrite, not a config change.

---

## The Solution

`SparkStandaloneExecutor` solves this the same way `KubernetesExecutor` solved it for Kubernetes: **configure the executor once, and every task runs on Spark transparently.**

```ini
# airflow.cfg — one change, affects all DAGs
[core]
executor = airflow.providers.apache.spark.executors.spark_standalone_executor.SparkStandaloneExecutor
```

From that point on, a completely ordinary `@task` function gets a live `SparkSession` for free:

```python
@task
def heavy_transform(rows: int) -> int:
    from pyspark.sql import SparkSession          # ← just works
    spark = SparkSession.builder.getOrCreate()    # ← returns the driver's session
    return spark.range(rows).selectExpr("sum(id) as s").collect()[0]["s"]
```

No `SparkSubmitOperator`. No standalone application file. No Spark connection configuration per task. The task author writes normal Python; the executor takes care of everything else.

---

## How It Works

```
Airflow Scheduler
  └─► SparkStandaloneExecutor._process_workloads()
        │
        │  POST /v1/submissions/create
        │  payload: { appResource: airflow-driver-launcher.jar,
        │             mainClass:   AirflowDriverLauncher,
        │             environmentVariables: { AIRFLOW_EXECUTE_WORKLOAD: <json> } }
        ▼
      Spark Master (REST API, port 6066)
        └─► Spark Worker spawns driver JVM process
              └─► AirflowDriverLauncher.main()
                    └─► python3 airflow_task_runner.py
                          └─► airflow.sdk.execution_time.execute_workload
                                ├─► SparkSession.builder.getOrCreate()  ← live session
                                └─► communicates back to Airflow via Execution API

  SparkStandaloneExecutor.sync()
    └─► GET /v1/submissions/status/{id}
          └─► driverState: FINISHED → task success
              driverState: FAILED   → task failure
```

### Why a JVM shim?

Spark Standalone cluster mode does not support Python as a primary `appResource`
(`spark-submit --deploy-mode cluster script.py` explicitly fails with
*"Cluster deploy mode is currently not supported for python applications on standalone clusters"*).

The `AirflowDriverLauncher` JAR is a minimal Java class that is submitted as the real
`appResource`. Its only job is to read `AIRFLOW_TASK_RUNNER_SCRIPT` from the environment and
spawn `python3 <script>` as a subprocess with all environment variables inherited. This lets
us pass the full serialised `ExecuteTask` workload through `AIRFLOW_EXECUTE_WORKLOAD` and
have the Python task runner execute it on the Spark worker exactly as `KubernetesExecutor`
does inside a Pod.

---

## SparkSubmitOperator vs SparkStandaloneExecutor

| | `SparkSubmitOperator` | `SparkStandaloneExecutor` |
|---|---|---|
| **Change needed per DAG** | Yes — replace every task with a Spark operator | No — configure executor once |
| **Task author needs to know about Spark** | Yes — must write standalone `.py` app file | No — regular `@task` function |
| **`SparkSession` availability** | Inside the submitted application | Inside every task automatically |
| **Non-Spark tasks** | Run on regular workers; only Spark tasks use Spark | All tasks run on Spark cluster |
| **Resource overrides** | Per-task `num_executors`, `executor_memory`, etc. | Per-task via `executor_config={"spark_properties": {...}}` |
| **XCom, callbacks, retries** | Partial — Airflow wraps the submitted job | Full — runs through the Airflow Task SDK |
| **Analogue** | `KubernetesPodOperator` | `KubernetesExecutor` |

---

## What Is Now Possible

**Before** (without this executor):

- A data engineer who wants `SparkSession` must restructure their task as a standalone Spark application, add a `SparkSubmitOperator` to the DAG, configure a Spark connection, and maintain a separate Python file deployed to the cluster.
- Moving an existing pipeline to Spark requires rewriting every affected task.
- You cannot mix "this task uses Spark" and "this task does not" without explicit operator choices in the DAG.

**After** (with `SparkStandaloneExecutor`):

- Any `@task` function can call `SparkSession.builder.getOrCreate()` and receive a real, distributed session on the Spark cluster.
- Existing DAGs that do not use Spark still run correctly — they simply run as driver processes without requesting a session.
- Infra teams can move an entire Airflow deployment onto Spark by changing one line in `airflow.cfg`.
- Resource allocation (`spark.driver.memory`, `spark.executor.cores`, etc.) is managed centrally with optional per-task overrides.
- Task logs are written to S3-compatible storage (MinIO in the POC) and are readable in the Airflow UI without any additional infrastructure.

---

## Who / What This Unblocks

**For Airflow users:**
Organisations running Spark Standalone on-prem can now adopt Airflow as their orchestrator without being forced onto Kubernetes and without restructuring every DAG. Data engineers and scientists write plain Python tasks; the platform team configures the executor once.

**For Airflow the project:**
This is a direct proof-of-concept for AIP-72 (task execution on arbitrary compute). The task runner uses the same `execute_workload` entry point as `KubernetesExecutor`, which means full token propagation, heartbeats, and XCom over the Execution API all work without any changes. Adding Spark Standalone support to Airflow now costs one executor class and a thin JVM shim.

**As a template:**
The submission pattern — `POST to REST API → poll status → propagate env vars` — is the same pattern used by Livy, YARN, and the Databricks Jobs API. A `LivyExecutor` or `DatabricksExecutor` following this POC would require only a different REST client, not a new architecture.

---

## Running the POC

### Prerequisites

- Docker + Docker Compose
- The Airflow repo checked out and Breeze available (`uv tool install breeze` or `pip install apache-airflow-breeze`)

### 1 — Start the Spark cluster and MinIO

```bash
cd dev/spark-standalone
docker compose up --build -d
docker compose run --rm minio-init   # creates the airflow-logs bucket
```

Services started:

| Service | URL | Purpose |
|---------|-----|---------|
| Spark Master | http://localhost:8080 | Spark cluster UI |
| Spark REST API | http://localhost:6066 | Task submission endpoint |
| MinIO S3 API | http://localhost:9000 | Remote log storage |
| MinIO Console | http://localhost:9001 | Browse buckets / logs (admin: `minioadmin`) |

### 2 — Start Airflow (Breeze)

`files/airflow-breeze-config/spark-standalone.sh` is sourced automatically by Breeze on startup
and sets all required env vars. Just start Breeze normally:

```bash
breeze start-airflow --backend postgres --db-reset
```

Breeze connects to the Spark cluster and MinIO via `host.docker.internal` (the Docker host).

### 3 — Trigger the demo DAG

Open the Airflow UI at http://localhost:28080, find the `demo_spark_standalone_executor` DAG
(tagged `spark`, `poc`), and trigger it manually.

The DAG has three tasks that run in sequence:

```
ingest  →  heavy_transform  →  publish
```

- `ingest`: lightweight ingestion step; demonstrates a task running on Spark without needing a session.
- `heavy_transform`: calls `SparkSession.builder.getOrCreate()` and runs a distributed sum over 1 million rows.
- `publish`: lightweight publish step with no Spark dependency.

### 4 — Watch task execution on Spark

While the DAG runs, open http://localhost:8080 to see the Spark Master UI. Each Airflow task appears as a running application (`airflow-<dag>-<task>-<run_id>`).

### 5 — View task logs in the Airflow UI

Click any completed task instance → **Logs**. Logs are fetched from MinIO (`s3://airflow-logs/`) — no `serve-logs` daemon required on the Spark workers.

To browse the raw log files: open the MinIO console at http://localhost:9001 → `airflow-logs` bucket.

---

## Per-task Resource Overrides

```python
@task(executor_config={
    "spark_properties": {
        "spark.driver.memory":    "2g",
        "spark.executor.memory":  "4g",
        "spark.executor.cores":   "4",
    }
})
def heavy_job():
    ...
```

Any `spark.*` property accepted by the REST Submission API can be set here.

---

## Configuration Reference

All settings live under `[spark_standalone_executor]` in `airflow.cfg` (or as env vars with the `AIRFLOW__SPARK_STANDALONE_EXECUTOR__` prefix).

| Key | Default | Description |
|-----|---------|-------------|
| `master_url` | `spark://localhost:7077` | Spark master URL passed inside submitted jobs |
| `rest_url` | `http://localhost:6066/v1/submissions` | Base URL of the REST Submission API |
| `task_runner_script` | `/opt/airflow/scripts/airflow_task_runner.py` | Path to the Python entry point on workers |
| `driver_launcher_jar` | `file:///opt/airflow/jars/airflow-driver-launcher.jar` | Path to the JVM shim JAR on workers |
| `spark_version` | `3.5.0` | Version reported to the REST API (must match cluster) |
| `driver_memory` | `512m` | Default driver memory |
| `executor_memory` | `1g` | Default executor memory |
| `executor_cores` | `1` | Default executor cores |
| `startup_timeout` | `30` | Seconds to wait for REST API during `start()` |
| `submission_timeout` | `30` | Seconds to wait per submission request |

---

## Repo Layout

```
dev/spark-standalone/
├── Dockerfile                     # Spark worker image: spark:python3 + task-sdk + providers-amazon
├── docker-compose.yml             # Spark master, 2 workers, MinIO, minio-init
├── AirflowDriverLauncher.java     # JVM shim: submits as appResource, spawns python3
├── scripts/
│   └── airflow_task_runner.py     # Python entry point run inside the Spark driver
├── dags/
│   └── demo_spark_standalone_executor.py   # Demo DAG (also in files/test_dags/)
└── env.sh                         # Convenience env vars for running Airflow on the host (non-Breeze)

files/airflow-breeze-config/
└── spark-standalone.sh            # Sourced by init.sh; configures all Airflow env vars for Breeze

providers/apache/spark/src/airflow/providers/apache/spark/executors/
└── spark_standalone_executor.py   # The executor implementation

providers/apache/spark/tests/unit/apache/spark/executors/
└── test_spark_standalone_executor.py   # Unit tests (15 tests, all passing)
```

---

## Running the Tests

```bash
uv run --project providers/apache/spark \
  pytest providers/apache/spark/tests/unit/apache/spark/executors/test_spark_standalone_executor.py -xvs
```

---

## Known Limitations (POC scope)

| Limitation | Notes |
|---|---|
| YARN / Kubernetes Spark cluster managers | Not supported. Use `SparkKubernetesOperator` or Livy for those. |
| `spark:python3` image is Spark 4.0 | The official `spark:python3` image ships Spark 4.0. Set `spark_version = 4.0.1` in config. |
| All tasks run on Spark | There is no per-task opt-out in this POC. A production implementation could check `executor_config` for an opt-out flag. |
| Task timeouts | Submission timeout is configurable; driver-level task timeouts are not yet wired. |
